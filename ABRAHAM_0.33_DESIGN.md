# ABRAHAM 0.33 design checkpoint: application registry and launcher contract

- 2026-11-08. MOSKO Laboratory 001 - Pripyat. Directive `MOSKO_ABRAHAM_033_PREPARATION_DIRECTIVE_2026-11-08.md`
  (Jadin, 2026-11-08), recorded as D-ABR-021. This is the **GATE 1 owner design review**.
- **Status: DESIGN FOR OWNER REVIEW. Nothing in this document is implemented.** No 0.33 tree exists. `work-0.33` is
  created only after 0.32b is accepted (directive Phase 0 item 8).
- Foundation: 0.32b, kernel 0.32.1-dev `81d4b4ec...`. 0.32b is **READY FOR AUDIT, not accepted**. Its acceptance gate
  verification is TR-0039. If Echo's audit changes 0.32b, this design is rebased on the corrected tree before coding.
- This file lives in the Abraham home because no 0.33 tree may exist yet. After approval it is copied unchanged into
  `work-0.33\docs\ABRAHAM_0.33_DESIGN.md`, and its digest is recorded.

**Rules this design must respect** (ratified in `ABRAHAM_0.2_BASELINE.md` or by owner decisions):
- P-09/P-30: authority decides, the kernel enforces, grants are revalidated at use.
- P-10: COOPERATIVE boundary only; no isolation is claimed.
- P-12: command grammar, exact names, no wildcards; the operation-to-class table is fixed in the core.
- P-13/P-33: INSPECT_PUBLIC is a closed allow list, changed only by reviewed code.
- P-15: public reasons only from Appendix A.
- P-17/P-46: no MUTATE runs without durable audit and INTENT/RESULT receipts.
- P-22: ExecutionReport vocabulary; never COMPLETED for an unobserved outcome; UNKNOWN when an outcome is lost.
- P-27: no deferred or queued privileged execution; no filesystem.
- P-35: no free text, payloads or sensitive data.
- P-41: liveness is separate from compromise.
- D-ABR-010/011: kernel diagnostic codes are separate from public reasons.
- D-ABR-012: memory invariants, re-verified in every sub-revision.
- D-ABR-019 + D-ABR-021: service execution policy, with the Phase 1 wording.

## 1. What 0.33 adds, in one paragraph

After the 0.32b service registry has started, the kernel validates a second compiled table: the **application
registry**, three descriptors in the proposal. It prints what it recognizes, together with each application's live
prerequisite state, and it gives a typed, bounded **launch request contract** that records five separate facts:
- is the request structurally valid?
- is the application known?
- are its prerequisites satisfied?
- is it authorized?
- did it execute?

In 0.33 the last two answers are always truthful negatives:
- no authorization mechanism exists, so a launch is refused (`CAP_MISSING`, or `AUTHZ_UNAVAILABLE` when a capability is
  named);
- no executor exists, so nothing executes: every request ends `result=NOT_EXECUTED`, `executed=NO`, `process=NONE`.

A DIAGNOSTIC build runs a fixed, compiled request script and prints every fact, so the operator can watch acceptance
for validation, every kind of refusal, the unavailable prerequisites, and the absence of execution. The launcher reads
service status and changes nothing. No application, request or registry entry grants authority.

## 2. Explicitly unimplemented in 0.33

| Not in 0.33 | Where it belongs | What 0.33 says instead |
|---|---|---|
| Any application execution, process, address space, ELF loading of applications, ring 3, syscalls, scheduler | 0.4 | `executed=NO`, `process=NONE`; the request states for execution exist only as **reserved** states (§5) |
| An authorization mechanism: authority adapter (LOCAL_SIMULATED is not built in Abraham), capability issuance, kernel-held grants, DecisionRecords, any Cyberforteca grant | 0.4 design or later | `authorization=CAP_MISSING` or `NO_AUTHORITY`; never AUTHORIZED; no DecisionRecord is written or implied |
| Audit record store, EnforcementReceipt INTENT/RESULT (P-17, P-46) | before any MUTATE executes | launch lines are serial diagnostics, never audit records |
| Interactive console input, a command interpreter | separately reviewed design | DIAGNOSTIC builds run a fixed compiled script only; the production kernel makes no requests |
| Framebuffer, graphics, the SOLOMON Classic, NIGHTRUNNER and TERMINAL 1990 shells, the browser engine | 0.34+ (§12) | shells will consume the same discovery data (§9) |
| Filesystem, package manager, installation, dynamic registration, manifests read from storage | not planned (P-27) | the registry is a compiled table, changed only by a reviewed code change |
| Stopping or terminating applications | 0.4 | no instance exists to stop; `stop app.*` is refused (`CAP_MISSING`) |
| Request queues, retries, deferral, persistence of requests | forbidden for 0.1 (P-27) | every request ends in a terminal state within the call that submitted it |
| Networking | P-19 revision | `dev.net0` stays NOT_INSTALLED |

## 3. Source modules and their responsibilities

New portable modules (no `unsafe`, no allocation, hosted-tested like `svc*.rs`):

| Module | Responsibility |
|---|---|
| `kernel/src/appregistry.rs` | `AppId`, `AppKind`, `ExecSupport`, `AppDesc`; `validate(apps, services)` as a `const fn` (compile time and again at boot); exact `lookup`; the `app.` name grammar |
| `kernel/src/apptable.rs` | the PRODUCTION application table and the DIAG tables; compile-time `assert_valid` against the 0.32b service table |
| `kernel/src/launchreq.rs` | bounded request text parser (a subset of the §4.4 grammar), the fixed operation-to-class table, `ParseFault` |
| `kernel/src/launchlife.rs` | request lifecycle: `RequestState`, the transition matrix (allowed / reserved / invalid), `ExecutionEvidence` (no constructor in 0.33) |
| `kernel/src/launch.rs` | the launcher: admission (request id), the five facts, `decide` (fixed precedence), `LaunchResult` (private fields), `AppInfo` discovery |

Kernel side:

| Module | Change |
|---|---|
| `kernel/src/launchpad.rs` (new) | prints `ABR|APP`, `ABR|APPINFO`, `ABR|LAUNCH`, `ABR|LAUNCHRESULT`, `ABR|LAUNCHPAD`; the DIAGNOSTIC request script (`diag-launchpad`) and the invalid-transition injection |
| `kernel/src/svcmgr.rs` | one read-only accessor that lends `&ServiceSet` to the launchpad; status rounds also print APPINFO |
| `kernel/src/main.rs` | one call after the service start; version 0.33.0-dev |
| `kernel/src/svcrun.rs` | **comments only**: the Phase 1 wording (§10). No behavior change |
| `docs/KERNEL_DIAGNOSTICS.md` | the new `APP_*` and `LAUNCH_*` diagnostic codes |
| `kernel/hosttest` | new tests (§11), the Phase 1 tests from the 0.32b gate, compile-fail checks |

Tools: `tools/g033/` holds the copy and start check, `launch_probe.py`, the judge self-test, the mutation check, the
static checks, the campaign, the index and the packaging. `tools/abr_boot_001.py` gains profile 0.33, which is C0-C12
plus a new C13 (launcher).

Unchanged: `svcregistry.rs`, `svclife.rs`, `svcstatus.rs` (and so the Appendix A mapping), memory, lifecycle, clock,
fault and event code, and `entry.asm`. No new event kind is added. The serial lines are the record.

## 4. Data structures and interface boundaries

### 4.1 Application descriptor (bounded, compiled)

```
pub struct AppId(pub u8);                         // its own type; never a ServiceId
pub enum AppKind { Viewer, Browser, Tool }        // a fixed enum, not free text
pub enum ExecSupport { None, Native }             // Native = an independent ring-3 image (0.4); refused in 0.33
pub const EXECUTOR: Executor = Executor::Absent;  // 0.33: no process loader exists
pub struct AppDesc {
    pub id: AppId,
    pub name: &'static str,                       // "app." + lowercase segments, at most 31 bytes
    pub kind: AppKind,
    pub revision: u16,                            // descriptor revision, bumped by a reviewed change
    pub requires: &'static [ServiceId],           // at most 4; each must exist in the 0.32b service table
    pub exec: ExecSupport,                        // the truthful execution statement
}
```

**Deliberately absent:**
- titles, descriptions, icons, paths and arguments: no free text (P-35); presentation belongs to the shells (§9);
- any capability, grant, privilege or authority field: recognition can never imply authority;
- any address, entry point or image: there is nothing to execute.

`validate(apps, services)` refuses the whole table, with one diagnostic code per fault, checked in this order:
- more than `MAX_APPS` = 8 entries (`APP_TOO_MANY_ENTRIES`);
- a malformed name: not `app.`, upper case, empty segment, wildcard, over 31 bytes (`APP_NAME_MALFORMED`);
- more than 4 requirements (`APP_TOO_MANY_REQUIREMENTS`);
- a duplicate id (`APP_DUPLICATE_ID`);
- a duplicate name (`APP_DUPLICATE_NAME`);
- a requirement that is not in the service table (`APP_UNKNOWN_REQUIREMENT`);
- a duplicate requirement (`APP_DUPLICATE_REQUIREMENT`);
- `exec=Native` while `EXECUTOR` is `Absent` (`APP_EXEC_CLAIM_UNSUPPORTED`): **no application can be advertised as
  executable**.

A refused registry has no entries. Every app target is then unknown, and the services are unaffected. `lookup`
compares exact bytes. Lookup order is the `AppId` number, never table position.

### 4.2 Proposed production table (Q1)

| AppId | Name | Kind | Requires | Exec | What 0.33 must report |
|---|---|---|---|---|---|
| 1 | `app.counterview` | VIEWER | `svc.counter` | NONE | known; prerequisites SATISFIED; not executable; launch NOT_EXECUTED |
| 2 | `app.netstatus` | VIEWER | `svc.netmon` | NONE | known; prerequisites UNSATISFIED (`svc.netmon` UNAVAILABLE / NOT_INSTALLED, root `dev.net0`); NOT_EXECUTED |
| 3 | `app.browser` | BROWSER | `svc.netmon` | NONE | known; UNSATISFIED; NOT_EXECUTED; the 0.34 research target |

These are placeholders in the same sense as `dev.net0`: honest descriptors of things that do not run yet. The browser
cannot declare a framebuffer requirement, because no framebuffer entry exists to depend on (§12).

### 4.3 Launch request (typed, bounded)

```
pub struct Request<'a> { pub request_id: u32, pub text: &'a [u8] }   // text at most 64 bytes, ASCII
// parsed form (launchreq.rs), never built by the caller:
pub struct Parsed<'a> { op: Op, class: OpClass, target: Target<'a>, capability: Option<&'a [u8]> }
```

- **Grammar subset** (P-12 §4.4): `operation SP target [SP "as" SP capability]`, with single spaces. 0.33 accepts no
  parameters: a `key=value` makes a `PARSE_ERROR`.
- **Fixed operation-to-class table**, unchanged from P-13:
  - INSPECT_PUBLIC: `status`, `list`, `show`;
  - INSPECT_PROTECTED: `inspect`;
  - MUTATE: `start`, `stop`, `set`, `reset`.
  Anything else is `OPERATION_UNKNOWN`.
- **Routing by target namespace:**
  - `app.*` goes to the launcher;
  - `svc.*` and `dev.*` go to the unchanged 0.32b `inspect_public`;
  - `app` alone is the exact collection name for `list app`.
  The launcher cannot reach a service contract by any other route.
- **The request id is supplied with the request.** It must be strictly greater than the last admitted id of this boot
  epoch (Q4). Otherwise the request gets `REQUEST_REPLAYED`. Memory is O(1): one `u32`. An admitted id is used up even
  when the request is later refused. Once id `u32::MAX` is admitted, every later request is a replay; this is
  documented and tested.

### 4.4 The five facts, and the result

```
pub struct Facts {
    structure:     Structure,      // WELL_FORMED | MALFORMED(ParseFault)
    recognition:   Recognition,    // KNOWN(AppId) | UNKNOWN | NOT_EVALUATED
    prerequisites: Prereq,         // SATISFIED | UNSATISFIED{ which: [ServiceId; 4], n } | NOT_EVALUATED
    support:       Support,        // NONE | NOT_EVALUATED   (no "SUPPORTED" value exists in 0.33)
    authorization: Authz,          // CAP_MISSING | NO_AUTHORITY | NOT_EVALUATED (no "AUTHORIZED" value exists)
    execution:     Execution,      // NOT_EXECUTED              (the only value in 0.33)
}
pub struct LaunchResult {          // private fields; only launch.rs can build one
    request_id, op, class, target, admission: FRESH|REPLAYED, facts,
    state: RequestState,           // always a terminal 0.33 state: REFUSED or NOT_EXECUTED
    stage: Stage,                  // where it stopped
    result: ExecResult,            // NOT_EXECUTED (P-22 vocabulary)
    verification: NOT_APPLICABLE, boundary: COOPERATIVE,
    reason: PublicReason,          // Appendix A only
    diag: &'static str,            // a registered kernel diagnostic code
}
```

**Facts are evaluated independently. One fixed precedence chooses the public outcome.**
- The read-only facts (prerequisites, support) are evaluated for every known application, even when an earlier gate
  has already refused the request. They are public INSPECT_PUBLIC information, so the operator always sees which
  prerequisites are unavailable.
- **Authorization is never evaluated as "AUTHORIZED".** The type has no such value in 0.33.
- **Execution has one value, NOT_EXECUTED.** The 0.4 form, `Started(ExecutionEvidence)`, needs a token that no 0.33 code
  can construct: a private field and no constructor, checked by a compile-fail test and a static check.

**Precedence** (option A, recommended; Q2), with stage, public reason and request state:

| # | Gate | Fails when | Public reason (Appendix A) | State |
|---|---|---|---|---|
| 1 | ADMISSION | id not fresh | `REQUEST_REPLAYED` | REFUSED |
| 2 | STRUCTURE | the text does not parse | `PARSE_ERROR` | REFUSED |
| 3 | OPERATION | the operation word is not in the table | `OPERATION_UNKNOWN` | REFUSED |
| 4 | RECOGNITION | well-formed `app.*` not in the registry (or the registry was refused) | `TARGET_UNKNOWN` | REFUSED |
|   | discovery | INSPECT_PUBLIC `status app.x` or `list app` | none: answered from the registry | not a launch request |
| 5 | AUTHORIZATION | MUTATE or INSPECT_PROTECTED without a capability | `CAP_MISSING` | NOT_EXECUTED (validated, then refused) |
| 5 | AUTHORIZATION | a capability is named, but no authority adapter runs | `AUTHZ_UNAVAILABLE` | NOT_EXECUTED |
| 6 | SUPPORT | `exec=NONE` | *(not reachable in 0.33; see §6)* | |
| 7 | PREREQUISITES | a required service is not AVAILABLE | *(not reachable in 0.33)* | |
| 8 | EXECUTION | no executor | *(not reachable in 0.33)* | |

Option A follows the ratified pipeline: normalize, then decide authority, then enforce, then execute, then report. It
is also the precedence of the 0.32b service contract (`start svc.counter` is `CAP_MISSING`). Because gate 5 always
refuses in 0.33, **every 0.33 public reason is an existing Appendix A code**. The support and prerequisite facts are
still reported on every result line, but they do not decide a public reason until an authorization mechanism exists.

## 5. Lifecycle states and permitted transitions

**Registry entry (static):** DECLARED (compiled), then at boot either REGISTERED (the table is valid) or REJECTED (the
whole table is refused). It is printed once and never changes during the boot.

**Request and instance lifecycle**, one per request:

```
                 +--> REFUSED                (terminal)   gates 1-4
   SUBMITTED ----+
                 +--> VALIDATED --> NOT_EXECUTED  (terminal)   gates 5-8
                          :
                          :  reserved for 0.4, refused in 0.33 (LAUNCH_TRANSITION_RESERVED):
                          +..> DISPATCHED ..> RUNNING ..> EXITED   (terminal)
                                   :            +.....> FAULTED  (terminal)
                                   +..> FAULTED +.....> LOST     (terminal; result UNKNOWN)
                                   +..> LOST
```

- **9 states, 81 ordered pairs:**
  - **3 allowed in 0.33:** SUBMITTED to REFUSED; SUBMITTED to VALIDATED; VALIDATED to NOT_EXECUTED.
  - **7 reserved:** VALIDATED to DISPATCHED; DISPATCHED to RUNNING, FAULTED or LOST; RUNNING to EXITED, FAULTED or
    LOST. Each is refused with `LAUNCH_TRANSITION_RESERVED`, state unchanged.
  - **71 invalid**, refused with `LAUNCH_INVALID_TRANSITION`, state unchanged.
  - Terminal states never move.
- **Entering RUNNING additionally requires `ExecutionEvidence`**, which no 0.33 code can construct. So the reserved
  path is closed twice: by the matrix and by the type.
- **What each state means, so that no state implies execution that did not occur:**
  - VALIDATED means only "admitted, well-formed, known". It is **not** an acceptance for execution.
  - NOT_EXECUTED means validated and then stopped, with nothing run.
  - REFUSED means never validated.
  - The 0.4 terminal states report termination only for a request that holds start evidence. LOST maps to
    `result=UNKNOWN` (P-22), never to completion.
- **Transitions are made only inside `launch.rs`.** Every request reaches its terminal state within the call that
  submitted it: no queue, no retry (P-27). A DIAGNOSTIC injection tries a reserved transition on a finished request
  and must be refused with the state unchanged, like the 0.32 `svc_invalid_transition` injection.

**The four things directive D asks to keep apart:**
- **Discovery:** INSPECT_PUBLIC; no request state at all.
- **Submission:** SUBMITTED.
- **Refusal:** REFUSED, or NOT_EXECUTED with its stage and reason.
- **Unsupported execution:** the `support=NONE` fact.
- **Termination:** reserved states, for 0.4.

## 6. Reason-code requirements

**0.33 under option A needs no new Appendix A code.** Every public outcome in §4.4 uses one of `REQUEST_REPLAYED`,
`PARSE_ERROR`, `OPERATION_UNKNOWN`, `TARGET_UNKNOWN`, `CAP_MISSING`, `AUTHZ_UNAVAILABLE`.

APPINFO lines report unavailable prerequisites with the required service's own public status and reason, as 0.32b
computes them:
- `NOT_INSTALLED` for `svc.netmon`;
- `OBSERVATION_STALE` on a degraded clock;
- `NONE` where 0.32b has none, which is the inherited D-ABR-019 Q3-B exception.

Diagnostic codes (`APP_*`, `LAUNCH_*`) go into `KERNEL_DIAGNOSTICS.md`, and they appear only in `diag=` fields
(D-ABR-010/011). The check `check_codes` extends to them, and `check_public_reasons` must still find exactly the 27
Appendix A codes.

**Missing contracts identified for later** (they are needed once authorization exists, so that gates 6-8 can decide):

| Gap | When it becomes a public reason | Proposed Appendix A code |
|---|---|---|
| G-1 | a valid, authorized launch of an application this configuration cannot execute | `EXECUTION_UNSUPPORTED`: "Target is known, but this configuration cannot execute it; nothing was attempted" |
| G-2 | a required service is not AVAILABLE and has no reason of its own (FAILED, STOPPED, DEGRADED) | `DEPENDENCY_UNAVAILABLE`: "A required service or adapter is not available" (also named in D-ABR-019 Q3 option A) |
| G-3 | a started process ends (0.4) | termination reasons, to be designed with the process model |

Under option A none of these is exposed in 0.33. Under option B (Q2), G-1 and G-2 would be needed now. They would
then need a ratified baseline revision **before** implementation (D-ABR-011), and that is a STOP.

## 7. Dependencies on 0.32b services

The launcher reads the following through `&ServiceSet`; it cannot call `start_all`, `step_all` or `request`:
- `ServiceSet::status(idx, clock, now)`, the public mapping;
- `registry()`;
- `svcregistry::lookup` and `index_of`;
- the service table.

It depends on 0.32b's corrected semantics:
- **Finding 3 / D-ABR-021:** a slow or unmeasured probe is never AVAILABLE. Without that correction, `app.counterview`
  would report prerequisites SATISFIED on the strength of a slow probe. "Satisfied" means AVAILABLE only (Q3).
- **Finding 1:** a dependent is stopped in the same cycle its dependency leaves RUNNING, so a prerequisite cannot be
  reported AVAILABLE through a dependency that has already failed.
- **The clock:** a degraded clock makes running services UNKNOWN / `OBSERVATION_STALE`, so prerequisites become
  UNSATISFIED; never satisfied on stale data.
- **The closed contracts:** `start`, `stop`, `set`, `reset` and `inspect` on `svc.*` stay exactly the 0.32b
  `inspect_public` answers.

## 8. Authority and security

- **Capability does not imply authority:** a descriptor has no authority field, and `KNOWN` grants nothing.
- **Authentication does not imply authorization:** there is no actor or session input at all in 0.33. The DIAGNOSTIC
  script has origin `DIAGNOSTIC`. It is not an operator session and carries no authority.
- **No fictional authority:**
  - no DecisionRecord, `SIMULATED_AUTHORITY`, grant id or Cyberforteca component is printed or implied;
  - `authorization=NO_AUTHORITY` says exactly that no authority adapter exists.
- **No bypass:**
  - the launcher holds only `&ServiceSet`, so the type system forbids mutation;
  - a hosted property test checks that every service's runtime record is identical before and after any request;
  - a VM check compares the SVCSTATUS rounds around the request script.
- **No isolation claim:** every result says `boundary=COOPERATIVE` (P-10).
- **No free text in lines:**
  - a target is echoed only if it matches the name grammar; otherwise `target=MALFORMED|target_len=N`;
  - a named capability is never echoed: `capability=PRESENTED` or `NONE`.

## 9. Operator-observable launchpad (serial)

**Production kernel** (no requests are ever made):

```
ABR|APP|registry=OK|entries=3|order=app.counterview,app.netstatus,app.browser|executor=ABSENT
ABR|APPINFO|id=app.counterview|kind=VIEWER|rev=1|exec=NONE|requires=svc.counter|prerequisites=SATISFIED|unavailable=NONE|observed_at_ms=...|clock=OK
ABR|APPINFO|id=app.netstatus|kind=VIEWER|rev=1|exec=NONE|requires=svc.netmon|prerequisites=UNSATISFIED|unavailable=svc.netmon:UNAVAILABLE:NOT_INSTALLED|observed_at_ms=...|clock=OK
```

APPINFO is printed with every 5 s status round (Q8), at the round's evaluation time. The judge can then check it
against the SVCSTATUS lines of the same round.

**DIAGNOSTIC `diag-launchpad`:** after the first status round, a fixed compiled script runs once. For each request, the
transitions and one result line are printed:

```
ABR|LAUNCH|req=1|seq=1|from=SUBMITTED|to=VALIDATED
ABR|LAUNCH|req=1|seq=2|from=VALIDATED|to=NOT_EXECUTED
ABR|LAUNCHRESULT|req=1|op=start|target=app.counterview|class=MUTATE|admission=FRESH|structure=WELL_FORMED|known=YES|prerequisites=SATISFIED|unavailable=NONE|support=NONE|capability=NONE|authorization=CAP_MISSING|executed=NO|process=NONE|state=NOT_EXECUTED|stage=AUTHORIZATION|result=NOT_EXECUTED|verification=NOT_APPLICABLE|boundary=COOPERATIVE|reason=CAP_MISSING|diag=LAUNCH_CAP_MISSING
...
ABR|LAUNCHPAD|requests=17|refused=9|not_executed=6|discovery=1|routed_to_services=1|executed=0|processes=0
```

The fixed script (expected outcomes in the design, before any run):

| # | Request | Expected |
|---|---|---|
| 1 | `start app.counterview` | VALIDATED, NOT_EXECUTED, `CAP_MISSING`; prerequisites SATISFIED; support NONE |
| 2 | `start app.netstatus` | NOT_EXECUTED, `CAP_MISSING`; `unavailable=svc.netmon:UNAVAILABLE:NOT_INSTALLED` |
| 3 | `start app.browser` | NOT_EXECUTED, `CAP_MISSING`; UNSATISFIED |
| 4 | `start app.counterview as cap.launch` | NOT_EXECUTED, `AUTHZ_UNAVAILABLE`; `capability=PRESENTED` |
| 5 | `stop app.counterview` | NOT_EXECUTED, `CAP_MISSING` (MUTATE) |
| 6 | `inspect app.counterview` | NOT_EXECUTED, `CAP_MISSING` (INSPECT_PROTECTED) |
| 7 | `status app.counterview` | discovery (INSPECT_PUBLIC): an APPINFO answer, no launch state |
| 8 | `start app.nosuch` | REFUSED, `TARGET_UNKNOWN` |
| 9 | `start app.counterviews` (near miss) | REFUSED, `TARGET_UNKNOWN` |
| 10 | `start app.CounterView` | REFUSED, `PARSE_ERROR` (`target=MALFORMED`) |
| 11 | `start app.*` | REFUSED, `PARSE_ERROR` (wildcard) |
| 12 | `launch app.counterview` | REFUSED, `OPERATION_UNKNOWN` |
| 13 | `start app.counterview now=1` | REFUSED, `PARSE_ERROR` (parameters not accepted) |
| 14 | `start  app.counterview` (two spaces), and a 65-byte text | REFUSED, `PARSE_ERROR` (two requests) |
| 15 | request 1 again (same id) | REFUSED, `REQUEST_REPLAYED` |
| 16 | `start svc.counter` | routed to the 0.32b service contract: `ABR|SVCQUERY ... result=REFUSED|reason=CAP_MISSING`; no launch state |
| 17 | injection: VALIDATED to RUNNING on request 1 | `ABR|LAUNCH|req=1|refused|...|diag=LAUNCH_INVALID_TRANSITION`; state unchanged (NOT_EXECUTED) |

Further DIAGNOSTIC builds:
- `diag-app-registry-dup`: a duplicate application id. Registry REFUSED at boot; every app target is unknown; the
  services run normally.
- `diag-app-false-exec`: an `exec=Native` claim with no executor. Refused with `APP_EXEC_CLAIM_UNSUPPORTED`.
- `diag-app-unknown-req`: a requirement on a service that does not exist. Refused.

These tables are deliberately excluded from the compile-time check, like 0.32's `DIAG_CYCLE`, so the boot-time check
can be seen to refuse them.

**Operator commands:**
- `python -I -B tools/g033/launch_probe.py run --expect launchpad ...`, then `judge`, to re-check a log.
- Optional (Q6): a hosted demonstration, `cargo run --example launchpad -- "start app.counterview"`. It runs the real
  `launch.rs` against a simulated service view, so Jadin can try his own requests. Label SIMULATED; it is not in the
  kernel.

**Future shells** (SOLOMON Classic, NIGHTRUNNER, TERMINAL 1990):
- they read the same `AppInfo` / `LaunchResult` values and map ids to their own labels and art;
- nothing in the registry or the launcher depends on presentation;
- a shell can neither add a fact nor change one.
The browser-engine interface (0.34) is kept just as separate.

## 10. Phase 1 interpretation carried into 0.33 (D-ABR-021)

There is no behavior change. The 0.32b code already implements the ratified interpretation, and TR-0039 tests it with
the owner's seven cases and seven policy mutants. 0.33 changes wording only:
- `svcrun.rs` comments and the design text say "three overruns **without an intervening verified in-budget step**"
  where they say "3 in a row";
- the counted constants stay as they are (1,000 µs, 3, 100, 1,000 ms, 5 s);
- the 15 Phase 1 tests join the hosted suite as permanent regressions.

## 11. Test plan (expected outcomes fixed before any run)

**Hosted (SIMULATED):**
- **Registry:**
  - the production table is valid;
  - each refusal code has its own test, including the near misses: `App.x`, `app.`, `app..x`, `app.x*`, `svc.x` as an
    app name, 32 bytes;
  - the lookup result is identical for all permutations of the table;
  - an exact lookup succeeds, and twelve near misses fail;
  - a false `Native` claim is refused.
- **Parser:**
  - positives for every operation in the table;
  - negatives: empty text, 65 bytes, a non-ASCII byte, a leading, trailing or double space, upper case, `*`, `?`,
    trailing tokens, `as` with no capability, `as` twice, a parameter, an unknown operation word.
- **Admission:** strictly increasing ids; an equal or lower id is replayed; refused requests use up their id; the
  `u32::MAX` edge.
- **Facts:** prerequisites computed from every service status and reason combination (AVAILABLE, DEGRADED, UNAVAILABLE,
  UNKNOWN, on OK and DEGRADED clocks); only AVAILABLE satisfies.
- **decide:**
  - exhaustive over every reachable fact combination;
  - exactly one terminal state;
  - the reason is in Appendix A;
  - `result=NOT_EXECUTED` and `executed=NO` always.
- **No manufactured execution:**
  - property test: 20,000 generated requests (targets, operations, ids, capability, service states); no state outside
    {REFUSED, NOT_EXECUTED}; no `executed=YES`;
  - compile-fail: `LaunchResult` built outside its module (E0451); `ExecutionEvidence` forged (E0451); a forged
    `RequestState` advance;
  - static: no constructor of `ExecutionEvidence` in `kernel/src`.
- **No authority from the registry:**
  - a known app with satisfied prerequisites and no capability gives `CAP_MISSING`;
  - with a capability, `AUTHZ_UNAVAILABLE`; never authorized;
  - the service runtime records are unchanged before and after.
- **Lifecycle:** all 81 pairs (3 allowed, 7 reserved, 71 invalid); a refused transition leaves the state unchanged;
  terminal states are fixed.
- **Retained:**
  - the 128 0.32b hosted tests and the 15 Phase 1 tests;
  - mutation check of all of them plus about 12 launcher mutants, for example: replay off by one, DEGRADED accepted,
    the exec-claim check removed, a wildcard accepted, precedence swapped, VALIDATED to RUNNING allowed, a service
    stepped by the launcher.

**VM (VM_MEASURED, QEMU 11.1.0, WHPX and TCG):**
- **Production, cold restart, profile 0.33 (C0-C13).** C13 checks:
  - one APP registry line, after the SVC registry;
  - APPINFO on every round, consistent with that round's SVCSTATUS;
  - `exec=NONE` for every app;
  - no LAUNCHRESULT line in production;
  - no reserved state anywhere;
  - no APP line before OPERATIONAL.
- **TCG warm reset** (D-ABR-007).
- **Launchpad diag on WHPX and TCG:** each of the 17 script rows exactly as in §9. The SVCSTATUS rounds before and
  after are consistent: only the counter value grows.
- **Registry-refused diags** (three builds): registry REFUSED, services unaffected.
- **0.32b regressions:** the service probes Y (slow, cascade, defects, refusals, cycle, clock).
- **D-ABR-012:** collision by check and by guard, and double release, on WHPX and TCG; no service or app line follows a
  memory fault.
- **Regressions:** fault reports F, clock and map O, exhaustion E.
- **Earlier kernels under their own profiles:** 0.29, 0.31a, 0.31b, 0.32, 0.32b.
- **Negative:** the 0.32b binary under profile 0.33 fails exactly C13.

**Judge falsifications** (copies of real runs; each must fail for its intended item; the unmutated control passes):
- **False readiness:** prerequisites SATISFIED while the SVCSTATUS of the same round says UNAVAILABLE; an AVAILABLE
  APPINFO on a degraded clock.
- **False execution:** `executed=YES`, `process=1`, `state=RUNNING`, a DISPATCHED transition, `executors=PRESENT`.
- **Missing refusals:** a request without a result line; a REFUSED line without a reason; the injection's refusal line
  deleted.
- **Contradictory results:**
  - REFUSED at stage AUTHORIZATION;
  - `known=NO` with prerequisites evaluated;
  - `AUTHZ_UNAVAILABLE` with `capability=NONE`;
  - a reason that is not in Appendix A;
  - summary counts that do not add up;
  - a replay accepted.
- **Invalid ordering:** NOT_EXECUTED before VALIDATED; a result before its transitions; launch lines before
  OPERATIONAL; the APP registry before the SVC registry; request ids out of order.

**Integrity:**
- reproducible build (two clean builds; loaded sections equal to the tested kernel);
- the 0.32b tree and every earlier tree unchanged;
- source and binary digests recorded;
- every limitation labelled.

## 12. Contradictions and tensions with the baseline (reported, not revised)

1. **P-33 (INSPECT_PUBLIC is a closed list).** `status app.<name>` and `list app` add two reads. That is the "reviewed
   code change" P-33 allows, and it needs the owner's approval (Q5).
2. **P-09/P-30 and P-17/P-46.** No grant, authority adapter, audit store or receipt exists. 0.33 is consistent: nothing
   executes. But **real execution in 0.4 is blocked by these ratified rules** until grants, an authority path
   (LOCAL_SIMULATED, labelled) and the audit store with INTENT/RESULT exist, or until the owner ratifies an exception.
   This is the main 0.4 dependency.
3. **P-22 (ExecutionReport).**
   - LAUNCHRESULT uses the ExecutionReport vocabulary, but it is not an ExecutionReport: it has no `audit_reference`,
     no `decision_id` and no `enforcement_point`, because none exists. It says `stage=` instead.
   - It must not be presented as an audit record.
4. **D-ABR-019 Q3-B.** APPINFO inherits `reason=NONE` where 0.32b has no code, for example for a FAILED service.
5. **Appendix A gaps G-1 to G-3** (§6). Not exposed under option A; needed for 0.4.
6. **Wording only:** D-ABR-019 Q4 "3 consecutive overruns" now reads as D-ABR-021 defines it.
7. **P-19 and the browser** (0.34): option (a) has no TCP stack, so a browser cannot fetch remote pages without a
   baseline revision (§13).
8. **Schedule.** 0.4 "by 2026-11-18" is an aspiration (handoff); this design adds no date claim.

## 13. Preliminary 0.34 graphics and browser-integration dependencies

- **Framebuffer:** a Limine framebuffer request, mapped by the kernel itself (MMIO, like the xAPIC). A `dev.fb0`
  ADAPTER in the service registry is installed only if Limine returned a framebuffer, so `app.browser` can then declare
  the requirement truthfully.
- **Text and pixels:** a bounded glyph renderer; the evidence is framebuffer checksums read back through QMP
  `screendump`.
- **Input:** QEMU keyboard (PS/2 or virtio-input). Part of P-14, and needed before any interactive shell, which needs
  its own reviewed design.
- **Memory:** NetSurf needs `malloc`. A kernel heap is a deliberate 0.34 owner decision; 0.31-0.33 have none. It must
  keep D-ABR-012 ownership.
- **Toolchain:** NetSurf is C. Building it freestanding needs a cross C toolchain (clang or GCC for
  `x86_64-unknown-none`). That is a download needing Jadin's OK; MSVC 14.51 does not target the kernel. A hosted
  NetSurf feasibility build on Windows is the first, cheaper step.
- **Networking:** with P-19 option (a) there is no TCP/HTTP, so only local or embedded test pages are possible without
  a baseline revision.
- **Licensing:** NetSurf is GPL-2.0. That is an owner decision for MOSKO distribution.
- **Alternative:** WPE WebKit stays the M1 MCD NetRunner host candidate, if NetSurf proves unsuitable (handoff).
- **Interfaces:**
  - the browser-engine interface stays independent of presentation, the same rule as §9;
  - the launcher contract does not change for 0.34: `app.browser` stays `exec=NONE` until 0.4 provides an executor.

## 14. Decisions for Jadin (Gate 1)

| Q | Decision | Recommendation |
|---|---|---|
| Q1 | Production application table | the three entries of §4.2 (`app.counterview`, `app.netstatus`, `app.browser`), all `exec=NONE` |
| Q2 | Gate precedence | **A**: authorization before feasibility. It matches the ratified pipeline and the 0.32b service contract, and it needs no new Appendix A code. **B** (feasibility first) gives more varied public reasons, but needs G-1/G-2 ratified first: a STOP |
| Q3 | When a prerequisite is satisfied | AVAILABLE only. DEGRADED, UNKNOWN and UNAVAILABLE do not satisfy |
| Q4 | Request-id freshness | strictly increasing within the boot epoch (one `u32`) |
| Q5 | INSPECT_PUBLIC additions | `status app.<name>` and `list app`. Or none: the boot-time registry print only |
| Q6 | Hosted operator demonstration (`cargo run --example launchpad`) | yes (SIMULATED; not in the kernel) |
| Q7 | Appendix A gaps G-1 to G-3 | defer to the 0.4 design; record them now as known gaps |
| Q8 | APPINFO frequency | with every status round (5 s), so C13 can check it against SVCSTATUS |

## 15. Invariants, with their scope and designed exceptions

- **No request in 0.33 ends in any state but REFUSED or NOT_EXECUTED,** and none reports `executed=YES`. No exception.
  The reserved states exist in the type and the matrix, and are unreachable.
- **Every result line has exactly one Appendix A reason.** Exceptions:
  - discovery answers (status, list) carry status, not a refusal reason;
  - APPINFO may say `NONE` for a prerequisite whose 0.32b status has no reason (Q3-B, inherited).
- **The launcher never changes service state.** Scope: every request and every DIAGNOSTIC injection. The service
  manager still changes state on its own schedule (the counter keeps counting).
- **Every admitted request id is greater than the previous one.** Designed exception: after `u32::MAX` nothing more
  is admitted in that boot.
- **The registry is either fully valid or fully refused.** There is no partially loaded table.
