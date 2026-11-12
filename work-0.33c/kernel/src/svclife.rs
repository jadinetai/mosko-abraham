//! Service lifecycle (ABRAHAM 0.32, D-ABR-019; design §3). Portable logic, no `unsafe`. Same style as lifecycle.rs.
//!
//! States: DECLARED, STARTING, RUNNING, STOPPING, STOPPED, FAILED. The 7 allowed transitions:
//!   DECLARED -> STARTING        start (kernel OPERATIONAL, installed, every dependency RUNNING: checked by svcrun.rs)
//!   STARTING -> RUNNING         readiness established (svcrun.rs)
//!   STARTING -> FAILED          readiness failed or contradicted
//!   RUNNING  -> STOPPING        a dependency left RUNNING
//!   RUNNING  -> FAILED          step error, contract violation, or 3 overruns without a good step between
//!   STOPPING -> STOPPED         stop hook returned
//!   STOPPING -> FAILED          stop hook returned an error
//! Reserved (design Q2): STOPPED -> DECLARED and FAILED -> DECLARED, only through `manual_reset` with a
//! `ManualReset` token. 0.32 has no automatic restart and the kernel has no call site for it (static check).
//! Every other (from, to) pair, including a repeat, is refused; the state and sequence number are unchanged.

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum SvcState {
    Declared = 0,
    Starting = 1,
    Running = 2,
    Stopping = 3,
    Stopped = 4,
    Failed = 5,
}

pub const ALL_STATES: [SvcState; 6] = [
    SvcState::Declared, SvcState::Starting, SvcState::Running, SvcState::Stopping, SvcState::Stopped, SvcState::Failed,
];

impl SvcState {
    pub const fn name(self) -> &'static str {
        match self {
            SvcState::Declared => "DECLARED",
            SvcState::Starting => "STARTING",
            SvcState::Running => "RUNNING",
            SvcState::Stopping => "STOPPING",
            SvcState::Stopped => "STOPPED",
            SvcState::Failed => "FAILED",
        }
    }
}

/// The 7 allowed transitions.
pub const fn allowed(from: SvcState, to: SvcState) -> bool {
    matches!(
        (from, to),
        (SvcState::Declared, SvcState::Starting)
            | (SvcState::Starting, SvcState::Running)
            | (SvcState::Starting, SvcState::Failed)
            | (SvcState::Running, SvcState::Stopping)
            | (SvcState::Running, SvcState::Failed)
            | (SvcState::Stopping, SvcState::Stopped)
            | (SvcState::Stopping, SvcState::Failed)
    )
}

/// The 2 reserved manual-reset transitions (never through `advance`).
pub const fn reserved_reset(from: SvcState, to: SvcState) -> bool {
    matches!((from, to), (SvcState::Stopped, SvcState::Declared) | (SvcState::Failed, SvcState::Declared))
}

/// Evidence that a reviewed operator asked for a reset. 0.32 has no operator path: nothing in the kernel makes one.
pub struct ManualReset {
    _reviewed: (),
}

impl ManualReset {
    pub const fn reviewed_operator_request() -> Self {
        ManualReset { _reviewed: () }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Transition {
    pub seq: u32,
    pub from: SvcState,
    pub to: SvcState,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Refused {
    pub from: SvcState,
    pub to: SvcState,
}

impl Refused {
    pub const fn code(self) -> &'static str {
        "SVC_INVALID_TRANSITION"
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct SvcLife {
    state: SvcState,
    seq: u32,
}

impl SvcLife {
    pub const fn new() -> Self {
        SvcLife { state: SvcState::Declared, seq: 0 }
    }

    pub const fn state(&self) -> SvcState {
        self.state
    }

    pub const fn seq(&self) -> u32 {
        self.seq
    }

    /// Request `to`; refused unless (state, to) is one of the 7 allowed transitions.
    pub fn advance(&mut self, to: SvcState) -> Result<Transition, Refused> {
        if !allowed(self.state, to) {
            return Err(Refused { from: self.state, to });
        }
        Ok(self.commit(to))
    }

    /// Reserved: STOPPED or FAILED back to DECLARED, only with a reviewed operator request.
    pub fn manual_reset(&mut self, _token: ManualReset) -> Result<Transition, Refused> {
        if !reserved_reset(self.state, SvcState::Declared) {
            return Err(Refused { from: self.state, to: SvcState::Declared });
        }
        Ok(self.commit(SvcState::Declared))
    }

    fn commit(&mut self, to: SvcState) -> Transition {
        let from = self.state;
        self.seq = self.seq.saturating_add(1);
        self.state = to;
        Transition { seq: self.seq, from, to }
    }
}
