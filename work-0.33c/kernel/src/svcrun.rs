//! Service manager core (ABRAHAM 0.32, D-ABR-019; design §3-§5; corrected in 0.32b, D-ABR-020). Portable logic,
//! no `unsafe`, no allocation.
//! The kernel side (svcmgr.rs) supplies a `Host`: the clock, the lifecycle state, the service behaviors and the
//! output. Hosted tests supply a scripted one.
//!
//! - `start_all` refuses unless the kernel lifecycle is exactly OPERATIONAL. Then it validates the table again
//!   (boot-time check), and starts the entries in dependency order. A not-installed entry is skipped. An entry whose
//!   dependency is not RUNNING is withheld and stays DECLARED. Readiness is checked as follows:
//!   1. the start hook runs;
//!   2. one probe step runs and must do at least one work unit within the budget;
//!   3. the service's own `ready` must pass;
//!   4. the observable state must equal the units the kernel counted.
//!   Only then is the entry RUNNING.
//!   0.32b (audit finding 3): the probe is a step, so its time is measured and judged like every step (one
//!   accounting function, `account`). A probe over the budget is an overrun: the entry is RUNNING but DEGRADED,
//!   never AVAILABLE on it. A probe that cannot be measured is not a fresh success, so the entry is not reported
//!   AVAILABLE until a measured step completes. The verdict is printed with readiness (`probe_timing=`).
//! - `step_all`: one step per RUNNING entry, in order. Work is bounded by the declared budget; using more is a
//!   contract violation (FAILED). Elapsed time is measured AFTER the step returns (raw TSC). It is never a timeout:
//!   nothing can interrupt a step. An overrun makes the entry DEGRADED; 3 overruns without an intervening verified
//!   in-budget step make it FAILED (D-ABR-021: not necessarily 3 adjacent calls); 100 in-budget steps recover it. A reading that goes backwards is "unmeasured", never a success, and (0.32b, finding 2) it
//!   breaks the streak of consecutive in-budget steps that recovery needs.
//! - A failure stops the RUNNING dependents in reverse dependency order. Nothing restarts automatically.
//!   0.32b (finding 1): before every step the manager checks that each dependency of the entry is RUNNING; if one is
//!   not, the entry is not stepped but stopped (with its own dependents, dependents first). A dependency always comes
//!   before its dependents in the order, so a dependent is stopped in the very cycle its dependency left RUNNING, and
//!   never runs another step after that.
//! - Lifecycle transitions are made only here. An external `request` is always refused, and the state is unchanged.

use crate::svclife::{Refused, SvcLife, SvcState, Transition};
use crate::svcregistry::{index_of, lookup, validate, Desc, Order, RegError, MAX_ENTRIES};
use crate::svcstatus::{map, ClockTrust, DepBlock, Inputs, PublicReason, PublicStatus};

/// Step time budget, measured after return (design Q4).
pub const STEP_BUDGET_US: u64 = 1_000;
/// Consecutive overruns that make a RUNNING entry FAILED.
pub const FAIL_AFTER_OVERRUNS: u32 = 3;
/// Consecutive in-budget steps that end the DEGRADED window.
pub const RECOVER_AFTER_GOOD: u32 = 100;
/// Period of the public status report.
pub const REPORT_PERIOD_MS: u64 = 5_000;

/// 0.32b: the time verdict of one step (the probe included), measured after it returned.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum StepTiming {
    InBudget,
    Overrun,
    Unmeasured,
}

impl StepTiming {
    pub const fn name(self) -> &'static str {
        match self {
            StepTiming::InBudget => "IN_BUDGET",
            StepTiming::Overrun => "OVERRUN",
            StepTiming::Unmeasured => "UNMEASURED",
        }
    }

    pub const fn of(us: Option<u64>) -> StepTiming {
        match us {
            None => StepTiming::Unmeasured,
            Some(v) if v > STEP_BUDGET_US => StepTiming::Overrun,
            Some(_) => StepTiming::InBudget,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum StepOutcome {
    /// The step finished and reports the work units it used.
    Done { units: u32 },
    /// The step failed with a registered kernel diagnostic code.
    Error(&'static str),
}

/// What the manager reports. The host prints it and records events; nothing is ever read back.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Report {
    StartRefused { diag: &'static str },
    RegistryOk { entries: usize, order: Order },
    RegistryRefused { error: RegError },
    NotInstalled { idx: usize },
    Withheld { idx: usize, dep: usize, dep_state: SvcState },
    Transition { idx: usize, t: Transition, diag: Option<&'static str> },
    Refused { idx: usize, r: Refused, diag: &'static str },
    Ready { idx: usize, probe_units: u32, kernel_units: u64, observed: Option<u64>, probe_us: Option<u64>, timing: StepTiming },
    ReadyFail { idx: usize, diag: &'static str },
    Overrun { idx: usize, elapsed_us: u64, consecutive: u32 },
    Unmeasured { idx: usize },
    Degraded { idx: usize },
    Recovered { idx: usize },
}

pub trait Host {
    fn kernel_operational(&self) -> bool;
    fn tsc(&mut self) -> u64;
    fn tsc_hz(&self) -> u64;
    /// Guarded boot-epoch uptime in ms (clock.rs peek), None if unreadable.
    fn uptime_ms(&mut self) -> Option<u64>;
    fn svc_start(&mut self, idx: usize) -> Result<(), &'static str>;
    fn svc_step(&mut self, idx: usize, budget: u32) -> StepOutcome;
    fn svc_ready(&mut self, idx: usize) -> Result<(), &'static str>;
    /// The entry's observable state (its own count of completed work units), read from its state.
    fn svc_observed(&self, idx: usize) -> Option<u64>;
    fn svc_stop(&mut self, idx: usize) -> Result<(), &'static str>;
    fn report(&mut self, table: &[Desc], r: Report);
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Registry {
    NotChecked,
    Ok,
    Refused(RegError),
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum StartResult {
    NotOperational,
    AlreadyStarted,
    RegistryRefused,
    Started,
}

/// Per-entry accounting, all fixed-size.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Runtime {
    pub life: SvcLife,
    /// Loop steps after the probe.
    pub steps: u64,
    /// Work units counted by the kernel (probe included).
    pub units: u64,
    pub overruns: u64,
    pub consecutive: u32,
    pub good: u32,
    pub overrun_window: bool,
    pub unmeasured: u64,
    pub last_step_ms: Option<u64>,
    pub withheld_by: Option<u8>,
}

impl Runtime {
    pub const NEW: Runtime = Runtime {
        life: SvcLife::new(), steps: 0, units: 0, overruns: 0, consecutive: 0, good: 0, overrun_window: false,
        unmeasured: 0, last_step_ms: None, withheld_by: None,
    };
}

pub struct ServiceSet {
    table: &'static [Desc],
    rt: [Runtime; MAX_ENTRIES],
    order: Order,
    registry: Registry,
}

fn elapsed_us(before: u64, after: u64, hz: u64) -> Option<u64> {
    if after < before || hz == 0 {
        return None;
    }
    let v = ((after - before) as u128) * 1_000_000 / (hz as u128);
    Some(if v > u64::MAX as u128 { u64::MAX } else { v as u64 })
}

impl ServiceSet {
    pub const fn new(table: &'static [Desc]) -> Self {
        ServiceSet { table, rt: [Runtime::NEW; MAX_ENTRIES], order: Order::empty(), registry: Registry::NotChecked }
    }

    pub fn table(&self) -> &'static [Desc] {
        self.table
    }

    pub fn registry(&self) -> Registry {
        self.registry
    }

    pub fn order(&self) -> Order {
        self.order
    }

    pub fn runtime(&self, idx: usize) -> Runtime {
        self.rt[idx]
    }

    pub fn state(&self, idx: usize) -> SvcState {
        self.rt[idx].life.state()
    }

    fn entries(&self) -> usize {
        core::cmp::min(self.table.len(), MAX_ENTRIES)
    }

    fn go(&mut self, idx: usize, to: SvcState, diag: Option<&'static str>, h: &mut impl Host) -> bool {
        match self.rt[idx].life.advance(to) {
            Ok(t) => {
                h.report(self.table, Report::Transition { idx, t, diag });
                true
            }
            Err(r) => {
                h.report(self.table, Report::Refused { idx, r, diag: r.code() });
                false
            }
        }
    }

    fn fail(&mut self, idx: usize, diag: &'static str, h: &mut impl Host) {
        self.go(idx, SvcState::Failed, Some(diag), h);
    }

    /// Start phase (design §3). Callable once with effect; a refused call changes nothing.
    pub fn start_all(&mut self, h: &mut impl Host) -> StartResult {
        if !h.kernel_operational() {
            h.report(self.table, Report::StartRefused { diag: "SVC_KERNEL_NOT_OPERATIONAL" });
            return StartResult::NotOperational;
        }
        if self.registry != Registry::NotChecked {
            h.report(self.table, Report::StartRefused { diag: "SVC_ALREADY_STARTED" });
            return StartResult::AlreadyStarted;
        }
        match validate(self.table) {
            Err(error) => {
                self.registry = Registry::Refused(error);
                h.report(self.table, Report::RegistryRefused { error });
                StartResult::RegistryRefused
            }
            Ok(order) => {
                self.order = order;
                self.registry = Registry::Ok;
                h.report(self.table, Report::RegistryOk { entries: self.table.len(), order });
                for k in 0..order.len() {
                    self.try_start(order.get(k), h);
                }
                StartResult::Started
            }
        }
    }

    fn try_start(&mut self, idx: usize, h: &mut impl Host) {
        let d = self.table[idx];
        if !d.installed {
            h.report(self.table, Report::NotInstalled { idx });
            return;
        }
        for dep in d.deps {
            let Some(j) = index_of(self.table, *dep) else { return };
            if self.state(j) != SvcState::Running {
                self.rt[idx].withheld_by = Some(j as u8);
                h.report(self.table, Report::Withheld { idx, dep: j, dep_state: self.state(j) });
                return;
            }
        }
        if !self.go(idx, SvcState::Starting, None, h) {
            return;
        }
        if let Err(diag) = h.svc_start(idx) {
            h.report(self.table, Report::ReadyFail { idx, diag });
            self.fail(idx, "SVC_READINESS_FAILED", h);
            return;
        }
        let before = h.tsc();
        let out = h.svc_step(idx, d.budget);
        let after = h.tsc();
        let units = match out {
            StepOutcome::Error(diag) => {
                h.report(self.table, Report::ReadyFail { idx, diag });
                self.fail(idx, "SVC_READINESS_FAILED", h);
                return;
            }
            StepOutcome::Done { units } => units,
        };
        if units > d.budget {
            self.fail(idx, "SVC_CONTRACT_VIOLATION", h);
            return;
        }
        self.rt[idx].units = units as u64;
        if let Err(diag) = h.svc_ready(idx) {
            h.report(self.table, Report::ReadyFail { idx, diag });
            self.fail(idx, "SVC_READINESS_FAILED", h);
            return;
        }
        let observed = h.svc_observed(idx);
        if units == 0 || observed != Some(units as u64) {
            h.report(self.table, Report::ReadyFail { idx, diag: "SVC_READINESS_CONTRADICTED" });
            self.fail(idx, "SVC_READINESS_CONTRADICTED", h);
            return;
        }
        let probe_us = elapsed_us(before, after, h.tsc_hz());
        let timing = StepTiming::of(probe_us);
        h.report(self.table, Report::Ready { idx, probe_units: units, kernel_units: units as u64, observed, probe_us, timing });
        if !self.go(idx, SvcState::Running, None, h) {
            return;
        }
        // 0.32b (finding 3): the probe is judged by the same accounting as every step.
        if self.account(idx, probe_us, h) {
            self.fail(idx, "SVC_STEP_OVERRUN", h);
            return;
        }
        if timing != StepTiming::Unmeasured {
            self.rt[idx].last_step_ms = h.uptime_ms();
        }
    }

    /// Time accounting of one completed step (the probe included), measured after it returned (design §4).
    /// Returns true if the entry must now be FAILED (FAIL_AFTER_OVERRUNS overruns with no verified in-budget step between them; D-ABR-021).
    fn account(&mut self, idx: usize, us: Option<u64>, h: &mut impl Host) -> bool {
        let Some(us) = us else {
            let r = &mut self.rt[idx];
            r.unmeasured = r.unmeasured.saturating_add(1);
            r.good = 0; // 0.32b (finding 2): not an in-budget step, so the consecutive streak is broken
            h.report(self.table, Report::Unmeasured { idx });
            return false;
        };
        if us > STEP_BUDGET_US {
            let r = &mut self.rt[idx];
            r.overruns = r.overruns.saturating_add(1);
            r.consecutive = r.consecutive.saturating_add(1);
            r.good = 0;
            let (consecutive, first) = (r.consecutive, !r.overrun_window);
            r.overrun_window = true;
            h.report(self.table, Report::Overrun { idx, elapsed_us: us, consecutive });
            if first {
                h.report(self.table, Report::Degraded { idx });
            }
            return consecutive >= FAIL_AFTER_OVERRUNS;
        }
        let r = &mut self.rt[idx];
        r.consecutive = 0;
        r.good = r.good.saturating_add(1);
        if r.overrun_window && r.good >= RECOVER_AFTER_GOOD {
            r.overrun_window = false;
            h.report(self.table, Report::Recovered { idx });
        }
        false
    }

    /// Every dependency of `idx` is RUNNING.
    fn deps_running(&self, idx: usize) -> bool {
        self.table[idx].deps.iter().all(|d| matches!(index_of(self.table, *d), Some(j) if self.state(j) == SvcState::Running))
    }

    /// One cooperative step for every RUNNING entry, in start order (design §4).
    pub fn step_all(&mut self, h: &mut impl Host) {
        if self.registry != Registry::Ok {
            return;
        }
        for k in 0..self.order.len() {
            let idx = self.order.get(k);
            if self.state(idx) != SvcState::Running {
                continue;
            }
            // 0.32b (finding 1): never step an entry whose dependency is not RUNNING; stop it (dependents first).
            if !self.deps_running(idx) {
                self.stop_dependents(h);
                continue;
            }
            let budget = self.table[idx].budget;
            let before = h.tsc();
            let out = h.svc_step(idx, budget);
            let after = h.tsc();
            let units = match out {
                StepOutcome::Error(diag) => {
                    self.fail(idx, diag, h);
                    continue;
                }
                StepOutcome::Done { units } => units,
            };
            if units > budget {
                self.fail(idx, "SVC_CONTRACT_VIOLATION", h);
                continue;
            }
            let r = &mut self.rt[idx];
            r.units = r.units.saturating_add(units as u64);
            r.steps = r.steps.saturating_add(1);
            let accounted = r.units;
            if h.svc_observed(idx) != Some(accounted) {
                self.fail(idx, "SVC_CONTRACT_VIOLATION", h);
                continue;
            }
            let us = elapsed_us(before, after, h.tsc_hz());
            if self.account(idx, us, h) {
                self.fail(idx, "SVC_STEP_OVERRUN", h);
                continue;
            }
            if us.is_some() {
                self.rt[idx].last_step_ms = h.uptime_ms();
            }
        }
    }

    /// Stop every RUNNING entry that depends, directly or not, on an entry that is not RUNNING; dependents first.
    fn stop_dependents(&mut self, h: &mut impl Host) {
        let mut stop = [false; MAX_ENTRIES];
        for k in 0..self.order.len() {
            let idx = self.order.get(k);
            if self.state(idx) != SvcState::Running {
                continue;
            }
            for dep in self.table[idx].deps {
                if let Some(j) = index_of(self.table, *dep) {
                    if self.state(j) != SvcState::Running || stop[j] {
                        stop[idx] = true;
                    }
                }
            }
        }
        for k in (0..self.order.len()).rev() {
            let idx = self.order.get(k);
            if !stop[idx] {
                continue;
            }
            if !self.go(idx, SvcState::Stopping, Some("SVC_DEPENDENCY_LOST"), h) {
                continue;
            }
            match h.svc_stop(idx) {
                Ok(()) => {
                    self.go(idx, SvcState::Stopped, None, h);
                }
                Err(diag) => self.fail(idx, diag, h),
            }
        }
    }

    /// An external transition request. Transitions are made only by the manager, so every request is refused, with
    /// the state unchanged: SVC_INVALID_TRANSITION if the pair is not in the matrix, SVC_TRANSITION_MANAGER_ONLY if
    /// it is.
    pub fn request(&mut self, idx: usize, to: SvcState, h: &mut impl Host) -> bool {
        if idx >= self.entries() {
            return false;
        }
        let from = self.state(idx);
        let r = Refused { from, to };
        let diag = if crate::svclife::allowed(from, to) { "SVC_TRANSITION_MANAGER_ONLY" } else { r.code() };
        h.report(self.table, Report::Refused { idx, r, diag });
        false
    }

    fn root_not_installed(&self, mut d: usize) -> bool {
        for _ in 0..MAX_ENTRIES {
            if !self.table[d].installed {
                return true;
            }
            match self.rt[d].withheld_by {
                Some(x) if self.state(d) == SvcState::Declared => d = x as usize,
                _ => return false,
            }
        }
        false
    }

    /// Public status of one entry (design §5), built from the registry only.
    pub fn status(&self, idx: usize, clock: ClockTrust, now_ms: Option<u64>) -> PublicStatus {
        let r = &self.rt[idx];
        let state = r.life.state();
        let withheld = match r.withheld_by {
            Some(d) if state == SvcState::Declared => {
                if self.root_not_installed(d as usize) { DepBlock::NotInstalledRoot } else { DepBlock::Other }
            }
            _ => DepBlock::None,
        };
        map(&Inputs {
            registry_ok: self.registry == Registry::Ok,
            installed: self.table[idx].installed,
            state,
            withheld,
            last_step_ms: r.last_step_ms,
            now_ms,
            clock,
            overrun_window: r.overrun_window,
        })
    }

    /// INSPECT_PUBLIC (P-13/P-33): exactly the operation `status` on exactly the table names. An unknown operation
    /// gives OPERATION_UNKNOWN, an unknown target TARGET_UNKNOWN. `inspect` (INSPECT_PROTECTED) and `start`, `stop`,
    /// `set`, `reset` (MUTATE) need a capability, and none exists in 0.32: CAP_MISSING (P-09, fail closed).
    /// Nothing changes in any case.
    pub fn inspect_public(&self, op: &str, target: &str, clock: ClockTrust, now_ms: Option<u64>) -> Result<PublicStatus, PublicReason> {
        let class = match op {
            "status" => 0,
            "inspect" | "start" | "stop" | "set" | "reset" => 1,
            _ => return Err(PublicReason::OperationUnknown),
        };
        let Some(idx) = lookup(self.table, target) else { return Err(PublicReason::TargetUnknown) };
        if class != 0 {
            return Err(PublicReason::CapMissing);
        }
        Ok(self.status(idx, clock, now_ms))
    }
}
