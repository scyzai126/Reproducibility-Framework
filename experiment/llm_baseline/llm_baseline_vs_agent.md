# Bare LLM baseline vs the assay agent

*2026-10-27. 31 papers, scored against benchmark v5 by `scripts/compare_assay_benchmark_v2.py`.
Data and code: `experiment/llm_baseline/`.*

**Baseline:** one gpt-5.4 call per paper (`prompt.txt`), with the same input the agent's round 1 reads
(the JATS text with the sentence markers removed, or the PDF attached). It asks for each assay's name in
the paper, a quote, and an OBI id and label from memory. Nothing else: no vocabulary, vote, verification
or fold. Default temperature, run 3 times.
**Agent:** the delivered `assay_result_v3` registries.

The model's OBI ids are scored in two ways:
- **strict:** the id as given. An id that does not exist or is obsolete counts as unmapped.
- **generous:** the model's label, looked up in `obi.obo` by name or synonym, falling back to the
  model's id when the label matches nothing.

## Results

| | agent | baseline, strict (mean of 3) | baseline, generous (mean of 3) |
|---|---|---|---|
| curated rows matched (of 157) | 156 | 153.7 | 155.0 |
| MISSED | 1 | 4.0 | 2.3 |
| entries delivered | 177 | 249.3 | 249.3 |
| EXTRA (no curated row) | **4** | 95.0 | 69.3 |
| exact: same OBI term as curator | **140** | 13.7 | 75.3 (73–77) |
| OBI recall: same term or parent/child | **92.4%** | 15.4% | 60.2% |
| wrong term (CONFLICT) | 5 | 116.0 | 50.0 |
| LLM calls | 512 | 31 | 31 |

Between baseline runs, 114 of 157 curated rows get the same status in all 3 runs. Of the distinct OBI terms
the baseline used, 99 of 340 appear in all 3 runs. The agent's run-to-run noise on mapping is 1 exact
(`docs/obi_vocab_full_vs_pruned_v3.md`).

**In short:** a plain call finds the assays about as well as the agent does: it matches 155 of 157 curated
rows against 156. Where the agent wins is everything after that: the right OBI term (140 vs 75 even when
the baseline's labels are read for it), a clean list (4 extra vs 69), and the same answer on every run.
The agent costs 16× the calls.

## Why the agent wins

**1. The model cannot recall OBI ids (strict: 14 exact vs 140).** Of the ~250 ids per run, 18 match the
label the model gave with them. 217 are real OBI ids for some other term, and 11 do not exist.
- "flow cytometry assay" was given as `OBI:0000716`, which is `ChIP-seq assay`.
- "ELISPOT assay" was given as `OBI:0001232`, which is *assay measuring epitope specific RANTES production
  by T cells*.
- "Luminex assay" was given as `OBI:0002859`, which does not exist.

A user who stores the id the model gives gets the right term for about 1 assay in 11. The agent never
writes an id that is not in the vocabulary.

**2. Even with its labels read for it, the model picks the wrong term in OBI (generous: 75 exact vs 140).**
It knows the technique's everyday name, not OBI's term for it.
- "DNA microarray" (`OBI:0400148`, a device) is given for *transcription profiling by array assay* in 7
  papers, and "microarray assay" in an 8th.
- "polymerase chain reaction" is given where the curators wrote a real-time or RT-PCR term (SDY984,
  SDY1995), and even for SDY1389's *T cell receptor repertoire sequencing assay*.
- Some labels are not OBI terms at all and resolve to nothing: "multiplex bead-based immunoassay",
  "neutralization assay", "complete blood count", "plaque reduction neutralization test".

The agent's retrieval over the 701-term vocabulary plus one pick gets these right. The family-level choice
the curators make (`real time polymerase chain reaction assay`, `transcription profiling by array assay`)
is exactly what that pick is shown and chooses from.

**3. The baseline's list is not a list of assays (EXTRA: 69 vs 4).** Each run delivers about 250 entries
for 157 curated rows. The extras are procedures and analysis steps the agent's prompt and verifier keep
out: `cell culture` (6), `data transformation` (6), `electrophoresis`, `vaccination`,
`pathogen challenge`, k-means clustering, Benjamini–Hochberg correction, median calculation, and once a
`grant`.

**4. The baseline is not stable.** Only 99 of the 340 distinct terms it used appear in all three runs.
Example: SDY1289's qPCR is `real time polymerase chain reaction assay` in runs 1 and 3, and unmapped in
run 2.

## Where the baseline wins (3 rows)

- SDY984 plasma metabolomics: the curator wrote `liquid chromatography mass spectrometry assay`, which the
  baseline gave in 2 of 3 runs. The agent gave `metabolomics by mass spectrometry assay`.
- SDY1373 "Next-Generation RNA Sequencing": the curator wrote `polyA-selected RNA sequencing assay`. The
  baseline's `RNA sequencing assay` is the parent term, so it counts as GRANULARITY. The agent's
  `bulk RNA-seq assay` is a sibling, so it counts as CONFLICT.
- SDY1289 qPCR: the curator wrote `real time polymerase chain reaction assay`. The agent gave the RT-qPCR
  term.

All three are within one or two steps of the curator's term. None is an assay the agent missed.

## Caveats

- The benchmark has 157 curated rows, but r2 and r3 score against 158. The comparator's fold of
  same-term curator rows depends on how the other side pairs with them.
- The agent column is one delivered run, scored at temperature 0. The baseline uses the default
  temperature on purpose.
- The baseline's match counts depend on the comparator pairing by name and quote, so they flatter a long
  list. Its 155 matched rows come alongside 69 extras.
