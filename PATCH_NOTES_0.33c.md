# Abraham 0.33c: patch notes (for Jadin)

2026-11-10. Decision **D-ABR-026** (the 0.33c final-audit directive). Workspace `Documents\Abraham\work-0.33c`, copied
from `work-0.33` (196 files, all equal: `COPY_MANIFEST_FROM_0.33.json`). Launcher correction in the new tree
`vmlauncher-0.33.2`, copied from `vmlauncher-0.33.1` (24 files, all equal). Test records **TR-0049** (0.33c audit:
Phases 1, 2 and 4) and **TR-0050** (launcher 0.33.2). TR-0047 and TR-0048 are Cyberforteca records, written by
another session while 0.33c was in progress.

- **The kernel is unchanged:** Abraham 0.33.0-dev `6b95b9a2...`, the binary TR-0042 tested. The MOSKO(TM) signature
  is a source comment; the binaries built with it are byte-identical to those built without it.
- **Use the corrected launcher:** double-click `vmlauncher-0.33.2\Abraham-VM-Launcher.exe` (`d7f2fc57...`). The
  earlier programs in `vmlauncher-0.33` and `vmlauncher-0.33.1` stay as recorded.
- **0.33 is still not accepted.** Criteria B, C and D are met. A and E are Echo's audit and your sign-off.
- **Your performance test:** `work-0.33c\docs\0.33c_OPERATOR_CHECKLIST.md`.
- **The 0.34 First Light proposal is separate:** `ABRAHAM_0.34_FIRST_LIGHT_DESIGN_PROPOSAL.md`. Nothing of 0.34 is
  implemented; that waits for your approval.

## What 0.33c did, in plain words

1. **Checked the foundation (Phase 1).** Every identity, index, package and record from the frozen boot (ABR-BOOT-001)
   up to TR-0046 was re-hashed and compared with what the records say.
   - Result: **RECONCILED.** The records are contiguous (D-ABR-001..026, TR-0001..046), and no decision accepts 0.33.
   - One historical mismatch is already on record (TR-0034: an edited 0.31a patch-notes file). It is accepted only
     with its exact digest.
2. **Reproduced the tests (Phase 2).** The whole 0.33 campaign ran again in `work-0.33c`, on the tested binaries:
   95 entries, WHPX and TCG. It covers:
   - the hosted tests and the 17 launchpad requests;
   - C13's positive and negative controls, and the falsified logs;
   - memory, D-ABR-012, service, fault and clock regressions;
   - every earlier accepted kernel under its own profile.

   **94 of 95 were as expected.** The one UNEXPECTED, B001 (a rebuild in a new folder is not byte-identical), was
   predicted in writing before the run. The reason is that the ELF symbol table holds the folder path. B002 then
   showed that every loaded section is identical. The launcher 0.33.1 findings were also reproduced: 10 of 11 as
   expected, with one test-design error of mine (below).
3. **Answered the two audit questions (Phase 3).** Neither needs a kernel change.
   - **A clock gap's cause.** When Abraham reports that its clock jumped, that alone does not say why. The 0.33.1
     launcher called every such gap a "host pause". That was a claim it could not support: a jump injected inside
     the guest (O003/O004, no pause at all) got the same label. Launcher 0.33.2 calls it a host suspension only with
     host evidence, namely that the launcher itself was stopped at the same time. Otherwise it says "cause not
     established" and ends with the new code 11. While examining this I found **F-VML-03**: 0.33.1 also flagged the
     services on those logs, because the first round after a jump can still say `clock=OK`. That is corrected too.
   - **A judge for the launchpad on a degraded clock.** No official judge covered it, so TR-0046 P004 was NOT VERIFIED.
     0.33.2 adds a **composite** judge. It only combines the official launchpad and degraded-clock rules, and it is
     labelled composite, never official.
4. **Signed the source (Phase 4).** The MOSKO(TM) ASCII signature is now at the top of `kernel/src/main.rs` and in the
   README. The production, launchpad and early-fail kernels were rebuilt with it. Each is **byte-identical** to the
   build without it, and its loaded sections equal the tested binary's. The signed production kernel passed C0-C13
   and the signed launchpad passed all 17 requests.
5. **Packaged it for Echo (Phase 5).** See "The package" below.
6. **Designed 0.34 (Phase 6), as a proposal only.**

## What changed

| File | Change |
|---|---|
| `work-0.33c/kernel/src/main.rs` | the MOSKO(TM) signature as `//` comment lines at the top (`d546a733` -> `f72f050b`). Comment only |
| `work-0.33c/README.md` | the same signature under the title; the 0.33c status |
| `work-0.33c/tools/g033c/` (new) | the reconciler, the campaign derivation (four recorded substitutions, with its diff), the launcher reproduction, the signature proof, the evidence index and the packager |
| `work-0.33c/docs/` | the audit clarifications, this checklist, the limitations register, the review |
| `vmlauncher-0.33.2/src/observe.rs` | "host pause" becomes "clock gap reported by the kernel". C12's counter-pair findings are not counted once the kernel has reported DEGRADED |
| `vmlauncher-0.33.2/src/main.rs` | version 0.33.2. The launcher measures its own stops (more than 2 s, monotonic and wall clock). Each kernel-reported gap gets a cause: HOST_SUSPENSION or NOT_ESTABLISHED. New result `CLOCK_ANOMALY_CAUSE_NOT_ESTABLISHED` (exit 11). The record and the result block say which. The panel's CLOCK row is compact, cause first, so it fits 120 columns. The record, the panel and the offline check list the counted service problems |
| `vmlauncher-0.33.2/tools/` | `judge_launchpad_degraded.py` (the composite judge, 9-case self-test); `pause_host.py` (freezes QEMU and the launcher together, as a standby does); `verify_run.py` uses the composite judge; the campaign gains F004, F005 and P006 |
| `vmlauncher-0.33.2/README.md`, `docs/VM_LAUNCHER_DESIGN.md` | the clock-gap wording and exit code 11 |

## Evidence

**0.33c audit (TR-0049):**
- reconciliation: `work-0.33c\evidence\reconcile\ABR-0.33c-R004`, RECONCILED;
- reproduction: `work-0.33c\evidence\campaign-033c` (95 entries, 94 as expected, B001 predicted) and
  `evidence\launcher-0.33.1-repro` (11 entries, 10 as expected);
- the signature: `evidence\phase4\ABR-0.33c-P4`, SIGNATURE CHANGES NO BINARY.

**Launcher 0.33.2 (TR-0050).** The counted campaign is `vmlauncher-0.33.2\evidence\campaign-vml`, 2026-11-11
02:29:02 to 02:42:16 UTC:
- program `d7f2fc573421134bc4325128f3f896ea79e0afd25586e3c6f5fa641622fb67e4`, and two clean builds identical to it
  (B001);
- **46 entries, 46 as expected**; no source change; every expected outcome fixed beforehand (`EXPECTED.json`).

| Entry | Result |
|---|---|
| F004 | 3A and F-VML-03 reproduced first. On the guest-injected jump (O003, O004), the 0.33.1 program says "host pause" and flags the services ("3602925 ms after the previous round"). The 0.33.2 program reports a clock gap 3 -> 3603 (3599 s), contract CONSISTENT, and no services problem |
| F005 | the composite judge's self-test: 9 of 9 cases right |
| P001, P002 | QEMU alone frozen 30 s (WHPX, TCG). Gap 10 -> 40 (29 s), cause NOT_ESTABLISHED, exit 11. VERIFIED by `launch_probe` degraded-clock |
| P003 | 4 s freeze: "round 4: svc.counter advanced 96 steps"; exit 10; VERIFIED |
| P004 | launchpad, QEMU alone frozen 30 s: exit 11. **VERIFIED by the composite judge.** TR-0046's P004 was NOT VERIFIED |
| P005 | the real window: `CLOCK : DEGRADED: cause not established \| gap reported by the kernel, 10 -> 40 s (29 s) \| stale data never trusted` |
| P006 | QEMU and the launcher frozen together 30 s (a host suspension). The launcher measured its own 30.0 s stop. The gap is a HOST_SUSPENSION; exit 0 OK; VERIFIED |
| X002 | 19 runs compared with their judges, 0 disagreements |
| A001-A010, N001-N017 | as TR-0046: OK and VERIFIED; every refusal and failure with its own code |
| V001, V002 | `work-0.33` (7,096 files), `vmlauncher-0.33` and `vmlauncher-0.33.1` unchanged |

**Three launches I did not start.** `vmlauncher-0.33.2\runs` holds three launches from 2026-11-11, 00:28-00:31 UTC,
between dry run 3 and the counted campaign. All three were made with the final program `d7f2fc57...`, each in a window
created for the launcher (a double-click), and each quit with Q:
- `VML-20261111T002831Z`: launchpad;
- `VML-20261111T002930Z` and `VML-20261111T003028Z`: production.

All three ended OK (exit 0) and are VERIFIED (`evidence\operator`). I take them to be yours. They are recorded as
operator launches, outside the counted campaign, and packaged.

## What went wrong along the way (every failure, and why)

- **Reconciler R001 crashed.** I unpacked a three-field tuple as two. Fixed; the empty run folder is kept.
- **Reconciler R002 misread the record index.** A heuristic guessed a row's category; replaced by a column-count rule.
- **Reconciler R003 found one mismatch.** It is the historical TR-0034 one, already recorded. It was added as a known
  exception with its exact digest, so R004 is RECONCILED. Nothing was hidden: R003 stays as it ran.
- **The first campaign attempt was refused at its freeze step.** The copied `build/build-info.json` was the repro-mode
  file written after the original B001, not the kernel-mode record. I restored the kernel-mode record from W001's
  own host record (`SETUP_build_info_restored.json`) and ran again (run 2). Attempt 1's console is kept.
- **B001 UNEXPECTED (predicted).** A rebuild in a new folder differs in the symbol table only (L-08). It is not re-scored.
- **Launcher reproduction X002 UNEXPECTED (my test-design error).** I copied 0.33.1's agreement threshold ("at least
  16 runs") into an 11-entry subset that has only 4 such runs. All 4 agreed, with 0 disagreements. The entry stays
  UNEXPECTED as it ran.
- **Two files written in the wrong place during the campaign.** I wrote the audit-clarification draft and the
  reproduction tool into folders the campaign's source manifest covers. I moved them out before the campaign closed,
  verified the covered tree was identical to its start manifest, then put them back. The campaign's end check
  (`source_changed_during_campaign: []`) passed only because I moved them out first. Neither file is part of what the
  campaign tested, but the slip is recorded here and in TR-0049.
- **Phase 4 rebuilt two DIAGNOSTIC kernels in place** in `work-0.33c/build/diag` (launchpad, early-fail). Their loaded
  sections are identical, and the tested binaries are preserved in `work-0.33` and packaged (L-15).
- **Launcher 0.33.2 dry run 1 found two defects of mine** (program `2088da9c...`, also used by the development runs
  DEV-001/002). The dry run is uncounted and exists to catch exactly this.
  - **P003:** the 4 s freeze run itself was right (code 10, the verdict naming the counter's progress), but the
    record's `service_problems` list was empty. I had moved C12's pair findings to a separate list and left the
    record, the panel's SERVICES marker and the offline check reading the old one. All three now use the counted
    list, and a unit-test assertion covers it.
  - **P005:** in a real 120-column window the panel's CLOCK row was cut off at "cause not", so the operator could not
    read the cause. The panel now uses a compact row that puts the cause first. The result block and the record keep
    the full text.

  Dry run 1 was stopped to fix them (`evidence/dev/dry-run-1`, with P003's sealed run). Dry run 2 (program
  `1e1727cc...`) was stopped after 12 entries, all as expected, when the second fix changed the source again
  (`evidence/dev/dry-run-2`). Dry run 3 ran on the final program `d7f2fc57...`.

## The package

`work-0.33c\evidence\review\ABRAHAM_0.33c_ECHO_AUDIT.zip`, one compact package for Echo. Its digest is in the
`.sha256` beside it and in TR-0049's row of `test-records\INDEX.md` (the package contains this file, so the digest
cannot be written here). It holds:
- the records (DECISIONS.md, both directives, TR-0042, TR-0044-TR-0046, TR-0049, TR-0050) and these patch notes;
- the changed source and its diffs (the signature edit, the launcher 0.33.2 source and its copy manifest);
- the tested programs: the kernels of the campaign BUILD_MANIFEST (the tested ones from `work-0.33` where Phase 4
  rebuilt them), launcher 0.33.1 `c09f1cbf...` and 0.33.2 `d7f2fc57...`;
- the raw QEMU and host evidence of every 0.33c run, without boot disks (ESP, `vars.fd`), which are pinned by digest
  in each run's seal and listed in `OMITTED.json`;
- the official judges, the composite judge, the reproduction instructions (`docs\0.33c_REVIEW.md`), the negative
  controls, the manifests and seals, and both evidence indexes.

`verify_audit_033c.py` inside it re-checks everything after extraction.

## Still open

The register is `work-0.33c/docs/0.33c_LIMITATIONS_REGISTER.md`, with 20 entries, none a kernel release blocker.
- **Open:** criterion A (Echo's review of the launcher contract) and criterion E (Echo's audit, then your sign-off).
- **Also to confirm:** the signature's exact text. Your approval is on record, but its text was not supplied (L-17).
