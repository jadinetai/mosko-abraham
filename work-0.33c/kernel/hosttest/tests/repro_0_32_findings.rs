//! 0.32b reproduction tests for the audit findings 1-3 (D-ABR-020). Label: SIMULATED.
//! Each test states the CORRECTED behavior and uses only interfaces that already exist in 0.32, so the same file
//! compiles against the unchanged 0.32 sources (run ABR-0.32b-X001: every test must FAIL there, which reproduces the
//! defect) and against the corrected 0.32b sources (H001: every test must PASS).

use abraham_frame_hosttest::svclife::SvcState;
use abraham_frame_hosttest::svcregistry::{Desc, Kind, ServiceId};
use abraham_frame_hosttest::svcrun::{Host, Report, ServiceSet, StartResult, StepOutcome, RECOVER_AFTER_GOOD, STEP_BUDGET_US};
use abraham_frame_hosttest::svcstatus::{ClockTrust, Status};
use std::boxed::Box;
use std::vec;
use std::vec::Vec;

/// One scripted entry: `cost[n]` TSC counts (1 MHz) for its n-th call (the last value repeats; None = the TSC goes
/// back by one count during the step); `fail_at` = the call number from which the step returns an error.
#[derive(Clone)]
struct B {
    calls: u64,
    value: u64,
    cost: Vec<Option<u64>>,
    fail_at: Option<u64>,
}

struct F {
    tsc: u64,
    now: Option<u64>,
    b: Vec<B>,
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
        Ok(())
    }
    fn svc_step(&mut self, i: usize, _budget: u32) -> StepOutcome {
        let b = &mut self.b[i];
        b.calls += 1;
        let k = core::cmp::min((b.calls - 1) as usize, b.cost.len() - 1);
        match b.cost[k] {
            Some(c) => self.tsc += c,
            None => self.tsc -= 1,
        }
        if let Some(n) = b.fail_at {
            if b.calls >= n {
                return StepOutcome::Error("SVC_TEST_STEP_ERROR");
            }
        }
        b.value += 1;
        StepOutcome::Done { units: 1 }
    }
    fn svc_ready(&mut self, _i: usize) -> Result<(), &'static str> {
        Ok(())
    }
    fn svc_observed(&self, i: usize) -> Option<u64> {
        Some(self.b[i].value)
    }
    fn svc_stop(&mut self, _i: usize) -> Result<(), &'static str> {
        Ok(())
    }
    fn report(&mut self, _t: &[Desc], r: Report) {
        self.log.push(r);
    }
}

fn table(deps: &[&[u8]]) -> &'static [Desc] {
    let names = ["svc.a", "svc.b", "svc.c", "svc.d"];
    let v: Vec<Desc> = deps.iter().enumerate().map(|(i, d)| Desc {
        id: ServiceId(i as u8 + 1),
        name: names[i],
        kind: Kind::Service,
        installed: true,
        deps: Box::leak(d.iter().map(|&x| ServiceId(x)).collect::<Vec<_>>().into_boxed_slice()),
        budget: 1,
    }).collect();
    Box::leak(v.into_boxed_slice())
}

fn host(n: usize) -> F {
    F { tsc: 1_000, now: Some(100), b: vec![B { calls: 0, value: 0, cost: vec![Some(5)], fail_at: None }; n], log: Vec::new() }
}

/// Finding 1: svc.b depends on svc.a. svc.a fails on its 3rd call (probe + 2 loop steps): in that same cycle, svc.b
/// must not be stepped any more. The corrected manager also never steps a dependent whose dependency is not RUNNING.
#[test]
fn r1_dependent_not_stepped_after_its_dependency_failed_in_the_same_cycle() {
    let t = table(&[&[], &[1]]);
    let mut f = host(2);
    f.b[0].fail_at = Some(3);
    let mut s = ServiceSet::new(t);
    assert_eq!(s.start_all(&mut f), StartResult::Started);
    s.step_all(&mut f); // a: call 2 ok; b: call 2
    let b_calls = f.b[1].calls;
    s.step_all(&mut f); // a: call 3 fails -> b must not run in this cycle
    assert_eq!(s.state(0), SvcState::Failed);
    assert_eq!(f.b[1].calls, b_calls, "the dependent ran a step after its dependency had left RUNNING");
    assert_eq!(s.state(1), SvcState::Stopped);
}

/// Finding 2: after an overrun, 99 good steps, one unmeasured step and one more good step must NOT end the overrun
/// window: the unmeasured step breaks the consecutive streak. 100 good steps after it do.
#[test]
fn r2_unmeasured_step_breaks_the_recovery_streak() {
    let t = table(&[&[]]);
    let mut f = host(1);
    let mut s = ServiceSet::new(t);
    s.start_all(&mut f);
    let mut cost = vec![Some(5), Some(STEP_BUDGET_US + 1)];
    cost.extend(core::iter::repeat(Some(5)).take((RECOVER_AFTER_GOOD - 1) as usize));
    cost.push(None);
    cost.push(Some(5));
    let steps = cost.len() - 1; // the first entry was the probe
    f.b[0].cost = cost;
    for _ in 0..steps {
        s.step_all(&mut f);
    }
    assert!(s.runtime(0).overrun_window, "recovered although an unmeasured step interrupted the streak");
    f.b[0].cost.push(Some(5));
    for _ in 0..RECOVER_AFTER_GOOD - 1 {
        s.step_all(&mut f);
    }
    assert!(!s.runtime(0).overrun_window, "100 consecutive good steps after the unmeasured one recover");
}

/// Finding 3: a probe step that overran its time budget is measured like every step. The service must not be
/// reported AVAILABLE right after it, and the overrun must be counted.
#[test]
fn r3_probe_overrun_is_counted_and_never_reported_available() {
    let t = table(&[&[]]);
    let mut f = host(1);
    f.b[0].cost = vec![Some(20_000), Some(5)];
    let mut s = ServiceSet::new(t);
    s.start_all(&mut f);
    let st = s.status(0, ClockTrust::Ok, Some(100));
    assert_ne!(st.status, Status::Available, "a 20 ms probe against a 1 ms budget was reported AVAILABLE");
    assert_eq!(s.runtime(0).overruns, 1, "the probe overrun was not counted");
    assert!(f.log.iter().any(|r| matches!(r, Report::Overrun { idx: 0, .. })), "the probe overrun was not reported");
}

/// Finding 3: a probe whose duration could not be measured is not a measured, in-budget success. The service must
/// not be reported AVAILABLE on it.
#[test]
fn r4_unmeasured_probe_is_never_reported_available() {
    let t = table(&[&[]]);
    let mut f = host(1);
    f.b[0].cost = vec![None, Some(5)];
    let mut s = ServiceSet::new(t);
    s.start_all(&mut f);
    let st = s.status(0, ClockTrust::Ok, Some(100));
    assert_ne!(st.status, Status::Available, "an unmeasured probe was reported AVAILABLE");
    assert_eq!(s.runtime(0).unmeasured, 1, "the unmeasured probe was not counted");
}
