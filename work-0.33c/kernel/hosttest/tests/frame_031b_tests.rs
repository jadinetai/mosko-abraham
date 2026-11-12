//! 0.31b hosted tests for frame.rs: F-031a-E04 fix and the D-ABR-012 repeat. Label: SIMULATED.
//! Test ids B01..B10 are referenced by the 0.31b review matrix.

use abraham_frame_hosttest::frame::*;
use std::collections::BTreeSet;
use std::vec::Vec;

const P: u64 = PAGE;
type A = FrameAllocator<4>; // physical [0, 1 MiB)

fn r(base: u64, length: u64, kind: Kind) -> Region {
    Region { base, length, kind }
}

fn usable_ranges(map: &[Region]) -> Vec<(u64, u64)> {
    map.iter().filter(|x| x.kind == Kind::Usable).map(|x| (x.base, x.base.saturating_add(x.length))).collect()
}

fn init(map: &[Region]) -> A {
    let mut a = A::new();
    a.init(map.iter().copied(), &[]).unwrap();
    a
}

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

fn random_map(rng: &mut Rng) -> Vec<Region> {
    let mut v = Vec::new();
    for _ in 0..rng.below(12) {
        let aligned = rng.below(4) != 0;
        let base = if aligned { rng.below(0x140000 / P) * P } else { rng.below(0x140000) };
        let length = match rng.below(10) {
            0 => 0,
            1 => u64::MAX - rng.below(0x10000),
            _ if aligned => (1 + rng.below(64)) * P,
            _ => 1 + rng.below(0x40000),
        };
        let kind = if rng.below(12) < 7 { Kind::Usable } else { Kind::from_limine(1 + rng.below(8)) };
        v.push(r(base, length, kind));
    }
    v
}

// ---------------------------------------------------------------- F-031a-E04

#[test]
fn b01_clean_map_nothing_outside() {
    let map = [r(0x1000, 0x4000, Kind::Usable), r(0x8000, 0x2000, Kind::Usable), r(0x5000, 0x1000, Kind::Reserved)];
    let a = init(&map);
    assert_eq!(a.pool_frames_outside(usable_ranges(&map).into_iter()), 0);
}

#[test]
fn b02_overlapping_usable_counts_nothing_outside_and_does_not_underflow() {
    // The exact map that made the 0.31a check compute 6 - 8 (X002).
    let map = [r(0x1000, 0x4000, Kind::Usable), r(0x3000, 0x4000, Kind::Usable)];
    let a = init(&map);
    assert_eq!(a.pool_frames_total(), 6);
    assert_eq!(a.pool_frames_outside(usable_ranges(&map).into_iter()), 0);
    assert!(a.anomalies().any(|(_, x)| x == Anomaly::UsableDuplicate), "the map defect is still reported");
}

#[test]
fn b03_identical_duplicates_nothing_outside() {
    let map = [r(0x1000, 0x4000, Kind::Usable), r(0x1000, 0x4000, Kind::Usable)];
    let a = init(&map);
    assert_eq!(a.pool_frames_outside(usable_ranges(&map).into_iter()), 0);
}

#[test]
fn b04_unsorted_misaligned_overlapping_mix_nothing_outside() {
    let map = [r(0x9800, 0x3000, Kind::Usable), r(0x1000, 0x6000, Kind::Usable), r(0x2000, 0x8000, Kind::Usable),
               r(0x6100, 0x100, Kind::Reserved)];
    let a = init(&map);
    assert_eq!(a.pool_frames_outside(usable_ranges(&map).into_iter()), 0);
}

#[test]
fn b05_omitted_range_is_detected_exactly() {
    let map = [r(0x1000, 0x4000, Kind::Usable), r(0x8000, 0x3000, Kind::Usable)];
    let a = init(&map);
    // Leave the second entry out of the ranges: its 3 frames are "outside".
    assert_eq!(a.pool_frames_outside([(0x1000u64, 0x5000u64)].into_iter()), 3);
    assert_eq!(a.pool_frames_outside(core::iter::empty()), a.pool_frames_total());
}

#[test]
fn b06_property_3000_random_maps() {
    let mut rng = Rng(0x0031_b000_e04f_0001);
    for case in 0..3000 {
        let map = random_map(&mut rng);
        let a = init(&map);
        let ranges = usable_ranges(&map);
        assert_eq!(a.pool_frames_outside(ranges.iter().copied()), 0, "case {case}: {map:?}");
        if !ranges.is_empty() {
            // drop one USABLE range; the count must equal the pool frames covered ONLY by it
            let k = rng.below(ranges.len() as u64) as usize;
            let rest: Vec<(u64, u64)> = ranges.iter().enumerate().filter(|(i, _)| *i != k).map(|(_, x)| *x).collect();
            let inside = |p: u64, rs: &[(u64, u64)]| rs.iter().any(|&(b, e)| p >= b && p.saturating_add(P) <= e);
            let expected = (0..A::limit() / P).map(|f| f * P)
                .filter(|&p| a.in_pool(p) && !inside(p, &rest)).count() as u64;
            assert_eq!(a.pool_frames_outside(rest.iter().copied()), expected, "case {case} without range {k}");
        }
    }
}

fn vm_map() -> Vec<Region> {
    // ABR-0.31a-P001/P002 measured map (also used by 0.31a H27).
    let t = [
        (0x0, 0xa0000, 0), (0x100000, 0x700000, 0), (0x800000, 0x8000, 3), (0x808000, 0x3000, 0),
        (0x80b000, 0x1000, 3), (0x80c000, 0x5000, 0), (0x811000, 0xef000, 3), (0x900000, 0xe80000, 5),
        (0x1780000, 0xa7ec000, 0), (0xbf6c000, 0x20000, 5), (0xbf8c000, 0x20d8000, 0), (0xe064000, 0x71000, 5),
        (0xe0d5000, 0x4000, 0), (0xe0d9000, 0x2a000, 5), (0xe103000, 0x1d000, 6), (0xe120000, 0xd21000, 5),
        (0xee41000, 0xc1000, 8), (0xef02000, 0x9eb000, 5), (0xf8ed000, 0x200000, 8), (0xfaed000, 0x80000, 1),
        (0xfb6d000, 0x12000, 2), (0xfb7f000, 0x80000, 3), (0xfbff000, 0x246000, 5), (0xfe45000, 0x1000, 0),
        (0xfe46000, 0x6a000, 5), (0xfeb0000, 0x4000, 1), (0xfeb4000, 0x2000, 3), (0xfeb6000, 0x3e000, 5),
        (0xfef4000, 0x84000, 8), (0xff78000, 0x88000, 3), (0xe0000000, 0x10000000, 1), (0xffc00000, 0x400000, 1),
        (0xfd00000000, 0x300000000, 1),
    ];
    t.iter().map(|&(b, l, k)| r(b, l, Kind::from_limine(k))).collect()
}

#[test]
fn b07_measured_vm_map_with_injected_duplicate_like_diag_map_overlap() {
    let base = vm_map();
    let mut with_dup = base.clone();
    with_dup.push(base[8]); // the largest USABLE entry again, as the diag-map-overlap build injects it
    let mut a = Box::new(FrameAllocator::<16384>::new());
    a.init(base.iter().copied(), &[]).unwrap();
    let mut b = Box::new(FrameAllocator::<16384>::new());
    b.init(with_dup.iter().copied(), &[]).unwrap();
    assert_eq!(b.pool_frames_total(), a.pool_frames_total(), "the duplicate adds no frame");
    // Appended after the highest entry, the duplicate is also out of order: both are reported.
    let found: Vec<(u32, Anomaly)> = b.anomalies().collect();
    assert_eq!(found, vec![(33, Anomaly::Unsorted), (33, Anomaly::UsableDuplicate)]);
    assert_eq!(b.pool_frames_outside(usable_ranges(&with_dup).into_iter()), 0);
}

// ---------------------------------------------------------------- D-ABR-012, repeated in 0.31b

#[test]
fn b08_double_release_property_latches_and_free_pool_unchanged() {
    let mut rng = Rng(0x0031_b012_db10_0001);
    for case in 0..500 {
        let mut a = init(&[r(0x1000, 0x80000, Kind::Usable)]);
        let mut held: Vec<u64> = Vec::new();
        let mut released: Vec<u64> = Vec::new();
        for _ in 0..(1 + rng.below(60)) {
            if held.is_empty() || rng.below(3) != 0 {
                if let Ok(f) = a.alloc() {
                    held.push(f.phys());
                    core::mem::forget(f);
                }
            } else {
                let p = held.swap_remove(rng.below(held.len() as u64) as usize);
                a.release_raw(p).unwrap();
                released.push(p);
            }
        }
        // release a frame that is already free: either one we released, or one never allocated
        let target = if !released.is_empty() && rng.below(2) == 0 {
            released[rng.below(released.len() as u64) as usize]
        } else {
            (0x1000..0x81000u64).step_by(P as usize).find(|p| a.is_free(*p)).unwrap()
        };
        let (free_count, free_bits) = (a.stats().free_frames, a.free_frames_total());
        assert_eq!(a.release_raw(target), Err(FrameError::DoubleRelease), "case {case}");
        assert_eq!(a.state(), State::Faulted, "case {case}");
        assert_eq!(a.fault(), Some((FrameError::DoubleRelease, target)));
        assert_eq!((a.stats().free_frames, a.free_frames_total()), (free_count, free_bits), "case {case}: pool changed");
        assert!(a.is_free(target));
        assert_eq!(a.alloc(), Err(FrameError::Faulted));
        if let Some(&p) = held.first() {
            assert_eq!(a.release_raw(p), Err(FrameError::Faulted));
        }
    }
}

#[test]
fn b09_collision_property_never_returns_a_live_frame() {
    let mut rng = Rng(0x0031_b012_c011_0001);
    for case in 0..500 {
        let mut a = init(&[r(0x1000, 0x80000, Kind::Usable)]);
        let live: BTreeSet<u64> = (0..1 + rng.below(4)).map(|_| (1 + rng.below(0x80)) * P).collect();
        let mut handed = Vec::new();
        let outcome = loop {
            match a.alloc_checked(|p| live.contains(&p)) {
                Ok(f) => {
                    handed.push(f.phys());
                    core::mem::forget(f);
                }
                Err(e) => break e,
            }
        };
        assert_eq!(outcome, FrameError::OwnershipCollision, "case {case}");
        assert!(handed.iter().all(|p| !live.contains(p)), "case {case}: live frame handed out");
        let (_, frame) = a.fault().unwrap();
        assert!(live.contains(&frame) && !a.in_pool(frame) && !a.is_free(frame), "case {case}: not quarantined");
        assert_eq!(a.stats().quarantined, 1);
        assert_eq!(a.alloc(), Err(FrameError::Faulted));
        assert_eq!(a.free_outside_pool(), 0);
    }
}

#[test]
fn b10_collision_with_the_measured_0_29_tables_on_0_31b_code() {
    let mut a = Box::new(FrameAllocator::<16384>::new());
    a.init(vm_map().into_iter(), &[Reservation { base: 0, length: 0x100000, owner: Owner::Low1Mib }]).unwrap();
    let live = [0xbf6b000u64, 0xbf6a000u64];
    let e = loop {
        match a.alloc_checked(|p| live.contains(&p)) {
            Ok(f) => core::mem::forget(f),
            Err(e) => break e,
        }
    };
    assert_eq!(e, FrameError::OwnershipCollision);
    assert_eq!(a.fault(), Some((FrameError::OwnershipCollision, 0xbf6a000)));
    assert!(!a.in_pool(0xbf6a000) && a.in_pool(0xbf6b000), "only the frame met is quarantined");
    assert_eq!(a.alloc(), Err(FrameError::Faulted));
}
