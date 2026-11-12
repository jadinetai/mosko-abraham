//! Read-only walk of the live 4-level page tables (0.31a, audit finding F-029-01).
//!
//! Used to prove frame ownership on the running kernel: every page-table frame reachable
//! from CR3 is visited, and kernel virtual addresses are translated, without writing
//! anything. Table frames are read through the HHDM, which (Limine base revision 3+) maps
//! the bootloader-reclaimable memory holding Limine's tables and the usable memory holding
//! any table Abraham created. 4-level paging only: LA57 is refused elsewhere (paging.rs).

use crate::cpu::read_cr3;
use core::ptr;

const PRESENT: u64 = 1 << 0;
const HUGE: u64 = 1 << 7;
const ADDRESS: u64 = 0x000f_ffff_ffff_f000;

#[derive(Clone, Copy, Default)]
pub struct WalkStats {
    pub tables: u64,
    pub pml4: u64,
    pub pdpt: u64,
    pub pd: u64,
    pub pt: u64,
    pub leaf_1g: u64,
    pub leaf_2m: u64,
    pub leaf_4k: u64,
}

fn entry(hhdm: u64, table: u64, index: u64) -> u64 {
    // SAFETY: `table` is a page-table frame reached from CR3 (or CR3 itself); the HHDM maps
    // it (see module comment). Reads only.
    unsafe { ptr::read_volatile((hhdm + table + index * 8) as *const u64) }
}

/// Visit every page-table frame reachable from CR3 as `visit(level, physical_frame)`,
/// level 4 = PML4 down to 1 = page table. Returns counts of tables and leaf mappings.
pub fn walk(hhdm: u64, mut visit: impl FnMut(u8, u64)) -> WalkStats {
    let mut s = WalkStats::default();
    let pml4 = read_cr3() & ADDRESS;
    visit(4, pml4);
    s.tables += 1;
    s.pml4 += 1;
    for i4 in 0..512 {
        let e4 = entry(hhdm, pml4, i4);
        if e4 & PRESENT == 0 {
            continue;
        }
        let pdpt = e4 & ADDRESS;
        visit(3, pdpt);
        s.tables += 1;
        s.pdpt += 1;
        for i3 in 0..512 {
            let e3 = entry(hhdm, pdpt, i3);
            if e3 & PRESENT == 0 {
                continue;
            }
            if e3 & HUGE != 0 {
                s.leaf_1g += 1;
                continue;
            }
            let pd = e3 & ADDRESS;
            visit(2, pd);
            s.tables += 1;
            s.pd += 1;
            for i2 in 0..512 {
                let e2 = entry(hhdm, pd, i2);
                if e2 & PRESENT == 0 {
                    continue;
                }
                if e2 & HUGE != 0 {
                    s.leaf_2m += 1;
                    continue;
                }
                let pt = e2 & ADDRESS;
                visit(1, pt);
                s.tables += 1;
                s.pt += 1;
                for i1 in 0..512 {
                    if entry(hhdm, pt, i1) & PRESENT != 0 {
                        s.leaf_4k += 1;
                    }
                }
            }
        }
    }
    s
}

/// Physical address that `virt` maps to in the live tables, if it is mapped.
pub fn translate(hhdm: u64, virt: u64) -> Option<u64> {
    let mut table = read_cr3() & ADDRESS;
    for (shift, huge_ok) in [(39u64, false), (30, true), (21, true)] {
        let e = entry(hhdm, table, (virt >> shift) & 0x1ff);
        if e & PRESENT == 0 {
            return None;
        }
        if huge_ok && e & HUGE != 0 {
            let size = 1u64 << shift;
            return Some((e & ADDRESS & !(size - 1)) | (virt & (size - 1)));
        }
        table = e & ADDRESS;
    }
    let e = entry(hhdm, table, (virt >> 12) & 0x1ff);
    if e & PRESENT == 0 { None } else { Some((e & ADDRESS) | (virt & 0xfff)) }
}
