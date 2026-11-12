//! Closed application registry (ABRAHAM 0.33, D-ABR-022; design §4.1). Portable logic, no `unsafe`, no allocation.
//!
//! - A table is a compiled `&'static [AppDesc]` (apptable.rs). There is no registration function: adding an entry
//!   is a reviewed code change. There is no filesystem, manifest file or package manager.
//! - A descriptor carries an exact name, a fixed kind, a revision number, the services it requires and a truthful
//!   execution statement. It carries NO title or free text (P-35; presentation belongs to the shells) and NO
//!   capability, grant or authority field: recognizing an application grants nothing.
//! - `validate(apps, services)` is a `const fn`: apptable.rs runs it at compile time against the production service
//!   table, and the kernel runs it again at boot against the table it actually uses. It refuses the whole table, in
//!   this order: more than MAX_APPS entries; a malformed name; more than MAX_REQUIRES requirements; a duplicate id;
//!   a duplicate name; a requirement that is not in the service table; a duplicate requirement; an `exec=NATIVE`
//!   claim while no executor exists (EXECUTOR is ABSENT in 0.33), so no application can be advertised as executable.
//! - The listing order is the `AppId` number, never table position. `lookup` compares exact bytes.

use crate::svcregistry::{index_of, Desc, ServiceId};

pub const MAX_APPS: usize = 8;
pub const MAX_REQUIRES: usize = 4;
pub const MAX_APP_NAME: usize = 31;

/// An application identifier. Its own type: never a `ServiceId`.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub struct AppId(pub u8);

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AppKind {
    Viewer,
    Browser,
    Tool,
}

impl AppKind {
    pub const fn name(self) -> &'static str {
        match self {
            AppKind::Viewer => "VIEWER",
            AppKind::Browser => "BROWSER",
            AppKind::Tool => "TOOL",
        }
    }
}

/// What a descriptor says it can do. `Native` (an independent ring-3 image) is reserved for 0.4 and is refused by
/// `validate` while no executor exists.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ExecSupport {
    None,
    Native,
}

impl ExecSupport {
    pub const fn name(self) -> &'static str {
        match self {
            ExecSupport::None => "NONE",
            ExecSupport::Native => "NATIVE",
        }
    }
}

/// Whether this kernel can start an independent executable. 0.33 has no process loader, so the only value is ABSENT.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Executor {
    Absent,
}

impl Executor {
    pub const fn name(self) -> &'static str {
        match self {
            Executor::Absent => "ABSENT",
        }
    }
}

pub const EXECUTOR: Executor = Executor::Absent;

#[derive(Clone, Copy, Debug)]
pub struct AppDesc {
    pub id: AppId,
    pub name: &'static str,
    pub kind: AppKind,
    /// Descriptor revision, raised by a reviewed change.
    pub revision: u16,
    /// Services this application needs; each must exist in the service table.
    pub requires: &'static [ServiceId],
    pub exec: ExecSupport,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AppFault {
    TooMany,
    NameMalformed,
    TooManyRequirements,
    DuplicateId,
    DuplicateName,
    UnknownRequirement,
    DuplicateRequirement,
    ExecClaimUnsupported,
}

/// A refused table: what is wrong and at which entry (table position).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct AppError {
    pub fault: AppFault,
    pub entry: usize,
}

impl AppError {
    pub const fn code(self) -> &'static str {
        match self.fault {
            AppFault::TooMany => "APP_TOO_MANY_ENTRIES",
            AppFault::NameMalformed => "APP_NAME_MALFORMED",
            AppFault::TooManyRequirements => "APP_TOO_MANY_REQUIREMENTS",
            AppFault::DuplicateId => "APP_DUPLICATE_ID",
            AppFault::DuplicateName => "APP_DUPLICATE_NAME",
            AppFault::UnknownRequirement => "APP_UNKNOWN_REQUIREMENT",
            AppFault::DuplicateRequirement => "APP_DUPLICATE_REQUIREMENT",
            AppFault::ExecClaimUnsupported => "APP_EXEC_CLAIM_UNSUPPORTED",
        }
    }
}

/// Listing order: table positions, by ascending `AppId`.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct AppOrder {
    idx: [u8; MAX_APPS],
    len: usize,
}

impl AppOrder {
    pub const fn empty() -> Self {
        AppOrder { idx: [0; MAX_APPS], len: 0 }
    }
    pub const fn len(&self) -> usize {
        self.len
    }
    pub const fn get(&self, k: usize) -> usize {
        self.idx[k] as usize
    }
}

const fn err(fault: AppFault, entry: usize) -> Result<AppOrder, AppError> {
    Err(AppError { fault, entry })
}

const fn bytes_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut i = 0;
    while i < a.len() {
        if a[i] != b[i] {
            return false;
        }
        i += 1;
    }
    true
}

/// Exact-name grammar: `app.` prefix, lowercase `[a-z0-9]+` segments joined by single dots, at least two segments,
/// at most MAX_APP_NAME bytes. No wildcard, no upper case, no space, no empty segment.
pub const fn name_ok(name: &str) -> bool {
    let b = name.as_bytes();
    if b.len() < 5 || b.len() > MAX_APP_NAME {
        return false;
    }
    if !(b[0] == b'a' && b[1] == b'p' && b[2] == b'p' && b[3] == b'.') {
        return false;
    }
    let mut i = 0;
    let mut seg = 0usize;
    let mut segments = 1usize;
    while i < b.len() {
        let c = b[i];
        if c == b'.' {
            if seg == 0 {
                return false;
            }
            segments += 1;
            seg = 0;
        } else if (c >= b'a' && c <= b'z') || (c >= b'0' && c <= b'9') {
            seg += 1;
        } else {
            return false;
        }
        i += 1;
    }
    seg > 0 && segments >= 2
}

/// Check an application table against the service table and compute its listing order.
pub const fn validate(apps: &[AppDesc], services: &[Desc]) -> Result<AppOrder, AppError> {
    let n = apps.len();
    if n > MAX_APPS {
        return err(AppFault::TooMany, MAX_APPS);
    }
    let mut i = 0;
    while i < n {
        if !name_ok(apps[i].name) {
            return err(AppFault::NameMalformed, i);
        }
        if apps[i].requires.len() > MAX_REQUIRES {
            return err(AppFault::TooManyRequirements, i);
        }
        let mut j = 0;
        while j < i {
            if apps[j].id.0 == apps[i].id.0 {
                return err(AppFault::DuplicateId, i);
            }
            if bytes_eq(apps[j].name.as_bytes(), apps[i].name.as_bytes()) {
                return err(AppFault::DuplicateName, i);
            }
            j += 1;
        }
        i += 1;
    }
    i = 0;
    while i < n {
        let req = apps[i].requires;
        let mut k = 0;
        while k < req.len() {
            if index_of(services, req[k]).is_none() {
                return err(AppFault::UnknownRequirement, i);
            }
            let mut m = 0;
            while m < k {
                if req[m].0 == req[k].0 {
                    return err(AppFault::DuplicateRequirement, i);
                }
                m += 1;
            }
            k += 1;
        }
        if matches!(apps[i].exec, ExecSupport::Native) && matches!(EXECUTOR, Executor::Absent) {
            return err(AppFault::ExecClaimUnsupported, i);
        }
        i += 1;
    }
    // listing order: repeatedly the smallest AppId not yet placed (selection; n <= 8)
    let mut order = AppOrder::empty();
    let mut placed = [false; MAX_APPS];
    while order.len < n {
        let mut best = usize::MAX;
        let mut c = 0;
        while c < n {
            if !placed[c] && (best == usize::MAX || apps[c].id.0 < apps[best].id.0) {
                best = c;
            }
            c += 1;
        }
        placed[best] = true;
        order.idx[order.len] = best as u8;
        order.len += 1;
    }
    Ok(order)
}

/// Compile-time check used by apptable.rs: a bad table does not build.
pub const fn assert_valid(apps: &[AppDesc], services: &[Desc]) {
    if validate(apps, services).is_err() {
        panic!("application table refused by appregistry::validate");
    }
}

/// Table position of the application named exactly `name`.
pub fn lookup(apps: &[AppDesc], name: &str) -> Option<usize> {
    apps.iter().position(|a| a.name.as_bytes() == name.as_bytes())
}
