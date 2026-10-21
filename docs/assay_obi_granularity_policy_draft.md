# OBI assay-term granularity policy — draft for curator review

*Draft 1, 2026-10-19. Prepared from the benchmark v4 comparison (`data/benchmark_assay/comparison/
benchmark_vs_stability.json`) and the OBI release 2026-05-08 vocabulary the pipeline searches
(`data/OBI/obi_generic_index.json`, 701 terms). This is a proposal: where you disagree with a row,
the table should change, not your annotation.*

## Why this document exists

The pipeline and the curated benchmark agree on the OBI term for 130 of 144 matched assays. Of
the 14 disagreements, 10 are about **depth**: both sides chose a term in the right family, one
picked the parent and the other a child. The pipeline currently leans more specific than the
curators (in 7 of those rows it chose a descendant or sibling of the curator's term; in 3 the
curator's term was the more specific one). Neither side is wrong by any written rule, because
there is none. This document proposes one, so that benchmark v5 and the pipeline encode the same
answer and future disagreements are about facts in the paper, not about depth.

## 1. The principle

> **Choose the most specific OBI term whose defining feature the paper states in its methods.
> Infer nothing from sample type, vendor or field convention alone. When the paper does not state
> the feature that separates a child from its parent, stay on the parent, and a parent chosen for
> that reason is correct, not "too broad".**

Corollaries:

- A **method variant** (PRNT vs FRNT vs microneutralization) is recorded in `aliases`, not by
  forcing a term OBI does not have.
- A **readout** decides between siblings only when the paper reports it (antibodies vs analytes;
  function vs phenotype).
- A **vendor or kit name** is evidence for what the kit is (Luminex is a bead array) but not for a
  child term beyond that.

## 2. Family table

| family | default term | go one level deeper only when the paper says… | never |
|---|---|---|---|
| **PCR** | `real time polymerase chain reaction assay` OBI:0000893 | cDNA, reverse transcription, RT-qPCR, or RNA as the template → `real time reverse-transcription PCR` OBI:0000911 | infer RT because the sample is RNA-rich |
| **RNA sequencing** | `RNA-seq assay` OBI:0001271 | bulk, whole blood, PAXgene, tissue, sorted or pooled cells with no single-cell barcoding → `bulk RNA-seq assay` OBI:0003090; 10x, Drop-seq, Seq-Well, scRNA → `single-cell RNA sequencing assay` OBI:0002631; polyA selection or rRNA depletion named as the library prep → OBI:0002571 / OBI:0002572 | choose the grandparent `RNA sequencing assay` OBI:0001177 when "RNA-seq" is written |
| **Bead multiplex** | `cytometric bead array assay` OBI:0000920 for a panel of analyte concentrations (Luminex, xMAP, Bio-Plex, Milliplex, "multiplex ELISA") | readouts are antibodies / serology → `antibody detection by cytometric bead array assay` OBI:0003116; beads acquired on a flow cytometer (BD CBA, LEGENDplex) → `analyte detection by flow based bead assay` OBI:0003799; Olink → `Olink assay` OBI:0003112; MSD / ECL → `electrochemiluminescence assay` OBI:0003780 | `antigen detection by CBA` OBI:0003115 for a cytokine panel (every cytokine panel detects antigens; the child adds nothing); `multiplex bead-based protein state immunoassay` OBI:0002970 for concentrations (it is for phosphorylation / modification state) |
| **Neutralization** | `serum neutralization of viral infectivity assay` OBI:0000872 | OBI has no term for PRNT, FRNT, microneutralization or CPE-based neutralization → stay on the parent and keep the method in `aliases`; `viral plaque assay` OBI:0003798 only when plaques are the readout and no neutralization is measured | `96-well neutralization assay` OBI:0000865 unless the paper names the 96-well format as the assay itself |
| **Flow cytometry** | `flow cytometry assay` OBI:0000916 for phenotyping and cell-subset frequencies | a function is measured after stimulation → the functional term: `cell proliferation assay` OBI:0000891, `T cell activation induced marker assay` OBI:0003230, MHC tetramer OBI:1110179, `cell-cell killing assay` OBI:0000882 for ADCC / cytotoxicity; intracellular cytokine staining → `flow cytometry assay` (OBI's ICS term is obsolete), recorded BROAD | fold a functional assay into the paper's phenotyping panel; call CyTOF `flow cytometry assay` (it is OBI:0002115) |
| **Blotting** | `western blot assay` OBI:0000854 when proteins are gel-separated and transferred | dot blot, slot blot, or no electrophoresis → `immunoblot assay` OBI:0001978 | treat the two as interchangeable |
| **Fluorescence imaging** | `immuno staining assay` OBI:0001632 | the readout is read under a microscope (IFA titres, slide-based serology) → `fluorescence microscopy assay` CHMO:0000087 | |
| **Mass spectrometry** | `liquid chromatography mass spectrometry assay` OBI:0003097 | the stated aim is the metabolome or proteome → `metabolomics by mass spectrometry assay` OBI:0003782 / `proteomics by mass spectrometry assay` OBI:0003781 | |
| **Arrays** | `transcription profiling by array assay` OBI:0001463 for expression | array content named → `genotyping by SNP array assay` OBI:0002031, `DNA methylation profiling by array assay` OBI:0001332, `microRNA profiling by array assay` OBI:0001335, `proteomic profiling by array assay` OBI:0001318; content unknown → `microarray assay` OBI:0001985 | any sequencing term for an array |
| **Counts** | `hematology assay` OBI:0000630 for a CBC / differential panel | one analyte reported → its count assay (e.g. `leukocyte count assay` OBI:2100013) | |
| **Plate immunoassays** | `enzyme-linked immunosorbent assay` OBI:0000661 for one analyte per well; `enzyme-linked immunospot assay` OBI:0600031 for spot counts | — | call a multiplex bead panel ELISA because the paper does |

## 3. Open questions for you

These are the rows where the pipeline's current rules and benchmark v4 disagree outright. Your
answer changes the table above.

1. **BD CBA kits.** Parent `cytometric bead array assay`, or the flow-based child
   `analyte detection by flow based bead assay` because the beads are read on a cytometer? (v4
   has the parent; the pipeline picks the child.)
2. **Cytokine concentration panels.** Can they ever be `multiplex bead-based protein state
   immunoassay`? (v4 says yes once, SDY1373; the draft says never.)
3. **ADCC read by flow.** `cell-cell killing assay` (what is measured) or `flow cytometry assay`
   (how it is read)? (v4: flow; pipeline: killing.)
4. **PRNT / FRNT / CPE neutralization.** Stay on `serum neutralization of viral infectivity
   assay`, or do you want a method-level term proposed to OBI? (v4 used `96-well neutralization
   assay` once, SDY80.)
5. **qPCR on cDNA.** Is "quantitative real-time PCR" of reverse-transcribed RNA
   `real time RT-PCR` (pipeline) or `real time PCR` (v4, SDY1289)? And the reverse case
   SDY1293, where v4 chose RT-PCR and the pipeline plain real-time PCR.
6. **Immunoblot vs western blot** (SDY1264): is "immunoblot analysis" with SDS-PAGE a western blot?
7. **Library-prep children of RNA-seq** (polyA-selected, SDY1373): do you want library prep to
   decide the term, or stay at bulk / single-cell?

## 4. Review sheet — the 14 disputed rows

| study | paper wording | curator's term (v4) | pipeline's term | relation | table row that decides |
|---|---|---|---|---|---|
| SDY1260 | anti-Diphtheria IgG by Luminex | antibody detection by cytometric bead array assay | cytometric bead array assay | curator more specific | bead multiplex: serology → antibody-detection child. **Draft agrees with curator.** |
| SDY1264 | immunoblot analysis | immunoblot assay | western blot assay | pipeline more specific | blotting; open question 6 |
| SDY1289 | qPCR | real time polymerase chain reaction assay | real time reverse-transcription PCR | siblings | PCR; open question 5 |
| SDY1289 | BD Th1/Th2 CBA array | cytometric bead array assay | analyte detection by flow based bead assay | pipeline more specific | bead multiplex; open question 1 |
| SDY1293 | Real-time polymerase chain reaction | real time reverse-transcription PCR | real time polymerase chain reaction assay | siblings | PCR; open question 5 |
| SDY1294 | NK-mediated ADCC assay | flow cytometry assay | cell-cell killing assay | different families | flow; open question 3 |
| SDY1294 | Immunofluorescence assay to detect anti-JEV / anti-WNV antibodies | fluorescence microscopy assay | immuno staining assay | siblings | fluorescence imaging. **Draft agrees with curator.** |
| SDY1328 | multiplex ELISA protocol, Human Inflammation multi-analyte | cytometric bead array assay | unmapped | — | bead multiplex: "multiplex ELISA" is a bead panel. **Draft agrees with curator**; pipeline miss |
| SDY1328 | complete blood count | hematology assay | unmapped | — | counts. **Draft agrees with curator**; pipeline miss |
| SDY1373 | Cytokine and Chemokine Multiplex Analysis | multiplex bead-based protein state immunoassay | cytometric bead array assay | siblings | bead multiplex; open question 2. **Draft agrees with pipeline** |
| SDY1373 | Next-Generation RNA Sequencing | polyA-selected RNA sequencing assay | bulk RNA-seq assay | curator more specific | RNA sequencing; open question 7 |
| SDY1655 | Human Cytokine Array / Chemokine Array 71–403 Plex | cytometric bead array assay | antigen detection by cytometric bead array assay | pipeline more specific | bead multiplex: never the antigen-detection child. **Draft agrees with curator** |
| SDY80 | Virus-neutralizing titers | 96-well neutralization assay | serum neutralization of viral infectivity assay | curator more specific | neutralization; open question 4. **Draft agrees with pipeline** |
| SDY984 | Plasma Metabolomics analysis | liquid chromatography mass spectrometry assay | metabolomics by mass spectrometry assay | pipeline more specific | mass spectrometry. **Draft agrees with pipeline** |

Five further matched rows have no curated term in v4 (left blank); they are not disputes.

## 5. How the pipeline will use the agreed policy

1. **Benchmark v5.** The 14 rows above are relabelled to the table; the comparison then scores
   depth against a shared rule instead of against one curator's choice.
2. **Picker prompt.** Rules 2, 5, 8, 9 and 10 of `apps/api/app/prompts/resolver_obi_assay.txt`
   collapse into a policy block generated from section 2, so the prompt and the benchmark
   cannot drift apart.
3. **Free adherence check.** After each pick, if the chosen term is in a family row and none of
   the required evidence words appears in the entry's name, aliases, readouts or quote, the entry
   is printed as `REVIEW granularity` and the reason is recorded in `assays_OBI.json`. No model
   call.
4. **Scoring.** A `MATCH_GRANULARITY` row that follows the table counts as a match; one that
   contradicts it counts as a miss. Today it is reported as a separate status with no verdict.

## 6. Things this policy does not decide

- Which assays a paper performed (extraction) or whether two write-ups are one assay (round 5).
- Terms OBI lacks: intracellular cytokine staining (obsolete in OBI), PRNT / FRNT, colony-count
  and cytokine-capture assays. Those are vocabulary gaps to raise with OBI, recorded as BROAD or
  UNMAPPED until then.
