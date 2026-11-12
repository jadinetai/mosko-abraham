//! `svc.counter` (ABRAHAM 0.32, P-16, D-ABR-019): a local service with an observable, monotonically increasing
//! counter. Portable, no `unsafe`. One step = one checked increment = one work unit; there is no loop in it. At the
//! maximum value the step fails (SVC_COUNTER_OVERFLOW) instead of wrapping.

use crate::svcrun::StepOutcome;

pub struct Counter {
    value: u64,
}

impl Counter {
    pub const fn new() -> Self {
        Counter { value: 0 }
    }

    /// Hosted tests only need this to reach the overflow; the kernel always starts at 0.
    pub const fn with_value(value: u64) -> Self {
        Counter { value }
    }

    pub fn start(&mut self) -> Result<(), &'static str> {
        self.value = 0;
        Ok(())
    }

    pub fn step(&mut self, budget: u32) -> StepOutcome {
        if budget == 0 {
            return StepOutcome::Done { units: 0 };
        }
        match self.value.checked_add(1) {
            Some(v) => {
                self.value = v;
                StepOutcome::Done { units: 1 }
            }
            None => StepOutcome::Error("SVC_COUNTER_OVERFLOW"),
        }
    }

    /// The service's own check: it has done its probe step.
    pub fn ready(&self) -> Result<(), &'static str> {
        if self.value >= 1 { Ok(()) } else { Err("SVC_COUNTER_NOT_READY") }
    }

    pub fn observed(&self) -> Option<u64> {
        Some(self.value)
    }

    pub fn stop(&mut self) -> Result<(), &'static str> {
        Ok(())
    }
}
