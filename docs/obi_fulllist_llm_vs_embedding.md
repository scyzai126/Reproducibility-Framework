# Map to OBI: full 701-term list to the LLM vs embedding top-20

2026-10-27. Code, prompt and runs: `experiment/obi_llm_fulllist/`; full table in `comparison/summary.md`.

## Verdict (all 31 papers)

The full list loses: **128 exact vs 141** for embedding (140 for the stored v3 run). It wins 5
entries and loses 18. On the 10 papers where embedding was weakest it is ahead by one, and on
the other 21, where embedding was already right everywhere, it loses 15 of 107 entries and wins
none. Embedding retrieval stays.

| 31 papers, 157 curated rows | fulllist | embedding | v3_reference |
|---|---|---|---|
| exact | 128 | **141** | 140 |
| OBI ok (same or parent/child) | 141 | **145** | 145 |
| obi_exact_rate | 82.1% | **90.4%** | 89.7% |
| obi_recall | 89.8% | **92.4%** | 92.4% |
| MATCH_GRANULARITY | 13 | 4 | 5 |
| MATCH_OBI_CONFLICT | 10 | 5 | 5 |
| MATCH_OBI_UNMAPPED | 5 | 6 | 6 |

**Cost.** 170 calls: 6,634,421 prompt tokens, of which 6,330,112 (95%) were cached, plus 877
completion tokens.

**The 15 entries lost on the other 21 papers.** Nine of them are the full list stopping at a
parent term when the specific child was right. That is the same failure as on the first 10,
and it is now clearly systematic:

- bulk RNA-seq assay → RNA-seq assay (SDY1288, SDY1991)
- genotyping by SNP array → genotyping by array (SDY1276, SDY212)
- bacterial neutralization → pathogen neutralization (SDY1325)
- antibody detection by CBA → cytometric bead array (SDY2189)
- real time RT-PCR → real time PCR (SDY1293, SDY1654)
- real time PCR → PCR (SDY1669; the stored v3 run made the same miss)

The rest are wrong neighbours:
- cell-cell killing → flow cytometry assay
- immuno staining → fluorescence microscopy assay
- bacterial LPS detection in plasma → reporter gene assay
- pathogen neutralization ↔ serum neutralization of viral infectivity, both directions
- infectious agent detection → none (UNMAPPED)

**Why.** In a 20-line list the specific child sits next to its parent, and the rules (2, 5, 8,
10) push the model toward it. In 701 lines the model goes to the familiar label and stops.
What the full list buys is recall: it finds a term that retrieval never surfaced. That is
worth 4 to 5 entries here, against 18 lost on specificity.

**Next step, if any.** A hybrid that keeps embedding as the pick and adds the full list only
when the picker answers "none" or BROAD. That targets the 3 unmapped wins (complete blood
count, multianalyte profiling, surface HBV antibody) without exposing the specific picks.

## First run: the 10 worst papers

### What changed between the arms

Round 4 only. The embedding arm retrieves 20 candidates from the pruned 701-term vocabulary
(two `text-embedding-3-small` queries) and asks gpt-5.4 to pick one. The full-list arm drops
retrieval: one gpt-5.4 call per assay sees all 701 terms, rendered exactly as the picker renders
a candidate. The rules are the same as in `resolver_obi_assay.txt`. The term list goes first, so
the calls share one cacheable prefix. Everything else is held fixed:

- the input (`assays.json` of `assay_result_v3`)
- the free exact-name step
- pinning of an exact hit's children, with the exact hit as the floor on "none"
- no BROAD re-pick and no round-5 fold
- the scorer (`compare_assay_benchmark_v2.py`, benchmark v5)

**Papers.** The 10 with the most non-exact matched rows under embedding. These are also the
only 10 of the 31 that have any: SDY1264, SDY1260, SDY1328, SDY1373, SDY984, SDY1289, SDY1640,
SDY1596, SDY1630, SDY1655. That is 70 entries and 55 curated rows.

**Baselines (free).**
- `embedding`: the same 10 registries from `obi_vocab_v3` arm `pruned`, run on the same day
  with the same input.
- `v3_reference`: the stored v3 mapping, which shows run-to-run variance.

### Result

| metric | fulllist | embedding | v3_reference |
|---|---|---|---|
| exact (same OBI term as curator) | **41** | 40 | 40 |
| OBI ok (same or parent/child) | **47** | 44 | 44 |
| obi_exact_rate | 74.5% | 72.7% | 72.7% |
| obi_recall | 85.5% | 80.0% | 80.0% |
| MATCH_GRANULARITY | 6 | 4 | 4 |
| MATCH_OBI_CONFLICT | 4 | 5 | 5 |
| MATCH_OBI_UNMAPPED | 4 | 6 | 6 |
| EXTRA | 4 | 5 | 4 |

**Cost.** 66 calls: 2,575,585 prompt tokens, of which 2,443,008 (95%) were cached, plus 342
completion tokens. The embedding arm uses about 20-line prompts plus 2-3 embedding calls per
assay.

### Entries that moved (61 of 70 identical)

**Won (5).** One of these is only variance: SDY984 `cytometric bead array assay (2)` was right
in `v3_reference` and wrong in the fresh embedding run. Against the stored mapping the net
result is +4 −3.

| paper | entry (paper wording) | embedding | fulllist = curator |
|---|---|---|---|
| SDY1328 | complete blood count | unmapped | hematology assay |
| SDY1328 | multiplex ELISA, Human Inflammation multianalyte profiling | unmapped | cytometric bead array assay |
| SDY1328 | surface HBV antibody assay | surface HBV antibody assay (EXTRA) | enzyme-linked immunosorbent assay |
| SDY1289 | real-time RT-PCR | real time RT-PCR assay | real time PCR assay |
| SDY984 | cytometric bead array (2) | analyte detection by flow based bead assay | cytometric bead array assay |

The pattern is that retrieval never surfaced the curator's term. "Complete blood count" does
not embed near "hematology assay", so with the whole list in view the model finds it.

**Lost (3).** In each case the full list chose a coarser or neighbouring term, against a rule
the embedding arm followed.

| paper | entry (paper wording) | embedding = curator | fulllist |
|---|---|---|---|
| SDY1289 | BD Th1/Th2 CBA array | analyte detection by flow based bead assay | cytometric bead array assay (rule 10's BD CBA exception missed) |
| SDY1630 | Whole transcriptome profiling of sorted NK subsets | bulk RNA-seq assay | RNA-seq assay (rule 8 "sorted cells = bulk" missed) |
| SDY1596 | Bacterial viability stain (SYTO/PI) | flow cytometry assay | cell viability assay, BROAD (defensible; the curator filed it under the instrument) |

**Changed (1).** SDY1596 `Whole blood assay`. Embedding chose `blood assay`, the full list said
"none". Both are EXTRA because the curator has no row for it.

### Reading

- The full list beats retrieval by 1 exact and 3 obi_ok on the 10 hardest papers. Its wins are
  recall misses, where the term was never in the top 20. Its losses are fine-grained rule
  applications that a 20-line list makes salient and a 701-line list dilutes.
- 15 non-exact rows is a small sample, and the run-to-run variance (SDY984) is as large as one
  of the wins. This is not yet evidence that the full list is better overall.
- The 21 papers that were not run have 0 non-exact rows under embedding. The full list could
  only lose there.

**Possible next steps.**
- Run the other 21 papers. About 107 calls at the same cached rate would show whether it
  regresses where embedding is already right.
- Try a hybrid that keeps the embedding top 20 marked inside the full list.
