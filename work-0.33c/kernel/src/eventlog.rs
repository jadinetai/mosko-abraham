//! Kernel diagnostic event log instance (0.31b; requirement ABR-031-EVT-01, D-ABR-015/016).
//! One static, fixed-capacity log (events.rs) in kernel .data/.bss: no allocation, no dispatch.
//! Printed once at OPERATIONAL (`ABR|EVENTS` + `ABR|EVENT` lines) and its newest records are dumped
//! with every fault (`ABR|FAULTCTX`). A record attempted while the log is in use (a fault inside a
//! record) is not written and is counted as lost_reentrant: never silent, never corrupting.

use crate::clock;
use crate::events::{Event, EventLog, Kind, CAPACITY};
use crate::kcell::KCell;
use crate::kprintln;
use core::fmt;
use core::sync::atomic::{AtomicU64, Ordering};

static LOG: KCell<EventLog> = KCell::new(EventLog::new());
static LOST_REENTRANT: AtomicU64 = AtomicU64::new(0);

/// `NONE` or the number: uptime is never invented.
pub struct OptMs(pub Option<u64>);

impl fmt::Display for OptMs {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.0 {
            Some(v) => write!(f, "{}", v),
            None => f.write_str("NONE"),
        }
    }
}

pub fn record(kind: Kind, code: &'static str, arg: u64) {
    let uptime = clock::peek_uptime_ms();
    if LOG.with(|l| l.record(kind, code, arg, uptime)).is_none() {
        LOST_REENTRANT.fetch_add(1, Ordering::Relaxed);
    }
}

fn print(tag: &str, e: &Event) {
    kprintln!("{}|seq={}|uptime_ms={}|kind={}|code={}|arg={:#x}", tag, e.seq, OptMs(e.uptime_ms), e.kind.name(), e.code, e.arg);
}

/// At OPERATIONAL: the summary and every retained record, oldest first.
pub fn print_all() {
    let _ = LOG.with(|l| {
        kprintln!("ABR|EVENTS|recorded={}|dropped={}|capacity={}|lost_reentrant={}",
                  l.recorded(), l.dropped(), CAPACITY, LOST_REENTRANT.load(Ordering::Relaxed));
        for i in 0..l.retained() {
            if let Some(e) = l.get(i) {
                print("ABR|EVENT", &e);
            }
        }
    });
}

/// Fault path: the newest `n` records as ABR|FAULTCTX lines; returns how many were printed.
pub fn dump_last(n: usize) -> usize {
    LOG.with(|l| {
        let mut k = 0;
        for e in l.last(n) {
            print("ABR|FAULTCTX", &e);
            k += 1;
        }
        k
    })
    .unwrap_or(0)
}

/// 0.32: how many records were ever appended (the seq of the newest). 0 if the log is in use at this instant.
pub fn recorded() -> u64 {
    LOG.with(|l| l.recorded()).unwrap_or(0)
}

/// 0.32: once, after the service start phase, the records appended since the OPERATIONAL printout (seq >= from_seq),
/// with distinct tags so that the 0.31b counts of ABR|EVENTS / ABR|EVENT are not disturbed. Read only.
pub fn print_since(from_seq: u64) {
    let _ = LOG.with(|l| {
        kprintln!("ABR|SVCEVENTS|from_seq={}|recorded={}|dropped={}|capacity={}|lost_reentrant={}",
                  from_seq, l.recorded(), l.dropped(), CAPACITY, LOST_REENTRANT.load(Ordering::Relaxed));
        for i in 0..l.retained() {
            if let Some(e) = l.get(i) {
                if e.seq as u64 >= from_seq {
                    print("ABR|SVCEVENT", &e);
                }
            }
        }
    });
}
