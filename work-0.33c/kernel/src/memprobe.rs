//! 0.31a Step 2 probe (feature `diag-memmap`, DIAGNOSTIC build, never an accepted kernel).
//!
//! Read-only inventory for the 0.31 design review: prints every Limine memory-map entry,
//! the kernel's physical placement, and every live page-table frame with the memory-map type
//! that contains it. Run once before and once after the APIC mapping (0.29 paging.rs path,
//! unchanged here), so frames taken privately from USABLE memory show up by address.

use crate::{kprintln, limine, paging, ptwalk};
use core::sync::atomic::Ordering;

unsafe extern "C" {
    static __abr_kernel_start: u8;
    static __abr_kernel_end: u8;
}

fn containing(frame: u64) -> (&'static str, usize) {
    for (i, e) in limine::memory_map().iter().enumerate() {
        if frame >= e.base && frame - e.base < e.length {
            return (limine::memmap_type_name(e.kind), i);
        }
    }
    ("NOT_IN_MEMMAP", usize::MAX)
}

pub fn memory_map() {
    for (i, e) in limine::memory_map().iter().enumerate() {
        kprintln!(
            "ABR|PROBE|memmap|i={}|base={:#x}|length={:#x}|end={:#x}|type={}",
            i, e.base, e.length, e.base.wrapping_add(e.length), limine::memmap_type_name(e.kind)
        );
    }
    let start = &raw const __abr_kernel_start as u64;
    let end = &raw const __abr_kernel_end as u64;
    match limine::executable_address() {
        Some((phys, virt)) => kprintln!(
            "ABR|PROBE|kernel|phys_base={:#x}|virt_base={:#x}|image_bytes={:#x}|phys_end={:#x}|phys_base_in={}",
            phys, virt, end - start, phys + (end - start), containing(phys).0
        ),
        None => kprintln!("ABR|PROBE|kernel|executable_address=UNAVAILABLE|image_bytes={:#x}", end - start),
    }
}

pub fn page_tables(stage: &str) {
    let Some(hhdm) = limine::hhdm_offset() else {
        kprintln!("ABR|PROBE|pt|stage={}|hhdm=UNAVAILABLE", stage);
        return;
    };
    let stats = ptwalk::walk(hhdm, |level, frame| {
        let (kind, i) = containing(frame);
        kprintln!("ABR|PROBE|pt|stage={}|level={}|frame={:#x}|in={}|memmap_i={}", stage, level, frame, kind,
                  if i == usize::MAX { -1 } else { i as i64 });
    });
    kprintln!(
        "ABR|PROBE|pt_summary|stage={}|tables={}|pml4={}|pdpt={}|pd={}|pt={}|leaf_1g={}|leaf_2m={}|leaf_4k={}|frames_taken_0_29_path={}",
        stage, stats.tables, stats.pml4, stats.pdpt, stats.pd, stats.pt, stats.leaf_1g, stats.leaf_2m, stats.leaf_4k,
        paging::FRAMES_TAKEN.load(Ordering::Relaxed)
    );
}
