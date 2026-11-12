//! TSC clock guard (ABRAHAM 0.31b, Echo F-029-04, D-ABR-014). Portable logic, no `unsafe`, no
//! hardware access: the kernel feeds it raw TSC readings (clock.rs); kernel/hosttest tests it.
//!
//! 0.29/0.31a computed uptime as `(now - start)` with `wrapping_sub`: a TSC that went backwards
//! produced an enormous uptime, and the heartbeat then tried to print every "missing" second.
//! Here uptime advances only by the forward difference between CONSECUTIVE readings:
//! - normal: add the difference;
//! - backward (reading lower than the last one): add nothing, re-base on the new reading, and
//!   raise `TSC_BACKWARD`. Uptime never decreases and never wraps;
//! - forward jump (more than `MAX_STEP_SECONDS` between consecutive readings, which normally come
//!   every 10 ms): add it, and raise `TSC_FORWARD_JUMP`. Under P-39 expiry runs on this clock, so
//!   keeping the jump can only make things expire early (fail-closed); dropping it could make them
//!   live too long.
//! After the first anomaly the guard is DEGRADED for the rest of the boot: the uptime it reports is
//! no longer claimed to be true elapsed time, and the kernel says so (no false monotonic claim).
//! Uptime is non-decreasing by construction; it is NOT claimed accurate once DEGRADED.

/// Largest step between two consecutive readings that is accepted silently.
pub const MAX_STEP_SECONDS: u64 = 5;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ClockAnomaly {
    /// The reading is lower than the previous one; `arg` = how many counts back.
    Backward(u64),
    /// The reading is more than MAX_STEP_SECONDS ahead of the previous one; `arg` = counts.
    ForwardJump(u64),
}

impl ClockAnomaly {
    pub const fn code(self) -> &'static str {
        match self {
            ClockAnomaly::Backward(_) => "TSC_BACKWARD",
            ClockAnomaly::ForwardJump(_) => "TSC_FORWARD_JUMP",
        }
    }

    pub const fn counts(self) -> u64 {
        match self {
            ClockAnomaly::Backward(c) | ClockAnomaly::ForwardJump(c) => c,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Observation {
    pub uptime_ms: u64,
    pub anomaly: Option<ClockAnomaly>,
}

/// All-zero `new()`: not started, no anomaly.
#[derive(Clone, Copy, Debug)]
pub struct ClockGuard {
    hz: u64,
    last: u64,
    elapsed: u64,
    anomalies: u64,
    degraded: bool,
    started: bool,
}

impl ClockGuard {
    pub const fn new() -> Self {
        ClockGuard { hz: 0, last: 0, elapsed: 0, anomalies: 0, degraded: false, started: false }
    }

    /// Start at `raw` with `hz` counts per second. A zero rate is refused (the clock stays
    /// unstarted and every reading reports no uptime).
    pub fn start(&mut self, hz: u64, raw: u64) -> bool {
        if hz == 0 || self.started {
            return false;
        }
        *self = ClockGuard { hz, last: raw, elapsed: 0, anomalies: 0, degraded: false, started: true };
        true
    }

    pub fn started(&self) -> bool {
        self.started
    }

    pub fn degraded(&self) -> bool {
        self.degraded
    }

    pub fn anomalies(&self) -> u64 {
        self.anomalies
    }

    fn ms(&self, counts: u64) -> u64 {
        let v = (counts as u128) * 1000 / (self.hz as u128);
        if v > u64::MAX as u128 { u64::MAX } else { v as u64 }
    }

    /// Feed one reading. `None` before `start`.
    pub fn observe(&mut self, raw: u64) -> Option<Observation> {
        if !self.started {
            return None;
        }
        let anomaly = if raw < self.last {
            Some(ClockAnomaly::Backward(self.last - raw))
        } else {
            let delta = raw - self.last;
            self.elapsed = self.elapsed.saturating_add(delta);
            if delta > self.hz.saturating_mul(MAX_STEP_SECONDS) { Some(ClockAnomaly::ForwardJump(delta)) } else { None }
        };
        self.last = raw; // re-base: after a backward step, progress continues from the new reading
        if anomaly.is_some() {
            self.anomalies = self.anomalies.saturating_add(1);
            self.degraded = true;
        }
        Some(Observation { uptime_ms: self.ms(self.elapsed), anomaly })
    }

    /// Uptime the next `observe(raw)` would report, without changing anything (fault path).
    pub fn peek(&self, raw: u64) -> Option<u64> {
        if !self.started {
            return None;
        }
        let ahead = if raw >= self.last { raw - self.last } else { 0 };
        Some(self.ms(self.elapsed.saturating_add(ahead)))
    }
}
