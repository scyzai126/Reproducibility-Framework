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

## Part 2 — adjudicating blocked folds (run, scored, wired in as round 6)

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

### The paid run (20 calls, `experiment/fold_adjudication/run_2026-11-02.txt`)

| verdict | pairs |
|---|---|
| SAME | 1 — SDY2189: FRNT "(2)" onto the FRNT entry; the benchmark lists one FRNT row |
| DIFFERENT | 19 |

Every pair the benchmark keeps apart came back DIFFERENT with the right reason: SDY1328 "anti-
Cholera toxin B subunit IgG whereas Record B measures anti-Diphtheria IgG"; SDY212
"immunophenotyping whereas Record B measures cytokine-induced STAT1/3/5 phosphorylation";
SDY1630's three NK pairs (profiling, IFN-γ production, CD107a degranulation); SDY1640, SDY1655,
SDY1294, SDY1364 (immunophenotyping against ICS); SDY984 (cytokine against IgG ELISPOT); SDY1260
(serum isotypes against supernatant cytokines). SDY1291's two array write-ups came back
DIFFERENT too — "Affymetrix Human Exon ST for the in vivo study vs Agilent SurePrint for the
in vitro study" — where the benchmark writes one Affymetrix row; two platforms are two
measurements by the extraction's own rule, so this stays a REVIEW line rather than a fold.

Scored with `scripts/compare_assay_benchmark_v2.py` (baseline rerun the same day as
`assay_result_v3/comparison/benchmark_v5_vs_v3_baseline_2026-11-02`, judged copies as
`experiment/fold_adjudication/runs/comparison/benchmark_v5_vs_judged_2026-11-02`):

| | agent entries | matched (exact) | missed | extra | split | precision | recall |
|---|---|---|---|---|---|---|---|
| v3 as stored | 177 | 156 (140) | 1 | 4 | 15 | 88.1% | 99.4% |
| after the judge | 176 | 156 (140) | 1 | 4 | 14 | 88.6% | 99.4% |

One split removed, nothing lost. The decision rule held, so the step is wired in.

### Round 6 in the pipeline

- `assay_service._run_rounds`: after round 5 writes its report, round 6 (`rounds["judge"]`)
  runs `adjudicate` on the canonical registry when any blocked fold is judgeable, else reports
  `skipped` with 0 calls. A failed call leaves round 5's report standing (`source: failed`).
  `reconcile_report` carries each verdict back onto round 5's own blocked record (by the
  paper's wording, found through `key_map`), writes a SAME fold by the wordings it folded, and
  points every folded wording at the survivor in `key_map`.
- `estimate_run` adds a round-6 row: one call per refused pair on the last run's registry,
  `basis: last_run`, `None` when nothing is stored. `run_assay_pipeline.py --dry-run` prints it
  with the pairs it would ask about.
- `run_assay_pipeline.py` prints `JUDGED  SAME: <reason>` under a judged `MERGED` line and
  `JUDGED  DIFFERENT: <reason>` under a judged `REVIEW  not folded` line.
- `run_assay_merge.py --judge` runs round 6 on a stored registry (`--judge --dry-run` counts).
- Tests: `test_assay_fold_judge.py` (module, with `reconcile_report`), four round-6 tests in
  `test_assay_service.py` (SAME folds, DIFFERENT keeps the record with its reason, nothing
  refused never calls, a failed call leaves round 5 standing), the round-6 estimate row in
  `test_assay_estimate.py`, the printer in `test_run_assay_pipeline.py`. Chain tests stub the
  judge to DIFFERENT (`stub_judge`, autouse) so none reaches the network.

## Not done, on purpose

- `readouts` is not removed from `_IDENTITY_FIELDS`; no lenient string match is added to round 5.
- No paper was re-run through rounds 1–4. The v3 registries on disk are unchanged: the judged
  copies live under `experiment/fold_adjudication/runs/`.
- The pre-existing 10 test failures in `test_experiment_resolver`, `test_file_reader`,
  `test_input_routing` and `test_query_builder` are unrelated and unchanged (1318 passed).
