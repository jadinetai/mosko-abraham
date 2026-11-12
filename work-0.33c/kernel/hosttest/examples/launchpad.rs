//! ABRAHAM 0.33 launchpad demonstration (D-ABR-022 Q6). Label: SIMULATED: it runs on the host, not in the kernel.
//!
//!   cd kernel/hosttest
//!   cargo run --example launchpad                                  the fixed 17-request DIAGNOSTIC script
//!   cargo run --example launchpad -- "start app.counterview" "list app" "status app.netstatus"
//!   cargo run --example launchpad -- --degraded-clock "start app.counterview"
//!
//! It runs the kernel's OWN launcher sources (appregistry.rs, apptable.rs, launchreq.rs, launchlife.rs, launch.rs,
//! compiled for the host exactly as in the hosted tests) against a real 0.32b ServiceSet with the production service
//! table (dev.net0 not installed, svc.counter running, svc.netmon withheld). Each request gets the kernel's line
//! format (the same fields as launchpad.rs prints on the VM) and one plain-English line. Requests are numbered 1, 2,
//! ... in the order given; a request id that is not greater than the last admitted one is refused (REQUEST_REPLAYED),
//! so to see that, use the default script. `--degraded-clock` evaluates the services on a DEGRADED clock: the counter
//! becomes UNKNOWN / OBSERVATION_STALE and app.counterview's prerequisites are then unmet (Q3).
//! Nothing here can execute an application either: the executor is ABSENT in this code as in the kernel.

use abraham_frame_hosttest::appregistry::EXECUTOR;
use abraham_frame_hosttest::apptable::{self, DIAG_SCRIPT};
use abraham_frame_hosttest::launch::*;
use abraham_frame_hosttest::launchlife::RequestState;
use abraham_frame_hosttest::svcregistry::Desc;
use abraham_frame_hosttest::svcrun::*;
use abraham_frame_hosttest::svcstatus::{ClockTrust, PublicReason};
use abraham_frame_hosttest::svctable;

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

fn opt_reason(r: Option<PublicReason>) -> &'static str {
    r.map(|r| r.name()).unwrap_or("NONE")
}

fn prereq(p: &Prereq, services: &ServiceSet) -> (&'static str, String) {
    match p {
        Prereq::Satisfied => ("SATISFIED", "NONE".into()),
        Prereq::NotEvaluated => ("NOT_EVALUATED", "NOT_EVALUATED".into()),
        Prereq::Unsatisfied { missing, .. } => ("UNSATISFIED", missing.iter().flatten()
            .map(|m| format!("{}:{}:{}", services.table()[m.service].name, m.status.name(), opt_reason(m.reason)))
            .collect::<Vec<_>>().join(",")),
    }
}

fn appinfo(l: &Launcher, i: &AppInfo, services: &ServiceSet, clock: ClockTrust) -> String {
    let a = &l.apps()[i.app];
    let req: Vec<&str> = a.requires.iter()
        .filter_map(|id| abraham_frame_hosttest::svcregistry::index_of(services.table(), *id).map(|x| services.table()[x].name))
        .collect();
    let (p, un) = prereq(&i.prerequisites, services);
    format!("ABR|APPINFO|id={}|kind={}|rev={}|exec={}|requires={}|prerequisites={}|unavailable={}|observed_at_ms=100|clock={}",
            a.name, a.kind.name(), a.revision, a.exec.name(), if req.is_empty() { "NONE".into() } else { req.join(",") }, p, un,
            clock.name())
}

fn result_line(r: &LaunchResult<'_>, services: &ServiceSet) -> String {
    let f = r.facts();
    let op = match (r.op(), f.structure) {
        (Some(o), _) => o.name(),
        (None, Structure::WellFormed) => "UNKNOWN",
        _ => "NONE",
    };
    let target = match r.target() {
        Echo::Name(n) => n.to_string(),
        Echo::Malformed(n) => format!("MALFORMED|target_len={n}"),
        Echo::None => "NONE".into(),
    };
    let (p, un) = prereq(&f.prerequisites, services);
    format!("ABR|LAUNCHRESULT|req={}|op={}|target={}|class={}|admission={}|structure={}|known={}|prerequisites={}|unavailable={}\
             |support={}|capability={}|authorization={}|executed={}|process=NONE|state={}|stage={}|result={}\
             |verification=NOT_APPLICABLE|boundary=COOPERATIVE|reason={}|diag={}",
            r.request_id(), op, target, f.class.map(|c| c.name()).unwrap_or("NONE"),
            match f.admission { Admission::Fresh => "FRESH", Admission::NotIncreasing => "NOT_INCREASING" },
            match f.structure { Structure::WellFormed => "WELL_FORMED", Structure::Malformed(_) => "MALFORMED", Structure::NotEvaluated => "NOT_EVALUATED" },
            match f.recognition { Recognition::Known(_) | Recognition::Collection => "YES", Recognition::Unknown | Recognition::RegistryRefused => "NO",
                                  Recognition::NotEvaluated => "NOT_EVALUATED" },
            p, un, match f.support { Support::None => "NONE", Support::NotEvaluated => "NOT_EVALUATED" },
            if f.capability_presented { "PRESENTED" } else { "NONE" },
            match f.authorization { Authz::CapMissing => PublicReason::CapMissing.name(), Authz::NoAuthority => "NO_AUTHORITY",
                                    Authz::NotEvaluated => "NOT_EVALUATED" },
            if r.executed() { "YES" } else { "NO" }, r.state().name(), r.stage().name(), r.result_name(), r.reason().name(), r.diag())
}

/// One plain-English line: what happened and why. Nothing here is a claim the result line does not make.
fn explain(r: &LaunchResult<'_>) -> String {
    let why = match r.diag() {
        "LAUNCH_ID_NOT_INCREASING" => "its request number is not greater than the last one (an ordering check, not authentication)",
        "LAUNCH_OPERATION_UNKNOWN" => "the operation word is not one Abraham knows for applications",
        "LAUNCH_TARGET_UNKNOWN" => "no application of exactly that name is in the registry",
        "LAUNCH_REGISTRY_REFUSED" => "the application registry itself was refused at boot",
        "LAUNCH_CAP_MISSING" => "it is a privileged request and no capability was presented (none can exist yet)",
        "LAUNCH_NO_AUTHORITY" => "a capability was named, but no authority mechanism exists to check it",
        d if d.starts_with("LAUNCH_PARSE_") => "the text does not follow the request grammar",
        _ => "see the diagnostic code",
    };
    let f = r.facts();
    let extra = match (&f.prerequisites, f.support) {
        (Prereq::Unsatisfied { .. }, _) => "; its prerequisites are also unmet",
        (Prereq::Satisfied, Support::None) => "; its prerequisites are met, but it cannot execute in 0.33 anyway",
        _ => "",
    };
    match r.state() {
        RequestState::Refused => format!("   = REFUSED at {}: {}{}. Nothing ran.", r.stage().name(), why, extra),
        _ => format!("   = accepted for validation, then NOT EXECUTED at {}: {}{}. Nothing ran.", r.stage().name(), why, extra),
    }
}

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "--help" || a == "-h") {
        println!("usage: cargo run --example launchpad [-- [--degraded-clock] \"<request>\" ...]");
        println!("  no request: the fixed 17-request DIAGNOSTIC script of the kernel (apptable::DIAG_SCRIPT)");
        println!("  grammar: <operation> <target> [as <capability>]   e.g. \"start app.counterview\", \"list app\", \"status app.browser\"");
        return;
    }
    let degraded = args.iter().any(|a| a == "--degraded-clock");
    args.retain(|a| a != "--degraded-clock");
    let clock = if degraded { ClockTrust::Degraded } else { ClockTrust::Ok };

    let mut host = H { tsc: 1_000, value: [0; 8] };
    let mut services = ServiceSet::new(svctable::PRODUCTION);
    services.start_all(&mut host);
    for _ in 0..3 {
        services.step_all(&mut host);
    }
    let mut l = Launcher::new(apptable::PRODUCTION, svctable::PRODUCTION);
    println!("ABRAHAM 0.33 launchpad demonstration: hosted, SIMULATED (the kernel's own launch.rs, not the VM)");
    println!("services: dev.net0 not installed; svc.counter running; svc.netmon withheld; clock {}", clock.name());
    match l.registry() {
        AppRegistry::Ok(o) => println!("ABR|APP|registry=OK|entries={}|order={}|executor={}", o.len(),
                                       (0..o.len()).map(|k| l.apps()[o.get(k)].name).collect::<Vec<_>>().join(","), EXECUTOR.name()),
        AppRegistry::Refused(e) => println!("ABR|APP|registry=REFUSED|diag={}|entry={}|executor={}", e.code(), e.entry, EXECUTOR.name()),
    }
    let view = LiveView { set: &services, clock, now_ms: Some(100) };
    if let AppRegistry::Ok(o) = l.registry() {
        for k in 0..o.len() {
            println!("{}", appinfo(&l, &l.info(o.get(k), &view), &services, clock));
        }
    }
    let script: Vec<(u32, Vec<u8>)> = if args.is_empty() {
        DIAG_SCRIPT.iter().map(|(id, t)| (*id, t.to_vec())).collect()
    } else {
        args.iter().enumerate().map(|(k, a)| (k as u32 + 1, a.as_bytes().to_vec())).collect()
    };
    let mut first: Option<RequestState> = None;
    let mut executed = 0u32;
    for (id, text) in &script {
        println!();
        println!("> request {id}: \"{}\"", String::from_utf8_lossy(text));
        match l.submit(*id, text, &view) {
            Outcome::Launch(r) => {
                for t in r.transitions().iter().flatten() {
                    println!("ABR|LAUNCH|req={}|seq={}|from={}|to={}", r.request_id(), t.seq, t.from.name(), t.to.name());
                }
                println!("{}", result_line(&r, &services));
                println!("{}", explain(&r));
                executed += r.executed() as u32;
                if r.request_id() == 1 && first.is_none() {
                    let refused = r.request_transition(RequestState::Running);
                    first = Some(r.state());
                    if args.is_empty() {
                        println!("   (kept for the forced-transition test at the end: {} -> RUNNING is {})", refused.from.name(), refused.code);
                    }
                }
            }
            Outcome::Discovery { request_id, answer } => match answer {
                Answer::Info(i) => {
                    println!("ABR|APPQUERY|req={request_id}|op=status|target={}|result=OK", l.apps()[i.app].name);
                    println!("{}", appinfo(&l, &i, &services, clock));
                    println!("   = answered from the registry (a public read): no request state, nothing ran.");
                }
                Answer::List => {
                    println!("ABR|APPQUERY|req={request_id}|op=list|target=app|result=OK");
                    if let AppRegistry::Ok(o) = l.registry() {
                        for k in 0..o.len() {
                            println!("{}", appinfo(&l, &l.info(o.get(k), &view), &services, clock));
                        }
                    }
                    println!("   = the registry listed (a public read): nothing ran.");
                }
            },
            Outcome::Routed { request_id, op, target } => {
                println!("ABR|LAUNCH|req={request_id}|routed=SERVICE|op={}|target={target}", op.name());
                match services.inspect_public(op.name(), target, clock, Some(100)) {
                    Ok(s) => println!("ABR|SVCQUERY|op={}|target={target}|result=OK|status={}|reason={}", op.name(), s.status.name(), opt_reason(s.reason)),
                    Err(r) => println!("ABR|SVCQUERY|op={}|target={target}|result=REFUSED|reason={}", op.name(), r.name()),
                }
                println!("   = a service, not an application: answered by the unchanged 0.32b service contract.");
            }
        }
    }
    let c = l.counters();
    println!();
    println!("ABR|LAUNCHPAD|requests={}|refused={}|not_executed={}|discovery={}|routed_to_services={}|executed={}|processes=0|executor={}",
             c.requests, c.refused, c.not_executed, c.discovery, c.routed, executed, EXECUTOR.name());
    if let (Some(state), true) = (first, args.is_empty()) {
        println!("forced transition: request 1 ({}) -> RUNNING refused with LAUNCH_INVALID_TRANSITION; state still {}",
                 state.name(), state.name());
    }
    println!("executed: {executed}. No application can execute in 0.33: the executor is {}.", EXECUTOR.name());
}
