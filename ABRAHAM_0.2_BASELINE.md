# MOSKO DIGITAL FRONT
## PROJECT ABRAHAM 0.2 - ARCHITECTURAL BASELINE

- **Date:** 2026-10-26
- **Status:** **RATIFIED design baseline.** Jadin accepted every change, P-01 to P-48, item by item on 2026-10-26 (Appendix D). This is a ratified *design*, not a completed implementation or verified release; no Abraham code or test exists yet.
- **Supersedes:** `ABRAHAM_0.1_BASELINE.md` (2026-10-23). The 0.1 file stays unchanged as the record.
- **Derived from:** `ABRAHAM_0.1_REVIEW.md` (2026-10-26), checked against the eight CF Rules and the Cyberforteca contract: first 0.32 (`Cyberforteca-0.32-Verification.zip`, including `MOSKO_DIGITAL_FRONT_HANDOFF.md`), then **0.41**, the build held for testing (`Desktop\Cyberforteca - 0-1\cyberforteca-0.41`). Conformance is in Appendix C.

### Marking convention

- Text with no tag is carried over from 0.1 unchanged, including 0.1's "- proposed" section headings.
- **`[RATIFIED P-nn]`** marks a changed or added item, accepted by Jadin. `P-nn` is listed in Appendix B with the review section it comes from.
- **`[RATIFIED REMOVAL P-nn]`** marks 0.1 text that 0.2 removes; the removed text is shown struck through so nothing disappears silently.
- **`[DIRECTIVE J-nn]`** marks an instruction Jadin gave directly during ratification (Appendix D).
- The pre-ratification draft is kept outside the project as a working copy; this file is the record.

---

## 1. Project decision record

- ACTIVE: Project Abraham is the first intended MOSKO operating system and the precursor to SOLOMON 1.
- ACTIVE: SOLOMON 1 remains the intended human-machine operating environment / HMOS lineage.
- ACTIVE: Cyberforteca is the separate identity, trust, capability, protected-communications, audit and recovery architecture.
- RETIRED: Tsad Rashon is scrapped. Do not schedule it or make it an Abraham dependency.
- SHELVED: BinDeck is shelved. Do not use it as the mandatory integration test device.
- RESEARCH: OpenWrt is the networking research testbed, not an assumed Abraham kernel.
- RESEARCH: Multi-SD / removable boot environment topology is not selected.
- RESEARCH: Akhavish-1 is not approved for development or 0.1 scope.
- OPEN: Final distinction between Abraham, SOLOMON 1 and the broader MOSKO OS family, including shared kernel versus successor architecture. **`[RATIFIED P-07]`** Kernel lineage stays OPEN; **contract lineage** becomes ACTIVE (see below).
- **`[RATIFIED P-01]`** ACTIVE: 0.1 target is **x86-64 under QEMU**, booting through **UEFI** firmware (edk2/OVMF) with an existing boot protocol (e.g. Limine). No hand-written legacy BIOS boot sector. Physical follow-on: an x86-64 UEFI mini-PC, selected later.
- **`[RATIFIED P-02]`** ACTIVE: Language boundary: **NASM** for entry, interrupt/trap stubs and context switch only; kernel and services in **Rust `no_std`**; C is the fallback if Rust proves unworkable.
- **`[RATIFIED P-03]`** ACTIVE: 0.1 storage is a QEMU **virtio-blk** image holding an **append-only record store** (not a filesystem). Recovery boots from a second, **read-only** image selected at boot.
- **`[RATIFIED P-04]`** ACTIVE: First device is a **UART-attached microcontroller** (RP2040 or similar) exposing one read value and one harmless actuator (LED). Under QEMU the identical adapter talks to a host-side **device simulator** over a chardev pipe.
- **`[RATIFIED P-05]`** ACTIVE: First networking exercise runs **in emulation**: OpenWrt's x86-64 image in its own QEMU VM, joined to the Abraham VM by a QEMU socket network. Physical OpenWrt board later.
- **`[RATIFIED P-06]`** ACTIVE: Abraham 0.1 does **not** depend on Cyberforteca components being verified by December. It implements the Cyberforteca-compatible interface against a **local simulated authority**; every decision it makes is labeled SIMULATED.
  - **`[RATIFIED P-31, retargeted by P-44]`** The simulated authority follows **Cyberforteca semantics** (exact scopes, closed fallback relation, decision separate from enforcement, use-time grant revalidation). In the hosted track, its decisions are **differentially tested** against the Cyberforteca Python reference on shared fixtures.
  - **`[RATIFIED P-44]`** The reference is **Cyberforteca 0.41** (public development version 0.4), the version Jadin is holding for testing, not 0.32. Abraham follows a newer Cyberforteca version only through an explicit baseline revision. 0.41's own report (2026-10-21/22, `TEST_RESULTS.txt`) says "unit layer checks pass", with no VM experiment run and acceptance left to Jadin. Device identity, attestation and session inputs there are still SIMULATED. Abraham inherits all of those limits.
- **`[DIRECTIVE J-01]`** ACTIVE: Cyberforteca's tests run **alongside** Abraham/SOLOMON development, against the version held for testing (currently 0.41).
- **`[DIRECTIVE J-02]`** ACTIVE: **Ritza** is the prototype of Abraham to be prepared for **NetRunner** if Abraham is not complete by **June 2027**. Ritza is the amalgamation of what has been developed up to then. Consequence for Abraham: the core and its tests (P-08) are built so they can be packaged into Ritza without depending on the native kernel.
- **`[DIRECTIVE J-03]`** ACTIVE: **Tsad Rashon is retired** (confirms §1 above). Where the Digital Front handoff still lists it, the baseline governs; the handoff is out of date on this point.
- **`[DIRECTIVE J-04]`** ACTIVE: **Test authority.** Echo / Claude Code may run tests on its own initiative. Every run is recorded so it can be audited, reviewed and verified (§6.5). Running a test never changes code under test or accepts a release; acceptance stays Jadin's.
- **`[RATIFIED P-07]`** ACTIVE: **Contract lineage.** SOLOMON 1 consumes Abraham's command/authority contract (§4), status model (§5), reason-code registry (Appendix A) and audit format, regardless of which kernel SOLOMON 1 runs on.
- **`[RATIFIED P-08]`** ACTIVE: **Two-track build.** The Abraham core (§2.1) is a portable library built both hosted (simulator on the development machine) and freestanding (linked into the kernel).

## 2. Product architecture

Abraham 0.1 is a small, demonstrable native computing foundation intended to produce reusable interfaces and tested kernel/host services for later SOLOMON 1 development. A functioning prototype is not automatically a secure or field-ready operating system.

Suggested system separation:

```
HUMAN / OPERATOR
|
INPUT + COMMAND NORMALIZER
|
ABRAHAM HMI / CONSOLE
|
REQUEST / CAPABILITY INTERFACE
|
CYBERFORTECA AUTHORITY ADAPTER <--> AUDIT / RECOVERY RECORDS      [decides]
|
KERNEL CAPABILITY CHECK (kernel.cap_check)                         [RATIFIED P-09: enforces]
|
BOUNDED SERVICES + DEVICE ADAPTERS
|
ABRAHAM KERNEL + HARDWARE ABSTRACTION
|
LOCAL STORAGE / INPUT / DISPLAY / DEVICE I-O
```

Independent branch:

```
ABRAHAM NETWORK STATUS / MANAGEMENT API
|
AUTHORIZED NETWORK MANAGEMENT SERVICE
|
OPENWRT LAB NODE OR OTHER SELECTED NETWORK PLANE      [RATIFIED P-05: OpenWrt x86-64 QEMU VM]
|
AP / LAN / ETHERNET / WIFI WAN / OPTIONAL CELLULAR
```

Future branch (not an Abraham 0.1 requirement):

```
BINAT NATONIM (HMAI) -> bounded commands, not implicit authority
SOLOMON 1 -> evolved HMI, HMOS services, future biological interfaces
```

### 2.1 Abraham core and platform split `[RATIFIED P-08]`

```
ABRAHAM CORE (portable, hosted + freestanding)
  command grammar + normalizer
  contract types (§4)
  simulated authority (LOCAL_SIMULATED)
  status model + reason-code registry
  audit record format + hash chain
        |
   -----+-----------------------------
   |                                 |
HOSTED SIMULATOR                 ABRAHAM KERNEL (freestanding)
(dev machine; unit and            boot, memory, scheduling,
 contract tests)                  cap_check, drivers, storage
```

The core is the part SOLOMON 1 inherits under contract lineage (P-07).

### 2.2 Enforcement point `[RATIFIED P-09]`

The authority adapter **decides**; the kernel **enforces**. An AUTHORIZED or RESTRICTED decision becomes a **kernel-held grant**, registered in kernel-protected state and scoped to the exact (capability, operation, resource) triple, the session, `boot_epoch`, policy version and `valid_until`. Services and device adapters accept state-changing operations only through a grant the kernel validates. A service holding no grant cannot reach a device adapter's mutating interface. `ExecutionReport.enforcement_point` names this location.

**`[RATIFIED P-30]`** (CF Rule 1) A grant is **not a bearer token**. Holding a grant reference confers nothing by itself: at every use the kernel resolves it by reference and **revalidates** issuer, session, epoch, policy version, revocation, exact resource/operation and time. Check and use are atomic, with no time-of-check/time-of-use gap. 0.2 says "grant" rather than "capability handle" so the term does not suggest that a held capability is authority.

**`[RATIFIED P-45]`** (CF Rule 1 as revised in 0.33) Authority can be delegated only by a legitimate owner or authorized controller, within explicit scope, identity, session, policy and enforcement limits. **Abraham 0.1 implements no delegation:** a grant authorizes its holder only and cannot be passed on. **No repeated request creates authority:** each retry of a denied request is a fresh evaluation with the same inputs and gets the same decision. Retry counts never feed policy.

**`[RATIFIED P-47]`** **Audit before grant** (from Cyberforteca 0.41 F02). A grant is created **PENDING** (unusable). It becomes **COMMITTED** (usable, within its epoch and lifetime) only after its decision record has been durably appended. If the append raises, the grant is **UNCERTAIN** and is **discarded**; the operator makes a fresh request. Abraham 0.1 does no reconciliation. This is the stricter of the two options in Cyberforteca 0.41 `HUMAN_REVIEW_041.md` item 2. If Jadin settles that item the other way for Cyberforteca, Abraham changes only through a baseline revision.

```
PENDING --append ok--> COMMITTED --first use / expiry / revocation--> CONSUMED | INVALIDATED
   \--append raised--> UNCERTAIN --> INVALIDATED (0.1: always)
```

### 2.3 Privilege boundary `[RATIFIED P-10]`

- **First vertical slice:** services may run in ring 0. Every report and console status then labels the boundary **`COOPERATIVE`**, and nothing claims isolation.
- **Before 0.1 exit:** services run in **ring 3** with syscall entry, per-task page tables and checked copy-in/copy-out. Boundary then reports `RING3`.

## 3. Minimum Abraham 0.1 capabilities - proposed

### A. Boot and execution

- Boot to an identifiable Abraham console in a selected emulator or target board.
- Establish kernel-owned execution context, memory ownership and error reporting.
- Implement basic task scheduling and a minimal privilege boundary appropriate to the selected architecture. **`[RATIFIED P-10]`** Boundary staging per §2.3.
- Record boot version and configuration; expose a diagnostic boot status.
- **`[RATIFIED P-11]`** Generate a random **`boot_epoch`** at every boot from RDRAND/RDSEED or virtio-rng. If no entropy source is present, boot status reports `DEGRADED` with `ENTROPY_UNAVAILABLE` and privileged operations are refused.
- **`[RATIFIED P-11]`** Record an **`environment_id`** (`NORMAL` / `RECOVERY`, later the boot medium) in boot status.
- **`[RATIFIED P-32]`** (CF Rule 4) `environment_id`, boot version and boot status are **self-reported**, not attested. They are labeled `SELF_REPORTED`, and policy never grants authority on them. The only effect `environment_id` may have is to **narrow** authority (recovery ceiling, §3F).

### B. Operator interface

- Provide a deterministic command grammar: actor, target, ~~verb~~ operation, parameters and requested capability. **`[RATIFIED P-12]`** "Operation" is the contract term; "verb" is only the word typed at the console. Grammar in §4.4.
- Separate read-only inspection from state-changing operations. **`[RATIFIED P-13]`** Three classes: `INSPECT_PUBLIC` (status, version, service health; no capability; works with authorization down), `INSPECT_PROTECTED` (audit, sessions, configuration; needs a capability), `MUTATE` (any state change; needs a capability). The class is set by the normalizer from the operation table, never by the caller.
  - **`[RATIFIED P-33]`** (CF Rule 6) `INSPECT_PUBLIC` is a **closed, reviewed allow list compiled into the core**, like Cyberforteca's closed fallback relation. It is not "authority given to anyone": it is the fixed set of non-sensitive reads the system exposes without authority. It can change only through a reviewed code change, never through policy. It may not include anything sensitive under CF Rule 7.
- Support at least one real input/display path. D-pad, Trakarskop, touchscreen and full accessibility remain future input profiles unless selected hardware validates them. **`[RATIFIED P-14]`** For 0.1 the path is the **serial console** plus QEMU keyboard/framebuffer.
- Commands should not require a WAN connection.
- **`[RATIFIED P-12]`** Actor and session come from console context, never from typed text. Unknown operation, unknown target, duplicate key or trailing input is a parse failure with a reason code; the normalizer never guesses.

### C. Local computing and device services

- Local persistence for configuration and diagnostic records. **`[RATIFIED P-03]`** Persistent record classes: configuration, diagnostics, audit. Explicitly non-persistent: sessions, grants.
- A basic device abstraction and one instrumented device or simulated adapter. **`[RATIFIED P-04]`** `dev.mcu0` with `dev.mcu0.value` (read) and `dev.led0` (set/read-back).
- Services must present explicit statuses: AVAILABLE, DEGRADED, UNAVAILABLE and UNKNOWN, with specific reason codes. **`[RATIFIED P-15]`** Reason codes come from the single registry in Appendix A.
- Prefer deterministic adapters and state machines over unnecessary AI.
- **`[RATIFIED P-16]`** **`svc.netmon`**: a deliberately network-dependent service that publishes uplink state. Gives T07/T08 something real to degrade.
- **`[RATIFIED P-16]`** **`svc.counter`**: a long-running local task with an observable, monotonically increasing counter. Proves local work is not interrupted (T08).

### D. Security and authority integration

- A Cyberforteca-compatible authorization interface that carries identity, session reference, target, requested operation, capability and policy result.
- Preserve the eight established CF Rules; authentication and technical access never imply authorization. **`[RATIFIED P-29]`** The CF Rules text is not yet attached to this baseline; compliance cannot be checked until it is.
- Never represent mocked policy or attestation as verified production security. **`[RATIFIED P-06]`** Every decision record carries `authority_source` and `simulated`; when `simulated = true` the console shows `SIMULATED` next to the outcome.
- Fail closed for privileged operations when authorization is unavailable, without disabling unrelated safe local functions.
- Produce an auditable decision record without keys, credentials or sensitive payloads.
- **`[RATIFIED P-09]`** Enforcement is at the kernel capability check (§2.2), not in the authority adapter.
- **`[RATIFIED P-17]`** **Audit fail-closed:** if the audit record for a `MUTATE` cannot be durably written, the operation does not execute (`NOT_EXECUTED`, `AUDIT_UNAVAILABLE`). `INSPECT_PUBLIC` keeps working.
- **`[RATIFIED P-17]`** Audit records are **hash-chained** (each carries the hash of the previous). This is described as **tamper-evident only**, never tamper-proof. **`[RATIFIED P-37]`** A hash chain alone cannot detect replacement of the whole history; without a protected anchor and an anti-rollback sequence (neither exists in 0.1) this limit is stated wherever the audit log is described.
- **`[RATIFIED P-37]`** No operation deletes or rewrites audit history. A request to do so is always `DENIED` and audited (`AUDIT_HISTORY_PROTECTED`), with no fallback and no recovery bypass, matching Cyberforteca's `DELETE_AUDIT_HISTORY` tripwire.
- **`[RATIFIED P-38, retargeted by P-44]`** Decision records are serialized with Cyberforteca's canonical JSON encoding: the **CF033 profile**, whose encoding rules are unchanged since CF032 (ASCII, sorted keys, no whitespace, explicit nulls, integers 0..2^53-1). Field paths and record shapes follow the tracked version (**CF041** audit record set), so Abraham and Cyberforteca records can be compared directly. A decision record always says enforcement `NOT_ATTEMPTED`; what actually ran is a **separate, correlated ExecutionReport**, never an edit of the decision.
- **`[RATIFIED P-35]`** (CF Rule 7) **No sensitive information in 0.1.** The audit hash chain gives integrity only; the record store, serial console and UDP management channel give **no confidentiality**. 0.1 therefore stores, displays and transmits no keys, credentials, personal data, biometric or biological data. Records follow Cyberforteca's allowlist (no free text, payloads or secrets). Any sensitive data class needs confidentiality designed in and ratified before it enters Abraham.

### E. Networking / offline method

- Keep local files, local services and local device operations usable without WAN wherever hardware permits.
- Expose local-link health, external-uplink health, selected route, metering and service availability as distinct concepts. **`[RATIFIED P-18]`** Model in §5.1.
- Support a no-WAN demonstration. Cellular is an optional later adapter and cannot be assumed to exist.
- Keep OpenWrt isolated as a supported research networking endpoint until a demonstrated integration need changes that decision.
- **`[RATIFIED P-19]`** **Networking option (a), minimal native networking:** a virtio-net driver; local link state read from the device; a UDP management channel to the OpenWrt VM. External-service reachability is **reported by OpenWrt**, not probed by Abraham. No general-purpose TCP stack in 0.1.
  - Fallback, if (a) slips: option (b), network state over a dedicated serial management channel from the OpenWrt VM, with `LOCAL_LINK` documented as "management channel up". Choosing (b) requires a ratified revision, not a silent switch.

### F. Recovery and environment transitions

- Provide a documented recovery procedure, at least in an emulator or development setup.
- Never reuse trusted sessions merely because the same machine or removable media is present.
- Recovery must not silently create administrator, firmware or policy-management authority.
- Do not claim boot media separation itself provides attestation or a hardware root of trust.
- **`[RATIFIED P-20]`** Sessions and grants exist **in memory only**, bound to `boot_epoch` + `environment_id`. They never persist across a boot.
  - **`[RATIFIED P-34]`** (CF Rule 5) Following Cyberforteca's session lifecycle, a session is also revoked, and its grants become unusable, on: **policy change**, **environment transition**, and **session expiry** (expired even if a cached status says active). A new session never inherits grants; any authority needs a fresh request and evaluation.
- **`[RATIFIED P-21, revised by P-36]`** **Recovery allow list** (`environment_id = RECOVERY`), a closed set:
  1. `INSPECT_PUBLIC`;
  2. **recovery inspection**: reading the audit log from read-only media, under its own recovery capability;
  3. **restore configuration** from a known-good record, which **excludes** policy, grants, sessions and principals (restoring an old snapshot must not restore old authority);
  4. invalidate all sessions.

  **`[RATIFIED P-36]`** Following Cyberforteca's recovery model, recovery contexts **reject** firmware, administrator, policy, capability-issuance, **device-command** and audit-deletion operations, even when authorized. Recovery authority is narrower than normal authority. The 0.2-draft `PHYSICAL_PRESENCE` capability is **withdrawn**: claimed presence would be self-declared authority (CF Rules 2 and 4). Recovery verification is separate from recovery authority. A full RecoveryKey/ownership path follows Cyberforteca's recovery contract and is out of scope for 0.1.

  Recovery never creates new principals and never raises an existing principal's authority.

## 4. Normalized command and authority contract - proposed

**`[RATIFIED P-22]`** The 0.1 contract is replaced by the records below. Fields carried over from 0.1 are unmarked; added fields are marked `+`.

### 4.1 CommandRequest

```
CommandRequest:
  request_id                 unique within boot_epoch; a repeat is rejected (REQUEST_REPLAYED)
  actor_reference
  session_reference
+ boot_epoch
+ environment_id             NORMAL | RECOVERY
+ origin                     CONSOLE | SERIAL | NETWORK_MGMT    (future: HMAI)
  target_resource
  operation
+ operation_class            INSPECT_PUBLIC | INSPECT_PROTECTED | MUTATE   (set by normalizer)
  parameters
  requested_capability
+ issued_at                  integer monotonic ms, clock_domain = boot_epoch
  expiration_or_time_limit   integer monotonic ms, clock_domain = boot_epoch
```

**Time rule `[RATIFIED P-39]`:** offline there is no trustworthy wall clock. As in Cyberforteca 0.32, validity and expiry use **integer monotonic milliseconds in one clock domain** (here, the boot epoch), with **half-open** intervals: `issued_at <= now < valid_until`. Times from another clock domain (e.g. the OpenWrt VM) are never compared directly. Wall-clock time may appear in audit records only, for human correlation, labeled `UNVERIFIED`.

### 4.2 DecisionRecord (replaces the DecisionOutcome enum)

```
DecisionRecord:
  request_id
  outcome              AUTHORIZED | RESTRICTED | DENIED
  granted_capability   required when RESTRICTED; must be in the closed
                       fallback relation (P-31)
  policy_reference
  reason_code
  decided_at           monotonic ms, clock_domain = boot_epoch
  valid_until          monotonic ms, clock_domain = boot_epoch
  enforcement          always NOT_ATTEMPTED here; see ExecutionReport
  authority_source     LOCAL_SIMULATED | CYBERFORTECA_<component>
  simulated            true | false
```

- RESTRICTED (only if an explicit safe lower-authority capability exists) - unchanged rule; **`[RATIFIED P-22, P-31]`** the lower capability must be in a **closed fallback relation** fixed in the core (not reversible, not transitive, not inferred from names). Extending it needs a reviewed code/schema change, not a policy rule. The effective scope is named in `granted_capability`; the original request is kept. RESTRICTED is not a success for the original operation.
- **`[RATIFIED P-31]`** Scopes are an **exact** (capability, operation, resource) triple: no wildcards, prefix matches, operation coercion or implicit resource expansion.
- **`[RATIFIED P-23]`** There is **no DEFERRED outcome** in 0.1. See §5.2.

### 4.3 ExecutionReport

```
ExecutionReport:
  request_id
  executed_operation
  enforcement_point          e.g. kernel.cap_check
+ privilege_boundary         COOPERATIVE | RING3
  result                     COMPLETED | PARTIAL | FAILED | NOT_EXECUTED | UNKNOWN
  verification_status        VERIFIED | UNVERIFIED | VERIFICATION_FAILED | NOT_APPLICABLE
  reason_code
  audit_reference
+ simulated                  copied from the DecisionRecord
```

- `UNKNOWN` is mandatory when an adapter dies mid-operation. A report never says `COMPLETED` for an outcome the system did not observe.
- `VERIFIED` only when the system read the effect back (e.g. queried the LED after setting it), not when the call returned without error.
- **`[RATIFIED P-40]`** (CF Rules 3 and 4) `VERIFIED` means **the device's read-back agreed** with the requested state. It says nothing about the device's integrity, firmware or identity: an unauthenticated UART device can report anything. Nothing in 0.1 treats a device report or a management-channel message as attestation.

### 4.3a Execution lineage `[RATIFIED P-46]`

From Cyberforteca 0.41 F03: a canonical, hash-chained line is not proof that it describes a legitimate execution. Every `MUTATE` execution writes **two** audit records, correlated with its decision:

```
DecisionRecord(decision_id, request_id, grant_id, session, boot_epoch, scope)
      |  every field below must match
      v
EnforcementReceipt INTENT(attempt_id)   -- written BEFORE the operation runs
      v
EnforcementReceipt RESULT(attempt_id)   -- written after; this is the ExecutionReport
```

- Both receipts bind `request_id`, `decision_id`, `grant_id`, `session_reference`, `boot_epoch`, capability, resource and `enforcement_point`.
- If the **INTENT** cannot be written, the operation does not run (`NOT_EXECUTED`, `AUDIT_UNAVAILABLE`), which is how P-17 is enforced.
- An INTENT with no RESULT (e.g. crash or power loss mid-operation) means the outcome is **`UNKNOWN`**. It is never inferred as completed.
- **One lineage checker**, the same code used live and offline: the live ledger refuses a violating record **before** writing it, and an offline validator re-checks the whole store. Status values follow Cyberforteca 0.41: `COMPLETE_VERIFIED`, `INCOMPLETE_UNCERTAIN`, `FAILED`, `BLOCKED`, `INVALID`. Orphan receipts, receipts that disagree with their decision, and receipts with no positive decision are `INVALID`.

### 4.4 Command grammar `[RATIFIED P-12]`

To be formalized as full EBNF before December coding:

```
command    = operation SP target *( SP param ) [ SP "as" SP capability ]
operation  = "status" / "list" / "show"                   ; INSPECT_PUBLIC
           / "inspect"                                    ; INSPECT_PROTECTED
           / "set" / "start" / "stop" / "reset"           ; MUTATE
target     = segment *( "." segment )                     ; e.g. dev.led0, svc.netmon
                                                          ; exact names only, no wildcards (P-31)
param      = key "=" value
```

The operation-to-class table is fixed in the core, so classification does not depend on the target.

### 4.5 Future HMAI

For future HMAI: interpret only as needed, request authorization, perform bounded work, verify/report, then relinquish autonomy. Abraham 0.1 need only implement and test the deterministic command path. No Binat implementation is implied. **`[RATIFIED P-22]`** A future HMAI request uses the same CommandRequest with `origin = HMAI`; it gets no authority the operator's session would not get.

## 5. Candidate states and degradation policy

### 5.1 Network state `[RATIFIED P-18]`

Network state is multidimensional, not one INTERNET_UP boolean:

- LOCAL_LINK: UP / DOWN / **NOT_INSTALLED** / UNKNOWN
- WAN_UPLINK: UP / DOWN / **NOT_INSTALLED** / UNKNOWN - **per uplink**, each with an `uplink_id`
- EXTERNAL_SERVICE: REACHABLE / UNREACHABLE / **NOT_INSTALLED** / UNKNOWN
- CELLULAR: AVAILABLE / UNAVAILABLE / NOT_INSTALLED / UNKNOWN
- COST_PROFILE: UNMETERED / METERED / UNKNOWN - **a property of each uplink**; the system-level value is the profile of the selected route
- **SELECTED_ROUTE: `<uplink_id>` / NONE / UNKNOWN** (added)

**`[RATIFIED P-18]`** Every dimension carries `observed_at` and `source` (e.g. `virtio-net`, `openwrt-mgmt`). Past a staleness limit it reports `UNKNOWN` with `OBSERVATION_STALE`; a last-known value is never shown as current.

**`[RATIFIED P-40]`** (CF Rule 3) State reported over the OpenWrt management channel is a **claim from another device**, labeled with its source. It is not evidence of that device's integrity, and it never feeds an authority decision in 0.1.

### 5.1a Liveness and compromise `[RATIFIED P-41]`

(CF Rule 8) Every service and adapter status carries two **separate** fields, as Cyberforteca's records do:

- `liveness`: `LIVE` / `STALE` / `LOST` / `UNKNOWN`
- `compromise`: `NONE_KNOWN` / `SUSPECTED` / `CONFIRMED`

Loss of liveness (crash, timeout, WAN loss, stale observation) **never** sets `compromise` by itself. Stale or lost liveness may deny **new** authority involving that component, but it is reported as an availability fault, not an attack. In 0.1 nothing sets `SUSPECTED` or `CONFIRMED` automatically; only explicit, separately specified evidence could.

### 5.2 Privilege and fault policy

Privilege failure is also distinct from connectivity failure:

- Identity unknown -> no new authority automatically granted. **`[RATIFIED P-33]`** (CF Rule 6, second part) Unknown is **not** treated as malicious: an unknown actor is not logged as an attack, does not set `compromise`, and is not locked out of `INSPECT_PUBLIC`.
- **`[RATIFIED P-34]`** Policy changed -> sessions under the old policy revoked; their grants unusable.
- Authorization unavailable -> privileged request denied ~~or safely deferred~~. **`[RATIFIED REMOVAL P-23]`** Deferral removed for 0.1: the request is `DENIED` with `AUTHZ_UNAVAILABLE` and the operator resubmits. A deferred privileged action would execute later under changed conditions (new boot, session or route), which §3F forbids silently accepting.
- WAN unavailable -> authorized local operation continues.
- Service crashed -> adapter reports unavailable; no manufactured completion. **`[RATIFIED P-22]`** In-flight operations report `result = UNKNOWN`.
- Boot medium changed -> previous session invalidated and re-evaluated. **`[RATIFIED P-20]`** Satisfied by construction: sessions do not survive any boot.
- **`[RATIFIED P-17]`** Audit unwritable -> `MUTATE` not executed; `INSPECT_PUBLIC` continues.
- **`[RATIFIED P-11]`** Entropy unavailable -> boot `DEGRADED`; privileged operations refused.

## 6. Acceptance tests - proposed 0.1 exit criteria

### 6.1 Harness `[RATIFIED P-24]`

- Abraham emits **structured result lines** on the serial port, e.g.
  `ABR|T05|PASS|req=0007|outcome=DENIED|reason=CAP_MISSING|sim=1`
- A **host-side runner** (Python) starts QEMU, injects console commands, toggles links through the QEMU monitor (`set_link`), restarts or kills the device simulator, and checks the lines.
- A test passes only on a matching line from Abraham **and** the runner's independent observation where one exists (e.g. the simulator's LED state).
- **`[RATIFIED P-48]`** Every result carries an **evidence label** (from Cyberforteca 0.41 F04) saying how it was observed:
  - `SIMULATED`: hosted simulator on the development machine;
  - `VM_MEASURED`: Abraham running under QEMU;
  - `HARDWARE_MEASURED`: Abraham on physical hardware.

  A result is reported only at the label it actually has. A `SIMULATED` pass is never described as measured, and a `VM_MEASURED` pass is never described as a hardware result.

### 6.2 Tests

| ID | Test (0.1 text) | Pass criteria `[RATIFIED P-25]` |
|---|---|---|
| T01 | Boot Abraham into the defined console on the selected test platform. | Console banner with version, `boot_epoch`, `environment_id`, privilege boundary. |
| T02 | Execute a local read-only command with no WAN present. | `INSPECT_PUBLIC` command succeeds with the WAN link down from boot. |
| T03 | Record local state, reboot and verify persistence or explicit non-persistence. | Config and audit records survive reboot; sessions and grants do not; both verified. |
| T04 | Enumerate a test device adapter and report its actual status. | `dev.mcu0` listed with status matching the simulator's/device's real state. |
| T05 | Reject a test state-changing request lacking a capability grant. | `DENIED`, `CAP_MISSING`, no change observed at the device, audit record written. |
| T06 | Permit only a narrowly defined test state change with a valid test authorization, and clearly mark test security as simulated where applicable. | `AUTHORIZED`, `verification_status = VERIFIED` by read-back, `simulated = true` on console and in audit. |
| T07 | Disconnect WAN and demonstrate local functionality remains usable. | `svc.netmon` reports `DEGRADED`/`UNAVAILABLE`; a local `INSPECT` and an authorized local `MUTATE` both still succeed. |
| T08 | Restore WAN without restarting unrelated local work. | `svc.counter` shows continuous progress across the restore; `svc.netmon` returns to `AVAILABLE`. |
| T09 | Report LAN, WAN, cellular presence, metering and external-service reachability independently. | Each §5.1 dimension changes alone when the runner varies only that input; cellular reports `NOT_INSTALLED`. |
| T10 | Reboot or switch test environment; verify no stale session is silently accepted. | A session token captured before reboot is replayed after it and rejected with `SESSION_STALE_EPOCH`. |
| T11 | Force a service failure; confirm visible degraded status and error record. | Simulator killed mid-operation: `result = UNKNOWN` (never `COMPLETED`), service `UNAVAILABLE`, `liveness = LOST`, **`compromise` unchanged** (P-41), error record written. |
| T12 | Exercise a documented recovery path without silently escalating privilege. | In `RECOVERY`, one allow-listed action succeeds; a **device command** (`set dev.led0`) is denied **even with a valid normal-mode authorization** (P-36); both audited. |

### 6.3 Added tests `[RATIFIED P-26]`

| ID | Test | Pass criteria |
|---|---|---|
| T13 | Malformed and ambiguous command input. | Rejected with `PARSE_ERROR` / `TARGET_UNKNOWN` / `OPERATION_UNKNOWN`; nothing executes. |
| T14 | Expired request. | Request past `valid_until` rejected with `CAP_EXPIRED`. |
| T15 | Replayed `request_id` within one boot. | Rejected with `REQUEST_REPLAYED`. |
| T16 | Audit store full or write failure. | `MUTATE` returns `NOT_EXECUTED`, `AUDIT_UNAVAILABLE`; `INSPECT_PUBLIC` still works. |
| T17 | RESTRICTED path. | Broad request granted only the declared fallback capability; an operation outside it is `DENIED`. |

### 6.4 CF Rule tests `[RATIFIED P-42]`

The handoff asks that CF Rule violations be "observable through testing where practical". Each rule gets at least one test:

| ID | Rule | Test | Pass criteria |
|---|---|---|---|
| T18 | 1 | Present a grant reference after its session is revoked, or for a different resource. | Kernel revalidation rejects it; nothing executes. |
| T19 | 2 | Console actor signed in (authenticated) but with no policy rule for `set dev.led0`. | `DENIED`, `POLICY_DENIED`. |
| T20 | 3 | Simulator sends well-formed, correctly framed status claiming "firmware OK". | Status shown with its source; no authority or attestation result derived from it. |
| T21 | 4 | Boot with `environment_id` altered to claim `NORMAL` from the recovery image. | No authority gained; the value is shown `SELF_REPORTED`. |
| T22 | 5 | Change policy version mid-session, then use an existing grant. | Grant rejected; a new request needs a new evaluation. (T10 covers reboot.) |
| T23 | 6 | Command from an unknown actor. | Mutating requests `DENIED` with `IDENTITY_UNKNOWN`; `INSPECT_PUBLIC` still answers; `compromise` unchanged. |
| T24 | 7 | Scan serialized audit records, console output and management-channel traffic from a full run for credential, key and session-token canaries. | No canary appears. |
| T25 | 8 | Stall the simulator (alive but silent) past its timeout. | `liveness = STALE`/`LOST`, `compromise = NONE_KNOWN`, no attack record. |

### 6.5 Test run records `[DIRECTIVE J-04]`

Echo / Claude Code may run tests without asking first. Each run, for Abraham, the Cyberforteca reference (J-01) or the P-44 differential tests, leaves a record in `daemons/abraham/test-records/` so it can be audited, reviewed and verified:

```
TestRunRecord:
  run_id                   unique, sequential
  started_at / ended_at    wall clock, UTC (human correlation only)
  subject                  what was tested, with version and source path
  subject_digest           SHA-256 of the archive or tree under test, where available
  command                  exact command line
  environment              OS, interpreter/toolchain versions, QEMU version, dependency pins
  evidence_label           SIMULATED | VM_MEASURED | HARDWARE_MEASURED (P-48)
  exit_code
  summary                  counts: passed / failed / errors / skipped
  output_file + digest     full raw output, saved next to the record, with its SHA-256
  deviations               anything that differed from the documented procedure
  modified_code_under_test always "no"; a run that needs a change stops and is reported instead
```

Records are append-only: a wrong record is corrected by a new record that references it, never by editing. A run proves only the tested behavior on the recorded configuration (§6). It never accepts a release; acceptance stays Jadin's.

Passing these proves the tested behaviors on the tested configuration only. It does not establish production Cyberforteca security, secure boot, clinical/neural safety, universal compatibility, or fault tolerance beyond the test conditions.

## 7. Explicitly out of scope for Abraham 0.1

- SOLOMON 1 completed HMOS features or neural stimulation interfaces
- Full Binat Natonim general HMAI autonomy
- Any medical or implanted-device actuation
- Finished Cyberforteca hardware-backed attestation unless separately validated
- Universal device drivers or all NetRunner and 0-R3177Y carrier support
- Production-grade cellular failover across all outages
- Full OpenWrt source integration or an OpenWrt fork
- Multi-SD patentability, secure-boot proof, or finalized mechanical arrangement
- Tsad Rashon and BinDeck release work
- Akhavish-1 robotics development
- **`[RATIFIED P-19]`** A general-purpose TCP/IP stack in Abraham (0.1 needs only what option (a) requires)
- **`[RATIFIED P-27]`** Deferred / queued privileged execution
- **`[RATIFIED P-27]`** Persistent sessions or any session survival across boots
- **`[RATIFIED P-27]`** A filesystem (0.1 uses the append-only record store)
- **`[RATIFIED P-17]`** Any tamper-proof claim for the audit log
- **`[RATIFIED P-35]`** Storing, displaying or transmitting any sensitive information (CF Rule 7)
- **`[RATIFIED P-36]`** RecoveryKey, ownership-binding and owner-cache purge flows (Cyberforteca recovery contract; later revision)
- **`[RATIFIED P-32]`** Attestation of any kind, including of Abraham's own boot

## 8. Open decisions

| # | Decision (0.1) | 0.2 status |
|---|---|---|
| 1 | Abraham target CPU/board or VM and firmware/boot method. | **`[RATIFIED P-01]`** Resolved: x86-64 / QEMU / UEFI. Physical board OPEN. |
| 2 | Native kernel scope and programming-language boundary. | **`[RATIFIED P-02, P-10]`** Resolved: NASM + Rust `no_std`; staged privilege boundary. |
| 3 | Abraham-to-SOLOMON lineage. | **`[RATIFIED P-07]`** Contract lineage ACTIVE; kernel lineage OPEN, not a 0.1 blocker. |
| 4 | Concrete first physical device. | **`[RATIFIED P-04]`** Resolved: UART microcontroller + host simulator. Exact part OPEN. |
| 5 | Storage and recovery media for 0.1. | **`[RATIFIED P-03]`** Resolved: virtio-blk append-only store + read-only recovery image. |
| 6 | Where the first networking exercise runs. | **`[RATIFIED P-05]`** Resolved: OpenWrt x86-64 in a QEMU VM. |
| 7 | Which Cyberforteca components have verified tests by December. | **`[RATIFIED P-06]`** No longer a blocker: local simulated authority, labeled. Still tracked. |
| 8 | Which input/carrier profile receives first physical validation. | **`[RATIFIED P-14]`** 0.1 uses serial console + QEMU keyboard/framebuffer. Physical profile OPEN, not a 0.1 blocker. |
| 9 | Confirm official 0-R3177Y identifier. | OPEN. Blocks manufacturing-facing specifications only. |
| 10 | Obtain M-CEM v0.1's detailed 17 design guidelines. | OPEN. Blocks any doctrine-compliance claim. |
| 11 | **`[RATIFIED P-28]`** Development toolchain. | OPEN. As of 2026-10-26 the dev machine has QEMU 11.0.93 (a pre-release build in `C:\Program Files\qemu`, not on this shell's PATH; Jadin has opened it for Echo's use) with x86-64 edk2 firmware, and Python 3.14.7. Rust, NASM and a C compiler are **not installed**. Decide whether to install them natively or use a container/WSL environment, and whether to pin a stable QEMU release. |
| 12 | **`[RATIFIED P-29]`** CF Rules text. | **Resolved.** Received 2026-10-26 in `Cyberforteca-0.32-Verification.zip`; Rule 1 taken in its 0.33 revised wording from Cyberforteca 0.41 `docs/ARCHITECTURE.md` §2 (P-45). Conformance in Appendix C. |
| 13 | **`[RATIFIED P-19]`** Networking option (a) vs (b). | **Resolved: option (a).** (b) only by a ratified revision. |
| 14 | **`[RATIFIED P-12]`** Full grammar. | OPEN until the EBNF in §4.4 is completed and reviewed. |
| 15 | **`[RATIFIED P-43]`** Abraham vs. Ritza. | **Resolved by `[DIRECTIVE J-02]`.** Ritza is the prototype of Abraham prepared for NetRunner if Abraham is not complete by June 2027, combining what has been developed by then. Still to settle before Ritza work starts: Ritza's platform (the handoff describes a Linux-based prototype) and its cut-off date. |
| 16 | **`[RATIFIED P-43]`** Handoff vs. baseline on Tsad Rashon. | **Resolved by `[DIRECTIVE J-03]`:** Tsad Rashon is retired. Remaining record-keeping: update `MOSKO_DIGITAL_FRONT_HANDOFF.md`, which still lists it. |
| 17 | **`[RATIFIED P-36, P-44]`** Recovery and approval decisions open in Cyberforteca. | OPEN, Jadin's call in Cyberforteca. The 0.32 recovery questions were settled in 0.33 (OWNER_CAPABILITIES split from RECOVERY_CAPABILITIES; recovery-key cache purge kept, one named entry per grant). Still open in 0.41 `HUMAN_REVIEW_041.md`: **item 1**, whether key-epoch binding extends to recovery/owner evidence; **item 2**, promoting vs. discarding uncertain approvals (Abraham takes the discard side, P-47). Abraham follows those decisions through a baseline revision and does not settle them itself. |

## 9. Development sequence

- **October-November 2026:** requirements and architecture, test platform, command/API contracts, hardware selection, risk and acceptance criteria. **`[RATIFIED P-08, P-28]`** Also: ratify 0.2; set up the toolchain; build the Abraham core hosted with unit tests for the contract, grammar, simulated authority and reason codes (exercising T05, T06, T13-T15, T17 and the decision logic of T18, T19, T22, T23 on the host), plus the differential run against the Cyberforteca 0.41 reference (P-31, P-44).
- **December 2026:** begin Abraham 0.1 engineering, narrow boot/console/local-operation vertical slice and repeatable tests. **`[RATIFIED P-24, P-10]`** Slice order: UEFI boot -> serial console banner (T01) -> core linked freestanding -> `INSPECT_PUBLIC` path (T02) -> record store (T03) -> test runner. Privilege boundary `COOPERATIVE` at this stage.
- **`[RATIFIED]` Before 0.1 exit:** device adapter + simulator (T04-T06, T11); OpenWrt VM + networking option (a) (T07-T09); ring-3 services (P-10); recovery image (T12); T16; **`[RATIFIED P-42]`** full-system CF Rule tests T18-T25.
- **Later:** integrate measured OpenWrt network lab findings, verified Cyberforteca enforcement and broader SOLOMON HMOS services through explicit revisions.

No later feature, device integration, release or conference capability is considered achieved until validated. Dates are intentions, not proof of readiness.

## 10. Governing principle

The machine exists to reduce the procedural distance between human intention and successful execution. Loss of WAN should degrade external capability, not destroy local capability. Human objectives are bounded by explicit authority, and the system must expose what it actually did, verify the result, and stop when the authorized task is complete.

---

## Appendix A. Reason-code registry `[RATIFIED P-15]`

One registry, shared by services, decisions, execution reports and network state. New codes are added here, never invented locally.

| Code | Used for |
|---|---|
| `AUTHZ_UNAVAILABLE` | Authority adapter unreachable or not running |
| `CAP_MISSING` | No capability presented for a protected or mutating operation |
| `CAP_EXPIRED` | Capability or request past `valid_until` |
| `POLICY_DENIED` | Authority evaluated and refused |
| `SESSION_STALE_EPOCH` | Session from a previous boot or other environment |
| `SESSION_UNKNOWN` | Session reference not recognized |
| `IDENTITY_UNKNOWN` | Actor not identified |
| `REQUEST_REPLAYED` | `request_id` already seen in this boot |
| `PARSE_ERROR` | Command does not match the grammar |
| `TARGET_UNKNOWN` | Target not in the resource table |
| `OPERATION_UNKNOWN` | Operation not in the operation table |
| `AUDIT_UNAVAILABLE` | Audit record could not be durably written |
| `ADAPTER_NO_RESPONSE` | Adapter timed out |
| `ADAPTER_CRASHED` | Adapter process or link lost |
| `DEVICE_NOT_PRESENT` | Expected device absent |
| `VERIFY_MISMATCH` | Read-back differs from the requested state |
| `LINK_DOWN` | Local link down |
| `UPLINK_DOWN` | WAN uplink down |
| `OBSERVATION_STALE` | State older than its staleness limit |
| `NOT_INSTALLED` | Hardware or adapter not present in this configuration |
| `ENTROPY_UNAVAILABLE` | No usable randomness source at boot |
| `STORAGE_ERROR` | Record store read/write failure |
| `SIMULATED_AUTHORITY` | Informational: decision made by `LOCAL_SIMULATED` |
| `AUDIT_HISTORY_PROTECTED` | Request to delete or rewrite audit history (always denied); same name as Cyberforteca 0.32 and 0.41 |
| `GRANT_REVALIDATION_FAILED` | Grant failed use-time revalidation (revoked, wrong epoch/policy/resource, expired) |
| `RECOVERY_CEILING` | Operation is outside the recovery allow list |
| `LIVENESS_STALE` | New authority refused because a component's liveness is stale or lost (not a compromise finding) |

## Appendix B. Change index

| ID | Change | Review § |
|---|---|---|
| P-01 | Target: x86-64 / QEMU / UEFI | 1 (#1) |
| P-02 | Language: NASM + Rust `no_std`, C fallback | 1 (#2) |
| P-03 | Storage: virtio-blk append-only store; read-only recovery image; persistence classes | 1 (#5) |
| P-04 | First device: UART microcontroller + host simulator | 1 (#4) |
| P-05 | Network lab: OpenWrt x86-64 in QEMU | 1 (#6) |
| P-06 | Local simulated authority, labeled SIMULATED | 1 (#7) |
| P-07 | Contract lineage ACTIVE; kernel lineage OPEN | 1 (#3) |
| P-08 | Two-track build; Abraham core | 5 |
| P-09 | Kernel-held grants as enforcement point | 3.1 |
| P-10 | Staged privilege boundary (COOPERATIVE then RING3) | 3.2 |
| P-11 | `boot_epoch`, `environment_id`, entropy requirement | 2.3, 3.4 |
| P-12 | Operation vs verb; grammar; normalizer never guesses | 2.2, 2.7 |
| P-13 | Inspect tiers: PUBLIC / PROTECTED / MUTATE | 2.6 |
| P-14 | 0.1 input path: serial + QEMU keyboard/framebuffer | 1 (#8) |
| P-15 | Reason-code registry | 7 |
| P-16 | `svc.netmon` and `svc.counter` | 5 |
| P-17 | Audit fail-closed; hash chain, tamper-evident only | 3.3 |
| P-18 | Network model: per-uplink cost, SELECTED_ROUTE, NOT_INSTALLED, freshness | 4 |
| P-19 | Networking option (a); (b) as ratified-only fallback; no general TCP/IP | 5 |
| P-20 | Sessions memory-only, boot-epoch bound | 3.4 |
| P-21 | Recovery allow list (PHYSICAL_PRESENCE withdrawn by P-36) | 3.5 |
| P-22 | Contract: CommandRequest fields, DecisionRecord, ExecutionReport enums, HMAI origin | 2.3-2.5 |
| P-23 | Remove deferral | 2.1 |
| P-24 | Structured serial output + host test runner | 6.1 |
| P-25 | Pass criteria for T01-T12 | 6.2 |
| P-26 | Added tests T13-T17 | 6.3 |
| P-27 | Out-of-scope additions | 2.1, 3.4, 1 (#5) |
| P-28 | Toolchain decision (new) | - (found 2026-10-26) |
| P-29 | CF Rules text required (received 2026-10-26) | 1 (#10) |
| P-30 | Grants are not bearer tokens; use-time revalidation; "capability handle" renamed "grant" | CF Rule 1; CF 0.32 §8 |
| P-31 | Simulated authority follows CF semantics; exact scopes; closed fallback relation; differential testing (retargeted to 0.41 by P-44) | CF 0.32 §8 |
| P-32 | Boot/environment values self-reported, never attested; attestation out of scope | CF Rule 4 |
| P-33 | INSPECT_PUBLIC as a closed allow list; unknown ≠ malicious | CF Rule 6 |
| P-34 | Session revocation on policy change, environment transition, expiry; no grant inheritance | CF Rule 5; CF 0.32 §6 |
| P-35 | No sensitive information in 0.1; integrity-only channels stated | CF Rule 7; CF 0.32 §11 |
| P-36 | Recovery ceiling: no device commands etc. in recovery; PHYSICAL_PRESENCE withdrawn; config restore excludes authority | CF Rules 2, 4; CF 0.32 §2, §10 |
| P-37 | Hash-chain limits stated; audit history undeletable | CF 0.32 §8, §11 |
| P-38 | Canonical CF JSON for decision records (CF033 encoding, CF041 shapes per P-44); decision separate from execution | CF 0.32 §11 |
| P-39 | Integer monotonic ms, clock domain, half-open intervals | CF 0.32 §6 |
| P-40 | VERIFIED ≠ device integrity; management-channel state is a claim | CF Rules 3, 4 |
| P-41 | Separate liveness and compromise fields | CF Rule 8 |
| P-42 | T18-T25: one test per CF Rule | Handoff ("observable through testing") |
| P-43 | Ritza relationship and Tsad Rashon record discrepancy flagged (resolved by J-02, J-03) | Handoff |
| P-44 | Track Cyberforteca 0.41 (held for testing) instead of 0.32 for P-31 and P-38 | CF 0.41 README, TEST_RESULTS |
| P-45 | CF Rule 1 in its 0.33 revised wording; no delegation in 0.1; retries create no authority | CF 0.41 ARCHITECTURE §2 |
| P-46 | INTENT/RESULT enforcement receipts; one lineage checker live and offline | CF 0.41 F03, AUDIT_LINEAGE_041 |
| P-47 | Grant PENDING until audited; UNCERTAIN always discarded in 0.1 | CF 0.41 F02, APPROVAL_AUDIT_LIFECYCLE_041; HUMAN_REVIEW_041 item 2 |
| P-48 | Evidence labels SIMULATED / VM_MEASURED / HARDWARE_MEASURED on every result | CF 0.41 F04 |

## Appendix C. CF Rules conformance `[RATIFIED P-29]`

Source: the eight CF Rules as stated in `MOSKO_DIGITAL_FRONT_HANDOFF.md` and `cyberforteca-0.32/docs/ARCHITECTURE.md` §2. **`[RATIFIED P-45]`** Rule 1 uses the wording Jadin revised in 0.33, as it stands in Cyberforteca 0.41 `docs/ARCHITECTURE.md` §2; Rules 2-8 are unchanged in 0.41. There are exactly eight; Rule 6 has two parts.

| # | CF Rule | Where 0.2 meets it | Problem found in the earlier 0.2 draft | Test |
|---|---|---|---|---|
| 1 | Capability does not imply authority. Authority may be delegated by a legitimate owner or authorized controller to a defined application or agent, constrained by explicit scope, identity, session, applicable policy, and the receiving system's enforcement boundaries. No repeated request creates authority by itself. | §2.2 kernel-held grants, revalidated at use (P-30); exact scopes and closed fallback relation (P-31); no delegation in 0.1, and retries are fresh evaluations (P-45); grants usable only once audited (P-47) | "Capability handle" read like bearer authority, and there was no use-time revalidation. Delegation and repeated requests were not addressed. | T05, T15, T17, T18 |
| 2 | Authentication does not imply authorization. | §3B actor/session from console context only; a decision needs a policy rule (§4.2) | `PHYSICAL_PRESENCE` would have let a presence claim confer recovery authority. Withdrawn (P-36). | T19 |
| 3 | Message authentication does not imply device integrity. | `VERIFIED` = read-back agreed only (P-40); management-channel state is a claim (P-40) | `VERIFIED` and OpenWrt-reported state could be read as device trust. | T20 |
| 4 | Attestation must be verified, not self-declared. | `environment_id` and boot status labeled `SELF_REPORTED`, never a basis for authority (P-32); attestation out of scope | The boot environment was self-declared but able to influence policy. | T21 |
| 5 | Trust is session-bound. | Sessions and grants memory-only and epoch-bound (P-20); revoked on policy/environment change and expiry; no inheritance (P-34) | Only reboot revoked a session; policy change did not. | T10, T22 |
| 6 | Unknown identity receives no authority; unknown does not automatically mean malicious. | `IDENTITY_UNKNOWN` gets no authority; unknown is not an attack and does not touch `compromise` (P-33) | The second part (not malicious) was not stated. `INSPECT_PUBLIC` was not defined as a closed set. | T23 |
| 7 | Sensitive information requires confidentiality as well as integrity. | No sensitive information in 0.1; integrity-only channels named as such (P-35) | The hash chain gave integrity only, and nothing ruled out sensitive data in plaintext stores or channels. | T24 |
| 8 | Loss of liveness does not itself prove compromise. | Separate `liveness` / `compromise` fields; liveness loss never sets compromise (P-41) | Crash and timeout states had no field separating availability from compromise. | T11, T25 |

**Not checked here:** the M-CEM v0.1 17 design guidelines (decision 10). Conformance above is a document-level check of this baseline against the rule text and the Cyberforteca 0.32 and 0.41 contracts. It becomes evidence only once T18-T25 exist and pass.

## Appendix D. Ratification record

- **Date:** 2026-10-26
- **Acceptance authority:** Jadin
- **Method:** item-by-item review in twelve groups (Echo / Claude Code session). Every item was offered as accept or reject/hold.
- **Result:** all of **P-01 to P-48 accepted**; none rejected or held.

| Group | Items | Decision |
|---|---|---|
| Platform and build | P-01, P-02, P-03, P-28 | Accepted |
| Devices and networking | P-04, P-05, P-19, P-16 | Accepted |
| Authority source and lineage | P-06, P-31, P-07, P-08 | Accepted |
| Operator interface | P-12, P-13, P-33, P-14 | Accepted |
| Enforcement and boot | P-09, P-30, P-10, P-11 | Accepted |
| Command and authority contract | P-22, P-23, P-39, P-38 | Accepted |
| Audit and data handling | P-17, P-37, P-35, P-15 | Accepted |
| Sessions, recovery, boot claims | P-20, P-34, P-21 with P-36, P-32 | Accepted |
| Status model and scope | P-18, P-40, P-41, P-27 | Accepted |
| Tests | P-24, P-25, P-26, P-42 | Accepted |
| Records and Cyberforteca 0.41 | P-44, P-45, P-29, P-43 | Accepted |
| Audit rules from Cyberforteca 0.41 | P-46, P-47, P-48 | Accepted |

**Directives given during ratification** (Jadin's words, condensed):

| ID | Directive |
|---|---|
| J-01 | Cyberforteca's current build (0.41) is the version held for testing; its tests run alongside the building of SOLOMON. |
| J-02 | Ritza is the prototype of Abraham that will be prepared for NetRunner if Abraham is not complete by June 2027; it is the amalgamation of what has been developed until then. |
| J-03 | Tsad Rashon is a retired concept. |
| J-04 | Echo is granted authority to run tests on its own; runs are recorded so they can be audited, reviewed and verified. |

Ratifying a design does not show that any of it works. Every capability above is unbuilt and unverified until its tests exist, run and are recorded under §6.5.
