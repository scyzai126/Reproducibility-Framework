# Assay workflow review, 2026-10-30 (second pass): the vote, the alias union, stale docs

Reviewed the five-round chain as it stands after the BROAD re-pick was removed (commit
3c1d607): `scripts/run_assay_pipeline.py` → `assay_service._run_rounds`, every module it calls,
and the hand-offs between rounds. Checked against `data/benchmark_agent_assays/assay_result_v3/` by
re-voting each paper's three stored extraction replies (`assays_raw.json`) rather than by paying
for a run. The earlier review the same day (`assay_workflow_review_2026-10-30.md`) covered
scoring and cost; its open items are not repeated here.

## Findings

### 1. The round-1 vote depended on which reply was called "run1" — fixed

`assay_consensus.cluster_for_vote` aligned a lone entry (one run, one key) only against clusters
already passed, walking clusters in run order. Since all of run1's keys are emitted first, a
run1-only wording could never join a run2+run3 cluster that named the same assay differently. It
went to `assays_minority.json` and printed a `MINORITY` line although the assay was delivered. The
three extraction calls run concurrently and are labelled by slot, so which reply is "run1" is
arbitrary.

Measured by re-voting the stored v3 replies in all three rotations:

| | before | after |
|---|---|---|
| papers whose minority set changes with rotation | 10 of 31 | 0 of 31 |
| `MINORITY` entries delivered in v3 (stored run order) | 8 | 4 |

The four that disappear are run1-only wordings that `same_entry` matches a delivered entry
(SDY1364 chemokine-receptor staining, SDY212 tetramer staining, SDY1373 RNA sequencing,
SDY1654 flow cytometry). Delivered counts did not change on any paper.

Fix: tier 2 now considers every cluster, earlier or later, that has no member from the lone
entry's run and that `same_entry` matches, and attaches one (lone, host) pair at a time, always
the best left — the host more runs agree on, then the lone entry's normalized name, then the
host's. The same-run guard is unchanged. Tests: rotation invariance on the ICS fixture, the
first-run case, host preference, lone-to-lone majorities, and the guard under every rotation.

### 2. Round 3 paid to delete aliases the paper does not contain — fixed

Round 1 unions aliases across runs on the grounds that an absent alias is caught for free by
round 2's string check. It was, but as a NOT_SUPPORTED position, which forced the record to
REVIEW and billed one round-3 alias call. In v3, 7 of 28 flagged alias positions were "does not
appear anywhere in the source text" — each a paid blind re-read to delete a string a free check
had already settled, and the corrector can only ever drop such an alias or hallucinate it back.

Fix: `assay_verifier.drop_absent_aliases` runs after the vote and before anything is written or
judged; drops are recorded under `rounds.extract.aliases_dropped` and printed by the CLI as
`DROPPED ALIAS  <key>: '<alias>' does not appear in the source text`. On the v3 replies it
removes exactly those 7 wordings. `too_short` and `no_alias` are not `missing`, so a two-letter
acronym is left for the judge. The verifier's own alias check stays, as the second line.

### 3. Docstrings describing a chain that no longer exists — fixed

`run_assay_pipeline.py` explained chaining by way of `platform` (removed) and said "Round 3
promotes" alongside "assays.json is written only once every round is done"; `assay_service`,
`assay_trace` billed round 1 as one call (it is `EXTRACTIONS` = 3); `assay_verifier` and
`assay_corrector` led with `platform`. Text only.

### Checked and fine

- **Abstract**: included as the first `[abstract]` section; the extraction prompt sweeps it in
  pass 2 and admits a NEW_ASSAY from it only on a "performed here" sentence. `derive_source`
  would label an abstract-only quote `results` (the `source` enum has no `abstract`); no v3 entry
  cites only abstract sentences, so this is latent.
- `identity_review`, `additional_evidence` and `generate_claim` ride through correction, the
  fold and `trim_registry` as documented.
- Round 5 is free and deterministic; `estimate_run` and `_run_rounds` agree. `--dry-run` on
  SDY1260 prints the same estimate before and after.
- Full backend suite: 1303 passed, 2 skipped, 10 failures pre-existing on HEAD in unrelated
  modules (`test_experiment_resolver`, `test_file_reader`, `test_input_routing`,
  `test_query_builder`), identical list on a clean checkout.

## Still open (from the earlier review)

Blocked-fold adjudication (22 blocked folds in v3, 14 on `readouts` prose), re-verifying the 37
REPLACED corrections, atomic output across rounds 2-5, PDF-route sentence numbering, scoring
`generate_claim`, a curator convention sheet.
