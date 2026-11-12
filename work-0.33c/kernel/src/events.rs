//! Kernel diagnostic event log (ABRAHAM 0.31b; requirement ABR-031-EVT-01; D-ABR-015, D-ABR-016).
//! Portable logic, no `unsafe`, no allocation: a fixed array owned by whoever holds the log (the
//! kernel keeps one static instance in eventlog.rs).
//!
//! - Fixed capacity CAPACITY. Records are numbered seq 1, 2, 3, ... and never renumbered.
//! - When full, the oldest record is overwritten and counted as dropped. Nothing is lost silently.
//! - Kinds: INIT, MEMORY, TIMING, FAULT; 0.32 adds SERVICE (D-ABR-019). Codes are registered kernel diagnostic codes
//!   (docs/KERNEL_DIAGNOSTICS.md), never Appendix A reason codes (D-ABR-010/011).
//! - Record and read only: no subscribers, no handlers, no dispatch (D-ABR-015).

pub const CAPACITY: usize = 32;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum Kind {
    Init = 1,
    Memory = 2,
    Timing = 3,
    Fault = 4,
    /// 0.32: service lifecycle and status changes (svcmgr.rs). Record and read only, like every kind.
    Service = 5,
}

impl Kind {
    pub const fn name(self) -> &'static str {
        match self {
            Kind::Init => "INIT",
            Kind::Memory => "MEMORY",
            Kind::Timing => "TIMING",
            Kind::Fault => "FAULT",
            Kind::Service => "SERVICE",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Event {
    pub seq: u32,
    /// None before the clock started: never a fake 0.
    pub uptime_ms: Option<u64>,
    pub kind: Kind,
    pub code: &'static str,
    pub arg: u64,
}

const EMPTY: Event = Event { seq: 0, uptime_ms: None, kind: Kind::Init, code: "", arg: 0 };

pub struct EventLog {
    slots: [Event; CAPACITY],
    recorded: u64,
}

impl EventLog {
    pub const fn new() -> Self {
        EventLog { slots: [EMPTY; CAPACITY], recorded: 0 }
    }

    /// Append one record; returns its seq.
    pub fn record(&mut self, kind: Kind, code: &'static str, arg: u64, uptime_ms: Option<u64>) -> u32 {
        let seq = (self.recorded + 1).min(u32::MAX as u64) as u32;
        let slot = (self.recorded % CAPACITY as u64) as usize;
        self.slots[slot] = Event { seq, uptime_ms, kind, code, arg };
        self.recorded += 1;
        seq
    }

    /// Every record ever appended (retained + dropped).
    pub fn recorded(&self) -> u64 {
        self.recorded
    }

    /// Records overwritten because the log was full.
    pub fn dropped(&self) -> u64 {
        self.recorded.saturating_sub(CAPACITY as u64)
    }

    pub fn retained(&self) -> usize {
        core::cmp::min(self.recorded, CAPACITY as u64) as usize
    }

    /// The retained record at position `i` (0 = oldest retained), if any.
    pub fn get(&self, i: usize) -> Option<Event> {
        if i >= self.retained() {
            return None;
        }
        let first = self.recorded - self.retained() as u64; // index of the oldest retained record
        Some(self.slots[((first + i as u64) % CAPACITY as u64) as usize])
    }

    /// The newest `n` retained records, oldest first.
    pub fn last(&self, n: usize) -> impl Iterator<Item = Event> + '_ {
        let keep = core::cmp::min(n, self.retained());
        (self.retained() - keep..self.retained()).filter_map(move |i| self.get(i))
    }
}
