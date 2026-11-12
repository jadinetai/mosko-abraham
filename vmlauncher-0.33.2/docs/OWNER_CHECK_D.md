# Owner check D: launch and observe Abraham yourself (D-ABR-024, criterion D)

About 10 minutes, on the ASUS TUF Gaming A16. Nothing here needs a terminal. Tick each line as you go. If any line
does not hold, stop and tell Claude what you saw (the run folder name is enough).

## 1. The production kernel

1. Open File Explorer: `Documents\Abraham\vmlauncher-0.33.1`.
2. Double-click **`Abraham-VM-Launcher.exe`**.

- [ ] A window opens with a menu. All three kernels say `[verified]`.

3. Press **Enter**.

- [ ] Every required file is listed as `OK`. Then the status panel appears at the top, and the kernel's lines scroll
  below.
- [ ] Within a few seconds: `KERNEL BOOT : OPERATIONAL at ...`, in green.
- [ ] `SERVICES`: `svc.counter RUNNING/AVAILABLE value=...`. The value grows every 5 s.
- [ ] `APPLICATIONS`: `counterview SATISFIED | netstatus, browser UNSATISFIED (svc.netmon)`.
- [ ] `LAUNCHER CONTRACT : CONSISTENT - ... no request; nothing executed`.

4. Wait about 20 s, then press **Q**.

- [ ] The result block shows `KERNEL BOOT : PASS`, `LAUNCHER CONTRACT : CONSISTENT`, `VM SHUTDOWN : CLEAN`,
  `RESULT : OK (exit code 0)`.

5. Press any key. The window closes.

## 2. The launcher contract (DIAGNOSTIC launchpad)

6. Double-click again, and press **2**.

- [ ] The 17 requests scroll by. Each answer has a plain-English line under it: refused, or validated then NOT
  EXECUTED.
- [ ] `LAUNCHER CONTRACT : CONSISTENT - 17 of 17 as designed: 9 refused, 6 not executed, 1 discovery, 1 routed;
  executed 0`.

7. Close the window with the **X** button this time.

- [ ] It closes within a few seconds.

## 3. A failure, reported as one

8. Double-click again, and press **3**.

- [ ] `KERNEL BOOT : BOOT FAILED (as this DIAGNOSTIC build is designed to): ABR|FAULT|reason=TIMER_UNAVAILABLE...`,
  in red.
- [ ] `LAUNCHER CONTRACT : NOT REACHED`.

9. Press **Q**, then any key.

## 4. Nothing left behind, and the records

- [ ] Task Manager (Ctrl+Shift+Esc), Details tab: no `qemu-system-x86_64.exe` is running.
- [ ] `vmlauncher-0.33.1\runs` holds three new folders `VML-<date>T<time>Z`. Each has a `verdict.txt` matching what you
  saw.
- [ ] Optional: open one `launch.json` and find `"computer_model": "ASUS TUF Gaming A16 ..."` and the kernel's SHA-256.

When every box is ticked, criterion D holds. Tell Claude: "Owner check D done", with the three run folder names. They
will be added to the record and verified with `tools/verify_run.py`.

The launcher shows the serial console. Abraham has no graphical desktop yet, and nothing runs inside it but the
kernel itself.
