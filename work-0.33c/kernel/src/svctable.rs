//! The compiled service tables (ABRAHAM 0.32, D-ABR-019 Q1). Portable data, no `unsafe`.
//!
//! PRODUCTION is the only table of an accepted kernel:
//!   dev.net0     ADAPTER, NOT installed: no network driver exists in 0.32 (P-19 virtio-net is a later revision).
//!   svc.counter  SERVICE, no dependency, 1 work unit per step.
//!   svc.netmon   SERVICE, depends on dev.net0, so it is never started and reports UNAVAILABLE / NOT_INSTALLED.
//!                It never claims network monitoring.
//! The DIAG_* tables are used only by DIAGNOSTIC builds (Cargo features), never by an accepted kernel. Every table
//! except DIAG_CYCLE must pass `validate` at compile time; DIAG_CYCLE is deliberately cyclic, so that the boot-time
//! check can be shown to refuse it.

use crate::svcregistry::{assert_valid, Desc, Kind, ServiceId};

pub const DEV_NET0: ServiceId = ServiceId(1);
pub const SVC_COUNTER: ServiceId = ServiceId(2);
pub const SVC_NETMON: ServiceId = ServiceId(3);
// DIAGNOSTIC entries only.
pub const SVC_DIAGCYC: ServiceId = ServiceId(4);
pub const SVC_DIAGREADY: ServiceId = ServiceId(5);
pub const SVC_DIAGLIAR: ServiceId = ServiceId(6);
pub const SVC_DIAGDEP: ServiceId = ServiceId(7);
pub const SVC_DIAGSLOW: ServiceId = ServiceId(8);
pub const SVC_DIAGSTALL: ServiceId = ServiceId(9);
// 0.32b DIAGNOSTIC entries only (finding 1: a dependency that fails while its dependent is RUNNING).
pub const SVC_DIAGFLAKY: ServiceId = ServiceId(10);
pub const SVC_DIAGDEP2: ServiceId = ServiceId(11);

const NET0: Desc = Desc { id: DEV_NET0, name: "dev.net0", kind: Kind::Adapter, installed: false, deps: &[], budget: 0 };
const COUNTER: Desc = Desc { id: SVC_COUNTER, name: "svc.counter", kind: Kind::Service, installed: true, deps: &[], budget: 1 };
const NETMON: Desc = Desc { id: SVC_NETMON, name: "svc.netmon", kind: Kind::Service, installed: true, deps: &[DEV_NET0], budget: 1 };

pub const PRODUCTION: &[Desc] = &[NET0, COUNTER, NETMON];

const fn svc(id: ServiceId, name: &'static str, deps: &'static [ServiceId]) -> Desc {
    Desc { id, name, kind: Kind::Service, installed: true, deps, budget: 1 }
}

/// svc.netmon additionally depends on svc.diagcyc, which depends on svc.netmon: a cycle.
pub const DIAG_CYCLE: &[Desc] = &[
    NET0,
    COUNTER,
    svc(SVC_NETMON, "svc.netmon", &[DEV_NET0, SVC_DIAGCYC]),
    svc(SVC_DIAGCYC, "svc.diagcyc", &[SVC_NETMON]),
];
/// Honest readiness failure, a false readiness claim, and a dependent of the failing one.
pub const DIAG_DEFECTS: &[Desc] = &[
    NET0, COUNTER, NETMON,
    svc(SVC_DIAGREADY, "svc.diagready", &[]),
    svc(SVC_DIAGLIAR, "svc.diagliar", &[]),
    svc(SVC_DIAGDEP, "svc.diagdep", &[SVC_DIAGREADY]),
];
/// A bounded 20 ms step (overrun).
pub const DIAG_SLOW: &[Desc] = &[NET0, COUNTER, NETMON, svc(SVC_DIAGSLOW, "svc.diagslow", &[])];
/// A 6 s step (stall), to show the clock-guard interaction.
pub const DIAG_STALL: &[Desc] = &[NET0, COUNTER, NETMON, svc(SVC_DIAGSTALL, "svc.diagstall", &[])];
/// 0.32b: svc.diagflaky fails on its 3rd loop step; svc.diagdep2 depends on it and comes after it in the order.
pub const DIAG_CASCADE: &[Desc] = &[
    NET0, COUNTER, NETMON,
    svc(SVC_DIAGFLAKY, "svc.diagflaky", &[]),
    svc(SVC_DIAGDEP2, "svc.diagdep2", &[SVC_DIAGFLAKY]),
];

const _: () = assert_valid(PRODUCTION);
const _: () = assert_valid(DIAG_DEFECTS);
const _: () = assert_valid(DIAG_SLOW);
const _: () = assert_valid(DIAG_STALL);
const _: () = assert_valid(DIAG_CASCADE);

#[cfg(feature = "diag-svc-cycle")]
pub const TABLE: &[Desc] = DIAG_CYCLE;
#[cfg(feature = "diag-svc-defects")]
pub const TABLE: &[Desc] = DIAG_DEFECTS;
#[cfg(feature = "diag-svc-slow")]
pub const TABLE: &[Desc] = DIAG_SLOW;
#[cfg(feature = "diag-svc-stall")]
pub const TABLE: &[Desc] = DIAG_STALL;
#[cfg(feature = "diag-svc-cascade")]
pub const TABLE: &[Desc] = DIAG_CASCADE;
#[cfg(not(any(feature = "diag-svc-cycle", feature = "diag-svc-defects", feature = "diag-svc-slow",
              feature = "diag-svc-stall", feature = "diag-svc-cascade")))]
pub const TABLE: &[Desc] = PRODUCTION;
