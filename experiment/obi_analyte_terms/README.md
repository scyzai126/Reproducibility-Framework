# Analyte-level OBI terms: can the pipeline use the 545 compositional terms it prunes?

*Experiment folder. Nothing here is on the serving path; the production mapper, the live
vocabulary (`data/OBI/obi_assay_pruned_index.json`, 701 terms) and its vectors are unchanged.*

## Question

The live OBI vocabulary is the 1794-term assay branch of `obi.obo` minus 545 IEDB-style
compositional labels ("ELISPOT assay measuring epitope specific IFN-gamma production by
T cells") and 548 out-of-scope domain terms (`data/OBI/README.md`). Those compositional terms
carry more detail than the family terms we map to. Two ways to get them back were tried on one
paper, SDY2189 (PMID 34252919, BNT162b2 systems vaccinology), against the mapping the pipeline
produces today:

| arm | what it does | cost on SDY2189 |
|---|---|---|
| **current (701, embedding)** | today's round 4: retrieve top-20 by embedding from the 701 terms, LLM picks | already on disk (`data/31paper_assays/stability/34252919_SDY2189/assays_OBI.json`) |
| **arm 1, 1794 flat** | the same mapper, unchanged, over all 1794 terms with their own vectors | 1093 rows embedded once; 24 calls |
| **arm 2, 701 hierarchical** | keep today's family pick; one judge call asks whether the record earns one of that family's compositional children | 2 calls |

## Layout

```
exp_obi_flat1794.py          arm 1: build-index | build-embeddings | map <registry_dir>
exp_obi_hierarchical.py      arm 2: <registry_dir> [--dry-run]
prompts/hierarchical_pick.txt       arm 2 judge prompt
tests/                       25 tests, run with ./.venv/bin/pytest experiment/obi_analyte_terms/tests
results/flat1794/<registry>/        arm 1 output: assays_OBI.json + raw.json (every candidate list and reply)
results/hierarchical/<registry>/    arm 2 output: hierarchical.json + raw.json (prompt, children, reply)
```

The 1794-term index and vectors live beside the pruned ones in `data/OBI/` (`obi_assay_full_index.json`, `obi_assay_full_embeddings.json`
; the vectors are 73 MB, `text-embedding-3-small`, `label | synonyms | definition` like the live file; the 701 live
rows were reused, 1093 were embedded). Only `exp_obi_flat1794.py` reads that file.

Arm 1 never edits the mapper: for the duration of a run it patches
`assay_obi_mapper._is_generic_assay_term` (the load-time filter that would otherwise prune the
1794 back to the 701 whatever terms file is passed) and `_EMBEDDINGS_PATH`, clears the lru caches,
and restores both after. Arm 2 computes each live term's compositional descendants from
`obi.obo` (walking `is_a` up through pruned nodes to the first live ancestor; 545 terms under 53
families) and gates in code before paying: `NO CHILDREN`, `TOO MANY` (> 60 children: the
epitope-assay umbrellas), `NO EVIDENCE` (no readouts and no sample type), `NO FAMILY`.

## SDY2189: the three mappings side by side

Curator = benchmark v4 (`data/benchmark_assay/benchmark_assay_v4/SDY2189_assays_AS_v2.json`).

| entry (paper wording) | current, 701 | arm 1, 1794 flat | arm 2, hierarchical | curator |
|---|---|---|---|---|
| Anti-spike binding ELISA | OBI:0000661 ELISA (EXACT) | OBI:0000661 ELISA (EXACT) — same | **OBI:0001657 ELISA measuring binding of a B cell epitope:antibody complex** | OBI:0000661 |
| Focus reduction neutralization titre assay | OBI:0000872 serum neutralization of viral infectivity (BROAD) | same | no children | OBI:0000872 |
| Intracellular cytokine staining assay | OBI:0000916 flow cytometry (BROAD) | same | **keep** OBI:0000916 | OBI:0000916 |
| Bead-based antigen arrays | OBI:0003116 antibody detection by CBA (EXACT) | same | no children | OBI:0003116 |
| CyTOF | OBI:0002115 (EXACT) | same | no children | OBI:0002115 |
| Olink panel | OBI:0003112 (EXACT) | same | no children | OBI:0003112 |
| Bulk transcriptomics | OBI:0003090 bulk RNA-seq (EXACT) | same | no children | OBI:0003090 |
| CITE-seq | OBI:0003788 (exact name) | same | no children | OBI:0003788 |
| RNA isolation and qPCR | OBI:0000911 RT-qPCR (EXACT) | same | no children | OBI:0000911 |

Granularity in parentheses is the picker's own EXACT/BROAD. The curator's tenth row
(Single-molecule array, no OBI id) has no counterpart in our registry and is out of scope here.

### Arm 1: what the flat 1794 picker saw and did

All nine entries landed on the same term as the 701 run. The compositional terms *were* in the
lists; the picker declined every one of them (`results/flat1794/34252919_SDY2189/raw.json`):

| entry | candidates shown | of which compositional | reply |
|---|---|---|---|
| Anti-spike ELISA | 24 | 14 | `1 exact` (ELISA) |
| Bead-based antigen arrays | 21 | 12 | `2 exact` (antibody detection by CBA) |
| FRNT | 23 | 6 | `1 broad` |
| ICS | 23 | **18** | `1 broad` (flow cytometry) |
| CyTOF | 29 | 0 | `7 exact` |
| Olink | 22 | 2 | `2 exact` |
| bulk RNA-seq | 24 | 0 | `1 exact` |
| RT-qPCR | 20 | 0 | `1 exact` |

The ICS list is the pre-prune failure mode in full: ranks 2 to 15 were fourteen "intracellular
cytokine staining assay measuring epitope specific *X* production by T cells" terms, one per
cytokine, with the family term at rank 1. In the 30-paper run that motivated the prune, that
shape produced wrong picks; here the picker, now shown definitions and the record's readouts
("antigen-specific T cell intracellular cytokine responses after spike peptide stimulation",
naming no cytokine), stayed on the family term. The ELISA list had rank 3 and rank 7 as
"ELISPOT / ELISA measuring binding of a B cell epitope:antibody complex" and the picker still
took ELISA.

So on this paper the flat arm neither gains nor loses anything. It does cost: the 1794 lists are
longer (20 to 29 lines), 14 to 18 of them decoys on the immunoassay entries, and the retrieval
slots they occupy are slots a correct sibling cannot have. The one benchmark row the prune is
known to cost (OBI:1110207 for an ICS entry in SDY1630) is not in this paper, so this run cannot
show the flat arm winning it back.

### Arm 2: the two judge calls, verbatim

**Anti-spike ELISA** → child chosen.
> `OBI:0001657 ELISA measuring binding of a B cell epitope:antibody complex | the assay detects
> serum antibodies binding immobilized spike antigen, matching an ELISA measuring binding of a B
> cell epitope:antibody complex.`

**ICS** → kept.
> `keep | the record supports peptide-stimulated antigen-specific T cell intracellular cytokine
> responses by flow cytometry, but it does not name any single cytokine analyte, so no
> analyte-specific child is justified.`

### Verdicts against the paper

- **ICS, keep — correct.** The paper's readouts are IFNγ, TNF and IL-4 across CD4 and CD8 T
  cells after spike peptide-pool stimulation (Results; Methods "Intracellular cytokine staining
  assay"). Each compositional child names one cytokine. No single child represents the assay,
  and the record's readouts field does not name the cytokines anyway. The judge's rule 1 (one
  analyte) did what it was written to do. Note what this means for the scheme: the ICS in a
  typical vaccine paper is multi-cytokine by design, so this family, the one with the most
  compositional children (48), will keep the family term nearly every time.
- **ELISA, OBI:0001657 — over-specific; the family term should have stayed.** The term's own
  definition is thin ("An ELISA that detects the binding of an antigen with an antibody"), and
  on that definition alone any antigen-binding ELISA qualifies. But the term sits under
  `B cell epitope assay` ("characterizes the structure of an antibody-epitope complex, or
  measures the binding of an antibody receptor to epitope") and its label says *B cell epitope*.
  The paper coats plates with whole recombinant spike protein and reads EC50 of serum IgG
  (Methods "Anti-spike binding enzyme-linked immunosorbent assay"): an antigen-binding titre,
  not an epitope-binding measurement. The pipeline's rule is "never more specific than the paper
  is"; this pick asserts an epitope the paper never defines. The judge followed the definition
  text literally, which is the failure mode the compositional terms invite: their definitions
  are weaker than their labels and their position in the ontology. The curator's term is the
  family term.

Arm 2 therefore went 1 for 2 on the entries it judged: one correct abstention, one incorrect
descent. Seven of nine entries never reached the judge because their family has no
compositional child in OBI at all (FRNT, antibody detection by CBA, CyTOF, Olink, bulk RNA-seq,
CITE-seq, RT-qPCR): the compositional vocabulary only exists where IEDB curated it.

## SDY1264: the three mappings side by side

Second paper (PMID 19029902, YF-17D systems vaccinology; registry
`data/31paper_assays/stability/19029902_SDY1264`, 9 entries). Curator = benchmark v4
`SDY1264_Assay_Hailong.json` (8 rows; the curator left ELISA and Immunofluorescence without an
OBI id). Cost: 26 calls for arm 1, 2 calls for arm 2.

| entry (paper wording) | current, 701 | arm 1, 1794 flat | arm 2, hierarchical | curator |
|---|---|---|---|---|
| Multiplex analysis (Luminex, 24 cytokines) | OBI:0000920 CBA (EXACT) | same | no children | OBI:0000920 |
| Flow cytometric analysis | OBI:0000916 flow cytometry (EXACT) | same | **keep** OBI:0000916 | OBI:0000916 |
| neutralizing antibodies by cytopathic effect | OBI:0000872 serum neutralization (EXACT) | same | no children | OBI:0000872 |
| plaque reduction neutralization test | OBI:0000872 (BROAD) | same | no children | OBI:0000872 |
| microarray | OBI:0001463 transcription profiling by array (EXACT) | same | no children | OBI:0001463 |
| RT-PCR | OBI:0000911 real time RT-PCR (EXACT) | **OBI:0001170 reverse transcription PCR assay (EXACT)** | no children | OBI:0000911 |
| Immunofluorescence | OBI:0002174 immunocytochemistry (EXACT) | same | no children | *(blank)* |
| immunoblot analysis | OBI:0000854 western blot (EXACT) | same | no children | OBI:0001978 immunoblot assay |
| ELISA (plasma C3a) | OBI:0000661 ELISA | same | **keep** OBI:0000661 | *(blank)* |

### Arm 1: what the flat 1794 picker saw and did

| entry | candidates shown | of which compositional | reply |
|---|---|---|---|
| Flow cytometric analysis | 21 | 3 | `1 exact` |
| Multiplex analysis | 22 | 4 | `4 exact` |
| PRNT | 21 | 6 | `6 broad` |
| neutralizing antibodies by CPE | 22 | 11 | `3 exact` |
| microarray | 26 | 3 | `10 exact` |
| RT-PCR | 20 | 0 | `1 exact` |
| immunoblot analysis | 22 | 11 | `2 exact` |
| Immunofluorescence | 22 | 0 | `10 exact` |
| ELISA | **59** | **50** | `1 exact` |

Two things stand out (`results/flat1794/19029902_SDY1264/raw.json`):

- **ELISA: the exact-hit pin became a 59-line list.** The paper's wording is the bare "ELISA",
  which is an exact label hit. On the 701 index that term has no children and the hit answers
  for free. On the 1794 index it has 53 compositional children, so the mapper pinned the hit
  plus all of them (50 after de-duplication against the retrieved pool) ahead of the 20
  retrieved candidates. The picker still chose ELISA. The free match became a three-call pick
  with 50 decoys, for the same answer.
- **RT-PCR: the only term that changed, and it changed for the worse.** The 1794 list for this
  entry contained **no** compositional term at all, and its top eight were identical to the 701
  run's (reverse transcription PCR first, real-time RT-PCR second). The 701 picker answered
  `2 exact`; the 1794 picker answered `1 exact`. The paper says "Two-step RT-PCR was performed
  ... normalized to the average cycling threshold value" on a TaqMan plate, which is real-time
  RT-PCR, the curator's term and the 701 pick. The tail of the list differed (the 1794 pool
  brought in domain-pruned terms such as `RNASE T2 structure mapping assay`), and that was
  enough to move a seeded, temperature-0 pick between two adjacent siblings. This is not a
  compositional-term effect; it is the picker's run-to-run variance, which the mapper's
  docstring already records as the largest source of change between runs. It counts against
  the flat arm all the same: a larger pool means a different list, and a different list means a
  different coin.

### Arm 2: the two judge calls, verbatim

**Flow cytometric analysis** → kept.
> `keep | the assay measures surface-marker frequencies (CD86, CD38, HLA-DR on monocytes,
> dendritic cells, and T cells) ex vivo, not a single named analyte produced by T cells in an
> epitope-specific stimulation assay.`

**ELISA (C3a)** → kept.
> `keep | the assay measures C3a concentration in plasma, and no candidate child matches C3a or
> supports epitope-specific T-cell production/release.`

### Verdicts against the paper

- **Flow, keep — correct.** Phenotyping (CD86 on monocytes and DCs, CD38/HLA-DR on CD8 T cells),
  no stimulation, no cytokine. All 48 children are ICS constructs; none applies.
- **ELISA, keep — correct.** "C3a in plasma was measured by ELISA (Quidel A015)": one analyte,
  but a complement fragment in plasma, not a T-cell product and not an epitope. The judge's rule
  2 (responder) held here where rule 3 (epitope framing) did not hold on SDY2189's spike ELISA.
  Note the asymmetry: the ELISA family's 53 children include no plain "ELISA measuring C3a", so
  there was nothing to descend to. Had OBI carried one, the SDY2189 behaviour suggests the judge
  would have taken it on the definition alone.

Arm 2 went 2 for 2 on SDY1264. Arm 1 went 8 for 9, and its one miss was not a
compositional-term pick.

## What the two papers show

Across SDY2189 and SDY1264, 18 entries, 4 judge calls, 50 picker calls over the 1794 terms:

| | arm 1, 1794 flat | arm 2, 701 hierarchical |
|---|---|---|
| entries changed vs the 701 run | 1 of 18 (SDY1264 RT-PCR, to a *less* specific sibling; not compositional) | 1 of 18 (SDY2189 spike ELISA, to a compositional child) |
| changes that were right | 0 | 0 |
| compositional terms chosen | 0 | 1 |
| decoys per immunoassay list | 12 to 18; 50 when the bare technique word is an exact hit | none shown until the judge |
| extra cost | every entry becomes a 2 to 3 call pick; a childless exact hit stops being free | 1 call on entries whose family has children: 4 of 18 |

1. **The flat 1794 arm never chose a compositional term and never improved a mapping.** On
   both papers the picker, shown definitions and readouts, rejected every analyte-specific
   decoy, including the pre-prune failure shape (14 ICS children ranked 2 to 15 on SDY2189).
   Its one change was a wrong sibling flip on a list with no compositional term in it, which
   the larger pool caused by changing the list's tail. And it removes the free exact match:
   "ELISA" went from a zero-call hit to a 59-line pick.
2. **The hierarchical arm is cheap and mostly abstains, and its one descent was wrong.** Four
   judge calls, three correct `keep`s (ICS, phenotyping flow, C3a ELISA), one over-specific
   descent (spike ELISA to "B cell epitope:antibody complex"). The failure is structural rather
   than a prompt bug: the compositional terms' OBO definitions are weaker than their labels and
   their place in the ontology, and a judge that reads definitions, as the pipeline tells it to,
   will take a term whose definition any antigen ELISA satisfies.
3. **Where the compositional terms could apply, the records do not earn them.** Of the 545, 367
   sit under `T cell epitope assay` and 94 under `B cell epitope assay`; the technique families
   that reach the judge (ELISA 53, flow 48, ELISPOT 43, antigen detection by CBA 47) are
   single-analyte, epitope-specific, T-cell-production constructs. The assays in these two
   vaccine papers are multi-cytokine (ICS), phenotyping (flow), whole-antigen (spike ELISA) or
   non-immune-analyte (C3a ELISA). 14 of 18 entries have no compositional child at all.
4. **Round 5 would need a side field.** The pipeline keys and folds entries by OBI term; an
   analyte-level term cannot be the key without breaking the fold of two wordings of one assay.

**Recommendation:** keep the 701 vocabulary as the mapping target, and do not add the
hierarchical judge to the mapper. Across two papers neither arm produced a term the curator
would score as a match that the current run does not already produce; arm 1 cost one correct
term and the free exact-match path, arm 2 produced one over-specific term. Analyte-level detail
stays in `readouts`, where it already is. SDY984 (two ELISPOTs including a three-cytokine one;
dry-run 32 + 4 calls) remains set up if a third paper is wanted.
