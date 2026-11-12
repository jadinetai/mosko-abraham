//! Kernel side of the 0.33 launcher (D-ABR-022; design §9). launch.rs holds the rules; this file prints them.
//!
//! - `init` runs once, from svcmgr::start, after the service start: it validates the application table against the
//!   service table in use (the boot-time check) and prints the `ABR|APP` registry line.
//! - `report` runs with every service status round, at the round's evaluation time: one `ABR|APPINFO` line per
//!   registered application, built from the same ServiceSet the SVCSTATUS lines of that round were built from.
//! - `run_script` (DIAGNOSTIC build `diag-launchpad` only) submits the fixed apptable::DIAG_SCRIPT once, prints every
//!   transition and result, answers `svc.`/`dev.` rows with the unchanged 0.32b `inspect_public`, prints the
//!   summary, then tries an invalid transition on request 1 (it must be refused, the state unchanged).
//! - The production kernel makes no request at all. There is no input path: no command interpreter exists.
//! - Lines carry only registered words, exact names and integers (P-35). `reason=` carries only Appendix A names, and
//!   those are always produced by `PublicReason::name` (svcstatus.rs), never written here. A malformed target is
//!   never echoed, only its length; a capability is never echoed, only `PRESENTED`.

use crate::appregistry::EXECUTOR;
use crate::apptable;
use crate::eventlog::OptMs;
use crate::kcell::KCell;
use crate::launch::{AppInfo, AppRegistry, Launcher, LiveView, Prereq};
#[cfg(feature = "diag-launchpad")]
use crate::launch::{Admission, Answer, Authz, Echo, LaunchResult, Outcome, Recognition, Structure, Support};
use crate::serial::Serial;
use crate::svcrun::ServiceSet;
use crate::svcstatus::{ClockTrust, PublicReason};
use crate::kprintln;
use core::fmt::Write;

static LP: KCell<Option<Launcher>> = KCell::new(None);

fn opt_reason(r: Option<PublicReason>) -> &'static str {
    match r {
        Some(r) => r.name(),
        None => "NONE",
    }
}

fn prereq_name(p: &Prereq) -> &'static str {
    match p {
        Prereq::Satisfied => "SATISFIED",
        Prereq::Unsatisfied { .. } => "UNSATISFIED",
        Prereq::NotEvaluated => "NOT_EVALUATED",
    }
}

/// `unavailable=` value: NONE (all satisfied), NOT_EVALUATED (an earlier gate refused), or `name:STATUS:REASON` per
/// missing service, comma-separated.
fn write_missing(s: &mut Serial, p: &Prereq, services: &ServiceSet) {
    let _ = write!(s, "|unavailable=");
    match p {
        Prereq::Unsatisfied { missing, .. } => {
            let mut first = true;
            for m in missing.iter().flatten() {
                let _ = write!(s, "{}{}:{}:{}", if first { "" } else { "," }, services.table()[m.service].name,
                               m.status.name(), opt_reason(m.reason));
                first = false;
            }
        }
        Prereq::Satisfied => {
            let _ = write!(s, "NONE");
        }
        Prereq::NotEvaluated => {
            let _ = write!(s, "NOT_EVALUATED");
        }
    }
}

fn write_info(l: &Launcher, i: &AppInfo, services: &ServiceSet, clock: ClockTrust, now: Option<u64>) {
    let a = &l.apps()[i.app];
    let mut s = Serial;
    let _ = write!(s, "ABR|APPINFO|id={}|kind={}|rev={}|exec={}|requires=", a.name, a.kind.name(), a.revision, a.exec.name());
    for (k, id) in a.requires.iter().enumerate() {
        let name = crate::svcregistry::index_of(services.table(), *id).map(|x| services.table()[x].name).unwrap_or("NONE");
        let _ = write!(s, "{}{}", if k == 0 { "" } else { "," }, name);
    }
    if a.requires.is_empty() {
        let _ = write!(s, "NONE");
    }
    let _ = write!(s, "|prerequisites={}", prereq_name(&i.prerequisites));
    write_missing(&mut s, &i.prerequisites, services);
    let _ = writeln!(s, "|observed_at_ms={}|clock={}", OptMs(now), clock.name());
}

/// Boot-time validation and the registry line (once).
pub fn init() {
    let _ = LP.with(|lp| {
        if lp.is_some() {
            return;
        }
        let l = Launcher::new(apptable::TABLE, crate::svctable::TABLE);
        match l.registry() {
            AppRegistry::Ok(order) => {
                let mut s = Serial;
                let _ = write!(s, "ABR|APP|registry=OK|entries={}|order=", order.len());
                for k in 0..order.len() {
                    let _ = write!(s, "{}{}", if k == 0 { "" } else { "," }, l.apps()[order.get(k)].name);
                }
                let _ = writeln!(s, "|executor={}", EXECUTOR.name());
            }
            AppRegistry::Refused(e) => {
                kprintln!("ABR|APP|registry=REFUSED|diag={}|entry={}|executor={}", e.code(), e.entry, EXECUTOR.name());
            }
        }
        *lp = Some(l);
    });
}

/// One APPINFO line per registered application, in AppId order, at the status round's evaluation time.
pub fn report(services: &ServiceSet, clock: ClockTrust, now: Option<u64>) {
    let _ = LP.with(|lp| {
        let Some(l) = lp.as_ref() else { return };
        let AppRegistry::Ok(order) = l.registry() else { return };
        let view = LiveView { set: services, clock, now_ms: now };
        for k in 0..order.len() {
            let i = l.info(order.get(k), &view);
            write_info(l, &i, services, clock, now);
        }
    });
}

#[cfg(feature = "diag-launchpad")]
fn print_result(r: &LaunchResult<'_>, services: &ServiceSet) {
    for t in r.transitions().iter().flatten() {
        kprintln!("ABR|LAUNCH|req={}|seq={}|from={}|to={}", r.request_id(), t.seq, t.from.name(), t.to.name());
    }
    let f = r.facts();
    let mut s = Serial;
    let op = match (r.op(), f.structure) {
        (Some(o), _) => o.name(),
        (None, Structure::WellFormed) => "UNKNOWN",
        _ => "NONE",
    };
    let _ = write!(s, "ABR|LAUNCHRESULT|req={}|op={}|target=", r.request_id(), op);
    match r.target() {
        Echo::Name(n) => {
            let _ = write!(s, "{}", n);
        }
        Echo::Malformed(n) => {
            let _ = write!(s, "MALFORMED|target_len={}", n);
        }
        Echo::None => {
            let _ = write!(s, "NONE");
        }
    }
    let _ = write!(s, "|class={}|admission={}|structure={}|known={}|prerequisites={}",
                   f.class.map(|c| c.name()).unwrap_or("NONE"),
                   match f.admission { Admission::Fresh => "FRESH", Admission::NotIncreasing => "NOT_INCREASING" },
                   match f.structure { Structure::WellFormed => "WELL_FORMED", Structure::Malformed(_) => "MALFORMED",
                                       Structure::NotEvaluated => "NOT_EVALUATED" },
                   match f.recognition { Recognition::Known(_) | Recognition::Collection => "YES",
                                         Recognition::Unknown | Recognition::RegistryRefused => "NO",
                                         Recognition::NotEvaluated => "NOT_EVALUATED" },
                   prereq_name(&f.prerequisites));
    write_missing(&mut s, &f.prerequisites, services);
    let _ = writeln!(s, "|support={}|capability={}|authorization={}|executed={}|process=NONE|state={}|stage={}|result={}\
                         |verification=NOT_APPLICABLE|boundary=COOPERATIVE|reason={}|diag={}",
                     match f.support { Support::None => "NONE", Support::NotEvaluated => "NOT_EVALUATED" },
                     if f.capability_presented { "PRESENTED" } else { "NONE" },
                     match f.authorization { Authz::CapMissing => PublicReason::CapMissing.name(),
                                             Authz::NoAuthority => "NO_AUTHORITY", Authz::NotEvaluated => "NOT_EVALUATED" },
                     if r.executed() { "YES" } else { "NO" },
                     r.state().name(), r.stage().name(), r.result_name(), r.reason().name(), r.diag());
}

/// DIAGNOSTIC build `diag-launchpad`: the fixed script, once (design §9).
#[cfg(feature = "diag-launchpad")]
pub fn run_script(services: &ServiceSet, clock: ClockTrust, now: Option<u64>) {
    let _ = LP.with(|lp| {
        let Some(l) = lp.as_mut() else { return };
        let view = LiveView { set: services, clock, now_ms: now };
        let mut first: Option<LaunchResult<'static>> = None;
        let mut executed = 0u32;
        for &(id, text) in apptable::DIAG_SCRIPT {
            match l.submit(id, text, &view) {
                Outcome::Launch(r) => {
                    print_result(&r, services);
                    if r.executed() {
                        executed += 1;
                    }
                    if first.is_none() && r.request_id() == 1 {
                        first = Some(r);
                    }
                }
                Outcome::Discovery { request_id, answer } => match answer {
                    Answer::Info(i) => {
                        kprintln!("ABR|APPQUERY|req={}|op=status|target={}|result=OK", request_id, l.apps()[i.app].name);
                        write_info(l, &i, services, clock, now);
                    }
                    Answer::List => {
                        kprintln!("ABR|APPQUERY|req={}|op=list|target=app|result=OK", request_id);
                    }
                },
                Outcome::Routed { request_id, op, target } => {
                    kprintln!("ABR|LAUNCH|req={}|routed=SERVICE|op={}|target={}", request_id, op.name(), target);
                    match services.inspect_public(op.name(), target, clock, now) {
                        Ok(st) => kprintln!("ABR|SVCQUERY|op={}|target={}|result=OK|status={}|reason={}", op.name(), target,
                                            st.status.name(), opt_reason(st.reason)),
                        Err(r) => kprintln!("ABR|SVCQUERY|op={}|target={}|result=REFUSED|reason={}", op.name(), target, r.name()),
                    }
                }
            }
        }
        let c = l.counters();
        kprintln!("ABR|LAUNCHPAD|requests={}|refused={}|not_executed={}|discovery={}|routed_to_services={}|executed={}\
                   |processes=0|executor={}", c.requests, c.refused, c.not_executed, c.discovery, c.routed, executed,
                  EXECUTOR.name());
        if let Some(r) = first {
            kprintln!("ABR|DIAG|injecting=launch_invalid_transition|req={}|to=RUNNING", r.request_id());
            let refused = r.request_transition(crate::launchlife::RequestState::Running);
            kprintln!("ABR|LAUNCH|req={}|refused|from={}|to={}|diag={}", r.request_id(), refused.from.name(),
                      refused.to.name(), refused.code);
            kprintln!("ABR|LAUNCH|req={}|state={}", r.request_id(), r.state().name());
        }
    });
}
