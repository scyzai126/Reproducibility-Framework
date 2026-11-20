# OBI vocabulary size and mapping accuracy: 1794 vs 1249 vs 701

> **Superseded 2026-11-10 — the recommendation at the foot of this page no longer holds.**
> Every arm here fixes `TOP_K = 20`. Widening the candidate list turns the result around: the
> vocabulary and K interact with opposite signs, and at K=30 the **1249** list beats the 701 by
> 3 exact, outside the noise band, while widening K on the 701 *costs* 2. The 1249 + K=30 pair
> became the live configuration on 2026-11-10 and the 701 was retired. Separately, over 892
> corpus papers the domain prune was found to be doing real damage — it had cut four
> conformation-capture terms out from under Hi-C, so two papers reporting promoter capture Hi-C
> mapped to 5C-seq. New evidence: `experiment/obi_topk_1249/FINDINGS.md`.
>
> The body below is left exactly as written: it is the faithful record of the 2026-10-27 run,
> and its finding that the **compositional** prune carries the score still stands — that prune
> is still applied.

*2026-10-27. 31 papers, 177 assay entries (`data/benchmark_agent_assays/assay_result_v3/`), scored
against benchmark v5. Each arm re-ran round 4 (embedding top-20 + one LLM pick) with a
different candidate pool and nothing else changed. Data: `experiment/obi_vocab_v3/`.*

The three vocabularies nest. `full` is the whole OBI assay branch. `noncompositional` removes
the 545 IEDB-style labels (*"ELISPOT assay measuring epitope specific IFN-γ production by T
cells"*). `pruned`, the live pool, also removes 548 out-of-scope domain terms (hospital
analyzer panels, entomology, electrophysiology, metrology, …).

## How the 701 were chosen: the filter chain

`data/OBI/obi.obo` (OBI release 2026-05-08) holds 5218 terms. Three steps take it to 701,
each reproducible from the OBO alone (`scripts/prune_obi_domain.py`; the first step is also
`scripts/build_obi_assay_terms.py`).

| step | keeps | removes | result |
|---|---|---|---|
| 0. assay branch | every `is_a` descendant of `OBI:0000070 assay` | 3423 non-assay terms | 1794 |
| 1. compositional labels | labels without *measuring* / *detecting* | 545 | 1249 |
| 2. out-of-scope domains | everything outside nine subtrees and the clinical-panel band | 548 | 701 |

**Step 0: keep only assays (5218 → 1794).** OBI imports terms from about thirty other
ontologies and defines many non-assay classes of its own. Dropped here: `planning`,
`study design`, `data transformation`, `specimen` (OBI process and material classes);
`insulin`, `water` (CHEBI chemicals); `uterine cervix`, `pituitary gland` (UBERON anatomy);
`primary cultured cell` (CL); `chromatin` (GO). None of these can be the answer to "which
assay did the paper run", so none should be a candidate. Four CHMO microscopy and
chromatography terms stay because OBI files them under `assay`.

**Step 1: drop the compositional labels (1794 → 1249).** The IEDB contributed hundreds of
terms that bake an analyte and a cell type into the assay name: `ELISPOT assay measuring
epitope specific interferon-gamma production by T cells`, `cytometric bead array assay
measuring epitope specific IP-10 production by T cells`, `measuring glucose concentration in
blood serum assay`. The rule is one regex, `\b(measuring|detecting)\b`, on the label. Why:
these are near-duplicates of a family term (ELISPOT, CBA, flow cytometry) and they outnumber
it (43 of the 45 ELISPOT-shaped labels are compositional), so in a top-20 retrieval they bury
the term the curators actually use. Example: SDY1669's "TLR4-based reporter assay" (readout:
plasma LPS) is curated to `OBI:0003793 bacterial lipopolysaccharide detection in plasma assay`.
In the 701 list it ranked #18 and was picked. In the 1794 list, 12 of the 20 candidates were
compositional, mostly *"cell culture analyte detection bioassay measuring epitope specific
IL-4 / TNF / IFN-γ … production by T cells"*; they sit close to "reporter assay" in embedding
space and pushed #18 off the list, so the picker fell back to #6, `reporter cell line analyte
detection bioassay`, marked BROAD. Second example: an ICS that reads IFN-γ, TNF and IL-4 at
once. Each IEDB child names one cytokine, so no child describes the assay; the lack of a more
specific term is the vocabulary's, not the picker being cautious. Since a typical vaccine
paper's ICS is multi-cytokine, the flow cytometry family (the one with the most compositional
children) will almost always stop at the family term. The A/B below measures the cost of leaving them in:
10 exact. One label is pinned back, `OBI:1110179 MHC tetramer/multimer assay measuring
binding of a T cell epitope:MHC:TCR complex`, because OBI names it as the replacement for the
retired tetramer staining term and the family has no plain term left.

**Step 2: drop out-of-scope domains (1249 → 701).** These are domains unlikely to be the answer
to "which assay did this immunology study run" that still sit close enough in embedding space to
act as decoys. The criterion is a judgement per domain, not a check that each term never appears
in a paper: tiers A and C are biomedical and clinical papers do report them, and they go because
they are not the study's assay. Nine groups, each defined by `is_a` subtree roots so it survives
an OBI release bump:

| tier | domain | example dropped | terms |
|---|---|---|---|
| A | hospital analyzer panels (`OBI:21xxxxx`, filtered by label) | `panel5 venous blood sodium assay`, `CBC with manual differential venous blood neutrophil count assay` | 333 |
| B | insecticide resistance | `insecticide resistance bioassay` | 26 |
| C | clinical examination | `coma severity assay`, `physical examination of an organism` | 51 |
| D | electrophysiology | `patch clamp assay` | 28 |
| E | nucleic-acid structure probing | `DEPC structure mapping assay`, `footprinting assay` | 61 |
| F | 3D structure determination | `NMR 3D molecular structure determination assay` | 22 |
| G | vector biology | `mosquito membrane feeding assay` | 4 |
| H | physical metrology | `temperature measurement assay`, `color detection assay` | 17 |
| I | surveys and trial designs | `handedness assay`, `Bernoulli trial` | 6 |

(Tiers overlap through multiple inheritance, so the column sums past 548.) Why: these terms
are semantic near-neighbours of ones we want and the mapper has no similarity threshold to
keep them out, so a decoy that reaches the top 20 reaches the LLM. Tier A is the only one
filtered by label rather than wholesale: the clinical band also holds plain analyte readouts a
paper does cite (`C-reactive protein assay`, `neutrophil count assay`), so only the
instrument- and panel-qualified labels go, and each one's plain sibling stays. Two families
are whitelisted back because the tier would leave them with nothing: the IgG / IgM / IgA /
IgE quantitation terms (OBI has no bare `IgG assay`), and `OBI:0000912 X-ray crystallography`.
The only empirical check on the choice is this corpus: the step removed no term any of the 31
papers was curated to, and the A/B below measures it at 1 exact (SDY1293). Rarely decisive,
never harmful here.

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
