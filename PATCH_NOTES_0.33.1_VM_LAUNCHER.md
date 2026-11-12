# Abraham VM launcher 0.33.1: patch notes (for Jadin)

2026-11-09. Decision **D-ABR-025** ("Yes, fix F-VML-01"). New tree `Documents\Abraham\vmlauncher-0.33.1`, copied from
`vmlauncher-0.33` (22 files, all equal: `COPY_MANIFEST_FROM_0.33.json`). Test record **TR-0046**.

- **Use the new program:** double-click `vmlauncher-0.33.1\Abraham-VM-Launcher.exe`.
- The old program in `vmlauncher-0.33` stays as recorded (TR-0044, TR-0045, your six runs) and is not changed.
- The kernel is unchanged: Abraham 0.33.0-dev `6b95b9a2...`.
- 0.33 is still not accepted: criteria A and E (Echo) are open.

## What was wrong, in plain words

**F-VML-01 (from your long run, TR-0045).**
1. Your laptop slept for about 4 minutes while Abraham ran.
2. Abraham noticed the jump in time itself, said so on its console, and from then on stopped trusting its timed data,
   exactly as designed.
3. The launcher then called the run `BOOT_FAILED`, because it treated any missing heartbeat as a boot problem. It also
   flagged the services, because it expected the counter to stay AVAILABLE, which a DEGRADED clock forbids.

The boot had succeeded. The label was wrong.

**F-VML-02 (found while testing the fix).** A freeze shorter than 5 s is too short for Abraham's clock guard to notice.
It still costs the counter service steps. The official judge (C12) catches that: it wants at least 250 counter steps
per 5 s round. The launcher's live check did not have that rule, so the two disagreed. The 0.33 program had the same
gap. Also, a services problem was reported under the contract's name (`LAUNCHER_CONTRACT_INCONSISTENT`, exit 6).

## What changed

| File | Change |
|---|---|
| `src/observe.rs` | reads the kernel's own clock lines: `TSC_FORWARD_JUMP`, `HEARTBEAT_GAP`, `DEGRADED`. A heartbeat gap is a **host pause, reported by the kernel** only if the kernel reported exactly that gap after its forward jump; any other gap is still a boot problem. Each status round is judged by its own clock: AVAILABLE with the clock OK, `UNKNOWN / OBSERVATION_STALE` otherwise, and DEGRADED stays latched. For rounds with the clock OK, C12's counter rules: the full status, an observation under 1 s old, value = steps + 1, at least 250 steps per round, and rounds 5,000-5,500 ms apart |
| `src/main.rs` | version 0.33.1. The result block names the pause and the stale data. A new result `SERVICES_NOT_AS_DESIGNED` (exit 10). The record gains `host_pauses_reported_by_the_kernel`, `clock_degraded`, `clock_anomalies_reported_by_the_kernel` and `unexplained_heartbeat_gaps`. The panel gains a CLOCK row (in yellow) once the clock is DEGRADED, and the applications row is regrouped so it fits 120 columns. The offline check reports the clock facts |
| `tools/verify_run.py` | a production run with a DEGRADED clock is judged by the official rules made for it: `launch_probe` degraded-clock in place of C11 and C12, and C5 less its continuity part, plus a check that every gap was reported by the kernel with its jump. A launchpad run with a DEGRADED clock has no official judge, and is reported NOT VERIFIED. Runs ending SERVICES_NOT_AS_DESIGNED or CONTRACT_INCONSISTENT are checked for agreement |
| `tools/pause_qemu.py` (new) | freezes QEMU for a set time, as a laptop standby does, with no test hook inside the program |
| `tools/console_probe.py` | can freeze QEMU while a real window is open, and checks that the panel shows it |
| `tools/campaign_vml.py` | the 0.33 entries re-run on the new program, plus F001-F003 (reproduce, correct, no false alarm), P001-P005 (pauses), and V001/V002 for both preserved trees |
| `README.md`, `docs/VM_LAUNCHER_DESIGN.md`, `docs/OWNER_CHECK_D.md` | the new folder, the pause behaviour, exit code 10 |

## Evidence (TR-0046)

Counted campaign `evidence/campaign-vml/` (2026-11-09 22:58:30 to 23:09:49 UTC):
- program `c09f1cbfb49ca9c5c99a8702b4c1388a436bc0784219daabbf014bde0d4dde18`;
- **43 entries, 43 as expected**; no source change during the campaign;
- every expected outcome fixed beforehand (`EXPECTED.json`).

**The defect, reproduced first, then corrected:**

| Entry | Result |
|---|---|
| F001 | the 0.33 program on your standby log fails `heartbeat_continuous` and the service rule ("round 665: svc.counter … expected AVAILABLE"): the defect, reproduced |
| F002 | the 0.33.1 program on the same log: every check holds; one host pause 3318 → 3570 (251 s) reported by the kernel; clock DEGRADED; contract CONSISTENT |
| F003 | no false alarm from the stricter rules on 16 genuine logs: your six runs, four from the 0.33 campaign, and six counted harness runs (WHPX, TCG, production, launchpad) |

**Forced pauses (QEMU frozen, as by a standby):**

| Entry | What | Result |
|---|---|---|
| P001 | production, WHPX, 30 s | the kernel reported 10 → 40 (29 s skipped) and DEGRADED. Launcher: boot PASS, services AS DESIGNED, contract CONSISTENT, OK (exit 0). VERIFIED through the official `launch_probe degraded-clock` |
| P002 | the same on TCG | the same |
| P003 | production, 4 s, right after a status round: too short for the kernel to notice | no clock anomaly. "round 4: svc.counter advanced 97 steps … at least 250". SERVICES_NOT_AS_DESIGNED (exit 10). VERIFIED: the official C12 fails too, so they agree |
| P004 | launchpad, 30 s | the launcher says OK; the verifier says NOT VERIFIED, for exactly one reason: no official judge exists for this case (the documented limit) |
| P005 | a real window, 30 s | the panel showed the CLOCK row (DEGRADED, the pause reported by the kernel) and "host pause 29 s" on the boot row, in yellow, not red; Q; VERIFIED |

**Regression.** Every 0.33 entry was re-run on the new program, and all held:
- A001-A010, including the real window, the X button and the menu;
- N001-N017: missing, wrong digests, failed boots, duplicates, killed processes, unsealed run, reused id;
- X001: 45/45 falsified logs right;
- X002: the live verdicts agree with the official ones on all 17 runs compared;
- X003: the boot disk is identical to W001 and L001;
- B001: two clean builds are identical;
- S001;
- H001: 19 unit tests.

**Preserved:**
- V001/V002: `work-0.33` is unchanged file for file, and its index holds.
- `vmlauncher-0.33` is unchanged file for file (678 files, with your six runs); its index holds, and its Echo package
  matches its digest.
- The only append is `DECISIONS.md` (D-ABR-025).

## Failures and mistakes

**Designed to fail, and correct:**
- F001 shows the old program's defect on purpose.
- P003 reports a short freeze as SERVICES_NOT_AS_DESIGNED, because the counter really lost steps.
- P004 is NOT VERIFIED on purpose: there is no official judge for it.
- All N entries fail as fixed beforehand.

**My mistakes, all found and fixed before the counted campaign:**
1. **The 3 s freeze (DEV-003) exposed F-VML-02.** The live service check lacked C12's progress and timing rules
   (inherited from 0.33), and services problems carried the contract's result name. Fixed with C12's counter rules
   and the new exit 10.
2. **The panel cut off the pause (dry run 1, DRY-P005).** At 120 columns the boot row ended at "host pause 29 s,
   repor…". The clock facts now have their own CLOCK row. The applications row was also regrouped, after DEV-006
   showed it cut off on a degraded run.
3. **Patch-tool slips:**
   - a path replacement in `OWNER_CHECK_D.md` did not apply (escaping); fixed by hand;
   - one campaign patch stopped halfway, because an earlier shell heredoc had joined a line in the 0.33 tool (valid
     Python, so it had run fine);
   - a borrow error in a new unit test.

   All were caught before any counted run.

Development record:
- DEV-001 to DEV-008;
- dry run 1: 42/43 (P005);
- dry run 2: 43/43.

They are in `evidence/dev/`.

**Unexplained:** none.

**Limits worth knowing:**
- A freeze shorter than 5 s is invisible to Abraham's clock guard. Only the counter's lost steps show it, and only
  when the loss falls within one status round. A short freeze split across two rounds may cost each round fewer than
  the 250 steps the rule allows, and then nobody can see it.
- A launchpad run across a pause has no official judge. The live checks still apply, but the verifier says NOT
  VERIFIED.
- The tests freeze QEMU's threads. A real standby also froze the host (TR-0045), and the kernel saw the same
  signature in both.
