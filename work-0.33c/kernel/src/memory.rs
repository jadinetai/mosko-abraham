//! Kernel side of frame ownership (ABRAHAM 0.31a, F-029-01, D-ABR-009..012).
//!
//! - The one global `FrameAllocator`, built from the Limine memory map plus the ledger
//!   (LOW_1MIB, KERNEL_IMAGE, MMIO) before any page table is created.
//! - Page-table frames come from it and are pinned (`alloc_page_table`).
//! - Every allocation is guarded: a candidate that is a live page table (from the last walk),
//!   inside the kernel image or the APIC page is an ownership collision. The allocator latches
//!   FAULTED and the kernel stops (D-ABR-012). So does a double release.
//! - `check` walks the live page tables and proves ownership on the running kernel. Any
//!   violation stops the boot (STOP condition, handoff F-029-01), unless the DIAGNOSTIC
//!   feature `diag-memcheck-nonfatal` asks for report-only.
//!
//! Every code printed here is registered in docs/KERNEL_DIAGNOSTICS.md (D-ABR-010..012).

use crate::events::Kind as EventKind;
use crate::frame::{Frame, FrameAllocator, FrameError, Kind, Owner, PinOwner, Region, Reservation, State, PAGE};
use crate::{cpu, eventlog, fault, kprintln, limine, ptwalk};
use core::cell::UnsafeCell;
use core::ptr;
use core::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};

/// 16,384 words x 64 frames x 4 KiB = 4 GiB of physical address space managed.
pub const WORDS: usize = 16384;
const LOW_1MIB: u64 = 0x10_0000;
const IA32_APIC_BASE: u32 = 0x1B;
const ADDRESS: u64 = 0x000f_ffff_ffff_f000;
/// Live page-table frames remembered from the last walk (for the allocation guard).
const LIVE_CAP: usize = 64;
const REPORT_CAP: u32 = 16;

unsafe extern "C" {
    static __abr_kernel_start: u8;
    static __abr_kernel_end: u8;
}

struct Global {
    busy: AtomicBool,
    allocator: UnsafeCell<FrameAllocator<WORDS>>,
    live: UnsafeCell<[u64; LIVE_CAP]>,
}

// SAFETY: single CPU; `busy` gives exclusive access to the cells; no interrupt handler
// touches them (trap handlers only count ticks and send EOI).
unsafe impl Sync for Global {}

static GLOBAL: Global = Global {
    busy: AtomicBool::new(false),
    allocator: UnsafeCell::new(FrameAllocator::new()),
    live: UnsafeCell::new([0; LIVE_CAP]),
};
static LIVE_COUNT: AtomicUsize = AtomicUsize::new(0);
static KERNEL_PHYS: AtomicU64 = AtomicU64::new(0);
static KERNEL_VIRT: AtomicU64 = AtomicU64::new(0);
static KERNEL_BYTES: AtomicU64 = AtomicU64::new(0);
static APIC_PAGE: AtomicU64 = AtomicU64::new(0);
static HHDM: AtomicU64 = AtomicU64::new(0);

/// Exclusive access to the allocator and the live list. Refuses re-entry instead of waiting.
fn with<R>(f: impl FnOnce(&mut FrameAllocator<WORDS>, &mut [u64; LIVE_CAP]) -> R) -> Result<R, FrameError> {
    if GLOBAL.busy.swap(true, Ordering::Acquire) {
        return Err(FrameError::Busy);
    }
    // SAFETY: `busy` was false and is now ours: nothing else holds these references.
    let r = unsafe { f(&mut *GLOBAL.allocator.get(), &mut *GLOBAL.live.get()) };
    GLOBAL.busy.store(false, Ordering::Release);
    Ok(r)
}

fn kernel_extent() -> (u64, u64) {
    let start = &raw const __abr_kernel_start as u64;
    let end = &raw const __abr_kernel_end as u64;
    (start, end - start)
}

fn page_round_up(x: u64) -> u64 {
    (x + PAGE - 1) & !(PAGE - 1)
}

/// True if `phys` is a frame the kernel knows is live outside the allocator's records.
fn is_live(phys: u64, live: &[u64]) -> bool {
    let kp = KERNEL_PHYS.load(Ordering::Relaxed);
    let kb = page_round_up(KERNEL_BYTES.load(Ordering::Relaxed));
    (phys >= kp && phys < kp.saturating_add(kb)) || phys == APIC_PAGE.load(Ordering::Relaxed) || live.contains(&phys)
}

fn unavailable(detail: &str) -> ! {
    fault::stop("FRAME_ALLOCATOR_UNAVAILABLE", 0, format_args!("reason=FRAME_ALLOCATOR_UNAVAILABLE|detail={}", detail));
}

/// The memory map as both the allocator and the ownership check see it (one source for both).
/// In the DIAGNOSTIC build `diag-map-overlap` a copy of the largest USABLE entry is appended, so
/// the map contains a duplicate, overlapping USABLE entry (Echo F-031a-E04).
fn regions() -> impl Iterator<Item = Region> + Clone {
    let map = limine::memory_map();
    map.iter().map(|e| Region { base: e.base, length: e.length, kind: Kind::from_limine(e.kind) }).chain(diag_overlap_entry())
}

#[cfg(feature = "diag-map-overlap")]
fn diag_overlap_entry() -> Option<Region> {
    limine::memory_map().iter().filter(|e| e.kind == limine::MEMMAP_USABLE).max_by_key(|e| e.length)
        .map(|e| Region { base: e.base, length: e.length, kind: Kind::Usable })
}

#[cfg(not(feature = "diag-map-overlap"))]
fn diag_overlap_entry() -> Option<Region> {
    None
}

fn usable_ranges() -> impl Iterator<Item = (u64, u64)> + Clone {
    regions().filter(|r| r.kind == Kind::Usable).map(|r| (r.base, r.base.saturating_add(r.length)))
}

/// Build the allocator from the memory map and the ledger, print the ownership report.
/// Any failure stops the boot: no OPERATIONAL without a memory owner.
pub fn init() {
    let Some(hhdm) = limine::hhdm_offset() else { unavailable("NO_HHDM") };
    let Some((kphys, kvirt)) = limine::executable_address() else { unavailable("NO_EXECUTABLE_ADDRESS") };
    let (kstart, kbytes) = kernel_extent();
    if kstart != kvirt {
        unavailable("KERNEL_VIRTUAL_BASE_MISMATCH");
    }
    HHDM.store(hhdm, Ordering::Relaxed);
    KERNEL_PHYS.store(kphys, Ordering::Relaxed);
    KERNEL_VIRT.store(kvirt, Ordering::Relaxed);
    KERNEL_BYTES.store(kbytes, Ordering::Relaxed);
    let apic = cpu::read_msr(IA32_APIC_BASE) & ADDRESS;
    APIC_PAGE.store(apic, Ordering::Relaxed);

    let map = limine::memory_map();
    for (i, e) in map.iter().enumerate() {
        kprintln!("ABR|MEMMAP|i={}|base={:#x}|length={:#x}|type={}", i, e.base, e.length, limine::memmap_type_name(e.kind));
    }
    if let Some(d) = diag_overlap_entry() {
        kprintln!("ABR|DIAG|injecting=map_overlap|i={}|base={:#x}|length={:#x}|type=USABLE|duplicate_of_largest_usable=true",
                  map.len(), d.base, d.length);
    }
    let regions = regions();
    let ledger = [
        Reservation { base: 0, length: LOW_1MIB, owner: Owner::Low1Mib },
        Reservation { base: kphys, length: page_round_up(kbytes), owner: Owner::KernelImage },
        Reservation { base: apic, length: PAGE, owner: Owner::Mmio },
    ];
    let outcome = with(|a, _| {
        let state = a.init(regions, &ledger);
        for (base, length, owner, removed) in a.ledger() {
            kprintln!("ABR|MEMLEDGER|owner={}|base={:#x}|length={:#x}|pool_frames_removed={}", owner, base, length, removed);
        }
        for (entry, anomaly) in a.anomalies() {
            kprintln!("ABR|MEM|anomaly|entry={}|code={}", entry, anomaly.code());
        }
        let s = a.stats();
        kprintln!(
            "ABR|MEM|state={}|managed_limit={:#x}|pool_frames={}|free_frames={}|usable_bytes={}|unmanaged_usable_bytes={}\
             |removed_by_map={}|removed_by_ledger={}|anomalies={}|kernel_phys={:#x}|kernel_bytes={:#x}|apic_page={:#x}",
            a.state().name(), FrameAllocator::<WORDS>::limit(), s.pool_frames_initial, s.free_frames,
            s.usable_bytes_reported, s.unmanaged_usable_bytes, s.removed_by_map, s.removed_by_ledger, s.anomalies,
            kphys, kbytes, apic
        );
        (state, s.pool_frames_initial)
    });
    let outcome = outcome.map(|(state, pool)| {
        if state == Ok(State::Ready) {
            eventlog::record(EventKind::Memory, "ALLOCATOR_READY", pool);
        }
        state
    });
    match outcome {
        Ok(Ok(State::Ready)) => {}
        Ok(Ok(state)) => unavailable(state.name()),
        Ok(Err(e)) | Err(e) => unavailable(e.code()),
    }
}

/// A serious allocator violation (D-ABR-012): report everything that shows the allocator did
/// not continue, then stop the kernel. Never returns.
fn serious(e: FrameError, frame: u64) -> ! {
    let hhdm = HHDM.load(Ordering::Relaxed);
    // The guard is held by nobody here: callers drop it before calling.
    let _ = with(|a, _| {
        let s = a.stats();
        let probe = match a.alloc() {
            Ok(_) => "HANDED_OUT", // must never happen once FAULTED
            Err(x) => x.code(),
        };
        kprintln!(
            "ABR|MEM|serious|code={}|frame={:#x}|state={}|free_frames={}|free_bitmap={}|frame_free={}|frame_in_pool={}\
             |quarantined={}|alloc_after={}",
            e.code(), frame, a.state().name(), s.free_frames, a.free_frames_total(), a.is_free(frame),
            a.in_pool(frame), s.quarantined, probe
        );
    });
    if e == FrameError::OwnershipCollision {
        // The colliding frame was never handed out: show the live mapping still works.
        let apic = APIC_PAGE.load(Ordering::Relaxed);
        let translated = ptwalk::translate(hhdm, hhdm + apic);
        kprintln!("ABR|MEM|serious|apic_virtual={:#x}|translates_to={:#x}|apic_mapping_intact={}",
                  hhdm + apic, translated.unwrap_or(0), translated == Some(apic));
    }
    fault::stop(e.code(), frame, format_args!("reason={}|source=ALLOCATOR|frame={:#x}", e.code(), frame));
}

/// One frame, guarded against collisions, contents untouched. Serious violations stop here.
pub fn alloc_frame() -> Result<Frame, FrameError> {
    let r = with(|a, live| {
        let n = LIVE_COUNT.load(Ordering::Relaxed);
        let r = a.alloc_checked(|p| is_live(p, &live[..n]));
        (r, a.fault())
    })?;
    match r {
        (Ok(f), _) => Ok(f),
        (Err(FrameError::OwnershipCollision), Some((_, frame))) => serious(FrameError::OwnershipCollision, frame),
        (Err(e), _) => Err(e),
    }
}

/// A zeroed frame, pinned for good as a page table. Returns its physical address.
pub fn alloc_page_table() -> Result<u64, FrameError> {
    let f = alloc_frame()?;
    let hhdm = HHDM.load(Ordering::Relaxed);
    // SAFETY: the frame is ours (just allocated), USABLE and therefore HHDM-mapped.
    unsafe { ptr::write_bytes((hhdm + f.phys()) as *mut u8, 0, PAGE as usize) };
    with(|a, _| a.pin(f, PinOwner::PageTable))?
}

/// Release by address (DIAGNOSTIC paths only in 0.31a: the default kernel never releases).
/// A refused release returns its code; a double release stops the kernel (D-ABR-012).
#[allow(dead_code)]
pub fn release_raw(phys: u64) -> Result<(), FrameError> {
    let r = with(|a, _| a.release_raw(phys))?;
    match r {
        Err(FrameError::DoubleRelease) => serious(FrameError::DoubleRelease, phys),
        Ok(()) => {
            // Poison the freed frame so a stale user reads garbage, not old data.
            let hhdm = HHDM.load(Ordering::Relaxed);
            // SAFETY: the frame is free and owned by the allocator; nothing else may use it.
            unsafe { ptr::write_bytes((hhdm + phys) as *mut u8, 0xA5, PAGE as usize) };
            Ok(())
        }
        other => other,
    }
}

/// Allocator counters for diagnostics.
#[allow(dead_code)]
pub fn stats() -> Option<crate::frame::Stats> {
    with(|a, _| a.stats()).ok()
}

/// Physical [base, base + bytes) of the kernel image and the APIC page.
#[allow(dead_code)]
pub fn kernel_and_apic() -> (u64, u64, u64) {
    (KERNEL_PHYS.load(Ordering::Relaxed), KERNEL_BYTES.load(Ordering::Relaxed), APIC_PAGE.load(Ordering::Relaxed))
}

/// Live page-table frames from the last check (copy).
#[allow(dead_code)]
pub fn live_tables(out: &mut [u64; LIVE_CAP]) -> usize {
    with(|_, live| {
        *out = *live;
        LIVE_COUNT.load(Ordering::Relaxed)
    })
    .unwrap_or(0)
}

#[allow(dead_code)]
pub fn hhdm() -> u64 {
    HHDM.load(Ordering::Relaxed)
}

struct Violations {
    count: u32,
    collision_class: bool,
}

impl Violations {
    fn add(&mut self, stage: &str, code: &str, frame: u64, collision: bool) {
        if self.count < REPORT_CAP {
            kprintln!("ABR|MEMCHECK|stage={}|violation={}|frame={:#x}", stage, code, frame);
        }
        self.count += 1;
        self.collision_class |= collision;
    }
}

fn in_bootloader_reclaimable(frame: u64) -> bool {
    limine::memory_map().iter().any(|e| {
        e.kind == limine::MEMMAP_BOOTLOADER_RECLAIMABLE && frame >= e.base && frame - e.base < e.length
    })
}

/// Prove frame ownership on the running kernel (see module comment). Returns true on PASS.
pub fn check(stage: &str) -> bool {
    let hhdm = HHDM.load(Ordering::Relaxed);
    let (kvirt, kbytes) = (KERNEL_VIRT.load(Ordering::Relaxed), KERNEL_BYTES.load(Ordering::Relaxed));
    let kphys = KERNEL_PHYS.load(Ordering::Relaxed);
    let apic = APIC_PAGE.load(Ordering::Relaxed);
    let outcome = with(|a, live| {
        let mut v = Violations { count: 0, collision_class: false };
        let (mut n_live, mut overflow, mut in_bootloader, mut pinned) = (0usize, false, 0u64, 0u64);
        let walk = ptwalk::walk(hhdm, |_level, f| {
            if n_live < LIVE_CAP {
                live[n_live] = f;
                n_live += 1;
            } else {
                overflow = true;
            }
            if a.is_free(f) {
                v.add(stage, "PT_FRAME_FREE", f, true);
            } else if in_bootloader_reclaimable(f) {
                in_bootloader += 1;
            } else if a.pinned().contains(&f) {
                pinned += 1;
            } else {
                v.add(stage, "PT_FRAME_UNACCOUNTED", f, true);
            }
        });
        LIVE_COUNT.store(n_live, Ordering::Relaxed);
        if overflow {
            v.add(stage, "LIVE_TABLE_LIST_OVERFLOW", 0, false);
        }
        let mut kernel_pages = 0u64;
        let mut offset = 0;
        while offset < kbytes {
            match ptwalk::translate(hhdm, kvirt + offset) {
                None => v.add(stage, "KERNEL_PAGE_UNMAPPED", kvirt + offset, false),
                Some(p) => {
                    let p = p & !(PAGE - 1);
                    if p != kphys + offset {
                        v.add(stage, "KERNEL_NOT_CONTIGUOUS", p, false);
                    }
                    if a.in_pool(p) {
                        v.add(stage, "KERNEL_FRAME_IN_POOL", p, true);
                    }
                }
            }
            kernel_pages += 1;
            offset += PAGE;
        }
        if a.in_pool(apic) {
            v.add(stage, "MMIO_FRAME_IN_POOL", apic, true);
        }
        if a.in_pool(0) {
            v.add(stage, "FRAME0_IN_POOL", 0, true);
        }
        // 0.31b (F-031a-E04): count pool frames outside every USABLE range directly. 0.31a summed
        // per-entry counts and subtracted, which double-counts overlapping entries and underflows.
        let outside = a.pool_frames_outside(usable_ranges());
        if outside != 0 {
            v.add(stage, "POOL_OUTSIDE_USABLE", outside, true);
        }
        if a.free_outside_pool() != 0 {
            v.add(stage, "FREE_OUTSIDE_POOL", a.free_outside_pool(), false);
        }
        let s = a.stats();
        if a.free_frames_total() != s.free_frames {
            v.add(stage, "FREE_COUNT_MISMATCH", a.free_frames_total(), false);
        }
        if a.pin_log_overflowed() {
            v.add(stage, "PIN_LOG_OVERFLOW", s.pinned, false);
        }
        if a.state() == State::Faulted {
            v.add(stage, "ALLOCATOR_FAULTED", a.fault().map(|(_, f)| f).unwrap_or(0), false);
        }
        for &f in a.pinned() {
            kprintln!("ABR|MEMPIN|stage={}|frame={:#x}|owner=PAGE_TABLE|in_pool={}|free={}", stage, f, a.in_pool(f), a.is_free(f));
        }
        kprintln!(
            "ABR|MEMCHECK|stage={}|pt_tables={}|pt_in_bootloader={}|pt_pinned={}|kernel_pages={}|pool_frames={}\
             |free_frames={}|pinned={}|violations={}|result={}",
            stage, walk.tables, in_bootloader, pinned, kernel_pages, a.pool_frames_total(), s.free_frames, s.pinned,
            v.count, if v.count == 0 { "PASS" } else { "FAIL" }
        );
        v
    });
    let v = match outcome {
        Ok(v) => v,
        Err(e) => {
            kprintln!("ABR|MEMCHECK|stage={}|violation=CHECK_NOT_RUN|detail={}|result=FAIL", stage, e.code());
            Violations { count: 1, collision_class: false }
        }
    };
    if v.count == 0 {
        eventlog::record(EventKind::Memory, "MEMCHECK_PASS", stage_id(stage));
        return true;
    }
    eventlog::record(EventKind::Memory, "MEMCHECK_FAIL", v.count as u64);
    let reason = if v.collision_class { "FRAME_OWNERSHIP_COLLISION" } else { "FRAME_OWNERSHIP_CHECK_FAILED" };
    if cfg!(feature = "diag-memcheck-nonfatal") {
        kprintln!("ABR|DIAG|memcheck_nonfatal|stage={}|would_fault={}|continuing=DIAGNOSTIC_ONLY", stage, reason);
        return false;
    }
    fault::stop(reason, v.count as u64,
                format_args!("reason={}|source=MEMCHECK|stage={}|violations={}", reason, stage, v.count));
}

/// Event argument for a check stage: 1 init, 2 timer, 3 after_exhaust, 4 after_release.
fn stage_id(stage: &str) -> u64 {
    match stage {
        "init" => 1,
        "timer" => 2,
        "after_exhaust" => 3,
        "after_release" => 4,
        _ => 0,
    }
}
