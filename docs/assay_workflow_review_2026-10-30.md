# Assay workflow review, 2026-10-30

Reviewed against `data/31paper_assays/assay_result_v3/` scored on `benchmark_assay_v5`
(`comparison/benchmark_v5_vs_agent.json`), the round-1..5 code in `assay_service._run_rounds`,
and the earlier reviews (`assay_entry_grain.md`, the 2026-10-19 Tier 1/2/3 list).

## Where it stands

| metric (31 papers) | value |
|---|---|
| curated rows / agent entries | 157 / 177 |
| recall | 156/157 (0.994) |
| exact OBI | 140 (+5 parent/child) |
| precision / F1 | 0.881 / 0.934 |
| SPLIT annotations | 15 |
| EXTRA / MISSED | 4 / 1 |
| verifier verdicts | ACCEPT 129, REVIEW 48, REJECT 1 |
| corrections | REPLACED 37, CLEARED 3, REAFFIRMED 5 |
| identity_review marks | 9 of 177 |
| minority entries (not delivered) | 8 across 6 papers |

The three extraction replies are genuinely different on every paper (0 of 31 papers have two
identical replies), so the vote is real, though the samples are still correlated (same prompt,
same seed).

## The 17 non-exact rows, by cause

| cause | rows | examples |
|---|---|---|
| curator key has no OBI id (benchmark gap) | 4 | SBA, Immunofluorescence, colony-forming units, lateral_flow_serology |
| multiplex bead panel: curator picks a specific multiplex term, agent picks CBA | 3 | SDY1260 Luminex, SDY1373, SDY1655 |
| PCR / RNA-seq qualifier convention | 4 | RT-PCR vs real-time RT-PCR (SDY1264), qPCR (SDY1289), 16S PCR (SDY1669), bulk vs plain RNA-seq (SDY1373) |
| our side unmapped, since covered by the full-list fallback (post-v3) | 2 | SDY1328 complete blood count, multiplex ELISA |
| compositional prune (policy) | 1 | SDY1630 IFN-gamma term |
| other | 3 | immunoblot vs western blot, metabolomics term, SIMOA miss (by design: Methods-only) |

Reading: the mapper is at its ceiling against this benchmark. Most of the remaining gap is a
convention disagreement with the curator (Luminex term, PCR qualifiers, bulk vs plain RNA-seq)
or a benchmark-side missing id, not a retrieval or picker error. More mapping experiments will
not move it; a convention sheet agreed with the curator and a benchmark fix will.

## Improvements, ranked

1. **The round-5 BROAD re-pick.** 0 of 27 terms changed corpus-wide, yet 16 of 31 v3 papers
   paid for it. Diagnosis: it re-ran round 4's retrieval and handed the picker the same top-20
   minus the BROAD term, i.e. 19 terms already judged not EXACT, and its prompt (rightly) bans
   the analyte-class terms that were the only other candidates. **Decision (2026-10-30, user's
   call, against the recommendation to cut it):** the re-pick now asks over the whole 701-term
   vocabulary minus the BROAD term, and keeps the answer only if it is an `is_a` descendant of
   that term. Expected gain on the corpus is zero: the full-list A/B named a finer term for 0 of
   these 27 (22 same category BROAD, 3 another category, 2 none), because the vocabulary has no
   term for ICS, degranulation, PRNT or FRNT. The cost stays one call per BROAD mapping.
   **Measured the same day** (`experiment/obi_repick_fulllist/run.py`, on copies of the v3
   registries): 25 entries asked, 2 skipped because their term has nothing under it in the
   vocabulary, 24 answered `none`, **1 changed, and wrongly**: SDY1289's "Flow cytometric
   analysis of IFN-γ/IL-2–producing activated CD4 T cells" (PBMC stimulated with peptide pools
   under Brefeldin A, stained for CD154, IL-2 and IFN-γ) moved from `flow cytometry assay` to
   `T cell activation induced marker assay` (OBI:0003230), whose definition reads "detects
   antigen-specific T cells *without the need to identify their cytokine production*". The
   record's readouts are cytokine production; this is intracellular cytokine staining, for which
   the pruned vocabulary has no term, and the AIM term is a sibling protocol that happens to sit
   under flow cytometry, so the descendant guard let it through. The curator has no ICS row for
   SDY1289 and no OBI ids in that file, so the benchmark score does not move either way. Net:
   the full-vocabulary re-pick buys nothing on this corpus and can introduce a definition-level
   error; the recommendation to cut it stands, and the decision is the user's.
2. **A judgement call on blocked folds.** 15 SPLIT rows cost 0.036 precision; ~7 of the
   un-folded pairs read as one protocol written twice (SDY1630, SDY1260 flow pairs). Blocked
   pairs are rare (~20 corpus-wide), so one call per blocked pair with both quotes
   ("same measurement, or different analyte/specimen?") is cheap and is the step
   `assay_entry_grain.md` names as next. The deliverable should also say *why* a `(2)` is apart.
3. **Re-verify REPLACED corrections.** 37 blind replacements enter the deliverable unjudged;
   only replaced quotes and aliases are code-checked. Either re-run the judge on replaced
   `sample_type`/`readouts` (~1 call per replaced field, ~15 per corpus run) or carry a
   `corrected` flag so a reader knows the value is a second opinion.
4. **Settle conventions with the curator** (free): Luminex/multiplex → which OBI term;
   when "bulk" is earned; qPCR vs qRT-PCR; add OBI ids to the 4 benchmark keys that lack one.
   Then re-score; the honest ceiling is probably ~150/157 exact.
5. **Scorer and design disagree about SPLIT.** The pipeline delivers one entry per measurement
   by design, and the scorer counts every extra entry on a curator's row as a precision hit.
   Report precision at both grains, or mark a SPLIT whose members differ on the identity
   triple as not-a-fault. The comparator also still folds leftover curated rows onto a paired
   row on the same OBI id (Tier 3, open), which hides over-folding.
6. **Atomic output.** `_run_rounds` deletes the previous run's files before round 2 starts; a
   crash in rounds 2-5 leaves the paper with no registry. Write to a temp dir, swap at the end.
7. **Decorrelate round 1 (optional).** Vary the seed per run, or the section order, so the
   three samples are less correlated. Only worth it if MINORITY lines keep hiding real assays;
   today none of the 8 minority entries costs a curated row.
8. **PDF route.** 4 papers deliver `sentence_ids: []`, `source: null`. Numbering the text
   layer's sentences would give ids and a crude Methods/Results split for free.
9. **`generate_claim` is unscored.** 169 true / 8 false; the comparator carries it but never
   compares it. If it is meant to be checked against the benchmark, add the score; if not,
   say so in the deliverable's docs.

Not re-proposed (already tested and rejected, see memory): BROAD/technique fold rules,
wider TOP_K, BM25, tree descent as default, folding several entries on one term into one.
