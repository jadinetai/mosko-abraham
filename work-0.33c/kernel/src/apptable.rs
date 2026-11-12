//! The compiled application tables (ABRAHAM 0.33, D-ABR-022 Q1). Portable data, no `unsafe`.
//!
//! PRODUCTION is the only table of an accepted kernel. Every entry is `exec=NONE`: no executor exists in 0.33.
//!   app.counterview  VIEWER   requires svc.counter: its prerequisites can be satisfied, yet it cannot execute.
//!   app.netstatus    VIEWER   requires svc.netmon (UNAVAILABLE / NOT_INSTALLED through dev.net0).
//!   app.browser      BROWSER  requires svc.netmon. PROVISIONAL (Echo, final review, Recommendation 3): the future
//!                             offline browser must not need network monitoring merely to render local content.
//! The DIAG_* tables are used only by DIAGNOSTIC builds (Cargo features), never by an accepted kernel. They are
//! deliberately invalid and are NOT checked at compile time, so the boot-time check can be shown to refuse them
//! (as 0.32's DIAG_CYCLE).

use crate::appregistry::{assert_valid, AppDesc, AppId, AppKind, ExecSupport};
use crate::svctable::{SVC_COUNTER, SVC_NETMON};
use crate::svcregistry::ServiceId;

pub const APP_COUNTERVIEW: AppId = AppId(1);
pub const APP_NETSTATUS: AppId = AppId(2);
pub const APP_BROWSER: AppId = AppId(3);

const COUNTERVIEW: AppDesc = AppDesc { id: APP_COUNTERVIEW, name: "app.counterview", kind: AppKind::Viewer, revision: 1,
                                       requires: &[SVC_COUNTER], exec: ExecSupport::None };
const NETSTATUS: AppDesc = AppDesc { id: APP_NETSTATUS, name: "app.netstatus", kind: AppKind::Viewer, revision: 1,
                                     requires: &[SVC_NETMON], exec: ExecSupport::None };
const BROWSER: AppDesc = AppDesc { id: APP_BROWSER, name: "app.browser", kind: AppKind::Browser, revision: 1,
                                   requires: &[SVC_NETMON], exec: ExecSupport::None };

pub const PRODUCTION: &[AppDesc] = &[COUNTERVIEW, NETSTATUS, BROWSER];

/// A second entry with application id 1.
pub const DIAG_DUP: &[AppDesc] = &[
    COUNTERVIEW,
    NETSTATUS,
    AppDesc { id: APP_COUNTERVIEW, name: "app.counterdup", kind: AppKind::Tool, revision: 1, requires: &[], exec: ExecSupport::None },
];
/// A NATIVE claim with no executor: an application falsely advertised as executable.
pub const DIAG_FALSE_EXEC: &[AppDesc] = &[
    COUNTERVIEW,
    AppDesc { id: AppId(4), name: "app.liar", kind: AppKind::Tool, revision: 1, requires: &[SVC_COUNTER], exec: ExecSupport::Native },
];
/// A requirement on a service id that is not in the service table.
pub const DIAG_UNKNOWN_REQ: &[AppDesc] = &[
    COUNTERVIEW,
    AppDesc { id: AppId(5), name: "app.orphan", kind: AppKind::Tool, revision: 1, requires: &[ServiceId(99)], exec: ExecSupport::None },
];

const _: () = assert_valid(PRODUCTION, crate::svctable::PRODUCTION);

#[cfg(feature = "diag-app-registry-dup")]
pub const TABLE: &[AppDesc] = DIAG_DUP;
#[cfg(feature = "diag-app-false-exec")]
pub const TABLE: &[AppDesc] = DIAG_FALSE_EXEC;
#[cfg(feature = "diag-app-unknown-req")]
pub const TABLE: &[AppDesc] = DIAG_UNKNOWN_REQ;
#[cfg(not(any(feature = "diag-app-registry-dup", feature = "diag-app-false-exec", feature = "diag-app-unknown-req")))]
pub const TABLE: &[AppDesc] = PRODUCTION;

/// The fixed DIAGNOSTIC launchpad script (design §9; run once by `diag-launchpad` builds, never by an accepted
/// kernel). Each row is (request id, request text). Expected outcomes are in the design and in the hosted tests.
pub const DIAG_SCRIPT: &[(u32, &[u8])] = &[
    (1, b"start app.counterview"),
    (2, b"start app.netstatus"),
    (3, b"start app.browser"),
    (4, b"start app.counterview as cap.launch"),
    (5, b"stop app.counterview"),
    (6, b"inspect app.counterview"),
    (7, b"status app.counterview"),
    (8, b"start app.nosuch"),
    (9, b"start app.counterviews"),
    (10, b"start app.CounterView"),
    (11, b"start app.*"),
    (12, b"launch app.counterview"),
    (13, b"start app.counterview now=1"),
    (14, b"start  app.counterview"),
    // 65 bytes: one over MAX_REQUEST_BYTES
    (15, b"start app.counterviewaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    (1, b"start app.counterview"),
    (16, b"start svc.counter"),
];
