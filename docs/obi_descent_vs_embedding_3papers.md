# OBI tree descent vs embedding retrieval: the three papers the embedding mapping got most wrong

*2026-10-21. Experiment folder `experiment/obi_descent_3papers/`; per-arm scorer output in its
`comparison/`, the walks themselves in `runs/<arm>/<paper>/raw.json`. Nothing under `data/`
was written and the production default (`OBI_MAPPING_STRATEGY=embedding`) is unchanged.
Two arms were run against the stored mapping: the root walk (`descend`, first section) and,
on its result, the embedding pick followed by one descent from it (`hybrid`, second section).*

## Question

Round 4 maps each assay to an OBI term. The default strategy retrieves the top 20 terms by
embedding similarity (plus the direct parents and children of the top 3) and asks the model to
pick once. The alternative, implemented 2026-10-20, walks the OBI assay tree from the top
(or from an exact name hit), one call per level, choosing among the current term's direct
children or stopping on it. Does the walk fix what retrieval got wrong?

The papers are the three with the most rows where *our* term disagreed with the curator in
`data/benchmark_assay/comparison/benchmark_vs_agent.json` (registry `assay_result_v1`):
SDY1264 (PMID 19029902, 2 rows), SDY1373 (28854372, 2 rows), and SDY1260 (24336226, 1 row,
chosen among six tied at one because its error was a parent picked over the curator's child,
the case the descent is for). The embedding arm is the stored mapping; the descent arm is a
fresh round 4 on a copy of each paper's canonical `assays.json`.

## Result: the descent did not win

| metric | embedding (stored) | descent |
|---|---|---|
| curated rows | 18 | 18 |
| agent entries | 18 | 18 |
| matched to a curated row | 18 | 17 |
| exact (same OBI term as curator) | 11 | 10 |
| obi_exact_rate | 61.1% | 58.8% |
| MATCH_GRANULARITY (parent/child of curator's term) | 2 | 1 |
| MATCH_OBI_CONFLICT (different term) | 3 | 4 |
| MATCH_OBI_UNMAPPED (curator gave no id) | 2 | 2 |
| MISSED / EXTRA | 0 / 0 | 1 / 1 |
| walks that backed off | — | 0 |
| chat calls spent | 41 (incl. embedding calls) | 37 |

Five entries changed term. One change was right, two were wrong, one moved an entry with no
curated term onto a worse term, and one moved a wrong term to a different wrong term.

### The five changed entries, with the walk

| paper | entry (paper wording) | embedding | descent | curator | walk |
|---|---|---|---|---|---|
| SDY1260 | anti-DT IgG capture microsphere assay / 27-plex cytokines (Luminex) | OBI:0000920 cytometric bead array assay | **OBI:0003116 antibody detection by CBA** | OBI:0003116 | root → analyte assay → CBA → `2 exact` (3 calls) |
| SDY1264 | neutralizing antibodies by CPE / PRNT | **OBI:0000872 serum neutralization of viral infectivity assay** | OBI:0003796 pathogen neutralization assay | OBI:0000872 | root → `81` pathogen neutralization → `stop broad` (2 calls) |
| SDY1264 | microarray (alias "transcriptional profiling") | **OBI:0001463 transcription profiling by array assay** | OBI:0001985 microarray assay | OBI:0001463 | exact hit on "microarray" → `stop broad` (1 call) |
| SDY1373 | RNA Extraction and Next-Generation RNA Sequencing (alias RNA-seq) | OBI:0003090 bulk RNA-seq assay | OBI:0000424 transcription profiling assay | OBI:0002571 polyA-selected RNA sequencing assay | root → `5` transcription profiling → `stop broad` (2 calls) |
| SDY1260 | serum bactericidal titers (SBA) | OBI:0003797 bacterial neutralization assay | OBI:0000743 immune response assay | *(none)* | root → `16` immune response assay → `stop broad` (2 calls) |

### Why each one went the way it did

**SDY1260 anti-DT IgG by Luminex: the win, and it is exactly the designed case.** The walk went
root → analyte assay (79 children) → cytometric bead array assay (3 children) → `antibody
detection by cytometric bead array assay`, EXACT. The record's readouts ("diphtheria
toxoid-specific IgG ... MFI-based arbitrary units") name antibodies, and at the last level the
model saw only CBA's three children and chose the serology one. The embedding picker had been
shown the same child (it is a `child of candidate N` neighbour) and still stayed on the parent;
with twenty other candidates on the page, the parent-vs-child question was one of many, and
here it was the only question.

**SDY1264 neutralization by CPE / PRNT: a dead end the tree built.** At the root the model chose
`pathogen neutralization assay` (candidate 81), which any reader would. Its only child in the
index is `bacterial neutralization assay`, so `stop broad` was the right answer *from there*.
The curator's term, `serum neutralization of viral infectivity assay` (OBI:0000872), is not
under pathogen neutralization assay at all: in `obi.obo` its `is_a` parents are `analyte assay`
and `blood assay`. The semantically obvious first step and the ontology's placement disagree,
and the walk cannot cross between branches. Retrieval found the term by its label and was never
asked which branch it lives in. The scorer also failed to pair the descent's term with the
curated row (MISSED + EXTRA), since neither OBI ancestry nor name matched.

**SDY1264 microarray: the same dead end, from an exact hit.** The paper's own name is
"microarray", an exact label hit on OBI:0001985 `microarray assay`, so the walk started there.
Its children in the index are genotyping, RNAi profiling, proteomic profiling, CGH and
RBP-immunoprecipitation arrays. `transcription profiling by array assay` is not among them: in
OBI it is a child of `transcription profiling assay`, not of `microarray assay`. So `stop broad`
was, again, the only defensible reply given the list. The embedding arm reached OBI:0001463
because retrieval on "microarray | transcriptional profiling | transcription profiling by
array" ranked it regardless of where it sits in the tree, and the pinned exact hit sat beside
it for the picker to weigh. The descent prompt's own array rule ("prefer the array term matching
what was hybridized") could not fire on a child that was not there.

**SDY1373 RNA-seq: a wrong first turn with no way back.** Readouts say "gene expression
levels"; the model went to `transcription profiling assay` (candidate 5). Its twelve children
are array, RT-PCR, CAGE, SAGE, MPSS and similar; every RNA-seq term lives under
`sequencing assay` → `RNA sequencing assay` → `RNA-seq assay`. So the walk stopped on the
category. The embedding arm's `bulk RNA-seq assay` was itself a conflict with the curator's
`polyA-selected RNA sequencing assay`, so this row was lost under both arms, but the descent
lost it one level higher.

**SDY1260 SBA: a wrong first turn among 96.** "Serum bactericidal titers" went to `immune
response assay` (candidate 16) rather than `pathogen neutralization assay` (81), whose child
`bacterial neutralization assay` is what the embedding arm chose and is the better term for an
SBA. The curator left this row without an id, so neither arm scores on it, but the descent's
term is the less useful of the two.

### The entries that did not change

Four of the seven rows the embedding mapping had wrong stayed wrong under the descent, on the
same term, at 2 to 5 calls each: RT-PCR → `reverse transcription PCR assay` (curator: real-time
RT-PCR; at level 2 both siblings were on the page and the model again took the plain one despite
"cycling threshold values" in the readouts), immunoblot → `western blot assay` (curator: its
parent `immunoblot assay`; the walk entered immunoblot and then stepped into its one child),
SDY1373's cytokine multiplex → `cytometric bead array assay` (curator OBI:0002970 `multiplex
bead-based protein state immunoassay`, which the prompt's own multiplex rule says is for protein
state, not concentration panels; the curator's choice looks like the odd one here), and
immunofluorescence → CHMO:0000087 at five levels (curator gave no id).

## What this says about the two strategies

1. **The descent's one gain is the "descend from a confident term" case.** From CBA, with three
   children on the page and the record in front of it, the model chose the right child. That is
   the shape of variant B (embedding or exact hit picks the entry term; the walk only goes
   *down* from it), not of a walk from the root.
2. **Three of the four losses are the OBI `is_a` graph, not the model.** Serum neutralization of
   viral infectivity sits under analyte assay, not pathogen neutralization; transcription
   profiling by array sits under transcription profiling, not microarray assay; RNA-seq sits under
   sequencing assay, not transcription profiling. In each the model took the branch a biologist
   would and the term was in another one. A walk commits to a branch at the first reply and
   cannot cross; retrieval never has to know which branch a term is in. This is a property of
   the ontology's placement choices and will recur on other papers.
3. **The first level is where it goes wrong.** Every lost entry was lost at the root reply
   (or at an exact-hit start that was itself a different branch). Nothing below that level
   made a mistake in these three papers: the per-level replies after the first turn were all
   defensible given the candidates shown.
4. **Cost was comparable, not lower.** 37 chat calls against the embedding arm's 41 (of which
   roughly 20 were cheap embedding calls), and every root-level call carried a ~96-line prompt.

## Recommendation after the root walk

Keep `embedding` as the default. Do not pursue the root walk (variant A) further; its
failure mode is structural. The result did argue for trying **variant B** on the parent-for-child
rows: take the embedding pick (or exact hit) as the entry term and, only when it has children in
the index, make one more call showing those children with the record, allowing `stop`. That
was run next.

## Variant B: the embedding pick, then one descent from it (`hybrid`)

Implemented as `OBI_MAPPING_STRATEGY=hybrid` (`assay_obi_mapper._descend_from_pick`). In the
experiment the walk started from the **stored** embedding pick rather than a fresh one, so only
the descent was paid for and the picker's run-to-run variance stayed out of the comparison. A
walk runs only when the picked term has children in the index: 11 of the 18 entries, one call
each, 11 calls in all.

| metric | embedding (stored) | descend | hybrid |
|---|---|---|---|
| exact (same OBI term as curator) | 11 | 10 | 11 |
| MATCH_GRANULARITY | 2 | 1 | 2 |
| MATCH_OBI_CONFLICT | 3 | 4 | 3 |
| MATCH_OBI_UNMAPPED | 2 | 2 | 2 |
| MISSED / EXTRA | 0 / 0 | 1 / 1 | 0 / 0 |
| chat calls spent (this run) | — | 37 | 11 |

Nine of the eleven walks answered `STOP EXACT` and left the pick where it was, including the
two cytokine panels on `cytometric bead array assay` (SDY1264, SDY1373), where the prompt's
multiplex rule says the parent is the term, and `flow cytometry assay` on all three papers.
Two walks moved, one each way, so the arm finished level with the embedding mapping:

| paper | entry | embedding | hybrid | curator | reply |
|---|---|---|---|---|---|
| SDY1260 | anti-DT IgG capture microsphere assay (Luminex) | OBI:0000920 cytometric bead array assay | **OBI:0003116 antibody detection by CBA** | OBI:0003116 | `2 exact` among CBA's three children |
| SDY1264 | neutralizing antibodies by CPE / PRNT | **OBI:0000872 serum neutralization of viral infectivity assay** | OBI:0000865 96-well neutralization assay | OBI:0000872 | `1 broad` on the only child |

**SDY1260 anti-DT IgG: right, and for 1 call rather than the root walk's 3.** The record's
readouts name antigen-specific IgG; shown CBA's three children (antigen detection, antibody
detection, flow-based bead), the model took the serology one. This is the row the root walk
also won, reached here without the 96-way first level.

**SDY1264 neutralization: an over-specific descent.** OBI:0000872 has one child in the index,
`96-well neutralization assay` ("performed in a 96-well plate"; synonym microneutralization).
The paper's record says CPE read on a Vero cell monolayer and a PRNT; nothing names a 96-well
or microneutralization format. The model stepped into the child and labelled it BROAD, which
is self-contradictory under the prompt (a child is taken only when the record gives evidence
for it; BROAD on a child means nothing more specific fits, not that the child is unsupported).
This is the failure the compositional-term experiment saw on the spike ELISA
(`experiment/obi_analyte_terms/README.md`): shown a single child whose definition any
instance of the parent nearly satisfies, a definition-first judge takes it. The scorer counts
it `MATCH_GRANULARITY` (a child of the curator's term), so the exact count fell by one.

### Where this leaves the three strategies

| | calls per unmatched entry | what it fixed here | what it broke here |
|---|---|---|---|
| embedding | 1 chat + 1-2 embedding | — | — |
| descend (root walk) | 2-5 chat, first on a 96-line prompt | 1 parent→child row | 3 rows lost at the first turn into a branch the term is not in; 1 unmapped row to a worse term |
| hybrid (pick, then descend) | embedding + 1 chat when the pick has children (11 of 18 here) | the same 1 row | 1 row over-specified onto a sole child |

Variant B is cheap (11 calls over 18 entries) and does not have the root walk's structural
failure, but on these papers it gained one row and lost one. The loss has a recognisable
shape: a term with exactly one index child whose definition is a format of the parent
(96-well, microneutralization). Two things could be tried before judging it on the full
corpus: not descending when the pick has a single child (that case can only ever over-specify
or stop, and the picker already saw that child as a `child of candidate N` neighbour), and
requiring the walk's reply on a child to be `EXACT` (a `BROAD` child is read as `STOP BROAD`).
Both are cheap rules; neither has evidence yet beyond this one row.

## Recommendation

Keep `embedding` as the default. The root walk is withdrawn as an idea. The hybrid is kept
behind `OBI_MAPPING_STRATEGY=hybrid` for a corpus-wide run if the two rules above are added;
its ceiling is the corpus's four `MATCH_GRANULARITY` rows, and on the three papers tested it
is a wash.
