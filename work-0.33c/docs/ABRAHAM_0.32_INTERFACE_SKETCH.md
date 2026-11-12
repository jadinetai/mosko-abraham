# ABRAHAM 0.32 system-service architecture: interface sketch (NOT IMPLEMENTED)

- 2026-11-05. Prepared under the 0.31b directive ("Preparation for 0.32: architecture only"). Nothing here is
  built, ratified or accepted. 0.32 starts only after Jadin accepts 0.31b.
- Baseline rules it must respect: P-09/P-30 (authority decides, kernel enforces, grants revalidated at use),
  P-10 (COOPERATIVE until ring 3), P-13/P-33 (INSPECT_PUBLIC closed allow list), P-15 (Appendix A codes),
  P-35 (no sensitive data), P-41 (liveness separate from compromise), D-ABR-010/011 (kernel diagnostics stay
  separate from public codes).

## 1. Service identity and the registry

- `ServiceId` is an exact dotted name from a **closed, compiled table**: `svc.counter`, `svc.netmon`,
  `dev.mcu0` (adapter), and so on. No wildcards, no runtime registration, no names derived from input.
- The table entry for each service holds:
  - its declared dependencies;
  - its step budget;
  - its public status mapping;
  - whether it needs a grant (none may in 0.32).
- Adding a service is a reviewed code change, as P-33 requires for INSPECT_PUBLIC.

## 2. Service lifecycle (kernel-owned state machine, same style as 0.31b lifecycle.rs)

`DECLARED -> STARTING -> RUNNING -> STOPPING -> STOPPED`, any of these may go to `FAILED`, and `RESTARTING`
returns to `STARTING` only under a bounded restart policy.
- Transitions are refused exactly as the 0.31b initialization lifecycle refuses them, with a test matrix for each.
- Services start only after kernel `OPERATIONAL`, in dependency order.
- A service never claims RUNNING before its own readiness check passes.

## 3. Dependency and initialization ordering

- Dependencies form a static graph, ordered by a deterministic topological sort with ties broken by `ServiceId`.
  A cycle is refused at build time (table check) and again at boot.
- If a dependency is not RUNNING, the dependent stays STARTING or becomes UNAVAILABLE with an Appendix A reason.
  It never runs on assumption.

## 4. Truthful status (public interface: Appendix A codes only)

| Field | Values |
|---|---|
| status | AVAILABLE / DEGRADED / UNAVAILABLE / UNKNOWN (baseline §3C) |
| reason | an **Appendix A** code (e.g. `DEVICE_NOT_PRESENT`, `ADAPTER_NO_RESPONSE`, `OBSERVATION_STALE`) |
| liveness | LIVE / STALE / LOST / UNKNOWN (P-41) |
| compromise | NONE_KNOWN / SUSPECTED / CONFIRMED; never set by liveness loss; nothing sets it automatically |
| observed_at | monotonic ms in the boot clock domain (P-39). The clock is DEGRADED-aware: a degraded clock makes affected statuses `UNKNOWN` with `OBSERVATION_STALE`, never a false fresh value |

- **Reason-code governance:** status is a public interface, so under D-ABR-011 every reason used here must already be
  in Appendix A.
- Any new public code needs a ratified baseline revision first. Kernel diagnostic codes such as `FRAME_*` and
  `TSC_*` never appear in service status.

## 5. Execution model in 0.32 (no scheduler, no unbounded daemons)

- Services are **bounded cooperative steps** called from the kernel's main loop. Each step is time-boxed: it
  returns within its declared budget, measured with the guarded clock.
- An overrun is a recorded event, and repeated overruns make the service DEGRADED.
- Still ring 0 and labelled COOPERATIVE (P-10). No threads, no preemption, no heap. If a service needs storage,
  it gets fixed-size state in its table entry.

## 6. Events and errors

- Service lifecycle changes are recorded in the 0.31b event log under a new kernel-diagnostic kind
  (`SERVICE`, to be registered). The log stays record-and-read only (D-ABR-015). Status is read from the registry,
  not from the log.
- Error reports carry no payloads, no free text and no secrets (P-35), only registered codes and numbers.

## 7. Authority boundary

- **No 0.32 service mutates anything** that needs authority.
- When mutating services arrive, a Cyberforteca-compatible decision becomes a kernel-held grant, revalidated at every
  use (P-09/P-30). The service registry never decides authority itself.
- Binat and the launcher stay unimplemented until their scheduled revisions.

## 8. Proposed tests (for owner review; none written)

| ID | Test | Label |
|---|---|---|
| S01 | registry table: unique ids, exact names, no cycles; a cyclic table is refused | hosted |
| S02 | service lifecycle: full transition matrix, refusals change nothing, FAILED terminal except bounded restart | hosted |
| S03 | dependency order deterministic across runs and table permutations | hosted |
| S04 | dependency down: dependent never RUNNING; status UNAVAILABLE with an Appendix A reason | hosted + VM |
| S05 | status uses Appendix A codes only; a kernel diagnostic code in a status is rejected (D-ABR-011 check) | hosted |
| S06 | liveness loss never sets compromise (P-41) | hosted + VM |
| S07 | step budget overrun: event recorded, DEGRADED after N overruns, other services keep running | VM |
| S08 | degraded clock: affected statuses UNKNOWN / OBSERVATION_STALE, never a fresh value | VM (diag-tsc builds) |
| S09 | services start only after OPERATIONAL; a failed kernel lifecycle starts none | VM |
| S10 | INSPECT_PUBLIC status query is a closed allow list; unknown target refused (`TARGET_UNKNOWN`) | hosted + VM |
| S11 | no service holds or uses authority in 0.32 (static check plus a refused mutating call) | hosted |
| S12 | harness C12 for service status, with judge falsifications like 0.31b C9-C11 | host |

## 9. Owner questions for the 0.32 design checkpoint (later)

1. The first services to build: `svc.counter` (local work, T08) and `svc.netmon` (network-dependent, T07)?
2. Bounded cooperative steps for 0.32, with preemption deferred to 0.4?
3. The restart policy: none, or N attempts with a backoff measured on the guarded clock?
