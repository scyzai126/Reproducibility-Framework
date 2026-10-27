# OBI vocabulary size and mapping accuracy: 1794 vs 1249 vs 701

*2026-10-27. 31 papers, 177 assay entries (`data/31paper_assays/assay_result_v3/`), scored
against benchmark v5. Each arm re-ran round 4 (embedding top-20 + one LLM pick) with a
different candidate pool and nothing else changed. Data: `experiment/obi_vocab_v3/`.*

The three vocabularies nest. `full` is the whole OBI assay branch. `noncompositional` removes
the 545 IEDB-style labels (*"ELISPOT assay measuring epitope specific IFN-γ production by T
cells"*). `pruned`, the live pool, also removes 548 out-of-scope domain terms (hospital
analyzer panels, entomology, electrophysiology, metrology, …).

## Results

| | `pruned` (701) | `noncompositional` (1249) | `full` (1794) |
|---|---|---|---|
| entries matched to a curated row | 156 | 156 | 156 |
| exact: same OBI term as the curator | **141** | 140 | 130 |
| OBI recall: same term or parent/child | **92.4%** | 91.7% | 88.5% |
| wrong term (CONFLICT) | 5 | 6 | 10 |
| picker answered `none` | 2 | 2 | 3 |
| LLM calls | 495 | 495 | 510 |

Run-to-run noise is 1 exact (a second 701 run differs on 2 of 177 entries).

- **1794 vs 701:** the full vocabulary gets 11 fewer entries exactly right. 15 entries chose a
  different term; 12 went the pruned arm's way, 1 the full arm's.
- **1249 vs 701:** 1 fewer exact. Only 1 entry differs.
- **So:** removing the compositional labels accounts for 10 of the 11; removing the domain
  terms for the last 1.

## Why 701 beats 1794

In the full arm, 38% of all candidates shown to the picker were compositional labels; in the
pruned arm 0.4%. That causes two failures.

**1. A compositional child outranks the family term (7 entries).** The right term is on the
list, but the picker takes the construct that names the paper's cytokine or analyte.

- SDY1364, "IFN-γ ELISpot": pruned picked `OBI:0600031 enzyme-linked immunospot assay` (#1).
  The full list had 18 compositional ELISPOTs; the picker took `OBI:1110059 ELISPOT assay
  measuring epitope specific interferon-gamma production by T cells`. Curator: `OBI:0600031`.
- SDY2189, "Anti-spike binding ELISA": `OBI:0000661 ELISA` was #1 in both arms; with 13
  compositional ELISAs below it, the full arm chose #5, `ELISA measuring binding of a B cell
  epitope:antibody complex`.

**2. The right term is pushed off the top 20 (6 entries).** Retrieval is 20 slots with no
threshold. The curator's term was reachable in the pruned list and absent from the full one.

- SDY1669, "TLR4-based reporter assay": `OBI:0003793 bacterial lipopolysaccharide detection in
  plasma assay` was #18 in the pruned list and was picked. In the full list 12 compositional
  reporter constructs displaced it; the picker settled for `reporter cell line analyte
  detection bioassay`.
- SDY1289 and SDY1640, cytokine bead arrays: `OBI:0003799 analyte detection by flow based bead
  assay` was #4 in the pruned list. In the full list 17 of 20 candidates were *"cytometric bead
  array assay measuring epitope specific …"*; it fell off, and the picker took the plain
  `OBI:0000920 cytometric bead array assay`.

**The one entry the full arm got right** is the same mechanism in reverse: SDY1630's NK
IFN-γ assay is curated to the compositional `OBI:1110207 assay detecting IFN-gamma
production`, which the pruned pool does not contain, so pruned could only answer
`flow cytometry assay`. One row; the same construct cost the full arm SDY1991.

The full arm also spends 15 more calls: a term that is a leaf in the pruned index has children
in the full one (ELISA has 53), so an exact name hit is sent to the picker instead of answered.

## Why 701 beats 1249

One entry, SDY1293, "malaria thick blood smears". In the pruned list `OBI:0002119 microscopy
assay` was #8 and was picked. In the 1249 list eight `OBI:21xxxxx` clinical-panel terms took
slots (`manual differential bodily fluid macrophage count assay` at #1, three `CBC with manual
differential venous blood …` terms further down); `microscopy assay` was not shown and the
picker took `blood microbiology assay`. The domain prune removes exactly those panel terms.

## Recommendation

Keep the 701-term `obi_assay_pruned_index.json` and keep both prunes. The compositional prune
carries the score; the domain prune is cheap and fixes the one case the clinical band can
reach. A similarity threshold would not help: the full arm's wrong picks scored as high as its
right ones.
