//! Live observation of the kernel's serial console.
//!
//! Lines are cleaned exactly as the harness cleans them (`abr_boot_001.serial_lines`: latin-1, CR removed, the ANSI
//! pattern `ESC [ [0-9;=?]* letter` removed, surrounding white space stripped), then fed to an [`Observer`], which
//! keeps two separate verdicts:
//!
//! * KERNEL BOOT: firmware, loader, kernel entry, banner, OPERATIONAL, heartbeat, faults;
//! * LAUNCHER CONTRACT (the application side): the application registry, the APPINFO lines of every status round and
//!   their agreement with the services, and, for the launchpad build, the 17 requests and their results.
//!
//! These are LIVE CHECKS: a subset of the rules of the official judges (`tools/abr_boot_001.py` C12/C13 and
//! `tools/g033/launch_probe.py`), written again here so the operator sees them while the VM runs. They are not the
//! official judgment; the verification campaign re-judges the launcher's sealed logs with the official tools.

use crate::pins::Build;

pub const ENTRY: &str = "ABR|ENTRY|abr_entry reached (NASM)";
pub const KMAIN: &str = "ABR|STAGE|kmain entered (Rust no_std)";
pub const OPERATIONAL: &str = "ABR|STATE|OPERATIONAL";
pub const SVC_TABLE: [&str; 3] = ["dev.net0", "svc.counter", "svc.netmon"];
/// The production application table (D-ABR-022 Q1): id, kind, rev, exec, requires.
pub const APP_TABLE: [(&str, &str, &str, &str, &str); 3] = [
    ("app.counterview", "VIEWER", "1", "NONE", "svc.counter"),
    ("app.netstatus", "VIEWER", "1", "NONE", "svc.netmon"),
    ("app.browser", "BROWSER", "1", "NONE", "svc.netmon"),
];
const APP_ORDER: &str = "app.counterview,app.netstatus,app.browser";
const LAUNCH_PREFIXES: [&str; 4] = ["ABR|LAUNCH|", "ABR|LAUNCHRESULT|", "ABR|LAUNCHPAD|", "ABR|APPQUERY|"];
const RESERVED_STATES: [&str; 5] = ["DISPATCHED", "RUNNING", "EXITED", "FAULTED", "LOST"];
const EARLY_STAGES: [&str; 4] = ["ADMISSION", "STRUCTURE", "OPERATION", "RECOGNITION"];
/// The launchpad summary the design fixes (design §9; TR-0042 L001).
pub const LAUNCHPAD_SUMMARY: &str =
    "ABR|LAUNCHPAD|requests=17|refused=9|not_executed=6|discovery=1|routed_to_services=1|executed=0|processes=0|executor=ABSENT";
pub const FORCED_REFUSED: &str = "ABR|LAUNCH|req=1|refused|from=NOT_EXECUTED|to=RUNNING|diag=LAUNCH_INVALID_TRANSITION";
pub const FORCED_STATE: &str = "ABR|LAUNCH|req=1|state=NOT_EXECUTED";
pub const ROUTED_ANSWER: &str = "ABR|SVCQUERY|op=start|target=svc.counter|result=REFUSED|reason=CAP_MISSING";

type Fields = Vec<(&'static str, &'static str)>;

fn merge(base: &[(&'static str, &'static str)], over: &[(&'static str, &'static str)]) -> Fields {
    let mut v: Fields = base.to_vec();
    for (k, x) in over {
        match v.iter_mut().find(|(b, _)| b == k) {
            Some(slot) => slot.1 = x,
            None => v.push((k, x)),
        }
    }
    v
}

/// The 17 requests of the DIAGNOSTIC launchpad script, as design section 9 fixes them: a port of
/// `launch_probe.expected_script()`. Each row: (request id, kind, the fields its line must carry).
pub fn expected_script() -> Vec<(&'static str, &'static str, Fields)> {
    let val: Fields = vec![
        ("admission", "FRESH"), ("structure", "WELL_FORMED"), ("known", "YES"), ("support", "NONE"),
        ("capability", "NONE"), ("executed", "NO"), ("process", "NONE"), ("state", "NOT_EXECUTED"),
        ("stage", "AUTHORIZATION"), ("result", "NOT_EXECUTED"), ("verification", "NOT_APPLICABLE"),
        ("boundary", "COOPERATIVE"), ("class", "MUTATE"), ("op", "start"), ("prerequisites", "SATISFIED"),
        ("unavailable", "NONE"), ("authorization", "CAP_MISSING"), ("reason", "CAP_MISSING"), ("diag", "LAUNCH_CAP_MISSING"),
    ];
    let refd: Fields = vec![
        ("admission", "FRESH"), ("structure", "WELL_FORMED"), ("known", "NO"), ("prerequisites", "NOT_EVALUATED"),
        ("unavailable", "NOT_EVALUATED"), ("support", "NOT_EVALUATED"), ("capability", "NONE"),
        ("authorization", "NOT_EVALUATED"), ("executed", "NO"), ("process", "NONE"), ("state", "REFUSED"),
        ("result", "NOT_EXECUTED"), ("verification", "NOT_APPLICABLE"), ("boundary", "COOPERATIVE"), ("op", "start"),
        ("class", "MUTATE"), ("stage", "RECOGNITION"), ("reason", "TARGET_UNKNOWN"), ("diag", "LAUNCH_TARGET_UNKNOWN"),
    ];
    let net: Fields = vec![("prerequisites", "UNSATISFIED"), ("unavailable", "svc.netmon:UNAVAILABLE:NOT_INSTALLED")];
    let parse: Fields = vec![
        ("op", "NONE"), ("target", "NONE"), ("class", "NONE"), ("structure", "MALFORMED"), ("known", "NOT_EVALUATED"),
        ("stage", "STRUCTURE"), ("reason", "PARSE_ERROR"),
    ];
    let rp = merge(&refd, &parse);
    vec![
        ("1", "result", merge(&val, &[("target", "app.counterview")])),
        ("2", "result", merge(&merge(&val, &[("target", "app.netstatus")]), &net)),
        ("3", "result", merge(&merge(&val, &[("target", "app.browser")]), &net)),
        ("4", "result", merge(&val, &[("target", "app.counterview"), ("capability", "PRESENTED"), ("authorization", "NO_AUTHORITY"),
                                      ("reason", "AUTHZ_UNAVAILABLE"), ("diag", "LAUNCH_NO_AUTHORITY")])),
        ("5", "result", merge(&val, &[("op", "stop"), ("target", "app.counterview")])),
        ("6", "result", merge(&val, &[("op", "inspect"), ("target", "app.counterview"), ("class", "INSPECT_PROTECTED")])),
        ("7", "query", vec![("op", "status"), ("target", "app.counterview")]),
        ("8", "result", merge(&refd, &[("target", "app.nosuch")])),
        ("9", "result", merge(&refd, &[("target", "app.counterviews")])),
        ("10", "result", merge(&rp, &[("target", "MALFORMED"), ("target_len", "15"), ("diag", "LAUNCH_PARSE_TARGET_MALFORMED")])),
        ("11", "result", merge(&rp, &[("target", "MALFORMED"), ("target_len", "5"), ("diag", "LAUNCH_PARSE_TARGET_MALFORMED")])),
        ("12", "result", merge(&refd, &[("op", "UNKNOWN"), ("target", "NONE"), ("known", "NOT_EVALUATED"), ("stage", "OPERATION"),
                                       ("reason", "OPERATION_UNKNOWN"), ("diag", "LAUNCH_OPERATION_UNKNOWN"), ("class", "NONE")])),
        ("13", "result", merge(&rp, &[("diag", "LAUNCH_PARSE_PARAMETER")])),
        ("14", "result", merge(&rp, &[("diag", "LAUNCH_PARSE_SPACING")])),
        ("15", "result", merge(&rp, &[("diag", "LAUNCH_PARSE_TOO_LONG")])),
        ("1", "result", merge(&refd, &[("op", "NONE"), ("target", "NONE"), ("admission", "NOT_INCREASING"), ("structure", "NOT_EVALUATED"),
                                      ("known", "NOT_EVALUATED"), ("stage", "ADMISSION"), ("reason", "REQUEST_REPLAYED"),
                                      ("diag", "LAUNCH_ID_NOT_INCREASING"), ("class", "NONE")])),
        ("16", "routed", vec![("op", "start"), ("target", "svc.counter")]),
    ]
}

/// The field order of a launch result line (launch_probe FIELDS; `target_len` follows `target` when present).
const RESULT_FIELDS: [&str; 21] = [
    "req", "op", "target", "class", "admission", "structure", "known", "prerequisites", "unavailable", "support",
    "capability", "authorization", "executed", "process", "state", "stage", "result", "verification", "boundary",
    "reason", "diag",
];
const DIAG_REASON: [(&str, &str); 6] = [
    ("LAUNCH_ID_NOT_INCREASING", "REQUEST_REPLAYED"), ("LAUNCH_OPERATION_UNKNOWN", "OPERATION_UNKNOWN"),
    ("LAUNCH_TARGET_UNKNOWN", "TARGET_UNKNOWN"), ("LAUNCH_REGISTRY_REFUSED", "TARGET_UNKNOWN"),
    ("LAUNCH_CAP_MISSING", "CAP_MISSING"), ("LAUNCH_NO_AUTHORITY", "AUTHZ_UNAVAILABLE"),
];

/// `ABR|LAUNCH|req=N|seq=S|from=F|to=T`
fn parse_transition(l: &str) -> Option<(String, String, String, String)> {
    let f = fields(l, "ABR|LAUNCH|")?;
    match f.as_slice() {
        [("req", r), ("seq", s), ("from", a), ("to", b)] => Some((r.to_string(), s.to_string(), a.to_string(), b.to_string())),
        _ => None,
    }
}

/// Cleans one raw serial line the way the harness does.
pub fn clean(raw: &[u8]) -> String {
    let mut out = String::with_capacity(raw.len());
    let mut i = 0;
    while i < raw.len() {
        let c = raw[i];
        if c == b'\r' {
            i += 1;
            continue;
        }
        if c == 0x1b && i + 1 < raw.len() && raw[i + 1] == b'[' {
            let mut j = i + 2;
            while j < raw.len() && (raw[j].is_ascii_digit() || matches!(raw[j], b';' | b'=' | b'?')) {
                j += 1;
            }
            if j < raw.len() && raw[j].is_ascii_alphabetic() {
                i = j + 1;
                continue;
            }
        }
        out.push(c as char); // latin-1
        i += 1;
    }
    out.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)).to_string()
}

/// Text that is safe to print on a terminal: no control characters from the guest reach the console.
pub fn printable(s: &str) -> String {
    s.chars().map(|c| if (c as u32) < 0x20 || (0x7f..0xa0).contains(&(c as u32)) { '.' } else { c }).collect()
}

#[derive(Default)]
pub struct LineAssembler {
    pending: Vec<u8>,
}

impl LineAssembler {
    /// Complete lines from the new bytes; a line still being written stays pending.
    pub fn push(&mut self, bytes: &[u8]) -> Vec<String> {
        self.pending.extend_from_slice(bytes);
        let mut out = Vec::new();
        while let Some(pos) = self.pending.iter().position(|&b| b == b'\n') {
            let line: Vec<u8> = self.pending.drain(..=pos).collect();
            out.push(clean(&line[..line.len() - 1]));
        }
        out
    }
    /// The final unterminated line, at the end of capture.
    pub fn flush(&mut self) -> Option<String> {
        if self.pending.is_empty() {
            return None;
        }
        let s = clean(&self.pending);
        self.pending.clear();
        Some(s)
    }
}

/// `key=value` fields after a fixed prefix, in order. None unless every part has a `=`.
fn fields<'a>(line: &'a str, prefix: &str) -> Option<Vec<(&'a str, &'a str)>> {
    let rest = line.strip_prefix(prefix)?;
    let mut v = Vec::new();
    for part in rest.split('|') {
        let (k, x) = part.split_once('=')?;
        v.push((k, x));
    }
    Some(v)
}

fn field<'a>(f: &[(&'a str, &'a str)], key: &str) -> Option<&'a str> {
    f.iter().find(|(k, _)| *k == key).map(|(_, v)| *v)
}

/// The values of every `|name=` occurrence in a line.
fn values_of<'a>(line: &'a str, name: &str) -> Vec<&'a str> {
    let pat = format!("|{name}=");
    let mut out = Vec::new();
    let mut from = 0;
    while let Some(p) = line[from..].find(&pat) {
        let start = from + p + pat.len();
        let end = line[start..].find('|').map(|e| start + e).unwrap_or(line.len());
        out.push(&line[start..end]);
        from = start;
    }
    out
}

/// The official execution-claim rule (abr_boot_001.execution_claims): a line that claims or implies that something
/// executed. A refused transition names its refused target (to=RUNNING) and is not a claim.
pub fn is_execution_claim(l: &str) -> bool {
    if !l.starts_with("ABR|") {
        return false;
    }
    let launch = l.starts_with("ABR|LAUNCH|") || l.starts_with("ABR|LAUNCHRESULT|");
    l.contains("executed=YES")
        || values_of(l, "process").iter().any(|v| *v != "NONE")
        || l.contains("exec=NATIVE")
        || values_of(l, "executor").iter().any(|v| *v != "ABSENT")
        || values_of(l, "processes").iter().any(|v| *v != "0")
        || values_of(l, "executed").iter().any(|v| *v != "0" && *v != "NO")
        || (launch
            && !l.contains("|refused|")
            && values_of(l, "state").iter().chain(values_of(l, "to").iter()).any(|v| RESERVED_STATES.contains(v)))
}

#[derive(Clone, Debug, Default)]
pub struct Svc {
    pub id: String,
    pub state: String,
    pub status: String,
    pub reason: String,
    pub liveness: String,
    pub compromise: String,
    pub at: String,
    pub clock: String,
    pub value: String,
    pub steps: String,
    pub overruns: String,
}

#[derive(Clone, Debug)]
pub enum AppReg {
    Ok { n: String, order: String, executor: String },
    Refused { diag: String, entry: String, #[allow(dead_code)] executor: String },
}

#[derive(Clone, Debug)]
enum Expect {
    Nothing,
    /// The APPINFO group that must follow the status round just completed.
    Round { next: usize, ok: bool },
    /// The APPINFO answer of a discovery request (APPQUERY).
    Query { ids: Vec<String>, next: usize },
}

#[derive(Clone, Debug, Default)]
pub struct LaunchRow {
    pub req: String,
    pub op: String,
    pub target: String,
    pub state: String,
    pub stage: String,
    #[allow(dead_code)]
    pub reason: String,
    pub diag: String,
    pub prerequisites: String,
    pub authorization: String,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Verdict {
    Waiting(String),
    InProgress(String),
    Consistent(String),
    Inconsistent(String),
    NotReached(String),
}

impl Verdict {
    pub fn word(&self) -> &'static str {
        match self {
            Verdict::Waiting(_) => "WAITING",
            Verdict::InProgress(_) => "IN PROGRESS",
            Verdict::Consistent(_) => "CONSISTENT",
            Verdict::Inconsistent(_) => "INCONSISTENT",
            Verdict::NotReached(_) => "NOT REACHED",
        }
    }
    pub fn text(&self) -> &str {
        match self {
            Verdict::Waiting(s)
            | Verdict::InProgress(s)
            | Verdict::Consistent(s)
            | Verdict::Inconsistent(s)
            | Verdict::NotReached(s) => s,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Boot {
    WaitingForFirmware,
    LoaderStarted,
    KernelEntered,
    Operational,
    Failed(String),
}

pub struct Observer {
    pub build: Build,
    pub version: &'static str,
    pub lines: usize,
    pub firmware_boot: Option<String>,
    pub firmware_shell: bool,
    pub entries: u32,
    pub kmain: bool,
    pub loader: Option<(String, bool)>,
    pub banner_version: Option<String>,
    pub banner_epoch: Option<String>,
    pub human_banner: bool,
    pub operational_at: Option<f64>,
    pub ticks: u32,
    pub last_uptime: Option<u64>,
    pub ticks_continuous: bool,
    pub last_tick_at: Option<f64>,
    pub faults: Vec<String>,
    pub fault_before_operational: bool,
    pub init_failed: Option<String>,
    pub svc_registry: Option<String>,
    round: Vec<Svc>,
    pub rounds: u32,
    pub latest: Option<Vec<Svc>>,
    last_counter: Option<u64>,
    /// (round time, counter value) of the previous round whose clock was OK (F-VML-02).
    last_ok_round: Option<(u64, u64)>,
    pub service_problems: Vec<String>,
    pub app_registry: Option<AppReg>,
    app_registry_lines: u32,
    expect: Expect,
    pub appinfo_groups: u32,
    pub latest_apps: Vec<(String, String, String)>,
    pub rows: Vec<LaunchRow>,
    pub appqueries: u32,
    pub routed: u32,
    pub routed_answer: Option<String>,
    pub summary: Option<String>,
    pub forced_refused: bool,
    pub state_after_forced: Option<String>,
    pub launch_lines: u32,
    pub contract_problems: Vec<String>,
    pub claims: Vec<String>,
    pub boot_problems: Vec<String>,
    /// A line cut by the end of capture (QEMU stopped while it was being written). Recorded, never judged.
    pub cut_line: Option<String>,
    /// An APPINFO group cut by the end of capture. Recorded; not a contract problem (as in the official C13).
    pub cut_group: Option<String>,
    pending_transitions: Vec<(String, String, String, String)>,
    /// F-VML-01 (0.33.1): the kernel's own clock reports (clockguard.rs, main.rs).
    pub clock_anomalies: Vec<String>,
    /// The reason of the kernel's `ABR|CLOCK|state=DEGRADED` line, once printed (latched for the boot).
    pub clock_degraded: Option<String>,
    /// Heartbeat gaps the kernel reported itself, each with its forward TSC jump: (from_s, to_s, skipped).
    /// 0.33.2 (D-ABR-026 3A): these establish a discontinuity the kernel observed, not its cause. A host suspension, a
    /// host-side stop of QEMU alone and a guest-side stall look the same from inside; the cause is judged only with
    /// host evidence, by the launcher (main.rs).
    pub clock_gaps: Vec<(u64, u64, u64)>,
    /// 0.33.2 (F-VML-03): C12's progress and spacing findings between clock-OK rounds. They count only on a run whose
    /// clock never degraded: like the official judges, which do not apply C12 once the clock is DEGRADED. The kernel's
    /// guard may report a jump up to one round late (0.32b's documented detection window), so the round that
    /// straddles the jump still says clock=OK.
    pub c12_pair_problems: Vec<String>,
    /// Heartbeat discontinuities the kernel did not report: (previous, next).
    pub unexplained_gaps: Vec<(u64, u64)>,
    pending_jump: bool,
    pending_gap: Option<(u64, u64, u64)>,
    /// A status round with a clock other than OK has been seen (latched).
    round_clock_degraded: bool,
    /// How many script requests (results, discovery, routed) have been compared with the design.
    pub script_pos: usize,
    script: Vec<(&'static str, &'static str, Fields)>,
    inject_seen: bool,
    first_launch_seen: bool,
}

impl Observer {
    pub fn new(build: Build, version: &'static str) -> Self {
        Observer {
            build,
            version,
            lines: 0,
            firmware_boot: None,
            firmware_shell: false,
            entries: 0,
            kmain: false,
            loader: None,
            banner_version: None,
            banner_epoch: None,
            human_banner: false,
            operational_at: None,
            ticks: 0,
            last_uptime: None,
            ticks_continuous: true,
            last_tick_at: None,
            faults: Vec::new(),
            fault_before_operational: false,
            init_failed: None,
            svc_registry: None,
            round: Vec::new(),
            rounds: 0,
            latest: None,
            last_counter: None,
            last_ok_round: None,
            service_problems: Vec::new(),
            app_registry: None,
            app_registry_lines: 0,
            expect: Expect::Nothing,
            appinfo_groups: 0,
            latest_apps: Vec::new(),
            rows: Vec::new(),
            appqueries: 0,
            routed: 0,
            routed_answer: None,
            summary: None,
            forced_refused: false,
            state_after_forced: None,
            launch_lines: 0,
            contract_problems: Vec::new(),
            claims: Vec::new(),
            boot_problems: Vec::new(),
            cut_line: None,
            cut_group: None,
            pending_transitions: Vec::new(),
            clock_anomalies: Vec::new(),
            clock_degraded: None,
            clock_gaps: Vec::new(),
            c12_pair_problems: Vec::new(),
            unexplained_gaps: Vec::new(),
            pending_jump: false,
            pending_gap: None,
            round_clock_degraded: false,
            script_pos: 0,
            script: expected_script(),
            inject_seen: false,
            first_launch_seen: false,
        }
    }

    /// Compares the next script request with the design.
    fn script_step(&mut self, kind: &str, req: &str, got: &[(&str, &str)]) {
        let pos = self.script_pos;
        self.script_pos += 1;
        let (want_req, want_kind, want) = match self.script.get(pos) {
            Some(x) => (x.0, x.1, x.2.clone()),
            None => {
                self.contract_problem(format!("request {req}: more requests than the 17 of the design"));
                return;
            }
        };
        if (want_req, want_kind) != (req, kind) {
            self.contract_problem(format!(
                "script row {}: request {req} ({kind}) where the design has request {want_req} ({want_kind})",
                pos + 1
            ));
            return;
        }
        for (k, v) in want {
            let g = got.iter().find(|(x, _)| *x == k).map(|(_, y)| *y);
            if g != Some(v) {
                self.contract_problem(format!("request {req}: {k}={} where the design has {v}", g.unwrap_or("(absent)")));
            }
        }
    }

    /// The capture has ended. `partial` is the unterminated last line, if any.
    pub fn end_of_capture(&mut self, partial: Option<String>) {
        if let Some(p) = partial.filter(|p| !p.is_empty()) {
            self.cut_line = Some(p);
        }
        match std::mem::replace(&mut self.expect, Expect::Nothing) {
            Expect::Round { next, .. } => {
                self.cut_group = Some(format!("status round {}: {next} of 3 APPINFO lines before the end of capture", self.rounds))
            }
            Expect::Query { ids, next } => {
                self.cut_group = Some(format!("discovery answer: {next} of {} APPINFO lines before the end of capture", ids.len()))
            }
            Expect::Nothing => {}
        }
    }

    fn contract_problem(&mut self, s: String) {
        if self.contract_problems.len() < 50 {
            self.contract_problems.push(s);
        }
    }

    fn service_problem(&mut self, s: String) {
        if self.service_problems.len() < 50 {
            self.service_problems.push(s);
        }
    }

    /// Feeds one cleaned line, observed `t` seconds after the VM was resumed.
    pub fn feed(&mut self, l: &str, t: f64) {
        if l.is_empty() {
            return;
        }
        self.lines += 1;
        let short: String = l.chars().take(90).collect();

        // An APPINFO group must follow its status round (or discovery request) directly.
        if !l.starts_with("ABR|APPINFO|") {
            match std::mem::replace(&mut self.expect, Expect::Nothing) {
                Expect::Round { next, .. } => self.contract_problem(format!(
                    "status round {}: only {next} of 3 APPINFO lines before `{short}`",
                    self.rounds
                )),
                Expect::Query { ids, next } => self.contract_problem(format!(
                    "discovery answer: only {next} of {} APPINFO lines before `{short}`",
                    ids.len()
                )),
                Expect::Nothing => {}
            }
        }

        if is_execution_claim(l) && self.claims.len() < 20 {
            self.claims.push(l.to_string());
        }
        if l.starts_with("ABR|") {
            let is_launch = LAUNCH_PREFIXES.iter().any(|p| l.starts_with(p)) || l.contains("injecting=launch");
            if is_launch {
                self.launch_lines += 1;
                if self.build != Build::Launchpad {
                    self.contract_problem(format!("launch line in a build that makes no request: `{short}`"));
                } else if !self.first_launch_seen {
                    self.first_launch_seen = true;
                    if self.operational_at.is_none() || !matches!(self.app_registry, Some(AppReg::Ok { .. })) || self.rounds == 0 {
                        self.contract_problem(
                            "the launcher script began before OPERATIONAL, the application registry and the first status round".into(),
                        );
                    }
                }
            }
            if self.build == Build::Launchpad {
                if let Some(t) = parse_transition(l) {
                    self.pending_transitions.push(t);
                    return;
                }
                if !self.pending_transitions.is_empty() && !l.starts_with("ABR|LAUNCHRESULT|") {
                    let r = self.pending_transitions[0].0.clone();
                    self.contract_problem(format!("transitions of request {r} not right before its result (`{short}` came between)"));
                    self.pending_transitions.clear();
                }
            }
        }

        if l.starts_with("BdsDxe: starting Boot") {
            if l.contains("PciRoot(") {
                self.firmware_boot.get_or_insert_with(|| l.to_string());
            } else if l.contains("Fv(") {
                self.firmware_shell = true;
            }
            return;
        }
        if l == ENTRY {
            self.entries += 1;
            if self.entries > 1 {
                self.boot_problems.push(format!("kernel entered {} times: the guest was reset", self.entries));
            }
            return;
        }
        if l == KMAIN {
            self.kmain = true;
            return;
        }
        if l == OPERATIONAL {
            if self.operational_at.is_none() {
                self.operational_at = Some(t);
            } else {
                self.boot_problems.push("OPERATIONAL reported twice".into());
            }
            return;
        }
        if let Some(rest) = l.strip_prefix("ABRAHAM | MOSKO native kernel ") {
            if rest.ends_with(" | ABR-BOOT-001") && !rest.trim_end_matches(" | ABR-BOOT-001").contains(' ') {
                self.human_banner = true;
            }
            return;
        }
        if let Some(f) = fields(l, "ABR|BOOTINFO|") {
            if let (Some(name), Some(rev)) = (field(&f, "loader"), field(&f, "base_revision_supported")) {
                self.loader = Some((name.to_string(), rev == "true"));
            }
            return;
        }
        if l.starts_with("ABR|BANNER|") {
            let f: Vec<(&str, &str)> =
                l["ABR|BANNER|".len()..].split('|').filter_map(|p| p.split_once('=')).collect();
            self.banner_version = field(&f, "version").map(String::from);
            self.banner_epoch = field(&f, "boot_epoch").map(String::from);
            return;
        }
        if let Some(f) = fields(l, "ABR|CLOCK|") {
            // The kernel's clock guard (KERNEL_DIAGNOSTICS §15): a forward TSC jump (more than 5 s between
            // readings), a backward reading, a heartbeat gap (more than 5 missing seconds), and DEGRADED,
            // latched after the first anomaly.
            match (field(&f, "anomaly"), field(&f, "state")) {
                (Some("TSC_FORWARD_JUMP"), _) => {
                    self.pending_jump = true;
                    self.clock_anomalies.push(l.to_string());
                }
                (Some("HEARTBEAT_GAP"), _) => {
                    let num = |k: &str| field(&f, k).and_then(|v| v.parse::<u64>().ok());
                    match (num("from_s"), num("to_s"), num("skipped")) {
                        (Some(a), Some(b), Some(n)) if b > a && n == b - a - 1 => self.pending_gap = Some((a, b, n)),
                        _ => self.boot_problems.push(format!("malformed heartbeat-gap report: `{short}`")),
                    }
                    self.clock_anomalies.push(l.to_string());
                }
                (Some(_), _) => self.clock_anomalies.push(l.to_string()),
                (None, Some("DEGRADED")) => {
                    if self.clock_anomalies.is_empty() {
                        self.boot_problems.push("clock DEGRADED with no anomaly reported before it".into());
                    }
                    self.clock_degraded.get_or_insert_with(|| field(&f, "reason").unwrap_or("").to_string());
                }
                _ => {}
            }
            return;
        }
        if let Some(f) = l.strip_prefix("ABR|TICK|uptime_s=") {
            let n: Option<u64> = f.split('|').next().and_then(|s| s.parse().ok());
            if let Some(n) = n {
                if let Some(prev) = self.last_uptime {
                    if n != prev + 1 {
                        // A discontinuity is a reported clock gap only if the kernel reported exactly this gap, after the
                        // forward TSC jump that produced it (F-VML-01). Anything else stays a boot problem.
                        if self.pending_gap == Some((prev, n, n - prev - 1)) && self.pending_jump {
                            self.clock_gaps.push((prev, n, n - prev - 1));
                        } else {
                            self.unexplained_gaps.push((prev, n));
                            self.ticks_continuous = false;
                        }
                    } else if let Some(g) = self.pending_gap {
                        self.boot_problems.push(format!(
                            "the kernel reported a heartbeat gap {} -> {} that its heartbeat lines do not show",
                            g.0, g.1
                        ));
                    }
                }
                self.pending_gap = None;
                self.pending_jump = false;
                self.last_uptime = Some(n);
                self.ticks += 1;
                self.last_tick_at = Some(t);
            }
            return;
        }
        if l.starts_with("ABR|FAULT|") {
            self.faults.push(l.to_string());
            if self.operational_at.is_none() {
                self.fault_before_operational = true;
            }
            return;
        }
        if l.starts_with("ABR|INIT|") && l.contains("|to=FAILED") {
            let reason = values_of(l, "reason").first().map(|s| s.to_string()).unwrap_or_else(|| "NONE".into());
            self.init_failed = Some(reason);
            return;
        }
        if let Some(f) = fields(l, "ABR|SVC|") {
            if let (Some("OK"), Some(order)) = (field(&f, "registry"), field(&f, "order")) {
                self.svc_registry = Some(order.to_string());
            }
            return;
        }
        if let Some(f) = fields(l, "ABR|SVCSTATUS|") {
            self.svc_status(&f, &short);
            return;
        }
        if l.starts_with("ABR|APP|") {
            self.app_registry_line(l, &short);
            return;
        }
        if l.starts_with("ABR|APPINFO|") {
            self.appinfo(l, &short);
            return;
        }
        if let Some(f) = fields(l, "ABR|APPQUERY|") {
            self.appqueries += 1;
            let op = field(&f, "op").unwrap_or("");
            let target = field(&f, "target").unwrap_or("");
            let ids: Vec<String> = if op == "list" {
                APP_TABLE.iter().map(|a| a.0.to_string()).collect()
            } else {
                vec![target.to_string()]
            };
            if field(&f, "result") != Some("OK") {
                self.contract_problem(format!("discovery request not answered OK: `{short}`"));
            }
            if self.build == Build::Launchpad {
                let req = field(&f, "req").unwrap_or("").to_string();
                self.script_step("query", &req, &f);
            }
            self.expect = Expect::Query { ids, next: 0 };
            return;
        }
        if l.starts_with("ABR|LAUNCHRESULT|") {
            self.launch_result(l, &short);
            return;
        }
        if let Some(rest) = l.strip_prefix("ABR|LAUNCHPAD|") {
            self.summary = Some(l.to_string());
            if self.script_pos != 17 {
                self.contract_problem(format!("summary after {} of the 17 script requests", self.script_pos));
            }
            if l != LAUNCHPAD_SUMMARY {
                self.contract_problem(format!("launchpad summary differs from the design: `{rest}`"));
            }
            let refused = self.rows.iter().filter(|r| r.state == "REFUSED").count();
            let not_exec = self.rows.iter().filter(|r| r.state == "NOT_EXECUTED").count();
            let f: Vec<(&str, &str)> = rest.split('|').filter_map(|p| p.split_once('=')).collect();
            let num = |k: &str| field(&f, k).and_then(|v| v.parse::<usize>().ok());
            let counted = self.rows.len() + self.appqueries as usize + self.routed as usize;
            if num("requests") != Some(counted)
                || num("refused") != Some(refused)
                || num("not_executed") != Some(not_exec)
                || num("discovery") != Some(self.appqueries as usize)
                || num("routed_to_services") != Some(self.routed as usize)
            {
                self.contract_problem(format!(
                    "summary counts disagree with the lines: lines give requests={counted} refused={refused} not_executed={not_exec} discovery={} routed={}",
                    self.appqueries, self.routed
                ));
            }
            return;
        }
        if l == FORCED_REFUSED {
            self.forced_refused = true;
            if !self.inject_seen {
                self.contract_problem("a RUNNING refusal without the diagnostic injection before it".into());
            }
            return;
        }
        if self.forced_refused && l.starts_with("ABR|LAUNCH|req=1|state=") {
            self.state_after_forced = Some(l.to_string());
            if l != FORCED_STATE {
                self.contract_problem(format!("state after the refused RUNNING transition: `{short}`"));
            }
            return;
        }
        if l.starts_with("ABR|LAUNCH|") && l.contains("|routed=SERVICE|") {
            self.routed += 1;
            let flat = l.replacen("|routed=SERVICE|", "|", 1);
            if let Some(f) = fields(&flat, "ABR|LAUNCH|") {
                let req = field(&f, "req").unwrap_or("").to_string();
                let owned: Vec<(String, String)> = f.iter().map(|(a, b)| (a.to_string(), b.to_string())).collect();
                let view: Vec<(&str, &str)> = owned.iter().map(|(a, b)| (a.as_str(), b.as_str())).collect();
                self.script_step("routed", &req, &view);
            }
            return;
        }
        if l.starts_with("ABR|DIAG|injecting=launch_invalid_transition|") {
            self.inject_seen = true;
            return;
        }
        if l.starts_with("ABR|SVCQUERY|") {
            self.routed_answer = Some(l.to_string());
            if l != ROUTED_ANSWER {
                self.contract_problem(format!("the routed service request was not answered CAP_MISSING: `{short}`"));
            }
        }
    }

    fn svc_status(&mut self, f: &[(&str, &str)], short: &str) {
        let s = Svc {
            id: field(f, "id").unwrap_or("").into(),
            state: field(f, "state").unwrap_or("").into(),
            status: field(f, "status").unwrap_or("").into(),
            reason: field(f, "reason").unwrap_or("").into(),
            liveness: field(f, "liveness").unwrap_or("").into(),
            compromise: field(f, "compromise").unwrap_or("").into(),
            at: field(f, "observed_at_ms").unwrap_or("").into(),
            clock: field(f, "clock").unwrap_or("").into(),
            value: field(f, "value").unwrap_or("").into(),
            steps: field(f, "steps").unwrap_or("").into(),
            overruns: field(f, "overruns").unwrap_or("").into(),
        };
        if SVC_TABLE.get(self.round.len()) != Some(&s.id.as_str()) {
            self.service_problem(format!("status line out of table order: `{short}`"));
            self.round.clear();
            return;
        }
        self.round.push(s);
        if self.round.len() < SVC_TABLE.len() {
            return;
        }
        let round = std::mem::take(&mut self.round);
        self.rounds += 1;
        let r = self.rounds;
        let counter = &round[1];
        // F-VML-01 (0.33.1): each round is judged by its own clock field, with the official status mapping
        // (abr_boot_001.status_possible): RUNNING with the clock OK is AVAILABLE; RUNNING with any other clock is
        // UNKNOWN / OBSERVATION_STALE / liveness UNKNOWN. Stale data is never AVAILABLE.
        let clock = counter.clock.clone();
        if round.iter().any(|s| s.clock != clock) {
            self.service_problem(format!("round {r}: the services disagree on the clock"));
        }
        if clock == "OK" {
            if self.round_clock_degraded {
                self.service_problem(format!("round {r}: clock OK after a DEGRADED round (the guard is latched)"));
            }
            // F-VML-02 (0.33.1): C12's counter rules (abr_boot_001.judge_services), for every round whose clock is
            // OK: the full status, an observation under 1 s old, value = steps + 1, at least 250 steps per round, and
            // rounds 5,000-5,500 ms apart. A host freeze shorter than the kernel's 5 s detection limit shows here.
            let round_at: Option<u64> = round[0].at.parse().ok();
            let fresh = match (round_at, counter.at.parse::<u64>().ok()) {
                (Some(a), Some(b)) => a >= b && a - b < 1000,
                _ => false,
            };
            if !(counter.state == "RUNNING" && counter.status == "AVAILABLE" && counter.reason == "NONE"
                && counter.liveness == "LIVE" && counter.compromise == "NONE_KNOWN" && counter.overruns == "0" && fresh)
            {
                self.service_problem(format!(
                    "round {r}: svc.counter {}/{} {} liveness {} overruns {} (expected RUNNING/AVAILABLE, LIVE, fresh, no overrun, with the clock OK)",
                    counter.state, counter.status, counter.reason, counter.liveness, counter.overruns
                ));
            }
            let value: Option<u64> = counter.value.parse().ok();
            let steps: Option<u64> = counter.steps.parse().ok();
            if value.is_none() || value != steps.map(|s| s + 1) {
                self.service_problem(format!("round {r}: svc.counter value {} is not steps {} + 1", counter.value, counter.steps));
            }
            if let (Some((prev_at, prev_v)), Some(at), Some(v)) = (self.last_ok_round, round_at, value) {
                if v < prev_v + 250 {
                    self.c12_pair_problems.push(format!(
                        "round {r}: svc.counter advanced {} steps in one status round (the harness expects at least 250): \
                         the VM ran slower than designed, or was frozen for less than the kernel's 5 s detection limit",
                        v.saturating_sub(prev_v)
                    ));
                }
                if !(at >= prev_at + 5000 && at < prev_at + 5500) {
                    self.c12_pair_problems
                        .push(format!("round {r}: {} ms after the previous round (the harness expects 5,000-5,500)", at.saturating_sub(prev_at)));
                }
            }
            if let (Some(at), Some(v)) = (round_at, value) {
                self.last_ok_round = Some((at, v));
            }
        } else {
            self.round_clock_degraded = true;
            self.last_ok_round = None;
            if self.clock_degraded.is_none() {
                self.service_problem(format!("round {r}: clock {clock} without the kernel's DEGRADED report"));
            }
            if !(counter.state == "RUNNING" && counter.status == "UNKNOWN" && counter.reason == "OBSERVATION_STALE"
                && counter.liveness == "UNKNOWN")
            {
                self.service_problem(format!(
                    "round {r}: svc.counter {}/{} {} with the clock {clock} (expected RUNNING/UNKNOWN OBSERVATION_STALE)",
                    counter.state, counter.status, counter.reason
                ));
            }
        }
        match counter.value.parse::<u64>() {
            Ok(v) => {
                if let Some(prev) = self.last_counter {
                    if v <= prev {
                        self.service_problem(format!("round {r}: svc.counter value {v} not above {prev}"));
                    }
                }
                self.last_counter = Some(v);
            }
            Err(_) if counter.status == "AVAILABLE" => {
                self.service_problem(format!("round {r}: svc.counter AVAILABLE without a value"))
            }
            Err(_) => {}
        }
        for s in [&round[0], &round[2]] {
            if !(s.state == "DECLARED" && s.status == "UNAVAILABLE" && s.reason == "NOT_INSTALLED" && s.liveness == "UNKNOWN"
                && s.compromise == "NONE_KNOWN" && s.value == "NONE" && s.steps == "0" && s.overruns == "0")
            {
                let msg = format!("round {r}: {} {}/{} {} (expected DECLARED/UNAVAILABLE NOT_INSTALLED)", s.id, s.state, s.status, s.reason);
                self.service_problem(msg);
            }
        }
        let registry = match &self.app_registry {
            Some(AppReg::Ok { .. }) => 1,
            Some(AppReg::Refused { .. }) => 2,
            None => 0,
        };
        if registry == 1 {
            self.expect = Expect::Round { next: 0, ok: true };
        } else if registry == 0 && self.build != Build::EarlyFail {
            self.contract_problem(format!("status round {r} before the application registry line"));
        }
        self.latest = Some(round);
    }

    fn app_registry_line(&mut self, l: &str, short: &str) {
        self.app_registry_lines += 1;
        if self.app_registry_lines > 1 {
            self.contract_problem(format!("application registry reported again: `{short}`"));
            return;
        }
        if self.operational_at.is_none() {
            self.contract_problem("application registry before OPERATIONAL".into());
        }
        if self.svc_registry.is_none() {
            self.contract_problem("application registry before the service registry".into());
        }
        if self.rounds > 0 {
            self.contract_problem("application registry after the first status round".into());
        }
        match fields(l, "ABR|APP|") {
            Some(f) if field(&f, "registry") == Some("OK") && f.len() == 4 => {
                let reg = AppReg::Ok {
                    n: field(&f, "entries").unwrap_or("").into(),
                    order: field(&f, "order").unwrap_or("").into(),
                    executor: field(&f, "executor").unwrap_or("").into(),
                };
                if let AppReg::Ok { n, order, executor } = &reg {
                    if n != "3" || order != APP_ORDER || executor != "ABSENT" {
                        self.contract_problem(format!("application registry is not the production table: `{short}`"));
                    }
                }
                self.app_registry = Some(reg);
            }
            Some(f) if field(&f, "registry") == Some("REFUSED") && f.len() == 4 => {
                let diag = field(&f, "diag").unwrap_or("").to_string();
                self.app_registry = Some(AppReg::Refused {
                    diag: diag.clone(),
                    entry: field(&f, "entry").unwrap_or("").into(),
                    executor: field(&f, "executor").unwrap_or("").into(),
                });
                self.contract_problem(format!("application registry REFUSED at boot ({diag}); the production table is valid"));
            }
            _ => self.contract_problem(format!("malformed application registry line: `{short}`")),
        }
    }

    fn appinfo(&mut self, l: &str, short: &str) {
        const KEYS: [&str; 9] =
            ["id", "kind", "rev", "exec", "requires", "prerequisites", "unavailable", "observed_at_ms", "clock"];
        let f = match fields(l, "ABR|APPINFO|") {
            Some(f) if f.iter().map(|(k, _)| *k).eq(KEYS.iter().copied()) => f,
            _ => {
                self.contract_problem(format!("malformed APPINFO line: `{short}`"));
                self.expect = Expect::Nothing;
                return;
            }
        };
        let id = field(&f, "id").unwrap_or("");
        let pre = field(&f, "prerequisites").unwrap_or("");
        let un = field(&f, "unavailable").unwrap_or("");
        let at = field(&f, "observed_at_ms").unwrap_or("");
        let clock = field(&f, "clock").unwrap_or("");
        let entry = APP_TABLE.iter().find(|a| a.0 == id);
        let mut problems = Vec::new();
        match entry {
            None => problems.push(format!("APPINFO for an unknown application `{id}`")),
            Some(a) => {
                if (field(&f, "kind"), field(&f, "rev"), field(&f, "exec"), field(&f, "requires"))
                    != (Some(a.1), Some(a.2), Some(a.3), Some(a.4))
                {
                    problems.push(format!("APPINFO descriptor of {id} differs from the table"));
                }
                if let Some(round) = &self.latest {
                    let missing: Vec<String> = a
                        .4
                        .split(',')
                        .filter_map(|req| round.iter().find(|s| s.id == req))
                        .filter(|s| s.status != "AVAILABLE")
                        .map(|s| format!("{}:{}:{}", s.id, s.status, s.reason))
                        .collect();
                    let want = if missing.is_empty() { ("SATISFIED".to_string(), "NONE".to_string()) } else { ("UNSATISFIED".to_string(), missing.join(",")) };
                    if (pre, un) != (want.0.as_str(), want.1.as_str()) {
                        problems.push(format!(
                            "{id} says prerequisites={pre} unavailable={un}, but the status round says {}/{}",
                            want.0, want.1
                        ));
                    }
                    // A round's APPINFO carries the round's time and clock (C13). A discovery answer is a fresh
                    // observation; like launch_probe, only its prerequisites are compared with the latest round.
                    let in_round = matches!(self.expect, Expect::Round { .. });
                    if in_round && (at != round[0].at || clock != round[1].clock) {
                        problems.push(format!("{id} APPINFO time/clock {at}/{clock} is not its round's {}/{}", round[0].at, round[1].clock));
                    }
                } else {
                    problems.push(format!("APPINFO for {id} before any status round"));
                }
            }
        }
        match std::mem::replace(&mut self.expect, Expect::Nothing) {
            Expect::Round { next, ok } => {
                let want = APP_TABLE[next].0;
                let mut ok = ok && problems.is_empty();
                if id != want {
                    problems.push(format!("status round {}: APPINFO {} where {want} was due", self.rounds, id));
                    ok = false;
                }
                if next + 1 < APP_TABLE.len() {
                    self.expect = Expect::Round { next: next + 1, ok };
                } else if ok {
                    self.appinfo_groups += 1;
                }
            }
            Expect::Query { ids, next } => {
                if ids.get(next).map(|s| s.as_str()) != Some(id) {
                    problems.push(format!("discovery answer: APPINFO {id} not requested"));
                }
                if next + 1 < ids.len() {
                    self.expect = Expect::Query { ids, next: next + 1 };
                }
            }
            Expect::Nothing => problems.push(format!("APPINFO outside a status round or discovery answer: `{short}`")),
        }
        for p in problems {
            self.contract_problem(p);
        }
        if let Some(slot) = self.latest_apps.iter_mut().find(|x| x.0 == id) {
            *slot = (id.to_string(), pre.to_string(), un.to_string());
        } else if entry.is_some() {
            self.latest_apps.push((id.to_string(), pre.to_string(), un.to_string()));
        }
    }

    fn launch_result(&mut self, l: &str, short: &str) {
        let f: Vec<(&str, &str)> = match fields(l, "ABR|LAUNCHRESULT|") {
            Some(f) => f,
            None => {
                self.contract_problem(format!("malformed launch result: `{short}`"));
                return;
            }
        };
        let keys: Vec<&str> = f.iter().map(|(k, _)| *k).collect();
        let mut want_keys: Vec<&str> = RESULT_FIELDS[..3].to_vec();
        if keys.contains(&"target_len") {
            want_keys.push("target_len");
        }
        want_keys.extend_from_slice(&RESULT_FIELDS[3..]);
        let g = |k: &str| field(&f, k).unwrap_or("").to_string();
        let mut bad = Vec::new();
        if keys != want_keys || (g("target") == "MALFORMED") != keys.contains(&"target_len") {
            bad.push("the line does not follow the launch-result grammar".to_string());
        }
        let trans = std::mem::take(&mut self.pending_transitions);
        let want_t: Vec<(&str, &str, &str)> = if g("state") == "NOT_EXECUTED" {
            vec![("1", "SUBMITTED", "VALIDATED"), ("2", "VALIDATED", "NOT_EXECUTED")]
        } else {
            vec![("1", "SUBMITTED", "REFUSED")]
        };
        let got_t: Vec<(&str, &str, &str)> = trans.iter().map(|(_, s, a, b)| (s.as_str(), a.as_str(), b.as_str())).collect();
        if got_t != want_t || trans.iter().any(|t| t.0 != g("req")) {
            bad.push(format!("its transitions {:?} are not {:?} right before it", got_t, want_t));
        }
        // The facts agree with the latest status round (launch_probe facts_match_round).
        if g("known") == "YES" {
            let target = g("target");
            if let (Some(a), Some(round)) = (APP_TABLE.iter().find(|a| a.0 == target), &self.latest) {
                let missing: Vec<String> = a
                    .4
                    .split(',')
                    .filter_map(|r| round.iter().find(|s| s.id == r))
                    .filter(|s| s.status != "AVAILABLE")
                    .map(|s| format!("{}:{}:{}", s.id, s.status, s.reason))
                    .collect();
                let want = if missing.is_empty() {
                    ("SATISFIED".to_string(), "NONE".to_string())
                } else {
                    ("UNSATISFIED".to_string(), missing.join(","))
                };
                if (g("prerequisites"), g("unavailable")) != want {
                    bad.push(format!(
                        "prerequisites {}/{} disagree with the status round ({}/{})",
                        g("prerequisites"),
                        g("unavailable"),
                        want.0,
                        want.1
                    ));
                }
            }
        }
        // The fact rules every result obeys (launch_probe fact_rules_ok, without its Appendix A list: the design
        // comparison below fixes every reason of the pinned build).
        let late_ok = g("state") == "NOT_EXECUTED"
            && g("stage") == "AUTHORIZATION"
            && g("known") == "YES"
            && g("structure") == "WELL_FORMED"
            && g("admission") == "FRESH"
            && matches!(g("class").as_str(), "MUTATE" | "INSPECT_PROTECTED")
            && g("authorization") == if g("capability") == "PRESENTED" { "NO_AUTHORITY" } else { "CAP_MISSING" };
        let early_ok = g("state") == "REFUSED" && EARLY_STAGES.contains(&g("stage").as_str());
        let unknown_ok = g("known") == "YES"
            || (g("prerequisites") == "NOT_EVALUATED"
                && g("unavailable") == "NOT_EVALUATED"
                && g("support") == "NOT_EVALUATED"
                && g("authorization") == "NOT_EVALUATED");
        let pre_ok = (g("prerequisites") == "SATISFIED") == (g("unavailable") == "NONE")
            && (g("prerequisites") == "NOT_EVALUATED") == (g("unavailable") == "NOT_EVALUATED");
        let diag = g("diag");
        let reason_ok = DIAG_REASON.iter().find(|(d, _)| *d == diag).map(|(_, r)| *r == g("reason")).unwrap_or(true)
            && (!diag.starts_with("LAUNCH_PARSE_") || g("reason") == "PARSE_ERROR");
        let stage_reason = match g("stage").as_str() {
            "ADMISSION" => Some("REQUEST_REPLAYED"),
            "STRUCTURE" => Some("PARSE_ERROR"),
            "OPERATION" => Some("OPERATION_UNKNOWN"),
            "RECOGNITION" => Some("TARGET_UNKNOWN"),
            _ => None,
        };
        let stage_reason_ok = stage_reason.map(|r| r == g("reason")).unwrap_or(true);
        let fixed_ok = [g("executed"), g("process"), g("result"), g("verification"), g("boundary")]
            == ["NO", "NONE", "NOT_EXECUTED", "NOT_APPLICABLE", "COOPERATIVE"];
        let admission_ok = (g("stage") == "ADMISSION") == (g("admission") == "NOT_INCREASING")
            && (g("admission") == "FRESH" || g("structure") == "NOT_EVALUATED");
        let gate_order_ok =
            !matches!(g("stage").as_str(), "ADMISSION" | "STRUCTURE" | "OPERATION") || g("known") == "NOT_EVALUATED";
        if !((early_ok || late_ok) && unknown_ok && pre_ok && reason_ok && stage_reason_ok && fixed_ok && admission_ok && gate_order_ok) {
            bad.push("it breaks the launch-result fact rules".to_string());
        }
        let row = LaunchRow {
            req: g("req"),
            op: g("op"),
            target: g("target"),
            state: g("state"),
            stage: g("stage"),
            reason: g("reason"),
            diag: g("diag"),
            prerequisites: g("prerequisites"),
            authorization: g("authorization"),
        };
        if g("executed") != "NO" || g("process") != "NONE" || g("result") != "NOT_EXECUTED" {
            bad.push("executed/process/result not NO/NONE/NOT_EXECUTED".to_string());
        }
        match row.state.as_str() {
            "NOT_EXECUTED" => {
                if row.stage != "AUTHORIZATION" || g("known") != "YES" || g("structure") != "WELL_FORMED" {
                    bad.push("NOT_EXECUTED but not validated and stopped at AUTHORIZATION".into());
                }
                if !matches!(row.authorization.as_str(), "CAP_MISSING" | "NO_AUTHORITY") {
                    bad.push(format!("authorization {} (0.33 has no authority: CAP_MISSING or NO_AUTHORITY)", row.authorization));
                }
            }
            "REFUSED" => {
                if !EARLY_STAGES.contains(&row.stage.as_str()) {
                    bad.push(format!("REFUSED at stage {} (must be an early gate)", row.stage));
                }
                if g("authorization") != "NOT_EVALUATED" {
                    bad.push("REFUSED but authorization evaluated".into());
                }
            }
            s => bad.push(format!("state {s} (only REFUSED or NOT_EXECUTED exist in 0.33)")),
        }
        for b in bad {
            self.contract_problem(format!("request {}: {b}", row.req));
        }
        if self.build == Build::Launchpad {
            let req = row.req.clone();
            self.script_step("result", &req, &f);
        }
        self.rows.push(row);
    }

    /// The KERNEL BOOT status. `elapsed` is seconds since the VM was resumed, `qemu_gone` says QEMU has exited.
    pub fn boot(&self, elapsed: f64, timeout: f64, qemu_gone: bool) -> Boot {
        if let Some(f) = self.faults.first().filter(|_| self.fault_before_operational) {
            return Boot::Failed(format!("{} (before OPERATIONAL; the kernel halted)", f));
        }
        if let Some(r) = &self.init_failed {
            if self.operational_at.is_none() {
                return Boot::Failed(format!("initialization FAILED, reason {r}"));
            }
        }
        if self.firmware_shell && self.entries == 0 {
            return Boot::Failed("the firmware found no boot loader and started its built-in shell".into());
        }
        if let Some(at) = self.operational_at {
            if at > timeout {
                return Boot::Failed(format!(
                    "OPERATIONAL reached only {at:.1} s after the VM was resumed, beyond the {timeout:.0} s limit"
                ));
            }
            return Boot::Operational;
        }
        if qemu_gone {
            return Boot::Failed("QEMU exited before the kernel reached OPERATIONAL".into());
        }
        if self.entries > 1 {
            return Boot::Failed("the guest was reset before OPERATIONAL".into());
        }
        if elapsed > timeout {
            return Boot::Failed(format!("OPERATIONAL not reached within {timeout:.0} s"));
        }
        if self.entries > 0 {
            Boot::KernelEntered
        } else if self.firmware_boot.is_some() {
            Boot::LoaderStarted
        } else {
            Boot::WaitingForFirmware
        }
    }

    /// The early-fail build's designed outcome: one injected fault before OPERATIONAL, never OPERATIONAL.
    pub fn early_fail_as_designed(&self) -> bool {
        self.operational_at.is_none()
            && self.faults.len() == 1
            && self.fault_before_operational
            && self.faults[0].contains("|reason=TIMER_UNAVAILABLE|")
            && self.faults[0].contains("|detail=DIAG_INJECTED_EARLY_INIT_FAILURE|")
    }

    /// Final boot checks, by name. Each is true when it holds.
    pub fn boot_checks(&self, heartbeat_alive: bool) -> Vec<(&'static str, bool)> {
        let loader_ok = matches!(&self.loader, Some((n, true)) if n.starts_with("Limine"));
        if self.build == Build::EarlyFail {
            return vec![
                ("firmware_started_the_loader_from_the_boot_disk", self.firmware_boot.is_some()),
                ("kernel_entered_once", self.entries == 1),
                ("never_operational", self.operational_at.is_none()),
                ("exactly_one_fault_the_injected_one", self.early_fail_as_designed()),
            ];
        }
        vec![
            ("firmware_started_the_loader_from_the_boot_disk", self.firmware_boot.is_some()),
            ("kernel_entered_once", self.entries == 1),
            ("rust_kmain_entered", self.kmain),
            ("loader_limine_base_revision_supported", loader_ok),
            ("banner_version_is_the_pinned_version", self.banner_version.as_deref() == Some(self.version) && self.human_banner),
            ("operational", self.operational_at.is_some()),
            ("no_fault", self.faults.is_empty()),
            ("no_guest_reset_or_repeated_state", self.boot_problems.is_empty()),
            ("heartbeat_continuous_except_pauses_the_kernel_reported", self.ticks >= 1 && self.ticks_continuous),
            ("heartbeat_alive_until_shutdown", heartbeat_alive),
        ]
    }

    /// One sentence on the clock gaps the kernel reported and the clock, when there is anything to say (F-VML-01).
    pub fn clock_summary(&self) -> Option<String> {
        if self.clock_gaps.is_empty() && self.clock_degraded.is_none() {
            return None;
        }
        let mut parts = Vec::new();
        if !self.clock_gaps.is_empty() {
            let p: Vec<String> = self
                .clock_gaps
                .iter()
                .map(|(a, b, n)| format!("heartbeat {a} -> {b}, {n} s skipped"))
                .collect();
            parts.push(format!(
                "{} clock gap{} the kernel reported itself ({})",
                self.clock_gaps.len(),
                if self.clock_gaps.len() == 1 { "" } else { "s" },
                p.join("; ")
            ));
        }
        if let Some(r) = &self.clock_degraded {
            parts.push(format!("clock DEGRADED ({r}) from then on, so later observations are stale, by design"));
        }
        Some(parts.join("; "))
    }

    /// The service findings that count: every service problem, and C12's progress and spacing findings unless the
    /// clock became DEGRADED (F-VML-03).
    pub fn counted_service_problems(&self) -> Vec<String> {
        let mut v = self.service_problems.clone();
        if self.clock_degraded.is_none() {
            v.extend(self.c12_pair_problems.iter().cloned());
        }
        v
    }

    pub fn service_checks(&self) -> Vec<(&'static str, bool)> {
        if self.build == Build::EarlyFail {
            return vec![];
        }
        vec![
            ("service_registry_is_the_production_table", self.svc_registry.as_deref() == Some("dev.net0,svc.counter,svc.netmon")),
            ("status_rounds_seen", self.rounds >= 1),
            ("services_as_designed_every_round", self.rounds >= 1 && self.counted_service_problems().is_empty()),
        ]
    }

    /// The LAUNCHER CONTRACT verdict. `finished` means the capture has ended (the VM has stopped).
    pub fn contract(&self, finished: bool, boot_failed: bool) -> Verdict {
        if let Some(c) = self.claims.first() {
            return Verdict::Inconsistent(format!("a line claims execution: `{}`", c.chars().take(100).collect::<String>()));
        }
        if let Some(p) = self.contract_problems.first() {
            return Verdict::Inconsistent(p.clone());
        }
        if self.build == Build::EarlyFail {
            if self.operational_at.is_some() {
                return Verdict::Inconsistent("this DIAGNOSTIC build must stop before OPERATIONAL".into());
            }
            return Verdict::NotReached(
                "the kernel stopped before OPERATIONAL, so this boot has no application registry (the designed outcome of this DIAGNOSTIC build)"
                    .into(),
            );
        }
        if self.operational_at.is_none() {
            return if boot_failed || finished {
                Verdict::NotReached("the kernel did not reach OPERATIONAL, so the application registry was never started".into())
            } else {
                Verdict::Waiting("waiting for the kernel to reach OPERATIONAL".into())
            };
        }
        if self.app_registry.is_none() {
            return if finished {
                Verdict::Inconsistent("no application registry line before the end of capture".into())
            } else {
                Verdict::Waiting("waiting for the application registry".into())
            };
        }
        if self.appinfo_groups == 0 {
            return if finished {
                Verdict::Inconsistent("no complete status round with its APPINFO lines".into())
            } else {
                Verdict::Waiting("waiting for the first status round".into())
            };
        }
        let base = format!(
            "registry OK (3 applications, executor ABSENT); {} status round{} each with its 3 APPINFO lines, prerequisites matching the services; nothing executed",
            self.appinfo_groups,
            if self.appinfo_groups == 1 { "" } else { "s" }
        );
        match self.build {
            Build::Production => Verdict::Consistent(format!("{base}; no launch request (the production build makes none)")),
            Build::Launchpad => {
                let answered = self.rows.len() + self.appqueries as usize + self.routed as usize;
                if self.summary.is_none()
                    || !self.forced_refused
                    || self.state_after_forced.is_none()
                    || self.routed_answer.is_none()
                    || self.script_pos != 17
                    || !self.inject_seen
                {
                    let what = format!("{answered} of 17 requests answered");
                    return if finished {
                        Verdict::Inconsistent(format!("the launcher script did not complete before the VM stopped ({what})"))
                    } else {
                        Verdict::InProgress(what)
                    };
                }
                let refused = self.rows.iter().filter(|r| r.state == "REFUSED").count();
                let not_exec = self.rows.iter().filter(|r| r.state == "NOT_EXECUTED").count();
                Verdict::Consistent(format!(
                    "17 requests: {refused} refused, {not_exec} validated then NOT EXECUTED, {} discovery, {} routed to services (answered CAP_MISSING); executed=0, processes=0, executor ABSENT; the forced RUNNING transition was refused and the state stayed NOT_EXECUTED. {base}",
                    self.appqueries, self.routed
                ))
            }
            Build::EarlyFail => unreachable!(),
        }
    }

    /// One plain-English line for a launch result (as the 0.33 VM viewer prints it).
    pub fn explain(row: &LaunchRow) -> String {
        let why = match row.diag.as_str() {
            "LAUNCH_ID_NOT_INCREASING" => "its request number is not greater than the last one (ordering, not authentication)",
            "LAUNCH_OPERATION_UNKNOWN" => "the operation word is not one Abraham knows for applications",
            "LAUNCH_TARGET_UNKNOWN" => "no application of exactly that name is in the registry",
            "LAUNCH_REGISTRY_REFUSED" => "the application registry was refused at boot",
            "LAUNCH_CAP_MISSING" => "a privileged request with no capability (none can exist yet)",
            "LAUNCH_NO_AUTHORITY" => "a capability was named, but no authority mechanism exists",
            d if d.starts_with("LAUNCH_PARSE_") => "the text does not follow the request grammar",
            d => d,
        };
        let extra = match row.prerequisites.as_str() {
            "UNSATISFIED" => "; its prerequisites are also unmet",
            "SATISFIED" => "; prerequisites met, but nothing can execute in 0.33",
            _ => "",
        };
        let head = if row.state == "REFUSED" {
            format!("REFUSED at {}", row.stage)
        } else {
            format!("validated, then NOT EXECUTED at {}", row.stage)
        };
        format!("= request {} ({} {}): {head}: {why}{extra}.", row.req, row.op, row.target)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn clean_matches_the_harness() {
        assert_eq!(clean(b"\x1b[2J\x1b[01;01HBdsDxe: loading\r"), "BdsDxe: loading");
        assert_eq!(clean(b"\r\nABR|ENTRY|abr_entry reached (NASM)  "), "ABR|ENTRY|abr_entry reached (NASM)");
        assert_eq!(clean(b"a\x1b]0;x"), "a\u{1b}]0;x");
        assert_eq!(printable("a\u{1b}[31mb"), "a.[31mb");
    }

    #[test]
    fn assembler_keeps_partial_lines() {
        let mut a = LineAssembler::default();
        assert_eq!(a.push(b"ABR|ST"), Vec::<String>::new());
        assert_eq!(a.push(b"ATE|OPERATIONAL\r\nABR|TI"), vec!["ABR|STATE|OPERATIONAL".to_string()]);
        assert_eq!(a.flush(), Some("ABR|TI".to_string()));
    }

    #[test]
    fn execution_claim_rule() {
        assert!(!is_execution_claim("ABR|LAUNCHRESULT|req=1|executed=NO|process=NONE|state=NOT_EXECUTED"));
        assert!(is_execution_claim("ABR|LAUNCHRESULT|req=1|executed=YES|process=NONE"));
        assert!(is_execution_claim("ABR|LAUNCHRESULT|req=1|executed=NO|process=7"));
        assert!(is_execution_claim("ABR|LAUNCHPAD|requests=17|executed=1|processes=0|executor=ABSENT"));
        assert!(is_execution_claim("ABR|APP|registry=OK|entries=3|order=x|executor=PRESENT"));
        assert!(is_execution_claim("ABR|LAUNCH|req=1|seq=3|from=NOT_EXECUTED|to=RUNNING"));
        assert!(!is_execution_claim(FORCED_REFUSED));
        assert!(is_execution_claim("ABR|APPINFO|id=app.x|kind=VIEWER|rev=1|exec=NATIVE"));
    }

    fn home() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
    }

    fn judge_file(path: PathBuf, build: Build) -> Observer {
        let bytes = std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
        let mut a = LineAssembler::default();
        let mut o = Observer::new(build, "0.33.0-dev");
        for (i, l) in a.push(&bytes).into_iter().enumerate() {
            o.feed(&l, i as f64 * 0.01);
        }
        o.end_of_capture(a.flush());
        o
    }

    #[test]
    fn sealed_production_log_is_consistent() {
        let o = judge_file(home().join(r"work-0.33\evidence\ABR-BOOT-001\ABR-0.33-W001\serial.log"), Build::Production);
        assert_eq!(o.boot(10.0, 120.0, false), Boot::Operational);
        assert!(o.boot_checks(true).iter().all(|c| c.1), "{:?}", o.boot_checks(true));
        assert!(o.service_checks().iter().all(|c| c.1), "{:?}", o.service_problems);
        let v = o.contract(true, false);
        assert!(matches!(v, Verdict::Consistent(_)), "{v:?}");
    }

    #[test]
    fn sealed_launchpad_log_is_consistent() {
        let o = judge_file(home().join(r"work-0.33\evidence\g033\ABR-0.33-L001\serial.log"), Build::Launchpad);
        let v = o.contract(true, false);
        assert!(matches!(v, Verdict::Consistent(_)), "{v:?} {:?}", o.contract_problems);
        assert_eq!(o.rows.len(), 15);
        // The same log is not a production log: its launch lines are refused under that build.
        let p = judge_file(home().join(r"work-0.33\evidence\g033\ABR-0.33-L001\serial.log"), Build::Production);
        assert!(matches!(p.contract(true, false), Verdict::Inconsistent(_)));
    }

    #[test]
    fn sealed_early_fail_log_is_a_designed_failure() {
        let o = judge_file(home().join(r"work-0.33\evidence\g6\ABR-0.33-F005\serial.log"), Build::EarlyFail);
        assert!(matches!(o.boot(10.0, 120.0, false), Boot::Failed(_)));
        assert!(o.early_fail_as_designed());
        assert!(matches!(o.contract(true, true), Verdict::NotReached(_)));
        // The same log under the production expectation: a failed boot, and the contract never reached.
        let p = judge_file(home().join(r"work-0.33\evidence\g6\ABR-0.33-F005\serial.log"), Build::Production);
        assert!(matches!(p.boot(10.0, 120.0, false), Boot::Failed(_)));
        assert!(matches!(p.contract(true, true), Verdict::NotReached(_)));
    }

    fn feed_all(build: Build, lines: &[String]) -> Observer {
        let mut o = Observer::new(build, "0.33.0-dev");
        for (i, l) in lines.iter().enumerate() {
            o.feed(l, i as f64);
        }
        o.end_of_capture(None);
        o
    }

    fn w001_lines() -> Vec<String> {
        let bytes = std::fs::read(home().join(r"work-0.33\evidence\ABR-BOOT-001\ABR-0.33-W001\serial.log")).unwrap();
        let mut a = LineAssembler::default();
        a.push(&bytes)
    }

    #[test]
    fn falsified_production_logs_are_inconsistent() {
        let base = w001_lines();
        let cases: Vec<(&str, Box<dyn Fn(&mut Vec<String>)>)> = vec![
            ("satisfied on an unavailable service", Box::new(|v: &mut Vec<String>| {
                let i = v.iter().position(|l| l.starts_with("ABR|APPINFO|id=app.netstatus")).unwrap();
                v[i] = v[i].replace("prerequisites=UNSATISFIED|unavailable=svc.netmon:UNAVAILABLE:NOT_INSTALLED", "prerequisites=SATISFIED|unavailable=NONE");
            })),
            ("missing APPINFO group", Box::new(|v: &mut Vec<String>| {
                let i = v.iter().rposition(|l| l.starts_with("ABR|APPINFO|id=app.browser")).unwrap();
                let j = v.iter().take(i).rposition(|l| l.starts_with("ABR|APPINFO|id=app.counterview")).unwrap();
                if v.iter().skip(i + 1).any(|l| l.starts_with("ABR|")) { v.drain(j..=i); } else {
                    let k = v.iter().take(j).rposition(|l| l.starts_with("ABR|APPINFO|id=app.browser")).unwrap();
                    let m = v.iter().take(k).rposition(|l| l.starts_with("ABR|APPINFO|id=app.counterview")).unwrap();
                    v.drain(m..=k);
                }
            })),
            ("execution claimed", Box::new(|v: &mut Vec<String>| {
                let i = v.iter().position(|l| l.starts_with("ABR|APPINFO|")).unwrap();
                v[i] = v[i].replace("exec=NONE", "exec=NATIVE");
            })),
            ("a launch line in production", Box::new(|v: &mut Vec<String>| {
                let i = v.iter().position(|l| l.starts_with("ABR|TICK|")).unwrap();
                v.insert(i, "ABR|LAUNCH|req=1|seq=1|from=SUBMITTED|to=VALIDATED".into());
            })),
            ("wrong APPINFO time", Box::new(|v: &mut Vec<String>| {
                let i = v.iter().rposition(|l| l.starts_with("ABR|APPINFO|id=app.browser")).unwrap();
                let t = v[i].split("observed_at_ms=").nth(1).unwrap().split('|').next().unwrap().to_string();
                v[i] = v[i].replace(&format!("observed_at_ms={t}"), "observed_at_ms=1");
            })),
            ("registry refused", Box::new(|v: &mut Vec<String>| {
                let i = v.iter().position(|l| l.starts_with("ABR|APP|registry=")).unwrap();
                v[i] = "ABR|APP|registry=REFUSED|diag=APP_DUPLICATE_ID|entry=2|executor=ABSENT".into();
            })),
        ];
        for (name, f) in cases {
            let mut v = base.clone();
            f(&mut v);
            let o = feed_all(Build::Production, &v);
            assert!(matches!(o.contract(true, false), Verdict::Inconsistent(_)), "{name}: {:?}", o.contract(true, false));
        }
        // And the unmodified log stays consistent through the same path.
        assert!(matches!(feed_all(Build::Production, &base).contract(true, false), Verdict::Consistent(_)));
    }

    #[test]
    fn boot_failures_are_named() {
        let mut o = Observer::new(Build::Production, "0.33.0-dev");
        assert_eq!(o.boot(1.0, 120.0, false), Boot::WaitingForFirmware);
        assert!(matches!(o.boot(1.0, 120.0, true), Boot::Failed(_)));
        assert!(matches!(o.boot(121.0, 120.0, false), Boot::Failed(_)));
        o.feed("BdsDxe: starting Boot0001 \"UEFI Misc Device\" from PciRoot(0x0)/Pci(0x1,0x0)", 1.0);
        assert_eq!(o.boot(1.0, 120.0, false), Boot::LoaderStarted);
        o.feed(ENTRY, 2.0);
        assert_eq!(o.boot(2.0, 120.0, false), Boot::KernelEntered);
        o.feed(OPERATIONAL, 3.0);
        assert_eq!(o.boot(3.0, 120.0, true), Boot::Operational);
        assert!(matches!(o.boot(3.0, 2.0, true), Boot::Failed(_))); // reached, but after the limit
        assert!(o.boot_checks(true).iter().any(|c| !c.1)); // no banner, no ticks: not a PASS
    }

    // ---- F-VML-01 (0.33.1): a clock gap the kernel reported (a real standby), and a DEGRADED clock -----------

    fn standby_lines() -> Vec<String> {
        // Jadin's own launch across a real Modern Standby (TR-0045), sealed in vmlauncher-0.33\runs.
        let p = home().join(r"vmlauncher-0.33\runs\VML-20261109T201841Z\serial.log");
        let bytes = std::fs::read(&p).unwrap_or_else(|e| panic!("{}: {e}", p.display()));
        let mut a = LineAssembler::default();
        a.push(&bytes)
    }

    fn all(v: &[(&'static str, bool)]) -> bool {
        v.iter().all(|c| c.1)
    }

    #[test]
    fn the_real_standby_run_is_a_reported_pause_not_a_boot_failure() {
        let o = feed_all(Build::Production, &standby_lines());
        assert_eq!(o.boot(10.0, 120.0, true), Boot::Operational);
        assert_eq!(o.clock_gaps, vec![(3318, 3570, 251)]);
        assert!(o.unexplained_gaps.is_empty());
        assert_eq!(o.clock_degraded.as_deref(), Some("TSC_FORWARD_JUMP"));
        assert!(all(&o.boot_checks(true)), "{:?} {:?}", o.boot_checks(true), o.boot_problems);
        assert!(all(&o.service_checks()), "{:?}", o.service_problems);
        assert!(matches!(o.contract(true, false), Verdict::Consistent(_)), "{:?}", o.contract_problems);
        assert!(o.clock_summary().unwrap().contains("251 s skipped"));
    }

    #[test]
    fn falsified_standby_logs_are_still_caught() {
        let base = standby_lines();
        let gap = base.iter().position(|l| l.starts_with("ABR|CLOCK|anomaly=HEARTBEAT_GAP")).unwrap();
        let jump = base.iter().position(|l| l.starts_with("ABR|CLOCK|anomaly=TSC_FORWARD_JUMP")).unwrap();
        let deg = base.iter().position(|l| l.starts_with("ABR|CLOCK|state=DEGRADED")).unwrap();
        let degraded_counter = base.iter().skip(deg).position(|l| l.starts_with("ABR|SVCSTATUS|id=svc.counter")).unwrap() + deg;
        let degraded_appinfo = base.iter().skip(deg).position(|l| l.starts_with("ABR|APPINFO|id=app.counterview")).unwrap() + deg;
        type Case = (&'static str, Box<dyn Fn(&mut Vec<String>)>, &'static str);
        let cases: Vec<Case> = vec![
            ("the gap is not reported by the kernel", Box::new(move |v: &mut Vec<String>| { v.remove(gap); }), "boot"),
            ("a gap without the forward jump", Box::new(move |v: &mut Vec<String>| { v.remove(jump); }), "boot"),
            ("a gap report that does not match the heartbeat", Box::new(move |v: &mut Vec<String>| {
                v[gap] = "ABR|CLOCK|anomaly=HEARTBEAT_GAP|from_s=3318|to_s=3500|skipped=181".into();
            }), "boot"),
            ("DEGRADED rounds without the kernel's DEGRADED report", Box::new(move |v: &mut Vec<String>| { v.remove(deg); }), "services"),
            ("a stale counter claimed AVAILABLE", Box::new(move |v: &mut Vec<String>| {
                v[degraded_counter] = v[degraded_counter].replace("status=UNKNOWN|reason=OBSERVATION_STALE|liveness=UNKNOWN", "status=AVAILABLE|reason=NONE|liveness=LIVE");
            }), "services"),
            ("the latch broken: a later round says clock=OK", Box::new(move |v: &mut Vec<String>| {
                let i = v.iter().rposition(|l| l.starts_with("ABR|SVCSTATUS|id=svc.counter")).unwrap();
                v[i] = v[i].replace("status=UNKNOWN|reason=OBSERVATION_STALE|liveness=UNKNOWN", "status=AVAILABLE|reason=NONE|liveness=LIVE").replace("clock=DEGRADED", "clock=OK");
            }), "services"),
            ("counterview SATISFIED on stale data", Box::new(move |v: &mut Vec<String>| {
                v[degraded_appinfo] = v[degraded_appinfo].replace("prerequisites=UNSATISFIED|unavailable=svc.counter:UNKNOWN:OBSERVATION_STALE", "prerequisites=SATISFIED|unavailable=NONE");
            }), "contract"),
        ];
        for (name, f, part) in cases {
            let mut v = base.clone();
            f(&mut v);
            let o = feed_all(Build::Production, &v);
            let caught = match part {
                "boot" => !all(&o.boot_checks(true)),
                "services" => !all(&o.service_checks()),
                _ => matches!(o.contract(true, false), Verdict::Inconsistent(_)),
            };
            assert!(caught, "not caught: {name}");
        }
    }

    #[test]
    fn an_unreported_heartbeat_gap_is_still_a_boot_problem() {
        let mut v: Vec<String> = w001_lines();
        let i = v.iter().position(|l| l.starts_with("ABR|TICK|uptime_s=5|")).unwrap();
        v.remove(i);
        let o = feed_all(Build::Production, &v);
        assert_eq!(o.unexplained_gaps, vec![(4, 6)]);
        assert!(!all(&o.boot_checks(true)));
        assert!(o.clock_gaps.is_empty());
    }

    // ---- F-VML-02 (0.33.1): C12's counter progress and timing, on rounds with the clock OK ---------------------

    #[test]
    fn c12_counter_rules_catch_a_short_undetected_freeze() {
        let base = w001_lines();
        let counters: Vec<usize> =
            base.iter().enumerate().filter(|(_, l)| l.starts_with("ABR|SVCSTATUS|id=svc.counter")).map(|(i, _)| i).collect();
        let k = counters[2]; // the third round
        let set = move |v: &mut Vec<String>, from: &str, to: &str| {
            v[k] = v[k].replace(from, to);
        };
        let value = base[k].split("|value=").nth(1).unwrap().split('|').next().unwrap().parse::<u64>().unwrap();
        let prev = base[counters[1]].split("|value=").nth(1).unwrap().split('|').next().unwrap().parse::<u64>().unwrap();
        let low = prev + 200;
        type Case = (&'static str, Box<dyn Fn(&mut Vec<String>)>);
        let cases: Vec<Case> = vec![
            ("only 200 steps in a round (a short freeze)", Box::new(move |v: &mut Vec<String>| {
                set(v, &format!("value={value}|steps={}", value - 1), &format!("value={low}|steps={}", low - 1));
            })),
            ("value is not steps + 1", Box::new(move |v: &mut Vec<String>| {
                set(v, &format!("|steps={}|", value - 1), &format!("|steps={}|", value - 5));
            })),
            ("an overrun while AVAILABLE", Box::new(move |v: &mut Vec<String>| { set(v, "|overruns=0", "|overruns=1"); })),
        ];
        for (name, f) in cases {
            let mut v = base.clone();
            f(&mut v);
            let o = feed_all(Build::Production, &v);
            assert!(!all(&o.service_checks()), "not caught: {name}");
        }
        // 0.33.2 (dry-run finding): the record, the panel and the offline check report the COUNTED list, which must
        // hold the pair finding while the clock never degraded.
        let mut v = base.clone();
        set(&mut v, &format!("value={value}|steps={}", value - 1), &format!("value={low}|steps={}", low - 1));
        let o = feed_all(Build::Production, &v);
        assert!(o.counted_service_problems().iter().any(|p| p.contains("at least 250")), "{:?}", o.counted_service_problems());
        // A round 6 s after the previous one breaks the 5,000-5,500 ms spacing.
        let mut v = base.clone();
        let round = |i: usize| base[i].split("observed_at_ms=").nth(1).unwrap().split('|').next().unwrap().to_string();
        let t2 = round(counters[2] - 1);
        let shifted = (t2.parse::<u64>().unwrap() + 1000).to_string();
        for i in counters[2] - 1..=counters[2] + 4 {
            v[i] = v[i].replace(&format!("observed_at_ms={t2}"), &format!("observed_at_ms={shifted}"));
        }
        let o = feed_all(Build::Production, &v);
        assert!(!all(&o.service_checks()), "not caught: rounds 6 s apart");
        // The genuine logs still pass the stricter rules.
        assert!(all(&feed_all(Build::Production, &base).service_checks()));
        assert!(all(&feed_all(Build::Production, &standby_lines()).service_checks()));
    }

    // ---- 0.33.2 (D-ABR-026 3A, F-VML-03): a guest-side jump, as the diag-tsc-jump build injects it ------------

    fn log_lines(rel: &str) -> Vec<String> {
        let p = home().join(rel);
        let bytes = std::fs::read(&p).unwrap_or_else(|e| panic!("{}: {e}", p.display()));
        let mut a = LineAssembler::default();
        a.push(&bytes)
    }

    #[test]
    fn a_guest_side_jump_is_a_clock_gap_not_a_host_pause_and_c12_pairs_do_not_count_after_degradation() {
        for run in ["ABR-0.33-O003", "ABR-0.33-O004"] {
            let o = feed_all(Build::Production, &log_lines(&format!(r"work-0.33\evidence\g031b\{run}\serial.log")));
            assert_eq!(o.clock_gaps, vec![(3, 3603, 3599)], "{run}");
            assert_eq!(o.clock_degraded.as_deref(), Some("TSC_FORWARD_JUMP"));
            // The round that straddles the jump still says clock=OK (the guard reports it 36 ms later): C12's
            // spacing finding is recorded, but does not count once the clock is DEGRADED.
            assert!(!o.c12_pair_problems.is_empty(), "{run}");
            assert!(all(&o.service_checks()), "{run}: {:?}", o.counted_service_problems());
            assert!(all(&o.boot_checks(true)), "{run}");
            assert!(matches!(o.contract(true, false), Verdict::Consistent(_)), "{run}");
            let s = o.clock_summary().unwrap();
            assert!(s.contains("clock gap") && !s.contains("host pause"), "{s}");
        }
        // On a run whose clock stayed OK, the same pair findings still count (F-VML-02 kept).
        let mut v = w001_lines();
        let i = v.iter().enumerate().filter(|(_, l)| l.starts_with("ABR|SVCSTATUS|id=svc.counter")).map(|(i, _)| i).nth(2).unwrap();
        let val = v[i].split("|value=").nth(1).unwrap().split('|').next().unwrap().parse::<u64>().unwrap();
        v[i] = v[i].replace(&format!("value={val}|steps={}", val - 1), &format!("value={}|steps={}", val - 300, val - 301));
        let o = feed_all(Build::Production, &v);
        assert!(!all(&o.service_checks()));
    }
}
