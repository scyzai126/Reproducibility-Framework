# Assay extraction vs. curated benchmark

27 papers · 137 benchmark assays · 152 extracted assays

The benchmark is a **recall reference, not an exhaustive list** — on some papers it records one assay where the paper describes nine. Recall is therefore the headline metric and no precision figure is given; our unmatched assays are listed as EXTRA with their paper evidence to be judged individually.

## Totals

| Study | PMID | Benchmark | Ours | Matched | Missed | Extra | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| SDY1260 | 24336226 | 6 | 6 | 6 | 0 | 0 | 100% |
| SDY1264 | 19029902 | 8 | 9 | 8 | 0 | 0 | 100% |
| SDY1288 | 30150281 | 7 | 6 | 7 | 0 | 0 | 100% |
| SDY1289 | 19047440 | 7 | 9 | 7 | 0 | 0 | 100% |
| SDY1291 | 23151505 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1293 | 20078211 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY1294 | 28687661 | 5 | 6 | 5 | 0 | 0 | 100% |
| SDY1325 | 28137280 | 5 | 5 | 5 | 0 | 0 | 100% |
| SDY1328 | 26742691 | 5 | 6 | 5 | 0 | 1 | 100% |
| SDY1373 | 28854372 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1389 | 30111633 | 6 | 6 | 6 | 0 | 0 | 100% |
| SDY1393 | 36656789 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY1596 | 32005538 | 3 | 5 | 2 | 1 | 2 | 67% |
| SDY1630 | 32059780 | 3 | 4 | 3 | 0 | 0 | 100% |
| SDY1640 | 32473127 | 6 | 6 | 6 | 0 | 0 | 100% |
| SDY1654 | 31624246 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1655 | 32717743 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1669 | 32788292 | 3 | 8 | 3 | 0 | 6 | 100% |
| SDY1708 | 34128959 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY180 | 23601689 | 6 | 6 | 6 | 0 | 0 | 100% |
| SDY1991 | 35455361 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1995 | 35062294 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY212 | 25834109 | 8 | 9 | 8 | 0 | 0 | 100% |
| SDY2189 | 34252919 | 10 | 10 | 9 | 1 | 0 | 90% |
| SDY404 | 25367297 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY80 | 24725414 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY984 | 28502771 | 9 | 11 | 9 | 0 | 2 | 100% |
| **All** | | **137** | **152** | **135** | **2** | **11** | **99%** |

## Status legend

| Status | Meaning |
|---|---|
| MATCH | paired on the same OBI term |
| MATCH_GRANULARITY | paired through the OBI is_a hierarchy — same assay, different specificity |
| MATCH_OBI_CONFLICT | paired by name, but the two sides carry disagreeing OBI terms |
| MATCH_OBI_UNMAPPED | paired by name, but one side carries no OBI term at all |
| SPLIT | one benchmark assay matched several of our entries |
| MISSED | benchmark assay we did not find |
| EXTRA | assay we found that the benchmark does not list |

---

## SDY1260 (24336226) — 6 benchmark / 6 ours

`data/benchmark_agent_assays/assay_result_v3/24336226_SDY1260/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Luminex` | `cytometric bead array assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `ELISpot` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `SBA` | `bacterial neutralization assay` | name | **MATCH_OBI_UNMAPPED** |
| `microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MATCH_OBI_UNMAPPED — `SBA`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `bacterial neutralization assay` — source: methods | section: Measurement of serum bactericidal titers (SBA) | sentences: S298
  > Continuous titers were determined by interpolation of the serum dilution yielding 50% killing as compared to the T 60 growth control plate average.


---

## SDY1264 (19029902) — 8 benchmark / 9 ours

`data/benchmark_agent_assays/assay_result_v3/19029902_SDY1264/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `Luminex assay` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `Flow cytometric analysis` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Assay for yellow fever virus (YFV) neutralizing antibodies` | `serum neutralization of viral infectivity assay`, `serum neutralization of viral infectivity assay (2)` | obi_exact | **SPLIT** |
| `RT-PCR` | `reverse transcription polymerase chain reaction assay` | name | **MATCH_OBI_CONFLICT** |
| `immunoblot assay` | `western blot assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Immunofluorescence` | `fluorescence microscopy assay` | name | **MATCH_OBI_UNMAPPED** |

### Conflicts (3)

**SPLIT — `Assay for yellow fever virus (YFV) neutralizing antibodies`**  
one benchmark assay matched 2 of our entries: `serum neutralization of viral infectivity assay`, `serum neutralization of viral infectivity assay (2)`

- `serum neutralization of viral infectivity assay` — source: methods | section: Assay for yellow fever virus (YFV) neutralizing antibodies | sentences: S180
  > In brief, for neutralizing antibodies by CPE, plasma dilutions in triplicate were incubated with 1,000 plaque-forming units of YFV at 37 °C for 1 h in 96-well flat-bottomed plates.
- `serum neutralization of viral infectivity assay (2)` — source: methods | section: Assay for yellow fever virus (YFV) neutralizing antibodies | sentences: S183
  > For the PRNT, various dilutions of the sera were incubated overnight at 4 °C with 200 plaque-forming units of YFV.

**MATCH_OBI_CONFLICT — `RT-PCR`**  
benchmark maps this assay to OBI:0000911 real time reverse-transcription polymerase chain reaction assay; we mapped it to OBI:0001170 reverse transcription polymerase chain reaction assay

- `reverse transcription polymerase chain reaction assay` — source: methods | section: RNA isolation and microarray and RT-PCR data generation | sentences: S197
  > Two-step RT-PCR was performed.

**MATCH_OBI_UNMAPPED — `Immunofluorescence`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `fluorescence microscopy assay` — source: methods | section: Data analysis | sentences: S213
  > Immunofluorescence signal was detected using a LSM510 confocal microscope (Zeiss), and images were captured and analyzed using the Zeiss LSM Image Browser.


---

## SDY1288 (30150281) — 7 benchmark / 6 ours

`data/benchmark_agent_assays/assay_result_v3/30150281_SDY1288/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `mass cytometry (CyTOF)` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `multiplex ELISA-based assay (Luminex)` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `RNA-seq` | `bulk RNA-seq assay` | obi_exact | **MATCH** |
| `real-time RT–PCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |
| `Inhibition ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `IgM_capture_ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `virus_isolation` | `infectious agent detection assay` | obi_exact | **MATCH** |

---

## SDY1289 (19047440) — 7 benchmark / 9 ours

`data/benchmark_agent_assays/assay_result_v3/19047440_SDY1289/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `gene array` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `quantitative real-time PCR (qPCR)` | `real time reverse-transcription polymerase chain reaction assay` | name | **MATCH_OBI_CONFLICT** |
| `IL-1β ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `flow cytometry (Ki67 proliferation assay)` | `flow cytometry assay`, `flow cytometry assay (2)`, `flow cytometry assay (3)` | obi_exact | **SPLIT** |
| `CFSE labeling` | `cell proliferation assay using carboxyfluorescein succinimidyl ester staining` | name | **MATCH_OBI_CONFLICT** |
| `cytometric bead assay (CBA)` | `analyte detection by flow based bead assay` | obi_exact | **MATCH** |
| `multiplex cytokine analysis` | `cytometric bead array assay` | obi_exact | **MATCH** |

### Conflicts (3)

**MATCH_OBI_CONFLICT — `quantitative real-time PCR (qPCR)`**  
benchmark maps this assay to OBI:0000893 real time polymerase chain reaction assay; we mapped it to OBI:0000911 real time reverse-transcription polymerase chain reaction assay

- `real time reverse-transcription polymerase chain reaction assay` — source: methods | section: qPCR validation. | sentences: S133
  > Changes in gene expression observed by microarray analyses were verified by qPCR.

**SPLIT — `flow cytometry (Ki67 proliferation assay)`**  
one benchmark assay matched 3 of our entries: `flow cytometry assay`, `flow cytometry assay (2)`, `flow cytometry assay (3)`

- `flow cytometry assay` — source: methods | section: Flow cytometric analysis of IFN-γ/IL-2–producing activated CD4 T cells. | sentences: S162
  > To assess the cytokine production ability of YF17D-specific helper T cells, 2 million PBMCs from vaccinated subjects (day 14 and 28) were stimulated for 6 h with YF17D-derived peptide pools, in the presence of Brefeldin A (Sigma-Aldrich), and then stained with anti-CD8 and -CD4 antibodies.
- `flow cytometry assay (2)` — source: methods | section: CD4 + T cell stimulation assay. | sentences: S178
  > The T cells and APCs were co-cultured for 7 h, stained with CD4 antibody, permeabilized, and labeled intracellularly with anti–IFN-γ, –IL-5, –IL-13, and -CD154 antibodies.
- `flow cytometry assay (3)` — source: methods | section: Flow cytometric analysis of IFN-γ/IL-2–producing activated CD4 T cells. | sentences: S166
  > The cells were then stained with anti-CD3, -CD4, -CD8, -CD45RA, -CCR7, -CCR4, -CXCR3, and -CCR6 antibodies (BD).

**MATCH_OBI_CONFLICT — `CFSE labeling`**  
benchmark maps this assay to OBI:00003582 ?; we mapped it to OBI:0003582 cell proliferation assay using carboxyfluorescein succinimidyl ester staining

- `cell proliferation assay using carboxyfluorescein succinimidyl ester staining` — source: methods | section: Proliferation and cytokine secretion assays. | sentences: S155
  > PBMCs from vaccinated volunteers were labeled with CFSE (Invitrogen), as previously described ( 64 ).


---

## SDY1291 (23151505) — 4 benchmark / 4 ours

`data/benchmark_agent_assays/assay_result_v3/23151505_SDY1291_pdf/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Affymetrix Exon Microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `RT-qPCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |
| `Multiplex Cytokine Analysis` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |

---

## SDY1293 (20078211) — 3 benchmark / 3 ours

`data/benchmark_agent_assays/assay_result_v3/20078211_SDY1293_pdf/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `GeneChip analysis` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `malaria thick blood smears` | `microscopy assay` | obi_exact | **MATCH** |
| `real-time polymerase chain reaction` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

---

## SDY1294 (28687661) — 5 benchmark / 6 ours

`data/benchmark_agent_assays/assay_result_v3/28687661_SDY1294/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `microarray analysis` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `flow_cytometry_immunophenotyping` | `flow cytometry assay`, `flow cytometry assay (2)` | obi_exact | **SPLIT** |
| `NK-mediated ADCC assay` | `cell-cell killing assay` | obi_exact | **MATCH** |
| `plaque_reduction_neutralization_test` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |
| `immunofluorescence_assay` | `immuno staining assay` | name | **MATCH_OBI_CONFLICT** |

### Conflicts (2)

**SPLIT — `flow_cytometry_immunophenotyping`**  
one benchmark assay matched 2 of our entries: `flow cytometry assay`, `flow cytometry assay (2)`

- `flow cytometry assay` — source: methods | section: Flow cytometry | sentences: S32
  > For all phenotype panels, one million cells were surface-stained with the antibody cocktails shown in Table 1 .
- `flow cytometry assay (2)` — source: methods | section: Flow cytometry | sentences: S41
  > For analysis of T cell function, 1 million PBMCs were stimulated with Env peptide pools, nonstructural protein (NS1) peptide pools (a kind gift from Dr.

**MATCH_OBI_CONFLICT — `immunofluorescence_assay`**  
benchmark maps this assay to CHMO:0000087 fluorescence microscopy assay; we mapped it to OBI:0001632 immuno staining assay

- `immuno staining assay` — source: methods | section: Immunofluorescence assay to detect anti-Japanese encephalitis virus and anti-West Nile virus antibodies | sentences: S25
  > To determine the presence of anti-Japanese encephalitis virus (JEV) and anti-West Nile virus (WNV) antibodies in the serum samples, fluorescence microscopy was employed.


---

## SDY1325 (28137280) — 5 benchmark / 5 ours

`data/benchmark_agent_assays/assay_result_v3/28137280_SDY1325/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `human complement serum bactericidal assay` | `bacterial neutralization assay` | obi_exact | **MATCH** |
| `B-cell enzyme-linked immunospot assay` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `flow cytometric characterisation of B cells and plasma cells` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Illumina® Human HT12v4.0 Expression BeadChip microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `quantitative real-time PCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

---

## SDY1328 (26742691) — 5 benchmark / 6 ours

`data/benchmark_agent_assays/assay_result_v3/26742691_SDY1328/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `polychromatic FCM` | `flow cytometry assay` | obi_exact | **MATCH** |
| `multiplex ELISA protocol Human Inflammation multianalyte profiling` | `multiplex ELISA protocol Human Inflammation multianalyte profiling` | name | **MATCH_OBI_UNMAPPED** |
| `haematologic markers` | `complete blood count` | name | **MATCH_OBI_UNMAPPED** |
| `GM1-enzyme-linked immunosorbent assay` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| — | `surface HBV antibody assay` | — | **EXTRA** |

### Conflicts (2)

**MATCH_OBI_UNMAPPED — `multiplex ELISA protocol Human Inflammation multianalyte profiling`**  
we mapped this assay to no OBI term

- `multiplex ELISA protocol Human Inflammation multianalyte profiling` — source: methods | section: Cytokine measurements | sentences: S231
  > Serum samples were shipped to RBM for analysis using the multiplex ELISA protocol Human Inflammation multianalyte profiling ( Supplementary Table 5b ).

**MATCH_OBI_UNMAPPED — `haematologic markers`**  
we mapped this assay to no OBI term

- `complete blood count` — source: methods | section: Haematologic measurements | sentences: S235
  > A panel of 3 standard haematologic markers (complete blood count) was measured on the 174 pre-vaccination samples taken 28 days prior to vaccination (V1) of the EM131 cohort.


### Extra assays not in the benchmark (1)

**`surface HBV antibody assay`** — OBI:0002148 surface HBV antibody assay  
- source: methods | section: Antibody titres | sentences: S138
  > Anti-hepatitis B surface antigen (anti-HBsAg) total antibodies were quantified in serum samples using the MONOLISA Anti-HBs PLUS kit (Bio-Rad catalogue number 72566).


---

## SDY1373 (28854372) — 4 benchmark / 4 ours

`data/benchmark_agent_assays/assay_result_v3/28854372_SDY1373/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Flow Cytometry Analysis` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Cytokine and Chemokine Multiplex Analysis` | `cytometric bead array assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Next-Generation RNA Sequencing` | `bulk RNA-seq assay` | name | **MATCH_OBI_CONFLICT** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `Next-Generation RNA Sequencing`**  
benchmark maps this assay to OBI:0002571 polyA-selected RNA sequencing assay; we mapped it to OBI:0003090 bulk RNA-seq assay

- `bulk RNA-seq assay` — source: methods | section: RNA Extraction and Next-Generation RNA Sequencing | sentences: S123
  > Diluted libraries were multiplex-sequenced on the Illumina HiSeq 2500 instrument (single read, 50-bp run).


---

## SDY1389 (30111633) — 6 benchmark / 6 ours

`data/benchmark_agent_assays/assay_result_v3/30111633_SDY1389/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Flow cytometry and sorting` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Whole-Transcriptome Profiling by RNA-Sequencing` | `bulk RNA-seq assay` | obi_exact | **MATCH** |
| `CyTOF Sample Preparation and Analysis` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `T cell proliferation assays` | `cell proliferation assay` | obi_exact | **MATCH** |
| `Human T cell receptor (TCR) sequencing and analysis` | `T cell receptor repertoire sequencing assay` | obi_exact | **MATCH** |
| `HLA multimer reagents` | `MHC tetramer/multimer assay measuring binding of a T cell epitope:MHC:TCR complex` | obi_exact | **MATCH** |

---

## SDY1393 (36656789) — 3 benchmark / 3 ours

`data/benchmark_agent_assays/assay_result_v3/36656789_SDY1393/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `RNA-seq` | `bulk RNA-seq assay` | obi_exact | **MATCH** |
| `HAI` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |

---

## SDY1596 (32005538) — 3 benchmark / 5 ours

`data/benchmark_agent_assays/assay_result_v3/32005538_SDY1596/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Luminex` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `Flow Cytometry` | `flow cytometry assay`, `flow cytometry assay (2)` | obi_exact | **SPLIT** |
| `colony-forming units` | — | — | **MISSED** |
| — | `population count assay` | — | **EXTRA** |
| — | `blood assay` | — | **EXTRA** |

### Conflicts (2)

**SPLIT — `Flow Cytometry`**  
one benchmark assay matched 2 of our entries: `flow cytometry assay`, `flow cytometry assay (2)`

- `flow cytometry assay` — source: methods | section: Bacterial viability stain/Assessment of mycobacterial membrane integrity | sentences: S17
  > Cell membrane integrity was assessed by flow cytometry (LSR Fortessa, BD Biosciences).
- `flow cytometry assay (2)` — source: methods | section: Relative quantitation of bacterial RNA by flow cytometry | sentences: S21
  > Mean fluorescence intensity of the RNA dye was assessed by flow cytometry (LSR Fortessa, BD Biosciences).

**MISSED — `colony-forming units`**  
no entry of ours matches this benchmark assay

- benchmark evidence — section: Abstract
  > We compared BCG-Denmark (DEN), -Japan (JPN), -India (IND), -Bulgaria (BUL) and -USA in vitro with respect to a) viability as measured by colony-forming units (CFU)


### Extra assays not in the benchmark (2)

**`population count assay`** — OBI:0003831 population count assay  
- source: methods | section: BCG culture in vitro | sentences: S23
  > Actual CFU counts were obtained by the culturable microbial count assay and used as a proxy for mycobacterial viability.

**`blood assay`** — OBI:0003040 blood assay  
- source: methods | section: Whole blood assay and cytokine/chemokine measurements | sentences: S34
  > Briefly, whole blood diluted 1:1 in RPMI medium was stimulated with different volume/volume (v/v) BCG concentrations in 96-well U-bottom plates.


---

## SDY1630 (32059780) — 3 benchmark / 4 ours

`data/benchmark_agent_assays/assay_result_v3/32059780_SDY1630/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `flow cytometry analysis` | `flow cytometry assay`, `flow cytometry assay (2)`, `flow cytometry assay (3)` | obi_exact | **SPLIT** |
| `in vitro cytokine stimulation and functional assays` | `flow cytometry assay (2)` | name_containment | **MATCH_OBI_CONFLICT** |
| `whole transcriptome profiling ok NK cell subsets)` | `bulk RNA-seq assay` | obi_exact | **MATCH** |

### Conflicts (2)

**SPLIT — `flow cytometry analysis`**  
one benchmark assay matched 3 of our entries: `flow cytometry assay`, `flow cytometry assay (2)`, `flow cytometry assay (3)`

- `flow cytometry assay` — source: methods | section: Flow cytometry analysis and cell sorting | sentences: S104
  > For flow cytometric analysis, cells were stained in 96-well U-bottom plates in the dark using antibody panels (see Key Resources Table ).
- `flow cytometry assay (2)` — source: methods | section: In vitro cytokine stimulation and functional assays of NK cells | sentences: S122
  > NK cells (CD45 + CD56 + CD3 − ) sorted from freshly processed tissue sites (see above) were cultured in 96-well u-bottom plates in RPMI-1640 medium containing fetal bovine serum (10%) with or without 10ng/ml IL-12 (PeproTech, cat# 200–12), 100ng/ml IL-15 (PeproTech, cat# 200–15) and 100ng/ml IL-18 (MBL International Corp.
- `flow cytometry assay (3)` — source: methods | section: In vitro cytokine stimulation and functional assays of NK cells | sentences: S126
  > For measuring degranulation by NK cells, 30,000–50,000 sorted, overnight rested NK cells were incubated with K562 cells (ATCC: CCL-243; provided by Emily Mace, Columbia University) at a 2:1 effector to target (NK: K562) ratio in a 96-well tissue culture plate at 37°C at 5% CO 2 for 4 hours.

**MATCH_OBI_CONFLICT — `in vitro cytokine stimulation and functional assays`**  
benchmark maps this assay to OBI:1110207 assay detecting IFN-gamma production; we mapped it to OBI:0000916 flow cytometry assay

- `flow cytometry assay (2)` — source: methods | section: In vitro cytokine stimulation and functional assays of NK cells | sentences: S122
  > NK cells (CD45 + CD56 + CD3 − ) sorted from freshly processed tissue sites (see above) were cultured in 96-well u-bottom plates in RPMI-1640 medium containing fetal bovine serum (10%) with or without 10ng/ml IL-12 (PeproTech, cat# 200–12), 100ng/ml IL-15 (PeproTech, cat# 200–15) and 100ng/ml IL-18 (MBL International Corp.


---

## SDY1640 (32473127) — 6 benchmark / 6 ours

`data/benchmark_agent_assays/assay_result_v3/32473127_SDY1640/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Activation Induced Marker (AIM) assay` | `T cell activation induced marker assay` | obi_exact | **MATCH** |
| `intracellular cytokine staining assay` | `flow cytometry assay`, `flow cytometry assay (2)` | obi_exact | **SPLIT** |
| `flow cytometry` | `flow cytometry assay`, `flow cytometry assay (2)` | obi_exact | **SPLIT** |
| `SARS-CoV-2 RBD ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `lateral_flow_serology` | `single-value binding of antibody with reporter to antigen assay` | name | **MATCH_OBI_UNMAPPED** |
| `cytokine bead assay` | `analyte detection by flow based bead assay` | obi_exact | **MATCH** |

### Conflicts (3)

**SPLIT — `intracellular cytokine staining assay`**  
one benchmark assay matched 2 of our entries: `flow cytometry assay`, `flow cytometry assay (2)`

- `flow cytometry assay` — source: methods | section: Direct ex vivo PBMC immune cell phenotyping | sentences: S322
  > All samples were acquired on a BD FACSymphony cell sorter (BD Biosciences, San Diego, CA).
- `flow cytometry assay (2)` — source: methods | section: Intracellular cytokine staining assay | sentences: S337
  > The gates applied for the identification of IFNγ, GzB, TNFα, or IL-10 production on the total population of CD8 + T cells were defined according to the cells cultured with DMSO for each individual.

**SPLIT — `flow cytometry`**  
one benchmark assay matched 2 of our entries: `flow cytometry assay`, `flow cytometry assay (2)`

- `flow cytometry assay` — source: methods | section: Direct ex vivo PBMC immune cell phenotyping | sentences: S322
  > All samples were acquired on a BD FACSymphony cell sorter (BD Biosciences, San Diego, CA).
- `flow cytometry assay (2)` — source: methods | section: Intracellular cytokine staining assay | sentences: S337
  > The gates applied for the identification of IFNγ, GzB, TNFα, or IL-10 production on the total population of CD8 + T cells were defined according to the cells cultured with DMSO for each individual.

**MATCH_OBI_UNMAPPED — `lateral_flow_serology`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `single-value binding of antibody with reporter to antigen assay` — source: methods | section: Convalescent COVID-19 Donors | sentences: S266
  > Following enrollment, whole blood from convalescent donors was run on a colloidal-gold immunochromatographic ‘lateral flow’ assay to evaluate for prior exposure to SARS-CoV-2.


---

## SDY1654 (31624246) — 4 benchmark / 4 ours

`data/benchmark_agent_assays/assay_result_v3/31624246_SDY1654/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `single cell RNA-sequencing (scRNA-seq)` | `single-cell RNA sequencing assay` | obi_exact | **MATCH** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `proliferation assay` | `cell proliferation assay` | obi_exact | **MATCH** |
| `quantitative real-time PCR (qPCR)` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

---

## SDY1655 (32717743) — 4 benchmark / 4 ours

`data/benchmark_agent_assays/assay_result_v3/32717743_SDY1655/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RT-qPCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |
| `Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71)` | `cytometric bead array assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `flow cytometry` | `flow cytometry assay`, `flow cytometry assay (2)` | obi_exact | **SPLIT** |
| `intracellular_cytokine_staining` | `flow cytometry assay`, `flow cytometry assay (2)` | obi_exact | **SPLIT** |

### Conflicts (2)

**SPLIT — `flow cytometry`**  
one benchmark assay matched 2 of our entries: `flow cytometry assay`, `flow cytometry assay (2)`

- `flow cytometry assay` — source: methods | section: Flow cytometry | sentences: S199
  > Finally, intracellular staining cocktails were directly added to each sample for 1 hour at 4°C.
- `flow cytometry assay (2)` — source: methods | section: Flow cytometry | sentences: S192
  > For intracellular cytokine staining following stimulation, cells were resuspended in 200 μL cRPMI (RPMI-1640 supplemented with 10% FBS, 2 mM L-glutamine, 100 U/ml penicillin, and 100 mg/ml streptomycin, 1mM Sodium Pyruvate, and 50uM 2-Mercaptoethanol) and stored at 4°C overnight.

**SPLIT — `intracellular_cytokine_staining`**  
one benchmark assay matched 2 of our entries: `flow cytometry assay`, `flow cytometry assay (2)`

- `flow cytometry assay` — source: methods | section: Flow cytometry | sentences: S199
  > Finally, intracellular staining cocktails were directly added to each sample for 1 hour at 4°C.
- `flow cytometry assay (2)` — source: methods | section: Flow cytometry | sentences: S192
  > For intracellular cytokine staining following stimulation, cells were resuspended in 200 μL cRPMI (RPMI-1640 supplemented with 10% FBS, 2 mM L-glutamine, 100 U/ml penicillin, and 100 mg/ml streptomycin, 1mM Sodium Pyruvate, and 50uM 2-Mercaptoethanol) and stored at 4°C overnight.


---

## SDY1669 (32788292) — 3 benchmark / 8 ours

`data/benchmark_agent_assays/assay_result_v3/32788292_SDY1669/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `phospho-CyTOF` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `intracellular staining assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Flow cytometry analysis of PBMCs` | `flow cytometry assay` | obi_exact | **MATCH** |
| — | `Olink assay` | — | **EXTRA** |
| — | `enzyme-linked immunosorbent assay` | — | **EXTRA** |
| — | `cellular indexing of transcriptomes and epitopes by sequencing` | — | **EXTRA** |
| — | `bulk RNA-seq assay` | — | **EXTRA** |
| — | `polymerase chain reaction assay` | — | **EXTRA** |
| — | `bacterial lipopolysaccharide detection in plasma assay` | — | **EXTRA** |

### Extra assays not in the benchmark (6)

**`Olink assay`** — OBI:0003112 Olink assay  
- source: results | section: Enhanced concentrations of cytokines and inflammatory mediators in plasma from COVID-19 patients | sentences: S58
  > Therefore, we evaluated cytokines and chemokines in plasma samples from the Atlanta cohort using the Olink multiplex inflammation panel that measures 92 different cytokines and chemokines.

**`enzyme-linked immunosorbent assay`** — OBI:0000661 enzyme-linked immunosorbent assay  
- source: results | section: Enhanced concentrations of cytokines and inflammatory mediators in plasma from COVID-19 patients | sentences: S69
  > Given the pronounced and unappreciated observations of the enhanced plasma concentrations of TNFSF14, EN-RAGE, and OSM and their correlation to disease severity, we used an enzyme-linked immunosorbent assay (ELISA) to independently validate these results.

**`cellular indexing of transcriptomes and epitopes by sequencing`** — OBI:0003788 cellular indexing of transcriptomes and epitopes by sequencing  
- source: results | section: Single-cell transcriptional response to COVID-19 infection | sentences: S75
  > To investigate the molecular and cellular processes that lead to the distinctive inflammatory program, we used cellular indexing of transcriptomes and epitopes by sequencing (CITE-seq) and profiled the gene and protein expression in PBMC samples of COVID-19–infected individuals.

**`bulk RNA-seq assay`** — OBI:0003090 bulk RNA-seq assay  
- source: results | section: Single-cell transcriptional response to COVID-19 infection | sentences: S116
  > To investigate this further and to independently validate the observations in the CITE-seq analysis, we performed bulk RNA sequencing (RNA-seq) analysis of PBMCs in an extended group of subjects (17 COVID-19 patients and 17 healthy controls) from the same cohort.

**`polymerase chain reaction assay`** — OBI:0002692 polymerase chain reaction assay  
- source: results | section: Severe COVID-19 infection is associated with the systemic release of bacterial products | sentences: S168, S169
  > Notably, the plasma of severe and ICU patients had significantly higher levels of bacterial DNA, as measured by PCR quantitation of bacterial 16 S ribosomal RNA (rRNA) gene product, and of LPS, as measured by a TLR4-based reporter assay ( Fig. 6, A and B ).

**`bacterial lipopolysaccharide detection in plasma assay`** — OBI:0003793 bacterial lipopolysaccharide detection in plasma assay  
- source: results | section: Severe COVID-19 infection is associated with the systemic release of bacterial products | sentences: S168, S169
  > Notably, the plasma of severe and ICU patients had significantly higher levels of bacterial DNA, as measured by PCR quantitation of bacterial 16 S ribosomal RNA (rRNA) gene product, and of LPS, as measured by a TLR4-based reporter assay ( Fig. 6, A and B ).


---

## SDY1708 (34128959) — 3 benchmark / 3 ours

`data/benchmark_agent_assays/assay_result_v3/34128959_SDY1708/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Mass cytometry` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `scRNA-seq` | `single-cell RNA sequencing assay` | obi_exact | **MATCH** |
| `scATAC-seq` | `single-cell ATAC-seq` | obi_exact | **MATCH** |

---

## SDY180 (23601689) — 6 benchmark / 6 ours

`data/benchmark_agent_assays/assay_result_v3/23601689_SDY180/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Microarray Assay` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Hemagglutinin Inhibition Assay` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `Virus-Neutralization Assay` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |
| `Commercial immunoassays (pneumococcal polysaccharide antibody)` | `single-value binding of antibody with reporter to antigen assay` | obi_exact | **MATCH** |
| `Multiplex Cytokine Analysis` | `cytometric bead array assay` | obi_exact | **MATCH** |

---

## SDY1991 (35455361) — 4 benchmark / 4 ours

`data/benchmark_agent_assays/assay_result_v3/35455361_SDY1991/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RNA-Sequencing Assay` | `bulk RNA-seq assay` | obi_exact | **MATCH** |
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `flow cytometry-based neutralization assays` | `pathogen neutralization assay` | obi_exact | **MATCH** |
| `IFN-γ Capture Assay` | `flow cytometry assay` | obi_exact | **MATCH** |

---

## SDY1995 (35062294) — 4 benchmark / 4 ours

`data/benchmark_agent_assays/assay_result_v3/35062294_SDY1995/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RNA Sequencing` | `bulk RNA-seq assay` | obi_exact | **MATCH** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Reverse transcription-PCR` | `reverse transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

---

## SDY212 (25834109) — 8 benchmark / 9 ours

`data/benchmark_agent_assays/assay_result_v3/25834109_SDY212/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `CMV IgG ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `multiparametric flow cytometry` | `flow cytometry assay`, `flow cytometry assay (2)` | obi_exact | **SPLIT** |
| `Luminex system` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `whole_blood_microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `hemagglutination inhibition assay` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `snp_genotyping_array` | `genotyping by SNP array assay` | obi_exact | **MATCH** |
| `plaque assay` | `viral plaque assay` | obi_exact | **MATCH** |
| `tetramer staining` | `MHC tetramer/multimer assay measuring binding of a T cell epitope:MHC:TCR complex` | obi_exact | **MATCH** |

### Conflicts (1)

**SPLIT — `multiparametric flow cytometry`**  
one benchmark assay matched 2 of our entries: `flow cytometry assay`, `flow cytometry assay (2)`

- `flow cytometry assay` — source: methods | section: Leukocyte subset frequency determination | sentences: S116
  > PBMC were thawed in warm media, washed twice and stained with three separate antihuman antibody cocktails containing: ( 1 ) anti-CD3 AmCyan, CD4 Pacific Blue, CD8 APCH7, CD28 APC; ( 2 ) CD3 AmCyan, CD4 Pacific Blue, CD8 APCH7, CD27 PE, CD45RA PE-Cy5; ( 3 ) CD3 AmCyan, CD19 Alexa Fluor700, CD56 PE, CD33 PE-Cy7, TCR APC, all reagents from BD Biosciences.
- `flow cytometry assay (2)` — source: methods | section: Phosphorylation of intracellular proteins by phosphoflow analysis | sentences: S129
  > After washing, cells were resuspended in FACS buffer and acquisition was performed on an LSRII instrument (BD Biosciences).


---

## SDY2189 (34252919) — 10 benchmark / 10 ours

`data/benchmark_agent_assays/assay_result_v3/34252919_SDY2189/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Focus reduction neutralization titre assay` | `serum neutralization of viral infectivity assay`, `serum neutralization of viral infectivity assay (2)` | obi_exact | **SPLIT** |
| `Intracellular cytokine staining assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Bead-based antigen arrays` | `antibody detection by cytometric bead array assay` | obi_exact | **MATCH** |
| `CyTOF analysis of whole-blood samples` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `Plasma protein profiling using multiplex Olink panel` | `Olink assay` | obi_exact | **MATCH** |
| `Single-molecule array` | — | — | **MISSED** |
| `Bulk transcriptomics` | `bulk RNA-seq assay` | obi_exact | **MATCH** |
| `CITE-seq` | `cellular indexing of transcriptomes and epitopes by sequencing` | obi_exact | **MATCH** |
| `RNA isolation and qPCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

### Conflicts (2)

**SPLIT — `Focus reduction neutralization titre assay`**  
one benchmark assay matched 2 of our entries: `serum neutralization of viral infectivity assay`, `serum neutralization of viral infectivity assay (2)`

- `serum neutralization of viral infectivity assay` — source: methods | section: Focus reduction neutralization titre assay | sentences: S134
  > Neutralization assays with authentic SARS-CoV-2 virus (infectious clone SARS-CoV-2 derived from 2019-nCoV/USA_WA1/2020 strain) were performed as previously described 31 .
- `serum neutralization of viral infectivity assay (2)` — source: methods | section: FRNT assay against the variants of concern | sentences: S152
  > FRNT assays were performed as described for the wild-type FRNT assay.

**MISSED — `Single-molecule array`**  
no entry of ours matches this benchmark assay

- benchmark evidence — section: Results
  > The concentration of IFNα2 (type I interferon) was not significantly increased on days 1 and 2 after vaccination, and the responses were just over the assay limit of the highly sensitive single-molecule array (SIMOA) (16 fg ml−1) (Extended Data Fig. 7c, d).


---

## SDY404 (25367297) — 3 benchmark / 3 ours

`data/benchmark_agent_assays/assay_result_v3/25367297_SDY404_pdf/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Flow Cytometry with Intracellular Cytokine Staining` | `flow cytometry assay` | obi_exact | **MATCH** |
| `hemagglutination_inhibition_assay` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `Western Blot Analysis` | `western blot assay` | obi_exact | **MATCH** |

---

## SDY80 (24725414) — 4 benchmark / 4 ours

`data/benchmark_agent_assays/assay_result_v3/24725414_SDY80/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `flow cytometric analyses` | `flow cytometry assay` | obi_exact | **MATCH** |
| `transcriptome analyses using microarrays` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `microneutralization_assay` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |
| `ELISpot assays` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |

---

## SDY984 (28502771) — 9 benchmark / 11 ours

`data/benchmark_agent_assays/assay_result_v3/28502771_SDY984/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Zostavax-specific IFN-γ, IL-4 and IL-21 ELISPOT` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `Zostavax-specific and total IgG B cell ELISPOT` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `Zostavax-specific IgG/IgA ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Viral DNA detection` | `real time polymerase chain reaction assay` | obi_exact | **MATCH** |
| `cytokine bead array assay` | `cytometric bead array assay`, `cytometric bead array assay (2)` | obi_exact | **SPLIT** |
| `PBMC Transcriptomics analysis` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `Plasma Metabolomics analysis` | `metabolomics by mass spectrometry assay` | name | **MATCH_OBI_CONFLICT** |
| `partial sequencing of amplicons` | `amplicon sequencing assay` | obi_exact | **MATCH** |
| — | `polymerase chain reaction assay` | — | **EXTRA** |
| — | `tandem mass spectrometry assay` | — | **EXTRA** |

### Conflicts (2)

**SPLIT — `cytokine bead array assay`**  
one benchmark assay matched 2 of our entries: `cytometric bead array assay`, `cytometric bead array assay (2)`

- `cytometric bead array assay` — source: methods | section: Multiplex cytokine assays | sentences: S249
  > Luminex assays were performed with the Beadlyte Human 10-Plex Multi-Cytokine Detection System (Upstate).
- `cytometric bead array assay (2)` — source: methods | section: In vitro stimulation of PBMCs with Zostavax® | sentences: S257
  > Cell-free culture supernatants collected were analyzed for cytokines and chemokines, including IL-6, TNF, CXCL8, CCL2, CXCL9 and CXCL10 using Cytokine Bead Array (CBA) kits (BD Biosciences, San Diego, US)

**MATCH_OBI_CONFLICT — `Plasma Metabolomics analysis`**  
benchmark maps this assay to OBI:0003097 liquid chromatography mass spectrometry assay; we mapped it to OBI:0003782 metabolomics by mass spectrometry assay

- `metabolomics by mass spectrometry assay` — source: methods | section: Plasma Metabolomics analysis | sentences: S264
  > Mass spectral data were collected with a 10-minute reversed phase gradient on a Thermo Q Exactive mass spectrometer (Thermo Fisher, San Diego, CA) set to record from mass-to-charge ratio (m/z) 85 to 2000.


### Extra assays not in the benchmark (2)

**`polymerase chain reaction assay`** — OBI:0002692 polymerase chain reaction assay  
- source: methods | section: Viral DNA detection | sentences: S234
  > In order to increase the sensitivity to detect VZV DNA ORF63, and to verify the PCR products having the same DNA sequence of VZV ORF63, nested PCR analysis was carried out on 1/40 of the volume of PCR product that did not initially contain detectable VZV DNA.

**`tandem mass spectrometry assay`** — OBI:0003540 tandem mass spectrometry assay  
- source: methods | section: Plasma Metabolomics analysis | sentences: S267
  > Metabolite confirmation was performed with tandem MS-MS experiments on Thermo QE HF, Orbitrap Fusion, or Finnigan LTQ FT Ultra mass spectrometers.
