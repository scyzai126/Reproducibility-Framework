# Pruned (701) vs full (1794) OBI vocabulary as the mapper's candidate pool: 31 papers

*Experiment folder. The production mapper, the live vocabulary and everything under `data/` are
unchanged; the only thing that differs between the two arms is which vocabulary file the
unchanged round-4 workflow searches.*

## Question

Round 4 maps each extracted assay to an OBI term by exact match on the paper's own name, else
embedding retrieval (top-20 plus OBI neighbours) and an LLM pick. The pipeline searches a
pruned vocabulary of 701 terms (`data/OBI/obi_assay_pruned_*.json`): the 1794-term `assay`
branch of OBI minus 545 IEDB-style compositional labels ("ELISPOT assay measuring epitope
specific IFN-gamma production by T cells") and 548 out-of-scope domain terms. Does the pruning
help or hurt agreement with the curators? Both vocabularies were run through the same workflow
over the same 157 entries (31 papers, the canonicalized `assays.json` of
`data/31paper_assays/stability/`), and scored against benchmark v4 with the pipeline's own
comparator (`scripts/compare_assay_benchmark_v2.py`, imported, not copied).

| arm | vocabulary | calls spent |
|---|---|---|
| **pruned** | 701 terms, `obi_assay_pruned_{index,embeddings}.json` | 434 |
| **full** | 1794 terms, `obi_assay_full_{index,embeddings}.json` | 449 |
| stability_reference | the pruned vocabulary, as run on 2026-10-19 and stored in `data/31paper_assays/stability/` | 0 (already on disk) |

The third column is the same vocabulary on another day. The gap between it and the fresh
pruned arm is the mapper's own run-to-run variance, which any arm-to-arm difference has to clear.

## Layout

```
run_vocab_comparison.py        map | score | report  (see its docstring)
tests/                         4 tests: ./.venv/bin/pytest experiment/obi_vocab_31papers/tests
runs/pruned/<registry>/        assays.json + assays_benchmark.json (copied in), assays_OBI.json, raw.json
runs/full/<registry>/          the same for the full vocabulary
comparison/pruned.{json,html}  v2 comparator output per arm (+ full, + stability_reference)
comparison/diff.json           per-entry differences between arms, with the curator's term
comparison/summary.md          the tables below, generated
map_log.txt                    the map run's console output
```

`raw.json` keeps, per entry, the numbered candidate list the picker saw and its reply, so every
changed term below can be read back to its cause.

## Result

| metric | pruned (701) | full (1794) | stability_reference (701, 2026-10-19) |
|---|---|---|---|
| curated rows / agent entries | 161 / 157 | 161 / 157 | 161 / 157 |
| matched (paired with a curated row) | 150 | 150 | 150 |
| **exact: same OBI term as the curator** | **132** | **126** | 131 |
| obi_exact_rate (exact / matched) | **88.0%** | 84.0% | 87.3% |
| obi_recall (exact / curated rows) | **82.0%** | 78.3% | 81.4% |
| MATCH_GRANULARITY (parent/child of the curator's term) | 5 | 7 | 5 |
| MATCH_OBI_CONFLICT (unrelated term) | 7 | 9 | 7 |
| MATCH_OBI_UNMAPPED (one side has no term) | 6 | 8 | 7 |
| unresolved (picker answered "none") | 2 | 4 | 4 |
| MISSED / EXTRA (extraction, same for all arms) | 11 / 2 | 11 / 2 | 11 / 3 |

**The pruned vocabulary agrees with the curators on 6 more entries than the full one** (132 vs
126 of 150 matched), a 4-point drop in exact rate for the full arm. The run-to-run variance of
the pruned vocabulary is 1 entry (132 fresh vs 131 stored), so the 6-entry gap is well outside
noise. The full arm also doubled the abstentions (4 vs 2).

### The 8 entries where the two arms chose different terms

Six go to the pruned arm, two to neither; none to the full arm.

| paper | entry | pruned (701) | full (1794) | curator | cause, from `raw.json` |
|---|---|---|---|---|---|
| SDY1364 (23266342) | ELISPOT | `OBI:0600031` ELISPOT | **`OBI:1110059` ELISPOT measuring epitope specific IFN-γ production by T cells** | ELISPOT | 20 of 24 candidates compositional; the family term was rank 2 and the picker took the IFN-γ child (reply `1 exact`). |
| SDY1364 (23844129) | ELISPOT | `OBI:0600031` ELISPOT | **`OBI:1110059`** same child | ELISPOT | 20 of 24 compositional; family at rank 1, picker answered `2 exact`. |
| SDY1364 (23266342) | flow cytometry (surface + intracellular cytokine staining) | `OBI:0000916` flow cytometry | **`OBI:1110172` ICS measuring epitope specific IFN-γ production by T cells** | flow cytometry | 17 of 22 compositional; family at rank 1, picker went to rank 15. |
| SDY1991 | flow cytometry | `OBI:0000916` flow cytometry | **`OBI:1110207` assay detecting IFN-gamma production** | flow cytometry | 15 of 21 compositional; family at rank 1, picker answered `2 exact`. This is the exact term whose four wrong picks on the 30-paper run added `detecting` to the prune regex. |
| SDY1655 | antigen detection by CBA (71-plex Luminex) | `OBI:0003115` antigen detection by CBA | **none** | `OBI:0000920` CBA | 14 of 22 compositional ("CBA measuring epitope specific X release by T cells"); the pruned arm's term was not retrieved at all and the picker abstained. |
| SDY1669 | bacterial LPS detection in plasma | `OBI:0003793` (= curator) | `OBI:0000904` reporter cell line analyte detection bioassay (BROAD) | `OBI:0003793` | 13 of 21 compositional; the correct term, rank 18 on the pruned list, did not make the full list. |
| SDY1293 | microscopy assay | `OBI:0002119` microscopy assay (= curator) | `OBI:0002649` blood microbiology assay | `OBI:0002119` | the correct term, rank 9 on the pruned list, did not make the full list; a domain term the prune removes took the slot. |
| SDY1328 | complete blood count | `OBI:0003040` blood assay | none | `OBI:0000630` hematology assay | wrong on both arms (the curator's term sat at rank 16 / 21 and neither picker took it); the full arm abstained. |

Two failure modes, both the ones the prune was introduced for, and both still live when the
compositional terms are back in the pool:

1. **A compositional child outranks or seduces the family term (4 entries).** Three of the four
   picks are IFN-γ-specific terms for assays the paper runs for several cytokines or for cell
   phenotypes; the picker, shown a list that is 70 to 85% analyte-specific constructs, picks one
   that matches a word in the record. The curator's term is the family term every time.
2. **The decoys crowd the right term out of the top 20 (3 entries).** With up to 20 of 24 slots
   taken by compositional or domain terms, a correct term that ranked 9th or 18th on the
   pruned list falls off the full list, and the picker either abstains or settles for a broad
   relative.

The full arm gained nothing in return: no entry moved *toward* the curator, and no curated term
that the pruned vocabulary lacks was reached. (One curated term, `OBI:1110207` for an ICS entry
in SDY1630, is outside the 701; the full arm did not land on it there, and chose it wrongly
in SDY1991 instead.)

### Variance baseline: pruned fresh vs stored stability run

Eight entries differ, one net in favour of the fresh run (2 toward the curator, 1 away, 2 wrong
on both, 3 without a curated term). The flips are between adjacent siblings (real-time RT-PCR vs
RT-PCR; immunocytochemistry vs fluorescence microscopy; CBA vs its antibody-detection child) and
are the known seeded-but-not-deterministic behaviour of the pick call. They are the yardstick:
a 1-entry net change is noise, the 6-entry gap between vocabularies is not.

## Conclusion

Keep the pruned 701-term vocabulary as the candidate pool. On 31 papers and 150 matched entries
the full vocabulary agreed with the curators on 6 fewer entries, abstained twice as often, cost
15 more calls, and reproduced exactly the two failure modes the prune was designed against: an
analyte-specific child chosen over the family term (4 entries, 3 of them IFN-γ constructs) and
the correct term pushed off the candidate list by decoys (3 entries). It recovered no term in
return.

## Reproduce

```bash
./.venv/bin/python experiment/obi_vocab_31papers/run_vocab_comparison.py map --arm both --dry-run   # counts, free
./.venv/bin/python experiment/obi_vocab_31papers/run_vocab_comparison.py map --arm both             # ~880 calls
./.venv/bin/python experiment/obi_vocab_31papers/run_vocab_comparison.py score                      # free
./.venv/bin/python experiment/obi_vocab_31papers/run_vocab_comparison.py report                     # free
```
