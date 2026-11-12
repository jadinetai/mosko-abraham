//! ABRAHAM 0.32b acceptance gate, Phase 1: the startup-probe interpretation the owner adopted on 2026-11-08
//! (recorded as D-ABR-021), tested against the UNCHANGED 0.32b sources (kernel/src/svc*.rs, compiled for the host
//! by the 0.32b hosted crate). Label: SIMULATED. These tests add no kernel behavior.
//!
//! The interpretation, as tested here:
//! - a slow startup probe is an execution-budget overrun, not a failed startup: with functional readiness held, the
//!   service enters RUNNING, its health is DEGRADED (never AVAILABLE on that probe), and the overrun counts toward
//!   the three-overrun failure policy;
//! - FAILED comes at the third overrun WITHOUT AN INTERVENING VERIFIED IN-BUDGET STEP, which need not be three
//!   adjacent calls: an unmeasured step neither counts as an overrun nor erases the overruns before it (the
//!   conservative rule kept for this revision);
//! - an unmeasured probe or step never establishes or refreshes healthy availability, and it breaks the streak of
//!   consecutive verified good steps that recovery needs;
//! - a functional readiness failure, or a readiness claim the kernel's own checks contradict, is FAILED whatever the
//!   probe's timing;
//! - the probe's duration and timing verdict are reported exactly as measured.
//!
//! The owner's seven cases: (1) p1; (2) p2; (3) p3a, p3b; (4) p4a-p4c; (5) p5; (6) p6a-p6d; (7) p7a, p7b; plus p8
//! (an unmeasured step never refreshes availability).

use abraham_frame_hosttest::svclife::SvcState;
use abraham_frame_hosttest::svcregistry::{Desc, Kind, ServiceId};
use abraham_frame_hosttest::svcrun::*;
use abraham_frame_hosttest::svcstatus::{ClockTrust, Liveness, PublicReason, Status};
use std::boxed::Box;
use std::format;
use std::vec;
use std::vec::Vec;

/// Timing of one call (the probe is call 1): in budget, over budget, or unmeasurable (the TSC goes back one count).
#[derive(Clone, Copy, Debug, PartialEq)]
enum T {
    Good,
    Over,
    Unm,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Fail {
    None,
    ReadyErr,
    Contradicted,
    ZeroUnits,
    ProbeError,
    StartError,
    OverBudgetUnits,
}

const GOOD_US: u64 = 5;
const SLOW_US: u64 = 20_000;

struct F {
    tsc: u64,
    now: Option<u64>,
    calls: u64,
    value: u64,
    script: Vec<T>,
    fail: Fail,
    log: Vec<Report>,
}

impl Host for F {
    fn kernel_operational(&self) -> bool {
        true
    }
    fn tsc(&mut self) -> u64 {
        self.tsc
    }
    fn tsc_hz(&self) -> u64 {
        1_000_000
    }
    fn uptime_ms(&mut self) -> Option<u64> {
        self.now
    }
    fn svc_start(&mut self, _i: usize) -> Result<(), &'static str> {
        if self.fail == Fail::StartError { Err("SVC_TEST_START_ERROR") } else { Ok(()) }
    }
    fn svc_step(&mut self, _i: usize, _budget: u32) -> StepOutcome {
        let k = core::cmp::min(self.calls as usize, self.script.len() - 1);
        self.calls += 1;
        match self.script[k] {
            T::Good => self.tsc += GOOD_US,
            T::Over => self.tsc += SLOW_US,
            T::Unm => self.tsc -= 1,
        }
        if self.calls == 1 {
            match self.fail {
                Fail::ProbeError => return StepOutcome::Error("SVC_TEST_PROBE_ERROR"),
                Fail::ZeroUnits => return StepOutcome::Done { units: 0 },
                Fail::Contradicted => return StepOutcome::Done { units: 1 }, // claims a unit; its state did not change
                Fail::OverBudgetUnits => {
                    self.value += 2;
                    return StepOutcome::Done { units: 2 };
                }
                _ => {}
            }
        }
        self.value += 1;
        StepOutcome::Done { units: 1 }
    }
    fn svc_ready(&mut self, _i: usize) -> Result<(), &'static str> {
        if self.fail == Fail::ReadyErr { Err("SVC_TEST_NOT_READY") } else { Ok(()) }
    }
    fn svc_observed(&self, _i: usize) -> Option<u64> {
        Some(self.value)
    }
    fn svc_stop(&mut self, _i: usize) -> Result<(), &'static str> {
        Ok(())
    }
    fn report(&mut self, _t: &[Desc], r: Report) {
        self.log.push(r);
    }
}

fn table() -> &'static [Desc] {
    Box::leak(vec![Desc { id: ServiceId(1), name: "svc.p", kind: Kind::Service, installed: true, deps: &[], budget: 1 }]
        .into_boxed_slice())
}

fn start(script: Vec<T>, fail: Fail) -> (ServiceSet, F) {
    let mut f = F { tsc: 1_000_000, now: Some(100), calls: 0, value: 0, script, fail, log: Vec::new() };
    let mut s = ServiceSet::new(table());
    assert_eq!(s.start_all(&mut f), StartResult::Started);
    (s, f)
}

fn status(s: &ServiceSet, f: &F) -> Status {
    s.status(0, ClockTrust::Ok, f.now).status
}

fn ready(f: &F) -> Option<(Option<u64>, StepTiming)> {
    f.log.iter().find_map(|r| match r {
        Report::Ready { probe_us, timing, .. } => Some((*probe_us, *timing)),
        _ => None,
    })
}

fn count(f: &F, p: impl Fn(&Report) -> bool) -> usize {
    f.log.iter().filter(|r| p(r)).count()
}

fn entered_running(f: &F) -> bool {
    f.log.iter().any(|r| matches!(r, Report::Transition { t, .. } if t.to == SvcState::Running))
}

fn failed_with(f: &F) -> Option<&'static str> {
    f.log.iter().find_map(|r| match r {
        Report::Transition { t, diag, .. } if t.to == SvcState::Failed => Some(diag.unwrap_or("NONE")),
        _ => None,
    })
}

// ------------------------------------------------------------------ (1) healthy in-budget probe

#[test]
fn p1_healthy_in_budget_probe_is_running_and_available() {
    let (s, f) = start(vec![T::Good], Fail::None);
    assert_eq!(ready(&f), Some((Some(GOOD_US), StepTiming::InBudget)));
    assert_eq!(s.state(0), SvcState::Running);
    let st = s.status(0, ClockTrust::Ok, Some(100));
    assert_eq!((st.status, st.reason, st.liveness), (Status::Available, None, Liveness::Live));
    let r = s.runtime(0);
    assert_eq!((r.overruns, r.consecutive, r.good, r.unmeasured, r.overrun_window, r.last_step_ms),
               (0, 0, 1, 0, false, Some(100)));
    assert_eq!(count(&f, |x| matches!(x, Report::Overrun { .. } | Report::Degraded { .. } | Report::Unmeasured { .. })), 0);
}

// ------------------------------------------------------------------ (2) a single slow probe

#[test]
fn p2_single_slow_probe_is_running_degraded_and_never_available_on_it() {
    let (mut s, mut f) = start(vec![T::Over, T::Good], Fail::None);
    assert_eq!(ready(&f), Some((Some(SLOW_US), StepTiming::Overrun)), "duration and verdict reported as measured");
    assert!(f.log.contains(&Report::Overrun { idx: 0, elapsed_us: SLOW_US, consecutive: 1 }));
    assert_eq!(count(&f, |x| matches!(x, Report::Degraded { .. })), 1);
    assert_eq!(s.state(0), SvcState::Running, "functional readiness held, so the service may enter RUNNING");
    let st = s.status(0, ClockTrust::Ok, f.now);
    assert_eq!((st.status, st.reason, st.liveness), (Status::Degraded, None, Liveness::Live));
    assert_eq!((s.runtime(0).overruns, s.runtime(0).consecutive), (1, 1), "the probe is overrun 1 of 3");
    for k in 1..RECOVER_AFTER_GOOD {
        s.step_all(&mut f);
        assert_eq!(status(&s, &f), Status::Degraded, "not AVAILABLE after {k} good steps");
    }
    s.step_all(&mut f);
    assert_eq!(status(&s, &f), Status::Available, "available only after 100 consecutive verified good steps");
    assert_eq!(count(&f, |x| matches!(x, Report::Recovered { .. })), 1);
}

// ------------------------------------------------------------------ (3) three overruns including the probe

#[test]
fn p3a_three_overruns_including_the_probe_fail() {
    let (mut s, mut f) = start(vec![T::Over], Fail::None);
    assert_eq!((s.state(0), s.runtime(0).consecutive), (SvcState::Running, 1));
    s.step_all(&mut f);
    assert_eq!((s.state(0), s.runtime(0).consecutive), (SvcState::Running, 2));
    assert_eq!(status(&s, &f), Status::Degraded);
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Failed, "two more overruns after the slow probe: FAILED");
    assert_eq!(failed_with(&f), Some("SVC_STEP_OVERRUN"));
    let r = s.runtime(0);
    assert_eq!((r.steps, r.overruns, r.consecutive), (2, 3, 3));
    assert!(f.log.contains(&Report::Overrun { idx: 0, elapsed_us: SLOW_US, consecutive: 3 }));
    assert_eq!(s.status(0, ClockTrust::Ok, f.now).status, Status::Unavailable);
    for _ in 0..10 {
        s.step_all(&mut f);
    }
    assert_eq!(f.calls, 3, "nothing restarts automatically (D-ABR-019 Q2)");
}

#[test]
fn p3b_negative_control_a_verified_good_step_resets_the_count() {
    let (mut s, mut f) = start(vec![T::Over, T::Over, T::Good, T::Over, T::Over, T::Over], Fail::None);
    let mut seen = vec![s.runtime(0).consecutive];
    for _ in 0..4 {
        s.step_all(&mut f);
        assert_eq!(s.state(0), SvcState::Running);
        seen.push(s.runtime(0).consecutive);
    }
    assert_eq!(seen, vec![1, 2, 0, 1, 2], "the in-budget step between them is a verified good step");
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Failed);
    assert_eq!(s.runtime(0).overruns, 5);
}

// ------------------------------------------------------------------ (4) an unmeasured probe

#[test]
fn p4a_unmeasured_probe_then_a_measured_good_step() {
    let (mut s, mut f) = start(vec![T::Unm, T::Good], Fail::None);
    assert_eq!(ready(&f), Some((None, StepTiming::Unmeasured)), "the verdict says UNMEASURED, with no duration");
    assert_eq!(count(&f, |x| matches!(x, Report::Unmeasured { .. })), 1);
    assert_eq!(s.state(0), SvcState::Running);
    let r = s.runtime(0);
    assert_eq!((r.unmeasured, r.good, r.consecutive, r.overruns, r.last_step_ms), (1, 0, 0, 0, None));
    let st = s.status(0, ClockTrust::Ok, Some(100));
    assert_eq!((st.status, st.reason, st.liveness), (Status::Unknown, Some(PublicReason::ObservationStale), Liveness::Stale),
               "an unmeasured probe does not establish healthy availability");
    s.step_all(&mut f);
    assert_eq!(status(&s, &f), Status::Available, "the first measured in-budget step does");
    assert_eq!((s.runtime(0).good, s.runtime(0).last_step_ms), (1, Some(100)));
}

#[test]
fn p4b_unmeasured_probe_then_a_slow_step_is_degraded() {
    let (mut s, mut f) = start(vec![T::Unm, T::Over], Fail::None);
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Running);
    assert_eq!(status(&s, &f), Status::Degraded);
    assert_eq!((s.runtime(0).consecutive, s.runtime(0).unmeasured), (1, 1));
}

#[test]
fn p4c_unmeasured_steps_establish_neither_availability_nor_failure() {
    let (mut s, mut f) = start(vec![T::Unm], Fail::None);
    for _ in 0..20 {
        s.step_all(&mut f);
        assert_eq!(s.state(0), SvcState::Running, "an unmeasured step is not an overrun");
        assert_ne!(status(&s, &f), Status::Available);
    }
    let r = s.runtime(0);
    assert_eq!((r.unmeasured, r.consecutive, r.overruns, r.good), (21, 0, 0, 0));
}

// ------------------------------------------------------------------ (5) recovery streak interrupted by an unmeasured step

#[test]
fn p5_recovery_streak_interrupted_by_an_unmeasured_step() {
    let mut script = vec![T::Good, T::Over];
    script.extend(core::iter::repeat(T::Good).take(50));
    script.push(T::Unm);
    script.extend(core::iter::repeat(T::Good).take(RECOVER_AFTER_GOOD as usize));
    let (mut s, mut f) = start(script, Fail::None);
    s.step_all(&mut f); // the overrun opens the DEGRADED window
    for _ in 0..50 {
        s.step_all(&mut f);
        assert_eq!(status(&s, &f), Status::Degraded);
    }
    assert_eq!(s.runtime(0).good, 50);
    s.step_all(&mut f); // unmeasured
    assert_eq!((s.runtime(0).good, s.runtime(0).unmeasured), (0, 1), "the streak is broken");
    assert_eq!(status(&s, &f), Status::Degraded);
    for _ in 0..(RECOVER_AFTER_GOOD - 1) {
        s.step_all(&mut f);
        assert_eq!(status(&s, &f), Status::Degraded, "99 good steps after the unmeasured one are not enough");
    }
    s.step_all(&mut f);
    assert_eq!(status(&s, &f), Status::Available);
    assert_eq!(count(&f, |x| matches!(x, Report::Recovered { .. })), 1);
}

// ------------------------------------------------------------------ (6) OVERRUN, OVERRUN, UNMEASURED, OVERRUN

#[test]
fn p6a_overrun_overrun_unmeasured_overrun_fails_at_the_third_overrun() {
    let (mut s, mut f) = start(vec![T::Good, T::Over, T::Over, T::Unm, T::Over], Fail::None);
    let mut trace = Vec::new();
    for _ in 0..3 {
        s.step_all(&mut f);
        let r = s.runtime(0);
        trace.push((s.state(0), r.consecutive, r.unmeasured));
    }
    assert_eq!(trace, vec![(SvcState::Running, 1, 0), (SvcState::Running, 2, 0), (SvcState::Running, 2, 1)],
               "the unmeasured step neither counts as an overrun nor erases the two before it");
    assert_eq!(status(&s, &f), Status::Degraded);
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Failed,
               "the third overrun with no verified good step in between fails it, although the calls were not adjacent");
    assert_eq!(failed_with(&f), Some("SVC_STEP_OVERRUN"));
    let r = s.runtime(0);
    assert_eq!((r.steps, r.overruns, r.unmeasured, r.consecutive), (4, 3, 1, 3));
}

#[test]
fn p6b_probe_overrun_overrun_unmeasured_overrun_fails() {
    let (mut s, mut f) = start(vec![T::Over, T::Over, T::Unm, T::Over], Fail::None);
    s.step_all(&mut f);
    s.step_all(&mut f);
    assert_eq!((s.state(0), s.runtime(0).consecutive), (SvcState::Running, 2));
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Failed);
    assert_eq!((s.runtime(0).steps, s.runtime(0).overruns, s.runtime(0).unmeasured), (3, 3, 1));
}

#[test]
fn p6c_the_threshold_counts_overruns_not_calls() {
    let (mut s, mut f) = start(vec![T::Good, T::Over, T::Unm, T::Unm, T::Over, T::Unm, T::Unm, T::Over], Fail::None);
    for k in 1..=6 {
        s.step_all(&mut f);
        assert_eq!(s.state(0), SvcState::Running, "still RUNNING after loop step {k}");
    }
    assert_eq!(s.runtime(0).consecutive, 2);
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Failed, "FAILED at the 7th loop step, the third overrun");
    assert_eq!((s.runtime(0).overruns, s.runtime(0).unmeasured), (3, 4));
}

#[test]
fn p6d_negative_control_a_verified_good_step_between_them() {
    let (mut s, mut f) = start(vec![T::Good, T::Over, T::Over, T::Good, T::Over, T::Good], Fail::None);
    for _ in 0..5 {
        s.step_all(&mut f);
        assert_eq!(s.state(0), SvcState::Running);
    }
    let r = s.runtime(0);
    assert_eq!((r.overruns, r.consecutive), (3, 0), "three overruns in total, never three without a good step between");
}

// ------------------------------------------------------------------ (7) functional readiness failure, independent of timing

#[test]
fn p7a_functional_readiness_failure_is_failed_whatever_the_probe_timing() {
    let cases = [
        (Fail::ReadyErr, "SVC_TEST_NOT_READY", "SVC_READINESS_FAILED"),
        (Fail::Contradicted, "SVC_READINESS_CONTRADICTED", "SVC_READINESS_CONTRADICTED"),
        (Fail::ZeroUnits, "SVC_READINESS_CONTRADICTED", "SVC_READINESS_CONTRADICTED"),
        (Fail::ProbeError, "SVC_TEST_PROBE_ERROR", "SVC_READINESS_FAILED"),
        (Fail::StartError, "SVC_TEST_START_ERROR", "SVC_READINESS_FAILED"),
    ];
    for timing in [T::Good, T::Over, T::Unm] {
        for (fail, ready_diag, fail_diag) in cases {
            let (s, f) = start(vec![timing], fail);
            let what = format!("{fail:?} with a {timing:?} probe");
            assert_eq!(s.state(0), SvcState::Failed, "{what}");
            assert!(!entered_running(&f), "{what}: never RUNNING");
            assert_eq!(ready(&f), None, "{what}: no readiness line");
            assert!(f.log.contains(&Report::ReadyFail { idx: 0, diag: ready_diag }), "{what}");
            assert_eq!(failed_with(&f), Some(fail_diag), "{what}");
            let r = s.runtime(0);
            assert_eq!((r.overruns, r.unmeasured, r.good), (0, 0, 0), "{what}: the timing was neither credited nor charged");
            let st = s.status(0, ClockTrust::Ok, Some(100));
            assert_eq!((st.status, st.liveness), (Status::Unavailable, Liveness::Lost), "{what}");
            assert_eq!(f.calls, if fail == Fail::StartError { 0 } else { 1 }, "{what}");
        }
    }
}

#[test]
fn p7b_contract_violation_in_the_probe_is_failed_whatever_the_timing() {
    for timing in [T::Good, T::Over, T::Unm] {
        let (s, f) = start(vec![timing], Fail::OverBudgetUnits);
        assert_eq!(s.state(0), SvcState::Failed, "{timing:?}");
        assert_eq!(failed_with(&f), Some("SVC_CONTRACT_VIOLATION"), "{timing:?}");
        assert!(!entered_running(&f) && ready(&f).is_none(), "{timing:?}");
    }
}

// ------------------------------------------------------------------ an unmeasured step never refreshes availability

#[test]
fn p8_an_unmeasured_step_never_refreshes_availability() {
    let (mut s, mut f) = start(vec![T::Good, T::Good, T::Unm], Fail::None);
    f.now = Some(200);
    s.step_all(&mut f);
    assert_eq!(s.runtime(0).last_step_ms, Some(200));
    f.now = Some(900);
    s.step_all(&mut f);
    assert_eq!(s.runtime(0).last_step_ms, Some(200), "an unmeasured step is not a fresh observation");
    assert_eq!(s.status(0, ClockTrust::Ok, Some(900)).status, Status::Available, "within 1,000 ms of the last measured step");
    f.now = Some(1_300);
    s.step_all(&mut f);
    let st = s.status(0, ClockTrust::Ok, Some(1_300));
    assert_eq!((st.status, st.reason), (Status::Unknown, Some(PublicReason::ObservationStale)));
    assert_eq!(s.state(0), SvcState::Running);
}
