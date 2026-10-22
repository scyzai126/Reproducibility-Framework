# Assay extraction vs. curated benchmark

27 papers · 137 benchmark assays · 136 extracted assays

The benchmark is a **recall reference, not an exhaustive list** — on some papers it records one assay where the paper describes nine. Recall is therefore the headline metric and no precision figure is given; our unmatched assays are listed as EXTRA with their paper evidence to be judged individually.

## Totals

| Study | PMID | Benchmark | Ours | Matched | Missed | Extra | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| SDY1260 | 24336226 | 6 | 6 | 6 | 0 | 0 | 100% |
| SDY1264 | 19029902 | 8 | 8 | 8 | 0 | 0 | 100% |
| SDY1288 | 30150281 | 7 | 7 | 7 | 0 | 1 | 100% |
| SDY1289 | 19047440 | 7 | 7 | 7 | 0 | 1 | 100% |
| SDY1291 | 23151505 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1293 | 20078211 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY1294 | 28687661 | 5 | 5 | 5 | 0 | 0 | 100% |
| SDY1325 | 28137280 | 5 | 5 | 5 | 0 | 0 | 100% |
| SDY1328 | 26742691 | 5 | 4 | 5 | 0 | 0 | 100% |
| SDY1373 | 28854372 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1389 | 30111633 | 6 | 6 | 6 | 0 | 0 | 100% |
| SDY1393 | 36656789 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY1596 | 32005538 | 3 | 3 | 2 | 1 | 1 | 67% |
| SDY1630 | 32059780 | 3 | 2 | 3 | 0 | 0 | 100% |
| SDY1640 | 32473127 | 6 | 5 | 6 | 0 | 0 | 100% |
| SDY1654 | 31624246 | 4 | 3 | 4 | 0 | 0 | 100% |
| SDY1655 | 32717743 | 4 | 3 | 3 | 1 | 1 | 75% |
| SDY1669 | 32788292 | 3 | 8 | 3 | 0 | 6 | 100% |
| SDY1708 | 34128959 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY180 | 23601689 | 6 | 5 | 5 | 1 | 0 | 83% |
| SDY1991 | 35455361 | 4 | 5 | 4 | 0 | 1 | 100% |
| SDY1995 | 35062294 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY212 | 25834109 | 8 | 8 | 8 | 0 | 0 | 100% |
| SDY2189 | 34252919 | 10 | 9 | 9 | 1 | 0 | 90% |
| SDY404 | 25367297 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY80 | 24725414 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY984 | 28502771 | 9 | 9 | 9 | 0 | 1 | 100% |
| **All** | | **137** | **136** | **133** | **4** | **12** | **97%** |

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

`data/31paper_assays/assay_result_v1/24336226_SDY1260/assays_benchmark.json`

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

## SDY1264 (19029902) — 8 benchmark / 8 ours

`data/31paper_assays/assay_result_v1/19029902_SDY1264/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `Luminex assay` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `Flow cytometric analysis` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Assay for yellow fever virus (YFV) neutralizing antibodies` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |
| `RT-PCR` | `reverse transcription polymerase chain reaction assay` | name | **MATCH_OBI_CONFLICT** |
| `immunoblot assay` | `western blot assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Immunofluorescence` | `fluorescence microscopy assay` | name | **MATCH_OBI_UNMAPPED** |

### Conflicts (2)

**MATCH_OBI_CONFLICT — `RT-PCR`**  
benchmark maps this assay to OBI:0000911 real time reverse-transcription polymerase chain reaction assay; we mapped it to OBI:0001170 reverse transcription polymerase chain reaction assay

- `reverse transcription polymerase chain reaction assay` — source: methods | section: RNA isolation and microarray and RT-PCR data generation | sentences: S197
  > Two-step RT-PCR was performed.

**MATCH_OBI_UNMAPPED — `Immunofluorescence`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `fluorescence microscopy assay` — source: methods | section: Data analysis | sentences: S213
  > Immunofluorescence signal was detected using a LSM510 confocal microscope (Zeiss), and images were captured and analyzed using the Zeiss LSM Image Browser.


---

## SDY1288 (30150281) — 7 benchmark / 7 ours

`data/31paper_assays/assay_result_v1/30150281_SDY1288/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `mass cytometry (CyTOF)` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `multiplex ELISA-based assay (Luminex)` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `RNA-seq` | `bulk RNA-seq assay` | obi_exact | **MATCH** |
| `real-time RT–PCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |
| `Inhibition ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `IgM_capture_ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `virus_isolation` | `infectious agent detection assay` | obi_exact | **MATCH** |
| — | `reverse transcription polymerase chain reaction assay` | — | **EXTRA** |

### Extra assays not in the benchmark (1)

**`reverse transcription polymerase chain reaction assay`** — OBI:0001170 reverse transcription polymerase chain reaction assay  
- source: methods | section: Viral titer assays | sentences: S200
  > Primers for the E1 gene were designed to quantify CHIKV copies in each patient and were used at 300 nM final concentration.


---

## SDY1289 (19047440) — 7 benchmark / 7 ours

`data/31paper_assays/assay_result_v1/19047440_SDY1289/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `gene array` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `quantitative real-time PCR (qPCR)` | `real time reverse-transcription polymerase chain reaction assay` | name | **MATCH_OBI_CONFLICT** |
| `IL-1β ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `flow cytometry (Ki67 proliferation assay)` | `flow cytometry assay` | obi_exact | **MATCH** |
| `CFSE labeling` | `cell proliferation assay using carboxyfluorescein succinimidyl ester staining` | name | **MATCH_OBI_CONFLICT** |
| `cytometric bead assay (CBA)` | `cytometric bead array assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `multiplex cytokine analysis` | `cytometric bead array assay` | obi_exact | **MATCH** |
| — | `viral plaque assay` | — | **EXTRA** |

### Conflicts (2)

**MATCH_OBI_CONFLICT — `quantitative real-time PCR (qPCR)`**  
benchmark maps this assay to OBI:0000893 real time polymerase chain reaction assay; we mapped it to OBI:0000911 real time reverse-transcription polymerase chain reaction assay

- `real time reverse-transcription polymerase chain reaction assay` — source: methods | section: qPCR validation. | sentences: S133
  > Changes in gene expression observed by microarray analyses were verified by qPCR.

**MATCH_OBI_CONFLICT — `CFSE labeling`**  
benchmark maps this assay to OBI:00003582 ?; we mapped it to OBI:0003582 cell proliferation assay using carboxyfluorescein succinimidyl ester staining

- `cell proliferation assay using carboxyfluorescein succinimidyl ester staining` — source: methods | section: Proliferation and cytokine secretion assays. | sentences: S155
  > PBMCs from vaccinated volunteers were labeled with CFSE (Invitrogen), as previously described ( 64 ).


### Extra assays not in the benchmark (1)

**`viral plaque assay`** — OBI:0003798 viral plaque assay  
- source: methods | section: In vitro infection of immature DCs with YF17D. | sentences: S149
  > Viral stocks were titrated on Vero cells by lysis plaque assay.


---

## SDY1291 (23151505) — 4 benchmark / 4 ours

`data/31paper_assays/assay_result_v1/23151505_SDY1291_pdf/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Affymetrix Exon Microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `RT-qPCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |
| `Multiplex Cytokine Analysis` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |

---

## SDY1293 (20078211) — 3 benchmark / 3 ours

`data/31paper_assays/assay_result_v1/20078211_SDY1293_pdf/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `GeneChip analysis` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `malaria thick blood smears` | `microscopy assay` | obi_exact | **MATCH** |
| `real-time polymerase chain reaction` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

---

## SDY1294 (28687661) — 5 benchmark / 5 ours

`data/31paper_assays/assay_result_v1/28687661_SDY1294/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `microarray analysis` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `flow_cytometry_immunophenotyping` | `flow cytometry assay` | obi_exact | **MATCH** |
| `NK-mediated ADCC assay` | `cell-cell killing assay` | obi_exact | **MATCH** |
| `plaque_reduction_neutralization_test` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |
| `immunofluorescence_assay` | `fluorescence microscopy assay` | obi_exact | **MATCH** |

---

## SDY1325 (28137280) — 5 benchmark / 5 ours

`data/31paper_assays/assay_result_v1/28137280_SDY1325/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `human complement serum bactericidal assay` | `bacterial neutralization assay` | obi_exact | **MATCH** |
| `B-cell enzyme-linked immunospot assay` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `flow cytometric characterisation of B cells and plasma cells` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Illumina® Human HT12v4.0 Expression BeadChip microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `quantitative real-time PCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

---

## SDY1328 (26742691) — 5 benchmark / 4 ours

`data/31paper_assays/assay_result_v1/26742691_SDY1328/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `polychromatic FCM` | `flow cytometry assay` | obi_exact | **MATCH** |
| `multiplex ELISA protocol Human Inflammation multianalyte profiling` | `enzyme-linked immunosorbent assay` | name_containment | **MATCH_OBI_CONFLICT** |
| `haematologic markers` | `hematology assay` | obi_exact | **MATCH** |
| `GM1-enzyme-linked immunosorbent assay` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `multiplex ELISA protocol Human Inflammation multianalyte profiling`**  
benchmark maps this assay to OBI:0000920 cytometric bead array assay; we mapped it to OBI:0000661 enzyme-linked immunosorbent assay

- `enzyme-linked immunosorbent assay` — source: methods | section: Antibody titres | sentences: S122
  > Anti-Cholera toxin B subunit (CTB) IgG were quantified in serum samples according to a GM1-enzyme-linked immunosorbent assay (ELISA) method adapted from Svennerholm et al.


---

## SDY1373 (28854372) — 4 benchmark / 4 ours

`data/31paper_assays/assay_result_v1/28854372_SDY1373/assays_benchmark.json`

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

`data/31paper_assays/assay_result_v1/30111633_SDY1389/assays_benchmark.json`

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

`data/31paper_assays/assay_result_v1/36656789_SDY1393/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `RNA-seq` | `RNA-seq assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `HAI` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |

---

## SDY1596 (32005538) — 3 benchmark / 3 ours

`data/31paper_assays/assay_result_v1/32005538_SDY1596/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Luminex` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `colony-forming units` | — | — | **MISSED** |
| — | `culturable microbial count assay` | — | **EXTRA** |

### Conflicts (1)

**MISSED — `colony-forming units`**  
no entry of ours matches this benchmark assay

- benchmark evidence — section: Abstract
  > We compared BCG-Denmark (DEN), -Japan (JPN), -India (IND), -Bulgaria (BUL) and -USA in vitro with respect to a) viability as measured by colony-forming units (CFU)


### Extra assays not in the benchmark (1)

**`culturable microbial count assay`** — no OBI term  
- source: methods | section: BCG culture in vitro | sentences: S23
  > Actual CFU counts were obtained by the culturable microbial count assay and used as a proxy for mycobacterial viability.


---

## SDY1630 (32059780) — 3 benchmark / 2 ours

`data/31paper_assays/assay_result_v1/32059780_SDY1630/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `flow cytometry analysis` | `flow cytometry assay` | obi_exact | **MATCH** |
| `in vitro cytokine stimulation and functional assays` | `flow cytometry assay` | name_containment | **MATCH_OBI_CONFLICT** |
| `whole transcriptome profiling ok NK cell subsets)` | `bulk RNA-seq assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `in vitro cytokine stimulation and functional assays`**  
benchmark maps this assay to OBI:1110207 assay detecting IFN-gamma production; we mapped it to OBI:0000916 flow cytometry assay

- `flow cytometry assay` — source: methods | section: Flow cytometry analysis and cell sorting | sentences: S108
  > Flow cytometry data were acquired on a BD LSRII and analyzed using FCS express 6 ( De Novo Software) and custom Python scripts.


---

## SDY1640 (32473127) — 6 benchmark / 5 ours

`data/31paper_assays/assay_result_v1/32473127_SDY1640/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Activation Induced Marker (AIM) assay` | `T cell activation induced marker assay` | obi_exact | **MATCH** |
| `intracellular cytokine staining assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `SARS-CoV-2 RBD ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `lateral_flow_serology` | `single-value binding of antibody with reporter to antigen assay` | name | **MATCH_OBI_UNMAPPED** |
| `cytokine bead assay` | `analyte detection by flow based bead assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MATCH_OBI_UNMAPPED — `lateral_flow_serology`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `single-value binding of antibody with reporter to antigen assay` — source: methods | section: Convalescent COVID-19 Donors | sentences: S266
  > Following enrollment, whole blood from convalescent donors was run on a colloidal-gold immunochromatographic ‘lateral flow’ assay to evaluate for prior exposure to SARS-CoV-2.


---

## SDY1654 (31624246) — 4 benchmark / 3 ours

`data/31paper_assays/assay_result_v1/31624246_SDY1654/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `single cell RNA-sequencing (scRNA-seq)` | `single-cell RNA sequencing assay` | obi_exact | **MATCH** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `proliferation assay` | `flow cytometry assay` | name_containment | **MATCH_OBI_CONFLICT** |
| `quantitative real-time PCR (qPCR)` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `proliferation assay`**  
benchmark maps this assay to OBI:0000891 cell proliferation assay; we mapped it to OBI:0000916 flow cytometry assay

- `flow cytometry assay` — source: methods | section: Flow cytometry and proliferation assays | sentences: S405
  > To evaluate the expression of T cell surface markers by flow cytometry, we incubated tissue and blood cell suspensions with Human TruStain FcX (BioLegend) and stained with following fluorochrome-conjugated antibodies


---

## SDY1655 (32717743) — 4 benchmark / 3 ours

`data/31paper_assays/assay_result_v1/32717743_SDY1655/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RT-qPCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |
| `Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71)` | — | — | **MISSED** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `intracellular_cytokine_staining` | `flow cytometry assay` | obi_exact | **MATCH** |
| — | `enzyme-linked immunosorbent assay` | — | **EXTRA** |

### Conflicts (1)

**MISSED — `Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71)`**  
no entry of ours matches this benchmark assay

- benchmark evidence — section: Methods
  > Patient serum was isolated as before and aliquots were stored in −80°C. Sera were shipped to Eve Technologies (Calgary, Alberta, Canada) on dry ice, and levels of cytokines and chemokines were measured with Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71). All the samples were measured upon the first thaw.


### Extra assays not in the benchmark (1)

**`enzyme-linked immunosorbent assay`** — OBI:0000661 enzyme-linked immunosorbent assay  
- source: results | section: Overview of COVID-19 immunological features | sentences: S23, S24
  > We analysed PBMC and plasma samples from patients with moderate or severe COVID-19 and healthy HCW donors ( Fig. 1a , gating strategy in) by flow cytometry and ELISA to quantify leuko- cytes and soluble mediators, respectively.


---

## SDY1669 (32788292) — 3 benchmark / 8 ours

`data/31paper_assays/assay_result_v1/32788292_SDY1669/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `phospho-CyTOF` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `intracellular staining assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Flow cytometry analysis of PBMCs` | `flow cytometry assay` | obi_exact | **MATCH** |
| — | `Olink assay` | — | **EXTRA** |
| — | `enzyme-linked immunosorbent assay` | — | **EXTRA** |
| — | `cellular indexing of transcriptomes and epitopes by sequencing` | — | **EXTRA** |
| — | `bulk RNA-seq assay` | — | **EXTRA** |
| — | `real time polymerase chain reaction assay` | — | **EXTRA** |
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

**`real time polymerase chain reaction assay`** — OBI:0000893 real time polymerase chain reaction assay  
- source: results | section: Severe COVID-19 infection is associated with the systemic release of bacterial products | sentences: S168
  > Notably, the plasma of severe and ICU patients had significantly higher levels of bacterial DNA, as measured by PCR quantitation of bacterial 16 S ribosomal RNA (rRNA) gene product, and of LPS, as measured by a TLR4-based reporter assay ( Fig.

**`bacterial lipopolysaccharide detection in plasma assay`** — OBI:0003793 bacterial lipopolysaccharide detection in plasma assay  
- source: results | section: Severe COVID-19 infection is associated with the systemic release of bacterial products | sentences: S168
  > Notably, the plasma of severe and ICU patients had significantly higher levels of bacterial DNA, as measured by PCR quantitation of bacterial 16 S ribosomal RNA (rRNA) gene product, and of LPS, as measured by a TLR4-based reporter assay ( Fig.


---

## SDY1708 (34128959) — 3 benchmark / 3 ours

`data/31paper_assays/assay_result_v1/34128959_SDY1708/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Mass cytometry` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `scRNA-seq` | `single-cell RNA sequencing assay` | obi_exact | **MATCH** |
| `scATAC-seq` | `single-cell ATAC-seq` | obi_exact | **MATCH** |

---

## SDY180 (23601689) — 6 benchmark / 5 ours

`data/31paper_assays/assay_result_v1/23601689_SDY180/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Microarray Assay` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Hemagglutinin Inhibition Assay` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `Virus-Neutralization Assay` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |
| `Commercial immunoassays (pneumococcal polysaccharide antibody)` | — | — | **MISSED** |
| `Multiplex Cytokine Analysis` | `cytometric bead array assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MISSED — `Commercial immunoassays (pneumococcal polysaccharide antibody)`**  
no entry of ours matches this benchmark assay

- benchmark evidence — section: Experimental Procedures
  > Antibody response to 14 pneumococcal polysaccharides was measured by using commercial immunoassays.


---

## SDY1991 (35455361) — 4 benchmark / 5 ours

`data/31paper_assays/assay_result_v1/35455361_SDY1991/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RNA-Sequencing Assay` | `bulk RNA-seq assay` | obi_exact | **MATCH** |
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `flow cytometry-based neutralization assays` | `pathogen neutralization assay` | obi_exact | **MATCH** |
| `IFN-γ Capture Assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| — | `IFN-γ Capture Assay` | — | **EXTRA** |

### Extra assays not in the benchmark (1)

**`IFN-γ Capture Assay`** — no OBI term  
- source: methods | section: 2.4. IFN-γ Capture Assay and Cell Sorting for RNA-Seq | sentences: S25
  > IFNγ producing cells were labeled using an IFN-γ Secretion Assay–Detection kit (PE) (catalog #130-054-202, Miltenyi Biotec, Bergisch Gladbach, North Rhine-Westphalia, Germany) according to manufacturer’s instructions.


---

## SDY1995 (35062294) — 4 benchmark / 4 ours

`data/31paper_assays/assay_result_v1/35062294_SDY1995/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RNA Sequencing` | `bulk RNA-seq assay` | obi_exact | **MATCH** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Reverse transcription-PCR` | `reverse transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

---

## SDY212 (25834109) — 8 benchmark / 8 ours

`data/31paper_assays/assay_result_v1/25834109_SDY212/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `CMV IgG ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `multiparametric flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Luminex system` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `whole_blood_microarray` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `hemagglutination inhibition assay` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `snp_genotyping_array` | `genotyping by SNP array assay` | obi_exact | **MATCH** |
| `plaque assay` | `viral plaque assay` | obi_exact | **MATCH** |
| `tetramer staining` | `MHC tetramer/multimer assay measuring binding of a T cell epitope:MHC:TCR complex` | obi_exact | **MATCH** |

---

## SDY2189 (34252919) — 10 benchmark / 9 ours

`data/31paper_assays/assay_result_v1/34252919_SDY2189/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Focus reduction neutralization titre assay` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |
| `Intracellular cytokine staining assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Bead-based antigen arrays` | `antibody detection by cytometric bead array assay` | obi_exact | **MATCH** |
| `CyTOF analysis of whole-blood samples` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `Plasma protein profiling using multiplex Olink panel` | `Olink assay` | obi_exact | **MATCH** |
| `Single-molecule array` | — | — | **MISSED** |
| `Bulk transcriptomics` | `bulk RNA-seq assay` | obi_exact | **MATCH** |
| `CITE-seq` | `cellular indexing of transcriptomes and epitopes by sequencing` | obi_exact | **MATCH** |
| `RNA isolation and qPCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MISSED — `Single-molecule array`**  
no entry of ours matches this benchmark assay

- benchmark evidence — section: Results
  > The concentration of IFNα2 (type I interferon) was not significantly increased on days 1 and 2 after vaccination, and the responses were just over the assay limit of the highly sensitive single-molecule array (SIMOA) (16 fg ml−1) (Extended Data Fig. 7c, d).


---

## SDY404 (25367297) — 3 benchmark / 3 ours

`data/31paper_assays/assay_result_v1/25367297_SDY404_pdf/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Flow Cytometry with Intracellular Cytokine Staining` | `flow cytometry assay` | obi_exact | **MATCH** |
| `hemagglutination_inhibition_assay` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `Western Blot Analysis` | `western blot assay` | obi_exact | **MATCH** |

---

## SDY80 (24725414) — 4 benchmark / 4 ours

`data/31paper_assays/assay_result_v1/24725414_SDY80/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `flow cytometric analyses` | `flow cytometry assay` | obi_exact | **MATCH** |
| `transcriptome analyses using microarrays` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `microneutralization_assay` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |
| `ELISpot assays` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |

---

## SDY984 (28502771) — 9 benchmark / 9 ours

`data/31paper_assays/assay_result_v1/28502771_SDY984/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Zostavax-specific IFN-γ, IL-4 and IL-21 ELISPOT` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `Zostavax-specific and total IgG B cell ELISPOT` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `Zostavax-specific IgG/IgA ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Viral DNA detection` | `real time polymerase chain reaction assay` | obi_exact | **MATCH** |
| `cytokine bead array assay` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `PBMC Transcriptomics analysis` | `transcription profiling by array assay` | obi_exact | **MATCH** |
| `Plasma Metabolomics analysis` | `metabolomics by mass spectrometry assay` | name | **MATCH_OBI_CONFLICT** |
| `partial sequencing of amplicons` | `amplicon sequencing assay` | obi_exact | **MATCH** |
| — | `tandem mass spectrometry assay` | — | **EXTRA** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `Plasma Metabolomics analysis`**  
benchmark maps this assay to OBI:0003097 liquid chromatography mass spectrometry assay; we mapped it to OBI:0003782 metabolomics by mass spectrometry assay

- `metabolomics by mass spectrometry assay` — source: methods | section: Plasma Metabolomics analysis | sentences: S264
  > Mass spectral data were collected with a 10-minute reversed phase gradient on a Thermo Q Exactive mass spectrometer (Thermo Fisher, San Diego, CA) set to record from mass-to-charge ratio (m/z) 85 to 2000.


### Extra assays not in the benchmark (1)

**`tandem mass spectrometry assay`** — OBI:0003540 tandem mass spectrometry assay  
- source: methods | section: Plasma Metabolomics analysis | sentences: S267
  > Metabolite confirmation was performed with tandem MS-MS experiments on Thermo QE HF, Orbitrap Fusion, or Finnigan LTQ FT Ultra mass spectrometers.
