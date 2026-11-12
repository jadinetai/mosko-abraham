//! 0.31b hosted tests: clock guard (F-029-04), lifecycle, event log (ABR-031-EVT-01).
//! Label: SIMULATED. Ids C01..C09, L01..L05, V01..V07 are referenced by the 0.31b review matrix.

use abraham_frame_hosttest::clockguard::*;
use abraham_frame_hosttest::events::*;
use abraham_frame_hosttest::lifecycle::*;
use std::vec::Vec;

const HZ: u64 = 1_000_000; // 1 MHz in the tests: 1 count = 1 us

fn started(raw: u64) -> ClockGuard {
    let mut g = ClockGuard::new();
    assert!(g.start(HZ, raw));
    g
}

// ---------------------------------------------------------------- clock guard

#[test]
fn c01_not_started_reports_nothing_and_zero_rate_refused() {
    let mut g = ClockGuard::new();
    assert_eq!(g.observe(5), None);
    assert_eq!(g.peek(5), None);
    assert!(!g.start(0, 5), "zero rate refused");
    assert!(!g.started());
    assert!(g.start(HZ, 5));
    assert!(!g.start(HZ, 9), "started once only");
}

#[test]
fn c02_normal_progression_is_exact() {
    let mut g = started(1_000);
    let mut ms = Vec::new();
    for k in 1..=50u64 {
        let o = g.observe(1_000 + k * 10_000).unwrap(); // 10 ms per reading
        assert_eq!(o.anomaly, None);
        ms.push(o.uptime_ms);
    }
    assert_eq!(*ms.last().unwrap(), 500);
    assert!(!g.degraded() && g.anomalies() == 0);
}

#[test]
fn c03_backward_step_adds_nothing_rebases_and_degrades() {
    let mut g = started(0);
    assert_eq!(g.observe(3 * HZ).unwrap().uptime_ms, 3_000);
    let o = g.observe(1 * HZ).unwrap(); // 2 s backwards
    assert_eq!(o.anomaly, Some(ClockAnomaly::Backward(2 * HZ)));
    assert_eq!(o.uptime_ms, 3_000, "uptime holds, never decreases, never wraps");
    assert!(g.degraded());
    let later = g.observe(1 * HZ + HZ / 2).unwrap(); // normal progress from the new base
    assert_eq!((later.uptime_ms, later.anomaly), (3_500, None));
    assert!(g.degraded(), "DEGRADED is latched for the boot");
}

#[test]
fn c04_forward_jump_is_kept_flagged_and_degrades() {
    let mut g = started(0);
    g.observe(3 * HZ).unwrap();
    let o = g.observe(3 * HZ + 3600 * HZ).unwrap(); // one hour in one step
    assert_eq!(o.anomaly, Some(ClockAnomaly::ForwardJump(3600 * HZ)));
    assert_eq!(o.uptime_ms, 3_603_000, "kept: expiry can only come early (fail-closed)");
    assert!(g.degraded());
}

#[test]
fn c05_step_limit_boundary() {
    let mut g = started(0);
    assert_eq!(g.observe(MAX_STEP_SECONDS * HZ).unwrap().anomaly, None, "exactly the limit is accepted");
    assert_eq!(g.observe(2 * MAX_STEP_SECONDS * HZ + 1).unwrap().anomaly, Some(ClockAnomaly::ForwardJump(MAX_STEP_SECONDS * HZ + 1)));
}

#[test]
fn c06_counter_wrap_near_2_64_is_a_backward_step_not_a_huge_uptime() {
    let mut g = started(u64::MAX - 10);
    let o = g.observe(5).unwrap(); // the 0.29 wrapping_sub would have produced ~2^64 counts here
    assert_eq!(o.anomaly, Some(ClockAnomaly::Backward(u64::MAX - 15)));
    assert_eq!(o.uptime_ms, 0);
}

#[test]
fn c07_saturation_never_panics() {
    let mut g = ClockGuard::new();
    assert!(g.start(1, 0)); // 1 count per second: every count is 1000 ms
    g.observe(u64::MAX).unwrap();
    let o = g.observe(u64::MAX).unwrap();
    assert_eq!(o.uptime_ms, u64::MAX, "saturates instead of overflowing");
}

#[test]
fn c08_peek_changes_nothing() {
    let mut g = started(0);
    g.observe(HZ).unwrap();
    assert_eq!(g.peek(2 * HZ), Some(2_000));
    assert_eq!(g.peek(HZ / 2), Some(1_000), "a backward peek adds nothing");
    assert_eq!(g.anomalies(), 0);
    assert_eq!(g.observe(2 * HZ).unwrap().uptime_ms, 2_000);
}

#[test]
fn c09_property_uptime_never_decreases_and_anomalies_are_exact() {
    let mut s = 0x0031_b029_04ff_0001u64;
    let mut next = || {
        s ^= s << 13;
        s ^= s >> 7;
        s ^= s << 17;
        s
    };
    for case in 0..300 {
        let mut raw = next() % (1u64 << 40);
        let mut g = started(raw);
        let (mut last_up, mut expected) = (0u64, 0u64);
        for _ in 0..200 {
            let step = next();
            let x = step / 20;
            raw = if step % 20 == 0 && raw > 0 {
                expected += 1; // strictly lower than the last reading
                raw - (1 + x % raw.min(10 * HZ))
            } else if step % 20 == 1 {
                expected += 1; // more than MAX_STEP_SECONDS ahead
                raw + MAX_STEP_SECONDS * HZ + 1 + x % (1000 * HZ)
            } else {
                raw + x % (MAX_STEP_SECONDS * HZ + 1) // within the limit (inclusive)
            };
            let o = g.observe(raw).unwrap();
            assert!(o.uptime_ms >= last_up, "case {case}: uptime decreased");
            last_up = o.uptime_ms;
        }
        assert_eq!(g.anomalies(), expected, "case {case}: anomaly count");
        assert_eq!(g.degraded(), expected > 0);
    }
}

// ---------------------------------------------------------------- lifecycle

const CHAIN: [InitState; 8] = [InitState::Early, InitState::LoaderVerified, InitState::MemoryOwned, InitState::MemoryVerified,
                               InitState::CpuTablesLoaded, InitState::TimerRunning, InitState::OwnershipVerified, InitState::Operational];

#[test]
fn l01_clean_boot_is_exactly_seven_transitions() {
    let mut l = Lifecycle::new();
    assert_eq!(l.state(), InitState::Early);
    for (n, w) in CHAIN.windows(2).enumerate() {
        let t = l.advance(w[1]).unwrap();
        assert_eq!(t, Transition { seq: n as u32 + 1, from: w[0], to: w[1] });
    }
    assert_eq!((l.state(), l.seq()), (InitState::Operational, 7));
}

#[test]
fn l02_full_9x9_transition_matrix() {
    let mut allowed = 0;
    for &from in ALL_STATES.iter() {
        for &to in ALL_STATES.iter() {
            let mut l = Lifecycle::from_parts(from, 4);
            let r = l.advance(to);
            let legal = to != InitState::Failed && from.next() == Some(to);
            assert_eq!(r.is_ok(), legal, "{from:?} -> {to:?}");
            if legal {
                allowed += 1;
                assert_eq!((l.state(), l.seq()), (to, 5));
            } else {
                assert_eq!(r, Err(Refused { from, to }));
                assert_eq!((l.state(), l.seq()), (from, 4), "refusal changes nothing");
            }
        }
    }
    assert_eq!(allowed, 7, "only the 7 chain steps are legal through advance()");
}

#[test]
fn l03_failed_is_reachable_from_everything_and_terminal() {
    for &from in ALL_STATES.iter() {
        let mut l = Lifecycle::from_parts(from, 2);
        let r = l.fail();
        if from == InitState::Failed {
            assert!(r.is_err());
        } else {
            assert_eq!(r.unwrap(), Transition { seq: 3, from, to: InitState::Failed });
        }
        for &to in ALL_STATES.iter() {
            assert!(l.advance(to).is_err(), "nothing leaves FAILED");
        }
        assert!(l.fail().is_err());
    }
}

#[test]
fn l04_refusal_code_is_registered_name() {
    assert_eq!(Refused { from: InitState::MemoryOwned, to: InitState::Operational }.code(), "INIT_INVALID_TRANSITION");
}

#[test]
fn l05_names_distinct_and_round_trip() {
    let mut names: Vec<&str> = ALL_STATES.iter().map(|s| s.name()).collect();
    for s in ALL_STATES {
        assert_eq!(InitState::from_u8(s as u8), s);
    }
    names.sort();
    names.dedup();
    assert_eq!(names.len(), 9);
}

// ---------------------------------------------------------------- event log

#[test]
fn v01_records_are_numbered_and_read_in_order() {
    let mut log = EventLog::new();
    for k in 0..5u64 {
        assert_eq!(log.record(Kind::Init, "LOADER_VERIFIED", k, Some(k * 10)), k as u32 + 1);
    }
    let seqs: Vec<u32> = (0..log.retained()).map(|i| log.get(i).unwrap().seq).collect();
    assert_eq!(seqs, vec![1, 2, 3, 4, 5]);
    assert_eq!((log.recorded(), log.dropped()), (5, 0));
}

#[test]
fn v02_full_log_overwrites_oldest_and_counts_it() {
    let mut log = EventLog::new();
    for k in 0..CAPACITY as u64 {
        log.record(Kind::Memory, "MEMCHECK_PASS", k, None);
    }
    assert_eq!((log.retained(), log.dropped()), (CAPACITY, 0));
    log.record(Kind::Timing, "TIMER_STARTED", 99, Some(1));
    assert_eq!((log.retained(), log.dropped(), log.recorded()), (CAPACITY, 1, CAPACITY as u64 + 1));
    assert_eq!(log.get(0).unwrap().seq, 2, "the oldest was overwritten");
    assert_eq!(log.get(CAPACITY - 1).unwrap().code, "TIMER_STARTED");
}

#[test]
fn v03_long_run_keeps_the_newest_in_order() {
    let mut log = EventLog::new();
    for k in 0..100u64 {
        log.record(Kind::Fault, "PANIC", k, None);
    }
    assert_eq!(log.dropped(), 100 - CAPACITY as u64);
    let seqs: Vec<u32> = (0..log.retained()).map(|i| log.get(i).unwrap().seq).collect();
    assert_eq!(seqs, (100 - CAPACITY as u32 + 1..=100).collect::<Vec<_>>());
    assert_eq!(log.get(CAPACITY), None);
}

#[test]
fn v04_last_n_is_newest_n_oldest_first() {
    let mut log = EventLog::new();
    for k in 0..10u64 {
        log.record(Kind::Init, "EARLY", k, None);
    }
    assert_eq!(log.last(3).map(|e| e.seq).collect::<Vec<_>>(), vec![8, 9, 10]);
    assert_eq!(log.last(50).count(), 10);
    assert_eq!(EventLog::new().last(8).count(), 0);
}

#[test]
fn v05_unknown_uptime_stays_none() {
    let mut log = EventLog::new();
    log.record(Kind::Init, "LOADER_VERIFIED", 1, None);
    assert_eq!(log.get(0).unwrap().uptime_ms, None, "never a fake 0");
}

#[test]
fn v06_kinds_are_the_four_required() {
    let names: Vec<&str> = [Kind::Init, Kind::Memory, Kind::Timing, Kind::Fault].iter().map(|k| k.name()).collect();
    assert_eq!(names, vec!["INIT", "MEMORY", "TIMING", "FAULT"]);
}

/// ABR-031-EVT-01 "fixed capacity, no dynamic allocation": the log is a const-constructible fixed
/// array that can live in a static, and its size does not depend on what is recorded.
static STATIC_LOG: EventLog = EventLog::new();

#[test]
fn v07_fixed_capacity_static_storage() {
    assert_eq!(STATIC_LOG.retained(), 0);
    let size = core::mem::size_of::<EventLog>();
    assert!(size >= CAPACITY * core::mem::size_of::<Event>() && size <= CAPACITY * core::mem::size_of::<Event>() + 16);
}
