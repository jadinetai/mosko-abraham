//! Launch request lifecycle (ABRAHAM 0.33, design §5). Portable, no `unsafe`, no allocation.
//!
//!   SUBMITTED -> REFUSED                       (terminal)  refused at admission, structure, operation or recognition
//!   SUBMITTED -> VALIDATED                                 admitted, well-formed and known: NOT an acceptance to run
//!   VALIDATED -> NOT_EXECUTED                  (terminal)  stopped after validation; nothing ran
//!   reserved for 0.4 (refused in 0.33, LAUNCH_TRANSITION_RESERVED):
//!   VALIDATED -> DISPATCHED; DISPATCHED -> RUNNING | FAULTED | LOST; RUNNING -> EXITED | FAULTED | LOST
//!   every other pair of the 81 is invalid (LAUNCH_INVALID_TRANSITION). Terminal states never move.
//!
//! A refused transition leaves the state unchanged. Entering RUNNING would additionally need `ExecutionEvidence`,
//! which no 0.33 code can construct (private field, no constructor): only a future process loader may create it.
//! LOST will map to ExecutionReport `result=UNKNOWN` (P-22), never to completion.

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum RequestState {
    Submitted,
    Refused,
    Validated,
    NotExecuted,
    Dispatched,
    Running,
    Exited,
    Faulted,
    Lost,
}

pub const ALL_STATES: [RequestState; 9] = [
    RequestState::Submitted, RequestState::Refused, RequestState::Validated, RequestState::NotExecuted,
    RequestState::Dispatched, RequestState::Running, RequestState::Exited, RequestState::Faulted, RequestState::Lost,
];

impl RequestState {
    pub const fn name(self) -> &'static str {
        match self {
            RequestState::Submitted => "SUBMITTED",
            RequestState::Refused => "REFUSED",
            RequestState::Validated => "VALIDATED",
            RequestState::NotExecuted => "NOT_EXECUTED",
            RequestState::Dispatched => "DISPATCHED",
            RequestState::Running => "RUNNING",
            RequestState::Exited => "EXITED",
            RequestState::Faulted => "FAULTED",
            RequestState::Lost => "LOST",
        }
    }
    pub const fn terminal(self) -> bool {
        matches!(self, RequestState::Refused | RequestState::NotExecuted | RequestState::Exited
                     | RequestState::Faulted | RequestState::Lost)
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Pair {
    Allowed,
    Reserved,
    Invalid,
}

pub const fn pair(from: RequestState, to: RequestState) -> Pair {
    use RequestState::*;
    match (from, to) {
        (Submitted, Refused) | (Submitted, Validated) | (Validated, NotExecuted) => Pair::Allowed,
        (Validated, Dispatched) | (Dispatched, Running) | (Dispatched, Faulted) | (Dispatched, Lost)
        | (Running, Exited) | (Running, Faulted) | (Running, Lost) => Pair::Reserved,
        _ => Pair::Invalid,
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Transition {
    pub seq: u8,
    pub from: RequestState,
    pub to: RequestState,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Refused {
    pub from: RequestState,
    pub to: RequestState,
    pub code: &'static str,
}

/// Proof that an independent executable has started. Reserved for 0.4: the private field and the absence of any
/// constructor mean no 0.33 code can make one, so no 0.33 path can report RUNNING.
#[derive(Debug)]
pub struct ExecutionEvidence {
    _private: (),
}

/// The lifecycle of one request. Only launch.rs moves it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Life {
    state: RequestState,
    seq: u8,
}

impl Life {
    pub const fn new() -> Self {
        Life { state: RequestState::Submitted, seq: 0 }
    }
    pub const fn state(&self) -> RequestState {
        self.state
    }
    pub const fn check(&self, to: RequestState) -> Result<(), Refused> {
        match pair(self.state, to) {
            Pair::Allowed => Ok(()),
            Pair::Reserved => Err(Refused { from: self.state, to, code: "LAUNCH_TRANSITION_RESERVED" }),
            Pair::Invalid => Err(Refused { from: self.state, to, code: "LAUNCH_INVALID_TRANSITION" }),
        }
    }
    /// Move to `to` if the pair is allowed in 0.33; otherwise refuse and change nothing.
    pub(crate) fn advance(&mut self, to: RequestState) -> Result<Transition, Refused> {
        self.check(to)?;
        let t = Transition { seq: self.seq + 1, from: self.state, to };
        self.state = to;
        self.seq += 1;
        Ok(t)
    }
    /// The 0.4 entry into RUNNING. In 0.33 it is refused like every reserved transition, and it cannot even be
    /// called, because `ExecutionEvidence` cannot be constructed.
    pub fn start_running(&mut self, _evidence: ExecutionEvidence) -> Result<Transition, Refused> {
        Err(Refused { from: self.state, to: RequestState::Running, code: "LAUNCH_TRANSITION_RESERVED" })
    }
}
