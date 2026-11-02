# `readouts`: the round-1 tie-break keeps a majority's detail; round-5 blocks go to a judge

2026-11-02, branch `feature/readouts-vote-and-fold-judge`. Plan in
`docs/plan/readouts_vote_and_fold_adjudication_plan.md`.

## What was measured

Two independent reviews landed on `readouts`, the least stable field in the schema. Over the
three stored extraction replies of each v3 registry (`assays_raw.json`, round `extract`,
31 papers, 178 delivered clusters):

| field | exact majority | lenient tier | anchor fallback | all null |
|---|---|---|---|---|
| standard_technique_name | 176 | 1 | 0 | 1 |
| sample_type | 161 | 4 | 1 | 12 |
| readouts | 110 | 66 | 2 | 0 |

All three readouts identical in 45 of 173 three-member clusters. So the vote on `readouts` is
settled by the lenient tier (containment or token Jaccard ≥ 0.5) more than a third of the time,
and almost never falls to the anchor.

The two reviews pointed in opposite directions:

- **Round 1** delivered the *shortest* of a leniently agreeing group. On SDY1289's gene array
  that was "gene expression levels" over two runs that both wrote whole-blood RNA on Illumina
  BeadChips: a detail a majority asserted, voted away.
- **Round 5** compares `readouts` by exact string. 22 blocked folds in v3, 14 on `readouts`;
  carrying the lenient match over releases exactly 1 (SDY1291). The other review read that as
  "the leg is binary, drop it or adjudicate it".

## Why `readouts` stays in the identity triple

`_refusal` tests technique, then sample_type, then readouts, so a pair blocked on readouts
already agrees on the other two legs: drop the leg and all 14 fold. Against the curated
benchmark (`data/benchmark_assay/benchmark_assay_v5/`) those pairs are two rows: SDY1328's
GM1-ELISA and multiplex ELISA, SDY1288's IgM-capture and inhibition ELISAs, SDY1640's flow
cytometry / ICS / AIM, SDY1630's flow cytometry and functional assays, SDY212's two flow
entries. One cytometer and one tube of PBMCs run an immunophenotyping panel, an ICS panel and a
phospho-flow panel; only `readouts` tells them apart. That the lenient rule releases 1 of 14 is
not a sign the rule is too weak; it is a sign 13 of the 14 are real differences.

## Part 1 — round 1 tie-break (landed, free)

`assay_consensus._vote_text`: among values that agree with equally many others, the one sharing
the most content words with the other values wins, then the shortest, then anchor order. A word
one run alone added still does not get in; a detail two runs wrote does.

Re-voting the stored v3 replies under both rules (`experiment/readouts_vote_medoid/run.py`,
log `run_2026-11-02.txt`):

| delivered value changed | count |
|---|---|
| standard_technique_name | 0 |
| sample_type | 1 (SDY1289 qPCR: "whole-blood RNA" → "whole-blood RNA samples") |
| readouts | 28 of 178 |

Every change is of the SDY1289 kind: "levels of IL-2, IL-4, IL-5, IL-10, IFN-γ, and TNF" gains
"; beads acquired on a flow cytometer", which two of three runs wrote; the CPE neutralization
readout gains "intact Vero cell monolayer", which two runs wrote. Substituting the 27 new values
that still matched the canonicalized registries into `assays.json` and recounting round 5 gave
22 blocked folds before and 22 after: the change touches no fold.

Tests: `test_a_detail_two_runs_wrote_survives_the_lenient_vote`,
`test_a_detail_only_one_run_wrote_still_does_not_survive` in `test_assay_consensus.py`.

## Part 2 — adjudicating blocked folds (built, not yet run for money)

`apps/api/app/agent/assay_fold_judge.py` with `apps/api/app/prompts/judge_fold.txt`.
`adjudicate(assays, obi, judge)` re-finds the blocked folds on a canonicalized registry and asks
the model once per pair whose only differing leg is `readouts` or `sample_type`; a pair that
differs on the technique is never sent. A literal `SAME` folds the member through
`merge_entries` (its write-up goes to `additional_evidence`, the fold record carries `judged`);
anything else keeps the pair apart and appends the model's reason to the `REVIEW  not folded`
record. Every reply lands under `judge` in `assays_raw.json`. Tests in
`tests/test_assay_fold_judge.py` drive it with a stub judge.

`experiment/fold_adjudication/run.py --dry-run` on v3:

```
22 blocked fold(s), 20 would be asked = 20 call(s) (0.65 per paper). --dry-run: nothing called.
```

The 2 skipped differ on the technique (SDY1264's CPE vs PRNT, SDY984's Luminex vs CBA). The
paid run writes to `experiment/fold_adjudication/runs/`, never in place.

**Decision rule for wiring it into round 5**: run the 20 calls, score `runs/` with
`scripts/compare_assay_benchmark_v2.py --registry-dir`, and read every verdict. The step goes
into `assay_service.py` (after `canonicalize_registry`, before `build_merge_report`, with a
`judge` row in `estimate_run`) only if the benchmark does not lose and no pair the benchmark
keeps apart (SDY1328, SDY212, SDY1630's ICS and CD107a, SDY1640) comes back `SAME`. Otherwise
the 22 `REVIEW  not folded` lines are the final state and the module stays as the record of
what was tried.

## Not done, on purpose

- `readouts` is not removed from `_IDENTITY_FIELDS`; no lenient string match is added to round 5.
- No paper was re-run through rounds 1–4; the paid adjudication waits for a go-ahead.
- The pre-existing 10 test failures in `test_experiment_resolver`, `test_file_reader`,
  `test_input_routing` and `test_query_builder` are unrelated and unchanged (1318 passed).
