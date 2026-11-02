# The assay agent against comparison arms

*2026-11-02. Scores: `experiment/common/comparison/arms_table.md` (rebuilt by
`experiment/common/compare_arms.py`). Plan: `docs/plan/assay_agent_comparison_baselines_plan.md`.
Scorer: `scripts/compare_assay_benchmark_v2.py`, default and `--strict`
(`docs/assay_scorer_strict_mode.md`). Benchmark v5, 31 papers, 158 curated rows.*

The question for the write-up is what the agent's five rounds add over simpler ways of listing a
paper's assays with OBI terms. Every arm below writes the same two registry files per paper and is
scored by the same code, in both scorer modes. The strict numbers are the ones to report.

## Arms

| arm | what it is | model calls / paper | status |
|---|---|---|---|
| agent | `scripts/run_assay_pipeline.py`, rounds 1-5, `data/31paper_assays/assay_result_v3` | ~16.5 | scored |
| bare LLM ×3 | one gpt-5.4 call, no vocabulary; ids as given, or its labels read for it | 1 | scored (2026-10-27) |
| dictionary | OBI labels + synonyms string-matched, longest match first; 701 pruned or 1794 full terms; whole paper or Methods | 0 | scored |
| agent, old fold | the delivered v3 registries with the superseded same-term fold | — | scored |
| RAG single call ×3 | the bare prompt with the 701-term vocabulary in context | 1 | **pending go-ahead** (93 calls) |
| OntoGPT | the published SPIRES tool, grounded to OBI by OAK, same model | 1 | **pending go-ahead** (31 calls) |
| NCBO Annotator | BioPortal's concept-recognition service on OBI | 0 | **pending a BioPortal API key** |

## Strict scorer, 31 papers

| metric | agent | bare LLM, ids as given | bare LLM, labels read | dictionary, pruned, paper | dictionary, pruned, Methods | agent, old fold |
|---|---|---|---|---|---|---|
| entries | 177 | 249 | 249 | 484 | 349 | 155 |
| matched of 158 | 156 | 154 | 155 | 141 | 124 | 151 |
| MISSED | 2 | 4 | 3 | 17 | 34 | 7 |
| EXTRA | 4 | 95 | 69 | 341 | 224 | 4 |
| exact OBI term | **140** | 13 | 75 | 79 | 63 | 136 |
| OBI ok (same or parent/child) | **145** | 23 | 95 | 108 | 91 | 141 |
| wrong term (CONFLICT) | 5 | 117 | 50 | 31 | 31 | 4 |
| recall | 98.7% | 97.3% | 98.1% | 89.2% | 78.5% | 95.6% |
| precision | 88.1% | 61.6% | 62.2% | 29.1% | 35.5% | 97.4% |
| F1 | **0.931** | 0.755 | 0.761 | 0.439 | 0.489 | 0.965 |
| OBI recall | **91.8%** | 14.6% | 59.9% | 68.4% | 57.6% | 89.2% |

Bare-LLM columns are the mean of three runs (ranges in the arms table). Default-scorer numbers
differ by one to three rows per column and are in the same file.

## What the table says

**Finding the assays is not the hard part.** A single call matches 154 of 158 curated rows; the
dictionary, with no model at all, matches 141. The agent's 156 is better, but by a few rows.

**Naming the term is.** The bare call gets 13 terms right out of 154 found, because it cannot
recall OBI ids; read its labels for it and it gets 75. The dictionary gets 79, and its wrong terms
are systematic: `microarray assay` where the curators write `transcription profiling by array
assay` (15 papers), the PCR parent where they write the RT-PCR child (5). The agent's 140 exact
and 145 within one ontology step come from the mapping stack (`docs/obi_vocab_full_vs_pruned_v3.md`,
`docs/obi_fulllist_llm_vs_embedding.md`): a pruned vocabulary, embedding retrieval of 20
candidates, one pick that reads definitions.

**A clean list is the other half.** The dictionary delivers 3.4 entries per curated row, the bare
call 1.6, the agent 1.1 (4 EXTRA in 177). The extras are what each method cannot tell from an
assay: for the dictionary, terms whose labels are everyday words (`protein assay`, `blood assay`,
`immune response assay` in 20-29 papers each); for the bare call, procedures and analysis steps
(`cell culture`, `data transformation`, a `grant`). The agent's verifier and its prompt keep
them out.

**The fold rule costs precision and buys curated rows.** The superseded same-term fold would
deliver 155 entries at 97.4% precision and F1 0.965, and lose 5 curated rows and 4 exact terms
under the strict scorer, because the curators write two rows on one term in 5 of the 31 papers.
Under the default scorer that loss is invisible (MISSED 2, F1 0.981), which is why the strict
mode exists. The delivered rule folded 0 of 177 entries in v3; what it buys is that an entry is
one measurement, not one technique (`docs/assay_entry_grain.md`).

**Cost.** The agent spends 512 calls over the corpus against 31 for a single-call arm and none for
the dictionary. The bare call's run-to-run variance (99 of 340 terms present in all three runs)
is the other side of that cost; the agent's is one exact term.

## Still to run

- **RAG single call** (`experiment/rag_single_call/`): 93 calls, ~40.6k-token cacheable prefix
  per call plus ~295k tokens of paper text per run. Shows whether handing the model the vocabulary
  closes the term gap without retrieval, a vote or verification.
- **OntoGPT** (`experiment/ontogpt/`): 31 calls, ~343k input tokens. The published system closest
  to ours; its grounder is lexical, so the smoke test already shows it leaves "flow cytometry",
  "Luminex multiplex assay", "PRNT" and "RNA-seq" ungrounded.
- **NCBO Annotator** (`experiment/ncbo_annotator/`): free once `BIOPORTAL_API_KEY` is in `.env`.

Each writes its own `comparison/summary.md`; `compare_arms.py` picks them up as they land.

## Caveats for the paper

- Benchmark and agent share the OBI release in `data/OBI/obi.obo`; the curators' files have known
  faults (`docs/benchmark_v5_vs_agent_v1_adjudication.md`: 5 curator faults, 6 malformed files).
- One curator per paper; there is no inter-curator agreement to bound the ceiling.
- Default temperature for the bare and RAG arms, temperature 0 for the agent's pick, by design:
  the single-call arms measure what a user would see.
- The dictionary's rules (plural, trailing "assay" stripped, longest match) are the obvious ones
  and are listed in its README; it is not tuned to the benchmark.
