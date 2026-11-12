//! Truthful fault reporting (0.31b, D-ABR-014). Every stop of the kernel goes through `stop`:
//!   ABR|FAULT|<what happened>|init_state=<state>|uptime_ms=<n|NONE>
//!   ABR|INIT|seq=..|from=<state>|to=FAILED|reason=<code>
//!   ABR|FAULTCTX|...  (the newest events, at most 8, the last being this fault)
//!   ABR|FAULT_END|events_dumped=<n>
//! then the CPU halts with interrupts off. uptime is NONE before the clock started, never a fake 0.
//! A fault while a fault is being reported prints one `ABR|FAULT|nested|...` line and halts.

use crate::eventlog::{self, OptMs};
use crate::events::Kind;
use crate::{clock, cpu, init, kprintln};
use core::arch::asm;
use core::fmt;
use core::sync::atomic::{AtomicBool, Ordering};

static REPORTING: AtomicBool = AtomicBool::new(false);
pub const CONTEXT_EVENTS: usize = 8;

pub fn stop(code: &'static str, arg: u64, what: fmt::Arguments) -> ! {
    // SAFETY: disabling interrupts on the way to a permanent halt.
    unsafe { asm!("cli", options(nomem, nostack)) };
    if REPORTING.swap(true, Ordering::AcqRel) {
        kprintln!("ABR|FAULT|nested|reason={}|arg={:#x}", code, arg);
        cpu::halt_forever();
    }
    kprintln!("ABR|FAULT|{}|init_state={}|uptime_ms={}", what, init::state_name(), OptMs(clock::peek_uptime_ms()));
    init::fail(code);
    eventlog::record(Kind::Fault, code, arg);
    let dumped = eventlog::dump_last(CONTEXT_EVENTS);
    kprintln!("ABR|FAULT_END|events_dumped={}", dumped);
    cpu::halt_forever();
}
