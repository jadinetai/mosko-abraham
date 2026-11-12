//! Kernel side of the initialization lifecycle (0.31b; lifecycle.rs holds the rules).
//! Every transition is printed (`ABR|INIT|seq=..|from=..|to=..`) and recorded as an INIT event.
//! A refused transition is reported and stops the kernel (INIT_INVALID_TRANSITION).

use crate::eventlog;
use crate::events::Kind;
use crate::fault;
use crate::kcell::KCell;
use crate::kprintln;
use crate::lifecycle::{InitState, Lifecycle};

static LIFE: KCell<Lifecycle> = KCell::new(Lifecycle::new());

pub fn advance(to: InitState) {
    match LIFE.with(|l| l.advance(to)) {
        Some(Ok(t)) => {
            kprintln!("ABR|INIT|seq={}|from={}|to={}", t.seq, t.from.name(), t.to.name());
            eventlog::record(Kind::Init, t.to.name(), t.seq as u64);
        }
        Some(Err(r)) => {
            kprintln!("ABR|INIT|refused|from={}|to={}", r.from.name(), r.to.name());
            fault::stop(r.code(), r.to as u64,
                        format_args!("reason={}|from={}|to={}", r.code(), r.from.name(), r.to.name()));
        }
        None => fault::stop("INIT_INVALID_TRANSITION", to as u64, format_args!("reason=INIT_INVALID_TRANSITION|detail=BUSY")),
    }
}

/// Current state name, or BUSY if the lifecycle is being updated at this instant.
pub fn state_name() -> &'static str {
    LIFE.with(|l| l.state().name()).unwrap_or("BUSY")
}

/// Enter FAILED (fault path). Prints the transition and records it; silent if already FAILED.
pub fn fail(reason: &'static str) {
    if let Some(Ok(t)) = LIFE.with(|l| l.fail()) {
        kprintln!("ABR|INIT|seq={}|from={}|to={}|reason={}", t.seq, t.from.name(), t.to.name(), reason);
        eventlog::record(Kind::Init, t.to.name(), t.seq as u64);
    }
}

#[allow(dead_code)]
pub fn state() -> Option<InitState> {
    LIFE.with(|l| l.state())
}
