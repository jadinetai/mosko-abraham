# Abraham 0.33 development tree (isolated): application registry and launcher contract

```text
 __  __    ___    ____    _  __   ___
|  \/  |  / _ \  / ___|  | |/ /  / _ \
| |\/| | | | | | \___ \  | ' /  | | | |
| |  | | | |_| |  ___) | | . \  | |_| |
|_|  |_|  \___/  |____/  |_|\_\  \___/  (TM)

MOSKO(TM) - MOSKO Laboratory 001, 2026 - Digital Front
```

Status 2026-11-10 (this tree, `work-0.33c`): **0.33c final audit package READY FOR ECHO. 0.33 is not accepted.**
- Decision D-ABR-026. This tree is the isolated 0.33c workspace, copied from `work-0.33` (`COPY_MANIFEST_FROM_0.33.json`,
  196 files, all equal); `work-0.33` is never written from here.
- Review and acceptance package: `docs/0.33c_REVIEW.md`. Limitations: `docs/0.33c_LIMITATIONS_REGISTER.md`. Operator
  checklist (the full performance test): `docs/0.33c_OPERATOR_CHECKLIST.md`. Audit clarifications:
  `docs/0.33c_AUDIT_CLARIFICATIONS.md`. Patch notes: `..\PATCH_NOTES_0.33c.md`.
- Criteria: B, C, D met; A and E open (Echo's review and audit, then Jadin's sign-off).
- The kernel is unchanged (`6b95b9a2...`). The MOSKO(TM) signature above and in `kernel/src/main.rs` is a comment; it
  changes no binary (`evidence/phase4`).
- Tools: `tools/g033c/`. Records TR-0049 (this tree) and TR-0050 (launcher 0.33.2, `..\vmlauncher-0.33.2`).

Status 2026-11-08 (as copied from `work-0.33`): **0.33 READY FOR AUDIT. Not accepted.**
- TR-0042 records the campaign: main run 89/95, supplement 12/12, demonstration supplement 4/4.
- Review: `docs/0.33_REVIEW.md`. Plain-language notes: `docs/PATCH_NOTES_0.33.md`.
- Watch the launcher in the VM: `python -I -B tools/g033/launchpad_demo.py --run-id ABR-0.33-DEMO-<n>`.
- Try your own requests: `cd kernel/hosttest; cargo run --example launchpad -- "start app.counterview"`.
- Decisions: design D-ABR-022 (`docs/ABRAHAM_0.33_DESIGN.md`, `06e44c74...`, unchanged); foundation D-ABR-023 (0.32b
  accepted). The Echo qualifications are in `docs/ABRAHAM_0.33_DESIGN_ADDENDUM.md`.
- This tree was copied from accepted 0.32b (`COPY_MANIFEST_FROM_0.32b.json`, runs ABR-0.33-V001/V002, TR-0041).
- `..\work-0.32b\` and every earlier tree are never written from here. A 4,411-file checkpoint
  (`evidence/start/ABR-0.33-V001`) proves that `work-0.32b` is unchanged.

| Path | What |
|---|---|
| kernel/src/appregistry.rs | AppId, AppDesc, ExecSupport, EXECUTOR = ABSENT; `validate(apps, services)` (const fn: compile time and boot), `lookup` |
| kernel/src/apptable.rs | the production table (app.counterview, app.netstatus, app.browser; all exec=NONE); the DIAG tables; the fixed DIAG_SCRIPT |
| kernel/src/launchreq.rs | the bounded request parser and the fixed operation-to-class table |
| kernel/src/launchlife.rs | the request lifecycle: 9 states, 3 allowed, 7 reserved for 0.4, 71 invalid; ExecutionEvidence (no constructor) |
| kernel/src/launch.rs | the launcher: admission, facts, `decide` (option A), LaunchResult (private), discovery |
| kernel/src/launchpad.rs | serial lines: ABR\|APP, APPINFO with every status round; DIAG: the script, LAUNCH, LAUNCHRESULT, LAUNCHPAD, the injection |
| kernel/src/svcmgr.rs, main.rs | the launchpad wired in after the service start and into every status round |
| kernel/src/svcrun.rs, svclife.rs | comments only: the D-ABR-021 wording of the failure threshold |
| kernel/hosttest/tests/apps_033_tests.rs | 27 tests (registry, parser, admission, facts, decision, no execution, no authority, lifecycle, script) |
| kernel/hosttest/tests/phase1_probe_policy.rs | the 15 Phase 1 tests from the 0.32b gate, kept as regressions |
| docs/PATCH_NOTES_0.33.md, 0.33_REVIEW.md, 0.33_OPERATOR_CHECKLIST.md | plain-language notes, review package, operator checklist |
| kernel/hosttest/examples/launchpad.rs, tools/g033/launchpad_demo.py | the Q6 demonstrations: hosted (your requests), and live in the VM |
| tools/g033/ | probe, self-tests, mutation, static checks, campaign, index, package |

Build: `python -I -B tools/build.py kernel`, which gives `build/abraham-kernel-0.33.0-dev.elf`. The DIAGNOSTIC build
is `python -I -B tools/build.py diag diag-launchpad`. No dependencies; nothing downloads anything.
