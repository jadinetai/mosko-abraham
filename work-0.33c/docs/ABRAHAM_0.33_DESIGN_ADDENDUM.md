# ABRAHAM 0.33 design addendum: qualifications carried forward (D-ABR-023)

- 2026-11-08. This file is a companion to `ABRAHAM_0.33_DESIGN.md`. That file is the approved design (D-ABR-022), copied
  unchanged: `06e44c74c82c189e10673a564a452ba6e883d98e77fe5547c2043ed1bc0a0162`.
- **This addendum changes no approved behavior.** It records wording that the approved design must be read with.

## 1. Echo, Recommendation 3 (final review, `..\..\MOSKO_ABRAHAM_032B_ECHO_FINAL_AUDIT_2026-11-08.md`)

1. **The request id is a bounded ordering mechanism, not authenticated replay protection.**
   - A request id is accepted only if it is greater than the last admitted id of the boot epoch (design §4.3, Q4).
   - This orders the requests the kernel itself submits, and refuses an out-of-order repeat with `REQUEST_REPLAYED`.
   - It authenticates nothing. 0.33 has no actor, session, origin binding or integrity check on a request, so any
     submitter that could reach the launcher could choose any larger id.
   - Every description of `REQUEST_REPLAYED` in 0.33 code, lines and documents says "id not greater than the last
     admitted id" and never "replay detected" in a security sense.
   - Authenticated replay protection belongs with the session and authority work (P-20, P-34), not 0.33.
2. **The `app.browser` requirement on `svc.netmon` is provisional.**
   - It stays as approved for 0.33 (Q1): `app.browser` requires `svc.netmon`, and so reports UNSATISFIED.
   - The future offline browser must not require working network monitoring merely to render local content. A later
     revision may give it no network requirement for local rendering, or a requirement only for remote fetching.
   - The descriptor comment and the APPINFO documentation say "provisional".

## 2. D-ABR-021: wording of the failure threshold

"3 in a row" and "3 consecutive overruns" in the 0.32/0.32b texts mean **three overruns without an intervening
verified in-budget step**, not necessarily three adjacent calls. The 0.33 copies of the comments say so. The behavior
and the parameters are unchanged: 1,000 µs, 3, 100, 1,000 ms, 5 s.

## 3. Echo, Recommendation 4: for the 0.34 design (not 0.33 work)

The 0.34 design must include:
- a bounded kernel heap preserving D-ABR-012;
- a pinned cross C toolchain, with every download needing a separate owner approval;
- explicit compliance with P-19, including the prohibition of a general-purpose TCP stack in the ratified 0.1 scope;
- a NetSurf GPL-2.0 licensing and distribution review;
- separation between kernel-owned memory and eventual browser application memory.

**Not authorized by this list:** downloading tools, changing the ratified baseline, executing NetSurf inside the
kernel, or any 0.34 implementation.
