# Abraham kernel diagnostic codes (registry)

- Kernel 0.32.0-dev (ABRAHAM 0.32: sections 16-18 added; sections 12-15 came with 0.31b). Created 2026-11-05 for 0.31a on
  Jadin's instruction (D-ABR-012).
- **Scope (D-ABR-010, D-ABR-011):** these are **kernel diagnostic codes**. They appear only on the
  kernel's serial diagnostic lines (`ABR|...`). They are **not** Appendix A reason codes of the 0.2
  baseline. Before any of them is used in a public service, authorization or application interface
  (status model, DecisionRecord, ExecutionReport, syscalls, launcher or service contracts), it must
  first enter Appendix A through a ratified baseline revision.
- **Rule:** every code the kernel can print is listed here, once, with its meaning and behavior.
  A new code is added to this file in the same change that introduces it.
  `tools/g031/check_diag_codes.py` scans `kernel/src/*.rs` and `kernel/asm/entry.asm` and fails if the
  kernel source contains a code that is not registered here.
- **0.32:** `tools/g032/check_codes_032.py` applies the same rule with the 0.32 service fields added to the keyed
  scan (`status=`, `liveness=`, `compromise=`, `clock=`, `start=`, `registry=`, `result=`, `ready=`, `diag=`,
  `status_change=`, `kind=`). The 27 **Appendix A reason codes are not listed here**: they come from the ratified
  baseline, and only `kernel/src/svcstatus.rs` may name them (`PublicReason::name`). The checker fails if one is
  written anywhere else. `ENTROPY_UNAVAILABLE` is the one code in both registries (section 3).
- **0.32 rule for service lines (D-ABR-011, D-ABR-019):** a kernel diagnostic code appears only in a `diag=` field
  of an `ABR|SVC` line. A `reason=` field of `ABR|SVCSTATUS` / `ABR|SVCQUERY` carries only an Appendix A code or
  `NONE` (no fitting code: design Q3 option B).
- Severity: **STOP** = the kernel halts (`cli; hlt`) and never reports OPERATIONAL. **SERIOUS** = an
  allocator invariant violation (D-ABR-012): the allocator latches FAULTED and the kernel stops.
  **REFUSED** = the operation is refused with the code, nothing changes, and the kernel continues.
  **INFO** = a report only. **DIAG** = printed only by a DIAGNOSTIC build, never by an accepted kernel.

## 1. Line tags

| Code | Printed by | Meaning |
|---|---|---|
| `ENTRY` | entry.asm | NASM entry reached (`ABR|ENTRY|...`) |
| `STAGE` | main.rs | boot stage reached (kmain, descriptor tables, timer) |
| `BOOTINFO` | main.rs | what the loader handed over |
| `BANNER` | main.rs | identification banner |
| `STATE` | main.rs | `OPERATIONAL` |
| `TICK` | main.rs | one heartbeat per elapsed TSC second |
| `FAULT` | cpu.rs, main.rs, memory.rs | a fault that stops the kernel (STOP) |
| `DIAG` | main.rs, memory.rs | a diagnostic build announcing what it injects (DIAG) |
| `MEMMAP` | memory.rs | one Limine memory-map entry (0.31a) |
| `MEMLEDGER` | memory.rs | one ledger reservation and the pool frames it removed (0.31a) |
| `MEM` | memory.rs | allocator state, anomalies, serious-violation details (0.31a) |
| `MEMCHECK` | memory.rs | live ownership check result or violation (0.31a) |
| `MEMPIN` | memory.rs | one pinned page-table frame (0.31a) |
| `MEMTEST` | memtest.rs | exhaustion test steps and summary (DIAG, 0.31a) |
| `PROBE` | memprobe.rs | Step 2 memory-map probe (DIAG, 0.31a) |

## 2. Fault reasons (`ABR|FAULT|reason=...`, all STOP)

| Code | Since | Meaning |
|---|---|---|
| `LIMINE_BASE_REVISION_UNSUPPORTED` | 0.1.0 | the loader did not accept base revision 6 |
| `TIMER_UNAVAILABLE` | 0.1.0 | the APIC timer could not be started; `detail=` says why (section 3) |
| `PANIC` | 0.1.0 | Rust panic |
| `FRAME_ALLOCATOR_UNAVAILABLE` | 0.31a | no memory owner could be established; `detail=` says why |
| `FRAME_OWNERSHIP_COLLISION` | 0.31a | **SERIOUS.** A live frame (page table, kernel image, device page, frame 0) is free or in the pool (`source=MEMCHECK`), or the allocator was about to hand one out (`source=ALLOCATOR`, frame quarantined, never returned) |
| `FRAME_OWNERSHIP_CHECK_FAILED` | 0.31a | the live ownership check failed for a reason other than a collision (section 6) |
| `FRAME_DOUBLE_RELEASE` | 0.31a | **SERIOUS.** A frame that was already free was released again; the free pool is unchanged |
| `MEMTEST_FAILED` | 0.31a | DIAG: the exhaustion test failed |
| CPU exception names | 0.1.0 | `ABR|FAULT|vector=...|name=...` uses the names in section 10, not `reason=` |

## 3. Fault details (`detail=...`)

| Code | With | Meaning |
|---|---|---|
| `NO_HHDM` | TIMER_UNAVAILABLE, FRAME_ALLOCATOR_UNAVAILABLE | the loader gave no higher-half direct map |
| `LA57_UNSUPPORTED` | TIMER_UNAVAILABLE | 5-level paging is active (never requested) |
| `HUGE_PAGE_ON_PATH` | TIMER_UNAVAILABLE | a large page sits where the APIC mapping needs a table |
| `NO_FREE_FRAME` | TIMER_UNAVAILABLE | 0.29 bump allocator exhausted. Since 0.31a only in the DIAG `diag-legacy-collision` build; the 0.31a kernel reports the allocator code instead (e.g. `OUT_OF_MEMORY`) |
| `APIC_GLOBALLY_DISABLED` | TIMER_UNAVAILABLE | IA32_APIC_BASE enable bit clear |
| `PIT_OUT2_NOT_LOW` | TIMER_UNAVAILABLE | PIT channel 2 did not start low |
| `PIT_TIMEOUT` | TIMER_UNAVAILABLE | PIT calibration window never ended |
| `CALIBRATION_OUT_OF_RANGE` | TIMER_UNAVAILABLE | APIC count outside the plausible window |
| `TSC_CALIBRATION_OUT_OF_RANGE` | TIMER_UNAVAILABLE | TSC below 50 MHz |
| `DIAG_INJECTED_EARLY_INIT_FAILURE` | TIMER_UNAVAILABLE | DIAG `diag-early-fail` |
| `NO_EXECUTABLE_ADDRESS` | FRAME_ALLOCATOR_UNAVAILABLE | no Executable Address response: the kernel image cannot be reserved |
| `KERNEL_VIRTUAL_BASE_MISMATCH` | FRAME_ALLOCATOR_UNAVAILABLE | the loader's virtual base differs from the link address |
| Allocator states and errors | FRAME_ALLOCATOR_UNAVAILABLE, TIMER_UNAVAILABLE | e.g. `EMPTY`, `OUT_OF_MEMORY` (sections 4, 5) |
| `ENTROPY_UNAVAILABLE` | banner `reason=` | no RDRAND; status DEGRADED (P-11). This is also an Appendix A code; the banner uses it in the Appendix A sense |

## 4. Frame allocator errors (`frame.rs`, `FrameError::code`)

| Code | Severity | Meaning |
|---|---|---|
| `OUT_OF_MEMORY` | REFUSED | no free frame; nothing written, no fallback; counted. A page table that cannot be allocated stops the boot through TIMER_UNAVAILABLE |
| `FRAME_ALLOCATOR_NOT_READY` | REFUSED | used before init |
| `FRAME_ALLOCATOR_ALREADY_INITIALIZED` | REFUSED | second init |
| `FRAME_MISALIGNED` | REFUSED | release of a non-page-aligned address |
| `FRAME_OUT_OF_RANGE` | REFUSED | release at or above the managed limit (4 GiB) |
| `FRAME_NOT_OWNED` | REFUSED | release of a reserved, pinned or never-usable frame (page tables, kernel, APIC, frame 0) |
| `FRAME_DOUBLE_RELEASE` | **SERIOUS** | release of a free frame; latches FAULTED; free pool unchanged |
| `FRAME_OWNERSHIP_COLLISION` | **SERIOUS** | the next free frame is live; quarantined, not returned; latches FAULTED |
| `FRAME_ALLOCATOR_FAULTED` | REFUSED | every operation after a serious violation |
| `FRAME_ALLOCATOR_BUSY` | REFUSED | re-entry (no lock to wait on) |
| `FRAME_STATE_INCONSISTENT` | REFUSED | a free bit without its pool bit; nothing handed out |

## 5. Allocator states (`ABR|MEM|state=...`)

| Code | Meaning |
|---|---|
| `UNINITIALIZED` | before init |
| `READY` | the pool holds frames |
| `EMPTY` | initialized with nothing allocatable: boot stops (FRAME_ALLOCATOR_UNAVAILABLE) |
| `FAULTED` | latched after a serious violation; never left |

## 6. Ownership-check violations (`ABR|MEMCHECK|...|violation=...`)

Collision class (fault reason FRAME_OWNERSHIP_COLLISION):

| Code | Meaning |
|---|---|
| `PT_FRAME_FREE` | a live page-table frame is in the allocator's free set (the F-029-01 case) |
| `PT_FRAME_UNACCOUNTED` | a live page-table frame is neither bootloader-reclaimable nor a pinned allocator frame |
| `KERNEL_FRAME_IN_POOL` | a frame of the running kernel image is in the pool |
| `MMIO_FRAME_IN_POOL` | the APIC register page is in the pool |
| `FRAME0_IN_POOL` | physical frame 0 is in the pool |
| `POOL_OUTSIDE_USABLE` | some pool frame lies outside every USABLE map entry |

Other (fault reason FRAME_OWNERSHIP_CHECK_FAILED):

| Code | Meaning |
|---|---|
| `FREE_OUTSIDE_POOL` | a free bit without its pool bit |
| `FREE_COUNT_MISMATCH` | the free counter differs from the free bitmap |
| `PIN_LOG_OVERFLOW` | more pinned frames than can be listed, so pinning can't be verified |
| `LIVE_TABLE_LIST_OVERFLOW` | more live page tables than the allocation guard can remember |
| `KERNEL_PAGE_UNMAPPED` | a kernel-image page does not translate |
| `KERNEL_NOT_CONTIGUOUS` | the kernel image is not where the loader said (reservation would be wrong) |
| `ALLOCATOR_FAULTED` | the allocator had already latched a serious violation |
| `CHECK_NOT_RUN` | the check could not get the allocator (re-entry) |

## 7. Memory-map anomalies (`ABR|MEM|anomaly|code=...`, INFO; each accounted for safely)

| Code | Handling |
|---|---|
| `ZERO_LENGTH` | entry skipped |
| `RANGE_OVERFLOW` | USABLE rejected; other types reserved up to the 52-bit limit |
| `USABLE_MISALIGNED` | trimmed inward to whole frames |
| `UNSORTED` | processed order-independently |
| `USABLE_DUPLICATE` | frames counted once |
| `RESERVED_OVERLAPS_USABLE` | every touched frame removed (reserved wins) |
| `UNKNOWN_TYPE` | treated as reserved |
| `RESERVATION_INVALID` | ledger entry zero-length (skipped) or overflowing (reserved to the limit) |

The 0.31a harness (C9) requires 0 anomalies on the tested VM: Limine guarantees a clean map there.

## 8. Exhaustion-test findings (`ABR|MEMTEST|violation=...`, DIAG)

| Code | Meaning |
|---|---|
| `INVALID_FRAME_HANDED_OUT` | the allocator returned a frame that fails the independent pre-write check; it is never written |
| `FRAME_CONTENT_CHANGED` | a frame's tag or pattern changed after it was written |

## 9. Ledger and pin owners, memory-map types

| Code | Kind | Meaning |
|---|---|---|
| `LOW_1MIB` | ledger owner | physical 0-1 MiB |
| `KERNEL_IMAGE` | ledger owner | the running kernel image |
| `MMIO` | ledger owner | device register page (local APIC) |
| `TEST` | ledger owner | host tests only |
| `PAGE_TABLE` | pin owner | a page table Abraham created (pinned, never released) |
| `USABLE` | map type | Limine type 0 |
| `RESERVED` | map type | 1 |
| `ACPI_RECLAIMABLE` | map type | 2 |
| `ACPI_NVS` | map type | 3 |
| `BAD_MEMORY` | map type | 4 |
| `BOOTLOADER_RECLAIMABLE` | map type | 5 (kept reserved in 0.31) |
| `EXECUTABLE_AND_MODULES` | map type | 6 |
| `FRAMEBUFFER` | map type | 7 |
| `RESERVED_MAPPED` | map type | 8 |
| `UNKNOWN_TYPE` | map type | any other value (also an anomaly) |
| `NOT_IN_MEMMAP` | probe | DIAG probe: an address in no map entry |

## 10. CPU exception names (`ABR|FAULT|vector=...|name=...`, STOP)

| Code | Vector |
|---|---|
| `DIVIDE_ERROR` | 0 |
| `DEBUG` | 1 |
| `NMI` | 2 |
| `BREAKPOINT` | 3 |
| `OVERFLOW` | 4 |
| `BOUND_RANGE` | 5 |
| `INVALID_OPCODE` | 6 |
| `DEVICE_NOT_AVAILABLE` | 7 |
| `DOUBLE_FAULT` | 8 |
| `COPROCESSOR_SEGMENT` | 9 |
| `INVALID_TSS` | 10 |
| `SEGMENT_NOT_PRESENT` | 11 |
| `STACK_FAULT` | 12 |
| `GENERAL_PROTECTION` | 13 |
| `PAGE_FAULT` | 14 |
| `RESERVED_15` | 15 |
| `X87_FP` | 16 |
| `ALIGNMENT_CHECK` | 17 |
| `MACHINE_CHECK` | 18 |
| `SIMD_FP` | 19 |
| `VIRTUALIZATION` | 20 |
| `CONTROL_PROTECTION` | 21 |
| `RESERVED_22` | 22 |
| `RESERVED_23` | 23 |
| `RESERVED_24` | 24 |
| `RESERVED_25` | 25 |
| `RESERVED_26` | 26 |
| `RESERVED_27` | 27 |
| `HYPERVISOR_INJECTION` | 28 |
| `VMM_COMMUNICATION` | 29 |
| `SECURITY` | 30 |
| `RESERVED_31` | 31 |
| `UNEXPECTED` | any vector above 31 that is not the timer or spurious vector |

## 11. Result words

| Code | Meaning |
|---|---|
| `PASS` | a check or test passed |
| `FAIL` | a check or test failed |
| `HANDED_OUT` | in a serious-violation report: the probe allocation succeeded. Must never appear: the allocator is FAULTED by then |
| `NONE` | 0.31b: a value that is not known (uptime before the clock started). Never replaced by a fake 0 |
| `BUSY` | 0.31b: the lifecycle state could not be read at that instant (a fault inside a transition) |

## 12. 0.31b line tags

| Code | Printed by | Meaning |
|---|---|---|
| `INIT` | init.rs | lifecycle transition `ABR|INIT|seq=n|from=X|to=Y` (to FAILED adds `reason=`); a refused one prints `ABR|INIT|refused|from=X|to=Y` |
| `EVENTS` | eventlog.rs | event-log summary at OPERATIONAL: recorded, dropped, capacity, lost_reentrant |
| `EVENT` | eventlog.rs | one event-log record at OPERATIONAL |
| `FAULTCTX` | eventlog.rs | one of the newest event records, dumped after a FAULT line (at most 8) |
| `FAULT_END` | fault.rs | end of a fault report: `events_dumped=n` |
| `CLOCK` | main.rs | a clock anomaly, and once per boot the DEGRADED state (F-029-04) |

## 13. Lifecycle states (lifecycle.rs) and the refusal code

| Code | Meaning |
|---|---|
| `EARLY` | kmain entered, console up (initial state) |
| `LOADER_VERIFIED` | the loader accepted base revision 6 |
| `MEMORY_OWNED` | the frame allocator owns USABLE memory |
| `MEMORY_VERIFIED` | ownership check `init` passed |
| `CPU_TABLES_LOADED` | the kernel's GDT, TSS and IDT are loaded |
| `TIMER_RUNNING` | the APIC timer and the TSC clock are running |
| `OWNERSHIP_VERIFIED` | ownership check `timer` passed (after the APIC page tables were created) |
| `OPERATIONAL` | the first timer interrupt was handled; reported only through the lifecycle |
| `FAILED` | terminal; entered by every fault report |
| `INIT_INVALID_TRANSITION` | STOP: a transition that skips, goes back, repeats or leaves FAILED was requested; fault reason |

## 14. Event log (events.rs; ABR-031-EVT-01, D-ABR-015/016)

| Code | Kind | Meaning, argument |
|---|---|---|
| `INIT` | kind | a lifecycle transition; code = the state entered, arg = its seq |
| `MEMORY` | kind | memory ownership |
| `TIMING` | kind | timer and clock |
| `FAULT` | kind | a fault report; code = the fault reason or exception name |
| `ALLOCATOR_READY` | MEMORY | the allocator owns its pool; arg = pool frames |
| `MEMCHECK_PASS` | MEMORY | an ownership check passed; arg = stage (1 init, 2 timer, 3 after_exhaust, 4 after_release) |
| `MEMCHECK_FAIL` | MEMORY | an ownership check failed; arg = violations |
| `TIMER_STARTED` | TIMING | the APIC timer and TSC clock started; arg = TSC Hz |

## 15. Clock (clockguard.rs, F-029-04; INFO, the kernel keeps running)

| Code | Meaning |
|---|---|
| `TSC_BACKWARD` | a reading lower than the previous one; uptime holds (adds 0), re-based; arg = counts back |
| `TSC_FORWARD_JUMP` | more than 5 s between consecutive readings; kept in uptime (fail-closed for expiry); arg = counts |
| `HEARTBEAT_GAP` | more than 5 missing heartbeat seconds; reported once instead of printed one by one; arg = seconds skipped |
| `DEGRADED` | after the first clock anomaly, for the rest of the boot: uptime is no longer claimed accurate (`uptime_claimed_accurate=false`) |

Every heartbeat carries `clock_anomalies=n` (the number of `ABR|CLOCK|anomaly=` lines so far).

## 16. 0.32 line tags

| Code | Printed by | Meaning |
|---|---|---|
| `SVC` | svcmgr.rs | a service-manager line: registry result, a start that was refused, skipped or withheld, a transition `ABR|SVC|id=..|seq=n|from=X|to=Y` (to FAILED or STOPPING adds `diag=`), a refused request, readiness, an overrun, an unmeasured step, a status change |
| `SVCSTATUS` | svcmgr.rs | the public status of one table entry (design §5): once after the start phase, then every 5 s, every entry in table order |
| `SVCEVENTS` | eventlog.rs | once, after the service start phase: the summary of the records appended since the OPERATIONAL printout (`from_seq`, recorded, dropped, capacity, lost_reentrant) |
| `SVCEVENT` | eventlog.rs | one of those records (same fields as `EVENT`) |
| `SVCQUERY` | svcmgr.rs | DIAG (`diag-svc-refusals`): one INSPECT_PUBLIC answer: `result=OK` with a status, or `result=REFUSED` with an Appendix A reason |

## 17. Service registry, lifecycle and steps (svcregistry.rs, svclife.rs, svcrun.rs, svcmgr.rs, svc_counter.rs)

Every case here leaves the kernel running. A service problem never stops the kernel, and never produces a success.

| Code | Kind | Meaning |
|---|---|---|
| `DECLARED` | service state | in the table, not started (the initial state) |
| `STARTING` | service state | start hook and readiness probe in progress |
| `RUNNING` | service state | readiness established; stepped from the main loop |
| `STOPPING` | service state | being stopped because a dependency left RUNNING |
| `STOPPED` | service state | stopped; no automatic restart. `FAILED` (section 13) is also the terminal service state |
| `SERVICE` | entry kind; event kind | a service table entry; the 0.32 event-log kind for service records |
| `ADAPTER` | entry kind | an adapter table entry (`dev.net0`) |
| `REFUSED` | result word | `registry=REFUSED`, `start=REFUSED`, `result=REFUSED` (SVCQUERY) |
| `SKIPPED` | result word | `start=SKIPPED`: the entry is not installed in this configuration |
| `WITHHELD` | result word | `start=WITHHELD`: a dependency is not RUNNING; the entry stays DECLARED |
| `RECOVERED` | result word | `status_change=RECOVERED`: 100 in-budget steps in a row ended the overrun window |
| `SVC_REGISTRY_OK` | SERVICE event | the table passed the boot-time check; arg = entries |
| `SVC_REGISTRY_REFUSED` | SERVICE event | the table failed the boot-time check, so no service starts; arg = entry position |
| `SVC_TOO_MANY_ENTRIES` | registry refusal | more than 8 entries |
| `SVC_NAME_MALFORMED` | registry refusal | a name outside the exact-name grammar |
| `SVC_TOO_MANY_DEPENDENCIES` | registry refusal | more than 4 dependencies |
| `SVC_BUDGET_TOO_LARGE` | registry refusal | a work budget above 64 units |
| `SVC_DUPLICATE_ID` | registry refusal | two entries with the same id |
| `SVC_DUPLICATE_NAME` | registry refusal | two entries with the same name |
| `SVC_SELF_DEPENDENCY` | registry refusal | an entry depends on itself |
| `SVC_UNKNOWN_DEPENDENCY` | registry refusal | a dependency id not in the table |
| `SVC_DUPLICATE_DEPENDENCY` | registry refusal | a dependency listed twice |
| `SVC_DEPENDENCY_CYCLE` | registry refusal | the dependencies form a cycle |
| `SVC_START_REFUSED` | SERVICE event | a start request that was refused (arg 0); the line names the diagnostic |
| `SVC_KERNEL_NOT_OPERATIONAL` | start refusal | start requested while the kernel lifecycle is not OPERATIONAL; nothing changes |
| `SVC_ALREADY_STARTED` | start refusal | a second start request; nothing changes |
| `SVC_MANAGER_BUSY` | start refusal | the manager was in use at that instant (re-entry); nothing changes |
| `SVC_NOT_INSTALLED` | SERVICE event | an entry skipped because it is not installed; arg = id |
| `SVC_START_WITHHELD` | SERVICE event | a start withheld because a dependency is not RUNNING; arg = id << 8, or-ed with the dependency id |
| `SVC_DECLARED` | SERVICE event | reserved for a manual reset back to DECLARED. The 0.32 kernel has no call site for it |
| `SVC_STARTING` | SERVICE event | transition to STARTING; arg = id << 8, or-ed with seq |
| `SVC_RUNNING` | SERVICE event | transition to RUNNING; arg = id << 8, or-ed with seq |
| `SVC_STOPPING` | SERVICE event | transition to STOPPING; arg = id << 8, or-ed with seq |
| `SVC_STOPPED` | SERVICE event | transition to STOPPED; arg = id << 8, or-ed with seq |
| `SVC_FAILED` | SERVICE event | transition to FAILED; arg = id << 8, or-ed with seq. The line's `diag=` gives the cause |
| `SVC_INVALID_TRANSITION` | refusal; SERVICE event | a requested (from, to) pair that is not in the matrix; state unchanged; arg = id << 16, from << 8, to |
| `SVC_TRANSITION_MANAGER_ONLY` | refusal; SERVICE event | an external request for a pair that is in the matrix: only the manager makes transitions; state unchanged |
| `SVC_READINESS_FAILED` | FAILED cause | the start hook, the probe step or the service's own readiness check failed |
| `SVC_READINESS_CONTRADICTED` | FAILED cause | readiness claimed, but the probe did no work, or the observable state differs from the units the kernel counted |
| `SVC_CONTRACT_VIOLATION` | FAILED cause | a step used more work units than its budget, or its observable state differs from the kernel's count |
| `SVC_STEP_OVERRUN` | overrun; FAILED cause | a step's elapsed time, measured after it returned, exceeded 1,000 us (never a timeout); 3 in a row make the service FAILED |
| `SVC_STEP_UNMEASURED` | step | the after-reading was below the before-reading: the step is neither in budget nor a success |
| `SVC_DEGRADED` | SERVICE event | the first overrun of a window: the service is DEGRADED; arg = id |
| `SVC_RECOVERED` | SERVICE event | the overrun window ended; arg = id |
| `SVC_DEPENDENCY_LOST` | STOPPING cause | a dependency left RUNNING; the dependent is stopped (dependents first) and never restarted |
| `SVC_NO_BEHAVIOR` | start/step refusal | a table entry with no behavior compiled in (never reached in 0.32: netmon is withheld) |
| `SVC_COUNTER_NOT_READY` | readiness | `svc.counter` has not done its probe step |
| `SVC_COUNTER_OVERFLOW` | FAILED cause | `svc.counter` at its maximum value: the step fails instead of wrapping |
| `SVC_DIAG_NOT_READY` | readiness, DIAG | `svc.diagready` (diag-svc-defects): its own readiness check fails by design |

## 18. Public status vocabulary (svcstatus.rs; baseline §3C, P-41)

These are the status, liveness, compromise and clock words printed on `ABR|SVCSTATUS` lines. They are listed so that
the scanner can account for every printed word. They are the ratified status vocabulary, not kernel diagnostic
codes. `DEGRADED` (section 15) is also a status word. The `reason=` values are not listed here; see the 0.32 rule at
the top.

| Code | Field | Meaning |
|---|---|---|
| `AVAILABLE` | status | usable now: RUNNING, its last step fresh (< 1,000 ms), no overrun window. Also the banner's status |
| `UNAVAILABLE` | status | not usable: not installed, withheld, not started, stopping, stopped or FAILED |
| `UNKNOWN` | status; liveness | cannot be stated freshly (degraded clock or stale observation); liveness not observable |
| `LIVE` | liveness | RUNNING, and its last completed step is fresh |
| `STALE` | liveness | RUNNING, but its last completed step is older than the freshness limit |
| `LOST` | liveness | FAILED: known not to be alive |
| `NONE_KNOWN` | compromise | the only value 0.32 can produce (P-41: liveness loss never sets compromise) |
| `SUSPECTED` | compromise | vocabulary only: nothing in 0.32 can set it |
| `CONFIRMED` | compromise | vocabulary only: nothing in 0.32 can set it |
| `OK` | clock | the clock guard has not latched DEGRADED |
| `UNREADABLE` | clock | the guard was in use at that instant; treated like DEGRADED (fail-closed) |

## 19. 0.32b additions (D-ABR-020)

| Code | Kind | Meaning |
|---|---|---|
| `SVC_DIAG_INJECTED_STEP_ERROR` | FAILED cause, DIAG | `svc.diagflaky` (diag-svc-cascade): its 3rd loop step fails by design, while `svc.diagdep2` depends on it |
| `IN_BUDGET` | step timing | `probe_timing=IN_BUDGET`: the probe step's elapsed time, measured after it returned, was within 1,000 us |
| `OVERRUN` | step timing | `probe_timing=OVERRUN`: the probe overran; it counts as the first overrun (DEGRADED, never AVAILABLE on it) |
| `UNMEASURED` | step timing | `probe_timing=UNMEASURED`: the probe's time could not be measured; it is not a fresh success, and the entry is not AVAILABLE until a measured step completes |

## 20. 0.33 line tags (D-ABR-022; design §9)

| Code | Printed by | Meaning |
|---|---|---|
| `APP` | launchpad.rs | `ABR|APP|registry=OK|entries=..|order=..|executor=ABSENT` or `registry=REFUSED|diag=APP_...|entry=..`: the boot-time check of the application table, once |
| `APPINFO` | launchpad.rs | discovery: one line per registered application with every status round (and after a `status app.<name>` query): kind, revision, exec, requirements, prerequisites, unavailable services with their own public status and reason |
| `APPQUERY` | launchpad.rs, DIAG | an allowed INSPECT_PUBLIC read (`status app.<name>`, `list app`) answered from the registry |
| `LAUNCH` | launchpad.rs, DIAG | one request transition (`req=..|seq=..|from=..|to=..`), a routed service request (`routed=SERVICE`), or a refused external transition and the unchanged state |
| `LAUNCHRESULT` | launchpad.rs, DIAG | the result of one launch request: every fact, the terminal state, the stage that decided, `result=NOT_EXECUTED`, `executed=NO`, `process=NONE`, the Appendix A `reason=` and the diagnostic `diag=` |
| `LAUNCHPAD` | launchpad.rs, DIAG | the script summary: requests, refused, not executed, discovery, routed, `executed=` (counted), `processes=0`, executor |

## 21. Application registry and launcher words (appregistry.rs, apptable.rs, launchreq.rs, launchlife.rs, launch.rs)

Registry refusals (`ABR|APP|registry=REFUSED|diag=...`; the whole table is refused, the services are unaffected):

| Code | Kind | Meaning |
|---|---|---|
| `APP_TOO_MANY_ENTRIES` | registry refusal | more than MAX_APPS (8) entries |
| `APP_NAME_MALFORMED` | registry refusal | not `app.` + lowercase `[a-z0-9]` segments, or over 31 bytes |
| `APP_TOO_MANY_REQUIREMENTS` | registry refusal | more than 4 required services |
| `APP_DUPLICATE_ID` | registry refusal | two entries with one AppId |
| `APP_DUPLICATE_NAME` | registry refusal | two entries with one name |
| `APP_UNKNOWN_REQUIREMENT` | registry refusal | a required service id that is not in the service table |
| `APP_DUPLICATE_REQUIREMENT` | registry refusal | a service listed twice |
| `APP_EXEC_CLAIM_UNSUPPORTED` | registry refusal | `exec=NATIVE` while no executor exists: an application falsely advertised as executable |

Descriptor and platform words:

| Code | Field | Meaning |
|---|---|---|
| `VIEWER` | kind | an application that presents information |
| `BROWSER` | kind | the browser placeholder (`app.browser`; its requirement is provisional, Echo Recommendation 3) |
| `TOOL` | kind | a utility (DIAGNOSTIC tables only in 0.33) |
| `NATIVE` | exec | reserved for 0.4 (an independent ring-3 image); refused by the registry check in 0.33 |
| `ABSENT` | executor | no process loader exists: nothing can execute in 0.33 |

Request facts and result words (`ABR|LAUNCHRESULT`):

| Code | Field | Meaning |
|---|---|---|
| `INSPECT_PUBLIC` | class | P-13 class of status, list, show |
| `INSPECT_PROTECTED` | class | P-13 class of inspect (needs a capability) |
| `MUTATE` | class | P-13 class of start, stop, set, reset (needs a capability) |
| `FRESH` | admission | the request id is greater than the last admitted id of this boot |
| `NOT_INCREASING` | admission | it is not: refused with `REQUEST_REPLAYED`. An ordering check, not authenticated replay protection (Echo Recommendation 3) |
| `WELL_FORMED` | structure | the text parses |
| `MALFORMED` | structure; target | the text does not parse; as a target, the target is not echoed (`target_len=` only) |
| `NOT_EVALUATED` | any fact | an earlier gate refused the request, so this fact was not evaluated |
| `YES` | known | the target is an application in the valid registry (or the collection `app` for `list`) |
| `SATISFIED` | prerequisites | every required service is AVAILABLE |
| `UNSATISFIED` | prerequisites | at least one is not; each is listed in `unavailable=` with its own status and reason |
| `PRESENTED` | capability | a capability token was given (never echoed) |
| `NO_AUTHORITY` | authorization | a capability was presented, but no authority mechanism exists: `AUTHZ_UNAVAILABLE` |
| `NOT_EXECUTED` | state; result | validated, then stopped; nothing ran (P-22 result vocabulary) |
| `ADMISSION` | stage | decided by the request id |
| `STRUCTURE` | stage | decided by the parser |
| `OPERATION` | stage | the operation word is unknown, or not defined for applications |
| `RECOGNITION` | stage | the target is not a known application |
| `AUTHORIZATION` | stage | refused for lack of authority (every validated 0.33 request) |

Request states (launchlife.rs; `REFUSED`, `RUNNING`, `FAULTED` and `LOST` are registered above):

| Code | Meaning |
|---|---|
| `SUBMITTED` | the request was received |
| `VALIDATED` | admitted, well-formed and known: NOT an acceptance to run |
| `DISPATCHED` | reserved for 0.4; refused in 0.33 |
| `EXITED` | reserved for 0.4 (an observed exit); refused in 0.33 |

Diagnostic codes (`diag=` only, D-ABR-010/011):

| Code | Public reason | Meaning |
|---|---|---|
| `LAUNCH_ID_NOT_INCREASING` | `REQUEST_REPLAYED` | the id is not greater than the last admitted one |
| `LAUNCH_PARSE_EMPTY` | `PARSE_ERROR` | empty text |
| `LAUNCH_PARSE_TOO_LONG` | `PARSE_ERROR` | more than 64 bytes |
| `LAUNCH_PARSE_BYTE` | `PARSE_ERROR` | a byte outside printable ASCII |
| `LAUNCH_PARSE_SPACING` | `PARSE_ERROR` | a leading, trailing or double space |
| `LAUNCH_PARSE_NO_TARGET` | `PARSE_ERROR` | an operation with no target |
| `LAUNCH_PARSE_TARGET_MALFORMED` | `PARSE_ERROR` | the target matches no name grammar (upper case, wildcard, ...) |
| `LAUNCH_PARSE_NO_CAPABILITY` | `PARSE_ERROR` | `as` with nothing after it |
| `LAUNCH_PARSE_CAPABILITY_MALFORMED` | `PARSE_ERROR` | a capability token of the wrong shape |
| `LAUNCH_PARSE_PARAMETER` | `PARSE_ERROR` | a `key=value` token (0.33 accepts no parameters) |
| `LAUNCH_PARSE_TRAILING` | `PARSE_ERROR` | extra tokens |
| `LAUNCH_PARSE_NOT_EVALUATED` | `PARSE_ERROR` | fail-closed value of `decide` for facts with no structure verdict (not produced by `submit`) |
| `LAUNCH_OPERATION_UNKNOWN` | `OPERATION_UNKNOWN` | not in the table, or not defined for applications (e.g. `show app.x`) |
| `LAUNCH_TARGET_UNKNOWN` | `TARGET_UNKNOWN` | a well-formed `app.` name not in the registry |
| `LAUNCH_REGISTRY_REFUSED` | `TARGET_UNKNOWN` | the application table was refused at boot, so no application is known |
| `LAUNCH_CAP_MISSING` | `CAP_MISSING` | a MUTATE or INSPECT_PROTECTED request without a capability |
| `LAUNCH_NO_AUTHORITY` | `AUTHZ_UNAVAILABLE` | a capability was presented, but no authority adapter runs |
| `LAUNCH_INVALID_TRANSITION` | none | a request lifecycle pair outside the matrix; refused, state unchanged |
| `LAUNCH_TRANSITION_RESERVED` | none | a 0.4 pair (dispatch, run, exit, fault, loss); refused in 0.33 |
| `LAUNCH_TRANSITION_LAUNCHER_ONLY` | none | an allowed pair requested from outside the launcher; refused (only launch.rs moves a request) |
