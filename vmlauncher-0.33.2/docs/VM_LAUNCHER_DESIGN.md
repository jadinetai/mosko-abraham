# ABRAHAM VM LAUNCHER 0.33.2: design (D-ABR-024; corrections D-ABR-025, D-ABR-026)

2026-11-09. MOSKO Laboratory 001 - Pripyat. Tree `Documents\Abraham\vmlauncher-0.33`. Directive
`MOSKO_ABRAHAM_033_VM_LAUNCHER_DIRECTIVE_2026-11-09.md` (recorded verbatim; decision D-ABR-024).

## 1. What it is, and what it is not

`Abraham-VM-Launcher.exe` is a **host-side** Windows program. It boots one of three pinned Abraham kernels in the pinned
QEMU, shows the kernel's serial console with a live status panel, stops the VM through QMP, and seals a record of every
launch.

It is **not** part of Abraham:
- It is not Abraham's internal application launcher (`work-0.33/kernel/src/launch*.rs`, D-ABR-022). It never reads,
  builds or changes that source or its contracts.
- It runs the virtual machine only. It runs no Windows program inside Abraham, and Abraham has no graphical desktop or
  framebuffer in 0.33. The window shows the serial console (directive item 3: a host-side serial console viewer).
- It writes nothing into `work-0.33` or any other tree. It reads the pinned files there.

## 2. Toolchain: a genuine executable, nothing downloaded

- Built by the installed Rust 1.99.1 (`x86_64-pc-windows-msvc`) and MSVC 14.51 linker, approved earlier for Abraham.
- `Cargo.lock` lists no dependency. The source uses the Rust standard library and hand-declared Windows API calls
  (kernel32, advapi32, and the C runtime's `_getch`). Nothing was downloaded or installed.
- A native PE32+ x86-64 console program (subsystem 3). It has no application manifest, so it requests no elevation and
  runs as the user who starts it (Windows' installer detection applies to 32-bit programs only).
- The C runtime is linked in (`crt-static`). The program imports only Windows system libraries: kernel32, advapi32,
  ntdll, ws2_32, dbghelp and an api-ms-win-core-synch set.
- `/Brepro` makes two clean builds byte-identical (checked).

So no option needed owner approval (directive: "If producing a genuine Windows executable requires a new tool or
download, present the options"). It is not a renamed script.

## 3. The validated configuration it reuses

Everything below is the 0.33 harness's (`work-0.33/tools/abr_boot_001.py`), pinned by digest:

| Item | Pinned SHA-256 | Source |
|---|---|---|
| QEMU 11.1.0 (Weil 20260811), `%USERPROFILE%\abraham-toolchain\qemu\11.1.0-weil-20260811\qemu-system-x86_64.exe` | `47d57a60...` | D-ABR-004/008 |
| edk2 `share\edk2-x86_64-code.fd` (read-only) | `33090cc0...` | D-ABR-003/008 |
| edk2 `share\edk2-i386-vars.fd` (template; copied per run) | `5d2ac383...` | harness |
| Limine 12.9.6 `BOOTX64.EFI` (`work-0.33\third_party\...`) | `e486ae7a...` | ABR-BOOT-001 |
| `work-0.33\boot\limine.conf` (template) | `ea81dbc9...` | harness |
| kernel `production`: `work-0.33\build\abraham-kernel-0.33.0-dev.elf` | `6b95b9a2...` | TR-0042 |
| kernel `launchpad`: `work-0.33\build\diag\abraham-kernel-diag-launchpad.elf` | `89b3d6fa...` | TR-0042 |
| kernel `early-fail`: `work-0.33\build\diag\abraham-kernel-diag-early-fail.elf` | `79b6cdce...` | TR-0042 |

The digests are compiled into the program. A different file is refused, never booted. Paths can be pointed elsewhere
for tests only (`--home`, `--qemu-dir`, `--runs-dir`). Such a run is labelled "TEST CONFIGURATION"; the digests still
apply.

**Staging** is the harness's:
- `esp\EFI\BOOT\BOOTX64.EFI`;
- `esp\boot\abraham-kernel`;
- `esp\boot\limine\limine.conf`: the template with every `{KERNEL_BLAKE2B}` replaced by the BLAKE2b-512 of the staged
  kernel, so Limine itself refuses another kernel;
- `vars.fd` copied from the template.

The staged files are read back and checked against their pins before QEMU starts.

**QEMU command:** exactly `abr_boot_001.qemu_command(...)` plus `-S`:
- `-machine q35 -accel whpx|tcg -cpu host|max -smp 1 -m 256 -display none -nodefaults -nic none`;
- serial to `file:<run>\serial.log`, QMP on `tcp:127.0.0.1:<free port>`;
- firmware pflash read-only, `vars.fd` pflash, and the ESP as `fat:ro:` virtio.

The verifier rebuilds the command with the harness's own function and compares it.

**Timer opt-out (D-ABR-005):** the same per-process `SetProcessInformation(ProcessPowerThrottling,
IGNORE_TIMER_RESOLUTION, state 0)`. It is applied while the VM is paused, then QMP `cont`, so the harness condition C0
holds for every launcher run.

**Process handling.** These are host-process differences from the harness; the VM configuration is unchanged:
- QEMU is created suspended and with no console of its own (`CREATE_NO_WINDOW`), so Ctrl+C or closing the window
  reaches only the launcher, which then stops QEMU in a controlled way;
- QEMU is put in a Windows job object with kill-on-close **before it runs**. If the launcher itself dies, Windows ends
  QEMU too;
- then the opt-out is applied and the thread resumed.

## 4. What the window shows

**Startup.** On a double-click there are no options, so a menu offers the three kernels (each shown as verified,
MISSING or DIGEST MISMATCH) and the accelerator (WHPX, the counted configuration, or TCG). Enter boots the production
kernel.

**While the VM runs.** An 8-line status panel stays at the top; the serial console scrolls beneath it, colour-coded.
The panel rows:
- **KERNEL BOOT:** waiting for firmware, loader started, kernel entered, OPERATIONAL (time, uptime, heartbeat,
  faults), or BOOT FAILED with the reason;
- **SERVICES:** the latest status round;
- **APPLICATIONS:** the registry and each application's prerequisites;
- **LAUNCHER CONTRACT:** WAITING, IN PROGRESS, CONSISTENT, INCONSISTENT or NOT REACHED.

The panel keeps the kernel's boot apart from the application-launcher contract (directive item 4). A kernel can boot
(PASS) while its contract is INCONSISTENT, and the early-fail build fails its boot by design, so its contract is NOT
REACHED.

**Keys:**
- Q shuts the VM down;
- L opens the record folder;
- H hides or shows the heartbeat lines (they are still recorded).

**At the end,** a result block shows:
- KERNEL BOOT, SERVICES, LAUNCHER CONTRACT and VM SHUTDOWN;
- the result name and exit code;
- what is not claimed.

When the window was opened for the launcher (a double-click), it waits for a key before it closes.

Guest bytes are cleaned before they reach the screen: ANSI sequences are stripped as the harness does, and other
control characters become `.`. Guest output cannot drive the host terminal.

## 5. The live checks, and their limits

The verdicts are **live checks**: a re-implementation, in the launcher, of the official rules. They are not the
official judgment, and every result says so. The rules:

**Kernel boot:**
- the firmware started the loader from the boot disk;
- the kernel entered once (NASM entry, Rust kmain);
- Limine with base revision supported;
- the banner shows the pinned version (0.33.0-dev);
- OPERATIONAL within the boot limit (default 120 s, the harness's);
- no fault, no reset, continuous heartbeat, still alive at shutdown.

For early-fail, its designed outcome instead: one injected `TIMER_UNAVAILABLE` fault before OPERATIONAL, never
OPERATIONAL.

**Services** (0.32b contract, production table; 0.33.1 adds C12's counter rules for every round whose clock is OK:
the full status, an observation under 1 s old, value = steps + 1, at least 250 steps per round, rounds 5,000-5,500 ms
apart):
- the registry order;
- svc.counter RUNNING/AVAILABLE and increasing every round;
- dev.net0 and svc.netmon DECLARED/UNAVAILABLE NOT_INSTALLED.

**Launcher contract** (C13 and `launch_probe.py`):
- the application registry exactly once, after OPERATIONAL and the service start, before the first round: the
  production table, executor ABSENT;
- each round followed directly by its three APPINFO lines, with the round's time and clock and prerequisites
  matching the services;
- the official execution-claim rule on every line.

The rest depends on the build:
- **production:** no launch line at all;
- **launchpad:** the 17 requests compared field by field with the design (§9, a port of `expected_script()`);
  - each result's transitions right before it;
  - the fact rules of `fact_rules_ok`;
  - facts agreeing with the latest status round;
  - the discovery answer;
  - the routed request answered `CAP_MISSING`;
  - the summary equal to the design and to the lines;
  - the injected RUNNING transition refused, with the state unchanged.

A status round or APPINFO group cut by the shutdown is recorded, not judged, as in the official C13.

**Clock gaps and a DEGRADED clock (0.33.1, F-VML-01, D-ABR-025; 0.33.2, F-VML-03, D-ABR-026).** When the guest's
clock jumps (the host froze the VM, or the guest stalled), the kernel's clock guard reports the result itself:
- `ABR|CLOCK|anomaly=TSC_FORWARD_JUMP` (more than 5 s between readings);
- `state=DEGRADED`, latched for the boot;
- `anomaly=HEARTBEAT_GAP|from_s=A|to_s=B|skipped=N`.

The heartbeat then jumps from A to B. The launcher counts a heartbeat discontinuity as a **clock gap, reported by
the kernel** only when exactly that gap was reported after its forward jump. Any other gap remains a boot problem.

**The kernel's report does not establish the cause (0.33.2).** From inside the guest, a host-side stop of QEMU and a
guest-side stall look the same. 0.33.1 called every reported gap a "host pause" (F-VML-03); 0.33.2 looks for host
evidence instead. The launcher measures its own loop: when one turn takes more than 2 s by the monotonic clock or the
wall clock (the larger), the launcher itself was stopped (a standby stops every program), and it records the stop. A
gap is a **host suspension** when such a stop of at least half the skipped seconds ended within 30 s before the
kernel's report. Otherwise its cause is **not established**, and the run ends `CLOCK_ANOMALY_CAUSE_NOT_ESTABLISHED`
(code 11) unless a more serious result applies. The boot, services and contract are still judged in full; code 11
only says that the launcher cannot explain the gap. Limit: a stop of QEMU alone (another program suspending it, or
a host scheduling stall that spares the launcher) is indistinguishable from a guest stall, and is reported as such.

**C12 counter-pair rules after a DEGRADED clock (0.33.2).** The counter's progress and round-spacing rules compare
two consecutive OK rounds. The kernel's 36 ms detection window can leave the first round after a jump still saying
`clock=OK`, so that pair can break the rules. Once the kernel has reported DEGRADED, such findings are recorded
(`c12_pair_findings_not_counted_after_degradation`) and not counted, as the official degraded-clock judge does.

Each status round is judged by its own `clock=` field, with the harness's status mapping (`status_possible`):
- with the clock OK, `svc.counter` is RUNNING/AVAILABLE;
- otherwise it is RUNNING/UNKNOWN OBSERVATION_STALE (liveness UNKNOWN), and never AVAILABLE.

The other rules:
- every service of a round carries the same clock;
- DEGRADED requires the kernel's own report and is latched;
- the APPINFO rules are unchanged (prerequisites follow the round), so `counterview` is UNSATISFIED on stale data.

The verifier judges such a production run with `launch_probe` `degraded-clock` in place of C11 and C12, and with C5
less its continuity part plus the gap check. No official judge exists for a launchpad run with a DEGRADED clock.
0.33.2 judges it with `tools/judge_launchpad_degraded.py`, a **composite** of `launch_probe`'s own `launchpad` and
`degraded-clock` rule sets: every launchpad check except the counter's increase, plus the degraded-clock checks
(`counterview` satisfied before the anomaly and unsatisfied on stale data after it), and only when the kernel
reported DEGRADED. Its checks are named `composite_`, never `official_`; it has its own self-test (9 cases).

**Limits:**
- The live check does not hold the Appendix A list. The design comparison fixes every reason of the pinned launchpad
  build.
- It does not judge the harness's C5 stability window (15 s) or C6-C8 (restart, series, evidence).
- The verifier (`tools/verify_run.py`) re-judges each sealed run with the official tools (§7).

## 6. Shutdown, failures and duplicate launches

**Controlled shutdown:**
1. The operator presses Q, closes the window, presses Ctrl+C or logs off; tests use `--auto-stop-after`.
2. The launcher sends QMP `query-status`, `info registers` (as the harness records them), then `quit`.
3. QEMU must exit within 10 s. Otherwise the job is terminated, and the shutdown is recorded as FORCED.
4. CLEAN means exit 0 and the SHUTDOWN event with reason `host-qmp-quit`, the clean quit of D-ABR-001.
5. Afterwards the job must hold no process, and no process of the pinned QEMU may remain.

Abraham 0.33 has no shutdown path of its own, so the VM is stopped by the host, as in every harness run.

**Exit codes:**

| Code | Result | When |
|---|---|---|
| 0 | OK | boot PASS, contract CONSISTENT, shutdown CLEAN, nothing left |
| 1 | BOOT_FAILED | a fault or failed initialization before OPERATIONAL, the firmware shell, a reset, OPERATIONAL not reached (or reached too late) within the limit, or a boot check failing. The early-fail build always ends here, labelled FAILED AS DESIGNED |
| 2 | REFUSED_INTEGRITY | a required file is not the pinned one (digest, ELF form, template line). Nothing started |
| 3 | REFUSED_MISSING_DEPENDENCY | a required file or the QEMU folder is missing or unreadable. Every input is reported, not only the first |
| 4 | REFUSED_DUPLICATE_LAUNCH | another launcher holds the session mutex `Local\MOSKO-Abraham-VM-Launcher-0.33`, or a QEMU from the pinned toolchain is already running (it may be a test campaign, which must not be disturbed). A QEMU from another folder is reported and left alone |
| 5 | VM_TERMINATED_UNEXPECTEDLY | QEMU exited without being asked |
| 6 | LAUNCHER_CONTRACT_INCONSISTENT | the services or the contract broke a live rule |
| 7 | LAUNCHER_ERROR | the launcher itself could not proceed, for example a reused run id |
| 8 | SHUTDOWN_NOT_CLEAN | forced, or not confirmed, or a process left |
| 9 | CANCELLED | Esc at the menu. Nothing started, no record |
| 10 | SERVICES_NOT_AS_DESIGNED | (0.33.1) the services broke a live rule while the contract held; for example C12's counter progress after a freeze shorter than the kernel's 5 s detection limit. In 0.33 such a run was reported as code 6 |
| 11 | CLOCK_ANOMALY_CAUSE_NOT_ESTABLISHED | (0.33.2) everything else as for OK, but the kernel reported a clock gap that no host evidence explains (§5). In 0.33.1 such a run was OK, labelled "host pause" |

**If the launcher is killed,** the job ends QEMU. Its run folder stays unsealed, and the next launch lists it as
"never sealed" without touching it.

## 7. Records and independent verification

Each launch gets `vmlauncher-0.33\runs\<run id>` (`VML-<UTC stamp>`). It holds:
- `launch.json`: the program's own digest, the host (computer model, Windows build), every input and its digest, the
  staged digests, the QEMU command and version line, the opt-out record, the job and process facts, the timeline, the
  QMP events, the status and registers before quit, the shutdown facts, the observations, every live check, the
  verdicts and the result;
- the ESP, `vars.fd`, `serial.log` (QEMU's own file), `qmp.jsonl`, the QEMU stdout and stderr, `live.json`;
- `console.txt`: what the window showed, as text;
- `verdict.txt`;
- `RUN_SHA256SUMS.json`: the harness's seal format, re-read after writing.

`tools/verify_run.py <run>` trusts nothing the launcher concluded. With Python's hashlib and the official judges of
`work-0.33` (imported read-only) it checks:
- the seal;
- the staged identities, with an independent BLAKE2b in `limine.conf`;
- the QEMU command, rebuilt by the harness's own function;
- C0-C5 and C9-C11 on the single boot, plus C12/C13 (production) or `launch_probe` launchpad, or the fault probe's
  `early` rules;
- the clean shutdown;
- that the live verdicts agree with the official ones.

## 8. Tests (the separate campaign, TR-0044)

- Expected outcomes are fixed in `tools/campaign_vml.py` before any counted run; ids are never reused.
- The source is frozen (digests) and checked unchanged after every entry.
- Classes:
  - acceptance: production and launchpad on WHPX and TCG; three repeats with the same program;
  - the real window: Q, the X button, the no-argument menu;
  - Q through redirected input;
  - negative: missing QEMU, kernel and firmware; wrong kernel, Limine, QEMU, firmware and template digests; failed
    boots (an injected fault, and the time limit); duplicate launcher; a pinned QEMU already running; QEMU killed
    before and after OPERATIONAL; the launcher killed; the unsealed run reported next time; a reused run id;
  - host checks: unit tests, two clean builds, static checks of the source and the PE file, the live checks against
    the 45 J007 falsified logs, `work-0.33` unchanged before and after.
