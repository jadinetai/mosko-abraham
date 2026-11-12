//! Investigation of Echo finding F-031a-E04 (0.31b Step 2). Evidence label: SIMULATED.
//!
//! 0.31a memory::check() computed
//!     in_usable = sum over USABLE map entries of pool_frames_in(entry)
//!     if in_usable != pool_frames_total() { report(pool_frames_total() - in_usable) }
//! The sum counts a frame once per USABLE entry that contains it, while the pool counts it once.
//! These tests run that exact formula on the real frame.rs and show where it breaks. They describe the
//! 0.31a behavior; they do not test the 0.31b fix.

use abraham_frame_hosttest::frame::*;

fn r(base: u64, length: u64) -> Region {
    Region { base, length, kind: Kind::Usable }
}

/// The 0.31a formula, verbatim apart from the kernel types.
fn formula_031a(a: &FrameAllocator<4>, usable: &[Region]) -> (u64, u64) {
    let in_usable: u64 = usable.iter().map(|e| a.pool_frames_in(e.base, e.base.saturating_add(e.length))).sum();
    (in_usable, a.pool_frames_total())
}

#[test]
fn e04_clean_map_formula_balances() {
    let map = [r(0x1000, 0x4000), r(0x8000, 0x2000)];
    let mut a = FrameAllocator::<4>::new();
    a.init(map.iter().copied(), &[]).unwrap();
    let (in_usable, total) = formula_031a(&a, &map);
    assert_eq!(in_usable, total, "no overlap: the formula is correct");
}

#[test]
fn e04_overlapping_usable_entries_underflow_the_subtraction() {
    // [0x1000,0x5000) and [0x3000,0x7000) share frames 0x3000 and 0x4000.
    let map = [r(0x1000, 0x4000), r(0x3000, 0x4000)];
    let mut a = FrameAllocator::<4>::new();
    a.init(map.iter().copied(), &[]).unwrap();
    let (in_usable, total) = formula_031a(&a, &map);
    assert_eq!(total, 6, "the allocator counts each frame once");
    assert_eq!(in_usable, 8, "the 0.31a sum counts the shared frames twice");
    assert!(in_usable != total, "so 0.31a reports a violation");
    assert_eq!(total.checked_sub(in_usable), None, "total - in_usable underflows");
    // Release builds do not check overflow: the reported 'frame' value wraps to a huge number.
    assert_eq!(total.wrapping_sub(in_usable), u64::MAX - 1);
    // The allocator itself flagged the map: the defect is in the check's arithmetic, not in ownership.
    assert!(a.anomalies().any(|(_, x)| x == Anomaly::UsableDuplicate));
}

#[test]
fn e04_identical_duplicate_entries_underflow_too() {
    let map = [r(0x1000, 0x4000), r(0x1000, 0x4000)];
    let mut a = FrameAllocator::<4>::new();
    a.init(map.iter().copied(), &[]).unwrap();
    let (in_usable, total) = formula_031a(&a, &map);
    assert_eq!((in_usable, total), (8, 4));
    assert_eq!(total.checked_sub(in_usable), None);
}
