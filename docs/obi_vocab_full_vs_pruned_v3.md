# Full (1794), noncompositional (1249) and pruned (701) OBI vocabularies as the mapper's candidate pool

*Run 2026-10-27 on `data/31paper_assays/assay_result_v3/` (31 papers, 177 entries) against
`data/benchmark_assay/benchmark_assay_v5/`. All arms ran fresh, same day, same code, round 4
pick only; the only difference is the candidate pool. Driver, per-arm registries and scorer
reports: `experiment/obi_vocab_v3/`. Nothing under `data/` was written; the mapper's default
is unchanged.*

## Result: the pruned 701-term vocabulary wins

| metric | `pruned` (701) | `noncompositional` (1249) | `full` (1794) | stored v3 run (701, reference) |
|---|---|---|---|---|
| matched | 156 | 156 | 156 | 156 |
| exact (same OBI term as the curator) | **141** | 140 | 130 | 140 |
| OBI recall (same term or parent/child) | **92.4%** | 91.7% | 88.5% | 92.4% |
| MATCH_OBI_CONFLICT / MATCH_GRANULARITY | 5 / 4 | 6 / 4 | 10 / 9 | 5 / 5 |
| picker answered `none` | 2 | 2 | 3 | 2 |
| calls spent | 495 | 495 | 510 | 338 |

The three vocabularies nest (1794 ⊃ 1249 ⊃ 701): `noncompositional` is the assay branch with
only the compositional labels removed, every domain still in.

Recall is identical: the vocabulary decides which term an entry gets, not whether it is
found. The full vocabulary agrees with the curator on 11 fewer entries than the pruned one;
the noncompositional vocabulary on 1 fewer. The run-to-run variance of the picker is 1 (fresh
`pruned` vs the stored v3 run: 2 entries, 1 exact), so the 11 is real and the 1 is at the
noise floor.

**Attribution.** Removing the compositional labels (1794 → 1249) recovers 10 of the 11 exact;
removing the out-of-scope domains (1249 → 701) recovers the last 1. `noncompositional` and
`pruned` chose different terms on exactly one entry, SDY1293 below.

15 entries chose different terms: 12 the pruned arm's way, 1 the full arm's way, 1 wrong under
both, 1 without a curated row. The same A/B on 2026-10-21 (older corpus, benchmark v4) gave
132 vs 126 exact with 8 changed entries, 6 of them the pruned arm's way and none the full
arm's. Same direction, wider gap.

## Why the pruned vocabulary does better

Across the corpus, 37.8% of the full arm's candidates were compositional labels
(*"… assay measuring epitope specific X production by Y cells"*); in the pruned arm 0.4%.
That one number drives both failure modes below. The clinical-band share barely moved
(6.7% vs 7.8%), so the compositional prune does most of the work here.

**1. A compositional child outranks the family term (7 of the 15).** The family term is on
the list, but the picker takes the construct that names the paper's cytokine or analyte.

- SDY1364, "IFN-γ ELISpot": pruned list had `OBI:0600031 enzyme-linked immunospot assay` at #1
  and nothing else ELISPOT-shaped; the full list put `OBI:1110059 ELISPOT assay measuring
  epitope specific interferon-gamma production by T cells` beside it, with 18 of 20 candidates
  compositional. The picker chose the IFN-γ construct; the curator's term is `OBI:0600031`.
- SDY2189, "Anti-spike binding ELISA": `OBI:0000661 enzyme-linked immunosorbent assay` stayed
  at #1 in both arms, but with 13 compositional ELISAs below it the full arm went to #5,
  `ELISA measuring binding of a B cell epitope:antibody complex`.

**2. The curator's term is crowded out of the top 20 (6 of the 15).** Retrieval is 20 slots
with no threshold. The right term was reachable in the pruned list and absent from the full
one, so the picker settled for a parent or a sibling.

- SDY1669, "TLR4-based reporter assay": `OBI:0003793 bacterial lipopolysaccharide detection in
  plasma assay` was #18 in the pruned list and was picked; in the full list 12 compositional
  reporter constructs pushed it off, and the picker took `reporter cell line analyte
  detection bioassay` (BROAD).
- SDY1289 and SDY1640, cytokine bead arrays: the curator's `OBI:0003799 analyte detection by
  flow based bead assay` was #4 in the pruned list; in the full list 17 of 20 candidates were
  *"cytometric bead array assay measuring epitope specific …"*, it fell off, and the picker took
  the plain `OBI:0000920 cytometric bead array assay` at #3.

**3. Unneeded picks.** A term that is a leaf in the pruned index has children in the full one,
so an exact name hit is pinned into a pick instead of answered outright (ELISA has 53
descendants in OBI). Exact hits answered without a pick: 7 in the pruned arm, 2 in the full
arm. That is the 15 extra calls.

## Stage 1 alone: 1249 vs 701

One entry differs, and it is the domain prune's one visible case in this corpus.

- SDY1293, "malaria thick blood smears": in the pruned list `OBI:0002119 microscopy assay` was
  #8 and was picked (BROAD). In the noncompositional list eight `OBI:21xxxxx` clinical-band
  terms took slots (`manual differential bodily fluid macrophage count assay` at #1, `CBC with
  manual differential venous blood …` at #12, #14, #20), `microscopy assay` was not shown, and
  the picker took `blood microbiology assay`. The pruned index drops those panel terms (tier A)
  and keeps their plain siblings; the pruned list still held two `OBI:21` terms, at #17 and #18.

Everything else the two arms agree on: 176 of 177 entries, the same two abstentions, the same
call count. The domain prune is cheap insurance rather than a large effect here; the
compositional prune is where the score comes from.

## The one entry the full vocabulary got right

SDY1630, "cytokine stimulation and functional assays of NK cells": the curator chose
`OBI:1110207 assay detecting IFN-gamma production`, a compositional label the pruned index
does not hold, so the pruned arm could only answer `flow cytometry assay` (BROAD). This is the
known ceiling of the prune: a benchmark row curated to a pruned term is unmatchable. It is one
row, and the same construct cost the full arm SDY1991 ("IFN-γ Capture Assay", curated to
`flow cytometry assay`) under reason 1.

One further changed entry (SDY1669 16S PCR) is picker variance, not vocabulary: both arms saw
the same top five and the stored v3 run agrees with the full arm.

## Recommendation

Keep `obi_assay_pruned_index.json` as the candidate pool, and keep both prunes: the
compositional one carries the score, the domain one costs nothing and fixes the one case the
clinical band can reach. Do not add a similarity threshold: the full arm's wrong picks scored
as high as its right ones.
