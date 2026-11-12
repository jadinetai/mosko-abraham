//! 0.32b hosted tests for the four corrections (D-ABR-020). Label: SIMULATED.
//! B01-B04: finding 1 (dependent shutdown, also within one cycle). B05-B07: finding 2 (recovery accounting).
//! B08-B13: finding 3 (probe timing). Each correction has at least one negative control (a healthy case that must
//! not be affected).

use abraham_frame_hosttest::svclife::SvcState;
use abraham_frame_hosttest::svcregistry::{Desc, Kind, ServiceId};
use abraham_frame_hosttest::svcrun::*;
use abraham_frame_hosttest::svcstatus::{ClockTrust, Liveness, PublicReason, Status};
use abraham_frame_hosttest::svctable;
use std::boxed::Box;
use std::vec;
use std::vec::Vec;

#[derive(Clone)]
struct B {
    calls: u64,
    value: u64,
    /// TSC counts per call (1 MHz); the last value repeats; None = the TSC goes back one count.
    cost: Vec<Option<u64>>,
    fail_at: Option<u64>,
    stops: u64,
}

struct F {
    tsc: u64,
    now: Option<u64>,
    b: Vec<B>,
    log: Vec<Report>,
    stop_order: Vec<usize>,
    /// (cycle, idx) of every step call, to see which entries ran in which cycle.
    trace: Vec<(u64, usize)>,
    cycle: u64,
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
        self.trace.push((self.cycle, i));
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
    fn svc_stop(&mut self, i: usize) -> Result<(), &'static str> {
        self.b[i].stops += 1;
        self.stop_order.push(i);
        Ok(())
    }
    fn report(&mut self, _t: &[Desc], r: Report) {
        self.log.push(r);
    }
}

fn table(entries: &[(u8, &'static str, &[u8])]) -> &'static [Desc] {
    let v: Vec<Desc> = entries.iter().map(|&(id, name, deps)| Desc {
        id: ServiceId(id),
        name,
        kind: Kind::Service,
        installed: true,
        deps: Box::leak(deps.iter().map(|&x| ServiceId(x)).collect::<Vec<_>>().into_boxed_slice()),
        budget: 1,
    }).collect();
    Box::leak(v.into_boxed_slice())
}

fn host(n: usize) -> F {
    F { tsc: 1_000, now: Some(100), b: vec![B { calls: 0, value: 0, cost: vec![Some(5)], fail_at: None, stops: 0 }; n],
        log: Vec::new(), stop_order: Vec::new(), trace: Vec::new(), cycle: 0 }
}

fn cycle(s: &mut ServiceSet, f: &mut F) {
    f.cycle += 1;
    s.step_all(f);
}

fn stepped_in(f: &F, c: u64) -> Vec<usize> {
    f.trace.iter().filter(|(k, _)| *k == c).map(|&(_, i)| i).collect()
}

// ------------------------------------------------------------------ finding 1

#[test]
fn b01_three_level_chain_no_dependent_steps_in_the_failing_cycle() {
    // a <- b <- c, and d independent; a fails on its 3rd call (probe + 2 loop steps)
    let t = table(&[(1, "svc.a", &[]), (2, "svc.b", &[1]), (3, "svc.c", &[2]), (4, "svc.d", &[])]);
    let mut f = host(4);
    f.b[0].fail_at = Some(3);
    let mut s = ServiceSet::new(t);
    assert_eq!(s.start_all(&mut f), StartResult::Started);
    cycle(&mut s, &mut f); // cycle 1: all four step
    assert_eq!(stepped_in(&f, 1), vec![0, 1, 2, 3]);
    cycle(&mut s, &mut f); // cycle 2: a fails; b and c must not step; d does
    assert_eq!(stepped_in(&f, 2), vec![0, 3], "only the failing entry and the independent one ran in that cycle");
    assert_eq!((s.state(0), s.state(1), s.state(2), s.state(3)),
               (SvcState::Failed, SvcState::Stopped, SvcState::Stopped, SvcState::Running));
    assert_eq!(f.stop_order, vec![2, 1], "dependents first: c, then b");
    for _ in 0..50 {
        cycle(&mut s, &mut f);
    }
    assert_eq!((f.b[1].calls, f.b[2].calls), (2, 2), "probe + 1 loop step each, never again");
    assert_eq!(f.b[3].calls, 53, "the independent entry keeps running");
}

#[test]
fn b02_the_order_not_the_table_position_decides() {
    // the dependent is listed first in the table; the order still puts its dependency first
    let t = table(&[(5, "svc.dep", &[6]), (6, "svc.base", &[])]);
    let mut f = host(2);
    f.b[1].fail_at = Some(2);
    let mut s = ServiceSet::new(t);
    s.start_all(&mut f);
    cycle(&mut s, &mut f); // base fails on its first loop step
    assert_eq!(stepped_in(&f, 1), vec![1], "the dependent is not stepped after its dependency failed");
    assert_eq!(s.state(0), SvcState::Stopped);
}

#[test]
fn b03_dependent_shutdown_accounting() {
    let t = table(&[(1, "svc.a", &[]), (2, "svc.b", &[1])]);
    let mut f = host(2);
    f.b[0].fail_at = Some(4);
    let mut s = ServiceSet::new(t);
    s.start_all(&mut f);
    for _ in 0..3 {
        cycle(&mut s, &mut f);
    }
    let r = s.runtime(1);
    assert_eq!(f.b[1].stops, 1, "the stop hook ran exactly once");
    assert_eq!((r.steps, r.units, f.b[1].value), (2, 3, 3), "2 loop steps + the probe, no step after the failure");
    assert_eq!(r.steps, s.runtime(0).steps, "the dependent did not step more often than its dependency's good steps");
    let tr: Vec<(SvcState, Option<&str>)> = f.log.iter().filter_map(|x| match x {
        Report::Transition { idx: 1, t, diag } => Some((t.to, *diag)),
        _ => None,
    }).collect();
    assert_eq!(tr, vec![(SvcState::Starting, None), (SvcState::Running, None), (SvcState::Stopping, Some("SVC_DEPENDENCY_LOST")),
                        (SvcState::Stopped, None)]);
    let st = s.status(1, ClockTrust::Ok, Some(100));
    assert_eq!((st.status, st.reason, st.liveness), (Status::Unavailable, None, Liveness::Unknown));
}

#[test]
fn b04_negative_control_healthy_dependency_never_blocks() {
    let t = table(&[(1, "svc.a", &[]), (2, "svc.b", &[1]), (3, "svc.c", &[2])]);
    let mut f = host(3);
    let mut s = ServiceSet::new(t);
    s.start_all(&mut f);
    for _ in 0..200 {
        cycle(&mut s, &mut f);
    }
    assert!(f.b.iter().all(|b| b.calls == 201 && b.stops == 0), "every entry stepped in every cycle");
    assert!((0..3).all(|i| s.state(i) == SvcState::Running));
    assert!(!f.log.iter().any(|r| matches!(r, Report::Transition { t, .. } if t.to == SvcState::Stopping)));
}

// ------------------------------------------------------------------ finding 2

fn one(cost: Vec<Option<u64>>) -> (ServiceSet, F) {
    let t = table(&[(1, "svc.a", &[])]);
    let mut f = host(1);
    f.b[0].cost = cost;
    let mut s = ServiceSet::new(t);
    s.start_all(&mut f);
    (s, f)
}

#[test]
fn b05_recovery_needs_100_consecutive_good_steps_after_an_unmeasured_one() {
    let over = Some(STEP_BUDGET_US + 1);
    let mut cost = vec![Some(5), over];
    cost.extend(core::iter::repeat(Some(5)).take(99));
    cost.push(None);
    cost.extend(core::iter::repeat(Some(5)).take(99));
    let (mut s, mut f) = one(cost);
    for _ in 0..(1 + 99 + 1 + 99) {
        cycle(&mut s, &mut f);
    }
    assert!(s.runtime(0).overrun_window, "99 good steps after the unmeasured one are not enough");
    assert_eq!(s.runtime(0).good, 99);
    cycle(&mut s, &mut f); // the 100th consecutive good step
    assert!(!s.runtime(0).overrun_window);
    assert_eq!(f.log.iter().filter(|r| matches!(r, Report::Recovered { .. })).count(), 1);
}

#[test]
fn b06_unmeasured_step_does_not_excuse_overruns() {
    // overrun, unmeasured, overrun, overrun: the unmeasured step is neither a success nor an overrun, so the
    // consecutive overrun count goes on and the third overrun fails the entry.
    let over = Some(STEP_BUDGET_US + 1);
    let (mut s, mut f) = one(vec![Some(5), over, None, over, over]);
    for _ in 0..4 {
        cycle(&mut s, &mut f);
    }
    assert_eq!(s.state(0), SvcState::Failed);
    let r = s.runtime(0);
    assert_eq!((r.overruns, r.unmeasured, r.consecutive), (3, 1, 3));
}

#[test]
fn b07_negative_control_without_unmeasured_steps_recovery_is_unchanged() {
    let mut cost = vec![Some(5), Some(STEP_BUDGET_US + 1)];
    cost.extend(core::iter::repeat(Some(5)).take(100));
    let (mut s, mut f) = one(cost);
    for _ in 0..100 {
        cycle(&mut s, &mut f);
    }
    assert!(s.runtime(0).overrun_window, "after 99 good steps");
    cycle(&mut s, &mut f);
    assert!(!s.runtime(0).overrun_window, "after 100 good steps, as in 0.32");
}

// ------------------------------------------------------------------ finding 3

fn ready_timing(f: &F) -> Option<StepTiming> {
    f.log.iter().find_map(|r| match r {
        Report::Ready { timing, .. } => Some(*timing),
        _ => None,
    })
}

#[test]
fn b08_step_timing_boundaries() {
    assert_eq!(StepTiming::of(None), StepTiming::Unmeasured);
    assert_eq!(StepTiming::of(Some(0)), StepTiming::InBudget);
    assert_eq!(StepTiming::of(Some(STEP_BUDGET_US)), StepTiming::InBudget);
    assert_eq!(StepTiming::of(Some(STEP_BUDGET_US + 1)), StepTiming::Overrun);
    let names: Vec<&str> = [StepTiming::InBudget, StepTiming::Overrun, StepTiming::Unmeasured].iter().map(|t| t.name()).collect();
    assert_eq!(names, ["IN_BUDGET", "OVERRUN", "UNMEASURED"]);
}

#[test]
fn b09_negative_control_probe_in_budget_is_available() {
    let (s, f) = one(vec![Some(5)]);
    assert_eq!(ready_timing(&f), Some(StepTiming::InBudget));
    let r = s.runtime(0);
    assert_eq!((r.overruns, r.unmeasured, r.good, r.overrun_window), (0, 0, 1, false));
    assert_eq!(s.status(0, ClockTrust::Ok, Some(100)).status, Status::Available);
    assert!(!f.log.iter().any(|x| matches!(x, Report::Overrun { .. } | Report::Degraded { .. } | Report::Unmeasured { .. })));
}

#[test]
fn b10_probe_overrun_is_the_first_overrun_degraded_not_available() {
    let (mut s, mut f) = one(vec![Some(20_000)]);
    assert_eq!(ready_timing(&f), Some(StepTiming::Overrun));
    assert_eq!(s.state(0), SvcState::Running, "readiness itself held: correct work, too slow");
    let st = s.status(0, ClockTrust::Ok, Some(100));
    assert_eq!((st.status, st.reason, st.liveness), (Status::Degraded, None, Liveness::Live));
    let kinds: Vec<&str> = f.log.iter().map(|r| match r {
        Report::RegistryOk { .. } => "REGISTRY_OK",
        Report::Transition { t, .. } if t.to == SvcState::Starting => "STARTING",
        Report::Ready { .. } => "READY",
        Report::Transition { t, .. } if t.to == SvcState::Running => "RUNNING",
        Report::Overrun { consecutive: 1, .. } => "OVERRUN1",
        Report::Degraded { .. } => "DEGRADED",
        _ => "OTHER",
    }).collect();
    assert_eq!(kinds, ["REGISTRY_OK", "STARTING", "READY", "RUNNING", "OVERRUN1", "DEGRADED"]);
    // the probe counts: 2 more overruns in a row make 3, and the entry fails after only 2 loop steps
    cycle(&mut s, &mut f);
    assert_eq!(s.state(0), SvcState::Running);
    cycle(&mut s, &mut f);
    assert_eq!(s.state(0), SvcState::Failed);
    assert_eq!((s.runtime(0).steps, s.runtime(0).overruns), (2, 3));
}

#[test]
fn b11_probe_overrun_then_100_good_steps_recover() {
    let (mut s, mut f) = one(vec![Some(20_000), Some(5)]);
    for _ in 0..99 {
        cycle(&mut s, &mut f);
    }
    assert_eq!(s.status(0, ClockTrust::Ok, Some(100)).status, Status::Degraded);
    cycle(&mut s, &mut f);
    assert_eq!(s.status(0, ClockTrust::Ok, Some(100)).status, Status::Available);
}

#[test]
fn b12_unmeasured_probe_is_not_a_fresh_success() {
    let (mut s, mut f) = one(vec![None, Some(5)]);
    assert_eq!(ready_timing(&f), Some(StepTiming::Unmeasured));
    assert_eq!(s.state(0), SvcState::Running);
    let r = s.runtime(0);
    assert_eq!((r.unmeasured, r.good, r.last_step_ms), (1, 0, None));
    let st = s.status(0, ClockTrust::Ok, Some(100));
    assert_eq!((st.status, st.reason, st.liveness), (Status::Unknown, Some(PublicReason::ObservationStale), Liveness::Stale));
    cycle(&mut s, &mut f); // the first measured, in-budget step
    assert_eq!(s.status(0, ClockTrust::Ok, Some(100)).status, Status::Available);
}

#[test]
fn b13_production_counter_probe_is_in_budget() {
    let mut f = host(3);
    let mut s = ServiceSet::new(svctable::PRODUCTION);
    s.start_all(&mut f);
    assert_eq!(ready_timing(&f), Some(StepTiming::InBudget));
    assert_eq!(s.status(1, ClockTrust::Ok, Some(100)).status, Status::Available);
}
