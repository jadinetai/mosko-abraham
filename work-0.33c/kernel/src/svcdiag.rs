//! DIAGNOSTIC service behaviors (ABRAHAM 0.32, design §7). Compiled only into the builds diag-svc-defects,
//! diag-svc-slow and diag-svc-stall, never into an accepted kernel. Each one is a deliberately defective service:
//!   svc.diagready  does its work honestly, but its own readiness check fails (SVC_DIAG_NOT_READY);
//!   svc.diagliar   claims one work unit per step and claims readiness, but its state never changes;
//!   svc.diagdep    depends on svc.diagready, so it must be withheld;
//!   svc.diagslow   every step busy-waits 20 ms (bounded), so every step overruns the 1 ms budget;
//!   svc.diagstall  every step after the probe busy-waits 6 s (bounded): longer than the clock guard's 5 s step.
//!   svc.diagflaky  (0.32b, diag-svc-cascade) works for its probe and 2 loop steps, then fails on the 3rd;
//!   svc.diagdep2   (0.32b) depends on svc.diagflaky and counts its own steps: it must never be stepped after
//!                  svc.diagflaky left RUNNING (audit finding 1).

use crate::clock;
use crate::svcregistry::ServiceId;
use crate::svcrun::StepOutcome;
use crate::svctable::{SVC_DIAGDEP, SVC_DIAGDEP2, SVC_DIAGFLAKY, SVC_DIAGLIAR, SVC_DIAGREADY, SVC_DIAGSLOW, SVC_DIAGSTALL};

pub struct Diag {
    ready: u64,
    liar: u64,
    dep: u64,
    slow: u64,
    stall: u64,
    flaky: u64,
    dep2: u64,
}

pub fn owns(id: ServiceId) -> bool {
    matches!(id, SVC_DIAGREADY | SVC_DIAGLIAR | SVC_DIAGDEP | SVC_DIAGSLOW | SVC_DIAGSTALL | SVC_DIAGFLAKY | SVC_DIAGDEP2)
}

/// Busy-wait about `ms` milliseconds on the raw TSC, with an iteration cap so it always ends.
fn spin(tsc_hz: u64, ms: u64) {
    let start = clock::read_tsc();
    let target = tsc_hz / 1000 * ms;
    let mut n: u64 = 0;
    while clock::read_tsc().wrapping_sub(start) < target && n < 4_000_000_000 {
        n += 1;
        core::hint::spin_loop();
    }
}

fn inc(v: &mut u64, budget: u32) -> StepOutcome {
    if budget == 0 {
        return StepOutcome::Done { units: 0 };
    }
    match v.checked_add(1) {
        Some(n) => {
            *v = n;
            StepOutcome::Done { units: 1 }
        }
        None => StepOutcome::Error("SVC_COUNTER_OVERFLOW"),
    }
}

impl Diag {
    pub const fn new() -> Self {
        Diag { ready: 0, liar: 0, dep: 0, slow: 0, stall: 0, flaky: 0, dep2: 0 }
    }

    pub fn start(&mut self, _id: ServiceId) -> Result<(), &'static str> {
        Ok(())
    }

    pub fn step(&mut self, id: ServiceId, budget: u32, tsc_hz: u64) -> StepOutcome {
        match id {
            SVC_DIAGREADY => inc(&mut self.ready, budget),
            SVC_DIAGLIAR => StepOutcome::Done { units: 1 },
            SVC_DIAGDEP => inc(&mut self.dep, budget),
            SVC_DIAGSLOW => {
                spin(tsc_hz, 20);
                inc(&mut self.slow, budget)
            }
            SVC_DIAGSTALL => {
                if self.stall >= 1 {
                    spin(tsc_hz, 6_000);
                }
                inc(&mut self.stall, budget)
            }
            SVC_DIAGFLAKY => {
                if self.flaky >= 3 {
                    return StepOutcome::Error("SVC_DIAG_INJECTED_STEP_ERROR");
                }
                inc(&mut self.flaky, budget)
            }
            SVC_DIAGDEP2 => inc(&mut self.dep2, budget),
            _ => StepOutcome::Error("SVC_NO_BEHAVIOR"),
        }
    }

    pub fn ready(&self, id: ServiceId) -> Result<(), &'static str> {
        match id {
            SVC_DIAGREADY => Err("SVC_DIAG_NOT_READY"),
            _ => Ok(()),
        }
    }

    pub fn observed(&self, id: ServiceId) -> Option<u64> {
        match id {
            SVC_DIAGREADY => Some(self.ready),
            SVC_DIAGLIAR => Some(self.liar),
            SVC_DIAGDEP => Some(self.dep),
            SVC_DIAGSLOW => Some(self.slow),
            SVC_DIAGSTALL => Some(self.stall),
            SVC_DIAGFLAKY => Some(self.flaky),
            SVC_DIAGDEP2 => Some(self.dep2),
            _ => None,
        }
    }
}
