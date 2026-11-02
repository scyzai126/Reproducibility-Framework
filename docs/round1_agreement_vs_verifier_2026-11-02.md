# Round-1 agreement against the verifier, 2026-11-02

Prompted by an outside review that argued (1) round-1 unanimity has no triage value, so no
"skip round 2 when unanimous" cost logic, and (2) the vote's margin is thrown away, and a
`runs_agreed` field would shrink the 48-entry REVIEW queue to 5. Checked for free by re-voting
the three stored extraction replies of every v3 paper (`assays_raw.json`, via
`assay_consensus.cluster_for_vote` / `consensus`) and cross-tabulating against
`assays_verification.json`. 178 delivered entries; 48 REVIEW/REJECT, as in the 10-30 review.

## 1. Unanimity: the conclusion holds, the evidence given for it does not

The review's figures (35 unanimous, 8 flagged; 142 disagreeing, 40 flagged) reproduce only when
"unanimous" ignores `aliases` and the quote. Those are where the flags live: of 59 field
verdicts the verifier would not support, 25 are an `aliases[i]` and 5 the quote.

| unanimity definition | unanimous | flagged | rest | flagged |
|---|---|---|---|---|
| strict, every field incl. aliases and quote | 19 | 1 (5%) | 159 | 47 (30%) |
| strict, the 5 scalar fields only (≈ the review's) | 34 | 7 (21%) | 144 | 41 (28%) |
| lenient text match, aliases excluded | 92 | 24 (26%) | 86 | 24 (28%) |

So unanimity is a real signal when every field counts. The skip is still not worth building:
19 of 178 entries qualify (about 0.6 round-2 calls per paper, ~11% of round 2), and one of them
(SDY212 ELISA, `readouts` NOT_SUPPORTED) would ship unjudged. CLAUDE.md's rule that an
unverified registry cannot be told from a verified one by reading it is the argument.

The `standard_technique_name` point (16 disagreements, 0 flags) is empty: the field is in
`assay_verifier._NOT_PROPOSED`, so the verifier never rules on it.

Per field, a round-1 disagreement predicts a flag only on `aliases` (18 of 81 disagreeing
entries flagged vs 5 of 97 agreeing). `readouts` disagrees on 131 of 178 (paraphrase) and
predicts almost nothing.

## 2. The vote's margin: the numbers are wrong, the small idea is right

Only 5 delivered entries corpus-wide are 2-of-3: SDY1289 "FACS analysis of PBMCs" and SDY180
"commercial immunoassays" (both REVIEW), SDY984 nested PCR, SDY1288 virus isolation and SDY1655
ICS (all ACCEPT). "48 → 5" conflates two unrelated doubts: REVIEW means the verifier would not
support a proposed field; 2-of-3 means one extraction never listed the assay. Recording the
margin does not shrink the REVIEW queue. It surfaces a signal that was silent: a 1-of-3 entry
printed `MINORITY`, a 2-of-3 entry printed nothing, and the three ACCEPTed 2-of-3 entries are
exactly the borderline real hits the 2026-10-19 stability re-run worried the vote would drop.

## What changed

- `assay_consensus.consensus_with_support` returns, per delivered key, `{"runs", "of"}`;
  `consensus` is unchanged.
- `_run_rounds` records the bare-majority keys under `rounds.extract.partial`.
- `run_assay_pipeline.report_result` prints `VOTE  <key> → <delivered key>: found by 2 of 3
  extractions; delivered`, after the `MINORITY` lines. Re-voting v3 offline prints exactly the
  five entries above.
- No field was added to `assays_benchmark.json`; no round is skipped on unanimity.
