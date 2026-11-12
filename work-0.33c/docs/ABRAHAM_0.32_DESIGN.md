# ABRAHAM 0.32 design checkpoint: closed service registry, service lifecycle, truthful status

- 2026-11-06. MOSKO Laboratory 001 - Pripyat. Tree `Documents\Abraham\work-0.32`. Record **TR-0036**.
- Directive: `MOSKO_ABRAHAM_032_DEVELOPMENT_DIRECTIVE_2026-11-06.md` (Jadin, 2026-11-06), recorded as D-ABR-018.
- **Status: DESIGN FOR OWNER REVIEW. Nothing in this document is implemented.** No kernel, harness or test code is
  written until Jadin approves this checkpoint (directive Step 2; "DO NOT IMPLEMENT 0.32 FULLY WITHOUT USER
  CONFIRMATION").
- Foundation: accepted 0.31b (D-ABR-017), kernel 0.31.1-dev `ca847b03...`, verified in runs ABR-0.32-V001..V004.
- Rules this design must respect, as ratified in `ABRAHAM_0.2_BASELINE.md`:
  - P-09/P-30: authority decides, the kernel enforces, grants are revalidated at use;
  - P-10: services run in ring 0, labelled COOPERATIVE;
  - P-13/P-33: INSPECT_PUBLIC is a closed allow list;
  - P-15: reasons come from Appendix A only;
  - P-35: no sensitive data, payloads or free text;
  - P-39: integer monotonic milliseconds in the boot-epoch clock domain, half-open intervals;
  - P-41: liveness is separate from compromise;
  - D-ABR-010/011: kernel diagnostic codes are separate from public codes;
  - D-ABR-012: memory invariants;
  - D-ABR-015/016: the event log records and is read; it never dispatches.

## 1. What 0.32 adds, in one paragraph

After the kernel reaches OPERATIONAL, a fixed, compiled table of three entries is checked, put in dependency order,
and started in that order from the kernel's main loop:
- `dev.net0` is a placeholder network adapter. It is honestly **not installed**, because no network driver exists.
- `svc.counter` is a real local service. It counts its own bounded steps.
- `svc.netmon` depends on `dev.net0`, so it is never started. It reports UNAVAILABLE / `NOT_INSTALLED`.

Every entry has a public status made only of Appendix A words and numbers. Liveness and compromise are separate
fields. A degraded clock makes time-dependent statuses UNKNOWN / `OBSERVATION_STALE`. Nothing is preemptive,
nothing is dynamic, nothing is allocated, and no service holds or uses authority.

## 2. Closed service registry (directive Step 3)

| Item | Design |
|---|---|
| Identifier | `ServiceId`: an enum with explicit numbers (`DevNet0 = 1`, `SvcCounter = 2`, `SvcNetmon = 3`). Each has one exact dotted name: lowercase `[a-z0-9]+` segments, 2 or more segments, prefix `svc.` or `dev.`, at most 31 bytes. No wildcards, no prefixes, no names built from input |
| Table | One `static` array of descriptors, compiled in. Each descriptor holds: id, name, kind (`SERVICE` / `ADAPTER`), `installed` (compile-time fact), dependencies (at most 4 ids), work budget (in work units), and its fixed-size state. At most 8 entries. **No registration function exists** |
| Validation | One `const fn validate(table)`, run twice: at compile time (`const _: () = assert!(...)`, so a bad production table does not build), and again at boot, before anything starts. It refuses: a duplicate id or name; a malformed name; a dependency on an unknown id; a self-dependency; a duplicate dependency; more than 8 entries or 4 dependencies; a budget above `MAX_WORK_UNITS`; a cycle |
| Order | A deterministic topological sort (Kahn's algorithm). Ties are broken by `ServiceId` number, never by table position. Production order: `dev.net0, svc.counter, svc.netmon` |
| Lookup | `lookup(name)` compares the exact bytes with each table name. Anything else (`svc.counte`, `SVC.COUNTER`, `svc.*`, a trailing dot or space, empty) is refused, nothing changes, and the public answer is `TARGET_UNKNOWN`. An unknown name is not an attack (P-33): it is not logged as one and does not touch compromise |
| Boot-time refusal | A table that fails at boot (only possible in the DIAGNOSTIC build `diag-svc-cycle`, which bypasses the compile-time assert) starts **no** service, prints `ABR|SVC|registry=REFUSED|diag=<code>`, and marks every entry UNAVAILABLE. The kernel keeps running and keeps heartbeats: kernel OPERATIONAL is not a service claim |

## 3. Service lifecycle (directive Step 4)

States: `DECLARED`, `STARTING`, `RUNNING`, `STOPPING`, `STOPPED`, `FAILED`. Same style as 0.31b `lifecycle.rs`:
portable code, no `unsafe`, a sequence number per service.

| # | Transition | Allowed only when |
|---|---|---|
| 1 | DECLARED -> STARTING | kernel lifecycle is OPERATIONAL, the entry is installed, and every dependency is RUNNING |
| 2 | STARTING -> RUNNING | readiness established (below) |
| 3 | STARTING -> FAILED | readiness failed or was contradicted |
| 4 | RUNNING -> STOPPING | a dependency left RUNNING (the only stop trigger in 0.32) |
| 5 | RUNNING -> FAILED | a step returned an error, broke its contract (used more work units than its budget), or overran its time budget 3 times in a row |
| 6 | STOPPING -> STOPPED | the stop hook returned |
| 7 | STOPPING -> FAILED | the stop hook returned an error |
| R | STOPPED or FAILED -> DECLARED | **reserved** manual reset. It is implemented and tested hosted only; the 0.32 kernel has no call site (a static check). See section 9, Q2 |

- Every other `(from, to)` pair is refused: 36 ordered pairs, 7 allowed, 2 reserved, 27 refused.
  A refusal prints `ABR|SVC|id=..|refused|from=..|to=..|diag=SVC_INVALID_TRANSITION`, records a SERVICE event, and
  leaves the state and sequence unchanged.
- **The kernel keeps running after a refused service transition.** The 0.31b kernel lifecycle stops on a refusal;
  a service fault must not stop the kernel, and must not produce a success either.
- **Withheld start:** a dependency that is not RUNNING is not a transition. The dependent stays DECLARED, and
  `ABR|SVC|id=..|start=WITHHELD|dependency=..` is printed and recorded once. A dependent is never STARTING on an
  assumption.
- **Dependency lost at runtime:** its RUNNING dependents are stopped, in reverse dependency order. They are never
  restarted automatically. In the production table this cannot happen (`svc.counter` has no dependency); hosted
  tests and `diag-svc-defects` exercise it.
- **No premature start:** `start_all()` first reads the kernel lifecycle. If it is not exactly OPERATIONAL, it is
  refused (`SVC_KERNEL_NOT_OPERATIONAL`) and nothing changes. A boot that fails before OPERATIONAL therefore starts
  nothing.

**Readiness ("never RUNNING before readiness"):**
1. While STARTING, the manager runs one probe step.
2. The service's own `ready()` check must pass.
3. The manager's independent check must also agree. The kernel, not the service, counts the work units the service
   reported, and the service's observable state must equal that count. For `svc.counter`, this means value = 1 after
   one probe step of 1 unit.

A service that claims to be ready without doing the work is contradicted by step 3. It becomes FAILED
(`SVC_READINESS_CONTRADICTED`) and never RUNNING.

## 4. Honest cooperative execution (directive Step 5)

- **Where steps run:** from the kernel main loop only, after OPERATIONAL, never in an interrupt handler. Each
  RUNNING service gets at most one step per loop wake, in dependency order. The loop wakes at the 100 Hz timer.
- **Bounded by construction:**
  - A step receives a work budget (at most `MAX_WORK_UNITS` = 64; `svc.counter` declares 1).
  - It performs a fixed number of small operations. `svc.counter` does one checked increment; an overflow is an
    error, so the counter cannot wrap.
  - It returns `Done { units }` or `Error(diag)`.
  - `units > budget` is a contract violation, and the service becomes FAILED.
  - A static text check refuses `loop` and `while` in production service step code.
- **Measured after return, never called a timeout:**
  - The manager reads the raw TSC before and after each step and converts the difference with the calibrated rate.
  - Above `STEP_BUDGET_US` = 1,000 µs, the step is an **overrun**: it is recorded, and the service becomes DEGRADED.
  - After 3 overruns in a row, the service becomes FAILED and is no longer stepped.
  - After 100 consecutive in-budget steps (about 1 s), a DEGRADED service is AVAILABLE again.
  - An after-reading lower than the before-reading is counted as `SVC_STEP_UNMEASURED`. It never counts as a success
    or as an in-budget step.
  - The raw TSC is used here, not the clock guard, so the guard's call pattern and its injected DIAGNOSTIC offsets
    are unchanged.
- **The honest limit:** with no preemption, a step that never returns stops the kernel. Heartbeats stop, and the
  harness sees it (C5, C12). 0.32 does not and cannot detect this from inside.
- **The second limit:** if one step lasts more than 5 s, the clock guard's next reading looks like a TSC forward jump
  (`TSC_FORWARD_JUMP`), and the clock is latched DEGRADED. This is fail-closed: every time-dependent status becomes
  UNKNOWN. But the cause is misattributed. The test `diag-svc-stall` (section 7) records this limit instead of hiding it.
- **Not added:** threads, preemption, a heap, any allocation, allocator use from an interrupt, a network stack,
  ring 3, retries.

## 5. Truthful status (directive Step 6)

Public status record, one per table entry. Every field is a closed enum or an integer, with no free text (P-35):

```
ABR|SVCSTATUS|id=<exact name>|state=<lifecycle>|status=AVAILABLE|DEGRADED|UNAVAILABLE|UNKNOWN
            |reason=<Appendix A code>|NONE|liveness=LIVE|STALE|LOST|UNKNOWN|compromise=NONE_KNOWN|SUSPECTED|CONFIRMED
            |observed_at_ms=<n>|NONE|clock=OK|DEGRADED|UNREADABLE|value=<n>|NONE|steps=<n>|overruns=<n>
```

- `reason` is a separate type, `PublicReason`, whose variants are exactly the 27 codes of Appendix A. A tool parses
  them from the ratified baseline. It cannot be built from a string or from a kernel diagnostic code; a compile-fail
  test proves this, with a compiling twin.
- Kernel diagnostic codes appear only in `diag=` fields of `ABR|SVC` lines, never in `reason=` (D-ABR-011).
- `observed_at_ms` is guarded uptime in the boot-epoch domain (P-39), read with `clock::peek_uptime_ms`.
  - Fresh means `observed_at <= now < observed_at + 1000` (half-open).
  - `clock=DEGRADED` follows the guard's latched flag. `UNREADABLE` means the guard was in use at that instant, and
    it is treated like DEGRADED (fail-closed).
- `compromise` is `NONE_KNOWN` in every row. **No 0.32 code can set SUSPECTED or CONFIRMED** (there is no setter; a
  static check confirms it). Liveness loss never touches compromise (P-41).
- The status is computed from the registry only, never from the event log.

**Mapping (the first matching row wins; a pure function, tested exhaustively):**

| # | Condition | status | reason | liveness |
|---|---|---|---|---|
| 1 | entry not installed (`dev.net0`) | UNAVAILABLE | `NOT_INSTALLED` | UNKNOWN |
| 2 | registry refused at boot | UNAVAILABLE | NONE (*) | UNKNOWN |
| 3 | FAILED | UNAVAILABLE | NONE (*) | LOST |
| 4 | DECLARED, start withheld by dependency d | UNAVAILABLE | d's reason if it is `NOT_INSTALLED`, else NONE (*) | UNKNOWN |
| 5 | DECLARED (not started), STARTING, STOPPING, STOPPED | UNAVAILABLE | NONE (*) | UNKNOWN |
| 6 | RUNNING, clock DEGRADED or UNREADABLE | UNKNOWN | `OBSERVATION_STALE` | UNKNOWN |
| 7 | RUNNING, last good step not fresh | UNKNOWN | `OBSERVATION_STALE` | STALE |
| 8 | RUNNING, fresh, overrun within the recovery window | DEGRADED | NONE (*) | LIVE |
| 9 | RUNNING, fresh, no recent overrun | AVAILABLE | NONE | LIVE |

- Rows 1-4 do not depend on time (a compile-time fact, a lifecycle fact), so a degraded clock does not change them.
- Rows 6-9 depend on time. With a degraded clock, row 6 is the only possible answer: a stale value is never shown as
  fresh.
- **(*) The reason-code gap (owner decision Q3):** Appendix A has no code for "this service failed", "a dependency is
  not running" or "a step overran its budget".
  - The nearest codes are misleading. `ADAPTER_NO_RESPONSE` means a timeout, and 0.32 has none. `ADAPTER_CRASHED`
    means a process or link was lost.
  - So this design prints `reason=NONE` there, and the specific cause stays on the diagnostic line.
  - In 0.32 these rows occur only in DIAGNOSTIC builds and hosted tests. The counted production boot uses only
    rows 1, 4, 6, 7, 9, all with ratified codes.
- **INSPECT_PUBLIC (P-13/P-33):** `inspect_public(operation, target)` accepts exactly one operation, `status`, on
  exactly the table names, and returns exactly the fields above.
  - Unknown target: `TARGET_UNKNOWN`.
  - Unknown operation: `OPERATION_UNKNOWN`.
  - `start`, `stop`, `set` or `reset`: MUTATE class, refused with `CAP_MISSING`, nothing changes. No grant mechanism
    exists in 0.32 (P-09: fail closed).
  - 0.32 has no operator input path, so this function is exercised hosted and by `diag-svc-refusals`.
- **Authority:** no 0.32 service grants, holds, checks or enforces authority. A static check confirms that service
  modules do not call memory, paging, APIC or CPU code.

## 6. Events and diagnostics (directive Step 7)

- **What is unchanged:**
  - The 32-slot log (`events.rs`) is unchanged in capacity, overwrite counting, sequence numbering and
    `lost_reentrant`.
  - It gets one new kind, `SERVICE` = 5, with registered codes: `SVC_REGISTRY_OK/REFUSED`,
    `SVC_STARTING/RUNNING/STOPPING/STOPPED/FAILED`, `SVC_START_WITHHELD`, `SVC_NOT_INSTALLED`, `SVC_START_REFUSED`,
    `SVC_INVALID_TRANSITION`, `SVC_DEGRADED`, `SVC_RECOVERED`.
  - It stays record and read only. The manager never reads it to decide anything (a static check), and it is not a
    durable or security audit.
- **Bounded volume:**
  - Events are recorded only on lifecycle and status changes. Steps and per-step overruns are not events; they are
    counted on status lines.
  - A clean production boot is expected to hold about 16 of 32 records: 11 from 0.31b, plus the registry, counter
    STARTING and RUNNING, `dev.net0` not installed, and netmon withheld.
  - If more are recorded, the oldest are overwritten and counted as `dropped`. That is never silent.
- **Order with the 0.31b printout:** the existing `ABR|EVENTS` block at OPERATIONAL is printed exactly as in 0.31b,
  before any service exists. So C10 is unchanged, and the absence of SERVICE records in it is part of the proof of
  no premature start.
- **Second dump:** after the start phase, one second dump of only the newer records:
  `ABR|SVCEVENTS|from_seq=n|recorded=..|dropped=..|capacity=32|lost_reentrant=..`, then `ABR|SVCEVENT|...` lines.
  These are distinct tags, so the 0.31b judge's counts are not disturbed. `eventlog.rs` gains a read-only
  `print_since(seq)`.
- Fault context (`ABR|FAULTCTX`) includes SERVICE records naturally.
- All new line tags and codes go into `KERNEL_DIAGNOSTICS.md` (new sections 16-18). `check_diag_codes.py` must pass.

## 7. Test matrix (directive Step 8: expected outcomes written before any run)

Labels: **SIMULATED** = hosted Rust or Python on the development machine. **host** = static and file checks.
**VM_MEASURED** = Abraham under QEMU 11.1.0 (q35, 256 MiB, 1 vCPU). New DIAGNOSTIC builds (never accepted
kernels):
- `diag-svc-cycle`: cyclic table, compile-time assert bypassed;
- `diag-svc-refusals`: early start, unknown id, invalid transition;
- `diag-svc-defects`: the test services `svc.diagready` (honest readiness failure), `svc.diagliar` (claims ready
  with no work) and `svc.diagdep` (depends on diagready);
- `diag-svc-slow`: a 20 ms bounded step;
- `diag-svc-stall`: a 6 s step.

| ID | What | Label | Expected |
|---|---|---|---|
| S01 | production table valid; ids and names unique; exact-name grammar; order `dev.net0, svc.counter, svc.netmon` | SIMULATED | PASS |
| S02 | each refusal of `validate`: duplicate id or name, 9 malformed names, unknown, self or duplicate dependency, too many entries or dependencies, budget above maximum; each returns its own code; the pure input is unchanged | SIMULATED | each refused for its own reason |
| S03 | cycles (2-, 3-, behind an acyclic prefix) refused `SVC_DEPENDENCY_CYCLE`, no order produced; a cyclic const table **does not compile** (compile-fail doctest, with a compiling twin) | SIMULATED | refused; compile error E0080 |
| S04 | determinism: same order for all 120 permutations of a 5-entry table and on repeated runs | SIMULATED | identical |
| S05 | exact lookup: every name found; 12 near-miss names refused with `TARGET_UNKNOWN`, compromise unchanged | SIMULATED | PASS |
| S06 | lifecycle matrix: all 36 pairs, exactly 7 allowed, 2 reserved; every refusal leaves state and seq unchanged | SIMULATED | PASS |
| S07 | no premature start: `start_all` before OPERATIONAL refused, all DECLARED. VM: no `ABR|SVC` line before `ABR|STATE|OPERATIONAL` on any boot; every build that fails before OPERATIONAL (N001-N008, F001, F002, F005) prints no `ABR|SVC` line | SIMULATED + VM_MEASURED | PASS |
| S08 | dependency down: withheld dependent stays DECLARED, UNAVAILABLE; a dependency lost at runtime stops its dependents in reverse order, no restart; `svc.netmon` UNAVAILABLE / `NOT_INSTALLED` on every counted boot | SIMULATED + VM_MEASURED | PASS |
| S09 | readiness: an honest failure is FAILED, never RUNNING; a false claim (`svc.diagliar`) is contradicted, FAILED, never RUNNING; `svc.counter` RUNNING only after `ready=PASS` with probe and kernel counts equal | SIMULATED + VM (`diag-svc-defects`) | PASS |
| S10 | budget accounting: units above budget means FAILED; a budget above maximum is refused by the table; overrun: 1 gives DEGRADED, 3 in a row give FAILED, 100 good steps give AVAILABLE again; unmeasured never counts as success | SIMULATED | PASS |
| S11 | slow returning step (20 ms): overrun lines, DEGRADED, then FAILED after 3; `svc.counter` keeps AVAILABLE and increasing; heartbeats continuous; **no** clock anomaly | VM_MEASURED (WHPX, TCG) | PASS |
| S12 | stall (6 s step): `TSC_FORWARD_JUMP` and clock DEGRADED; time-dependent statuses UNKNOWN / `OBSERVATION_STALE`; never AVAILABLE afterwards; recorded as the misattribution limit | VM_MEASURED (WHPX), informational | PASS as described |
| S13 | status mapping: every combination of the inputs (state, installed, dependencies, freshness, clock, overruns) gives the row of section 5; compromise always NONE_KNOWN | SIMULATED | PASS |
| S14 | P-15 whitelist: the `PublicReason` names equal the Appendix A list parsed from the baseline (27, counted by script); an injected extra name FAILS the tool; a kernel diagnostic code cannot become a `PublicReason` (compile-fail, with twin); the only name in both registries is `ENTROPY_UNAVAILABLE`, already registered with its Appendix A meaning | SIMULATED + host | PASS; injected FAIL |
| S15 | liveness and compromise: LIVE, STALE, LOST and FAILED transitions never change compromise; no setter exists (static) | SIMULATED + host | PASS |
| S16 | degraded clock: before the injection `svc.counter` is AVAILABLE/LIVE; after it, UNKNOWN / `OBSERVATION_STALE` / liveness UNKNOWN on every report, while its value still increases; netmon and `dev.net0` unchanged | VM_MEASURED (`diag-tsc-backward`, `diag-tsc-jump`, WHPX + TCG) | PASS |
| S17 | INSPECT_PUBLIC: only `status`; unknown target `TARGET_UNKNOWN`; unknown operation `OPERATION_UNKNOWN`; start, stop, set and reset give `CAP_MISSING` and nothing changes | SIMULATED + VM (`diag-svc-refusals`) | PASS |
| S18 | refusals keep the kernel up: early start, unknown id and invalid transition refused; state unchanged; `svc.counter` still AVAILABLE; heartbeats continue | VM_MEASURED (WHPX, TCG) | PASS |
| S19 | cyclic table at boot: `registry=REFUSED`, no service STARTING or RUNNING, all UNAVAILABLE, kernel heartbeats continue | VM_MEASURED (WHPX, TCG) | PASS |
| S20 | events: SERVICE kind recorded; the second dump agrees with the `ABR|SVC` transition lines; dropped=0 on a clean boot; overflow and sequence behavior unchanged (hosted, 0.31b tests plus service records) | SIMULATED + VM | PASS |
| S21 | static checks: no allocator, no alloc crate, no dispatch (0.31b S001); no `loop`/`while` in production step code; no compromise setter; no reset call site; services do not read the log or call memory/paging/APIC/CPU | host (text and byte scans) | PASS |
| C12 | new harness condition (profile 0.32, every boot): exactly one `registry=OK` line after OPERATIONAL, with the order above; counter DECLARED to STARTING to RUNNING after `ready=PASS`; netmon withheld by `dev.net0`; status reports every 5 s with the exact grammar; reasons only Appendix A or NONE, parsed from the baseline; counter value strictly increasing and never above the loop wakes it could have used (`timer_irqs` + `spurious` + 1 probe, from the nearest preceding heartbeat); compromise NONE_KNOWN everywhere; second dump consistent | VM_MEASURED | PASS |
| J | C12 falsifications on copies of a real 0.32 log, each to fail for its intended reason. Cases: RUNNING with no readiness; RUNNING before OPERATIONAL; netmon AVAILABLE; `reason=FRAME_DOUBLE_RELEASE`; `reason=MADE_UP`; free text; compromise SUSPECTED; counter flat or falling; counter above its possible wakes; duplicate or missing registry line; AVAILABLE after a clock anomaly; STALE shown as AVAILABLE; event dump mismatch; dropped records; truncated log; out-of-order seq; injected `ABR|SVC` line before OPERATIONAL. Plus the 0.31b J001-J003 under profile 0.32 | host | every falsification FAIL, control PASS |
| R | regression on the final builds. Hosted: the 73 0.31b tests. VM: W/T cold C0-C12 (2 WHPX, 2 TCG); M warm C0-C12 (2 TCG); E exhaustion (WHPX, TCG); **D-ABR-012** N001-N006 (WHPX, TCG); N007/N008 lifecycle skip; F001-F005 faults (FAULTCTX may now include SERVICE); O001-O006; N009-N012 harness self-tests; G 0.29, 0.31a and 0.31b kernels under their profiles, the accepted 0.31b binary under profile 0.32 FAILS exactly C12, the 0.32 kernel under profile 0.31b PASSES C0-C11; repro; C7 series; inventory; 0.31b and 0.31a trees unchanged | mixed | as stated |

**Not counted or excluded:**
- WHPX warm reset (D-ABR-007, external edk2 defect).
- Guest-requested reboot (NOT_IMPLEMENTED).
- T01-T25 (their own revisions; S08 and S16 only prepare T07/T08).
- Hardware.

## 8. Reconciliation with `ABRAHAM_0.32_INTERFACE_SKETCH.md` (not approved; this design replaces it)

| Sketch | This design | Why |
|---|---|---|
| §2 `RESTARTING` and a bounded restart policy | removed; FAILED is terminal for the boot; manual reset reserved (R) | directive: no automatic restart in the first iteration; the clock may be DEGRADED |
| §3 a blocked dependent "stays STARTING or becomes UNAVAILABLE" | it stays **DECLARED** (start withheld); it is never STARTING | STARTING would claim a start that was never attempted |
| §4 example reasons `DEVICE_NOT_PRESENT`, `ADAPTER_NO_RESPONSE` | `NOT_INSTALLED` for `dev.net0`; no timeout reason | no driver is part of this configuration, and 0.32 has no timeouts |
| §5 each step "time-boxed ... returns within its declared budget" | bounded by construction; elapsed time measured **after** return; never called a timeout | directive Step 5 |
| §5 "repeated overruns make the service DEGRADED" | 1 overrun gives DEGRADED, 3 in a row give FAILED, 100 good steps recover | concrete values for review (Q4) |
| §6 SERVICE kind; status from the registry | kept; a second dump with distinct tags | keeps 0.31b C10 untouched |
| §8 S01-S12 | replaced by S01-S21 + C12 + J + R above | the directive's Step 8 list |
| not in the sketch | the 5 s stall versus TSC jump interaction; the reason-code gap; dependency lost at runtime; the build-path digest finding (V003) | found in this step |

## 9. Risks, and decisions for Jadin

| # | Question | Recommendation |
|---|---|---|
| Q1 | First services | `svc.counter` (positive case) and `svc.netmon` (dependency-negative), with **`dev.net0`** added as a not-installed placeholder adapter that netmon depends on. Netmon never claims network monitoring |
| Q2 | Restart policy | No automatic restart. FAILED is terminal for the boot. Cold restart (D-ABR-001) is the only restart in 0.32. The manual reset transition is designed and tested hosted, with no kernel call site, until a reviewed operator path exists |
| Q3 | Reason-code gap (rows marked * in section 5) | **(B)** For 0.32, `reason=NONE` with the cause on the diagnostic line. No baseline change; the counted boot uses only ratified codes. The alternative **(A)** is a ratified Appendix A revision first (e.g. `SERVICE_FAILED`, `DEPENDENCY_UNAVAILABLE`, `STEP_OVERRUN`): a STOP until ratified. B leaves §3C's "specific reason codes" unmet on those failure rows; that is recorded as an exception. Revisit before 0.33, whose launcher contract will need public failure reasons |
| Q4 | Parameters | step budget 1,000 µs; `MAX_WORK_UNITS` 64; counter 1 unit; FAILED after 3 overruns in a row; recovery after 100 good steps; freshness 1,000 ms; status report every 5 s |
| Q5 | Echo's 0.31b audit has not been delivered | The handoff planned to handle it before 0.32 opened. Proceed with implementation in parallel, accepting that a blocker found by Echo would require a 0.31c correction and a rebase of `work-0.32`? |
| - | `OBSERVATION_STALE` for a degraded clock | As carried in the sketch and the handoff: "freshness cannot be established" is treated as stale. Confirm this reading |

**Risks:**
1. The cooperative limit: a non-returning step hangs the kernel. Only the harness can see it.
2. The stall is misattributed as a TSC jump (fail-closed).
3. Event-log pressure if a service flaps between DEGRADED and AVAILABLE (bounded, and counted when dropped).
4. **Path-dependent kernel digests:** the identical 0.31b source built in `work-0.32` gives `53a1159b...`, not
   `ca847b03...`. The loaded sections are identical; `.symtab`/`.strtab` differ (V003). So regressions of 0.31b use
   the accepted binary, pinned by digest, and never a rebuild.
5. The schedule (0.4 by 2026-11-18) is an aim; correctness comes first.

## 10. Files the implementation would touch (after approval only)

- **New kernel files:**
  - `kernel/src/svcregistry.rs`, `svclife.rs`, `svcstatus.rs` (portable, no `unsafe`, hosted-tested);
  - `svcmgr.rs` (the kernel side: one static manager in a `KCell`, start phase, loop hook, lines, events);
  - `svc_counter.rs`;
  - `svcdiag.rs` (DIAGNOSTIC services only).
- **Changed kernel files:**
  - `main.rs` (start phase after the OPERATIONAL printout; one hook in the loop);
  - `events.rs` (`Kind::Service`);
  - `eventlog.rs` (`print_since`);
  - `clock.rs` (a read-only `degraded()` accessor);
  - `Cargo.toml` / `Cargo.lock` (version **0.32.0-dev**, five DIAGNOSTIC features);
  - `hosttest` (the new modules and tests).
- **Unchanged:** `frame.rs`, `memory.rs`, `paging.rs`, `ptwalk.rs`, `lifecycle.rs`, `init.rs`, `clockguard.rs`,
  `fault.rs`, `asm/entry.asm`.
- **Tools:**
  - `abr_boot_001.py` (profile 0.32, C12);
  - `g6/fault_probe.py` (SERVICE allowed in FAULTCTX under 0.32);
  - new in `tools/g032/`: `service_probe.py`, `judge_selftest_032.py`, `check_public_reasons.py`,
    `static_checks_032.py`, `campaign_032.py`, `evidence_index_032.py`, `make_audit_032.py`.
- **Documents:** `KERNEL_DIAGNOSTICS.md` §16-18, then after the tests: `PATCH_NOTES_0.32.md`,
  `0.32_OPERATOR_CHECKLIST.md`, `0.32_REVIEW.md`, the source diff, the evidence index and the Echo package, in that
  order (documents finished before indexing).

## 11. Invariants, with their scope and designed exceptions

- **No service is STARTING or RUNNING before kernel OPERATIONAL**, on every boot.
  *Exception:* none. `diag-svc-refusals` attempts it and must be refused.
- **No service is RUNNING without established readiness** (its own check and the kernel's count agree).
  *Exceptions by design:* `svc.diagready` and `svc.diagliar` in `diag-svc-defects` try and must end FAILED.
- **No dependent starts while a dependency is not RUNNING.**
- **Compromise is NONE_KNOWN on every status line of every 0.32 run.** Nothing can set it.
- **Every `reason=` value is an Appendix A code or NONE.**
  *Exception (Q3-B):* NONE where Appendix A has no fitting code, in DIAGNOSTIC and hosted cases only.
- **No time-dependent status is AVAILABLE while the clock is DEGRADED or unreadable.**
- **The event log drops nothing on a clean production boot.**
  *Exception:* overwrite is exercised hosted only; a flapping service could cause drops, which are counted.
- **All 0.31b invariants still hold:**
  - one memory owner;
  - ownership checks before OPERATIONAL;
  - the 7-transition kernel lifecycle;
  - no allocation and no dispatch;
  - uptime never decreases or wraps;
  - D-ABR-012 latches.
  *Exceptions:* only the DIAGNOSTIC builds that violate an invariant on purpose, which must stop.
