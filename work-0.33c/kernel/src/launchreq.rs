//! Launch request text: a bounded parser for a subset of the P-12 grammar (ABRAHAM 0.33, design §4.3). Portable,
//! no `unsafe`, no allocation. The parser only reads; it keeps no copy of the text.
//!
//!   request = operation SP target [ SP "as" SP capability ]       single spaces; at most MAX_REQUEST_BYTES bytes
//!
//! - Bytes must be printable ASCII (0x21-0x7E) separated by single spaces (0x20): no leading, trailing or double
//!   space, no control byte, nothing above 0x7E.
//! - The operation word is looked up in the fixed operation-to-class table (P-13); anything else is
//!   OPERATION_UNKNOWN. The class is set here, never by the caller.
//! - The target must be exactly `app` (the collection, for `list`), an `app.` name (appregistry grammar), or a
//!   `svc.`/`dev.` name (svcregistry grammar, routed unchanged to the 0.32b service contract). Anything else, a
//!   wildcard or upper case included, is a PARSE_ERROR.
//! - 0.33 accepts no parameters: a token containing `=` is a PARSE_ERROR. Any other extra token is trailing input.
//! - A capability token is checked for shape only and never kept: the result says only that one was presented.

use crate::appregistry;
use crate::svcregistry;

pub const MAX_REQUEST_BYTES: usize = 64;
pub const MAX_CAPABILITY: usize = 31;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Op {
    Status,
    List,
    Show,
    Inspect,
    Start,
    Stop,
    Set,
    Reset,
}

impl Op {
    pub const fn name(self) -> &'static str {
        match self {
            Op::Status => "status",
            Op::List => "list",
            Op::Show => "show",
            Op::Inspect => "inspect",
            Op::Start => "start",
            Op::Stop => "stop",
            Op::Set => "set",
            Op::Reset => "reset",
        }
    }
    const ALL: [Op; 8] = [Op::Status, Op::List, Op::Show, Op::Inspect, Op::Start, Op::Stop, Op::Set, Op::Reset];
    pub fn from_word(w: &[u8]) -> Option<Op> {
        Op::ALL.iter().copied().find(|o| o.name().as_bytes() == w)
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum OpClass {
    InspectPublic,
    InspectProtected,
    Mutate,
}

impl OpClass {
    pub const fn name(self) -> &'static str {
        match self {
            OpClass::InspectPublic => "INSPECT_PUBLIC",
            OpClass::InspectProtected => "INSPECT_PROTECTED",
            OpClass::Mutate => "MUTATE",
        }
    }
}

/// The fixed operation-to-class table (P-13), independent of the target.
pub const fn class_of(op: Op) -> OpClass {
    match op {
        Op::Status | Op::List | Op::Show => OpClass::InspectPublic,
        Op::Inspect => OpClass::InspectProtected,
        Op::Start | Op::Stop | Op::Set | Op::Reset => OpClass::Mutate,
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ParseFault {
    Empty,
    TooLong,
    Byte,
    Spacing,
    NoTarget,
    TargetMalformed,
    NoCapability,
    CapabilityMalformed,
    Parameter,
    Trailing,
}

impl ParseFault {
    pub const fn code(self) -> &'static str {
        match self {
            ParseFault::Empty => "LAUNCH_PARSE_EMPTY",
            ParseFault::TooLong => "LAUNCH_PARSE_TOO_LONG",
            ParseFault::Byte => "LAUNCH_PARSE_BYTE",
            ParseFault::Spacing => "LAUNCH_PARSE_SPACING",
            ParseFault::NoTarget => "LAUNCH_PARSE_NO_TARGET",
            ParseFault::TargetMalformed => "LAUNCH_PARSE_TARGET_MALFORMED",
            ParseFault::NoCapability => "LAUNCH_PARSE_NO_CAPABILITY",
            ParseFault::CapabilityMalformed => "LAUNCH_PARSE_CAPABILITY_MALFORMED",
            ParseFault::Parameter => "LAUNCH_PARSE_PARAMETER",
            ParseFault::Trailing => "LAUNCH_PARSE_TRAILING",
        }
    }
}

/// Where a well-formed target belongs.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Namespace {
    /// `app.<name>`: the launcher.
    App,
    /// exactly `app`: the application collection (for `list`).
    Collection,
    /// `svc.<name>` or `dev.<name>`: the unchanged 0.32b service contract.
    Service,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Parsed<'a> {
    pub op: Op,
    pub class: OpClass,
    /// Only ever a string that matched its namespace grammar.
    pub target: &'a str,
    pub ns: Namespace,
    pub capability_presented: bool,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Parse<'a> {
    Ok(Parsed<'a>),
    /// The text tokenized, but its operation word is not in the table.
    UnknownOperation,
    /// `target_len` is the length of the target token when the fault is in it (for a non-echoing report).
    Malformed { fault: ParseFault, target_len: Option<usize> },
}

const fn cap_ok(b: &[u8]) -> bool {
    if b.is_empty() || b.len() > MAX_CAPABILITY {
        return false;
    }
    let mut i = 0;
    let mut seg = 0usize;
    while i < b.len() {
        let c = b[i];
        if c == b'.' {
            if seg == 0 {
                return false;
            }
            seg = 0;
        } else if (c >= b'a' && c <= b'z') || (c >= b'0' && c <= b'9') {
            seg += 1;
        } else {
            return false;
        }
        i += 1;
    }
    seg > 0
}

fn malformed<'a>(fault: ParseFault, target_len: Option<usize>) -> Parse<'a> {
    Parse::Malformed { fault, target_len }
}

pub fn parse(text: &[u8]) -> Parse<'_> {
    if text.is_empty() {
        return malformed(ParseFault::Empty, None);
    }
    if text.len() > MAX_REQUEST_BYTES {
        return malformed(ParseFault::TooLong, None);
    }
    if text.iter().any(|&c| c != b' ' && !(0x21..=0x7e).contains(&c)) {
        return malformed(ParseFault::Byte, None);
    }
    if text[0] == b' ' || text[text.len() - 1] == b' ' || text.windows(2).any(|w| w == b"  ") {
        return malformed(ParseFault::Spacing, None);
    }
    let mut tokens = text.split(|&c| c == b' ');
    let word = tokens.next().unwrap_or(&[]);
    let Some(op) = Op::from_word(word) else { return Parse::UnknownOperation };
    let Some(t) = tokens.next() else { return malformed(ParseFault::NoTarget, None) };
    // the text is printable ASCII (checked above), so it is valid UTF-8
    let Ok(target) = core::str::from_utf8(t) else { return malformed(ParseFault::Byte, None) };
    let ns = if target == "app" {
        Namespace::Collection
    } else if appregistry::name_ok(target) {
        Namespace::App
    } else if svcregistry::name_ok(target) {
        Namespace::Service
    } else {
        return malformed(ParseFault::TargetMalformed, Some(t.len()));
    };
    let mut capability_presented = false;
    while let Some(tok) = tokens.next() {
        if tok.contains(&b'=') {
            return malformed(ParseFault::Parameter, None);
        }
        if tok == b"as" && !capability_presented {
            match tokens.next() {
                None => return malformed(ParseFault::NoCapability, None),
                Some(c) if c.contains(&b'=') => return malformed(ParseFault::Parameter, None),
                Some(c) if !cap_ok(c) => return malformed(ParseFault::CapabilityMalformed, None),
                Some(_) => capability_presented = true,
            }
            continue;
        }
        return malformed(ParseFault::Trailing, None);
    }
    Parse::Ok(Parsed { op, class: class_of(op), target, ns, capability_presented })
}
