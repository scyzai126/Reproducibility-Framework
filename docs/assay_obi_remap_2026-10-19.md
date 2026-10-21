# OBI re-map of six papers after the round-4 fixes (2026-10-19)

*Paid run, approved by the user after a free `--dry-run` estimate. Follows
`docs/assay_obi_mapping_review.md` ("Code-level review and fixes"). Command per paper, from the
repo root:*

```
.venv/bin/python scripts/run_assay_merge.py data/31paper_assays/stability/<paper> --map-all --judge
```

Round 4 ran on each paper's `assays_corrected.json` with the fixed mapper (seeded pick, 4 workers,
label-first lookup, unreadable reply → error); round 5 then re-keyed with the fold judge. Files
were overwritten in place; the previous term per entry was snapshotted first for this comparison.

## Result in one line

**All 42 entries mapped to the same OBI term as the previous run.** No `OBI ERROR`, no `UNMAPPED`,
no `FOLD JUDGE FAILED`, no `REVIEW UNFOLDED`. What changed is round 5: three pairs the earlier
(unjudged) run had folded are now kept apart by the judge, so three papers deliver one more assay.

## Cost

| paper | entries | picks | embeddings | judge | free exact hits |
|---|---|---|---|---|---|
| 19029902_SDY1264 | 9 | 8 | 15 | 1 | ELISA |
| 36656789_SDY1393 | 3 | 3 | 5 | 0 | — |
| 34252919_SDY2189 | 10 | 9 | 18 | 1 | CITE-seq |
| 28502771_SDY984 | 11 | 11 | 21 | 1 | — |
| 20078211_SDY1293_pdf | 3 | 3 | 6 | 0 | — |
| 28687661_SDY1294 | 6 | 6 | 11 | 1 | — |
| **total** | **42** | **40** | **76** | **4** | |

120 calls against an estimate of 116 + ≤3. Every pick reply parsed (`assays_raw.json["obi"]`).

## Term stability

42 of 42 entries: same `obi_id` as before. Resources: 28 `embedding_llm`, 4
`embedding_llm_normalized` (the technique query alone reached the term: CPE neutralization,
ICS ×2, GeneChip), 5 `exact_original_llm` (pinned exact hit refined by the picker: microarray →
transcription profiling by array; RNA-seq → bulk RNA-seq; flow cytometry ×3), 2 `exact_original`.

Granularity: 31 EXACT, 9 BROAD, 2 none (free hits). BROAD entries are the known families: PRNT /
FRNT / CPE neutralization on `serum neutralization of viral infectivity assay` (5), ICS-type on
`flow cytometry assay` (2), nested PCR on `polymerase chain reaction assay`, thick blood smear on
`microscopy assay`, immunofluorescence serology on `immuno staining assay`.

One run after the fix is not a variance measurement: it shows the seeded mapper reproduces the
earlier terms on these 42 entries, not that it would across many runs. The earlier run-to-run
change (9 of 31 papers) was measured between two unseeded runs.

## Round 5: what the judge did

The previous files were canonicalized before the fold judge existed, so every same-term pair had
folded. With `--judge`:

| paper | pair on one term | judge | reason (verbatim) |
|---|---|---|---|
| SDY1264 | `neutralizing antibodies by cytopathic effect` + `plaque reduction neutralization test` → serum neutralization of viral infectivity assay | **KEPT APART** | "These are different measurements because the stated techniques differ (CPE-based virus neutralization assay vs PRNT), even though both measure YFV neutralizing antibodies in blood-derived specimens." |
| SDY2189 | `Focus reduction neutralization titre assay` + `FRNT assay against the variants of concern` → serum neutralization of viral infectivity assay | **MERGED** | one measurement (both BROAD this run; the earlier EXACT/BROAD flip that once split them did not recur) |
| SDY984 | `Zostavax®-specific IFN-γ, IL-4 and IL-21 ELISPOT` + `Zostavax®-specific and total IgG B cell ELISPOT` → enzyme-linked immunospot assay | **KEPT APART** | "Both use ELISPOT on PBMCs, but they measure different analytes: cytokine-secreting T-cell responses (IFN-γ/IL-4/IL-21) versus VZV-specific and total IgG-secreting B cells." |
| SDY1294 | `flow cytometry` + `T cell function` → flow cytometry assay | **KEPT APART** | "Both use flow cytometry on PBMCs, but one is general immunophenotyping/intracellular protein staining while the other is a distinct peptide-stimulated intracellular cytokine assay measuring T cell function." |

Delivered entry counts: SDY1264 8 → 9, SDY984 10 → 11, SDY1294 5 → 6; SDY2189 stays 9;
SDY1393 and SDY1293 unchanged at 3. The three splits are the fold-judge rule working as
designed (technique + analyte + specimen); the earlier review had listed SDY1264's two
neutralization assays and SDY984's two ELISPOTs among the wrong term-only folds.

## Files touched

Only the six folders under `data/31paper_assays/stability/`: `assays.json`, `assays_OBI.json`,
`assays_benchmark.json`, `assays_merges.json`, and `assays_raw.json` (obi and canonicalize rounds
replaced, other rounds kept). No code, prompt, vocabulary or test changed.
