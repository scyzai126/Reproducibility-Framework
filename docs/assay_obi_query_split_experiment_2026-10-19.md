# Step-3 query experiments: alias split, and where the unrecovered misses rank (2026-10-19)

*Embedding calls only (221 `text-embedding-3-small` calls, no chat calls); no result file in the
repo changed. Follows `docs/assay_obi_retrieval_expansion_2026-10-19.md`. Script and cached
query vectors live in the session scratchpad; the method is reproducible from this note.*

## Questions

1. Does embedding the paper name and each alias as **separate queries** rank the curator's term
   better than today's single concatenated string `name | alias1 | alias2 …`?
2. For the three curated terms that are on no candidate list and not reachable by neighbour
   expansion, **how far down** do they rank — just below 20, or far below?

## Setup

Papers: the 13 of 31 with at least one row disagreeing with the curators (MATCH_GRANULARITY,
MATCH_OBI_CONFLICT, MATCH_OBI_UNMAPPED in `benchmark_vs_stability.json`). All 69 of their entries
were run so a change that helps one row and hurts others is visible. Each entry's name, aliases
and technique come from its `assays_corrected.json`; the curated term from the comparison via the
`key_map`. Rankings are over the 701 index terms with the mapper's own merge
(`_merge_candidates`, 14 slots reserved for the primary pool, K = 20).

| variant | primary pool | other pools |
|---|---|---|
| **L0 current** | top-20 of `name \| aliases` (one vector) | top-20 of technique |
| **S1** | top-20 of name alone | top-20 of each alias, then technique |
| **S2** | union of the name pool and each alias pool, best score per term, cut to 20 | top-20 of technique |

## Experiment 1 — alias split

| rows | n | L0 on list | S1 on list | S2 on list | L0 at #1 | S1 at #1 | S2 at #1 |
|---|---|---|---|---|---|---|---|
| disagreeing with curators | 14 | 10 | 8 | **11** | 5 | 2 | 4 |
| agreeing, same papers | 55 | 55 | 51 | **55** | 45 | 43 | **46** |

Rows whose list membership changed:

| paper | entry | curated term | L0 | S1 | S2 | why |
|---|---|---|---|---|---|---|
| SDY1260 | anti-Diphtheria IgG by Luminex | antibody detection by cytometric bead array assay | absent (rank 18 in A, pushed out by the merge) | #15 | **#15** | the alias "anti-DT IgG capture microsphere assay" alone ranks it 6th; concatenated it sinks to 18 |
| SDY1289 | BD Th1/Th2 CBA array | cytometric bead array assay | #3 | absent | #3 | S1 fills the reserved slots from the name pool (rank 21 there) and crowds out the alias and technique hits |
| SDY1294 | NK-mediated ADCC assay | flow cytometry assay | #1 | absent | #1 | reached only by the technique query (rank 284 in A); S1 crowds it out |
| SDY984 | Plasma Metabolomics analysis | liquid chromatography mass spectrometry assay | #1 | absent | #1 | same: technique-only (rank 106 in A) |
| SDY1264 | Multiplex analysis | cytometric bead array assay | #4 | absent | **#1** | best alias ranks it 1st; S2 promotes it |
| SDY1293 | GeneChip analysis | transcription profiling by array assay | #1 | absent | #1 | technique-only (rank 23 in A) |
| SDY1596 | Bacterial viability stain | flow cytometry assay | #1 | absent | #1 | technique-only (rank 408 in A) |
| SDY1640 | Intracellular cytokine staining assay | flow cytometry assay | #1 | absent | #1 | technique-only (rank 156 in A) |

Reading:

- **S1 is harmful.** Giving the name pool the 14 reserved slots starves the technique pool, and
  the technique is what reaches the term for section-heading names. It loses 2 disagreeing rows
  and 4 agreeing ones.
- **S2 is a strict improvement on this sample**, small: +1 disagreeing row on the list (SDY1260),
  no row lost, one more term at position 1 (SDY1264), one position worse elsewhere. The one row
  it gains is the same row the neighbour expansion already recovers, so on this benchmark its
  net effect over the current code is zero rows; its merit is putting that term on the list by
  retrieval (position 15) rather than as an appended neighbour.
- Cost of S2: one embedding call per alias, about two more per entry on average; embedding calls
  are the cheap kind.

## Experiment 2 — the three unrecovered misses

| paper | entry | curated term | rank in A (name \| aliases) | rank in B (technique) | in merged K=40? |
|---|---|---|---|---|---|
| SDY1328 | multiplex ELISA protocol Human Inflammation multi-analyte… | cytometric bead array assay | 88 | 31 (technique "enzyme-linked immunosorbent assay") | no |
| SDY1328 | complete blood count | hematology assay | 33 | no technique | yes, #33 |
| SDY1655 | Human Cytokine Array/Chemokine Array 71–403 Plex | cytometric bead array assay | 21 | 27 (technique "multiplex immunoassay") | yes, #17 |

Reading:

- None of the three is at rank 21–40 **in both** queries; two are reachable at K=40 through
  one of them. The SDY1328 multiplex ELISA row is far down in both: query A ranks the imaging and
  state-immunoassay multiplex terms above CBA, and query B (literally "ELISA") ranks ELISA
  itself. That is an extraction-side technique judgement ("multiplex ELISA" written as ELISA);
  no query change reaches CBA from those strings.
- Raising K to 40 would add two of the three terms to the list at the price of a 40-line prompt
  for every entry, and a longer list is what the pin-children cap exists to avoid. The picker
  then still has to prefer CBA at #17 over the state-immunoassay term at #1, which for SDY1655 it
  did not do when both were present in the current list (it chose `multiplex bead-based protein
  state immunoassay`); that is rule 10's job, not retrieval's.
- "complete blood count" → `hematology assay` is a granularity call (CBC is several count assays
  under one parent); our pipeline left it unmapped rather than wrong.

## Recommendation

- **Do not adopt S1.**
- **S2 is safe but optional.** On this benchmark it adds no row beyond what neighbour expansion
  already recovers. Adopt it only if a larger benchmark shows alias-driven misses; the structure
  (union the alias pools, keep the 14/6 reservation) is the version to use.
- **Keep K = 20.** Two misses are reachable at 40 but one of them was then not picked anyway, and
  the third is unreachable; the cost lands on every entry.
- The remaining retrieval misses trace back to the extractor's `standard_technique_name` on
  multiplex panels ("enzyme-linked immunosorbent assay" for a Luminex kit) and to the picker's
  rule 10, not to how the queries are formed. Step 3 as it stands is good enough.

## Cost

221 embedding calls, 0 chat calls. The query vectors are cached in the scratchpad; a re-run of
the analysis is free.
