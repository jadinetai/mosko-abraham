//! Closed service registry (ABRAHAM 0.32, D-ABR-018/019; design §2). Portable logic, no `unsafe`, no allocation.
//!
//! - A table is a compiled `&'static [Desc]` (svctable.rs). There is no registration function: adding an entry is a
//!   reviewed code change.
//! - `validate` is a `const fn`. svctable.rs runs it at compile time (a bad production table does not build) and the
//!   kernel runs it again at boot, before anything starts. It refuses: more than MAX_ENTRIES entries; a malformed
//!   name; more than MAX_DEPS dependencies; a budget above MAX_WORK_UNITS; a duplicate id or name; a self-dependency;
//!   a dependency on an unknown id; a duplicate dependency; a cycle.
//! - The start order is a deterministic topological sort: among the entries whose dependencies are all placed, the
//!   smallest `ServiceId` number goes first. Table position never decides.
//! - `lookup` compares exact bytes. Anything else is unknown (the public answer is TARGET_UNKNOWN, svcrun.rs).

pub const MAX_ENTRIES: usize = 8;
pub const MAX_DEPS: usize = 4;
pub const MAX_NAME: usize = 31;
/// Largest work budget any entry may declare (design Q4).
pub const MAX_WORK_UNITS: u32 = 64;

/// A service or adapter identifier. The production numbers are the named constants in svctable.rs.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub struct ServiceId(pub u8);

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Service,
    Adapter,
}

impl Kind {
    pub const fn name(self) -> &'static str {
        match self {
            Kind::Service => "SERVICE",
            Kind::Adapter => "ADAPTER",
        }
    }
}

/// One table entry. `installed` is a compile-time fact of this configuration (no driver means not installed).
#[derive(Clone, Copy, Debug)]
pub struct Desc {
    pub id: ServiceId,
    pub name: &'static str,
    pub kind: Kind,
    pub installed: bool,
    pub deps: &'static [ServiceId],
    /// Work units one step may use.
    pub budget: u32,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum RegFault {
    TooMany,
    NameMalformed,
    TooManyDependencies,
    BudgetTooLarge,
    DuplicateId,
    DuplicateName,
    SelfDependency,
    UnknownDependency,
    DuplicateDependency,
    Cycle,
}

/// A refused table: what is wrong and at which entry (table position).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct RegError {
    pub fault: RegFault,
    pub entry: usize,
}

impl RegError {
    pub const fn code(self) -> &'static str {
        match self.fault {
            RegFault::TooMany => "SVC_TOO_MANY_ENTRIES",
            RegFault::NameMalformed => "SVC_NAME_MALFORMED",
            RegFault::TooManyDependencies => "SVC_TOO_MANY_DEPENDENCIES",
            RegFault::BudgetTooLarge => "SVC_BUDGET_TOO_LARGE",
            RegFault::DuplicateId => "SVC_DUPLICATE_ID",
            RegFault::DuplicateName => "SVC_DUPLICATE_NAME",
            RegFault::SelfDependency => "SVC_SELF_DEPENDENCY",
            RegFault::UnknownDependency => "SVC_UNKNOWN_DEPENDENCY",
            RegFault::DuplicateDependency => "SVC_DUPLICATE_DEPENDENCY",
            RegFault::Cycle => "SVC_DEPENDENCY_CYCLE",
        }
    }
}

/// Start order: table positions, first to last.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Order {
    idx: [u8; MAX_ENTRIES],
    len: usize,
}

impl Order {
    pub const fn empty() -> Self {
        Order { idx: [0; MAX_ENTRIES], len: 0 }
    }

    pub const fn len(&self) -> usize {
        self.len
    }

    /// Table position of the `k`-th entry to start.
    pub const fn get(&self, k: usize) -> usize {
        self.idx[k] as usize
    }

    pub fn positions(&self) -> &[u8] {
        &self.idx[..self.len]
    }
}

const fn err(fault: RegFault, entry: usize) -> Result<Order, RegError> {
    Err(RegError { fault, entry })
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

/// Exact-name grammar: `svc.` or `dev.` prefix, lowercase `[a-z0-9]+` segments joined by single dots, at least two
/// segments, at most MAX_NAME bytes. No wildcard, no upper case, no space, no empty segment.
pub const fn name_ok(name: &str) -> bool {
    let b = name.as_bytes();
    if b.len() < 5 || b.len() > MAX_NAME {
        return false;
    }
    let svc = b[0] == b's' && b[1] == b'v' && b[2] == b'c';
    let dev = b[0] == b'd' && b[1] == b'e' && b[2] == b'v';
    if !(svc || dev) || b[3] != b'.' {
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

/// Table position of `id`, if present.
pub const fn index_of(t: &[Desc], id: ServiceId) -> Option<usize> {
    let mut i = 0;
    while i < t.len() {
        if t[i].id.0 == id.0 {
            return Some(i);
        }
        i += 1;
    }
    None
}

const fn deps_placed(t: &[Desc], i: usize, placed: &[bool; MAX_ENTRIES]) -> bool {
    let deps = t[i].deps;
    let mut k = 0;
    while k < deps.len() {
        match index_of(t, deps[k]) {
            Some(j) => {
                if !placed[j] {
                    return false;
                }
            }
            None => return false,
        }
        k += 1;
    }
    true
}

/// Check a table and compute its start order (see the module comment for the rules, in the order they are checked).
pub const fn validate(t: &[Desc]) -> Result<Order, RegError> {
    let n = t.len();
    if n > MAX_ENTRIES {
        return err(RegFault::TooMany, MAX_ENTRIES);
    }
    let mut i = 0;
    while i < n {
        if !name_ok(t[i].name) {
            return err(RegFault::NameMalformed, i);
        }
        if t[i].deps.len() > MAX_DEPS {
            return err(RegFault::TooManyDependencies, i);
        }
        if t[i].budget > MAX_WORK_UNITS {
            return err(RegFault::BudgetTooLarge, i);
        }
        let mut j = 0;
        while j < i {
            if t[j].id.0 == t[i].id.0 {
                return err(RegFault::DuplicateId, i);
            }
            if bytes_eq(t[j].name.as_bytes(), t[i].name.as_bytes()) {
                return err(RegFault::DuplicateName, i);
            }
            j += 1;
        }
        i += 1;
    }
    i = 0;
    while i < n {
        let deps = t[i].deps;
        let mut k = 0;
        while k < deps.len() {
            if deps[k].0 == t[i].id.0 {
                return err(RegFault::SelfDependency, i);
            }
            if index_of(t, deps[k]).is_none() {
                return err(RegFault::UnknownDependency, i);
            }
            let mut m = 0;
            while m < k {
                if deps[m].0 == deps[k].0 {
                    return err(RegFault::DuplicateDependency, i);
                }
                m += 1;
            }
            k += 1;
        }
        i += 1;
    }
    let mut placed = [false; MAX_ENTRIES];
    let mut order = Order::empty();
    while order.len < n {
        let mut best = usize::MAX;
        let mut c = 0;
        while c < n {
            if !placed[c] && deps_placed(t, c, &placed) && (best == usize::MAX || t[c].id.0 < t[best].id.0) {
                best = c;
            }
            c += 1;
        }
        if best == usize::MAX {
            let mut first = 0;
            while placed[first] {
                first += 1;
            }
            return err(RegFault::Cycle, first);
        }
        placed[best] = true;
        order.idx[order.len] = best as u8;
        order.len += 1;
    }
    Ok(order)
}

/// Compile-time gate for a table: `const _: () = assert_valid(TABLE);` stops the build on any refusal.
pub const fn assert_valid(t: &[Desc]) {
    if let Err(e) = validate(t) {
        panic!("{}", e.code());
    }
}

/// Exact-byte lookup by name. Near misses (case, spaces, dots, wildcards, prefixes) are not found.
pub fn lookup(t: &[Desc], name: &str) -> Option<usize> {
    t.iter().position(|d| bytes_eq(d.name.as_bytes(), name.as_bytes()))
}
