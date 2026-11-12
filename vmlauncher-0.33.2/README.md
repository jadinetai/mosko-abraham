# Abraham VM Launcher 0.33.2: how to use it

**Double-click `Abraham-VM-Launcher.exe` in this folder (`vmlauncher-0.33.2`).** No commands are needed.

0.33.2 (D-ABR-026, the 0.33c audit) corrects how a clock gap is explained. When the kernel reports that its clock
jumped (`TSC_FORWARD_JUMP`), that report alone does not say **why**. The launcher now calls it a host suspension only
when it has host evidence: the launcher itself was stopped for about as long, at the same time (a laptop going to
sleep stops both). Otherwise it says the cause is not established and ends with code 11. 0.33.1 called every such
gap a "host pause" (F-VML-03). The earlier programs in `vmlauncher-0.33` and `vmlauncher-0.33.1` stay as recorded.

1. A window opens with a short menu. Press **Enter** (or **1**) for the Abraham 0.33.0-dev production kernel. The
   other two choices are DIAGNOSTIC builds:
   - **2, launchpad:** the kernel sends its 17 fixed launcher-contract requests and prints how each one was answered;
   - **3, early-fail:** a deliberately failed boot, so you can see what a failure looks like.
2. The launcher checks every file it needs against its pinned SHA-256 (the kernel, QEMU, the UEFI firmware, Limine
   and its boot entry). If one is missing or different, it says which one, and **starts nothing**.
3. Abraham boots in QEMU. The top of the window is the status panel:
   - **KERNEL BOOT:** the kernel's own progress, up to OPERATIONAL (normally about 2.5 s), then its uptime and
     heartbeat;
   - **SERVICES:** the service status the kernel reports every 5 s;
   - **APPLICATIONS:** the application registry, and which applications have their prerequisites;
   - **LAUNCHER CONTRACT:** whether the kernel's application-launcher output obeys the 0.33 contract. This is separate
     from the boot: a kernel can boot and still break the contract.

   Below the panel, the kernel's serial console scrolls live, exactly as the kernel prints it.
4. **Press Q** to shut the VM down. Closing the window with X also shuts it down cleanly. A result block follows. The
   window waits for a key, so you can read it.

**Run it again** the same way, as often as you like. Nothing needs rebuilding or setting up.

## What is normal

| You see | It means |
|---|---|
| `KERNEL BOOT: OPERATIONAL at 2.4 s` | the real kernel finished its initialization |
| `svc.counter RUNNING/AVAILABLE value=...` | the counter service runs; the value grows every round |
| `dev.net0, svc.netmon UNAVAILABLE NOT_INSTALLED` | there is no network adapter, by design |
| `counterview SATISFIED`, `netstatus, browser UNSATISFIED (svc.netmon)` | prerequisites, as the services say |
| `LAUNCHER CONTRACT: CONSISTENT` | the registry and its reports obey the 0.33 contract. **Nothing executes:** the executor is ABSENT in 0.33 |
| `VM SHUTDOWN: CLEAN` | QEMU stopped through its control channel (QMP quit), and no QEMU process is left |
| early-fail: `BOOT FAILED (as this DIAGNOSTIC build is designed to)` | the designed failure, reported as a failure |
| `clock gap 251 s` (yellow) and a `CLOCK: DEGRADED` row | the kernel noticed a jump in its own clock and reported it. From then on its clock is DEGRADED, so it reports the counter as `UNKNOWN / OBSERVATION_STALE` and `counterview` as UNSATISFIED: stale data is never trusted. This is the designed behaviour, not a failure |
| `CLOCK: ... host suspension (the launcher was stopped N s too)` | the laptop slept or Windows suspended programs: the launcher was stopped at the same time, so the cause is established. Result OK (code 0) |
| `CLOCK: ... cause not established (the launcher kept running)` | the kernel reported the gap, but the launcher kept running, so nothing on the host explains it (QEMU alone was stopped, or the guest stalled; they look the same from inside). Result `CLOCK_ANOMALY_CAUSE_NOT_ESTABLISHED` (code 11): the boot itself is still judged, and nothing was hidden |

The panel's verdicts are **live checks** made by the launcher. The official judgment of a run is
`tools/verify_run.py` (below), which re-judges the saved record with the 0.33 harness's own tools.

## What it does not do

- It does **not** give Abraham a graphical desktop: Abraham 0.33 has no framebuffer. You see its serial console.
- It does **not** run Windows programs inside Abraham. It runs the virtual machine, and nothing else.
- It is not part of Abraham, and not Abraham's internal application launcher.
- It needs no administrator rights. It changes no Windows setting, no boot configuration and no PATH. It downloads
  nothing.

## Records

Every launch, refused launches included, leaves a sealed folder `runs\VML-<date>T<time>Z\` (press **L** while running
to open it). The folder holds:
- `verdict.txt`: the result block;
- `console.txt`: everything the window showed;
- `serial.log`: the kernel's console, byte for byte;
- `launch.json`: everything else, including the exact kernel file and its SHA-256, and every input's digest;
- the boot disk and QMP log, sealed in `RUN_SHA256SUMS.json`.

To check a record independently:

```
python -I -B tools/verify_run.py runs\VML-<...>
```

## Exit codes

| Code | Result |
|---|---|
| 0 | OK |
| 1 | boot failed |
| 2 | a file is not the pinned one |
| 3 | a file is missing |
| 4 | another launch is already running |
| 5 | QEMU stopped unexpectedly |
| 6 | contract inconsistent |
| 7 | launcher error |
| 8 | shutdown not clean |
| 9 | cancelled at the menu |
| 10 | services not as designed (0.33.1; until 0.33.1 this was reported as code 6) |
| 11 | the kernel reported a clock gap whose cause the host cannot establish (0.33.2; in 0.33.1 this was code 0, "host pause") |

Details: `docs/VM_LAUNCHER_DESIGN.md`. Decisions D-ABR-024, D-ABR-025, D-ABR-026. Test records TR-0044 (0.33),
TR-0046 (0.33.1); the 0.33.2 record is the D-ABR-026 launcher row of `test-records/INDEX.md`.
