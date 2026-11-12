//! Minimal page-table edit: map one 4 KiB MMIO page uncached (the local APIC in xAPIC mode).
//!
//! From Limine base revision 3 the HHDM covers only RAM-like memory-map regions, not device
//! MMIO, so the kernel maps the APIC page itself, at HHDM + physical address.
//!
//! 0.31a (F-029-01, D-ABR-009): missing intermediate tables come from the frame allocator
//! (memory.rs), zeroed and **pinned**, so they can never be handed out again. The 0.29
//! private bump allocator (top of the largest USABLE region, invisible to everything else)
//! exists only in the DIAGNOSTIC negative-control build `diag-legacy-collision`.
//! 4-level paging only: LA57 is never requested.

use crate::cpu::{read_cr3, read_cr4, read_msr};
use crate::limine;
use core::arch::asm;
use core::ptr;
use core::sync::atomic::{AtomicU64, Ordering};

const PRESENT: u64 = 1 << 0;
const WRITABLE: u64 = 1 << 1;
const WRITE_THROUGH: u64 = 1 << 3;
const CACHE_DISABLE: u64 = 1 << 4;
const HUGE: u64 = 1 << 7;
const NO_EXECUTE: u64 = 1 << 63;
const ADDRESS: u64 = 0x000f_ffff_ffff_f000;
const CR4_LA57: u64 = 1 << 12;
const IA32_EFER: u32 = 0xC000_0080;
const EFER_NXE: u64 = 1 << 11;

/// Page-table frames this kernel created, reported on the serial console.
pub static FRAMES_TAKEN: AtomicU64 = AtomicU64::new(0);

/// 0.31a: a zeroed page-table frame from the frame allocator, pinned for good.
#[cfg(not(feature = "diag-legacy-collision"))]
fn take_frame(_hhdm: u64) -> Result<u64, &'static str> {
    let frame = crate::memory::alloc_page_table().map_err(|e| e.code())?;
    FRAMES_TAKEN.fetch_add(1, Ordering::Relaxed);
    Ok(frame)
}

/// DIAGNOSTIC negative control only (F-029-01): the 0.29 private bump allocator, unchanged.
/// It takes frames the frame allocator still believes are free; the ownership check
/// (memory::check) and the allocation guard must catch exactly that.
#[cfg(feature = "diag-legacy-collision")]
fn take_frame(hhdm: u64) -> Result<u64, &'static str> {
    use crate::limine::MEMMAP_USABLE;
    const PAGE: u64 = 4096;
    static FRAME_TOP: AtomicU64 = AtomicU64::new(0);
    static FRAME_FLOOR: AtomicU64 = AtomicU64::new(0);
    if FRAME_TOP.load(Ordering::Relaxed) == 0 {
        let region = limine::memory_map().iter().filter(|e| e.kind == MEMMAP_USABLE).max_by_key(|e| e.length)
            .ok_or("NO_FREE_FRAME")?;
        let floor = (region.base + PAGE - 1) & !(PAGE - 1);
        let top = (region.base + region.length) & !(PAGE - 1);
        FRAME_FLOOR.store(floor, Ordering::Relaxed);
        FRAME_TOP.store(top, Ordering::Relaxed);
    }
    let top = FRAME_TOP.load(Ordering::Relaxed);
    if top < FRAME_FLOOR.load(Ordering::Relaxed) + PAGE {
        return Err("NO_FREE_FRAME");
    }
    let frame = top - PAGE;
    FRAME_TOP.store(frame, Ordering::Relaxed);
    FRAMES_TAKEN.fetch_add(1, Ordering::Relaxed);
    // SAFETY: (0.29 reasoning, deliberately kept) usable memory is HHDM-mapped.
    unsafe { ptr::write_bytes((hhdm + frame) as *mut u8, 0, PAGE as usize) };
    Ok(frame)
}

/// Map `phys` (one page) uncached at HHDM + `phys` and return that virtual address.
pub fn map_uncached(phys: u64) -> Result<u64, &'static str> {
    let hhdm = limine::hhdm_offset().ok_or("NO_HHDM")?;
    if read_cr4() & CR4_LA57 != 0 {
        return Err("LA57_UNSUPPORTED");
    }
    let phys = phys & ADDRESS;
    let virt = hhdm + phys;
    let nx = if read_msr(IA32_EFER) & EFER_NXE != 0 { NO_EXECUTE } else { 0 };

    let mut table = read_cr3() & ADDRESS;
    for shift in [39u64, 30, 21] {
        let slot = (hhdm + table + ((virt >> shift) & 0x1ff) * 8) as *mut u64;
        // SAFETY: page tables live in bootloader-reclaimable memory or in pinned USABLE frames
        // (0.31a); the HHDM maps both.
        let entry = unsafe { ptr::read_volatile(slot) };
        table = if entry & PRESENT == 0 {
            let frame = take_frame(hhdm)?;
            unsafe { ptr::write_volatile(slot, frame | PRESENT | WRITABLE) };
            frame
        } else if entry & HUGE != 0 {
            return Err("HUGE_PAGE_ON_PATH");
        } else {
            entry & ADDRESS
        };
    }
    let slot = (hhdm + table + ((virt >> 12) & 0x1ff) * 8) as *mut u64;
    // SAFETY: as above; then flush the one translation that changed.
    unsafe {
        ptr::write_volatile(slot, phys | PRESENT | WRITABLE | WRITE_THROUGH | CACHE_DISABLE | nx);
        asm!("invlpg [{}]", in(reg) virt, options(nostack, preserves_flags));
    }
    Ok(virt)
}
