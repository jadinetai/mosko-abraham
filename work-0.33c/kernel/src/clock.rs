//! TSC clocksource (0.1.1, D-ABR-006), guarded since 0.31b (clockguard.rs, Echo F-029-04).
//! Uptime is measured, not counted: a timer interrupt the platform fails to deliver does not turn
//! into lost time. Since 0.31b it also cannot jump backwards or wrap: every reading goes through
//! the guard, which reports anomalies and latches DEGRADED (no false monotonic-time claim).

use crate::clockguard::{ClockGuard, Observation};
use crate::kcell::KCell;
use core::arch::asm;
use core::arch::x86_64::__cpuid;
#[cfg(any(feature = "diag-tsc-backward", feature = "diag-tsc-jump"))]
use core::sync::atomic::{AtomicU64, Ordering};

static GUARD: KCell<ClockGuard> = KCell::new(ClockGuard::new());

/// Raw TSC (also used by the APIC calibration, which must never see an injected offset).
pub fn read_tsc() -> u64 {
    let (low, high): (u32, u32);
    // SAFETY: RDTSC has no side effects; CR4.TSD is clear (Limine clears unlisted CR4 bits).
    unsafe { asm!("rdtsc", out("eax") low, out("edx") high, options(nomem, nostack, preserves_flags)) };
    ((high as u64) << 32) | low as u64
}

// DIAGNOSTIC builds only: an offset applied to the readings the guard sees, to inject a backward
// step or a forward jump into the running kernel.
#[cfg(any(feature = "diag-tsc-backward", feature = "diag-tsc-jump"))]
static INJECT_ADD: AtomicU64 = AtomicU64::new(0);
#[cfg(any(feature = "diag-tsc-backward", feature = "diag-tsc-jump"))]
static INJECT_SUB: AtomicU64 = AtomicU64::new(0);

fn reading() -> u64 {
    let raw = read_tsc();
    #[cfg(any(feature = "diag-tsc-backward", feature = "diag-tsc-jump"))]
    let raw = raw.wrapping_add(INJECT_ADD.load(Ordering::Relaxed)).wrapping_sub(INJECT_SUB.load(Ordering::Relaxed));
    raw
}

/// DIAGNOSTIC: from now on the guard sees the TSC 2 s behind (backward) or 1 h ahead (jump).
/// Returns the injected offset in counts.
#[cfg(any(feature = "diag-tsc-backward", feature = "diag-tsc-jump"))]
pub fn diag_arm(tsc_hz: u64) -> u64 {
    #[cfg(feature = "diag-tsc-backward")]
    {
        INJECT_SUB.store(tsc_hz * 2, Ordering::Relaxed);
        tsc_hz * 2
    }
    #[cfg(all(feature = "diag-tsc-jump", not(feature = "diag-tsc-backward")))]
    {
        INJECT_ADD.store(tsc_hz * 3600, Ordering::Relaxed);
        tsc_hz * 3600
    }
}

/// CPUID.80000007H:EDX bit 8. Reported, not required: virtual CPUs often hide the flag.
pub fn tsc_invariant() -> bool {
    #[allow(unused_unsafe)]
    let max_extended = unsafe { __cpuid(0x8000_0000) }.eax;
    if max_extended < 0x8000_0007 {
        return false;
    }
    #[allow(unused_unsafe)]
    let leaf = unsafe { __cpuid(0x8000_0007) };
    leaf.edx & (1 << 8) != 0
}

/// Called once, at the moment the periodic timer starts: uptime 0 = timer start.
pub fn start(tsc_hz: u64) -> bool {
    GUARD.with(|g| g.start(tsc_hz, reading())).unwrap_or(false)
}

/// One guarded reading (kmain only). None before start or if re-entered.
pub fn observe() -> Option<Observation> {
    GUARD.with(|g| g.observe(reading())).flatten()
}

/// Uptime without changing the guard (events, fault reports). None before start, or if the guard
/// is in use at that instant (a fault inside a reading): reported as NONE, never invented.
pub fn peek_uptime_ms() -> Option<u64> {
    GUARD.with(|g| g.peek(reading())).flatten()
}

/// 0.32: whether the guard has latched DEGRADED (read only). None if the guard is in use at this instant; the
/// service status treats that as UNREADABLE, like DEGRADED (fail-closed).
pub fn degraded() -> Option<bool> {
    GUARD.with(|g| g.degraded())
}
