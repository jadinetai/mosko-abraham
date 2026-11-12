//! Kernel side of the 0.32 service architecture (D-ABR-019; design §2-§6). svcrun.rs holds the rules. This file
//! connects them to the kernel: the lifecycle state, the guarded clock, the raw TSC, serial lines and event records.
//!
//! - One static manager in a KCell: no allocation, a fixed table (svctable::TABLE).
//! - `start` runs once, from kmain, right after the OPERATIONAL printout. `tick` runs from the kernel main loop
//!   (never from an interrupt): one bounded step per RUNNING service, and a public status report every
//!   REPORT_PERIOD_MS.
//! - Lines carry only registered codes, exact names and integers (P-35). Kernel diagnostic codes appear only in
//!   `diag=` fields. `reason=` fields on ABR|SVCSTATUS / ABR|SVCQUERY lines carry only Appendix A codes or NONE
//!   (D-ABR-011).
//! - Events (kind SERVICE) are recorded on lifecycle and status changes only; the manager never reads the log.

use crate::eventlog::{self, OptMs};
use crate::events::Kind;
use crate::kcell::KCell;
use crate::lifecycle::InitState;
use crate::serial::Serial;
use crate::svc_counter::Counter;
use crate::svclife::SvcState;
use crate::svcregistry::Desc;
use crate::svcrun::{Host, Report, ServiceSet, StartResult, StepOutcome, REPORT_PERIOD_MS, STEP_BUDGET_US};
use crate::svcstatus::{ClockTrust, PublicReason};
use crate::svctable::{self, TABLE};
use crate::{clock, init, kprintln};
use core::fmt::Write;

struct KHost {
    tsc_hz: u64,
    counter: Counter,
    #[cfg(any(feature = "diag-svc-defects", feature = "diag-svc-slow", feature = "diag-svc-stall", feature = "diag-svc-cascade"))]
    diag: crate::svcdiag::Diag,
}

impl KHost {
    const fn new() -> Self {
        KHost {
            tsc_hz: 0,
            counter: Counter::new(),
            #[cfg(any(feature = "diag-svc-defects", feature = "diag-svc-slow", feature = "diag-svc-stall", feature = "diag-svc-cascade"))]
            diag: crate::svcdiag::Diag::new(),
        }
    }
}

struct Kernel {
    set: ServiceSet,
    host: KHost,
    next_report_ms: u64,
    active: bool,
}

static SVC: KCell<Kernel> =
    KCell::new(Kernel { set: ServiceSet::new(TABLE), host: KHost::new(), next_report_ms: 0, active: false });

fn state_code(s: SvcState) -> &'static str {
    match s {
        SvcState::Declared => "SVC_DECLARED",
        SvcState::Starting => "SVC_STARTING",
        SvcState::Running => "SVC_RUNNING",
        SvcState::Stopping => "SVC_STOPPING",
        SvcState::Stopped => "SVC_STOPPED",
        SvcState::Failed => "SVC_FAILED",
    }
}

fn reason_name(r: Option<PublicReason>) -> &'static str {
    match r {
        Some(r) => r.name(),
        None => "NONE",
    }
}

fn trust() -> ClockTrust {
    match clock::degraded() {
        Some(false) => ClockTrust::Ok,
        Some(true) => ClockTrust::Degraded,
        None => ClockTrust::Unreadable,
    }
}

impl Host for KHost {
    fn kernel_operational(&self) -> bool {
        init::state() == Some(InitState::Operational)
    }

    fn tsc(&mut self) -> u64 {
        clock::read_tsc()
    }

    fn tsc_hz(&self) -> u64 {
        self.tsc_hz
    }

    fn uptime_ms(&mut self) -> Option<u64> {
        clock::peek_uptime_ms()
    }

    fn svc_start(&mut self, idx: usize) -> Result<(), &'static str> {
        match TABLE[idx].id {
            svctable::SVC_COUNTER => self.counter.start(),
            #[cfg(any(feature = "diag-svc-defects", feature = "diag-svc-slow", feature = "diag-svc-stall", feature = "diag-svc-cascade"))]
            id if crate::svcdiag::owns(id) => self.diag.start(id),
            _ => Err("SVC_NO_BEHAVIOR"),
        }
    }

    fn svc_step(&mut self, idx: usize, budget: u32) -> StepOutcome {
        match TABLE[idx].id {
            svctable::SVC_COUNTER => self.counter.step(budget),
            #[cfg(any(feature = "diag-svc-defects", feature = "diag-svc-slow", feature = "diag-svc-stall", feature = "diag-svc-cascade"))]
            id if crate::svcdiag::owns(id) => self.diag.step(id, budget, self.tsc_hz),
            _ => StepOutcome::Error("SVC_NO_BEHAVIOR"),
        }
    }

    fn svc_ready(&mut self, idx: usize) -> Result<(), &'static str> {
        match TABLE[idx].id {
            svctable::SVC_COUNTER => self.counter.ready(),
            #[cfg(any(feature = "diag-svc-defects", feature = "diag-svc-slow", feature = "diag-svc-stall", feature = "diag-svc-cascade"))]
            id if crate::svcdiag::owns(id) => self.diag.ready(id),
            _ => Err("SVC_NO_BEHAVIOR"),
        }
    }

    fn svc_observed(&self, idx: usize) -> Option<u64> {
        match TABLE[idx].id {
            svctable::SVC_COUNTER => self.counter.observed(),
            #[cfg(any(feature = "diag-svc-defects", feature = "diag-svc-slow", feature = "diag-svc-stall", feature = "diag-svc-cascade"))]
            id if crate::svcdiag::owns(id) => self.diag.observed(id),
            _ => None,
        }
    }

    fn svc_stop(&mut self, idx: usize) -> Result<(), &'static str> {
        match TABLE[idx].id {
            svctable::SVC_COUNTER => self.counter.stop(),
            #[cfg(any(feature = "diag-svc-defects", feature = "diag-svc-slow", feature = "diag-svc-stall", feature = "diag-svc-cascade"))]
            id if crate::svcdiag::owns(id) => Ok(()),
            _ => Err("SVC_NO_BEHAVIOR"),
        }
    }

    fn report(&mut self, t: &[Desc], r: Report) {
        let id = |i: usize| t[i].id.0 as u64;
        match r {
            Report::StartRefused { diag } => {
                kprintln!("ABR|SVC|start=REFUSED|diag={}|init_state={}", diag, init::state_name());
                eventlog::record(Kind::Service, "SVC_START_REFUSED", 0);
            }
            Report::RegistryOk { entries, order } => {
                let mut s = Serial;
                let _ = write!(s, "ABR|SVC|registry=OK|entries={}|order=", entries);
                for (k, &i) in order.positions().iter().enumerate() {
                    let _ = write!(s, "{}{}", if k == 0 { "" } else { "," }, t[i as usize].name);
                }
                let _ = writeln!(s);
                eventlog::record(Kind::Service, "SVC_REGISTRY_OK", entries as u64);
            }
            Report::RegistryRefused { error } => {
                kprintln!("ABR|SVC|registry=REFUSED|diag={}|entry={}", error.code(), error.entry);
                eventlog::record(Kind::Service, "SVC_REGISTRY_REFUSED", error.entry as u64);
            }
            Report::NotInstalled { idx } => {
                kprintln!("ABR|SVC|id={}|start=SKIPPED|installed=false|kind={}", t[idx].name, t[idx].kind.name());
                eventlog::record(Kind::Service, "SVC_NOT_INSTALLED", id(idx));
            }
            Report::Withheld { idx, dep, dep_state } => {
                kprintln!("ABR|SVC|id={}|start=WITHHELD|dependency={}|dependency_state={}", t[idx].name, t[dep].name,
                          dep_state.name());
                eventlog::record(Kind::Service, "SVC_START_WITHHELD", (id(idx) << 8) | id(dep));
            }
            Report::Transition { idx, t: tr, diag } => {
                match diag {
                    Some(d) => kprintln!("ABR|SVC|id={}|seq={}|from={}|to={}|diag={}", t[idx].name, tr.seq,
                                         tr.from.name(), tr.to.name(), d),
                    None => kprintln!("ABR|SVC|id={}|seq={}|from={}|to={}", t[idx].name, tr.seq, tr.from.name(),
                                      tr.to.name()),
                }
                eventlog::record(Kind::Service, state_code(tr.to), (id(idx) << 8) | tr.seq as u64);
            }
            Report::Refused { idx, r, diag } => {
                kprintln!("ABR|SVC|id={}|refused|from={}|to={}|diag={}", t[idx].name, r.from.name(), r.to.name(), diag);
                eventlog::record(Kind::Service, diag, (id(idx) << 16) | ((r.from as u64) << 8) | r.to as u64);
            }
            Report::Ready { idx, probe_units, kernel_units, observed, probe_us, timing } => {
                // 0.32b (finding 3): the probe's time verdict is stated with readiness, never left implicit.
                kprintln!("ABR|SVC|id={}|ready=PASS|probe_units={}|kernel_units={}|observed={}|probe_us={}|probe_timing={}",
                          t[idx].name, probe_units, kernel_units, OptMs(observed), OptMs(probe_us), timing.name());
            }
            Report::ReadyFail { idx, diag } => {
                kprintln!("ABR|SVC|id={}|ready=FAIL|diag={}", t[idx].name, diag);
            }
            Report::Overrun { idx, elapsed_us, consecutive } => {
                kprintln!("ABR|SVC|id={}|overrun|elapsed_us={}|budget_us={}|consecutive={}|diag=SVC_STEP_OVERRUN",
                          t[idx].name, elapsed_us, STEP_BUDGET_US, consecutive);
            }
            Report::Unmeasured { idx } => {
                kprintln!("ABR|SVC|id={}|unmeasured|diag=SVC_STEP_UNMEASURED", t[idx].name);
            }
            Report::Degraded { idx } => {
                kprintln!("ABR|SVC|id={}|status_change=DEGRADED|diag=SVC_STEP_OVERRUN", t[idx].name);
                eventlog::record(Kind::Service, "SVC_DEGRADED", id(idx));
            }
            Report::Recovered { idx } => {
                kprintln!("ABR|SVC|id={}|status_change=RECOVERED", t[idx].name);
                eventlog::record(Kind::Service, "SVC_RECOVERED", id(idx));
            }
        }
    }
}

/// One public status line per table entry, in table order (design §5).
fn report_all(k: &Kernel, now: Option<u64>) {
    let clock = trust();
    for idx in 0..TABLE.len() {
        let st = k.set.status(idx, clock, now);
        let rt = k.set.runtime(idx);
        kprintln!(
            "ABR|SVCSTATUS|id={}|state={}|status={}|reason={}|liveness={}|compromise={}|observed_at_ms={}|clock={}\
             |value={}|steps={}|overruns={}",
            TABLE[idx].name, rt.life.state().name(), st.status.name(), reason_name(st.reason), st.liveness.name(),
            st.compromise().name(), OptMs(st.observed_at_ms), st.clock.name(), OptMs(k.host.svc_observed(idx)),
            rt.steps, rt.overruns
        );
    }
    // 0.33: the applications' prerequisites, from this same round (same ServiceSet, clock and time).
    crate::launchpad::report(&k.set, clock, now);
}

/// Start phase (once). `printed` = the number of event records printed at OPERATIONAL. A start refused before
/// OPERATIONAL (or a second start) prints its refusal and nothing else; the manager is unchanged.
pub fn start(tsc_hz: u64, printed: u64) {
    let res = SVC.with(|k| {
        k.host.tsc_hz = tsc_hz;
        let Kernel { set, host, .. } = k;
        set.start_all(host)
    });
    match res {
        Some(StartResult::Started) | Some(StartResult::RegistryRefused) => {}
        Some(StartResult::NotOperational) | Some(StartResult::AlreadyStarted) => return,
        None => {
            kprintln!("ABR|SVC|start=REFUSED|diag=SVC_MANAGER_BUSY");
            return;
        }
    }
    eventlog::print_since(printed + 1);
    // 0.33: the application registry is validated against the service table in use, and printed once.
    crate::launchpad::init();
    let _ = SVC.with(|k| {
        k.active = true;
        let now = clock::peek_uptime_ms();
        report_all(k, now);
        k.next_report_ms = now.unwrap_or(0).saturating_add(REPORT_PERIOD_MS);
    });
}

/// Kernel main loop hook: one cooperative step per RUNNING service, then the periodic report.
pub fn tick() {
    let _ = SVC.with(|k| {
        if !k.active {
            return;
        }
        {
            let Kernel { set, host, .. } = k;
            set.step_all(host);
        }
        if let Some(now) = clock::peek_uptime_ms() {
            if now >= k.next_report_ms {
                report_all(k, Some(now));
                k.next_report_ms = now.saturating_add(REPORT_PERIOD_MS);
            }
        }
    });
}

/// DIAGNOSTIC build `diag-launchpad` (0.33): the fixed request script reads the services through a shared borrow.
#[cfg(feature = "diag-launchpad")]
pub fn diag_launchpad() {
    let _ = SVC.with(|k| crate::launchpad::run_script(&k.set, trust(), clock::peek_uptime_ms()));
}

/// DIAGNOSTIC build `diag-svc-refusals`: public queries (an unknown name, a near miss, a MUTATE operation, an unknown
/// operation, a valid status) and an invalid transition request. Each refusal must leave the manager unchanged.
#[cfg(feature = "diag-svc-refusals")]
pub fn diag_refusals() {
    let _ = SVC.with(|k| {
        let (clock, now) = (trust(), clock::peek_uptime_ms());
        for (op, target) in [("status", "svc.undeclared"), ("status", "SVC.COUNTER"), ("start", "svc.counter"),
                             ("reboot", "svc.counter"), ("status", "svc.counter")] {
            match k.set.inspect_public(op, target, clock, now) {
                Ok(s) => kprintln!("ABR|SVCQUERY|op={}|target={}|result=OK|status={}|reason={}", op, target,
                                   s.status.name(), reason_name(s.reason)),
                Err(r) => kprintln!("ABR|SVCQUERY|op={}|target={}|result=REFUSED|reason={}", op, target, r.name()),
            }
        }
        if let Some(idx) = crate::svcregistry::lookup(TABLE, "svc.counter") {
            kprintln!("ABR|DIAG|injecting=svc_invalid_transition|id=svc.counter|to=STARTING");
            let Kernel { set, host, .. } = k;
            let _ = set.request(idx, SvcState::Starting, host);
        }
    });
}
