# What counts as one assay entry, and why a registry carries `flow cytometry assay (2)`

Written 2026-10-26, against `data/31paper_assays/assay_result_v3/` and
`data/benchmark_assay/benchmark_assay_v5/`.

The question: a delivered registry sometimes holds `flow cytometry assay`, `flow cytometry
assay (2)` and `(3)`, all on `OBI:0000916`. Is that a defect, and should the pipeline deliver one
entry per OBI term instead?

**No. Several entries on one term are correct, and the pipeline should keep delivering them.**
What was wrong is the rule that decided which ones to keep apart.

## Why several entries on one term are right

One entry means one measurement, not one technique. Four independent lines say so.

- **The extraction asks for it.** `apps/api/app/prompts/extract_assays.txt` ("One entry per
  distinct measurement") identifies a measurement by a triple -- the technique, the analyte, and
  the specimen -- and names the flow-cytometer case outright, listing immunophenotyping, AIM,
  CFSE, intracellular cytokine staining and MHC multimer staining as separate entries even when
  the paper calls all of them flow cytometry.
- **The curators do it too.** Five of the 31 benchmark files carry two rows on one OBI id:
  SDY1288 (two ELISAs), SDY1640, SDY1655 and SDY1669 (flow cytometry against intracellular
  cytokine staining), and SDY984 (a T-cell cytokine ELISPOT against a B-cell IgG ELISPOT).
- **The adjudication scores the opposite as the fault.** `benchmark_v5_vs_agent_v1_adjudication.md`
  counts nine of fourteen agent faults as a dropped or merged assay, against three over-splits.
- **The downstream join needs it.** `claim_assay_linker.py` binds each claim to one `assay_key` and
  carries that entry's `sample_type` and `generate_claim` back to the claim. Fold two protocols
  into one entry and `generate_claim` is OR-ed, so a protocol the paper reports nothing from can
  no longer be told from its merged twin.

## Why OBI collapses them onto one term

Not because the mapper failed. `_is_generic_assay_label` in `assay_obi_mapper.py` prunes
IEDB-style compositional labels ("assay measuring epitope specific X of Y cells") from the
candidate vocabulary, leaving 701 terms. That prune is deliberate: the docstring records that
those labels are about 30% of the OBI assay branch and outrank the plain family terms in
similarity search.

The prune removes every IFN-gamma, interferon and degranulation term, including `OBI:1110207
assay detecting IFN-gamma production` -- the term the SDY1630 curator chose, and the one the
docstring names as having been picked four times in a 30-paper run, twice in place of ELISPOT.

So for a whole class of assays there is no term naming the function, and `flow cytometry assay`
marked BROAD is the correct answer. Round 5's re-pick, which exists to rescue a BROAD mapping,
**made 27 chat calls across the corpus and changed 0 terms.** That is not a bug in the re-pick;
it is the only answer the pruned vocabulary allows. It remains dead spend, and cutting it was
considered and left out of scope.

## The rule that was keeping entries apart, and what replaced it

`assay_merger._refusal` used to refuse a fold when either mapping was marked BROAD, or when
`standard_technique_name` conflicted. Corpus-wide that was **12 blocked folds for "mapping is
BROAD" and 1 for a technique difference** -- so the splits were a side effect of the mapping's
granularity, not a judgement about protocols.

Using BROAD as the signal fails in both directions. It keeps two write-ups of one measurement
apart whenever either mapped to a category term, and it cannot keep two genuinely different
measurements apart when both mapped EXACT to one term. The second case was happening: of the nine
folds the corpus performed, five merged entries whose analyte, specimen or platform differ --
SDY984's two ELISPOTs, SDY1260's serum-antibody and supernatant-cytokine ELISAs, SDY1328's two
antigen ELISAs, SDY1640's two RBD ELISAs, and SDY1291's Affymetrix and Agilent arrays.

The rule is now the extraction's own identity triple: a fold is refused when
`standard_technique_name`, `sample_type` or `readouts` conflict. A field absent on one side never
blocks, and `sample_type` is compared by containment, so "sera samples" and "samples" agree while
"serum" and "cell supernatants" do not.

## Two discriminators that were tested and rejected

Neither separates the folds that should happen from the ones that should not, measured over every
folded and blocked pair in the corpus:

| Discriminator | Folded pairs | Blocked pairs |
|---|---|---|
| Token overlap on `readouts` | 0.00 - 0.75 | 0.00 - 0.43 |
| Same evidence section | 2 of 9 | 5 of 13 |

Six folds that should hold score below 0.06 on readout overlap while five blocks that should hold
score above 0.17, so no threshold works; and same-section appears on both sides. A rule that got
every case right would need a judgement per group, which is a call per candidate fold. The rule
shipped instead errs toward splitting, on the adjudication's evidence that splitting is the rarer
and milder fault.

## What it did to the corpus

`assays.json` is written post-fold, so re-running round 5 on a finished registry cannot un-fold
anything -- the folded members are gone as entries. The corpus was re-canonicalized from each
paper's `assays_corrected.json`, with every wording's OBI id rebuilt from the stored `key_map`.
That calls nothing. Registry entries rose from 168 to 177 across 7 papers, and **round 5 now folds
nothing anywhere in the corpus.**

Both columns below are scored against the same benchmark, by re-scoring the committed registries
alongside the new ones. That matters here: on 2026-10-26 `load_lenient` in
`compare_assay_benchmark_v2.py` gained `_hoist_nested_entries`, which un-nests the entries an
unclosed brace swallowed, and seven `benchmark_assay_v5` files were edited the same day. The
scorer repair is why SDY1669 now parses as 9 curator rows instead of 3, and why `benchmark_raw`
reads 158 against the 152 in reports committed earlier. Neither of those is this change, and the
old-rule column already carries both, so the two columns differ only by the fold rule.

| metric | old rule | new rule |
|---|---|---|
| benchmark rows | 155 | 157 |
| agent entries | 168 | 177 |
| matched | 154 | 156 |
| exact MATCH | 138 | 140 |
| OBI ok | 143 | 145 |
| missed | 1 | 1 |
| extra | 4 | 4 |
| split annotations | 9 | 15 |
| recall | 0.994 | 0.994 |
| precision | 0.917 | 0.881 |
| F1 | 0.954 | 0.934 |
| OBI recall | 0.923 | 0.924 |

Read honestly, this is a mixed result. Two curator rows that the scorer previously had to merge --
SDY984's second ELISPOT among them -- now pair on their own, so matched and exact each rise by
two, and recall, misses and EXTRA are untouched. Against that, seven of the nine un-folded entries
claimed no curator row and show up as split annotations, which is what drags precision from 0.917
to 0.881.

Several of those seven look like one protocol written up twice rather than two protocols: SDY1630
now separates "Flow cytometry analysis and cell sorting" from "High-dimensional parameter flow
cytometric analysis of NK cell subsets", and SDY1260 separates "flow cytometry" from "FACS
staining". Both pairs read as the same panel under two headings. That is the predicted cost of a
rule that compares model-written readout prose for equality, and it is the first thing to revisit
if the fold is given a judgement step.

## What a reader of a delivered registry cannot see

`trim_registry` drops `standard_technique_name`, `sample_type` and `readouts` from
`assays_benchmark.json`, so a `(2)` entry in the deliverable carries nothing that says why it is
apart. The reason is in `assays_merges.json` under `blocked`, as a `REVIEW  not folded` line.
Carrying a discriminator into the deliverable was considered and left out of scope.
