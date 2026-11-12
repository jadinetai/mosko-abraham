# Abraham 0.33 VM launcher: patch notes (for Jadin)

2026-11-09. Directive `MOSKO_ABRAHAM_033_VM_LAUNCHER_DIRECTIVE_2026-11-09.md`, decision D-ABR-024. New tree
`Documents\Abraham\vmlauncher-0.33`. Test record **TR-0044**.

- **The launcher passes its independent acceptance test (criterion C), as recorded in TR-0044.** This is a
  measurement, not an acceptance.
- **0.33 is not accepted.** Final owner acceptance still needs:
  - A: the launcher-contract review;
  - D: your own launch on the A16 (`docs/OWNER_CHECK_D.md`);
  - E: Echo's audit and your sign-off.
- Criterion B (kernel and service regressions) was met by the TR-0042 campaign.

**To use it:** double-click `vmlauncher-0.33\Abraham-VM-Launcher.exe`, then press Enter. `README.md` explains what you
will see.

## What was built, in plain words

A real Windows program, built with the Rust and Visual C++ tools already installed. It has no other parts and needs no
download. It does what the 0.33 harness does to boot Abraham, but in a window you can watch:
1. It checks every file against its recorded SHA-256 (kernel, QEMU, firmware, Limine, boot entry). It refuses, and
   names the file, if anything is missing or different.
2. It builds the boot disk exactly as the harness does. The staged kernel, Limine EFI and `limine.conf` are
   byte-identical to the counted harness runs W001 and L001.
3. It starts the same QEMU with the same command and the same timer setting, inside a Windows "job". If the launcher
   is killed, Windows ends QEMU too.
4. It shows a status panel above the live serial console. The panel keeps the **kernel boot** (did it reach
   OPERATIONAL?) apart from the **launcher contract** (do the application registry and the 17 requests obey the 0.33
   rules?).
5. Q, or closing the window, stops the VM cleanly through QMP. Abraham has no shutdown of its own; the harness stops
   it the same way.
6. Every launch, even a refused one, leaves a sealed record folder in `runs\`.
7. `tools/verify_run.py` re-checks any record with Python's own hashing and the official 0.33 judges. It does not
   trust what the launcher said.

It does not give Abraham a desktop, it runs no Windows program inside Abraham, and it touches nothing in `work-0.33`.

## The files

| File | What it is |
|---|---|
| `Abraham-VM-Launcher.exe` | the program (PE32+ x86-64 console, about 1 MB, no administrator rights needed) |
| `src/main.rs` | menu, file checks, duplicate checks, staging, QEMU start, the live loop, shutdown, records |
| `src/observe.rs` | reads the serial console and keeps the live verdicts (boot, services, launcher contract) |
| `src/win.rs` | the Windows calls: job object, timer opt-out, process list, console, single-instance lock |
| `src/qmp.rs`, `src/json.rs` | the QMP connection and a small JSON reader and writer |
| `src/hash.rs` | SHA-256 and BLAKE2b-512, checked against the published test values |
| `src/ui.rs`, `src/util.rs`, `src/pins.rs` | the window; time stamps and the run seal; the pinned digests |
| `Cargo.toml`, `Cargo.lock`, `.cargo/config.toml` | the build: no dependency; reproducible (`/Brepro`); the C runtime linked in |
| `tools/verify_run.py` | the independent check of one run record |
| `tools/console_probe.py` | drives the program in a real window (Q, the X button, the menu) and reads back what the window shows |
| `tools/campaign_vml.py`, `tools/dry_run_campaign.py` | the counted campaign, with fixed expectations; its development dry run |
| `tools/make_audit_vml.py` | the package for Echo |
| `README.md`, `docs/VM_LAUNCHER_DESIGN.md`, `docs/OWNER_CHECK_D.md` | how to use it; the design; your check D |
| home: `MOSKO_ABRAHAM_033_VM_LAUNCHER_DIRECTIVE_2026-11-09.md`, `DECISIONS.md` (D-ABR-024 appended) | the directive and its decision |

Nothing in `work-0.33`, or in any earlier tree, was changed (V001/V002).

## Evidence (TR-0044)

Counted campaign `evidence/campaign-vml/` (2026-11-09 18:24:52 to 18:31:06 UTC):
- program `64d90d76d2f596c8e5dad8bb6c5444478cd95abe791964ec6e4a9ae3dab51930`;
- **35 entries, 35 as expected**; no source change during the campaign;
- every expected outcome fixed in `tools/campaign_vml.py` before the run (`EXPECTED.json`).

**Acceptance (the directive's test, on this A16, WHPX unless noted):**

| Entry | What | Result |
|---|---|---|
| A001-A003 | production kernel, three launches in a row, same program, nothing rebuilt or reconfigured | OPERATIONAL at 2.7 / 2.6 / 2.5 s; contract CONSISTENT; CLEAN; exit 0 |
| A004 | launchpad (the 17 requests) | CONSISTENT: 9 refused, 6 not executed, 1 discovery, 1 routed; executed 0 |
| A005, A006 | production, launchpad on TCG | the same, both OK |
| A007 | a real window: Q typed into it | the panel showed OPERATIONAL; clean; the window waited for a key |
| A008 | a real window: closed with X | clean QMP quit; the window gone 0.4 s after the close |
| A009 | a real window with no options: the menu, key 1 | the menu read back from the window; boot; clean |
| A010 | Q through redirected input | clean |

**Independent verification.** `tools/verify_run.py` re-judged every completed run with the official 0.33 tools and
Python's own hashing:
- the QEMU command is exactly the harness's;
- the staged `limine.conf` matches an independent BLAKE2b;
- conditions C0-C5 and C9-C11 held, plus C12/C13 for production or `launch_probe` for the launchpad (C6-C8 do not
  apply to a single launch);
- **the launcher's live verdicts agreed with the official ones on all 13 runs compared (X002)**;
- the boot disk is byte-identical to the counted harness runs W001 and L001 (X003).

**Negative tests:**

| Class | Entries | Result |
|---|---|---|
| Missing dependency | N001 (no QEMU folder), N002 (no kernel), N003 (no firmware) | exit 3; every missing file named; QEMU never started |
| Wrong digest | N004 (kernel), N005 (Limine), N006 (QEMU), N007 (firmware), N008 (boot-entry template) | exit 2; DIGEST MISMATCH named; nothing started |
| Failed boot | N009 (early-fail: the injected fault), N010 (production with a 1 s limit) | exit 1. N009 is FAILED AS DESIGNED: `TIMER_UNAVAILABLE`, CPU halted. N010: "OPERATIONAL reached only 2.4 s after the VM was resumed, beyond the 1 s limit". Both shut down cleanly |
| Duplicate launch | N011 (a second launcher), N012 (a pinned QEMU already running) | exit 4; no second QEMU; the first VM unaffected (exit 0); N012 names the running QEMU's pid |
| Unexpected termination | N013 (QEMU killed after OPERATIONAL), N014 (killed before), N015 (the launcher killed) | N013 and N014: exit 5, VM_TERMINATED_UNEXPECTEDLY, sealed. N015: QEMU gone 0.02 s after the launcher died; its folder left unsealed |
| After a crash | N016 | the next launch named N015 as never sealed and left it untouched |
| Reused run id | N017 | exit 7; A001's folder unchanged |

**Host checks:**
- H001: 15 unit tests (hash test values, JSON, line cleaning, the observer on the sealed W001, L001 and F005 logs, and
  falsified logs);
- B001: two clean builds are identical to the program;
- S001:
  - no dependency;
  - a PE32+ console program with no manifest, so no elevation;
  - only Windows system DLLs;
  - no registry, PATH or boot change in the source;
  - sockets on 127.0.0.1 only;
  - every write goes into the run folder;
- **X001: the live checks called all 43 falsified 0.33 logs (J007) INCONSISTENT, and the 2 genuine ones CONSISTENT**;
- V001, V002: the TR-0042 evidence index still holds (632 rows, 631 unchanged). The one changed row is `DECISIONS.md`,
  which is append-only: D-ABR-024 is the only addition. `work-0.33` is identical file for file, before and after.

## Failures and mistakes

**Designed to fail, and correct:**
- N001-N017: each refused, failed or terminated exactly as fixed beforehand.
- N009: the early-fail kernel's failure is reported as a failure. It is FAILED AS DESIGNED, still exit 1, never PASS.
- N015: the killed launcher's folder is unsealed, which is the truthful state. It is reported, never repaired.

**My mistakes, all found and fixed before the counted campaign:**
1. **The template check was too strict (DEV-001).** The boot-entry template names `{KERNEL_BLAKE2B}` twice, once in a
   comment, and I required exactly one. The first launch was refused. The check now requires the boot entry's path
   line. The template is replaced as the harness does it, in every place.
2. **Relative paths reached QEMU (DEV-002).** The verifier caught it: with a relative `--runs-dir`, the QEMU command
   differed from the harness's. Every path is now absolute.
3. **The live check for the discovery answer was wrong (unit test).** It demanded the round's time on a discovery
   answer, which is a fresh observation. Corrected to the official rule (prerequisites only).
4. **The first live check was too weak for the launchpad.** It let 12 of the 23 falsified launchpad logs through as
   CONSISTENT. A viewer must not do that, so I ported the official rules: the designed 17-row script, transition
   order, the fact rules, and facts against the round. Now 43/43 are rejected.
5. **An OPERATIONAL after the time limit would have counted as PASS.** I found this while designing N010. Now it is a
   failure that names the limit.
6. **DEV-004 stopped after 12 s.** That is too short for the harness's 15 s stability window (C5), so its
   verification failed on C5 only. Counted runs stop 20 s after OPERATIONAL.
7. **The program needed `vcruntime140.dll`.** It was on this PC, but a copy elsewhere might not find it. The C runtime
   is now linked in.
8. **The campaign tool's first dry run of its host checks found its own defects:**
   - the 0.33 index's paths are relative to the Abraham home, not to `work-0.33`;
   - it did not expect the D-ABR-024 append to `DECISIONS.md`;
   - its socket rule flagged the 127.0.0.1 connection;
   - shell quoting put a stray control character into one of its patterns.

   All were corrected before any counted entry.
9. **Full dry run 1 (development, 33/35) found two launcher defects and one verifier defect:**
   - **DRY-A009.** When the startup text was longer than the window (long folder names wrap), the console had already
     scrolled, and the panel was drawn where the window was not looking. The run itself was fine. The live view now
     uses the console's alternate screen, and the final panel is reprinted above the result.
   - **DRY-N014.** With QEMU killed before its control channel answered:
     - the launcher waited the full 30 s and then printed "VM resumed". It now stops waiting as soon as QEMU has
       exited, and says the VM was not resumed;
     - `verify_run.py` crashed on the missing `qmp.jsonl`. It now handles the case.

   Dry run 2, with the corrected program `64d90d76...`, was 35/35. Then the counted run.

**Unexplained:** none.

**Limits worth knowing:**
- The panel's verdicts are live checks. The official word on a run is `tools/verify_run.py`.
- One launch cannot show C6 (restart), C7 (a series) or C8 (the harness's own evidence rule). The seal check replaces
  C8.
- Like the harness, only QEMU's executable is pinned, not its DLLs.
- The static checks are text and byte scans.
- The window tests used the classic console window (conhost). A double-click on your PC may open Windows Terminal
  instead. Both understand the same display codes, but your own check D is the test of that.
- The launcher's `info registers` capture showed HLT=0 on WHPX in N009. The CPU halt was proven independently, by the
  HLT instruction before RIP, as the fault probe does.
