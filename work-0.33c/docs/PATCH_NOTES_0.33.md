# Abraham 0.33 patch notes (for Jadin)

2026-11-08. Tree `work-0.33`. Design D-ABR-022, foundation D-ABR-023 (0.32b accepted).
- **0.33 is READY FOR AUDIT. It is not accepted.**
- Records: TR-0041 (start and development runs) and TR-0042 (campaign).
- Review package: `docs/0.33_REVIEW.md`. Operator checklist: `docs/0.33_OPERATOR_CHECKLIST.md`.

**Watch the launcher run in the VM:**

```
python -I -B tools/g033/launchpad_demo.py --run-id ABR-0.33-DEMO-1
```

It boots the real diag-launchpad kernel in QEMU and prints each request live, with a plain-English line under each
result. Use a new run id each time.

**Try your own requests** (on your PC, the kernel's own launcher code):

```
cd kernel/hosttest
cargo run --example launchpad -- "start app.counterview" "list app" "status app.browser"
```

Add `--degraded-clock` to see prerequisites fail on stale data.

## What 0.33 does, in plain words

The kernel now knows three applications by exact name:
- `app.counterview`, which needs the counter service;
- `app.netstatus` and `app.browser`, which need network monitoring. That service does not run, because no network
  adapter exists. The browser's requirement is marked provisional, at Echo's request.

**Every five seconds**, with the service status, the kernel prints for each application:
- whether its prerequisites are met;
- which service is missing, and why;
- that it cannot execute: `exec=NONE`, and the executor is ABSENT.

The values are the same ones the service status lines of that round report. When the clock is degraded, the counter's
status becomes stale, and the counter viewer's prerequisites become unmet: never satisfied on stale data.

**A diagnostic build sends 17 fixed requests to the launcher.** For each one it prints:
- whether it was accepted for validation, or refused, and at which step;
- the five facts, separately: well-formed, known, prerequisites, authorized, executed;
- the final result.

Every result is `NOT_EXECUTED`, `executed=NO`, `process=NONE`. A known application with all prerequisites met is still
refused for lack of authority (`CAP_MISSING`), because no authority mechanism exists yet. Naming a capability does not
help either (`AUTHZ_UNAVAILABLE`).

`start svc.counter` is answered by the unchanged 0.32b service contract. A forced RUNNING transition is refused, and
the state is unchanged.

**The production kernel makes no request at all.** Its binary does not even contain the code that prints a launch
result.

## Changed files, and why

| File | Why |
|---|---|
| `kernel/src/appregistry.rs`, `apptable.rs` | the registry rules and the three-entry table. The table is checked when the kernel is compiled and again at boot; an "executable" claim is refused |
| `kernel/src/launchreq.rs`, `launchlife.rs`, `launch.rs` | the request parser; the request lifecycle (RUNNING is reserved, and its proof cannot be forged); the launcher and its fixed decision order |
| `kernel/src/launchpad.rs` | the serial lines |
| `kernel/src/svcmgr.rs`, `main.rs` | two hooks (registry check at start, APPINFO in each round) and the diagnostic call. Service behavior is unchanged |
| `kernel/src/svcrun.rs`, `svclife.rs` | comments only: "3 overruns without an intervening verified in-budget step" (D-ABR-021) |
| `kernel/Cargo.toml`, `Cargo.lock` | version 0.33.0-dev; four DIAGNOSTIC features |
| `kernel/hosttest/...` | 27 launcher tests, the 15 Phase 1 tests kept, 4 compile-fail and twin blocks |
| `docs/KERNEL_DIAGNOSTICS.md` | §20-§21: every new line tag and word |
| `docs/ABRAHAM_0.33_DESIGN.md` | the approved design, unchanged |
| `docs/ABRAHAM_0.33_DESIGN_ADDENDUM.md` | Echo's qualifications |
| `tools/abr_boot_001.py` | profile 0.33 with condition C13. C12 is unchanged |
| `tools/g033/*` | probe, self-test, mutation check, static checks, re-judging, campaign, index, package |
| `tools/g032b/judge_selftest_032b.py`, `tools/g032/judge_selftest_032.py` | corrected for 0.33 sources (§Failures, 3) |
| `tools/g032/verify_tree_checkpoint.py` | `work-0.32b` added to the preserved trees |
| `kernel/hosttest/examples/launchpad.rs` | Q6: the hosted demonstration (your own requests) |
| `tools/g033/launchpad_demo.py`, `check_demo_033.py` | Q6: the VM viewer, and the check of the hosted demo |

## Evidence

- **Campaign:** main run 95 entries, 89 as expected; supplement 12/12; no source change during either.
- **The 0.33 kernel passes every check (C0-C13)**, on WHPX and TCG, cold and warm restart, and with live memory
  exhaustion.
- **Earlier kernels:** they still pass their own profiles. The accepted 0.32b kernel fails only the new launcher check,
  which proves that check is not empty.
- **Hosted tests:** 174 pass.
- **Deliberately broken versions:** 35 of the 0.32b rules and 16 of the launcher rules, all caught.
- **Falsified logs:** 58 (services) and 45 (launcher), each rejected for the right reason.
- **D-ABR-012 memory protections:** 8/8, on both accelerators. Faults, clock checks and exhaustion as in 0.32b.
- **Reproducible:** two clean builds equal the tested kernel `6b95b9a2...`.
- **Preserved:** `work-0.32b` and every earlier tree, unchanged.
- **Demonstration**, recorded supplement 2, 4/4: the hosted demo is checked against the contract; the VM viewer
  passes on WHPX and TCG.

## Failures and mistakes

**Designed to fail, and correct:**
- G005 and G009: older kernels under the new profile fail exactly the checks they lack.
- N009-N012: the harness refuses a wrong digest, fails a killed QEMU, labels a run without the timer opt-out, and
  Limine refuses a tampered kernel.
- K002-K004 and P002: injected code violations, each caught.
- R006: the old pre-fix log is still rejected.

**My mistakes:**
1. **Development**, all fixed before the counted campaign:
   - two errors in my first test file;
   - a 66-byte test row that should have been 65;
   - an unnecessary `unsafe` helper (removed);
   - dead-code warnings (fixed the 0.32b way);
   - `unavailable=NONE` printed for prerequisites that were never checked (now `NOT_EVALUATED`);
   - a Python slip in a new tool;
   - one self-test rule that was too strict (a line planted before OPERATIONAL rightly breaks the lifecycle check too);
   - three older self-tests pointed at a source run of the wrong profile.
   - While planning the mutation check I found a gap: no test read a launch result's live prerequisites. I added that
     test (n05).
2. **In the counted campaign, 6 entries were UNEXPECTED, all because of my test tools.** In every case the kernel's
   output was exactly as designed.
   - **L003-L006, and the refused-registry control of J005.** My probe rule demanded application status lines after
     every round. A kernel whose application table was refused correctly prints none. I had dry-run the launchpad
     build through the probe, but not a refused-registry build. That was my process gap.
   - **J001.** The 0.32b self-test assumed the source run's last status round was complete. G010's capture really
     ended inside it, so the test built malformed cases, and the judge correctly rejected or reported them. The test
     also used "0.33" as an "unknown" profile name, but 0.33 is now a real profile.
3. **The fix:**
   - I closed the main run as recorded, then corrected the three tools (no kernel change).
   - I re-ran the six under new ids (L007-L010, J006, J007), and re-judged the sealed logs (R001-R005): 12/12.
4. **Q6 was done after the campaign**, at your request, as supplement 2, so the counted run was not changed.
   - My first trial of the VM viewer (DEV-DEMO1) died because I cut its output short with `head`. It left a QEMU
     running, which I found and stopped.
   - The viewer now always shuts QEMU down and always seals its folder.
   - DEV-DEMO1 is kept, with a note.

**Unexplained:** none.

**An inherited limit worth knowing.** On a 1 h clock jump, one status round was computed 36 ms before the clock guard
noticed the jump. That round honestly said the clock was OK, and the launcher followed it. From the next round on,
everything is stale and unmet. This is the 0.32b clock guard's detection window, unchanged; the review lists it.
