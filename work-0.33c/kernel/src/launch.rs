//! The launcher contract (ABRAHAM 0.33, D-ABR-022; design §4-§8). Portable, no `unsafe`, no allocation.
//!
//! A request is evaluated into separate facts:
//!   admission     the request id is greater than the last admitted id of this boot epoch. This is a bounded
//!                 ORDERING mechanism, not authenticated replay protection (Echo, final review, Recommendation 3):
//!                 0.33 has no actor, session or integrity binding on a request.
//!   structure     the text parses (launchreq.rs)
//!   operation     the operation word is in the table, and the pair is defined for applications
//!   recognition   the target is an application in the (valid) registry
//!   prerequisites every required service is AVAILABLE (D-ABR-022 Q3), read from the 0.32b public status
//!   support       what the descriptor says it can execute (always NONE in 0.33)
//!   authorization no mechanism exists in 0.33: CAP_MISSING, or NO_AUTHORITY when a capability is presented.
//!                 There is no AUTHORIZED value.
//!   execution     NOT_EXECUTED is the only value. There is no executed value.
//! `decide` chooses the public outcome from the facts with one fixed precedence (option A, D-ABR-022 Q2):
//! admission, structure, operation, recognition, authorization. Every public reason is an Appendix A code.
//!
//! The launcher reads services through `StatusView` (a shared borrow of the 0.32b ServiceSet): it cannot start,
//! step or stop anything. `LaunchResult` has private fields; only this module builds one. Every request reaches a
//! terminal state inside `submit`: there is no queue and no retry (P-27). INSPECT_PUBLIC on applications is a closed
//! allow list (P-33, D-ABR-022 Q5): `status app.<name>` and `list app`. `svc.`/`dev.` targets are routed unchanged to
//! the 0.32b `inspect_public`.

use crate::appregistry::{validate, AppDesc, AppError, AppOrder, ExecSupport, MAX_REQUIRES};
use crate::launchlife::{Life, Refused, RequestState, Transition};
use crate::launchreq::{parse, Namespace, Op, OpClass, Parse, ParseFault};
use crate::svcregistry::{index_of, Desc};
use crate::svcrun::ServiceSet;
use crate::svcstatus::{ClockTrust, PublicReason, PublicStatus, Status};

/// Read-only access to the services' public status.
pub trait StatusView {
    fn services(&self) -> &'static [Desc];
    fn status_of(&self, idx: usize) -> PublicStatus;
}

/// The kernel's view: the live ServiceSet, borrowed shared, at one evaluation time.
pub struct LiveView<'a> {
    pub set: &'a ServiceSet,
    pub clock: ClockTrust,
    pub now_ms: Option<u64>,
}

impl StatusView for LiveView<'_> {
    fn services(&self) -> &'static [Desc] {
        self.set.table()
    }
    fn status_of(&self, idx: usize) -> PublicStatus {
        self.set.status(idx, self.clock, self.now_ms)
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Admission {
    Fresh,
    NotIncreasing,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Structure {
    WellFormed,
    Malformed(ParseFault),
    NotEvaluated,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Operation {
    Defined,
    Unknown,
    NotEvaluated,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Recognition {
    Known(usize),
    /// exactly `app`, for `list app`
    Collection,
    Unknown,
    RegistryRefused,
    NotEvaluated,
}

/// One required service that is not AVAILABLE, with its own public status and reason.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Missing {
    pub service: usize,
    pub status: Status,
    pub reason: Option<PublicReason>,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Prereq {
    Satisfied,
    Unsatisfied { missing: [Option<Missing>; MAX_REQUIRES], n: u8 },
    NotEvaluated,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Support {
    /// The descriptor says `exec=NONE`.
    None,
    NotEvaluated,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Authz {
    CapMissing,
    NoAuthority,
    NotEvaluated,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Execution {
    NotExecuted,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Facts {
    pub admission: Admission,
    pub structure: Structure,
    pub operation: Operation,
    pub class: Option<OpClass>,
    pub recognition: Recognition,
    pub prerequisites: Prereq,
    pub support: Support,
    pub capability_presented: bool,
    pub authorization: Authz,
    pub execution: Execution,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Stage {
    Admission,
    Structure,
    Operation,
    Recognition,
    Authorization,
}

impl Stage {
    pub const fn name(self) -> &'static str {
        match self {
            Stage::Admission => "ADMISSION",
            Stage::Structure => "STRUCTURE",
            Stage::Operation => "OPERATION",
            Stage::Recognition => "RECOGNITION",
            Stage::Authorization => "AUTHORIZATION",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Decision {
    /// Refused before validation: state REFUSED.
    Refuse { stage: Stage, reason: PublicReason, diag: &'static str },
    /// Validated, then stopped: state NOT_EXECUTED.
    NotExecuted { stage: Stage, reason: PublicReason, diag: &'static str },
    /// An allowed INSPECT_PUBLIC read of the registry: no request lifecycle.
    Discovery,
}

/// The fixed precedence (option A). Total over all fact combinations; every reason is an Appendix A code; no
/// combination yields execution.
pub const fn decide(f: &Facts) -> Decision {
    if matches!(f.admission, Admission::NotIncreasing) {
        return Decision::Refuse { stage: Stage::Admission, reason: PublicReason::RequestReplayed, diag: "LAUNCH_ID_NOT_INCREASING" };
    }
    match f.structure {
        Structure::Malformed(p) => return Decision::Refuse { stage: Stage::Structure, reason: PublicReason::ParseError, diag: p.code() },
        Structure::NotEvaluated => return Decision::Refuse { stage: Stage::Structure, reason: PublicReason::ParseError, diag: "LAUNCH_PARSE_NOT_EVALUATED" },
        Structure::WellFormed => {}
    }
    if !matches!(f.operation, Operation::Defined) {
        return Decision::Refuse { stage: Stage::Operation, reason: PublicReason::OperationUnknown, diag: "LAUNCH_OPERATION_UNKNOWN" };
    }
    match f.recognition {
        Recognition::Known(_) | Recognition::Collection => {}
        Recognition::RegistryRefused => return Decision::Refuse { stage: Stage::Recognition, reason: PublicReason::TargetUnknown, diag: "LAUNCH_REGISTRY_REFUSED" },
        _ => return Decision::Refuse { stage: Stage::Recognition, reason: PublicReason::TargetUnknown, diag: "LAUNCH_TARGET_UNKNOWN" },
    }
    if matches!(f.class, Some(OpClass::InspectPublic)) {
        return Decision::Discovery;
    }
    match f.authorization {
        Authz::CapMissing => Decision::NotExecuted { stage: Stage::Authorization, reason: PublicReason::CapMissing, diag: "LAUNCH_CAP_MISSING" },
        // NoAuthority, and (fail closed) a validated request whose authorization was never evaluated
        _ => Decision::NotExecuted { stage: Stage::Authorization, reason: PublicReason::AuthzUnavailable, diag: "LAUNCH_NO_AUTHORITY" },
    }
}

/// The target as it may be printed: a name that matched its grammar, or only the length of a malformed one.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Echo<'a> {
    Name(&'a str),
    Malformed(usize),
    None,
}

/// The outcome of one launch request (REFUSED or NOT_EXECUTED). Private fields: built only by `submit`.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct LaunchResult<'a> {
    request_id: u32,
    op: Option<Op>,
    target: Echo<'a>,
    facts: Facts,
    life: Life,
    transitions: [Option<Transition>; 2],
    stage: Stage,
    reason: PublicReason,
    diag: &'static str,
}

impl<'a> LaunchResult<'a> {
    pub fn request_id(&self) -> u32 { self.request_id }
    pub fn op(&self) -> Option<Op> { self.op }
    pub fn target(&self) -> Echo<'a> { self.target }
    pub fn facts(&self) -> Facts { self.facts }
    pub fn state(&self) -> RequestState { self.life.state() }
    pub fn transitions(&self) -> [Option<Transition>; 2] { self.transitions }
    pub fn stage(&self) -> Stage { self.stage }
    pub fn reason(&self) -> PublicReason { self.reason }
    pub fn diag(&self) -> &'static str { self.diag }
    /// P-22 vocabulary: always NOT_EXECUTED in 0.33.
    pub fn result_name(&self) -> &'static str { "NOT_EXECUTED" }
    pub fn executed(&self) -> bool { false }
    /// An external transition request (e.g. the DIAGNOSTIC injection). Transitions are made only by the launcher,
    /// so every request is refused and the state is unchanged.
    pub fn request_transition(&self, to: RequestState) -> Refused {
        match self.life.check(to) {
            Err(r) => r,
            Ok(()) => Refused { from: self.life.state(), to, code: "LAUNCH_TRANSITION_LAUNCHER_ONLY" },
        }
    }
}

/// Discovery: what the registry and the live service status say about one application.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct AppInfo {
    pub app: usize,
    pub exec: ExecSupport,
    pub prerequisites: Prereq,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Answer {
    Info(AppInfo),
    List,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Outcome<'a> {
    Launch(LaunchResult<'a>),
    Discovery { request_id: u32, answer: Answer },
    /// A `svc.`/`dev.` target: the caller answers it with the unchanged 0.32b `ServiceSet::inspect_public`.
    Routed { request_id: u32, op: Op, target: &'a str },
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AppRegistry {
    Ok(AppOrder),
    Refused(AppError),
}

#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Counters {
    pub requests: u32,
    pub refused: u32,
    pub not_executed: u32,
    pub discovery: u32,
    pub routed: u32,
}

pub struct Launcher {
    apps: &'static [AppDesc],
    registry: AppRegistry,
    last_admitted: Option<u32>,
    counters: Counters,
}

impl Launcher {
    /// Validates the application table against the service table it will read (the boot-time check).
    pub fn new(apps: &'static [AppDesc], services: &[Desc]) -> Self {
        let registry = match validate(apps, services) {
            Ok(o) => AppRegistry::Ok(o),
            Err(e) => AppRegistry::Refused(e),
        };
        Launcher { apps, registry, last_admitted: None, counters: Counters::default() }
    }

    pub fn apps(&self) -> &'static [AppDesc] { self.apps }
    pub fn registry(&self) -> AppRegistry { self.registry }
    pub fn counters(&self) -> Counters { self.counters }
    pub fn last_admitted(&self) -> Option<u32> { self.last_admitted }

    /// The prerequisite fact of one application, from the services' public status (AVAILABLE only satisfies).
    pub fn prerequisites(&self, app: usize, view: &impl StatusView) -> Prereq {
        let mut missing = [None; MAX_REQUIRES];
        let mut n = 0u8;
        for id in self.apps[app].requires {
            let ok = match index_of(view.services(), *id) {
                Some(s) => {
                    let st = view.status_of(s);
                    if st.status == Status::Available {
                        true
                    } else {
                        if (n as usize) < MAX_REQUIRES {
                            missing[n as usize] = Some(Missing { service: s, status: st.status, reason: st.reason });
                        }
                        false
                    }
                }
                None => false, // unreachable for a validated table; fail closed
            };
            if !ok {
                n = n.saturating_add(1);
            }
        }
        if n == 0 { Prereq::Satisfied } else { Prereq::Unsatisfied { missing, n } }
    }

    /// Discovery answer for one registered application (APPINFO).
    pub fn info(&self, app: usize, view: &impl StatusView) -> AppInfo {
        AppInfo { app, exec: self.apps[app].exec, prerequisites: self.prerequisites(app, view) }
    }

    fn admit(&mut self, id: u32) -> Admission {
        match self.last_admitted {
            Some(last) if id <= last => Admission::NotIncreasing,
            _ => {
                self.last_admitted = Some(id);
                Admission::Fresh
            }
        }
    }

    /// Submit one request. Returns within the call, in a terminal state (or as discovery / routed).
    pub fn submit<'a>(&mut self, request_id: u32, text: &'a [u8], view: &impl StatusView) -> Outcome<'a> {
        self.counters.requests = self.counters.requests.saturating_add(1);
        let mut f = Facts {
            admission: self.admit(request_id),
            structure: Structure::NotEvaluated,
            operation: Operation::NotEvaluated,
            class: None,
            recognition: Recognition::NotEvaluated,
            prerequisites: Prereq::NotEvaluated,
            support: Support::NotEvaluated,
            capability_presented: false,
            authorization: Authz::NotEvaluated,
            execution: Execution::NotExecuted,
        };
        let mut op = None;
        let mut echo = Echo::None;
        if f.admission == Admission::Fresh {
            match parse(text) {
                Parse::Malformed { fault, target_len } => {
                    f.structure = Structure::Malformed(fault);
                    if let Some(n) = target_len {
                        echo = Echo::Malformed(n);
                    }
                }
                Parse::UnknownOperation => {
                    f.structure = Structure::WellFormed;
                    f.operation = Operation::Unknown;
                }
                Parse::Ok(p) => {
                    f.structure = Structure::WellFormed;
                    f.class = Some(p.class);
                    f.capability_presented = p.capability_presented;
                    op = Some(p.op);
                    echo = Echo::Name(p.target);
                    if p.ns == Namespace::Service {
                        self.counters.routed = self.counters.routed.saturating_add(1);
                        return Outcome::Routed { request_id, op: p.op, target: p.target };
                    }
                    // the closed allow list for applications: INSPECT_PUBLIC only as `status app.<name>` / `list app`
                    f.operation = match (p.class, p.op, p.ns) {
                        (OpClass::InspectPublic, Op::Status, Namespace::App) => Operation::Defined,
                        (OpClass::InspectPublic, Op::List, Namespace::Collection) => Operation::Defined,
                        (OpClass::InspectPublic, _, _) => Operation::Unknown,
                        _ => Operation::Defined,
                    };
                    if f.operation == Operation::Defined {
                        f.recognition = match (self.registry, p.ns) {
                            (AppRegistry::Refused(_), _) => Recognition::RegistryRefused,
                            (AppRegistry::Ok(_), Namespace::Collection) if p.op == Op::List => Recognition::Collection,
                            (AppRegistry::Ok(_), Namespace::Collection) => Recognition::Unknown,
                            (AppRegistry::Ok(_), _) => match crate::appregistry::lookup(self.apps, p.target) {
                                Some(i) => Recognition::Known(i),
                                None => Recognition::Unknown,
                            },
                        };
                    }
                    if let Recognition::Known(i) = f.recognition {
                        // read-only public facts, evaluated for every known application
                        f.prerequisites = self.prerequisites(i, view);
                        f.support = match self.apps[i].exec {
                            ExecSupport::None => Support::None,
                            // refused by validate, so never reached; never claims support
                            ExecSupport::Native => Support::NotEvaluated,
                        };
                    }
                    if matches!(f.recognition, Recognition::Known(_) | Recognition::Collection) {
                        if p.class != OpClass::InspectPublic {
                            f.authorization = if p.capability_presented { Authz::NoAuthority } else { Authz::CapMissing };
                        }
                    }
                }
            }
        }
        match decide(&f) {
            Decision::Discovery => {
                self.counters.discovery = self.counters.discovery.saturating_add(1);
                let answer = match f.recognition {
                    Recognition::Known(i) => Answer::Info(self.info(i, view)),
                    _ => Answer::List,
                };
                Outcome::Discovery { request_id, answer }
            }
            Decision::Refuse { stage, reason, diag } => {
                let mut life = Life::new();
                let t1 = life.advance(RequestState::Refused).ok();
                self.counters.refused = self.counters.refused.saturating_add(1);
                Outcome::Launch(LaunchResult { request_id, op, target: echo, facts: f, life, transitions: [t1, None],
                                               stage, reason, diag })
            }
            Decision::NotExecuted { stage, reason, diag } => {
                let mut life = Life::new();
                let t1 = life.advance(RequestState::Validated).ok();
                let t2 = life.advance(RequestState::NotExecuted).ok();
                self.counters.not_executed = self.counters.not_executed.saturating_add(1);
                Outcome::Launch(LaunchResult { request_id, op, target: echo, facts: f, life, transitions: [t1, t2],
                                               stage, reason, diag })
            }
        }
    }
}
