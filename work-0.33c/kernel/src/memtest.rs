//! 0.31a VM test (feature `diag-mem-exhaust`, DIAGNOSTIC build, never an accepted kernel).
//!
//! On the running kernel, before OPERATIONAL:
//!  1. refused releases: misaligned, out of range, frame 0, APIC page, kernel image, every live
//!     page table (Limine's and Abraham's pinned ones): each gives its code and changes nothing;
//!  2. exhaustion: allocate until OUT_OF_MEMORY. Every frame is checked (aligned, >= 1 MiB,
//!     inside a USABLE entry, not kernel, not APIC, not a live page table) BEFORE anything is
//!     written to it; then it is filled with a tag and a pattern and linked into a list kept in
//!     the frames themselves;
//!  3. OUT_OF_MEMORY is sticky; the ownership check still passes with every frame written;
//!  4. the list is re-read: every tag and pattern intact, so no frame was handed out twice and
//!     no write landed in another frame;
//!  5. one release + alloc returns that same frame; then everything is released, counts return
//!     to their starting values and the ownership check passes again.
//! The kernel then continues to OPERATIONAL: its heartbeats show the writes hit nothing live.
//! A double release is NOT exercised here: it stops the kernel by design (diag-double-release).

use crate::frame::{FrameError, PAGE};
use crate::{kprintln, limine, memory};
use core::ptr;

const WORDS_PER_FRAME: usize = (PAGE / 8) as usize;

fn pattern(phys: u64, i: usize) -> u64 {
    phys ^ (i as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15)
}

fn word(hhdm: u64, phys: u64, i: usize) -> *mut u64 {
    (hhdm + phys + i as u64 * 8) as *mut u64
}

fn in_usable(phys: u64) -> bool {
    limine::memory_map().iter().any(|e| {
        e.kind == limine::MEMMAP_USABLE && phys >= e.base && phys + PAGE <= e.base.saturating_add(e.length)
    })
}

struct Outcome {
    ok: bool,
    checks: u32,
    failed: u32,
}

impl Outcome {
    fn expect(&mut self, name: &str, pass: bool) {
        self.checks += 1;
        if !pass {
            self.failed += 1;
            self.ok = false;
            kprintln!("ABR|MEMTEST|check={}|result=FAIL", name);
        }
    }
}

fn refused(phys: u64, want: FrameError) -> bool {
    memory::release_raw(phys) == Err(want)
}

pub fn run() -> bool {
    let hhdm = memory::hhdm();
    let mut o = Outcome { ok: true, checks: 0, failed: 0 };
    let (kphys, kbytes, apic) = memory::kernel_and_apic();
    let mut live = [0u64; 64];
    let n_live = memory::live_tables(&mut live);
    let live = &live[..n_live];
    let start = memory::stats().unwrap_or_default();
    kprintln!("ABR|MEMTEST|stage=start|free_frames={}|pinned={}|live_tables={}", start.free_frames, start.pinned, n_live);

    // 1. exhaustion with pre-write checks (first, so a colliding design meets the
    //    allocation guard here; see diag-legacy-collision)
    let (mut head, mut count, mut bad) = (0u64, 0u64, 0u64);
    let oom = loop {
        match memory::alloc_frame() {
            Ok(f) => {
                let p = f.phys();
                core::mem::forget(f); // ownership now tracked through the list below
                let valid = p % PAGE == 0 && p >= 0x10_0000 && in_usable(p) && !(p >= kphys && p < kphys + kbytes)
                    && p != apic && !live.contains(&p);
                if !valid {
                    bad += 1;
                    if bad <= 8 {
                        kprintln!("ABR|MEMTEST|violation=INVALID_FRAME_HANDED_OUT|frame={:#x}", p);
                    }
                    continue; // never written
                }
                // SAFETY: the frame is ours, USABLE, HHDM-mapped and checked above.
                unsafe {
                    ptr::write_volatile(word(hhdm, p, 0), p);
                    ptr::write_volatile(word(hhdm, p, 1), head);
                    for i in 2..WORDS_PER_FRAME {
                        ptr::write_volatile(word(hhdm, p, i), pattern(p, i));
                    }
                }
                head = p;
                count += 1;
            }
            Err(e) => break e,
        }
    };
    o.expect("exhaustion_reason_out_of_memory", oom == FrameError::OutOfMemory);
    o.expect("no_invalid_frame_handed_out", bad == 0);
    o.expect("all_free_frames_handed_out", count == start.free_frames);
    o.expect("oom_sticky_1", memory::alloc_frame().err() == Some(FrameError::OutOfMemory));
    o.expect("oom_sticky_2", memory::alloc_frame().err() == Some(FrameError::OutOfMemory));
    let at_oom = memory::stats().unwrap_or_default();
    o.expect("free_frames_zero_at_oom", at_oom.free_frames == 0);
    kprintln!("ABR|MEMTEST|stage=exhausted|allocated={}|expected={}|reason={}|oom_events={}|invalid={}",
              count, start.free_frames, oom.code(), at_oom.oom_events, bad);

    // 2. refused releases while exhausted (codes, no state change)
    o.expect("release_misaligned", refused(kphys + 8, FrameError::Misaligned));
    o.expect("release_out_of_range", refused(1 << 32, FrameError::OutOfRange));
    o.expect("release_frame0", refused(0, FrameError::NotOwned));
    o.expect("release_apic_page", refused(apic, FrameError::NotOwned));
    o.expect("release_kernel_image", refused(kphys, FrameError::NotOwned));
    let mut tables_refused = 0;
    for &t in live {
        if refused(t, FrameError::NotOwned) {
            tables_refused += 1;
        }
    }
    o.expect("release_every_live_page_table", tables_refused == n_live && n_live > 0);
    let after_refusals = memory::stats().unwrap_or_default();
    o.expect("refusals_changed_nothing", after_refusals.free_frames == 0
        && after_refusals.allocated == at_oom.allocated
        && after_refusals.refused_releases == at_oom.refused_releases + 5 + n_live as u64);
    kprintln!("ABR|MEMTEST|stage=refusals|live_tables_refused={}/{}|refused_releases={}",
              tables_refused, n_live, after_refusals.refused_releases);

    // 3. ownership still proven with every free frame written
    o.expect("memcheck_after_exhaust", memory::check("after_exhaust"));

    // 4. re-read every frame
    let (mut seen, mut corrupt, mut p) = (0u64, 0u64, head);
    while p != 0 && seen <= count {
        let mut intact = true;
        // SAFETY: p came from the list built above; each entry is a frame we own.
        unsafe {
            if ptr::read_volatile(word(hhdm, p, 0)) != p {
                intact = false;
            }
            for i in 2..WORDS_PER_FRAME {
                if ptr::read_volatile(word(hhdm, p, i)) != pattern(p, i) {
                    intact = false;
                    break;
                }
            }
        }
        if !intact {
            corrupt += 1;
            if corrupt <= 8 {
                kprintln!("ABR|MEMTEST|violation=FRAME_CONTENT_CHANGED|frame={:#x}", p);
            }
        }
        seen += 1;
        // SAFETY: as above.
        p = unsafe { ptr::read_volatile(word(hhdm, p, 1)) };
    }
    o.expect("every_frame_seen_once", seen == count && p == 0);
    o.expect("every_frame_intact", corrupt == 0);
    kprintln!("ABR|MEMTEST|stage=verified|frames={}|intact={}|corrupt={}", seen, seen - corrupt, corrupt);

    // 5. release one, get the same one back; then release all
    if head != 0 {
        // SAFETY: head is ours.
        let next = unsafe { ptr::read_volatile(word(hhdm, head, 1)) };
        o.expect("release_one", memory::release_raw(head).is_ok());
        let again = memory::alloc_frame().map(|f| {
            let q = f.phys();
            core::mem::forget(f);
            q
        });
        o.expect("realloc_returns_released_frame", again == Ok(head));
        o.expect("oom_again_after_realloc", memory::alloc_frame().err() == Some(FrameError::OutOfMemory));
        // SAFETY: head is ours again; restore its list link (its content was poisoned on release).
        unsafe { ptr::write_volatile(word(hhdm, head, 1), next) };
    }
    let (mut released, mut refused_n, mut p) = (0u64, 0u64, head);
    while p != 0 && released + refused_n <= count {
        // SAFETY: read the link before the frame is released (and poisoned).
        let next = unsafe { ptr::read_volatile(word(hhdm, p, 1)) };
        if memory::release_raw(p).is_ok() { released += 1 } else { refused_n += 1 }
        p = next;
    }
    let end = memory::stats().unwrap_or_default();
    o.expect("released_all", released == count && refused_n == 0);
    o.expect("free_frames_restored", end.free_frames == start.free_frames && end.allocated == start.allocated);
    o.expect("pinned_unchanged", end.pinned == start.pinned);
    o.expect("memcheck_after_release", memory::check("after_release"));
    kprintln!(
        "ABR|MEMTEST|summary|allocated={}|expected={}|oom={}|oom_sticky=true|unique_and_intact={}|refusals={}|released={}\
         |checks={}|failed={}|result={}",
        count, start.free_frames, oom.code(), corrupt == 0 && seen == count, 5 + n_live, released, o.checks, o.failed,
        if o.ok { "PASS" } else { "FAIL" }
    );
    o.ok
}
