//! 0.32 hosted tests (D-ABR-019): closed registry, service lifecycle, manager, status mapping, public reasons,
//! INSPECT_PUBLIC, SERVICE events. Label: SIMULATED. Test names start with the design §7 matrix id they serve.
//! The kernel's own source files are compiled here unchanged (src/lib.rs).

use abraham_frame_hosttest::events::{EventLog, Kind as EvKind, CAPACITY};
use abraham_frame_hosttest::svc_counter::Counter;
use abraham_frame_hosttest::svclife::*;
use abraham_frame_hosttest::svcregistry::*;
use abraham_frame_hosttest::svcrun::*;
use abraham_frame_hosttest::svcstatus::*;
use abraham_frame_hosttest::svctable;
use std::boxed::Box;
use std::string::String;
use std::vec;
use std::vec::Vec;

// ------------------------------------------------------------------ helpers

fn leak_deps(d: &[u8]) -> &'static [ServiceId] {
    Box::leak(d.iter().map(|&x| ServiceId(x)).collect::<Vec<_>>().into_boxed_slice())
}

fn leak_name(s: &str) -> &'static str {
    Box::leak(String::from(s).into_boxed_str())
}

fn d(id: u8, name: &str, deps: &[u8]) -> Desc {
    Desc { id: ServiceId(id), name: leak_name(name), kind: Kind::Service, installed: true, deps: leak_deps(deps), budget: 1 }
}

fn leak_table(v: Vec<Desc>) -> &'static [Desc] {
    Box::leak(v.into_boxed_slice())
}

fn names(t: &[Desc], o: &Order) -> Vec<&'static str> {
    o.positions().iter().map(|&i| t[i as usize].name).collect()
}

/// A scripted behavior for one entry.
#[derive(Clone)]
struct Beh {
    start: Result<(), &'static str>,
    ready: Result<(), &'static str>,
    /// Units the step claims.
    units: u32,
    /// Whether the step really advances the observable state by the claimed units.
    honest: bool,
    /// Step number (1 = probe) from which the step returns an error.
    error_from: Option<u64>,
    /// TSC counts each step takes (1 MHz: 1 count = 1 us); a list cycles; `None` rewinds the TSC.
    cost: Vec<Option<u64>>,
    stop: Result<(), &'static str>,
    value: u64,
    calls: u64,
    observable: bool,
}

impl Beh {
    fn good() -> Beh {
        Beh { start: Ok(()), ready: Ok(()), units: 1, honest: true, error_from: None, cost: vec![Some(5)],
              stop: Ok(()), value: 0, calls: 0, observable: true }
    }
}

struct Fake {
    operational: bool,
    tsc: u64,
    now: Option<u64>,
    beh: Vec<Beh>,
    log: Vec<Report>,
    stops: Vec<usize>,
}

const HZ: u64 = 1_000_000;

impl Fake {
    fn new(n: usize) -> Fake {
        Fake { operational: true, tsc: 1_000, now: Some(100), beh: vec![Beh::good(); n], log: Vec::new(), stops: Vec::new() }
    }
    fn count(&self, f: impl Fn(&Report) -> bool) -> usize {
        self.log.iter().filter(|r| f(r)).count()
    }
}

impl Host for Fake {
    fn kernel_operational(&self) -> bool {
        self.operational
    }
    fn tsc(&mut self) -> u64 {
        self.tsc
    }
    fn tsc_hz(&self) -> u64 {
        HZ
    }
    fn uptime_ms(&mut self) -> Option<u64> {
        self.now
    }
    fn svc_start(&mut self, idx: usize) -> Result<(), &'static str> {
        self.beh[idx].start
    }
    fn svc_step(&mut self, idx: usize, _budget: u32) -> StepOutcome {
        let b = &mut self.beh[idx];
        b.calls += 1;
        let cost = b.cost[((b.calls - 1) as usize) % b.cost.len()];
        match cost {
            Some(c) => self.tsc += c,
            None => self.tsc -= 1,
        }
        if let Some(n) = b.error_from {
            if b.calls >= n {
                return StepOutcome::Error("SVC_TEST_STEP_ERROR");
            }
        }
        if b.honest {
            b.value += b.units as u64;
        }
        StepOutcome::Done { units: b.units }
    }
    fn svc_ready(&mut self, idx: usize) -> Result<(), &'static str> {
        self.beh[idx].ready
    }
    fn svc_observed(&self, idx: usize) -> Option<u64> {
        if self.beh[idx].observable { Some(self.beh[idx].value) } else { None }
    }
    fn svc_stop(&mut self, idx: usize) -> Result<(), &'static str> {
        self.stops.push(idx);
        self.beh[idx].stop
    }
    fn report(&mut self, _t: &[Desc], r: Report) {
        self.log.push(r);
    }
}

fn started(t: &'static [Desc], f: &mut Fake) -> ServiceSet {
    let mut s = ServiceSet::new(t);
    assert_eq!(s.start_all(f), StartResult::Started);
    s
}

// ------------------------------------------------------------------ S01 production and diagnostic tables

#[test]
fn s01_production_table_valid_unique_and_ordered() {
    let t = svctable::PRODUCTION;
    let o = validate(t).expect("production table valid");
    assert_eq!(names(t, &o), ["dev.net0", "svc.counter", "svc.netmon"]);
    assert_eq!(t.len(), 3);
    for (i, a) in t.iter().enumerate() {
        assert!(name_ok(a.name), "{}", a.name);
        for b in &t[i + 1..] {
            assert_ne!(a.id, b.id);
            assert_ne!(a.name, b.name);
        }
    }
    assert!(!t[0].installed && t[0].kind == Kind::Adapter, "dev.net0 is a not-installed adapter");
    assert_eq!(t[2].deps, &[svctable::DEV_NET0], "svc.netmon depends on dev.net0 only");
    assert_eq!(validate(svctable::TABLE), validate(svctable::PRODUCTION), "the hosted build sees the production table");
}

#[test]
fn s01_diagnostic_tables_valid_except_the_cyclic_one() {
    for t in [svctable::DIAG_DEFECTS, svctable::DIAG_SLOW, svctable::DIAG_STALL] {
        assert!(validate(t).is_ok());
    }
    let e = validate(svctable::DIAG_CYCLE).unwrap_err();
    assert_eq!(e.fault, RegFault::Cycle);
    assert_eq!(e.code(), "SVC_DEPENDENCY_CYCLE");
}

// ------------------------------------------------------------------ S02 each refusal

#[test]
fn s02_each_validation_refusal_has_its_own_code() {
    let ok = vec![d(1, "svc.a", &[]), d(2, "svc.b", &[1])];
    assert!(validate(&ok).is_ok());
    let mut cases: Vec<(&str, Vec<Desc>, RegFault)> = Vec::new();
    cases.push(("duplicate id", vec![d(1, "svc.a", &[]), d(1, "svc.b", &[])], RegFault::DuplicateId));
    cases.push(("duplicate name", vec![d(1, "svc.a", &[]), d(2, "svc.a", &[])], RegFault::DuplicateName));
    cases.push(("unknown dependency", vec![d(1, "svc.a", &[9])], RegFault::UnknownDependency));
    cases.push(("self dependency", vec![d(1, "svc.a", &[1])], RegFault::SelfDependency));
    cases.push(("duplicate dependency", vec![d(1, "svc.a", &[]), d(2, "svc.b", &[1, 1])], RegFault::DuplicateDependency));
    cases.push(("too many dependencies", vec![d(1, "svc.a", &[]), d(2, "svc.b", &[]), d(3, "svc.c", &[]), d(4, "svc.d", &[]),
                                             d(5, "svc.e", &[]), d(6, "svc.f", &[1, 2, 3, 4, 5])], RegFault::TooManyDependencies));
    cases.push(("too many entries", (1..=9).map(|i| d(i, &std::format!("svc.s{i}"), &[])).collect(), RegFault::TooMany));
    let mut big = d(1, "svc.a", &[]);
    big.budget = MAX_WORK_UNITS + 1;
    cases.push(("budget above maximum", vec![big], RegFault::BudgetTooLarge));
    let mut at_max = d(1, "svc.a", &[]);
    at_max.budget = MAX_WORK_UNITS;
    assert!(validate(&[at_max]).is_ok(), "the maximum itself is allowed");
    let mut codes = Vec::new();
    for (what, table, fault) in &cases {
        let copy: Vec<Desc> = table.clone();
        let e = validate(table).unwrap_err();
        assert_eq!(e.fault, *fault, "{what}");
        codes.push(e.code());
        // pure: the table is unchanged, and validating again gives the same answer
        assert!(table.iter().zip(&copy).all(|(a, b)| a.id == b.id && a.name == b.name && a.deps == b.deps));
        assert_eq!(validate(table), Err(e));
    }
    codes.sort();
    codes.dedup();
    assert_eq!(codes.len(), cases.len(), "every refusal has its own code");
    assert_eq!(validate(&[d(1, "svc.", &[])]).unwrap_err().code(), "SVC_NAME_MALFORMED");
}

#[test]
fn s02_malformed_names_refused() {
    // The design listed 9 names; the mutation check (M05) showed that none of them had an upper-case letter or an
    // underscore after a valid prefix, so a grammar that admits those survived. Two names were added for that.
    let thirty_two = "svc.abcdefghijklmnopqrstuvwxyz01";
    assert_eq!(thirty_two.len(), 32);
    let bad = ["", "svc", "svc.", ".svc.x", "svc..x", "SVC.counter", "svc.count*", "net.link0", thirty_two,
               "svc.Counter", "svc.a_b"];
    assert_eq!(bad.len(), 11);
    for n in bad {
        assert!(!name_ok(n), "{n:?} must be refused");
        assert_eq!(validate(&[d(1, n, &[])]).unwrap_err().fault, RegFault::NameMalformed, "{n:?}");
    }
    for n in ["svc.counter", "svc.netmon", "dev.net0", "svc.a.b2", "svc.abcdefghijklmnopqrstuvwxyz0"] {
        assert!(name_ok(n), "{n:?} is well formed");
    }
}

// ------------------------------------------------------------------ S03 cycles

#[test]
fn s03_cycles_refused_with_no_order() {
    let two = vec![d(1, "svc.a", &[2]), d(2, "svc.b", &[1])];
    let three = vec![d(1, "svc.a", &[3]), d(2, "svc.b", &[1]), d(3, "svc.c", &[2])];
    let behind = vec![d(1, "svc.root", &[]), d(2, "svc.x", &[1]), d(3, "svc.y", &[2, 4]), d(4, "svc.z", &[3])];
    for t in [&two, &three, &behind] {
        let e = validate(t).unwrap_err();
        assert_eq!((e.fault, e.code()), (RegFault::Cycle, "SVC_DEPENDENCY_CYCLE"));
    }
    assert_eq!(validate(&behind).unwrap_err().entry, 2, "the first entry that could not be placed");
    // the boot-time manager refuses the cyclic diagnostic table and starts nothing
    let mut f = Fake::new(svctable::DIAG_CYCLE.len());
    let mut s = ServiceSet::new(svctable::DIAG_CYCLE);
    assert_eq!(s.start_all(&mut f), StartResult::RegistryRefused);
    assert!(matches!(s.registry(), Registry::Refused(e) if e.fault == RegFault::Cycle));
    assert_eq!(f.count(|r| matches!(r, Report::Transition { .. })), 0, "no service started");
    for i in 0..svctable::DIAG_CYCLE.len() {
        assert_eq!(s.state(i), SvcState::Declared);
        let st = s.status(i, ClockTrust::Ok, Some(200));
        assert_eq!(st.status, Status::Unavailable);
    }
    s.step_all(&mut f);
    assert!(f.beh.iter().all(|b| b.calls == 0), "nothing is ever stepped");
}

// ------------------------------------------------------------------ S04 determinism

fn permutations(v: &mut Vec<Desc>, k: usize, out: &mut Vec<Vec<Desc>>) {
    if k == v.len() {
        out.push(v.clone());
        return;
    }
    for i in k..v.len() {
        v.swap(k, i);
        permutations(v, k + 1, out);
        v.swap(k, i);
    }
}

#[test]
fn s04_order_is_identical_for_all_120_permutations() {
    // a diamond plus a free entry: 5 -> {3, 4} -> 1, and 2 alone
    let base = vec![d(1, "svc.base", &[]), d(2, "svc.free", &[]), d(3, "svc.left", &[1]), d(4, "svc.right", &[1]),
                    d(5, "svc.top", &[3, 4])];
    let mut all = Vec::new();
    permutations(&mut base.clone(), 0, &mut all);
    assert_eq!(all.len(), 120);
    let want = ["svc.base", "svc.free", "svc.left", "svc.right", "svc.top"];
    for p in &all {
        let o = validate(p).unwrap();
        assert_eq!(names(p, &o), want);
        assert_eq!(validate(p).unwrap(), o, "repeatable");
    }
}

// ------------------------------------------------------------------ S05 exact lookup

#[test]
fn s05_exact_lookup_and_twelve_near_misses() {
    let t = svctable::PRODUCTION;
    assert_eq!(lookup(t, "dev.net0"), Some(0));
    assert_eq!(lookup(t, "svc.counter"), Some(1));
    assert_eq!(lookup(t, "svc.netmon"), Some(2));
    let near = ["svc.counte", "svc.counterx", "SVC.COUNTER", "svc.Counter", "svc.*", "svc.counter.", " svc.counter",
                "svc.counter ", "", "svc", "counter", "svc.counter\0"];
    assert_eq!(near.len(), 12);
    let mut f = Fake::new(3);
    let s = started(t, &mut f);
    for n in near {
        assert_eq!(lookup(t, n), None, "{n:?}");
        assert_eq!(s.inspect_public("status", n, ClockTrust::Ok, Some(200)), Err(PublicReason::TargetUnknown), "{n:?}");
    }
    // an unknown name is not an attack (P-33): every status still reads NONE_KNOWN
    for i in 0..3 {
        assert_eq!(s.status(i, ClockTrust::Ok, Some(200)).compromise(), Compromise::NoneKnown);
    }
}

// ------------------------------------------------------------------ S06 lifecycle matrix

fn life_in(state: SvcState) -> SvcLife {
    let mut l = SvcLife::new();
    let path: &[SvcState] = match state {
        SvcState::Declared => &[],
        SvcState::Starting => &[SvcState::Starting],
        SvcState::Running => &[SvcState::Starting, SvcState::Running],
        SvcState::Stopping => &[SvcState::Starting, SvcState::Running, SvcState::Stopping],
        SvcState::Stopped => &[SvcState::Starting, SvcState::Running, SvcState::Stopping, SvcState::Stopped],
        SvcState::Failed => &[SvcState::Starting, SvcState::Failed],
    };
    for &s in path {
        l.advance(s).unwrap();
    }
    l
}

#[test]
fn s06_all_36_pairs_exactly_7_allowed_2_reserved() {
    let mut allowed_n = 0;
    let mut reserved_n = 0;
    for from in ALL_STATES {
        for to in ALL_STATES {
            let mut l = life_in(from);
            let before = l;
            let r = l.advance(to);
            if allowed(from, to) {
                allowed_n += 1;
                let t = r.unwrap();
                assert_eq!((t.from, t.to, t.seq), (from, to, before.seq() + 1));
                assert_eq!(l.state(), to);
            } else {
                assert_eq!(r, Err(Refused { from, to }));
                assert_eq!(r.unwrap_err().code(), "SVC_INVALID_TRANSITION");
                assert_eq!(l, before, "refusal leaves state and seq unchanged");
            }
            if reserved_reset(from, to) {
                reserved_n += 1;
                assert!(!allowed(from, to), "a reserved reset is never an ordinary transition");
            }
        }
    }
    assert_eq!((allowed_n, reserved_n, 36 - allowed_n - reserved_n), (7, 2, 27));
}

#[test]
fn s06_manual_reset_is_reserved_and_needs_a_token() {
    for from in ALL_STATES {
        let mut l = life_in(from);
        let before = l;
        let r = l.manual_reset(ManualReset::reviewed_operator_request());
        if from == SvcState::Stopped || from == SvcState::Failed {
            assert_eq!(r.unwrap().to, SvcState::Declared);
            assert_eq!(l.state(), SvcState::Declared);
        } else {
            assert!(r.is_err());
            assert_eq!(l, before);
        }
    }
    // the manager offers no reset at all: an external request for FAILED -> DECLARED is refused
    let t = leak_table(vec![d(1, "svc.a", &[])]);
    let mut f = Fake::new(1);
    f.beh[0].ready = Err("SVC_TEST_NOT_READY");
    let mut s = started(t, &mut f);
    assert_eq!(s.state(0), SvcState::Failed);
    assert!(!s.request(0, SvcState::Declared, &mut f));
    assert_eq!(s.state(0), SvcState::Failed, "FAILED is terminal for the boot");
}

// ------------------------------------------------------------------ S07 no premature start

#[test]
fn s07_no_start_before_operational_and_refusal_changes_nothing() {
    let mut f = Fake::new(3);
    f.operational = false;
    let mut s = ServiceSet::new(svctable::PRODUCTION);
    assert_eq!(s.start_all(&mut f), StartResult::NotOperational);
    assert_eq!(f.log, vec![Report::StartRefused { diag: "SVC_KERNEL_NOT_OPERATIONAL" }]);
    assert_eq!(s.registry(), Registry::NotChecked);
    for i in 0..3 {
        assert_eq!(s.runtime(i), Runtime::NEW);
    }
    s.step_all(&mut f);
    assert!(f.beh.iter().all(|b| b.calls == 0));
    // later, at OPERATIONAL, the same set starts normally
    f.operational = true;
    assert_eq!(s.start_all(&mut f), StartResult::Started);
    assert_eq!(s.state(1), SvcState::Running);
    // and a second start is refused
    assert_eq!(s.start_all(&mut f), StartResult::AlreadyStarted);
}

// ------------------------------------------------------------------ S08 dependencies

#[test]
fn s08_production_netmon_withheld_by_not_installed_adapter() {
    let mut f = Fake::new(3);
    let s = started(svctable::PRODUCTION, &mut f);
    assert_eq!(f.log[0], Report::RegistryOk { entries: 3, order: validate(svctable::PRODUCTION).unwrap() });
    assert_eq!(f.log[1], Report::NotInstalled { idx: 0 });
    assert_eq!((s.state(0), s.state(1), s.state(2)), (SvcState::Declared, SvcState::Running, SvcState::Declared));
    assert!(f.log.contains(&Report::Withheld { idx: 2, dep: 0, dep_state: SvcState::Declared }));
    assert_eq!(f.beh[0].calls + f.beh[2].calls, 0, "neither dev.net0 nor svc.netmon ever runs");
    for i in [0, 2] {
        let st = s.status(i, ClockTrust::Ok, Some(200));
        assert_eq!((st.status, st.reason, st.liveness), (Status::Unavailable, Some(PublicReason::NotInstalled), Liveness::Unknown));
    }
    let c = s.status(1, ClockTrust::Ok, Some(200));
    assert_eq!((c.status, c.reason, c.liveness), (Status::Available, None, Liveness::Live));
}

#[test]
fn s08_withheld_by_a_failed_dependency_has_no_public_reason() {
    let t = leak_table(vec![d(1, "svc.a", &[]), d(2, "svc.b", &[1])]);
    let mut f = Fake::new(2);
    f.beh[0].ready = Err("SVC_TEST_NOT_READY");
    let s = started(t, &mut f);
    assert_eq!((s.state(0), s.state(1)), (SvcState::Failed, SvcState::Declared));
    assert_eq!(f.beh[1].calls, 0, "the dependent never runs on an assumption");
    let st = s.status(1, ClockTrust::Ok, Some(200));
    assert_eq!((st.status, st.reason, st.row), (Status::Unavailable, None, 4));
}

#[test]
fn s08_dependency_lost_stops_dependents_in_reverse_order_without_restart() {
    // a <- b <- c, and d independent; a fails at its 4th call (probe + 3 steps ok)
    let t = leak_table(vec![d(1, "svc.a", &[]), d(2, "svc.b", &[1]), d(3, "svc.c", &[2]), d(4, "svc.d", &[])]);
    let mut f = Fake::new(4);
    f.beh[0].error_from = Some(4);
    let mut s = started(t, &mut f);
    assert!((0..4).all(|i| s.state(i) == SvcState::Running));
    for _ in 0..3 {
        s.step_all(&mut f);
    }
    assert_eq!(s.state(0), SvcState::Failed);
    assert_eq!(f.stops, vec![2, 1], "c is stopped before b");
    assert_eq!((s.state(1), s.state(2), s.state(3)), (SvcState::Stopped, SvcState::Stopped, SvcState::Running));
    let stopping: Vec<_> = f.log.iter().filter_map(|r| match r {
        Report::Transition { idx, t, diag } if t.to == SvcState::Stopping => Some((*idx, *diag)),
        _ => None,
    }).collect();
    assert_eq!(stopping, vec![(2, Some("SVC_DEPENDENCY_LOST")), (1, Some("SVC_DEPENDENCY_LOST"))]);
    let calls_b = f.beh[1].calls;
    for _ in 0..50 {
        s.step_all(&mut f);
    }
    assert_eq!(f.beh[1].calls, calls_b, "no restart");
    assert_eq!(f.count(|r| matches!(r, Report::Transition { t, .. } if t.to == SvcState::Starting)), 4, "only the 4 initial starts");
    assert_eq!(s.state(3), SvcState::Running, "an independent service keeps running");
}

#[test]
fn s08_failing_stop_hook_ends_in_failed() {
    let t = leak_table(vec![d(1, "svc.a", &[]), d(2, "svc.b", &[1])]);
    let mut f = Fake::new(2);
    f.beh[0].error_from = Some(2);
    f.beh[1].stop = Err("SVC_TEST_STOP_ERROR");
    let mut s = started(t, &mut f);
    s.step_all(&mut f);
    assert_eq!((s.state(0), s.state(1)), (SvcState::Failed, SvcState::Failed));
}

// ------------------------------------------------------------------ S09 readiness

fn one(beh: Beh) -> (ServiceSet, Fake) {
    let t = leak_table(vec![d(1, "svc.a", &[])]);
    let mut f = Fake::new(1);
    f.beh[0] = beh;
    let mut s = ServiceSet::new(t);
    assert_eq!(s.start_all(&mut f), StartResult::Started);
    (s, f)
}

fn never_running(f: &Fake) -> bool {
    f.count(|r| matches!(r, Report::Transition { t, .. } if t.to == SvcState::Running)) == 0
}

#[test]
fn s09_honest_readiness_failure_is_failed_never_running() {
    let (s, f) = one(Beh { ready: Err("SVC_TEST_NOT_READY"), ..Beh::good() });
    assert_eq!(s.state(0), SvcState::Failed);
    assert!(never_running(&f));
    assert!(f.log.contains(&Report::ReadyFail { idx: 0, diag: "SVC_TEST_NOT_READY" }));
    let st = s.status(0, ClockTrust::Ok, Some(200));
    assert_eq!((st.status, st.reason, st.liveness, st.compromise()), (Status::Unavailable, None, Liveness::Lost, Compromise::NoneKnown));
}

#[test]
fn s09_false_readiness_claims_are_contradicted() {
    // claims a unit and readiness, but its state did not change (the svc.diagliar case)
    let (s, f) = one(Beh { honest: false, ..Beh::good() });
    assert_eq!(s.state(0), SvcState::Failed);
    assert!(never_running(&f));
    assert!(f.log.contains(&Report::ReadyFail { idx: 0, diag: "SVC_READINESS_CONTRADICTED" }));
    // claims readiness with no work at all
    let (s, f) = one(Beh { units: 0, ..Beh::good() });
    assert_eq!(s.state(0), SvcState::Failed);
    assert!(never_running(&f));
    // no observable state at all
    let (s, f) = one(Beh { observable: false, ..Beh::good() });
    assert_eq!(s.state(0), SvcState::Failed);
    assert!(never_running(&f));
}

#[test]
fn s09_start_hook_or_probe_error_is_failed() {
    let (s, f) = one(Beh { start: Err("SVC_TEST_START_ERROR"), ..Beh::good() });
    assert_eq!(s.state(0), SvcState::Failed);
    assert!(never_running(&f));
    assert_eq!(f.beh[0].calls, 0, "no probe after a failed start hook");
    let (s, f) = one(Beh { error_from: Some(1), ..Beh::good() });
    assert_eq!(s.state(0), SvcState::Failed);
    assert!(never_running(&f));
}

#[test]
fn s09_counter_running_only_after_probe_with_equal_counts() {
    let mut f = Fake::new(3);
    let s = started(svctable::PRODUCTION, &mut f);
    let ready = f.log.iter().position(|r| matches!(r, Report::Ready { idx: 1, .. })).unwrap();
    let running = f.log.iter().position(|r| matches!(r, Report::Transition { idx: 1, t, .. } if t.to == SvcState::Running)).unwrap();
    let starting = f.log.iter().position(|r| matches!(r, Report::Transition { idx: 1, t, .. } if t.to == SvcState::Starting)).unwrap();
    assert!(starting < ready && ready < running);
    match f.log[ready] {
        Report::Ready { probe_units, kernel_units, observed, .. } => assert_eq!((probe_units, kernel_units, observed), (1, 1, Some(1))),
        _ => unreachable!(),
    }
    assert_eq!(s.runtime(1).units, 1);
}

#[test]
fn s09_the_real_counter_behaves_as_specified() {
    let mut c = Counter::new();
    assert!(c.ready().is_err(), "not ready before its probe");
    c.start().unwrap();
    assert_eq!(c.step(1), StepOutcome::Done { units: 1 });
    assert!(c.ready().is_ok());
    assert_eq!(c.observed(), Some(1));
    assert_eq!(c.step(0), StepOutcome::Done { units: 0 }, "no budget, no work");
    let mut top = Counter::with_value(u64::MAX);
    assert_eq!(top.step(1), StepOutcome::Error("SVC_COUNTER_OVERFLOW"));
    assert_eq!(top.observed(), Some(u64::MAX), "never wraps");
}

// ------------------------------------------------------------------ S10 budget and overrun accounting

#[test]
fn s10_more_units_than_budget_is_a_contract_violation() {
    let (s, f) = one(Beh { units: 2, ..Beh::good() });
    assert_eq!(s.state(0), SvcState::Failed, "during the probe");
    assert!(never_running(&f));
    // later in RUNNING: the claim is consistent with the state, but above the budget
    let (mut s, mut f) = one(Beh::good());
    f.beh[0].units = 2;
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Failed);
    assert!(f.log.iter().any(|r| matches!(r, Report::Transition { t, diag: Some("SVC_CONTRACT_VIOLATION"), .. } if t.to == SvcState::Failed)));
}

#[test]
fn s10_observable_must_equal_kernel_accounting_while_running() {
    let (mut s, mut f) = one(Beh::good());
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Running);
    f.beh[0].honest = false; // claims a unit but does nothing
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Failed);
}

#[test]
fn s10_one_overrun_degrades_three_in_a_row_fail() {
    let (mut s, mut f) = one(Beh { cost: vec![Some(5)], ..Beh::good() });
    f.beh[0].cost = vec![Some(STEP_BUDGET_US + 1)];
    f.beh[0].calls = 0;
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Running);
    assert!(s.runtime(0).overrun_window);
    assert_eq!(s.status(0, ClockTrust::Ok, Some(200)).status, Status::Degraded);
    assert_eq!(f.count(|r| matches!(r, Report::Degraded { .. })), 1);
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Running);
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Failed);
    assert_eq!(s.runtime(0).overruns, 3);
    assert_eq!(f.count(|r| matches!(r, Report::Overrun { .. })), 3);
    assert!(f.log.iter().any(|r| matches!(r, Report::Transition { diag: Some("SVC_STEP_OVERRUN"), t, .. } if t.to == SvcState::Failed)));
    assert_eq!(f.count(|r| matches!(r, Report::Degraded { .. })), 1, "DEGRADED reported once");
}

#[test]
fn s10_exactly_at_the_budget_is_in_budget_and_two_overruns_do_not_fail() {
    let (mut s, mut f) = one(Beh::good());
    f.beh[0].cost = vec![Some(STEP_BUDGET_US)];
    s.step_all(&mut f);
    assert!(!s.runtime(0).overrun_window, "1,000 us is within the budget");
    f.beh[0].cost = vec![Some(STEP_BUDGET_US + 1), Some(STEP_BUDGET_US + 1), Some(5)];
    f.beh[0].calls = 0;
    for _ in 0..30 {
        s.step_all(&mut f);
    }
    assert_eq!(s.state(0), SvcState::Running, "never 3 in a row");
    assert_eq!(s.runtime(0).overruns, 20);
}

#[test]
fn s10_recovers_after_100_good_steps() {
    let (mut s, mut f) = one(Beh::good());
    f.beh[0].cost = vec![Some(STEP_BUDGET_US + 500)];
    s.step_all(&mut f);
    f.beh[0].cost = vec![Some(10)];
    for _ in 0..99 {
        s.step_all(&mut f);
    }
    assert!(s.runtime(0).overrun_window, "99 good steps are not enough");
    assert_eq!(s.status(0, ClockTrust::Ok, Some(200)).status, Status::Degraded);
    s.step_all(&mut f);
    assert!(!s.runtime(0).overrun_window);
    assert_eq!(f.count(|r| matches!(r, Report::Recovered { .. })), 1);
    assert_eq!(s.status(0, ClockTrust::Ok, Some(200)).status, Status::Available);
}

#[test]
fn s10_unmeasured_step_is_never_a_success() {
    // 0.32b (audit finding 2): this test asserted in 0.32 that `good` stays unchanged on an unmeasured step. That
    // matched the defect: the streak of consecutive in-budget steps must be BROKEN (reset), not kept.
    let (mut s, mut f) = one(Beh::good());
    f.now = Some(150);
    s.step_all(&mut f);
    let last = s.runtime(0).last_step_ms;
    assert!(s.runtime(0).good >= 1, "a good streak exists before the unmeasured step");
    f.beh[0].cost = vec![None];
    f.now = Some(170);
    s.step_all(&mut f);
    let r = s.runtime(0);
    assert_eq!(r.unmeasured, 1);
    assert_eq!((r.last_step_ms, r.good, r.overruns), (last, 0, 0), "not fresh, the streak is broken, not an overrun");
    assert_eq!(f.count(|r| matches!(r, Report::Unmeasured { .. })), 1);
}

#[test]
fn s10_step_error_fails_with_the_service_code() {
    let (mut s, mut f) = one(Beh { error_from: Some(3), ..Beh::good() });
    s.step_all(&mut f);
    s.step_all(&mut f);
    assert_eq!(s.state(0), SvcState::Failed);
    assert!(f.log.iter().any(|r| matches!(r, Report::Transition { diag: Some("SVC_TEST_STEP_ERROR"), .. })));
    let calls = f.beh[0].calls;
    s.step_all(&mut f);
    assert_eq!(f.beh[0].calls, calls, "a FAILED entry is never stepped again");
}

// ------------------------------------------------------------------ S13 status mapping, exhaustive

/// The design §5 table, re-stated independently of svcstatus.rs.
fn oracle(i: &Inputs) -> (Status, Option<PublicReason>, Liveness, u8) {
    use SvcState::*;
    let fresh = match (i.last_step_ms, i.now_ms) {
        (Some(t), Some(n)) => n >= t && n - t < FRESH_MS,
        _ => false,
    };
    if !i.installed {
        (Status::Unavailable, Some(PublicReason::NotInstalled), Liveness::Unknown, 1)
    } else if !i.registry_ok {
        (Status::Unavailable, None, Liveness::Unknown, 2)
    } else if i.state == Failed {
        (Status::Unavailable, None, Liveness::Lost, 3)
    } else if i.state == Declared && i.withheld != DepBlock::None {
        let r = if i.withheld == DepBlock::NotInstalledRoot { Some(PublicReason::NotInstalled) } else { None };
        (Status::Unavailable, r, Liveness::Unknown, 4)
    } else if i.state != Running {
        (Status::Unavailable, None, Liveness::Unknown, 5)
    } else if i.clock != ClockTrust::Ok {
        (Status::Unknown, Some(PublicReason::ObservationStale), Liveness::Unknown, 6)
    } else if !fresh {
        (Status::Unknown, Some(PublicReason::ObservationStale), Liveness::Stale, 7)
    } else if i.overrun_window {
        (Status::Degraded, None, Liveness::Live, 8)
    } else {
        (Status::Available, None, Liveness::Live, 9)
    }
}

#[test]
fn s13_mapping_matches_the_design_table_for_every_combination() {
    let times: [(Option<u64>, Option<u64>); 6] = [
        (Some(1_000), Some(1_000)),  // fresh (now == observed_at)
        (Some(1_000), Some(1_999)),  // fresh (last ms inside)
        (Some(1_000), Some(2_000)),  // stale (half-open end)
        (Some(2_000), Some(1_000)),  // observation "from the future": not fresh
        (None, Some(1_000)),         // never stepped
        (Some(1_000), None),         // now unreadable
    ];
    let mut n = 0;
    let mut rows = [0usize; 10];
    for registry_ok in [true, false] {
        for installed in [true, false] {
            for state in ALL_STATES {
                for withheld in [DepBlock::None, DepBlock::NotInstalledRoot, DepBlock::Other] {
                    for clock in [ClockTrust::Ok, ClockTrust::Degraded, ClockTrust::Unreadable] {
                        for (last_step_ms, now_ms) in times {
                            for overrun_window in [false, true] {
                                let i = Inputs { registry_ok, installed, state, withheld, last_step_ms, now_ms, clock, overrun_window };
                                let got = map(&i);
                                let want = oracle(&i);
                                assert_eq!((got.status, got.reason, got.liveness, got.row), want, "{i:?}");
                                assert_eq!(got.compromise(), Compromise::NoneKnown);
                                assert_eq!(got.clock, clock);
                                if clock != ClockTrust::Ok && state == SvcState::Running && installed && registry_ok {
                                    assert_ne!(got.status, Status::Available, "never fresh on a degraded clock");
                                }
                                rows[got.row as usize] += 1;
                                n += 1;
                            }
                        }
                    }
                }
            }
        }
    }
    assert_eq!(n, 2 * 2 * 6 * 3 * 3 * 6 * 2);
    assert!(rows[1..].iter().all(|&c| c > 0), "every row reached: {rows:?}");
}

// ------------------------------------------------------------------ S14 public reasons (P-15)

#[test]
fn s14_public_reasons_are_the_27_appendix_a_codes() {
    assert_eq!(ALL_REASONS.len(), 27);
    let mut names: Vec<&str> = ALL_REASONS.iter().map(|r| r.name()).collect();
    assert!(names.iter().all(|n| !n.is_empty() && n.bytes().all(|b| b.is_ascii_uppercase() || b == b'_')));
    names.sort();
    names.dedup();
    assert_eq!(names.len(), 27, "unique");
    // the kernel diagnostic codes this revision prints are none of them
    for code in ["SVC_DEPENDENCY_CYCLE", "SVC_INVALID_TRANSITION", "SVC_STEP_OVERRUN", "SVC_READINESS_FAILED",
                 "SVC_READINESS_CONTRADICTED", "SVC_CONTRACT_VIOLATION", "FRAME_DOUBLE_RELEASE", "TSC_BACKWARD"] {
        assert!(!names.contains(&code), "{code}");
    }
}

// ------------------------------------------------------------------ S15 liveness vs compromise

#[test]
fn s15_no_liveness_change_ever_changes_compromise() {
    let t = leak_table(vec![d(1, "svc.a", &[])]);
    let mut f = Fake::new(1);
    f.now = Some(1_000);
    let mut s = ServiceSet::new(t);
    let mut seen = Vec::new();
    let mut look = |s: &ServiceSet, clock, now| {
        let st = s.status(0, clock, now);
        assert_eq!(st.compromise(), Compromise::NoneKnown);
        seen.push(st.liveness);
    };
    look(&s, ClockTrust::Ok, Some(1_000)); // declared
    s.start_all(&mut f);
    look(&s, ClockTrust::Ok, Some(1_000)); // LIVE
    look(&s, ClockTrust::Ok, Some(5_000)); // STALE
    look(&s, ClockTrust::Degraded, Some(1_000)); // UNKNOWN
    f.beh[0].error_from = Some(2);
    s.step_all(&mut f);
    look(&s, ClockTrust::Ok, Some(1_000)); // LOST
    assert_eq!(seen, vec![Liveness::Unknown, Liveness::Live, Liveness::Stale, Liveness::Unknown, Liveness::Lost]);
}

// ------------------------------------------------------------------ S16 degraded clock (hosted part)

#[test]
fn s16_degraded_clock_makes_running_status_unknown_but_not_static_facts() {
    let mut f = Fake::new(3);
    let mut s = started(svctable::PRODUCTION, &mut f);
    for clock in [ClockTrust::Degraded, ClockTrust::Unreadable] {
        let c = s.status(1, clock, Some(150));
        assert_eq!((c.status, c.reason, c.liveness), (Status::Unknown, Some(PublicReason::ObservationStale), Liveness::Unknown));
        for i in [0, 2] {
            let st = s.status(i, clock, Some(150));
            assert_eq!((st.status, st.reason), (Status::Unavailable, Some(PublicReason::NotInstalled)), "a static fact");
        }
    }
    // the service itself keeps running on a degraded clock: only the claim about it changes
    s.step_all(&mut f);
    assert_eq!(s.state(1), SvcState::Running);
}

// ------------------------------------------------------------------ S17 INSPECT_PUBLIC

#[test]
fn s17_inspect_public_is_a_closed_allow_list() {
    let mut f = Fake::new(3);
    let s = started(svctable::PRODUCTION, &mut f);
    let before: Vec<Runtime> = (0..3).map(|i| s.runtime(i)).collect();
    let ok = s.inspect_public("status", "svc.counter", ClockTrust::Ok, Some(150)).unwrap();
    assert_eq!(ok, s.status(1, ClockTrust::Ok, Some(150)));
    assert_eq!(s.inspect_public("status", "svc.undeclared", ClockTrust::Ok, Some(150)), Err(PublicReason::TargetUnknown));
    for op in ["start", "stop", "set", "reset", "inspect"] {
        assert_eq!(s.inspect_public(op, "svc.counter", ClockTrust::Ok, Some(150)), Err(PublicReason::CapMissing), "{op}");
    }
    for op in ["reboot", "STATUS", "", "status ", "list", "show"] {
        assert_eq!(s.inspect_public(op, "svc.counter", ClockTrust::Ok, Some(150)), Err(PublicReason::OperationUnknown), "{op:?}");
    }
    assert_eq!(s.inspect_public("frobnicate", "svc.nope", ClockTrust::Ok, Some(150)), Err(PublicReason::OperationUnknown),
               "the operation is checked first");
    let after: Vec<Runtime> = (0..3).map(|i| s.runtime(i)).collect();
    assert_eq!(before, after, "nothing changed");
}

#[test]
fn s17_external_transition_requests_are_always_refused() {
    let mut f = Fake::new(3);
    let mut s = started(svctable::PRODUCTION, &mut f);
    let before = s.runtime(1);
    f.log.clear();
    assert!(!s.request(1, SvcState::Starting, &mut f)); // not in the matrix
    assert!(!s.request(1, SvcState::Stopping, &mut f)); // in the matrix, but manager-only
    assert!(!s.request(9, SvcState::Starting, &mut f)); // no such entry: nothing reported
    assert_eq!(s.runtime(1), before);
    let diags: Vec<_> = f.log.iter().map(|r| match r { Report::Refused { diag, .. } => *diag, _ => "?" }).collect();
    assert_eq!(diags, ["SVC_INVALID_TRANSITION", "SVC_TRANSITION_MANAGER_ONLY"]);
}

// ------------------------------------------------------------------ S20 SERVICE events

#[test]
fn s20_service_kind_records_and_overflow_stays_explicit() {
    assert_eq!(EvKind::Service as u8, 5);
    assert_eq!(EvKind::Service.name(), "SERVICE");
    let mut log = EventLog::new();
    for k in 0..(CAPACITY as u64 + 8) {
        let kind = if k % 2 == 0 { EvKind::Service } else { EvKind::Init };
        assert_eq!(log.record(kind, "SVC_RUNNING", k, Some(k)), (k + 1) as u32);
    }
    assert_eq!((log.recorded(), log.dropped(), log.retained()), (40, 8, 32));
    let seqs: Vec<u32> = (0..log.retained()).map(|i| log.get(i).unwrap().seq).collect();
    assert_eq!(seqs, (9..=40).collect::<Vec<u32>>(), "oldest overwritten, never renumbered");
    assert_eq!(log.get(0).unwrap().kind, EvKind::Service);
}

#[test]
fn s20_clean_production_start_reports_the_expected_sequence() {
    let mut f = Fake::new(3);
    started(svctable::PRODUCTION, &mut f);
    let kinds: Vec<&str> = f.log.iter().map(|r| match r {
        Report::RegistryOk { .. } => "REGISTRY_OK",
        Report::NotInstalled { .. } => "NOT_INSTALLED",
        Report::Transition { t, .. } if t.to == SvcState::Starting => "STARTING",
        Report::Ready { .. } => "READY",
        Report::Transition { t, .. } if t.to == SvcState::Running => "RUNNING",
        Report::Withheld { .. } => "WITHHELD",
        _ => "OTHER",
    }).collect();
    assert_eq!(kinds, ["REGISTRY_OK", "NOT_INSTALLED", "STARTING", "READY", "RUNNING", "WITHHELD"]);
}
