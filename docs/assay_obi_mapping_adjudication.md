# OBI-term mapping: who is right on the 19 matched-but-not-exact rows?

Source: `benchmark_vs_stability` (benchmark v4 vs the 2026-10-19 `stability/` run). Of 149
matched rows, 130 agree on the OBI term; these are the other 19 (5 MATCH_GRANULARITY, 7
MATCH_OBI_CONFLICT, 7 MATCH_OBI_UNMAPPED). Each was judged on the OBI definitions (`obi.obo`),
the paper's own wording, and the extraction rule "never more specific than the paper is".

| # | paper | assay | curator term | agent term | verdict | why |
|---|---|---|---|---|---|---|
| 1 | SDY1260 | anti-DT IgG by Luminex | OBI:0003116 antibody detection by CBA | OBI:0000920 cytometric bead array (parent) | **agent less precise** | Antigen-coated beads capturing antibodies is exactly OBI:0003116; the picker stopped at the parent. |
| 2 | SDY1264 | immunoblot analysis | OBI:0001978 immunoblot assay | OBI:0000854 western blot (child) | both acceptable | Protein immunoblot = western blot; the child is the standard synonym. |
| 3 | SDY1289 | BD Th1/Th2 CBA | OBI:0000920 CBA (parent) | OBI:0003799 analyte detection by flow-based bead assay | **curator less precise** | Cytokine concentrations read on a flow cytometer is the child's definition. |
| 4 | SDY1655 | HD71 71-plex (Eve Technologies, Luminex) | OBI:0000920 CBA (parent) | OBI:0003115 antigen detection by CBA | **curator less precise** | Antibody-coated beads capturing cytokines is OBI:0003115. |
| 5 | SDY80 | virus-neutralizing titers | OBI:0000865 96-well neutralization ("microneutralization") | OBI:0000872 serum neutralization (parent) | **agent right by rule** | Paper never says microneutralization or 96-well — only "according to Hancock et al. 2009". The curator used knowledge of the cited method; the rule forbids upgrading beyond the paper. |
| 6 | SDY1289 | qPCR on RNA (43 genes) | OBI:0000893 real-time PCR | OBI:0000911 real-time RT-PCR | **agent over-inferred** (minor) | qPCR on RNA implies an RT step, but the paper never states one; by rule the plain term stands. |
| 7 | SDY1293 | TaqMan gene expression assays | OBI:0000911 real-time RT-PCR | OBI:0000893 real-time PCR | **agent wrong** | The paper (Results) says "confirmation by reverse-transcriptase polymerase chain reaction". The picker only sees the entry's fields, not the paper, so it missed it. |
| 8 | SDY1294 | NK-mediated ADCC assay | OBI:0000916 flow cytometry (generic) | OBI:0000882 cell-cell killing assay | **curator less precise** | OBI:0000882 is "a cytometry assay that tracks how many cells are killed by other cells" — ADCC exactly. |
| 9 | SDY1294 | immunofluorescence assay (IFA on infected BHK cells) | CHMO:0000087 fluorescence microscopy assay | OBI:0001632 immuno staining assay (generic) | **curator better** | OBI has no "immunofluorescence" term. Fluorescence-microscopy is the technique the paper names; the agent's generic parent says less. (The agent used OBI:0002174 immunocytochemistry for the same wording in SDY1264 — inconsistent.) |
| 10 | SDY1373 | 13-plex Bio-Plex cytokines | OBI:0002970 multiplex bead-based **protein state** immunoassay | OBI:0000920 CBA | **curator wrong** | OBI:0002970 is for phospho-/protein-state readouts; cytokine concentrations are an analyte assay (0000920, or 0003799 more specifically). |
| 11 | SDY1373 | RNA-seq | OBI:0002571 polyA-selected RNA-seq | OBI:0003090 bulk RNA-seq | **curator better**, agent acceptable | Paper states NEBNext poly(A) mRNA isolation, so the specific term is supported; bulk RNA-seq is true but says less. |
| 12 | SDY984 | plasma metabolomics (RP-LC, Q Exactive) | OBI:0003097 LC-MS assay | OBI:0003782 metabolomics by MS assay | both defensible | Sibling branches of mass spectrometry assay: one names the instrument chain, the other the purpose. Ontology ambiguity, not an error. |
| 13 | SDY1260 | SBA | *(none)* | OBI:0003797 bacterial neutralization assay | **curator should map** | OBI has no "bactericidal" term; bacterial neutralization is the closest parent. |
| 14 | SDY1325 | human complement SBA | *(none)* | OBI:0003797 bacterial neutralization assay | **curator should map** | Same as 13. |
| 15 | SDY1264 | Immunofluorescence | *(none)* | OBI:0002174 immunocytochemistry | **curator should map** | Reasonable term; a row with no id can never score exact. |
| 16 | SDY1328 | RBM Human InflammationMAP (multiplex "ELISA") | OBI:0000920 CBA | *(unresolved)* | **agent's fault** | RBM's platform is Luminex xMAP; the picker abstained although the parent term exists. |
| 17 | SDY1328 | complete blood count | OBI:0000630 hematology assay | *(unresolved)* | **agent's fault** | The parent is in the vocabulary; the picker abstained. |
| 18 | SDY1596 | colony-forming units | *(none)* | *(unresolved)* | ontology gap | OBI has no colony-forming / CFU term. |
| 19 | SDY1640 | lateral-flow serology | *(none)* | *(unresolved)* | ontology gap | OBI has no lateral-flow / immunochromatographic term. |

## Tally
- **Agent at fault or less precise: 6** (rows 1, 6, 7, 9, 16, 17).
- **Curator at fault or less precise: 8** (rows 3, 4, 5, 8, 10, 13, 14, 15).
- **Both defensible / ontology gap: 5** (rows 2, 11, 12, 18, 19).

## Agent-side patterns (what to fix in the mapper)
1. **Abstains when a correct parent exists** — rows 16, 17. The picker's "none" should be
   reserved for *no term in the family at all*; a vocabulary parent (hematology assay, CBA) is
   the right answer when nothing narrower applies.
2. **Stops at the parent when the child applies** — row 1 (antibody detection by CBA).
3. **RT inference is inconsistent** — infers RT where the paper is silent (row 6) and misses it
   where the paper states it outside the entry's quote (row 7). The picker sees only the entry
   record, never the paper; a `reverse transcription` cue would have to be captured at
   extraction time (readouts / aliases) to be visible.
4. **Generic immuno-staining term for microscopy assays** — row 9; and the same wording mapped
   differently in two papers (rows 9 vs 15).

## Curator-side patterns (what to fix in the benchmark)
1. **24 rows have no OBI id** (3 of them appear here: both SBAs, one immunofluorescence); none
   can ever score exact.
2. **Generic parent where a specific child exists** — rows 3, 4, 8.
3. **Wrong branch** — row 10 (protein-state immunoassay for cytokine concentrations).
4. **More specific than the paper** — row 5 (96-well/microneutralization from the cited method).

## Ontology gaps (neither side can fix)
Lateral-flow immunoassay, colony-forming-unit assay, serum bactericidal assay, and a plain
immunofluorescence assay have no OBI term; intracellular cytokine staining's specific term is
among the compositional terms pruned from the working vocabulary (see earlier adjudication).
