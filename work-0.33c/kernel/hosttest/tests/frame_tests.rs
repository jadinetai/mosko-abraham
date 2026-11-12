//! Hosted tests for kernel/src/frame.rs (ABRAHAM 0.31a). Evidence label: SIMULATED.
//! Test ids H01..H40 are referenced by the 0.31a review matrix.

use abraham_frame_hosttest::frame::*;
use std::collections::BTreeSet;
use std::vec::Vec;

const P: u64 = PAGE;
type A = FrameAllocator<4>; // 256 frames: physical [0, 1 MiB)

fn r(base: u64, length: u64, kind: Kind) -> Region {
    Region { base, length, kind }
}

fn res(base: u64, length: u64, owner: Owner) -> Reservation {
    Reservation { base, length, owner }
}

fn new_init(regions: &[Region], reservations: &[Reservation]) -> (A, State) {
    let mut a = A::new();
    let s = a.init(regions.iter().copied(), reservations).expect("init");
    (a, s)
}

/// Allocate until the allocator says OUT_OF_MEMORY; returns the frames (as addresses).
fn drain<const W: usize>(a: &mut FrameAllocator<W>) -> Vec<u64> {
    let mut out = Vec::new();
    loop {
        match a.alloc() {
            Ok(f) => {
                let p = f.phys();
                core::mem::forget(f);
                out.push(p);
            }
            Err(FrameError::OutOfMemory) => return out,
            Err(e) => panic!("unexpected {e:?}"),
        }
    }
}

fn anomaly_codes<const W: usize>(a: &FrameAllocator<W>) -> Vec<Anomaly> {
    a.anomalies().map(|(_, x)| x).collect()
}

fn consistent<const W: usize>(a: &FrameAllocator<W>) {
    let s = a.stats();
    assert_eq!(a.free_outside_pool(), 0, "free must imply pool");
    assert_eq!(a.free_frames_total(), s.free_frames, "free counter vs bitmap");
    assert_eq!(a.pool_frames_total(), s.free_frames + s.allocated, "pool = free + allocated");
}

// ---------------------------------------------------------------- positive

#[test]
fn h01_frames_aligned_unique_and_only_from_usable() {
    let map = [r(0x1000, 0xf000, Kind::Usable), r(0x10000, 0x10000, Kind::Reserved), r(0x20000, 0x10000, Kind::Usable)];
    let (mut a, s) = new_init(&map, &[]);
    assert_eq!(s, State::Ready);
    assert_eq!(a.stats().pool_frames_initial, 15 + 16);
    let got = drain(&mut a);
    assert_eq!(got.len(), 31);
    let set: BTreeSet<u64> = got.iter().copied().collect();
    assert_eq!(set.len(), got.len(), "unique");
    for p in &got {
        assert_eq!(p % P, 0, "aligned");
        assert!((0x1000..0x10000).contains(p) || (0x20000..0x30000).contains(p), "{p:#x} outside USABLE");
    }
    consistent(&a);
}

#[test]
fn h02_frame_zero_never_returned_even_if_map_says_usable() {
    let (mut a, _) = new_init(&[r(0, 0x8000, Kind::Usable)], &[]);
    let got = drain(&mut a);
    assert_eq!(got.len(), 7);
    assert!(!got.contains(&0));
    assert!(!a.in_pool(0));
}

#[test]
fn h03_ledger_reservations_never_returned() {
    let reservations = [res(0, 0x10000, Owner::Low1Mib), res(0x20000, 0x1000, Owner::Test)];
    let (mut a, _) = new_init(&[r(0, 0x40000, Kind::Usable)], &reservations);
    let got = drain(&mut a);
    for p in &got {
        assert!(*p >= 0x10000 && *p != 0x20000, "{p:#x} reserved");
    }
    assert_eq!(got.len(), 0x40 - 0x10 - 1);
    assert_eq!(a.stats().removed_by_ledger, 0x10 + 1);
    let ledger: Vec<_> = a.ledger().collect();
    assert_eq!(ledger[0], (0, 0x10000, "LOW_1MIB", 0x10));
    assert_eq!(ledger[1], (0x20000, 0x1000, "TEST", 1));
}

#[test]
fn h04_pinned_frames_leave_the_pool_forever() {
    let (mut a, _) = new_init(&[r(0x1000, 0x8000, Kind::Usable)], &[]);
    let f = a.alloc().unwrap();
    let p = a.pin(f, PinOwner::PageTable).unwrap();
    assert!(!a.in_pool(p) && !a.is_free(p));
    assert_eq!(a.pinned(), &[p]);
    assert_eq!(a.release_raw(p), Err(FrameError::NotOwned));
    assert_eq!(a.state(), State::Ready, "refused release of a pinned frame does not latch");
    let rest = drain(&mut a);
    assert!(!rest.contains(&p), "pinned frame handed out again");
    assert_eq!(rest.len(), 7);
    assert_eq!(a.stats().pinned, 1);
    consistent(&a);
}

#[test]
fn h05_pin_log_overflow_is_reported() {
    let (mut a, _) = new_init(&[r(0x1000, 0x80000, Kind::Usable)], &[]);
    for _ in 0..(PIN_LOG + 1) {
        let f = a.alloc().unwrap();
        a.pin(f, PinOwner::PageTable).unwrap();
    }
    assert_eq!(a.pinned().len(), PIN_LOG);
    assert!(a.pin_log_overflowed());
}

#[test]
fn h06_release_then_realloc_returns_frames() {
    let (mut a, _) = new_init(&[r(0x1000, 0x4000, Kind::Usable)], &[]);
    let f1 = a.alloc().unwrap();
    let p1 = f1.phys();
    a.release(f1).unwrap();
    // next fit: the released frame comes back only after the scan wraps
    let rest = drain(&mut a);
    assert_eq!(rest.len(), 4);
    assert_eq!(*rest.last().unwrap(), p1, "released frame is the last one found");
    consistent(&a);
}

// ---------------------------------------------------------------- exhaustion

#[test]
fn h07_exhaustion_is_out_of_memory_sticky_and_writes_nothing() {
    let (mut a, _) = new_init(&[r(0x1000, 0x3000, Kind::Usable)], &[]);
    let got = drain(&mut a);
    assert_eq!(got.len(), 3);
    for _ in 0..3 {
        assert_eq!(a.alloc(), Err(FrameError::OutOfMemory));
    }
    let s = a.stats();
    assert_eq!(s.oom_events, 4);
    assert_eq!(s.free_frames, 0);
    assert_eq!(a.state(), State::Ready, "OOM is a condition, not a fault");
    // after one release, exactly that frame comes back, then OOM again
    a.release_raw(got[1]).unwrap();
    assert_eq!(a.alloc().map(|f| f.phys()), Ok(got[1]));
    assert_eq!(a.alloc(), Err(FrameError::OutOfMemory));
    consistent(&a);
}

#[test]
fn h08_empty_map_and_all_reserved_are_empty_state() {
    let (mut a, s) = new_init(&[], &[]);
    assert_eq!(s, State::Empty);
    assert_eq!(a.alloc(), Err(FrameError::OutOfMemory));
    let (mut b, s) = new_init(&[r(0x1000, 0x4000, Kind::Reserved), r(0x8000, 0x4000, Kind::BootloaderReclaimable)], &[]);
    assert_eq!(s, State::Empty);
    assert_eq!(b.alloc(), Err(FrameError::OutOfMemory));
}

// ---------------------------------------------------------------- serious violations (D-ABR-012)

#[test]
fn h09_double_release_latches_and_never_frees_twice() {
    let (mut a, _) = new_init(&[r(0x1000, 0x8000, Kind::Usable)], &[]);
    let f = a.alloc().unwrap();
    let keep = a.alloc().unwrap();
    let p = f.phys();
    a.release(f).unwrap();
    let free_before = a.stats().free_frames;
    let bitmap_before = a.free_frames_total();
    assert_eq!(a.release_raw(p), Err(FrameError::DoubleRelease));
    // the free pool is unchanged: the frame is free exactly once
    assert_eq!(a.stats().free_frames, free_before);
    assert_eq!(a.free_frames_total(), bitmap_before);
    assert!(a.is_free(p));
    // latched: never continues as if nothing happened
    assert_eq!(a.state(), State::Faulted);
    assert_eq!(a.fault(), Some((FrameError::DoubleRelease, p)));
    assert_eq!(a.alloc(), Err(FrameError::Faulted));
    assert_eq!(a.release(keep), Err(FrameError::Faulted));
    assert_eq!(a.release_raw(p), Err(FrameError::Faulted));
    consistent(&a);
}

#[test]
fn h10_release_of_never_allocated_free_frame_is_a_double_release() {
    let (mut a, _) = new_init(&[r(0x1000, 0x8000, Kind::Usable)], &[]);
    assert_eq!(a.release_raw(0x3000), Err(FrameError::DoubleRelease));
    assert_eq!(a.state(), State::Faulted);
}

#[test]
fn h11_collision_prevents_the_allocation_quarantines_and_latches() {
    // F-029-01 in miniature: 0x6000 is a live page table that the map calls USABLE.
    let live = 0x6000;
    let (mut a, _) = new_init(&[r(0x1000, 0x8000, Kind::Usable)], &[]);
    let mut got = Vec::new();
    let err = loop {
        match a.alloc_checked(|p| p == live) {
            Ok(f) => {
                got.push(f.phys());
                core::mem::forget(f);
            }
            Err(e) => break e,
        }
    };
    assert_eq!(err, FrameError::OwnershipCollision);
    assert!(!got.contains(&live), "the live frame was returned");
    assert_eq!(got, vec![0x1000, 0x2000, 0x3000, 0x4000, 0x5000]);
    assert!(!a.in_pool(live) && !a.is_free(live), "quarantined");
    assert_eq!(a.stats().quarantined, 1);
    assert_eq!(a.state(), State::Faulted);
    assert_eq!(a.fault(), Some((FrameError::OwnershipCollision, live)));
    assert_eq!(a.alloc(), Err(FrameError::Faulted), "no allocation after a collision");
    assert_eq!(a.release_raw(0x1000), Err(FrameError::Faulted));
    consistent(&a);
}

#[test]
fn h12_first_fault_is_kept() {
    let (mut a, _) = new_init(&[r(0x1000, 0x8000, Kind::Usable)], &[]);
    assert_eq!(a.alloc_checked(|_| true), Err(FrameError::OwnershipCollision));
    assert_eq!(a.release_raw(0x2000), Err(FrameError::Faulted));
    assert_eq!(a.fault(), Some((FrameError::OwnershipCollision, 0x1000)));
}

// ---------------------------------------------------------------- refusals

#[test]
fn h13_release_refusals_have_codes_and_do_not_latch() {
    let map = [r(0x1000, 0x8000, Kind::Usable), r(0x9000, 0x1000, Kind::Reserved)];
    let (mut a, _) = new_init(&map, &[]);
    let f = a.alloc().unwrap();
    assert_eq!(a.release_raw(f.phys() + 8), Err(FrameError::Misaligned));
    assert_eq!(a.release_raw(A::limit()), Err(FrameError::OutOfRange));
    assert_eq!(a.release_raw(u64::MAX & !(P - 1)), Err(FrameError::OutOfRange));
    assert_eq!(a.release_raw(0x9000), Err(FrameError::NotOwned), "reserved");
    assert_eq!(a.release_raw(0x20000), Err(FrameError::NotOwned), "never in the map");
    assert_eq!(a.release_raw(0), Err(FrameError::NotOwned), "frame 0");
    assert_eq!(a.state(), State::Ready);
    assert_eq!(a.stats().refused_releases, 6);
    a.release(f).unwrap();
    consistent(&a);
}

#[test]
fn h14_not_ready_before_init_and_init_once() {
    let mut a = A::new();
    assert_eq!(a.state(), State::Uninitialized);
    assert_eq!(a.alloc(), Err(FrameError::NotReady));
    assert_eq!(a.release_raw(0x1000), Err(FrameError::NotReady));
    a.init([r(0x1000, 0x1000, Kind::Usable)].into_iter(), &[]).unwrap();
    assert_eq!(a.init([r(0x2000, 0x1000, Kind::Usable)].into_iter(), &[]), Err(FrameError::AlreadyInitialized));
    assert_eq!(a.stats().pool_frames_initial, 1);
}

// ---------------------------------------------------------------- malformed maps

#[test]
fn h15_zero_length_entries_skipped() {
    let (a, _) = new_init(&[r(0x1000, 0, Kind::Usable), r(0x2000, 0x1000, Kind::Usable)], &[]);
    assert_eq!(a.stats().pool_frames_initial, 1);
    assert_eq!(anomaly_codes(&a), vec![Anomaly::ZeroLength]);
}

#[test]
fn h16_overflowing_usable_rejected_without_panic() {
    // sorted by base, so the only anomalies are the two overflows
    let (a, s) = new_init(&[r(PHYS_LIMIT, 0x1000, Kind::Usable), r(u64::MAX - 0x1000, 0x2000, Kind::Usable)], &[]);
    assert_eq!(s, State::Empty);
    assert_eq!(anomaly_codes(&a), vec![Anomaly::RangeOverflow, Anomaly::RangeOverflow]);
}

#[test]
fn h17_overflowing_reserved_reserves_everything_above_its_base() {
    let (a, _) = new_init(&[r(0x1000, 0x1f000, Kind::Usable), r(0x8000, u64::MAX, Kind::Reserved)], &[]);
    assert_eq!(a.stats().pool_frames_initial, 7, "only [0x1000, 0x8000) remains");
    assert!(anomaly_codes(&a).contains(&Anomaly::RangeOverflow));
}

#[test]
fn h18_misaligned_usable_trimmed_inward() {
    let (mut a, _) = new_init(&[r(0x1800, 0x4000, Kind::Usable)], &[]);
    assert_eq!(drain(&mut a), vec![0x2000, 0x3000, 0x4000]);
    assert_eq!(anomaly_codes(&a), vec![Anomaly::UsableMisaligned]);
    let (b, s) = new_init(&[r(0x1100, 0xe00, Kind::Usable)], &[]);
    assert_eq!(s, State::Empty, "no whole frame inside");
    assert_eq!(anomaly_codes(&b), vec![Anomaly::UsableMisaligned]);
}

#[test]
fn h19_unsorted_map_same_pool_as_sorted() {
    let sorted = [r(0x1000, 0x2000, Kind::Usable), r(0x3000, 0x1000, Kind::AcpiNvs), r(0x4000, 0x4000, Kind::Usable)];
    let unsorted = [sorted[2], sorted[0], sorted[1]];
    let (mut a, _) = new_init(&sorted, &[]);
    let (mut b, _) = new_init(&unsorted, &[]);
    assert_eq!(drain(&mut a), drain(&mut b));
    assert!(anomaly_codes(&b).contains(&Anomaly::Unsorted));
    assert!(anomaly_codes(&a).is_empty());
}

#[test]
fn h20_unaligned_reserved_overlap_removes_whole_frames() {
    let (mut a, _) = new_init(&[r(0x1000, 0xf000, Kind::Usable), r(0x8800, 0x900, Kind::Reserved)], &[]);
    let got = drain(&mut a);
    assert!(!got.contains(&0x8000) && !got.contains(&0x9000));
    assert_eq!(got.len(), 13);
    assert_eq!(a.stats().removed_by_map, 2);
    assert!(anomaly_codes(&a).contains(&Anomaly::ReservedOverlapsUsable));
}

#[test]
fn h21_duplicate_usable_counted_once() {
    let (mut a, _) = new_init(&[r(0x1000, 0x4000, Kind::Usable), r(0x3000, 0x4000, Kind::Usable)], &[]);
    let got = drain(&mut a);
    assert_eq!(got.len(), 6);
    assert_eq!(got.iter().copied().collect::<BTreeSet<_>>().len(), 6);
    assert_eq!(anomaly_codes(&a), vec![Anomaly::UsableDuplicate]);
}

#[test]
fn h22_unknown_type_is_reserved() {
    let map = [r(0x1000, 0xf000, Kind::Usable), r(0x2000, 0x1000, Kind::from_limine(99))];
    let (mut a, _) = new_init(&map, &[]);
    assert!(!drain(&mut a).contains(&0x2000));
    let codes = anomaly_codes(&a);
    assert!(codes.contains(&Anomaly::UnknownType) && codes.contains(&Anomaly::ReservedOverlapsUsable));
}

#[test]
fn h23_every_non_usable_type_is_reserved() {
    for t in 1..=8u64 {
        let map = [r(0x1000, 0x4000, Kind::Usable), r(0x2000, 0x1000, Kind::from_limine(t))];
        let (mut a, _) = new_init(&map, &[]);
        assert!(!drain(&mut a).contains(&0x2000), "type {t}");
    }
}

#[test]
fn h24_memory_above_the_limit_is_unmanaged() {
    let (mut a, _) = new_init(&[r(0xf0000, 0x20000, Kind::Usable)], &[]);
    assert_eq!(drain(&mut a).len(), 16);
    assert_eq!(a.stats().unmanaged_usable_bytes, 0x10000);
    let (mut b, s) = new_init(&[r(0x200000, 0x100000, Kind::Usable)], &[]);
    assert_eq!(s, State::Empty);
    assert_eq!(b.stats().unmanaged_usable_bytes, 0x100000);
    assert_eq!(b.release_raw(0x200000), Err(FrameError::OutOfRange));
}

#[test]
fn h25_invalid_reservations_counted_and_safe() {
    let (a, _) = new_init(&[r(0x1000, 0xf000, Kind::Usable)],
                          &[res(0x2000, 0, Owner::Test), res(0x8000, u64::MAX, Owner::Test)]);
    assert_eq!(a.stats().pool_frames_initial, 7);
    assert_eq!(anomaly_codes(&a), vec![Anomaly::ReservationInvalid, Anomaly::ReservationInvalid]);
}

// ---------------------------------------------------------------- differential test

/// Independent reference: a frame is allocatable iff it lies wholly inside a valid USABLE entry,
/// below the limit, is not frame 0, and intersects no non-USABLE entry and no reservation.
fn model(regions: &[Region], reservations: &[Reservation], limit: u64) -> BTreeSet<u64> {
    let frames = (limit / P) as usize;
    let mut ok = vec![false; frames];
    let end_of = |base: u64, len: u64| match base.checked_add(len) {
        Some(e) if e <= PHYS_LIMIT => Some(e),
        _ => None,
    };
    for x in regions.iter().filter(|x| x.kind == Kind::Usable && x.length > 0) {
        if let Some(e) = end_of(x.base, x.length) {
            for f in 0..frames {
                let a = f as u64 * P;
                if a >= x.base && a + P <= e {
                    ok[f] = true;
                }
            }
        }
    }
    let mut blocked: Vec<(u64, u64)> = regions.iter().filter(|x| x.kind != Kind::Usable && x.length > 0)
        .map(|x| (x.base, end_of(x.base, x.length).unwrap_or(PHYS_LIMIT))).collect();
    blocked.extend(reservations.iter().filter(|x| x.length > 0)
        .map(|x| (x.base, end_of(x.base, x.length).unwrap_or(PHYS_LIMIT))));
    for (b, e) in blocked {
        for f in 0..frames {
            let a = f as u64 * P;
            if a < e && b < a + P {
                ok[f] = false;
            }
        }
    }
    ok[0] = false;
    (0..frames).filter(|&f| ok[f]).map(|f| f as u64 * P).collect()
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

fn random_map(rng: &mut Rng) -> (Vec<Region>, Vec<Reservation>) {
    let span = 0x140000; // a little beyond the 1 MiB limit
    let mut regions = Vec::new();
    for _ in 0..rng.below(12) {
        let aligned = rng.below(4) != 0;
        let base = if aligned { rng.below(span / P) * P } else { rng.below(span) };
        let length = match rng.below(10) {
            0 => 0,
            1 => u64::MAX - rng.below(0x10000),
            _ if aligned => (1 + rng.below(64)) * P,
            _ => 1 + rng.below(0x40000),
        };
        let kind = match rng.below(12) {
            0..=5 => Kind::Usable,
            11 => Kind::from_limine(42),
            t => Kind::from_limine(t - 5),
        };
        regions.push(r(base, length, kind));
    }
    if rng.below(2) == 0 {
        regions.sort_by_key(|x| x.base);
    }
    let mut reservations = Vec::new();
    for _ in 0..rng.below(3) {
        reservations.push(res(rng.below(span), rng.below(0x20000), Owner::Test));
    }
    (regions, reservations)
}

#[test]
fn h26_differential_against_reference_model_3000_maps() {
    let mut rng = Rng(0x0031_a000_f029_0001);
    let mut nonempty = 0;
    for case in 0..3000 {
        let (regions, reservations) = random_map(&mut rng);
        let expected = model(&regions, &reservations, A::limit());
        let mut a = A::new();
        a.init(regions.iter().copied(), &reservations).unwrap();
        assert_eq!(a.stats().pool_frames_initial, expected.len() as u64, "case {case}: {regions:?} {reservations:?}");
        let got = drain(&mut a);
        let got_set: BTreeSet<u64> = got.iter().copied().collect();
        assert_eq!(got_set.len(), got.len(), "case {case}: duplicate frame");
        assert_eq!(got_set, expected, "case {case}");
        consistent(&a);
        // give everything back in a scrambled order and take it all again: same set
        let mut back = got.clone();
        for i in (1..back.len()).rev() {
            back.swap(i, rng.below(i as u64 + 1) as usize);
        }
        for p in &back {
            a.release_raw(*p).unwrap();
        }
        assert_eq!(drain(&mut a).into_iter().collect::<BTreeSet<_>>(), expected, "case {case} after release");
        if !expected.is_empty() {
            nonempty += 1;
        }
    }
    assert!(nonempty > 1000, "generator produced too few usable maps ({nonempty})");
}

// ---------------------------------------------------------------- replay of the measured VM map

/// Limine memory map measured on QEMU 11.1.0 q35, 256 MiB, by probe runs ABR-0.31a-P001 (WHPX)
/// and P002 (TCG); identical on both.
fn vm_map() -> Vec<Region> {
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

const VM_KERNEL: (u64, u64) = (0xe103000, 0x1c0d0);
const LIVE_029_TABLES: [u64; 2] = [0xbf6b000, 0xbf6a000]; // measured after the 0.29 APIC mapping

fn vm_reservations() -> Vec<Reservation> {
    vec![res(0, 0x100000, Owner::Low1Mib), res(VM_KERNEL.0, VM_KERNEL.1, Owner::KernelImage),
         res(0xfee00000, P, Owner::Mmio)]
}

#[test]
fn h27_kernel_sized_allocator_on_the_measured_vm_map() {
    let map = vm_map();
    let mut a = Box::new(FrameAllocator::<16384>::new());
    assert_eq!(FrameAllocator::<16384>::limit(), 1 << 32);
    a.init(map.iter().copied(), &vm_reservations()).unwrap();
    let s = a.stats();
    assert_eq!(s.anomalies, 0, "Limine's map is clean");
    assert_eq!(s.usable_bytes_reported, 218_566_656);
    let usable_frames = 218_566_656 / P;
    assert_eq!(s.pool_frames_initial, usable_frames - 0xa0, "all USABLE minus the 640 KiB below 1 MiB");
    // pool lies wholly inside USABLE
    let inside: u64 = map.iter().filter(|x| x.kind == Kind::Usable).map(|x| a.pool_frames_in(x.base, x.base + x.length)).sum();
    assert_eq!(inside, a.pool_frames_total());
    assert!(!a.in_pool(0) && !a.in_pool(0xfee00000) && !a.in_pool(VM_KERNEL.0));
}

#[test]
fn h28_f029_01_replay_map_trusting_allocator_would_hand_out_live_tables() {
    // The 0.29 situation: the tables were taken privately, the allocator only sees the map.
    let mut a = Box::new(FrameAllocator::<16384>::new());
    a.init(vm_map().into_iter(), &vm_reservations()).unwrap();
    for t in LIVE_029_TABLES {
        assert!(a.is_free(t), "{t:#x}: the map calls it free, so a naive allocator would return it");
    }
    // With the live set known, the first time a live table comes up it is refused and latched.
    let mut handed = 0u64;
    let err = loop {
        match a.alloc_checked(|p| LIVE_029_TABLES.contains(&p)) {
            Ok(f) => {
                assert!(!LIVE_029_TABLES.contains(&f.phys()));
                core::mem::forget(f);
                handed += 1;
            }
            Err(e) => break e,
        }
    };
    assert_eq!(err, FrameError::OwnershipCollision);
    assert_eq!(a.fault(), Some((FrameError::OwnershipCollision, 0xbf6a000)), "lowest live table hit first");
    assert_eq!(a.alloc(), Err(FrameError::Faulted));
    assert!(handed > 40_000);
}

#[test]
fn h29_031_design_tables_come_from_the_allocator_and_are_pinned() {
    // The 0.31a order: allocator first, page tables allocated from it and pinned.
    let mut a = Box::new(FrameAllocator::<16384>::new());
    a.init(vm_map().into_iter(), &vm_reservations()).unwrap();
    let pd = a.alloc().map(|f| a_pin(&mut a, f)).unwrap();
    let pt = a.alloc().map(|f| a_pin(&mut a, f)).unwrap();
    let pinned: Vec<u64> = a.pinned().to_vec();
    assert_eq!(pinned, vec![pd, pt]);
    // Draining with the pinned tables marked live never collides: they are not in the pool.
    let mut n = 0u64;
    loop {
        match a.alloc_checked(|p| pinned.contains(&p)) {
            Ok(f) => {
                core::mem::forget(f);
                n += 1;
            }
            Err(FrameError::OutOfMemory) => break,
            Err(e) => panic!("{e:?}"),
        }
    }
    assert_eq!(n, a.stats().pool_frames_initial - 2);
    assert_eq!(a.state(), State::Ready);
}

fn a_pin(a: &mut FrameAllocator<16384>, f: Frame) -> u64 {
    a.pin(f, PinOwner::PageTable).unwrap()
}

#[test]
fn h30_codes_are_distinct_and_stable() {
    let errors = [FrameError::OutOfMemory, FrameError::NotReady, FrameError::AlreadyInitialized,
                  FrameError::Misaligned, FrameError::OutOfRange, FrameError::NotOwned, FrameError::DoubleRelease,
                  FrameError::OwnershipCollision, FrameError::Faulted, FrameError::Busy, FrameError::Inconsistent];
    let codes: BTreeSet<&str> = errors.iter().map(|e| e.code()).collect();
    assert_eq!(codes.len(), errors.len());
    assert_eq!(FrameError::DoubleRelease.code(), "FRAME_DOUBLE_RELEASE");
    assert_eq!(FrameError::OwnershipCollision.code(), "FRAME_OWNERSHIP_COLLISION");
    assert_eq!(FrameError::OutOfMemory.code(), "OUT_OF_MEMORY");
}
