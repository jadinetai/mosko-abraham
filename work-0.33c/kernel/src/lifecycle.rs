//! Kernel initialization lifecycle (ABRAHAM 0.31b, D-ABR-014). Portable logic, no `unsafe`.
//!
//! EARLY -> LOADER_VERIFIED -> MEMORY_OWNED -> MEMORY_VERIFIED -> CPU_TABLES_LOADED -> TIMER_RUNNING
//!       -> OWNERSHIP_VERIFIED -> OPERATIONAL, plus terminal FAILED.
//!
//! Rules: a state may advance only to the next one in that chain. FAILED is reachable from every
//! state except FAILED itself, and nothing leaves FAILED. Skipping, going back, repeating a state or
//! leaving FAILED is refused (INIT_INVALID_TRANSITION) and the state is left unchanged. OPERATIONAL
//! can therefore only be reached after both memory-ownership checks passed. EARLY is the initial
//! state (kmain entered, console up), so a clean boot makes exactly 7 transitions.

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum InitState {
    Early = 0,
    LoaderVerified = 1,
    MemoryOwned = 2,
    MemoryVerified = 3,
    CpuTablesLoaded = 4,
    TimerRunning = 5,
    OwnershipVerified = 6,
    Operational = 7,
    Failed = 8,
}

pub const ALL_STATES: [InitState; 9] = [
    InitState::Early, InitState::LoaderVerified, InitState::MemoryOwned, InitState::MemoryVerified,
    InitState::CpuTablesLoaded, InitState::TimerRunning, InitState::OwnershipVerified, InitState::Operational,
    InitState::Failed,
];

impl InitState {
    pub const fn name(self) -> &'static str {
        match self {
            InitState::Early => "EARLY",
            InitState::LoaderVerified => "LOADER_VERIFIED",
            InitState::MemoryOwned => "MEMORY_OWNED",
            InitState::MemoryVerified => "MEMORY_VERIFIED",
            InitState::CpuTablesLoaded => "CPU_TABLES_LOADED",
            InitState::TimerRunning => "TIMER_RUNNING",
            InitState::OwnershipVerified => "OWNERSHIP_VERIFIED",
            InitState::Operational => "OPERATIONAL",
            InitState::Failed => "FAILED",
        }
    }

    pub const fn from_u8(v: u8) -> InitState {
        match v {
            0 => InitState::Early,
            1 => InitState::LoaderVerified,
            2 => InitState::MemoryOwned,
            3 => InitState::MemoryVerified,
            4 => InitState::CpuTablesLoaded,
            5 => InitState::TimerRunning,
            6 => InitState::OwnershipVerified,
            7 => InitState::Operational,
            _ => InitState::Failed,
        }
    }

    /// The only state this one may advance to (FAILED aside).
    pub const fn next(self) -> Option<InitState> {
        match self {
            InitState::Early => Some(InitState::LoaderVerified),
            InitState::LoaderVerified => Some(InitState::MemoryOwned),
            InitState::MemoryOwned => Some(InitState::MemoryVerified),
            InitState::MemoryVerified => Some(InitState::CpuTablesLoaded),
            InitState::CpuTablesLoaded => Some(InitState::TimerRunning),
            InitState::TimerRunning => Some(InitState::OwnershipVerified),
            InitState::OwnershipVerified => Some(InitState::Operational),
            InitState::Operational | InitState::Failed => None,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Transition {
    pub seq: u32,
    pub from: InitState,
    pub to: InitState,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Refused {
    pub from: InitState,
    pub to: InitState,
}

impl Refused {
    pub const fn code(self) -> &'static str {
        "INIT_INVALID_TRANSITION"
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Lifecycle {
    state: InitState,
    seq: u32,
}

impl Lifecycle {
    pub const fn new() -> Self {
        Lifecycle { state: InitState::Early, seq: 0 }
    }

    pub const fn from_parts(state: InitState, seq: u32) -> Self {
        Lifecycle { state, seq }
    }

    pub fn state(&self) -> InitState {
        self.state
    }

    pub fn seq(&self) -> u32 {
        self.seq
    }

    /// Request `to`. FAILED is requested through `fail`, never here.
    pub fn advance(&mut self, to: InitState) -> Result<Transition, Refused> {
        if to == InitState::Failed || self.state.next() != Some(to) {
            return Err(Refused { from: self.state, to });
        }
        Ok(self.commit(to))
    }

    /// Enter FAILED from any state except FAILED.
    pub fn fail(&mut self) -> Result<Transition, Refused> {
        if self.state == InitState::Failed {
            return Err(Refused { from: InitState::Failed, to: InitState::Failed });
        }
        Ok(self.commit(InitState::Failed))
    }

    fn commit(&mut self, to: InitState) -> Transition {
        let from = self.state;
        self.seq = self.seq.saturating_add(1);
        self.state = to;
        Transition { seq: self.seq, from, to }
    }
}
