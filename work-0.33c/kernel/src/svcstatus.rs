//! Truthful public service status (ABRAHAM 0.32, D-ABR-019; design §5). Portable logic, no `unsafe`.
//!
//! - `PublicReason` has exactly the 27 codes of Appendix A of the ratified 0.2 baseline (P-15), in that order. It
//!   cannot be built from a string or from a kernel diagnostic code (no conversion exists; D-ABR-011).
//!   `tools/g032/check_public_reasons.py` compares this list with the baseline.
//! - Status, liveness and compromise are separate fields (P-41). Compromise is NONE_KNOWN in every status this module
//!   can build: there is no setter, and liveness loss never touches it.
//! - Freshness is half-open on boot-epoch milliseconds (P-39): fresh means observed_at <= now < observed_at + FRESH_MS.
//! - A degraded or unreadable clock makes every time-dependent status UNKNOWN / OBSERVATION_STALE (directive Step 6).
//! - Where Appendix A has no fitting code, the reason is None (printed NONE) and the cause stays on the diagnostic
//!   line (design Q3 option B, D-ABR-019).

use crate::svclife::SvcState;

/// Freshness limit for a RUNNING service's last completed step (design Q4).
pub const FRESH_MS: u64 = 1_000;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum PublicReason {
    AuthzUnavailable,
    CapMissing,
    CapExpired,
    PolicyDenied,
    SessionStaleEpoch,
    SessionUnknown,
    IdentityUnknown,
    RequestReplayed,
    ParseError,
    TargetUnknown,
    OperationUnknown,
    AuditUnavailable,
    AdapterNoResponse,
    AdapterCrashed,
    DeviceNotPresent,
    VerifyMismatch,
    LinkDown,
    UplinkDown,
    ObservationStale,
    NotInstalled,
    EntropyUnavailable,
    StorageError,
    SimulatedAuthority,
    AuditHistoryProtected,
    GrantRevalidationFailed,
    RecoveryCeiling,
    LivenessStale,
}

pub const ALL_REASONS: [PublicReason; 27] = [
    PublicReason::AuthzUnavailable, PublicReason::CapMissing, PublicReason::CapExpired, PublicReason::PolicyDenied,
    PublicReason::SessionStaleEpoch, PublicReason::SessionUnknown, PublicReason::IdentityUnknown,
    PublicReason::RequestReplayed, PublicReason::ParseError, PublicReason::TargetUnknown,
    PublicReason::OperationUnknown, PublicReason::AuditUnavailable, PublicReason::AdapterNoResponse,
    PublicReason::AdapterCrashed, PublicReason::DeviceNotPresent, PublicReason::VerifyMismatch, PublicReason::LinkDown,
    PublicReason::UplinkDown, PublicReason::ObservationStale, PublicReason::NotInstalled,
    PublicReason::EntropyUnavailable, PublicReason::StorageError, PublicReason::SimulatedAuthority,
    PublicReason::AuditHistoryProtected, PublicReason::GrantRevalidationFailed, PublicReason::RecoveryCeiling,
    PublicReason::LivenessStale,
];

impl PublicReason {
    pub const fn name(self) -> &'static str {
        match self {
            PublicReason::AuthzUnavailable => "AUTHZ_UNAVAILABLE",
            PublicReason::CapMissing => "CAP_MISSING",
            PublicReason::CapExpired => "CAP_EXPIRED",
            PublicReason::PolicyDenied => "POLICY_DENIED",
            PublicReason::SessionStaleEpoch => "SESSION_STALE_EPOCH",
            PublicReason::SessionUnknown => "SESSION_UNKNOWN",
            PublicReason::IdentityUnknown => "IDENTITY_UNKNOWN",
            PublicReason::RequestReplayed => "REQUEST_REPLAYED",
            PublicReason::ParseError => "PARSE_ERROR",
            PublicReason::TargetUnknown => "TARGET_UNKNOWN",
            PublicReason::OperationUnknown => "OPERATION_UNKNOWN",
            PublicReason::AuditUnavailable => "AUDIT_UNAVAILABLE",
            PublicReason::AdapterNoResponse => "ADAPTER_NO_RESPONSE",
            PublicReason::AdapterCrashed => "ADAPTER_CRASHED",
            PublicReason::DeviceNotPresent => "DEVICE_NOT_PRESENT",
            PublicReason::VerifyMismatch => "VERIFY_MISMATCH",
            PublicReason::LinkDown => "LINK_DOWN",
            PublicReason::UplinkDown => "UPLINK_DOWN",
            PublicReason::ObservationStale => "OBSERVATION_STALE",
            PublicReason::NotInstalled => "NOT_INSTALLED",
            PublicReason::EntropyUnavailable => "ENTROPY_UNAVAILABLE",
            PublicReason::StorageError => "STORAGE_ERROR",
            PublicReason::SimulatedAuthority => "SIMULATED_AUTHORITY",
            PublicReason::AuditHistoryProtected => "AUDIT_HISTORY_PROTECTED",
            PublicReason::GrantRevalidationFailed => "GRANT_REVALIDATION_FAILED",
            PublicReason::RecoveryCeiling => "RECOVERY_CEILING",
            PublicReason::LivenessStale => "LIVENESS_STALE",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Status {
    Available,
    Degraded,
    Unavailable,
    Unknown,
}

impl Status {
    pub const fn name(self) -> &'static str {
        match self {
            Status::Available => "AVAILABLE",
            Status::Degraded => "DEGRADED",
            Status::Unavailable => "UNAVAILABLE",
            Status::Unknown => "UNKNOWN",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Liveness {
    Live,
    Stale,
    Lost,
    Unknown,
}

impl Liveness {
    pub const fn name(self) -> &'static str {
        match self {
            Liveness::Live => "LIVE",
            Liveness::Stale => "STALE",
            Liveness::Lost => "LOST",
            Liveness::Unknown => "UNKNOWN",
        }
    }
}

/// P-41. In 0.32 nothing can set SUSPECTED or CONFIRMED: the variants exist only so the vocabulary is complete.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Compromise {
    NoneKnown,
    Suspected,
    Confirmed,
}

impl Compromise {
    pub const fn name(self) -> &'static str {
        match self {
            Compromise::NoneKnown => "NONE_KNOWN",
            Compromise::Suspected => "SUSPECTED",
            Compromise::Confirmed => "CONFIRMED",
        }
    }
}

/// What the clock guard says at the moment of the status (clock.rs): OK, latched DEGRADED, or UNREADABLE (the
/// guard was in use at that instant; treated like DEGRADED, fail-closed).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ClockTrust {
    Ok,
    Degraded,
    Unreadable,
}

impl ClockTrust {
    pub const fn name(self) -> &'static str {
        match self {
            ClockTrust::Ok => "OK",
            ClockTrust::Degraded => "DEGRADED",
            ClockTrust::Unreadable => "UNREADABLE",
        }
    }
}

/// Why a DECLARED entry was not started.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum DepBlock {
    /// Not withheld.
    None,
    /// Withheld, and the root cause is an entry that is not installed.
    NotInstalledRoot,
    /// Withheld for another reason (a dependency FAILED, STOPPED, ...).
    Other,
}

/// Everything the mapping looks at.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Inputs {
    pub registry_ok: bool,
    pub installed: bool,
    pub state: SvcState,
    pub withheld: DepBlock,
    /// Boot-epoch ms of the last completed, contract-consistent step.
    pub last_step_ms: Option<u64>,
    /// Boot-epoch ms now (guarded uptime), if readable.
    pub now_ms: Option<u64>,
    pub clock: ClockTrust,
    /// An overrun happened and the recovery window has not yet passed.
    pub overrun_window: bool,
}

/// One public status. Every field is a closed enum or an integer (P-35).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PublicStatus {
    pub status: Status,
    pub reason: Option<PublicReason>,
    pub liveness: Liveness,
    compromise: Compromise,
    pub observed_at_ms: Option<u64>,
    pub clock: ClockTrust,
    /// Which row of the design §5 table produced it (1..9).
    pub row: u8,
}

impl PublicStatus {
    pub const fn compromise(&self) -> Compromise {
        self.compromise
    }
}

const fn ps(row: u8, status: Status, reason: Option<PublicReason>, liveness: Liveness, at: Option<u64>, clock: ClockTrust) -> PublicStatus {
    PublicStatus { status, reason, liveness, compromise: Compromise::NoneKnown, observed_at_ms: at, clock, row }
}

/// Half-open freshness (P-39).
pub const fn fresh(last: Option<u64>, now: Option<u64>) -> bool {
    match (last, now) {
        (Some(t), Some(n)) => t <= n && n < t.saturating_add(FRESH_MS),
        _ => false,
    }
}

/// The design §5 mapping: the first matching row wins.
pub const fn map(i: &Inputs) -> PublicStatus {
    let (c, now) = (i.clock, i.now_ms);
    if !i.installed {
        return ps(1, Status::Unavailable, Some(PublicReason::NotInstalled), Liveness::Unknown, now, c);
    }
    if !i.registry_ok {
        return ps(2, Status::Unavailable, None, Liveness::Unknown, now, c);
    }
    match i.state {
        SvcState::Failed => ps(3, Status::Unavailable, None, Liveness::Lost, now, c),
        SvcState::Declared if !matches!(i.withheld, DepBlock::None) => {
            let reason = if matches!(i.withheld, DepBlock::NotInstalledRoot) { Some(PublicReason::NotInstalled) } else { None };
            ps(4, Status::Unavailable, reason, Liveness::Unknown, now, c)
        }
        SvcState::Declared | SvcState::Starting | SvcState::Stopping | SvcState::Stopped => {
            ps(5, Status::Unavailable, None, Liveness::Unknown, now, c)
        }
        SvcState::Running => {
            if !matches!(c, ClockTrust::Ok) {
                ps(6, Status::Unknown, Some(PublicReason::ObservationStale), Liveness::Unknown, i.last_step_ms, c)
            } else if !fresh(i.last_step_ms, now) {
                ps(7, Status::Unknown, Some(PublicReason::ObservationStale), Liveness::Stale, i.last_step_ms, c)
            } else if i.overrun_window {
                ps(8, Status::Degraded, None, Liveness::Live, i.last_step_ms, c)
            } else {
                ps(9, Status::Available, None, Liveness::Live, i.last_step_ms, c)
            }
        }
    }
}
