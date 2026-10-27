# Full (1794) vs pruned (701) OBI vocabulary as the mapper's candidate pool, on assay_result_v3

*Run 2026-10-27 against `data/31paper_assays/assay_result_v3/` (31 papers, 177 entries) and
`data/benchmark_assay/benchmark_assay_v5/`, scored by `scripts/compare_assay_benchmark_v2.py`.
Driver, per-arm registries and the scorer's reports are under `experiment/obi_vocab_v3/`
(`runs/<arm>/<paper>/{assays_OBI.json, raw.json}`, `comparison/`). Nothing under `data/` was
written and the mapper's default vocabulary is unchanged.*

## Question

Round 4 maps each extracted assay to an OBI term: an exact match on the paper's own wording,
else embedding retrieval of the top 20 candidates and one LLM pick. The pool it retrieves from
is `obi_assay_pruned_index.json`: the 1794-term assay branch of OBI minus 545 IEDB-style
compositional labels (*"ELISPOT assay measuring epitope specific interferon-gamma production by
T cells"*) and minus 548 terms in nine out-of-scope domains (hospital analyzer panels,
entomology, electrophysiology, metrology, …). The two prunes exist on the argument that these
terms are semantic near-neighbours of the ones we want and the mapper has no similarity
threshold to keep them out of the top 20.

Does the prune earn its keep on the current corpus, benchmark and scorer? Two arms, both run
fresh on the same day with the same code, differing only in the pool:

| arm | index | terms |
|---|---|---|
| `pruned` | `data/OBI/obi_assay_pruned_index.json` + its vectors | 701 |
| `full` | `data/OBI/obi_assay_full_index.json` + its vectors | 1794 |

Both map the canonical `assays.json` of every v3 registry, so keys stay those of
`assays_benchmark.json`. Round 4's pick only: no BROAD re-pick and no round-5 fold, so a
difference between arms is the candidate pool and nothing else. The stored v3 mapping (the
pruned vocabulary, run before this experiment) is scored as a third, free column: the gap between it and
the fresh `pruned` arm is the picker's own run-to-run variance.

The same A/B ran once before, on 2026-10-21 (branch `feature/immport-llm-fallback`, the
stability corpus, benchmark v4): pruned 132 exact vs full 126, 8 entries changed, 6 of them the
pruned arm's way and none the full arm's. This run asks whether v3 confirms it.

## Result: the prune wins again, by more

| metric | `pruned` (fresh) | `full` (fresh) | v3 stored (reference) |
|---|---|---|---|
| curated rows | 157 | 157 | 157 |
| agent entries | 177 | 177 | 177 |
| matched | 156 | 156 | 156 |
| exact (same OBI term as the curator) | **141** | 130 | 140 |
| OBI ok (same term, or parent/child) | **145** | 139 | 145 |
| obi_exact_rate | **90.4%** | 83.3% | 89.7% |
| obi_recall | **92.4%** | 88.5% | 92.4% |
| MATCH_GRANULARITY | 4 | 9 | 5 |
| MATCH_OBI_CONFLICT | 5 | 10 | 5 |
| MATCH_OBI_UNMAPPED | 6 | 7 | 6 |
| MISSED / EXTRA | 1 / 5 | 1 / 4 | 1 / 4 |
| unresolved (picker said `none`) | 2 | 3 | 2 |
| exact hits answered without a pick | 7 | 2 | 8 |
| calls spent (picks + query embeddings) | 495 | 510 | 338 |

Recall is identical: the vocabulary decides which term an entry gets, not whether an entry is
found. What moves is the term. The full arm agrees with the curator on 11 fewer entries, loses
6 on OBI recall, abstains once more, and spends 15 more calls, 5 of them because an exact hit
that is a leaf in the pruned index (ELISA, 53 descendants in OBI) has children in the full one
and is pinned into a pick it did not need.

The variance yardstick is 1: `pruned` and the stored v3 run differ on 2 entries and 1 exact.
The arm-to-arm gap of 11 is not noise.

### Entries that chose different terms

15 of 177. The pruned arm's term agrees with the curator on 12, the full arm's on 1, neither on
1, and 1 has no curated row. Flags: *(compositional)* marks a label the stage-1 prune removes;
*(outside 701)* a term the pruned index does not hold at all; the two sets coincide here.

| paper | entry (paper wording) | `pruned` | `full` | curator | agrees |
|---|---|---|---|---|---|
| SDY1364 (23266342) | ex vivo IFNγ ELISpot assay | **OBI:0600031 enzyme-linked immunospot assay** | OBI:1110059 ELISPOT assay measuring epitope specific interferon-gamma production by T cells *(compositional)* | OBI:0600031 | pruned |
| SDY1364 (23844129) | IFN-γ ELISpot | **OBI:0600031 enzyme-linked immunospot assay** | OBI:1110059 *(compositional)* | OBI:0600031 | pruned |
| SDY2189 | Anti-spike binding ELISA | **OBI:0000661 enzyme-linked immunosorbent assay** | OBI:0001657 ELISA measuring binding of a B cell epitope:antibody complex *(compositional)* | OBI:0000661 | pruned |
| SDY1289 | CFSE labeling | **OBI:0003582 cell proliferation assay using CFSE staining** | OBI:0002096 CFSE staining assay measuring epitope specific proliferation of T cells *(compositional)* | OBI:0003582 | pruned |
| SDY1294 | NK-mediated ADCC assay | **OBI:0000882 cell-cell killing assay** | OBI:0001642 assay measuring epitope specific antibody-dependent cellular cytotoxicity *(compositional)* | OBI:0000882 | pruned |
| SDY1991 | IFN-γ Capture Assay | **OBI:0000916 flow cytometry assay** | OBI:1110207 assay detecting IFN-gamma production *(compositional)* | OBI:0000916 | pruned |
| SDY1630 | In vitro cytokine stimulation and functional assays of NK cells | OBI:0000916 flow cytometry assay | **OBI:1110207 assay detecting IFN-gamma production** *(compositional)* | OBI:1110207 | full |
| SDY1289 | BD Th1/Th2 CBA array | **OBI:0003799 analyte detection by flow based bead assay** | OBI:0000920 cytometric bead array assay | OBI:0003799 | pruned |
| SDY1640 | Cytokine bead assays | **OBI:0003799 analyte detection by flow based bead assay** | OBI:0000920 cytometric bead array assay | OBI:0003799 | pruned |
| SDY984 | Cytokine Bead Array (CBA), 2nd entry | OBI:0003799 analyte detection by flow based bead assay | OBI:0000920 cytometric bead array assay | — | no curated term |
| SDY1293 | malaria thick blood smears | **OBI:0002119 microscopy assay** | OBI:0002649 blood microbiology assay | OBI:0002119 | pruned |
| SDY1294 | Immunofluorescence assay to detect anti-JEV / anti-WNV antibodies | **OBI:0001632 immuno staining assay** | OBI:0001501 fluorescence detection assay | OBI:0001632 | pruned |
| SDY1669 | TLR4-based reporter assay | **OBI:0003793 bacterial lipopolysaccharide detection in plasma assay** | OBI:0000904 reporter cell line analyte detection bioassay | OBI:0003793 | pruned |
| SDY1655 | Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71) | OBI:0000920 cytometric bead array assay | `none` | OBI:0003115 antigen detection by cytometric bead array assay | neither |
| SDY1669 | PCR quantitation of bacterial 16S rRNA gene product | **OBI:0000893 real time polymerase chain reaction assay** | OBI:0002692 polymerase chain reaction assay | OBI:0000893 | pruned |

### Why each went the way it did

Read from the candidate lines in `runs/<arm>/<paper>/raw.json`. Across the whole corpus the
full arm's candidate lists were 37.8% compositional labels (pruned: 0.4%, the one pinned
tetramer term); the share of `OBI:21xxxxx` clinical-band terms barely moved (6.7% vs 7.8%), so
the domain prune mattered less here than the compositional one.

**Seven entries: a compositional child beat the family term.** In six the family term was on
the list, usually at #1 or #2, and the picker still took the analyte-specific construct. Both
SDY1364 ELISpots: the pruned list had `OBI:0600031` at #1 and nothing else ELISPOT-shaped; the
full list put `OBI:1110059` (IFN-γ) at #1 or #2 beside it, with 18 of 20 candidates
compositional, and the picker chose the construct that names the cytokine the paper names.
SDY2189's anti-spike ELISA: `OBI:0000661` stayed at #1 in both arms, but with 13 compositional
ELISAs below it the picker went to #5, *"ELISA measuring binding of a B cell epitope:antibody
complex"*. SDY1289's CFSE labelling and SDY1294's ADCC: the curator's term sat at #14 / #9 in the
pruned list and was picked; in the full list a compositional sibling outranked it by one place
and was picked instead. SDY1991's IFN-γ capture assay: flow cytometry at #1 in both arms, the
full arm took `OBI:1110207` at #2. These are the exact failure the stage-1 prune was written
against, and they reproduce the 2026-10-21 pattern (three IFN-γ constructs then, six analyte
constructs now).

**The one full-arm win is the same construct, because the curator used it.** SDY1630's NK
IFN-γ functional assay is curated to `OBI:1110207 assay detecting IFN-gamma production`, a
compositional label the pruned index does not hold, so the pruned arm can only answer
`flow cytometry assay` (BROAD). The full arm found it at #10 and took it. This is the known
ceiling of the prune (noted in `data/OBI/README.md`): a benchmark row curated to a pruned term
is unmatchable. It is one row, and the same construct cost the full arm SDY1991 one line above.

**Four entries: the curator's term was crowded out of the top 20.** Here the family term was
not on the full arm's list at all. SDY1293's thick blood smears: `microscopy assay` was #8 of
the pruned list (picked, BROAD); in the full list two `manual differential bodily fluid … count`
terms from the clinical band and the microbiology family filled the slots, the curator's term
was not shown, and the picker took `blood microbiology assay`. SDY1294's immunofluorescence:
`immuno staining assay` at #10 in the pruned list, absent from the full one (8 compositional
entries), replaced by its parent `fluorescence detection assay`. SDY1669's TLR4 reporter assay:
`bacterial lipopolysaccharide detection in plasma assay` was #18 in the pruned list, the last
slot a 20-wide retrieval could still reach; in the full list 12 compositional reporter
constructs pushed it out and the picker settled for `reporter cell line analyte detection
bioassay` (BROAD). The three CBA entries (SDY1289, SDY1640, SDY984) are one case: the curator's
`analyte detection by flow based bead assay` was #4 in the pruned list; in the full list 17 of
the 20 candidates were *"cytometric bead array assay measuring epitope specific X"*
constructs, `OBI:0003799` fell off the list, and the picker took the plain
`cytometric bead array assay` at #3. Both terms are in the 701, so this is displacement, not a
pruned term being chosen.

**One abstention.** SDY1655's HD71 71-plex panel: the pruned arm picked
`cytometric bead array assay` (#6), the full arm answered `none` from a list that was 15/20
compositional. The curator's `antigen detection by cytometric bead array assay` was #20 in the
pruned list and absent from the full one; neither arm had it within reach, so this row is wrong
either way and the full arm is merely wrong by abstaining.

**One entry is picker variance, not vocabulary.** SDY1669's 16S PCR: both arms retrieved the
same top five in the same order (`polymerase chain reaction assay` #1, `real time polymerase
chain reaction assay` #2). The pruned arm answered "2 exact", the full arm "1 broad". The stored
v3 run also chose #1, so this is one of the two entries where `pruned` and the reference differ.
Subtracting it, the vocabulary accounts for 11 of the 12 pruned-arm wins.

### Variance: fresh `pruned` vs stored v3

Two entries differ, both inside the 701: SDY1669's PCR above, and SDY984's second CBA entry
(`analyte detection by flow based bead assay` vs `cytometric bead array assay`, no curated row).
Exact 141 vs 140. The picker runs at `temperature=0` without a seed, and this is what that
buys on 177 entries: about one term in a hundred moves between runs.

## Against the 2026-10-21 run

Same direction, wider gap:

| | 2026-10-21 (stability, benchmark v4) | 2026-10-27 (v3, benchmark v5) |
|---|---|---|
| exact, pruned vs full | 132 vs 126 (−6) | 141 vs 130 (−11) |
| obi_recall | 82.0% vs 78.3% | 92.4% vs 88.5% |
| entries that changed | 8 | 15 |
| of which the pruned term is the curator's | 6 | 12 |
| of which the full term is the curator's | 0 | 1 (SDY1630, a curated compositional term) |
| mechanism: compositional child picked | 4 | 7 |
| mechanism: curator's term crowded off the list | 3 | 6 (incl. 3 CBA) |
| extra calls in the full arm | +15 | +15 |

The earlier run's full arm reused the 701 vectors through a patched filter; this one has its
own 1794-term embeddings file, so retrieval over the full branch is now measured as it would
really run. It is worse than the earlier estimate, not better.

## Recommendation

Keep `obi_assay_pruned_index.json` as the candidate pool. The full vocabulary agreed with the
curators on 11 fewer entries, lost 6 on OBI recall, abstained once more, cost 15 more calls, and
recovered one row that only a curated compositional term could ever have matched. The stage-1
(compositional) prune does nearly all of the work in this corpus; the domain prune's effect is
visible only on SDY1293, where clinical-band count terms displaced `microscopy assay`.

Two follow-ups this run does not settle:

- The 1249-term `noncompositional` vocabulary (stage 1 only) is built, vectorised and defined
  as an arm in the driver; running it would attribute the 11-entry gap between the two prunes
  directly instead of by reading candidate lists (`map --arm noncompositional`, about 175 picks).
- The three CBA entries and SDY1655 show the picker choosing between `OBI:0000920 cytometric
  bead array assay`, `OBI:0003799 analyte detection by flow based bead assay` and
  `OBI:0003115 antigen detection by cytometric bead array assay` on wording alone; the curators
  are not consistent among these three either (SDY1655 vs SDY1289/SDY1640). That is a
  granularity policy question for the benchmark, not a vocabulary one.
