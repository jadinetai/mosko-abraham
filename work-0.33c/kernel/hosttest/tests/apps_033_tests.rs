//! 0.33 hosted tests: application registry, launch requests, results and lifecycle (D-ABR-022; design §11).
//! Label: SIMULATED. A01-A06 registry; Q01-Q04 parser; D01-D03 admission; F01-F02 prerequisite facts; X01-X03 the
//! decision; N01-N04 no manufactured execution and no authority; L01-L03 lifecycle; S01 the launchpad script.

use abraham_frame_hosttest::appregistry::*;
use abraham_frame_hosttest::apptable::{self, DIAG_SCRIPT};
use abraham_frame_hosttest::launch::*;
use abraham_frame_hosttest::launchlife::{pair, Pair, RequestState, ALL_STATES};
use abraham_frame_hosttest::launchreq::{class_of, parse, Namespace, Op, OpClass, Parse, ParseFault, MAX_REQUEST_BYTES};
use abraham_frame_hosttest::svclife::SvcState;
use abraham_frame_hosttest::svcregistry::{Desc, ServiceId};
use abraham_frame_hosttest::svcrun::*;
use abraham_frame_hosttest::svcstatus::{map, ClockTrust, DepBlock, Inputs, PublicReason, PublicStatus, Status, ALL_REASONS};
use abraham_frame_hosttest::svctable;
use std::boxed::Box;
use std::format;
use std::string::String;
use std::vec;
use std::vec::Vec;

// ------------------------------------------------------------------ fixtures

/// A cooperative host for the real 0.32b ServiceSet (every step in budget, observed = counted).
struct H {
    tsc: u64,
    value: [u64; 8],
}

impl Host for H {
    fn kernel_operational(&self) -> bool { true }
    fn tsc(&mut self) -> u64 { self.tsc }
    fn tsc_hz(&self) -> u64 { 1_000_000 }
    fn uptime_ms(&mut self) -> Option<u64> { Some(100) }
    fn svc_start(&mut self, _i: usize) -> Result<(), &'static str> { Ok(()) }
    fn svc_step(&mut self, i: usize, _b: u32) -> StepOutcome {
        self.tsc += 5;
        self.value[i] += 1;
        StepOutcome::Done { units: 1 }
    }
    fn svc_ready(&mut self, _i: usize) -> Result<(), &'static str> { Ok(()) }
    fn svc_observed(&self, i: usize) -> Option<u64> { Some(self.value[i]) }
    fn svc_stop(&mut self, _i: usize) -> Result<(), &'static str> { Ok(()) }
    fn report(&mut self, _t: &[Desc], _r: Report) {}
}

/// The production services, started: dev.net0 not installed, svc.counter AVAILABLE, svc.netmon withheld.
fn production_services() -> ServiceSet {
    let mut h = H { tsc: 1_000, value: [0; 8] };
    let mut s = ServiceSet::new(svctable::PRODUCTION);
    assert_eq!(s.start_all(&mut h), StartResult::Started);
    s
}

fn live(s: &ServiceSet) -> LiveView<'_> {
    LiveView { set: s, clock: ClockTrust::Ok, now_ms: Some(100) }
}

/// A scripted view: any public status per service position.
struct Fake {
    st: Vec<PublicStatus>,
}

impl StatusView for Fake {
    fn services(&self) -> &'static [Desc] { svctable::PRODUCTION }
    fn status_of(&self, idx: usize) -> PublicStatus { self.st[idx] }
}

fn ps(state: SvcState, withheld: DepBlock, installed: bool, last: Option<u64>, clock: ClockTrust, window: bool) -> PublicStatus {
    map(&Inputs { registry_ok: true, installed, state, withheld, last_step_ms: last, now_ms: Some(100), clock, overrun_window: window })
}

fn launch<'a>(o: Outcome<'a>) -> LaunchResult<'a> {
    match o {
        Outcome::Launch(r) => r,
        other => panic!("expected a launch result, got {other:?}"),
    }
}

fn d(id: u8, name: &'static str, req: &'static [ServiceId], exec: ExecSupport) -> AppDesc {
    AppDesc { id: AppId(id), name, kind: AppKind::Tool, revision: 1, requires: req, exec }
}

fn leak(v: Vec<AppDesc>) -> &'static [AppDesc] {
    Box::leak(v.into_boxed_slice())
}

const C: &[ServiceId] = &[svctable::SVC_COUNTER];

// ------------------------------------------------------------------ registry

#[test]
fn a01_production_table_valid_ordered_by_id() {
    let o = validate(apptable::PRODUCTION, svctable::PRODUCTION).expect("production table valid");
    let names: Vec<&str> = (0..o.len()).map(|k| apptable::PRODUCTION[o.get(k)].name).collect();
    assert_eq!(names, ["app.counterview", "app.netstatus", "app.browser"]);
    assert!(apptable::PRODUCTION.iter().all(|a| a.exec == ExecSupport::None), "no application advertised as executable");
    assert_eq!(EXECUTOR, Executor::Absent);
    assert_eq!(apptable::TABLE.len(), apptable::PRODUCTION.len(), "hosted tests see the production table");
}

#[test]
fn a02_each_refusal_has_its_own_code() {
    let s = svctable::PRODUCTION;
    let cases: Vec<(&'static [AppDesc], &str, usize)> = vec![
        (leak((0..9).map(|i| d(i + 1, ["app.a", "app.b", "app.c", "app.d", "app.e", "app.f", "app.g", "app.h", "app.i"][i as usize], &[], ExecSupport::None)).collect()), "APP_TOO_MANY_ENTRIES", MAX_APPS),
        (leak(vec![d(1, "App.x", &[], ExecSupport::None)]), "APP_NAME_MALFORMED", 0),
        (leak(vec![d(1, "app.x", Box::leak(vec![ServiceId(1), ServiceId(2), ServiceId(3), ServiceId(1), ServiceId(2)].into_boxed_slice()), ExecSupport::None)]), "APP_TOO_MANY_REQUIREMENTS", 0),
        (leak(vec![d(1, "app.x", &[], ExecSupport::None), d(1, "app.y", &[], ExecSupport::None)]), "APP_DUPLICATE_ID", 1),
        (leak(vec![d(1, "app.x", &[], ExecSupport::None), d(2, "app.x", &[], ExecSupport::None)]), "APP_DUPLICATE_NAME", 1),
        (leak(vec![d(1, "app.x", &[ServiceId(99)], ExecSupport::None)]), "APP_UNKNOWN_REQUIREMENT", 0),
        (leak(vec![d(1, "app.x", Box::leak(vec![ServiceId(2), ServiceId(2)].into_boxed_slice()), ExecSupport::None)]), "APP_DUPLICATE_REQUIREMENT", 0),
        (leak(vec![d(1, "app.x", C, ExecSupport::None), d(2, "app.y", C, ExecSupport::Native)]), "APP_EXEC_CLAIM_UNSUPPORTED", 1),
    ];
    for (t, code, entry) in cases {
        let e = validate(t, s).expect_err(code);
        assert_eq!((e.code(), e.entry), (code, entry));
    }
}

#[test]
fn a03_the_diagnostic_tables_are_refused_at_boot() {
    let s = svctable::PRODUCTION;
    assert_eq!(validate(apptable::DIAG_DUP, s).unwrap_err().code(), "APP_DUPLICATE_ID");
    assert_eq!(validate(apptable::DIAG_FALSE_EXEC, s).unwrap_err().code(), "APP_EXEC_CLAIM_UNSUPPORTED");
    assert_eq!(validate(apptable::DIAG_UNKNOWN_REQ, s).unwrap_err().code(), "APP_UNKNOWN_REQUIREMENT");
}

#[test]
fn a04_malformed_names_refused() {
    let bad = ["App.x", "app.", "app..x", "app.x.", ".app.x", "app.x*", "app.?", "app.x y", "svc.x", "dev.x", "app",
               "app.X", "app.x-y", "app._", "appx.y", "app.abcdefghijklmnopqrstuvwxyz01"];
    for n in bad {
        assert!(!name_ok(n), "{n} must be refused");
    }
    assert_eq!("app.abcdefghijklmnopqrstuvwxyz01".len(), MAX_APP_NAME + 1, "32 bytes");
    for n in ["app.x", "app.counterview", "app.a1.b2", "app.abcdefghijklmnopqrstuvwxyz"] {
        assert!(name_ok(n), "{n} is well-formed");
    }
}

#[test]
fn a05_order_is_identical_for_every_permutation() {
    let base = [d(3, "app.c", &[], ExecSupport::None), d(1, "app.a", &[], ExecSupport::None), d(2, "app.b", &[], ExecSupport::None),
                d(4, "app.d", C, ExecSupport::None)];
    let mut perms = 0;
    let idx = [0usize, 1, 2, 3];
    let mut p = idx;
    loop {
        let t = leak(p.iter().map(|&i| base[i]).collect());
        let o = validate(t, svctable::PRODUCTION).unwrap();
        let names: Vec<&str> = (0..o.len()).map(|k| t[o.get(k)].name).collect();
        assert_eq!(names, ["app.a", "app.b", "app.c", "app.d"]);
        for n in ["app.a", "app.b", "app.c", "app.d"] {
            assert_eq!(t[lookup(t, n).unwrap()].name, n);
        }
        perms += 1;
        // next permutation
        let mut i = 3;
        while i > 0 && p[i - 1] >= p[i] { i -= 1; }
        if i == 0 { break; }
        let mut j = 3;
        while p[j] <= p[i - 1] { j -= 1; }
        p.swap(i - 1, j);
        p[i..].reverse();
    }
    assert_eq!(perms, 24);
}

#[test]
fn a06_exact_lookup_and_twelve_near_misses() {
    let t = apptable::PRODUCTION;
    assert_eq!(lookup(t, "app.counterview"), Some(0));
    for n in ["app.counterviews", "app.counterVIEW", "App.counterview", "app.counterview ", " app.counterview", "app.counter",
              "app.counterview.", "app.countervie", "svc.counterview", "app.counterview*", "app.c*", "app.counterviеw"] {
        assert_eq!(lookup(t, n), None, "{n}");
    }
}

// ------------------------------------------------------------------ parser

#[test]
fn q01_every_operation_classified_by_the_fixed_table() {
    let cases = [("status", OpClass::InspectPublic), ("list", OpClass::InspectPublic), ("show", OpClass::InspectPublic),
                 ("inspect", OpClass::InspectProtected), ("start", OpClass::Mutate), ("stop", OpClass::Mutate),
                 ("set", OpClass::Mutate), ("reset", OpClass::Mutate)];
    for (w, c) in cases {
        let text = format!("{w} app.counterview");
        match parse(text.as_bytes()) {
            Parse::Ok(p) => assert_eq!((p.op.name(), p.class, class_of(p.op), p.ns), (w, c, c, Namespace::App)),
            other => panic!("{w}: {other:?}"),
        }
    }
    assert!(matches!(parse(b"list app"), Parse::Ok(p) if p.ns == Namespace::Collection));
    assert!(matches!(parse(b"start svc.counter"), Parse::Ok(p) if p.ns == Namespace::Service));
    assert!(matches!(parse(b"start dev.net0"), Parse::Ok(p) if p.ns == Namespace::Service));
    assert!(matches!(parse(b"start app.counterview as cap.launch"), Parse::Ok(p) if p.capability_presented));
}

#[test]
fn q02_malformed_texts_have_their_own_fault() {
    let long = [b'a'; MAX_REQUEST_BYTES + 1];
    let cases: Vec<(&[u8], ParseFault)> = vec![
        (b"", ParseFault::Empty),
        (&long, ParseFault::TooLong),
        (b"start app.counterview\x00", ParseFault::Byte),
        (b"start app.counterview\t", ParseFault::Byte),
        (b"start app.counterview\xc3\xa9", ParseFault::Byte),
        (b" start app.counterview", ParseFault::Spacing),
        (b"start app.counterview ", ParseFault::Spacing),
        (b"start  app.counterview", ParseFault::Spacing),
        (b"start", ParseFault::NoTarget),
        (b"start app.CounterView", ParseFault::TargetMalformed),
        (b"start app.*", ParseFault::TargetMalformed),
        (b"start app.counter?", ParseFault::TargetMalformed),
        (b"start apps.x", ParseFault::TargetMalformed),
        (b"start app.counterview as", ParseFault::NoCapability),
        (b"start app.counterview as Cap", ParseFault::CapabilityMalformed),
        (b"start app.counterview now=1", ParseFault::Parameter),
        (b"start app.counterview as x=y", ParseFault::Parameter),
        (b"start app.counterview extra", ParseFault::Trailing),
        (b"start app.counterview as a as b", ParseFault::Trailing),
    ];
    for (t, fault) in cases {
        match parse(t) {
            Parse::Malformed { fault: f, .. } => assert_eq!(f, fault, "{:?}", String::from_utf8_lossy(t)),
            other => panic!("{:?}: {other:?}", String::from_utf8_lossy(t)),
        }
    }
    assert_eq!(parse(&[b'a'; MAX_REQUEST_BYTES]), Parse::UnknownOperation, "64 bytes is within the bound");
}

#[test]
fn q03_unknown_operation_words() {
    for t in [&b"launch app.counterview"[..], b"START app.counterview", b"run app.x", b"starts app.x", b"x"] {
        assert_eq!(parse(t), Parse::UnknownOperation, "{:?}", String::from_utf8_lossy(t));
    }
}

#[test]
fn q04_a_malformed_target_is_reported_by_length_only() {
    match parse(b"start app.CounterView") {
        Parse::Malformed { fault: ParseFault::TargetMalformed, target_len: Some(15) } => {}
        other => panic!("{other:?}"),
    }
    let s = production_services();
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    let r = launch(l.submit(1, b"start app.CounterView", &live(&s)));
    assert_eq!(r.target(), Echo::Malformed(15), "the malformed text is never echoed");
}

// ------------------------------------------------------------------ admission

#[test]
fn d01_ids_must_increase_and_refused_requests_use_up_their_id() {
    let s = production_services();
    let v = live(&s);
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    assert_eq!(launch(l.submit(5, b"start app.nosuch", &v)).reason(), PublicReason::TargetUnknown);
    assert_eq!(l.last_admitted(), Some(5), "a refused request still used up its id");
    for id in [5, 4, 0] {
        let r = launch(l.submit(id, b"start app.counterview", &v));
        assert_eq!((r.state(), r.stage(), r.reason(), r.diag()),
                   (RequestState::Refused, Stage::Admission, PublicReason::RequestReplayed, "LAUNCH_ID_NOT_INCREASING"));
        assert_eq!(r.facts().structure, Structure::NotEvaluated, "an out-of-order request is not even parsed");
    }
    assert_eq!(l.last_admitted(), Some(5), "a refused id changes nothing");
    assert_eq!(launch(l.submit(6, b"start app.counterview", &v)).reason(), PublicReason::CapMissing);
}

#[test]
fn d02_the_u32_max_edge() {
    let s = production_services();
    let v = live(&s);
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    assert_eq!(launch(l.submit(u32::MAX, b"start app.counterview", &v)).facts().admission, Admission::Fresh);
    assert_eq!(launch(l.submit(u32::MAX, b"start app.counterview", &v)).facts().admission, Admission::NotIncreasing,
               "after u32::MAX nothing more is admitted in that boot");
}

#[test]
fn d03_the_first_id_may_be_zero() {
    let s = production_services();
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    assert_eq!(launch(l.submit(0, b"start app.counterview", &live(&s))).facts().admission, Admission::Fresh);
}

// ------------------------------------------------------------------ prerequisite facts

#[test]
fn f01_only_available_satisfies() {
    let l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    let combos = [
        (ps(SvcState::Running, DepBlock::None, true, Some(100), ClockTrust::Ok, false), true),
        (ps(SvcState::Running, DepBlock::None, true, Some(100), ClockTrust::Ok, true), false),   // DEGRADED
        (ps(SvcState::Running, DepBlock::None, true, None, ClockTrust::Ok, false), false),        // stale
        (ps(SvcState::Running, DepBlock::None, true, Some(100), ClockTrust::Degraded, false), false),
        (ps(SvcState::Running, DepBlock::None, true, Some(100), ClockTrust::Unreadable, false), false),
        (ps(SvcState::Failed, DepBlock::None, true, Some(100), ClockTrust::Ok, false), false),
        (ps(SvcState::Stopped, DepBlock::None, true, Some(100), ClockTrust::Ok, false), false),
        (ps(SvcState::Declared, DepBlock::NotInstalledRoot, true, None, ClockTrust::Ok, false), false),
        (ps(SvcState::Declared, DepBlock::Other, true, None, ClockTrust::Ok, false), false),
        (ps(SvcState::Declared, DepBlock::None, false, None, ClockTrust::Ok, false), false),
        (ps(SvcState::Starting, DepBlock::None, true, None, ClockTrust::Ok, false), false),
    ];
    for (st, ok) in combos {
        let f = Fake { st: vec![st; 3] };
        let p = l.prerequisites(0, &f); // app.counterview requires svc.counter (position 1)
        assert_eq!(p == Prereq::Satisfied, ok, "{:?}/{:?} -> {p:?}", st.status, st.reason);
        assert_eq!(ok, st.status == Status::Available);
        if let Prereq::Unsatisfied { missing, n } = p {
            assert_eq!(n, 1);
            assert_eq!(missing[0], Some(Missing { service: 1, status: st.status, reason: st.reason }), "own status and reason reported");
        }
    }
}

#[test]
fn f02_production_prerequisites() {
    let s = production_services();
    let v = live(&s);
    let l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    assert_eq!(l.prerequisites(0, &v), Prereq::Satisfied);
    for app in [1, 2] {
        match l.prerequisites(app, &v) {
            Prereq::Unsatisfied { missing, n: 1 } => {
                let m = missing[0].unwrap();
                assert_eq!((svctable::PRODUCTION[m.service].name, m.status, m.reason),
                           ("svc.netmon", Status::Unavailable, Some(PublicReason::NotInstalled)));
            }
            other => panic!("{other:?}"),
        }
    }
}

// ------------------------------------------------------------------ the decision

#[test]
fn x01_decide_is_total_appendix_a_only_and_never_executes() {
    let adms = [Admission::Fresh, Admission::NotIncreasing];
    let structs = [Structure::WellFormed, Structure::Malformed(ParseFault::Trailing), Structure::NotEvaluated];
    let ops = [Operation::Defined, Operation::Unknown, Operation::NotEvaluated];
    let classes = [None, Some(OpClass::InspectPublic), Some(OpClass::InspectProtected), Some(OpClass::Mutate)];
    let recs = [Recognition::Known(0), Recognition::Collection, Recognition::Unknown, Recognition::RegistryRefused, Recognition::NotEvaluated];
    let prs = [Prereq::Satisfied, Prereq::Unsatisfied { missing: [None; MAX_REQUIRES], n: 1 }, Prereq::NotEvaluated];
    let sups = [Support::None, Support::NotEvaluated];
    let auths = [Authz::CapMissing, Authz::NoAuthority, Authz::NotEvaluated];
    let mut n = 0;
    for &admission in &adms { for &structure in &structs { for &operation in &ops { for &class in &classes {
    for &recognition in &recs { for &prerequisites in &prs { for &support in &sups { for &authorization in &auths {
    for cap in [false, true] {
        let f = Facts { admission, structure, operation, class, recognition, prerequisites, support,
                        capability_presented: cap, authorization, execution: Execution::NotExecuted };
        n += 1;
        match decide(&f) {
            Decision::Refuse { reason, .. } | Decision::NotExecuted { reason, .. } => assert!(ALL_REASONS.contains(&reason)),
            Decision::Discovery => {
                assert_eq!((admission, structure, operation, class), (Admission::Fresh, Structure::WellFormed, Operation::Defined, Some(OpClass::InspectPublic)));
            }
        }
        // the earliest failing gate decides, whatever the later facts say
        if admission == Admission::NotIncreasing {
            assert!(matches!(decide(&f), Decision::Refuse { stage: Stage::Admission, reason: PublicReason::RequestReplayed, .. }));
        }
        // prerequisites and support never change the outcome under option A
        let g = Facts { prerequisites: Prereq::Satisfied, support: Support::None, ..f };
        assert_eq!(decide(&f), decide(&g));
    }}}}}}}}}
    assert_eq!(n, 2 * 3 * 3 * 4 * 5 * 3 * 2 * 3 * 2);
}

#[test]
fn x02_validated_requests_are_refused_by_authorization() {
    let base = Facts { admission: Admission::Fresh, structure: Structure::WellFormed, operation: Operation::Defined,
                       class: Some(OpClass::Mutate), recognition: Recognition::Known(0), prerequisites: Prereq::Satisfied,
                       support: Support::None, capability_presented: false, authorization: Authz::CapMissing,
                       execution: Execution::NotExecuted };
    assert_eq!(decide(&base), Decision::NotExecuted { stage: Stage::Authorization, reason: PublicReason::CapMissing, diag: "LAUNCH_CAP_MISSING" });
    let with_cap = Facts { capability_presented: true, authorization: Authz::NoAuthority, ..base };
    assert_eq!(decide(&with_cap), Decision::NotExecuted { stage: Stage::Authorization, reason: PublicReason::AuthzUnavailable, diag: "LAUNCH_NO_AUTHORITY" });
    let unevaluated = Facts { authorization: Authz::NotEvaluated, ..base };
    assert!(matches!(decide(&unevaluated), Decision::NotExecuted { reason: PublicReason::AuthzUnavailable, .. }), "fail closed");
}

#[test]
fn x03_a_refused_registry_makes_every_app_unknown_and_leaves_services_alone() {
    let s = production_services();
    let before: Vec<_> = (0..3).map(|i| s.runtime(i)).collect();
    let mut l = Launcher::new(apptable::DIAG_DUP, svctable::PRODUCTION);
    assert!(matches!(l.registry(), AppRegistry::Refused(e) if e.code() == "APP_DUPLICATE_ID"));
    let r = launch(l.submit(1, b"start app.counterview", &live(&s)));
    assert_eq!((r.state(), r.reason(), r.diag()), (RequestState::Refused, PublicReason::TargetUnknown, "LAUNCH_REGISTRY_REFUSED"));
    assert!(matches!(l.submit(2, b"start svc.counter", &live(&s)), Outcome::Routed { .. }), "services keep their own contract");
    assert_eq!((0..3).map(|i| s.runtime(i)).collect::<Vec<_>>(), before);
}

// ------------------------------------------------------------------ no manufactured execution, no authority

fn lcg(x: &mut u64) -> u64 {
    *x = x.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
    *x >> 33
}

#[test]
fn n01_twenty_thousand_requests_never_execute_or_touch_services() {
    let words = ["status", "list", "show", "inspect", "start", "stop", "set", "reset", "launch", "run", "", "START"];
    let targets = ["app.counterview", "app.netstatus", "app.browser", "app", "app.nosuch", "app.Counter", "app.*", "svc.counter",
                   "dev.net0", "svc.netmon", "", "app..x"];
    let tails = ["", " as cap.launch", " now=1", " extra", " as", " as Cap", "  ", " as a as b"];
    let s = production_services();
    let before: Vec<_> = (0..3).map(|i| s.runtime(i)).collect();
    let states = [SvcState::Running, SvcState::Failed, SvcState::Declared, SvcState::Stopped];
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    let mut x = 7u64;
    let mut seen = [0u32; 4];
    for k in 0..20_000u32 {
        let text = format!("{} {}{}", words[lcg(&mut x) as usize % words.len()], targets[lcg(&mut x) as usize % targets.len()],
                           tails[lcg(&mut x) as usize % tails.len()]);
        let id = if lcg(&mut x) % 10 == 0 { k / 2 } else { k + 1_000 };
        let st = ps(states[lcg(&mut x) as usize % 4], DepBlock::None, true, Some(100), ClockTrust::Ok, lcg(&mut x) % 3 == 0);
        let fake = Fake { st: vec![st; 3] };
        let o = if k % 2 == 0 { l.submit(id, text.as_bytes(), &live(&s)) } else { l.submit(id, text.as_bytes(), &fake) };
        match o {
            Outcome::Launch(r) => {
                assert!(matches!(r.state(), RequestState::Refused | RequestState::NotExecuted), "{text}: {:?}", r.state());
                assert!(!r.executed() && r.result_name() == "NOT_EXECUTED" && r.facts().execution == Execution::NotExecuted);
                assert!(ALL_REASONS.contains(&r.reason()));
                assert!(!matches!(r.facts().authorization, Authz::NotEvaluated) || r.state() == RequestState::Refused);
                seen[if r.state() == RequestState::Refused { 0 } else { 1 }] += 1;
            }
            Outcome::Discovery { .. } => seen[2] += 1,
            Outcome::Routed { .. } => seen[3] += 1,
        }
    }
    assert!(seen.iter().all(|&c| c > 20), "every outcome kind was exercised: {seen:?}");
    assert_eq!((0..3).map(|i| s.runtime(i)).collect::<Vec<_>>(), before, "the launcher never changed a service");
}

#[test]
fn n02_recognition_and_satisfied_prerequisites_grant_no_authority() {
    let s = production_services();
    let v = live(&s);
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    let r = launch(l.submit(1, b"start app.counterview", &v));
    assert_eq!(r.facts().recognition, Recognition::Known(0));
    assert_eq!(r.facts().prerequisites, Prereq::Satisfied);
    assert_eq!(r.facts().support, Support::None);
    assert_eq!((r.state(), r.stage(), r.reason(), r.facts().authorization),
               (RequestState::NotExecuted, Stage::Authorization, PublicReason::CapMissing, Authz::CapMissing));
    let r = launch(l.submit(2, b"start app.counterview as cap.launch", &v));
    assert_eq!((r.reason(), r.facts().authorization, r.facts().capability_presented),
               (PublicReason::AuthzUnavailable, Authz::NoAuthority, true), "a named capability is not authority");
    for (id, t) in [(3, &b"stop app.counterview"[..]), (4, b"inspect app.counterview"), (5, b"reset app.browser"), (6, b"set app.netstatus")] {
        assert_eq!(launch(l.submit(id, t, &v)).reason(), PublicReason::CapMissing);
    }
}

#[test]
fn n03_service_targets_are_routed_to_the_unchanged_contract() {
    let s = production_services();
    let v = live(&s);
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    match l.submit(1, b"start svc.counter", &v) {
        Outcome::Routed { op, target, .. } => {
            assert_eq!((op, target), (Op::Start, "svc.counter"));
            assert_eq!(s.inspect_public(op.name(), target, ClockTrust::Ok, Some(100)), Err(PublicReason::CapMissing));
        }
        other => panic!("{other:?}"),
    }
    assert_eq!(s.state(1), SvcState::Running, "unchanged");
}

#[test]
fn n04_discovery_is_the_closed_allow_list() {
    let s = production_services();
    let v = live(&s);
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    match l.submit(1, b"status app.netstatus", &v) {
        Outcome::Discovery { answer: Answer::Info(i), .. } => {
            assert_eq!((i.app, i.exec), (1, ExecSupport::None));
            assert!(matches!(i.prerequisites, Prereq::Unsatisfied { n: 1, .. }));
        }
        other => panic!("{other:?}"),
    }
    assert!(matches!(l.submit(2, b"list app", &v), Outcome::Discovery { answer: Answer::List, .. }));
    for (id, t) in [(3, &b"show app.netstatus"[..]), (4, b"list app.netstatus"), (5, b"status app")] {
        let r = launch(l.submit(id, t, &v));
        assert_eq!(r.state(), RequestState::Refused, "{:?}", String::from_utf8_lossy(t));
    }
    assert_eq!(launch(l.submit(6, b"status app.nosuch", &v)).reason(), PublicReason::TargetUnknown);
    let c = l.counters();
    assert_eq!((c.requests, c.discovery, c.refused), (6, 2, 4));
}

// ------------------------------------------------------------------ lifecycle

#[test]
fn l01_all_81_pairs_three_allowed_seven_reserved() {
    let (mut a, mut r, mut i) = (0, 0, 0);
    for f in ALL_STATES {
        for t in ALL_STATES {
            match pair(f, t) {
                Pair::Allowed => a += 1,
                Pair::Reserved => r += 1,
                Pair::Invalid => i += 1,
            }
            if f.terminal() {
                assert_eq!(pair(f, t), Pair::Invalid, "terminal {f:?} never moves");
            }
        }
    }
    assert_eq!((a, r, i), (3, 7, 71));
    assert_eq!(pair(RequestState::Validated, RequestState::Running), Pair::Invalid);
    assert_eq!(pair(RequestState::Dispatched, RequestState::Running), Pair::Reserved);
}

#[test]
fn l02_external_transition_requests_are_refused_and_change_nothing() {
    let s = production_services();
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    let r = launch(l.submit(1, b"start app.counterview", &live(&s)));
    for to in ALL_STATES {
        let refused = r.request_transition(to);
        assert_eq!((refused.from, refused.to), (RequestState::NotExecuted, to));
        assert_eq!(refused.code, "LAUNCH_INVALID_TRANSITION", "a terminal state never moves");
        assert_eq!(r.state(), RequestState::NotExecuted);
    }
}

#[test]
fn l03_transitions_recorded_in_order() {
    let s = production_services();
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    let r = launch(l.submit(1, b"start app.counterview", &live(&s)));
    let t: Vec<(u8, RequestState, RequestState)> = r.transitions().iter().flatten().map(|t| (t.seq, t.from, t.to)).collect();
    assert_eq!(t, vec![(1, RequestState::Submitted, RequestState::Validated), (2, RequestState::Validated, RequestState::NotExecuted)]);
    let r = launch(l.submit(2, b"start app.nosuch", &live(&s)));
    let t: Vec<(u8, RequestState, RequestState)> = r.transitions().iter().flatten().map(|t| (t.seq, t.from, t.to)).collect();
    assert_eq!(t, vec![(1, RequestState::Submitted, RequestState::Refused)]);
}

// ------------------------------------------------------------------ the launchpad script (design §9)

#[test]
fn s01_the_launchpad_script_gives_exactly_the_designed_outcomes() {
    // (state or kind, reason, diag) for each row, written from the design before the implementation ran
    let expect: [(&str, Option<PublicReason>, &str); 17] = [
        ("NOT_EXECUTED", Some(PublicReason::CapMissing), "LAUNCH_CAP_MISSING"),
        ("NOT_EXECUTED", Some(PublicReason::CapMissing), "LAUNCH_CAP_MISSING"),
        ("NOT_EXECUTED", Some(PublicReason::CapMissing), "LAUNCH_CAP_MISSING"),
        ("NOT_EXECUTED", Some(PublicReason::AuthzUnavailable), "LAUNCH_NO_AUTHORITY"),
        ("NOT_EXECUTED", Some(PublicReason::CapMissing), "LAUNCH_CAP_MISSING"),
        ("NOT_EXECUTED", Some(PublicReason::CapMissing), "LAUNCH_CAP_MISSING"),
        ("DISCOVERY", None, ""),
        ("REFUSED", Some(PublicReason::TargetUnknown), "LAUNCH_TARGET_UNKNOWN"),
        ("REFUSED", Some(PublicReason::TargetUnknown), "LAUNCH_TARGET_UNKNOWN"),
        ("REFUSED", Some(PublicReason::ParseError), "LAUNCH_PARSE_TARGET_MALFORMED"),
        ("REFUSED", Some(PublicReason::ParseError), "LAUNCH_PARSE_TARGET_MALFORMED"),
        ("REFUSED", Some(PublicReason::OperationUnknown), "LAUNCH_OPERATION_UNKNOWN"),
        ("REFUSED", Some(PublicReason::ParseError), "LAUNCH_PARSE_PARAMETER"),
        ("REFUSED", Some(PublicReason::ParseError), "LAUNCH_PARSE_SPACING"),
        ("REFUSED", Some(PublicReason::ParseError), "LAUNCH_PARSE_TOO_LONG"),
        ("REFUSED", Some(PublicReason::RequestReplayed), "LAUNCH_ID_NOT_INCREASING"),
        ("ROUTED", None, ""),
    ];
    assert_eq!(DIAG_SCRIPT.len(), 17);
    assert_eq!(DIAG_SCRIPT[14].1.len(), 65);
    let s = production_services();
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    for (k, ((id, text), (kind, reason, diag))) in DIAG_SCRIPT.iter().zip(expect.iter()).enumerate() {
        let got = match l.submit(*id, text, &live(&s)) {
            Outcome::Launch(r) => (r.state().name(), Some(r.reason()), r.diag()),
            Outcome::Discovery { .. } => ("DISCOVERY", None, ""),
            Outcome::Routed { .. } => ("ROUTED", None, ""),
        };
        assert_eq!(got, (*kind, *reason, *diag), "row {}", k + 1);
    }
    let c = l.counters();
    assert_eq!((c.requests, c.refused, c.not_executed, c.discovery, c.routed), (17, 9, 6, 1, 1));
}

#[test]
fn n05_result_facts_carry_the_live_prerequisites() {
    // found while planning the mutation check: no test read a launch result's prerequisite fact
    let s = production_services();
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    let r = launch(l.submit(1, b"start app.netstatus", &live(&s)));
    match r.facts().prerequisites {
        Prereq::Unsatisfied { missing, n: 1 } => {
            let m = missing[0].unwrap();
            assert_eq!((svctable::PRODUCTION[m.service].name, m.status, m.reason),
                       ("svc.netmon", Status::Unavailable, Some(PublicReason::NotInstalled)));
        }
        other => panic!("{other:?}"),
    }
    assert_eq!(r.facts().support, Support::None);
    let r = launch(l.submit(2, b"start app.nosuch", &live(&s)));
    assert_eq!((r.facts().prerequisites, r.facts().support), (Prereq::NotEvaluated, Support::NotEvaluated));
}
