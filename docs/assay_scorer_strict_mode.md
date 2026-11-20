# Assay scorer: strict mode

*2026-11-02. `scripts/compare_assay_benchmark_v2.py --strict`. Reports:
`data/benchmark_agent_assays/assay_result_v3/comparison/benchmark_vs_agent{,_strict}.{json,html}`.*

The comparator had two leniencies that flatter whichever side is scored, noted as Tier 3 of the
2026-10-19 review and left open until now. Before any baseline arm is set beside the agent, the
scorer needed a mode without them, so that every column of the comparison table is computed the
same way. The default mode is unchanged, so every number in earlier write-ups still reproduces.

## What strict changes

1. **No leftover fold.** By default a curated row that found no partner folds into a paired row on
   the same OBI id within the paper, so it is never MISSED and the denominator shrinks (157 instead
   of the 158 rows the curators wrote). Strict keeps every row: a leftover is MISSED.
2. **Term-only pairs are taken last.** A pair the ontology alone made (same term, or parent/child)
   with nothing in the names, aliases or short forms to confirm it now ranks below every pair that
   has such a name signal, whatever that pair's tier. It is taken only when nothing better claims
   either side. A pair made by a shared evidence sentence alone ranks below the term-only pair,
   because one Methods sentence often names several assays. The pairs taken on the ontology alone
   are counted as `term_only_pairs` in both modes and flagged on the row.

`quote names the other side` is not treated as a name signal for the same reason: the agent's
quote for an array assay can name flow cytometry because the sentence lists both.

## Agent v3, default vs strict (31 papers, benchmark v5)

| | default | strict |
|---|---|---|
| benchmark rows | 157 (raw 158) | 158 |
| agent entries | 177 | 177 |
| matched | 156 | 156 |
| exact OBI term | 140 | 140 |
| OBI ok (same or parent/child) | 145 | 145 |
| MISSED | 1 | 2 |
| EXTRA | 4 | 4 |
| term-only pairs | 6 | 6 |
| recall | 99.4% | 98.7% |
| precision | 88.1% | 88.1% |
| F1 | 0.934 | 0.931 |
| OBI exact rate | 89.7% | 89.7% |
| OBI recall | 92.4% | 91.8% |

The one row strict adds as MISSED is SDY1669 `Flow cytometry analysis of PBMCs`: the curator
wrote it and `intracellular staining assay` as two rows on `flow cytometry assay`, the agent
delivered one flow cytometry entry, and the default fold hid the second row. The other MISSED is
SDY2189's SIMOA in both modes, which never appears in Methods and is not taken by design.

The six term-only pairs, read against the papers, are all the same assay on both sides; they just
share no wording:

| paper | curator row | agent entry (its wording) |
|---|---|---|
| SDY1264 | Assay for yellow fever virus (YFV) neutralizing antibodies | serum neutralization of viral infectivity assay (neutralizing antibodies by CPE) |
| SDY1264 | immunoblot assay | western blot assay (immunoblot analysis), parent/child |
| SDY1294 | microarray analysis | transcription profiling by array assay (microarray hybridization) |
| SDY1669 | PCR quantitation of bacterial 16S rRNA gene product | polymerase chain reaction assay, parent/child |
| SDY1991 | ELISA | enzyme-linked immunosorbent assay (DENV-specific IgG ELISAs) |
| SDY984 | cytokine bead array assay | cytometric bead array assay (Multiplex cytokine assays) |

So for the agent the strict number is the default number less one fold. The mode matters more for
the baselines: a dictionary or annotator arm that delivers many entries on one term would have had
every leftover curated row on that term folded away, and every one of its term-only pairs taken
before the pair the names made.

## Use

```
python3 scripts/compare_assay_benchmark_v2.py --registry-dir <dir>            # default
python3 scripts/compare_assay_benchmark_v2.py --registry-dir <dir> --strict   # report stem gets _strict
```

Tests: `apps/api/tests/test_compare_assay_benchmark_v2.py`, section "strict mode".
