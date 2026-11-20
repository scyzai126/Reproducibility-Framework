# The assay agent against comparison arms

*2026-11-02, all arms run. **Agent column rescored 2026-11-11** on the current
`assay_result_v3`: the OBI round was re-run with the 1249-term noncompositional vocabulary at
TOP_K=30 (2026-11-10, `experiment/obi_topk_1249/FINDINGS.md`) and the outstanding round-6 judge
calls were filled in. No other arm was re-run — none of them depends on our mapping, and every
baseline column is byte-identical to the 2026-11-02 rebuild. Scores:
`experiment/common/comparison/arms_table.md` (rebuilt by `experiment/common/compare_arms.py`).
Plan: `docs/plan/assay_agent_comparison_baselines_plan.md`.
Scorer: `scripts/compare_assay_benchmark_v2.py`, default and `--strict`
(`docs/assay_scorer_strict_mode.md`). Benchmark v5, 31 papers, 158 curated rows.*

The question for the write-up is what the agent's five rounds add over simpler ways of listing a
paper's assays with OBI terms. Every arm below writes the same two registry files per paper and is
scored by the same code, in both scorer modes. The strict numbers are the ones to report.

## Arms

| arm | what it is | model calls / paper | status |
|---|---|---|---|
| agent | `scripts/run_assay_pipeline.py`, rounds 1-6, `data/benchmark_agent_assays/assay_result_v3` | ~17 | scored |
| bare LLM ×3 | one gpt-5.4 call, no vocabulary; ids as given, or its labels read for it | 1 | scored (2026-10-27) |
| dictionary | OBI labels + synonyms string-matched, longest match first; 701 pruned or 1794 full terms; whole paper or Methods | 0 | scored |
| agent, old fold | the delivered v3 registries with the superseded same-term fold | — | scored |
| RAG single call ×3 | the bare prompt with the 701-term vocabulary in context | 1 | scored (93 calls) |
| OntoGPT | the published SPIRES tool (v1.2.0), grounded to OBI by OAK, same model | 1 | scored (31 calls) |
| NCBO Annotator | BioPortal's concept-recognition service on OBI; whole paper or Methods | 0 | scored |

## Strict scorer, 31 papers, 158 curated rows

| metric | agent | bare LLM, ids as given | bare LLM, labels read | RAG single call | OntoGPT | NCBO Annotator, paper | dictionary, paper | agent, old fold |
|---|---|---|---|---|---|---|---|---|
| entries | 176 | 249 | 249 | 227 | 263 | 94 | 484 | 155 |
| matched of 158 | 156 | 154 | 155 | 157 | 155 | 60 | 141 | 151 |
| MISSED | 2 | 4 | 3 | 1 | 3 | 98 | 17 | 7 |
| EXTRA | 4 | 95 | 69 | 33 | 107 | 34 | 341 | 4 |
| exact OBI term | **144** | 13 | 75 | 120 | 22 | 47 | 79 | 136 |
| OBI ok (same or parent/child) | **148** | 23 | 95 | 137 | 23 | 51 | 108 | 141 |
| wrong term (CONFLICT) | 4 | 117 | 50 | 13 | 3 | 9 | 31 | 4 |
| no usable term (UNMAPPED) | 4 | 14 | 10 | 7 | 129 | 0 | 2 | 6 |
| recall | 98.7% | 97.3% | 98.1% | 99.2% | 98.1% | 38.0% | 89.2% | 95.6% |
| precision | 88.6% | 61.6% | 62.2% | 69.1% | 58.9% | 63.8% | 29.1% | 97.4% |
| F1 | **0.934** | 0.755 | 0.761 | 0.815 | 0.736 | 0.476 | 0.439 | 0.965 |
| OBI recall | **93.7%** | 14.6% | 59.9% | 86.7% | 14.6% | 32.3% | 68.4% | 89.2% |
| model calls | 532 | 31 | 31 | 31 | 31 | 0 | 0 | 512 |

Bare-LLM and RAG columns are the mean of three runs (ranges in the arms table). The arms table
also has the dictionary and NCBO Methods-only variants, the dictionary on the full 1794-term
vocabulary, and every default-scorer number, which differ by one to three rows per column.

## What the table says

**Finding the assays is not the hard part, for a model.** A single call matches 154 of 158
curated rows, OntoGPT 155, the RAG call 157; the home-made dictionary, with no model at all,
matches 141. The agent's 156 is in that band. The one arm that cannot find them is the
published annotator: NCBO matches 60, because it only sees a paper that writes OBI's own string
(it finds `flow cytometry assay` in 10 papers, every time through the synonym `FACS`, and
misses the 18 that write "flow cytometry").

**Naming the term is.** The bare call gets 13 terms right out of 154 found, because it cannot
recall OBI ids; read its labels for it and it gets 75. OntoGPT, the published system built on
the same idea, gets 22: its grounder is lexical, so "flow cytometry", "microarray analysis",
"Luminex", "RNA-seq" and "ELISpot" all stay ungrounded (129 of its matched rows carry no term).
The dictionary gets 79, and its wrong terms are systematic: `microarray assay` where the
curators write `transcription profiling by array assay` (15 papers), the PCR parent where they
write the RT-PCR child (5). Handing the model the vocabulary closes most of the gap: the RAG
call gets 120, and none of its ids is invented. The last 24 are the ones a one-shot list loses
to a familiar neighbour (`docs/obi_fulllist_llm_vs_embedding.md`): `flow cytometry assay` →
`immuno staining assay`, the RT-qPCR term → the plain real-time PCR term, `serum neutralization
of viral infectivity assay` → `pathogen neutralization assay`, `cytometric bead array assay` →
ELISA. The agent's 144 exact and 148 within one ontology step come from the mapping stack: a
vocabulary with the compositional labels pruned, embedding retrieval of 30 candidates, one pick
that reads definitions. The vocabulary and the candidate width interact — widening K on the old
701-term list *costs* 2 exact while the 1249-term list gains 2 — so both were changed together on
2026-11-10 (`experiment/obi_topk_1249/FINDINGS.md`; the superseded K=20 A/B is
`docs/obi_vocab_full_vs_pruned_v3.md`). That switch is worth 4 of these 144: the arm scored
2026-11-02 had 140.

**A clean list is the other half.** The dictionary delivers 3.1 entries per curated row, OntoGPT
1.7, the bare call 1.6, the RAG call 1.4, the agent 1.1 (4 EXTRA in 176). The extras are what
each method cannot tell from an assay: for the dictionary, terms whose labels are everyday words
(`protein assay`, `blood assay`, `immune response assay` in 20-29 papers each); for NCBO, OBI's
acronym synonyms taken literally (`LPS` → two lipopolysaccharide-detection assays in 7 papers,
`CMV` → an anti-CMV antibody assay, `RPA` → `RNA protection assay`: 24 of its 34 extras); for the
bare call and OntoGPT, procedures and analysis steps (`cell culture`, `data transformation`,
principal component analysis, GSEA, `cell sorting`, a `grant`); for the RAG call, a parent term
listed beside the child it also gave (`polymerase chain reaction assay` next to the real-time
term: 15 over three runs) and `null` entries it could not name (14). The agent's verifier and
its prompt keep them out. Precision is where every single-call arm stays below 70%.

**The fold rule costs precision and buys curated rows.** The superseded same-term fold would
deliver 155 entries at 97.4% precision and F1 0.965, and lose 5 curated rows and 8 exact terms
under the strict scorer, because the curators write two rows on one term in 5 of the 31 papers.
Under the default scorer that loss is invisible (MISSED 2, F1 0.981), which is why the strict
mode exists. Round 5's own rule folded 0 of 177 entries in v3 and round 6 folded 1 — SDY2189's
two focus-reduction neutralization records, on a `JUDGED SAME` verdict — leaving 176. What the
rule buys is that an entry is one measurement, not one technique (`docs/assay_entry_grain.md`).

**Cost.** The agent spends 532 calls over the corpus against 31 for a single-call arm and none for
the dictionary or NCBO. The RAG call's 1.5M prompt tokens per run are 86% cached across three
runs; OntoGPT's 338k are not cached at all. Run-to-run variance is the other side of that cost:
the bare call keeps 99 of 340 terms across three runs, the RAG call changes the status of 9 of
158 curated rows between runs; the agent's variance is one exact term.

## Per-arm write-ups

Each arm's README carries its own numbers and examples: `experiment/rag_single_call/README.md`,
`experiment/ontogpt/README.md`, `experiment/ncbo_annotator/README.md`,
`experiment/dictionary_baseline/README.md`, `experiment/no_fold/README.md`,
`experiment/llm_baseline/llm_baseline_vs_agent.md`.

## Caveats for the paper

- Benchmark and agent share the OBI release in `data/OBI/obi.obo`; the curators' files have known
  faults (`docs/benchmark_v5_vs_agent_v1_adjudication.md`: 5 curator faults, 6 malformed files).
- One curator per paper; there is no inter-curator agreement to bound the ceiling.
- Default temperature for the bare and RAG arms, temperature 0 for the agent's pick, by design:
  the single-call arms measure what a user would see.
- The dictionary's rules (plural, trailing "assay" stripped, longest match) are the obvious ones
  and are listed in its README; it is not tuned to the benchmark. NCBO and OntoGPT are run as
  they ship, with their defaults; OntoGPT uses the agent's model and the OBI SQLite build OAK
  fetches, which may trail `data/OBI/obi.obo`.
- OntoGPT is one run, not three: its grounding is deterministic and the model side showed in the
  bare-LLM arm what a repeat buys.
