# Assay extraction vs. curated benchmark

31 papers · 147 benchmark assays · 149 extracted assays

The benchmark is a **recall reference, not an exhaustive list** — on some papers it records one assay where the paper describes nine. Recall is therefore the headline metric and no precision figure is given; our unmatched assays are listed as EXTRA with their paper evidence to be judged individually.

## Totals

| Study | PMID | Benchmark | Ours | Matched | Missed | Extra | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| SDY1260 | 24336226 | 6 | 6 | 6 | 0 | 0 | 100% |
| SDY1264 | 19029902 | 4 | 9 | 3 | 1 | 6 | 75% |
| SDY1276 | 21357945 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY1276 | 23878721 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1288 | 30150281 | 5 | 6 | 5 | 0 | 2 | 100% |
| SDY1289 | 19047440 | 12 | 6 | 12 | 0 | 0 | 100% |
| SDY1291 | 23151505 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1293 | 20078211 | 2 | 3 | 2 | 0 | 1 | 100% |
| SDY1294 | 28687661 | 4 | 5 | 4 | 0 | 1 | 100% |
| SDY1325 | 28137280 | 5 | 5 | 5 | 0 | 0 | 100% |
| SDY1328 | 26742691 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1364 | 23266342 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY1364 | 23844129 | 5 | 5 | 5 | 0 | 0 | 100% |
| SDY1373 | 28854372 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY1389 | 30111633 | 5 | 5 | 5 | 0 | 1 | 100% |
| SDY1393 | 36656789 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY1596 | 32005538 | 2 | 3 | 2 | 0 | 1 | 100% |
| SDY1630 | 32059780 | 3 | 2 | 3 | 0 | 0 | 100% |
| SDY1640 | 32473127 | 6 | 5 | 6 | 0 | 1 | 100% |
| SDY1654 | 31624246 | 4 | 3 | 4 | 0 | 0 | 100% |
| SDY1655 | 32717743 | 3 | 3 | 2 | 1 | 1 | 67% |
| SDY1669 | 32788292 | 7 | 8 | 7 | 0 | 1 | 100% |
| SDY1708 | 34128959 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY180 | 23601689 | 6 | 5 | 5 | 1 | 0 | 83% |
| SDY1991 | 35455361 | 4 | 6 | 4 | 0 | 3 | 100% |
| SDY1995 | 35062294 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY212 | 25834109 | 7 | 7 | 7 | 0 | 0 | 100% |
| SDY2189 | 34252919 | 10 | 9 | 9 | 1 | 0 | 90% |
| SDY404 | 25367297 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY80 | 24725414 | 4 | 4 | 4 | 0 | 0 | 100% |
| SDY984 | 28502771 | 8 | 9 | 8 | 0 | 2 | 100% |
| **All** | | **147** | **149** | **143** | **4** | **20** | **97%** |

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

`data/31paper_assays/24336226_SDY1260/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Luminex` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `ELISpot` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `SBA` | `bacterial neutralization assay` | name | **MATCH_OBI_UNMAPPED** |
| `microarray` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |

### Conflicts (2)

**MATCH_OBI_UNMAPPED — `SBA`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `bacterial neutralization assay` — source: methods | section: Measurement of serum bactericidal titers (SBA) | sentences: S298
  > Continuous titers were determined by interpolation of the serum dilution yielding 50% killing as compared to the T 60 growth control plate average.

**MATCH_OBI_CONFLICT — `microarray`**  
benchmark maps this assay to OBI:0002631 single-cell RNA sequencing assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: Blood transcriptome analysis | sentences: S269
  > DNA microarray experiment was performed as previously described 6 , on Affymetrix human U133 Plus 2.0 arrays (GeneTitan platform).


---

## SDY1264 (19029902) — 4 benchmark / 9 ours

`data/31paper_assays/19029902_SDY1264/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `microarray` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `Luminex assay` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `Flow cytometric analysis` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Assay for yellow fever virus (YFV) neutralizing antibodies` | — | — | **MISSED** |
| — | `cytopathic effect (CPE)` | — | **EXTRA** |
| — | `plaque reduction neutralization test (PRNT)` | — | **EXTRA** |
| — | `reverse transcription polymerase chain reaction assay` | — | **EXTRA** |
| — | `immunocytochemistry` | — | **EXTRA** |
| — | `immunoblot assay` | — | **EXTRA** |
| — | `enzyme-linked immunosorbent assay` | — | **EXTRA** |

### Conflicts (2)

**MATCH_OBI_CONFLICT — `microarray`**  
benchmark maps this assay to OBI:0002631 single-cell RNA sequencing assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: RNA isolation and microarray and RT-PCR data generation | sentences: S14
  > To gain a global perspective of the innate response to YF-17D, we performed transcriptional profiling of total peripheral blood mono-nuclear cells (PBMCs) from the 15 subjects (trial 1).

**MISSED — `Assay for yellow fever virus (YFV) neutralizing antibodies`**  
no entry of ours matches this benchmark assay

- benchmark evidence — section: Methods
  > Assay for yellow fever virus (YFV) neutralizing antibodies


### Extra assays not in the benchmark (6)

**`cytopathic effect (CPE)`** — no OBI term  
- source: methods | section: Assay for yellow fever virus (YFV) neutralizing antibodies | sentences: S179
  > YFV neutralizing antibodies were measured by cytopathic effect (CPE) (trial 1) or by plaque reduction neutralization test (PRNT) (trial 2).

**`plaque reduction neutralization test (PRNT)`** — no OBI term  
- source: methods | section: Assay for yellow fever virus (YFV) neutralizing antibodies | sentences: S179
  > YFV neutralizing antibodies were measured by cytopathic effect (CPE) (trial 1) or by plaque reduction neutralization test (PRNT) (trial 2).

**`reverse transcription polymerase chain reaction assay`** — OBI:0001170 reverse transcription polymerase chain reaction assay  
- source: methods | section: RNA isolation and microarray and RT-PCR data generation | sentences: S47
  > For an independent verification of these genes, we assayed 10 day 3/day 0 and 15 day 7/day 0 changes in trial 1 by RT-PCR.

**`immunocytochemistry`** — OBI:0002174 immunocytochemistry  
- source: methods | section: Data analysis | sentences: S207
  > Immunofluorescence, immunoblot analysis and ELISA.

**`immunoblot assay`** — OBI:0001978 immunoblot assay  
- source: methods | section: Data analysis | sentences: S214
  > For immunoblot analysis, human total PBMC or BHK cells were lysed with 100 μl of M-PER mammalian protein extraction reagent (Pierce) containing Halt pro-tease inhibitor, EDTA and phosphatase inhibitor (Pierce).

**`enzyme-linked immunosorbent assay`** — OBI:0000661 enzyme-linked immunosorbent assay  
- source: methods | section: Data analysis | sentences: S218
  > C3a in plasma was measured by ELISA (Quidel A015).


---

## SDY1276 (21357945) — 3 benchmark / 3 ours

`data/31paper_assays/21357945_SDY1276_pdf/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Microarray Analysis` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `Hemagglutination inhibition (HAI) tests` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `Neutralizing antibody tests` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `Microarray Analysis`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: ? | section: Microarray Analysis
  > cRNA was hybridized onto Illumina Human HT-12v3 Expression BeadChips (Illumina), following the manufacturer’s protocol.


---

## SDY1276 (23878721) — 4 benchmark / 4 ours

`data/31paper_assays/23878721_SDY1276/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `global gene expression analysis` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `genotyping_by_array` | `genotyping assay`, `microarray assay` | obi_ancestry | **SPLIT** |
| `hemagglutination inhibition (HAI) test` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `neutralizing antibody test` | `pathogen neutralization assay` | name_containment | **MATCH_OBI_CONFLICT** |

### Conflicts (3)

**MATCH_OBI_CONFLICT — `global gene expression analysis`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: Measurement of global transcript abundance | sentences: S135
  > cRNA was hybridized onto Illumina HumanHT-12v3 or HumanHT-12v4 Expression BeadChips (Illumina, Inc.), following the manufacturer’s protocol.

**SPLIT — `genotyping_by_array`**  
one benchmark assay matched 2 of our entries: `genotyping assay`, `microarray assay` (our term OBI:0000435 genotyping assay is broader than the benchmark's OBI:0001274 genotyping by array assay)

- `genotyping assay` — source: methods | section: Whole-genome genotyping | sentences: S130
  > Genotyping was performed on Illumina HumanOmniExpress microarrays (Illumina, Inc., San Diego, CA) following the manufacturer’s instructions.
- `microarray assay` — source: methods | section: Measurement of global transcript abundance | sentences: S135
  > cRNA was hybridized onto Illumina HumanHT-12v3 or HumanHT-12v4 Expression BeadChips (Illumina, Inc.), following the manufacturer’s protocol.

**MATCH_OBI_CONFLICT — `neutralizing antibody test`**  
benchmark maps this assay to OBI:0000872 serum neutralization of viral infectivity assay; we mapped it to OBI:0003796 pathogen neutralization assay

- `pathogen neutralization assay` — source: methods | section: Serum samples and antibody titer measurements | sentences: S142
  > Neutralizing antibody tests were performed as previously described ( Frank et al., 1980 ) except that hamster serum was not included.


---

## SDY1288 (30150281) — 5 benchmark / 6 ours

`data/31paper_assays/30150281_SDY1288/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `mass cytometry (CyTOF)` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `multiplex ELISA-based assay (Luminex)` | `enzyme-linked immunosorbent assay` | name | **MATCH_OBI_UNMAPPED** |
| `RNA-seq` | `RNA-seq assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `real-time RT–PCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |
| `Inhibition ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| — | `virus isolation` | — | **EXTRA** |
| — | `reverse transcription polymerase chain reaction assay` | — | **EXTRA** |

### Conflicts (1)

**MATCH_OBI_UNMAPPED — `multiplex ELISA-based assay (Luminex)`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `enzyme-linked immunosorbent assay` — source: methods | section: Study participants | sentences: S156
  > In addition, seroconversion by IgM capture ELISA and/or a >4-fold increase in antibody titer by Inhibition ELISA in paired acute and convalescent sera were evaluated (Galo et al , 2017 ).


### Extra assays not in the benchmark (2)

**`virus isolation`** — no OBI term  
- source: methods | section: Study participants | sentences: S155
  > Chikungunya cases were laboratory-confirmed by detection of CHIKV using real-time RT–PCR (Waggoner et al, 2016), in some cases followed by virus isolation, in acute-phase samples.

**`reverse transcription polymerase chain reaction assay`** — OBI:0001170 reverse transcription polymerase chain reaction assay  
- source: methods | section: Viral titer assays | sentences: S200
  > Primers for the E1 gene were designed to quantify CHIKV copies in each patient and were used at 300 nM final concentration.


---

## SDY1289 (19047440) — 12 benchmark / 6 ours

`data/31paper_assays/19047440_SDY1289/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `gene array` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `quantitative real-time PCR (qPCR)` | `real time polymerase chain reaction assay` | obi_exact | **MATCH** |
| `IL-1β ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `flow cytometry (Ki67 proliferation assay)` | `flow cytometry assay` | obi_exact | **MATCH** |
| `CFSE labeling` | `flow cytometry assay` | name | **MATCH_OBI_CONFLICT** |
| `cytometric bead assay (CBA)` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `polychromatic flow cytometry (intracellular cytokine staining)` | `flow cytometry assay` | obi_exact | **MATCH** |
| `FACS analysis of PBMCs (central memory Th1/Th2 phenotyping)` | `flow cytometry assay` | obi_exact | **MATCH** |
| `multiplex cytokine analysis` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `polychromatic flow cytometry (MIMIC DC/T cell co-culture)` | `flow cytometry assay` | obi_exact | **MATCH** |
| `microarray analysis (VaxDesign/MIMIC samples)` | `microarray assay` | name_containment | **MATCH_OBI_CONFLICT** |
| `lysis plaque assay` | `viral plaque assay` | obi_exact | **MATCH** |

### Conflicts (3)

**MATCH_OBI_CONFLICT — `gene array`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: Gene array analysis of whole-blood and VaxDesign samples. | sentences: S124
  > The biotinylated cRNA was hybridized onto Illumina Human RefSeq-8 BeadChips v2 (Montreal and Lausanne samples) or v3 (VaxDesign samples) at 58°C for 20 h and quantified using Illumina BeadStation 500GX scanner and Illumina BeadStudio v3 software.

**MATCH_OBI_CONFLICT — `CFSE labeling`**  
benchmark maps this assay to OBI:0002106 carboxyfluorescein succinimidyl ester staining assay; we mapped it to OBI:0000916 flow cytometry assay

- `flow cytometry assay` — source: methods | section: Proliferation and cytokine secretion assays. | sentences: S155
  > PBMCs from vaccinated volunteers were labeled with CFSE (Invitrogen), as previously described ( 64 ).

**MATCH_OBI_CONFLICT — `microarray analysis (VaxDesign/MIMIC samples)`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: Gene array analysis of whole-blood and VaxDesign samples. | sentences: S124
  > The biotinylated cRNA was hybridized onto Illumina Human RefSeq-8 BeadChips v2 (Montreal and Lausanne samples) or v3 (VaxDesign samples) at 58°C for 20 h and quantified using Illumina BeadStation 500GX scanner and Illumina BeadStudio v3 software.


---

## SDY1291 (23151505) — 4 benchmark / 4 ours

`data/31paper_assays/23151505_SDY1291_pdf/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Affymetrix Exon Microarray` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `RT-qPCR` | `real time polymerase chain reaction assay` | name | **MATCH_OBI_CONFLICT** |
| `Multiplex Cytokine Analysis` | `multiplex bead-based protein state immunoassay` | name | **MATCH_OBI_CONFLICT** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |

### Conflicts (3)

**MATCH_OBI_CONFLICT — `Affymetrix Exon Microarray`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: ? | section: Affymetrix Exon Arrays
  > RNA expression for the in vivo study and one in vitro study was analyzed using the Human Exon ST 1.0 microarray platform (Affymetrix)

**MATCH_OBI_CONFLICT — `RT-qPCR`**  
benchmark maps this assay to OBI:0000911 real time reverse-transcription polymerase chain reaction assay; we mapped it to OBI:0000893 real time polymerase chain reaction assay

- `real time polymerase chain reaction assay` — source: ? | section: Microarrays and Quantitative Real-Time PCR
  > Quantitative real-time PCR was performed as described in ref. 17.

**MATCH_OBI_CONFLICT — `Multiplex Cytokine Analysis`**  
benchmark maps this assay to OBI:0000920 cytometric bead array assay; we mapped it to OBI:0002970 multiplex bead-based protein state immunoassay

- `multiplex bead-based protein state immunoassay` — source: ? | section: Multiplex Cytokine Analysis
  > Serum cytokine analysis was performed using the Lincoplex High Sensitivity kit


---

## SDY1293 (20078211) — 2 benchmark / 3 ours

`data/31paper_assays/20078211_SDY1293_pdf/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `GeneChip analysis` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `real-time polymerase chain reaction` | `real time polymerase chain reaction assay` | name | **MATCH_OBI_CONFLICT** |
| — | `microscopy assay` | — | **EXTRA** |

### Conflicts (2)

**MATCH_OBI_CONFLICT — `GeneChip analysis`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: ? | section: Preparation of samples for GeneChip analysis
  > Preparation of cellular RNA and subsequent processing for GeneChip analysis were performed as described elsewhere [28], by use of the HG-U133 A 2.0 and HG-U133 Plus 2.0 GeneChips (Affymetrix)

**MATCH_OBI_CONFLICT — `real-time polymerase chain reaction`**  
benchmark maps this assay to OBI:0000911 real time reverse-transcription polymerase chain reaction assay; we mapped it to OBI:0000893 real time polymerase chain reaction assay

- `real time polymerase chain reaction assay` — source: ? | section: Real-time polymerase chain reaction
  > TaqMan Gene Expression Assays (Applied Biosystems) were used to detect genes in the immunoproteosome pathway (PSME2, PSMB9, PSMB6, and PSMA4) in 3 randomly chosen samples from protected and nonprotected persons


### Extra assays not in the benchmark (1)

**`microscopy assay`** — OBI:0002119 microscopy assay  
- source: ? | section: Clinical specimens
  > Infection with malaria was determined by detection of parasite in malaria thick blood smears during the 30 days after challenge.


---

## SDY1294 (28687661) — 4 benchmark / 5 ours

`data/31paper_assays/28687661_SDY1294/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `microarray analysis` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `flow_cytometry_immunophenotyping` | `flow cytometry assay` | obi_exact | **MATCH** |
| `plaque_reduction_neutralization_test` | `pathogen neutralization assay` | obi_exact | **MATCH** |
| `immunofluorescence_assay` | `immuno staining assay` | name | **MATCH_OBI_CONFLICT** |
| — | `NK-mediated ADCC assay` | — | **EXTRA** |

### Conflicts (2)

**MATCH_OBI_CONFLICT — `microarray analysis`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: RNA preparation and microarray hybridization | sentences: S54
  > After hybridization on Human PrimeView Arrays for 16 h at 45°C and rotation at 60 rpm in a Hybridization Oven 640 (Affymetrix), slides were washed and stained with a Fluidics Station 450 system (Affymetrix).

**MATCH_OBI_CONFLICT — `immunofluorescence_assay`**  
benchmark maps this assay to CHMO:0000087 fluorescence microscopy assay; we mapped it to OBI:0001632 immuno staining assay

- `immuno staining assay` — source: methods | section: Immunofluorescence assay to detect anti-Japanese encephalitis virus and anti-West Nile virus antibodies | sentences: S25
  > To determine the presence of anti-Japanese encephalitis virus (JEV) and anti-West Nile virus (WNV) antibodies in the serum samples, fluorescence microscopy was employed.


### Extra assays not in the benchmark (1)

**`NK-mediated ADCC assay`** — no OBI term  
- source: methods | section: Flow cytometry | sentences: S35
  > In the NK-mediated ADCC assay, target cells are coated with anti-P815 antibodies to serve as the Fc target cells for NK-mediated ADCC.


---

## SDY1325 (28137280) — 5 benchmark / 5 ours

`data/31paper_assays/28137280_SDY1325/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Serum bactericidal assay` | `bacterial neutralization assay` | name | **MATCH_OBI_UNMAPPED** |
| `enzyme-linked immunospot assay` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `Flow cytometry` | `flow cytometry assay` | name | **MATCH_OBI_UNMAPPED** |
| `Microarray assay` | `microarray assay` | obi_exact | **MATCH** |
| `real time reverse-transcription polymerase chain reaction assay` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

### Conflicts (2)

**MATCH_OBI_UNMAPPED — `Serum bactericidal assay`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `bacterial neutralization assay` — source: methods | section: Serum bactericidal assay | sentences: S57
  > Serum samples collected at days 0, 28 and 56 were assessed for human SBA activity against serogroup A (F8238) and serogroup C (C11).

**MATCH_OBI_UNMAPPED — `Flow cytometry`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `flow cytometry assay` — source: methods | section: Flow cytometric characterisation of B cells and plasma cells | sentences: S54
  > The cells were analysed on a Beckman-Coulter Cyan Flow Cytometer with 9-colour parameters.


---

## SDY1328 (26742691) — 4 benchmark / 4 ours

`data/31paper_assays/26742691_SDY1328/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `microarray` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `polychromatic FCM` | `flow cytometry assay` | obi_exact | **MATCH** |
| `multiplex ELISA protocol Human Inflammation multianalyte profiling` | `enzyme-linked immunosorbent assay` | name_containment | **MATCH_OBI_CONFLICT** |
| `haematologic markers` | `complete blood count` | name | **MATCH_OBI_UNMAPPED** |

### Conflicts (3)

**MATCH_OBI_CONFLICT — `microarray`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: Establishing gene-expression signature predictive of HBV vaccine response | sentences: S186
  > Three-hundred and thirty-five samples passing quality control were then amplified using the NuGEN amplification protocol and hybridized to Affymetrix HuRSTA-2a520709 chips (Affymetrix, Santa Clara, CA).

**MATCH_OBI_CONFLICT — `multiplex ELISA protocol Human Inflammation multianalyte profiling`**  
benchmark maps this assay to OBI:0000920 cytometric bead array assay; we mapped it to OBI:0000661 enzyme-linked immunosorbent assay

- `enzyme-linked immunosorbent assay` — source: methods | section: Antibody titres | sentences: S122
  > Anti-Cholera toxin B subunit (CTB) IgG were quantified in serum samples according to a GM1-enzyme-linked immunosorbent assay (ELISA) method adapted from Svennerholm et al.

**MATCH_OBI_UNMAPPED — `haematologic markers`**  
we mapped this assay to no OBI term

- `complete blood count` — source: methods | section: Haematologic measurements | sentences: S235
  > A panel of 3 standard haematologic markers (complete blood count) was measured on the 174 pre-vaccination samples taken 28 days prior to vaccination (V1) of the EM131 cohort.


---

## SDY1364 (23266342) — 3 benchmark / 3 ours

`data/31paper_assays/23266342_SDY1364/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `ELISpot` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |

---

## SDY1364 (23844129) — 5 benchmark / 5 ours

`data/31paper_assays/23844129_SDY1364/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Illumina microarray` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `IFN_gamma_ELISpot` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `flow_cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `quantitative_RT_PCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |
| `western_blot` | `western blot assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `Illumina microarray`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: Gene Expression Analysis | sentences: S106
  > Amplified RNA (750ng per array) was hybridized to the Illumina HumanHT-12 version 4 expression beadchip according to manufacturer’s instructions.


---

## SDY1373 (28854372) — 4 benchmark / 4 ours

`data/31paper_assays/28854372_SDY1373/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Flow cytometry assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| `multiplex bead-based protein state immunoassay` | `cytometric bead array assay` | name | **MATCH_OBI_CONFLICT** |
| `Enzyme linked immunosorbent assay` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `bulk RNA-seq assay` | `RNA sequencing assay` | obi_ancestry | **MATCH_GRANULARITY** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `multiplex bead-based protein state immunoassay`**  
benchmark maps this assay to OBI:0002970 multiplex bead-based protein state immunoassay; we mapped it to OBI:0000920 cytometric bead array assay

- `cytometric bead array assay` — source: methods | section: Cytokine and Chemokine Multiplex Analysis | sentences: S116
  > Samples were read in duplicates according to the manufacturer’s protocol on a Bio-Plex Luminex-200 (Bio-Rad) and analyzed using Bio-Plex Manager software.


---

## SDY1389 (30111633) — 5 benchmark / 5 ours

`data/31paper_assays/30111633_SDY1389/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Flow cytometry assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Bulk RNA sequencing assay` | `RNA sequencing assay` | name | **MATCH_OBI_UNMAPPED** |
| `cytometry time of flight assay` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `T cell proliferation assay` | `flow cytometry assay` | name | **MATCH_OBI_UNMAPPED** |
| `amplicon sequencing assay` | `T cell receptor repertoire sequencing assay` | name | **MATCH_OBI_CONFLICT** |
| — | `HLA multimer reagents` | — | **EXTRA** |

### Conflicts (3)

**MATCH_OBI_UNMAPPED — `Bulk RNA sequencing assay`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `RNA sequencing assay` — source: methods | section: Whole-Transcriptome Profiling by RNA-Sequencing | sentences: S21
  > Library was prepared using a poly-A pull-down and Illumina TruSeq RNA kit, and sequenced using Illumina HiSeq2000.

**MATCH_OBI_UNMAPPED — `T cell proliferation assay`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `flow cytometry assay` — source: methods | section: Flow cytometry and sorting | sentences: S18
  > Cells were acquired on an LSRII flow cytometer or sorted with Influx cell sorter (BD Biosciences) and analyzed using FlowJo (Treestar, Ashland, OR).

**MATCH_OBI_CONFLICT — `amplicon sequencing assay`**  
benchmark maps this assay to OBI:0002767 amplicon sequencing assay; we mapped it to OBI:0002990 T cell receptor repertoire sequencing assay

- `T cell receptor repertoire sequencing assay` — source: methods | section: Human T cell receptor (TCR) sequencing and analysis | sentences: S38
  > TCR-Vβ sequences were amplified from the indicated DNA quantities ( Table S3 ) with specific primers as published.


### Extra assays not in the benchmark (1)

**`HLA multimer reagents`** — no OBI term  
- source: methods | section: T cell proliferation assays | sentences: S36
  > Cells were stained with HLA multimer reagents containing epitopes of CMV (CMV-multimer) ( Table S2 ) as previously described.


---

## SDY1393 (36656789) — 3 benchmark / 3 ours

`data/31paper_assays/36656789_SDY1393/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `RNA-seq` | `RNA-seq assay` | obi_exact | **MATCH** |
| `HAI` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |

---

## SDY1596 (32005538) — 2 benchmark / 3 ours

`data/31paper_assays/32005538_SDY1596/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Luminex` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| — | `culturable microbial count assay` | — | **EXTRA** |

### Extra assays not in the benchmark (1)

**`culturable microbial count assay`** — no OBI term  
- source: methods | section: BCG culture in vitro | sentences: S23
  > Actual CFU counts were obtained by the culturable microbial count assay and used as a proxy for mycobacterial viability.


---

## SDY1630 (32059780) — 3 benchmark / 2 ours

`data/31paper_assays/32059780_SDY1630/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `flow cytometry analysis` | `flow cytometry assay` | obi_exact | **MATCH** |
| `in vitro cytokine stimulation and functional assays` | `flow cytometry assay` | name_containment | **MATCH_OBI_CONFLICT** |
| `whole transcriptome profiling by RNA sequencing (RNA-seq)` | `RNA sequencing assay` | obi_ancestry | **MATCH_GRANULARITY** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `in vitro cytokine stimulation and functional assays`**  
benchmark maps this assay to OBI:1110207 assay detecting IFN-gamma production; we mapped it to OBI:0000916 flow cytometry assay

- `flow cytometry assay` — source: methods | section: Flow cytometry analysis and cell sorting | sentences: S108
  > Flow cytometry data were acquired on a BD LSRII and analyzed using FCS express 6 ( De Novo Software) and custom Python scripts.


---

## SDY1640 (32473127) — 6 benchmark / 5 ours

`data/31paper_assays/32473127_SDY1640/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Activation Induced Marker (AIM) assay` | `flow cytometry assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `intracellular cytokine staining assay` | `flow cytometry assay` | name | **MATCH_OBI_CONFLICT** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `SARS-CoV-2 RBD ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `lateral_flow_serology` | `lateral flow assay` | name | **MATCH_OBI_UNMAPPED** |
| `cytokine bead assay` | `cytometric bead array assay` | obi_ancestry | **MATCH_GRANULARITY** |
| — | `polymerase chain reaction assay` | — | **EXTRA** |

### Conflicts (2)

**MATCH_OBI_CONFLICT — `intracellular cytokine staining assay`**  
benchmark maps this assay to OBI:0001632 immuno staining assay; we mapped it to OBI:0000916 flow cytometry assay

- `flow cytometry assay` — source: methods | section: Direct ex vivo PBMC immune cell phenotyping | sentences: S322
  > All samples were acquired on a BD FACSymphony cell sorter (BD Biosciences, San Diego, CA).

**MATCH_OBI_UNMAPPED — `lateral_flow_serology`**  
we mapped this assay to no OBI term

- `lateral flow assay` — source: methods | section: Convalescent COVID-19 Donors | sentences: S266
  > Following enrollment, whole blood from convalescent donors was run on a colloidal-gold immunochromatographic ‘lateral flow’ assay to evaluate for prior exposure to SARS-CoV-2.


### Extra assays not in the benchmark (1)

**`polymerase chain reaction assay`** — OBI:0002692 polymerase chain reaction assay  
- source: results | section: Immunological Phenotypes of Recovered COVID-19 Patients | sentences: S25
  > SARS-CoV-2 infection was determined by swab test viral PCR during the acute phase of the infection.


---

## SDY1654 (31624246) — 4 benchmark / 3 ours

`data/31paper_assays/31624246_SDY1654/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `single cell RNA-sequencing (scRNA-seq)` | `RNA sequencing assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `proliferation assay` | `flow cytometry assay` | name_containment | **MATCH_OBI_CONFLICT** |
| `quantitative real-time PCR (qPCR)` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `proliferation assay`**  
benchmark maps this assay to OBI:0000891 cell proliferation assay; we mapped it to OBI:0000916 flow cytometry assay

- `flow cytometry assay` — source: methods | section: Flow cytometry and proliferation assays | sentences: S405
  > To evaluate the expression of T cell surface markers by flow cytometry, we incubated tissue and blood cell suspensions with Human TruStain FcX (BioLegend) and stained with following fluorochrome-conjugated antibodies


---

## SDY1655 (32717743) — 3 benchmark / 3 ours

`data/31paper_assays/32717743_SDY1655/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RT-qPCR` | `real time reverse-transcription polymerase chain reaction assay` | obi_exact | **MATCH** |
| `Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71)` | — | — | **MISSED** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
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

## SDY1669 (32788292) — 7 benchmark / 8 ours

`data/31paper_assays/32788292_SDY1669/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `phospho-CyTOF` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `Olink multiplex inflammation panel` | `proximity extension assay`, `polymerase chain reaction assay` | obi_ancestry | **SPLIT** |
| `enzyme-linked immunosorbent assay (ELISA)` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `cellular indexing of transcriptomes and epitopes by sequencing (CITE-seq)` | `cellular indexing of transcriptomes and epitopes by sequencing` | obi_exact | **MATCH** |
| `bulk RNA sequencing (RNA-seq)` | `RNA sequencing assay` | name | **MATCH_OBI_UNMAPPED** |
| `PCR quantitation of bacterial 16S ribosomal RNA (rRNA) gene product` | `polymerase chain reaction assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `TLR4-based reporter assay` | `reporter cell line analyte detection bioassay` | name | **MATCH_OBI_UNMAPPED** |
| — | `flow cytometry assay` | — | **EXTRA** |

### Conflicts (3)

**SPLIT — `Olink multiplex inflammation panel`**  
one benchmark assay matched 2 of our entries: `proximity extension assay`, `polymerase chain reaction assay` (our term OBI:0003113 proximity extension assay is broader than the benchmark's OBI:0003112 Olink assay)

- `proximity extension assay` — source: results | section: Enhanced concentrations of cytokines and inflammatory mediators in plasma from COVID-19 patients | sentences: S58
  > Therefore, we evaluated cytokines and chemokines in plasma samples from the Atlanta cohort using the Olink multiplex inflammation panel that measures 92 different cytokines and chemokines.
- `polymerase chain reaction assay` — source: results | section: Severe COVID-19 infection is associated with the systemic release of bacterial products | sentences: S168
  > Notably, the plasma of severe and ICU patients had significantly higher levels of bacterial DNA, as measured by PCR quantitation of bacterial 16 S ribosomal RNA (rRNA) gene product, and of LPS, as measured by a TLR4-based reporter assay ( Fig.

**MATCH_OBI_UNMAPPED — `bulk RNA sequencing (RNA-seq)`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `RNA sequencing assay` — source: results | section: Single-cell transcriptional response to COVID-19 infection | sentences: S116
  > To investigate this further and to independently validate the observations in the CITE-seq analysis, we performed bulk RNA sequencing (RNA-seq) analysis of PBMCs in an extended group of subjects (17 COVID-19 patients and 17 healthy controls) from the same cohort.

**MATCH_OBI_UNMAPPED — `TLR4-based reporter assay`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `reporter cell line analyte detection bioassay` — source: results | section: Severe COVID-19 infection is associated with the systemic release of bacterial products | sentences: S168
  > Notably, the plasma of severe and ICU patients had significantly higher levels of bacterial DNA, as measured by PCR quantitation of bacterial 16 S ribosomal RNA (rRNA) gene product, and of LPS, as measured by a TLR4-based reporter assay ( Fig.


### Extra assays not in the benchmark (1)

**`flow cytometry assay`** — OBI:0000916 flow cytometry assay  
- source: results | section: COVID-19 results in functional impairment of blood myeloid cells and pDCs | sentences: S44
  > To test this, we performed ex vivo stimulation of PBMCs from healthy or COVID-19–infected individuals, using a mixture of synthetic TLR7 and TLR 8 (TLR7/8) and TLR3 ligands, which are known to be expressed by viruses, and we performed an intracellular staining assay to detect cytokine responses.


---

## SDY1708 (34128959) — 3 benchmark / 3 ours

`data/31paper_assays/34128959_SDY1708/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Mass cytometry` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `scRNA-seq` | `RNA sequencing assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `scATAC-seq` | `single-cell ATAC-seq` | obi_exact | **MATCH** |

---

## SDY180 (23601689) — 6 benchmark / 5 ours

`data/31paper_assays/23601689_SDY180/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Microarray Assay` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Hemagglutinin Inhibition Assay` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `Virus-Neutralization Assay` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |
| `Commercial immunoassays (pneumococcal polysaccharide antibody)` | — | — | **MISSED** |
| `Multiplex Cytokine Analysis` | `cytometric bead array assay` | obi_exact | **MATCH** |

### Conflicts (2)

**MATCH_OBI_CONFLICT — `Microarray Assay`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: Microarray Assay | sentences: S120
  > Amplified RNA was hybridized to Illumina HT-12 V3 beadchips (48,803 probes) and scanned on an Illumina Beadstation 500.

**MISSED — `Commercial immunoassays (pneumococcal polysaccharide antibody)`**  
no entry of ours matches this benchmark assay

- benchmark evidence — section: Experimental Procedures
  > Antibody response to 14 pneumococcal polysaccharides was measured by using commercial immunoassays.


---

## SDY1991 (35455361) — 4 benchmark / 6 ours

`data/31paper_assays/35455361_SDY1991/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RNA-Sequencing Assay` | `RNA sequencing assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `IFN-γ Capture Assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| — | `reverse transcription polymerase chain reaction assay` | — | **EXTRA** |
| — | `pathogen neutralization assay` | — | **EXTRA** |
| — | `IFN-γ Capture Assay` | — | **EXTRA** |

### Extra assays not in the benchmark (3)

**`reverse transcription polymerase chain reaction assay`** — OBI:0001170 reverse transcription polymerase chain reaction assay  
- source: methods | section: 2.1. Human Blood Samples | sentences: S12
  > The diagnosis of DENV infection was also confirmed if at least one of the following criteria was met in the acute phase serum: (1) positive reverse transcription-polymerase chain reaction (RT-PCR) of DENV RNA, (2) positive serology for dengue IgM, or (3) positive dengue-specific non-structural antigen-1 (NS1).

**`pathogen neutralization assay`** — OBI:0003796 pathogen neutralization assay  
- source: methods | section: 2.2. Serology | sentences: S19
  > The serology was performed by DENV-specific IgG ELISAs and flow cytometry-based neutralization assays, as previously described [ 26 ].

**`IFN-γ Capture Assay`** — no OBI term  
- source: methods | section: 2.4. IFN-γ Capture Assay and Cell Sorting for RNA-Seq | sentences: S25
  > IFNγ producing cells were labeled using an IFN-γ Secretion Assay–Detection kit (PE) (catalog #130-054-202, Miltenyi Biotec, Bergisch Gladbach, North Rhine-Westphalia, Germany) according to manufacturer’s instructions.


---

## SDY1995 (35062294) — 4 benchmark / 4 ours

`data/31paper_assays/35062294_SDY1995/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RNA Sequencing` | `RNA sequencing assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `Flow Cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Reverse transcription-PCR` | `reverse transcription polymerase chain reaction assay` | name | **MATCH_OBI_CONFLICT** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `Reverse transcription-PCR`**  
benchmark maps this assay to OBI:0000911 real time reverse-transcription polymerase chain reaction assay; we mapped it to OBI:0001170 reverse transcription polymerase chain reaction assay

- `reverse transcription polymerase chain reaction assay` — source: methods | section: 2.2. Dengue Serology and PCR Tests | sentences: S33
  > Reverse transcription-PCR was performed by using the DV1 and DV3 primer set [ 13 ] and the ALD 1 and ALD 2 primer set [ 14 ] in one reaction with details specified previously [ 15 ].


---

## SDY212 (25834109) — 7 benchmark / 7 ours

`data/31paper_assays/25834109_SDY212/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `CMV IgG ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `multiparametric flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Luminex system` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `whole_blood_microarray` | `microarray assay` | obi_exact | **MATCH** |
| `hemagglutination inhibition assay` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `snp_genotyping_array` | `microarray assay`, `genotyping by SNP array assay` | obi_ancestry | **SPLIT** |
| `plaque assay` | `viral plaque assay` | obi_exact | **MATCH** |

### Conflicts (1)

**SPLIT — `snp_genotyping_array`**  
one benchmark assay matched 2 of our entries: `microarray assay`, `genotyping by SNP array assay` (our term OBI:0001985 microarray assay is broader than the benchmark's OBI:0001274 genotyping by array assay)

- `microarray assay` — source: methods | section: Whole blood microarray analysis of gene expression | sentences: S112
  > For each sample, 750 ng of total RNA were hybridized to Beadchips (HumanHT-12v3 Expression Bead Chip, Illumina) that contains 48,771 probes for around 25,000 annotated genes.
- `genotyping by SNP array assay` — source: methods | section: Single-nucleotide polymorphism assay | sentences: S181
  > All samples were genotyped using the custom designed ImmunoChip array (Illumina).


---

## SDY2189 (34252919) — 10 benchmark / 9 ours

`data/31paper_assays/34252919_SDY2189/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Focus reduction neutralization titre assay` | `serum neutralization of viral infectivity assay` | obi_exact | **MATCH** |
| `Intracellular cytokine staining assay` | `flow cytometry assay` | name | **MATCH_OBI_CONFLICT** |
| `Bead-based antigen arrays` | `antibody detection by cytometric bead array assay` | obi_exact | **MATCH** |
| `CyTOF analysis of whole-blood samples` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `Plasma protein profiling using multiplex Olink panel` | `proximity extension assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `Single-molecule array` | — | — | **MISSED** |
| `Bulk transcriptomics` | `RNA sequencing assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `CITE-seq` | `cellular indexing of transcriptomes and epitopes by sequencing` | obi_exact | **MATCH** |
| `RNA isolation and qPCR` | `real time polymerase chain reaction assay` | name | **MATCH_OBI_CONFLICT** |

### Conflicts (3)

**MATCH_OBI_CONFLICT — `Intracellular cytokine staining assay`**  
benchmark maps this assay to OBI:0002766 cytokine assay; we mapped it to OBI:0000916 flow cytometry assay

- `flow cytometry assay` — source: methods | section: Intracellular cytokine staining assay | sentences: S166
  > Antigen-specific T cell responses were measured using the intracellular cytokine staining assay as previously described.

**MISSED — `Single-molecule array`**  
no entry of ours matches this benchmark assay

- benchmark evidence — section: Results
  > The concentration of IFNα2 (type I interferon) was not significantly increased on days 1 and 2 after vaccination, and the responses were just over the assay limit of the highly sensitive single-molecule array (SIMOA) (16 fg ml−1) (Extended Data Fig. 7c, d).

**MATCH_OBI_CONFLICT — `RNA isolation and qPCR`**  
benchmark maps this assay to OBI:0000911 real time reverse-transcription polymerase chain reaction assay; we mapped it to OBI:0000893 real time polymerase chain reaction assay

- `real time polymerase chain reaction assay` — source: methods | section: RNA isolation and qPCR | sentences: S315, S316, S317
  > The PCRs were carried out using Biorad Prime PCR reagents and SYBR green chemistry (SsoAdvanced Universal SYBR Green Supermix (cat. no. 1725272)) in Biorad CFX384 real-time PCR.


---

## SDY404 (25367297) — 3 benchmark / 3 ours

`data/31paper_assays/25367297_SDY404_pdf/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Flow Cytometry with Intracellular Cytokine Staining` | `flow cytometry assay` | obi_exact | **MATCH** |
| `hemagglutination_inhibition_assay` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |
| `Western Blot Analysis` | `western blot assay` | obi_exact | **MATCH** |

---

## SDY80 (24725414) — 4 benchmark / 4 ours

`data/31paper_assays/24725414_SDY80/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `flow cytometric analyses` | `flow cytometry assay` | obi_exact | **MATCH** |
| `transcriptome analyses using microarrays` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `microneutralization_assay` | `serum neutralization of viral infectivity assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `ELISpot assays` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `transcriptome analyses using microarrays`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: Experimental Procedures | sentences: S129
  > PBMCs were cryopreserved or lysed and stored at -80C for subsequent RNA extraction using miRNeasy (Qiagen) and hybridization to HG 1.0 ST arrays (Affymetrix).


---

## SDY984 (28502771) — 8 benchmark / 9 ours

`data/31paper_assays/28502771_SDY984/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Flow cytometry` | `flow cytometry assay` | obi_exact | **MATCH** |
| `Zostavax-specific IFN-γ, IL-4 and IL-21 ELISPOT` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `Zostavax-specific and total IgG B cell ELISPOT` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `Zostavax-specific IgG/IgA ELISA` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Viral DNA detection` | `polymerase chain reaction assay` | obi_exact | **MATCH** |
| `Multiplex cytokine assays` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `PBMC Transcriptomics analysis` | `microarray assay` | name | **MATCH_OBI_CONFLICT** |
| `Plasma Metabolomics analysis` | `liquid chromatography mass spectrometry assay` | obi_exact | **MATCH** |
| — | `sequencing assay` | — | **EXTRA** |
| — | `tandem mass spectrometry assay` | — | **EXTRA** |

### Conflicts (1)

**MATCH_OBI_CONFLICT — `PBMC Transcriptomics analysis`**  
benchmark maps this assay to OBI:0001463 transcription profiling by array assay; we mapped it to OBI:0001985 microarray assay

- `microarray assay` — source: methods | section: PBMC Transcriptomics analysis | sentences: S260
  > Samples, after quality control, were hybridized on Human U133 Plus 2.0 Arrays (Affymetrix).


### Extra assays not in the benchmark (2)

**`sequencing assay`** — OBI:0600047 sequencing assay  
- source: methods | section: Viral DNA detection | sentences: S245
  > The type of VZV DNA detected was identified on random positive samples by partial sequencing of amplicons to include codon 958 of ORF62, which distinguishes vaccine strain VZV (V-Oka) from wild type varicella

**`tandem mass spectrometry assay`** — OBI:0003540 tandem mass spectrometry assay  
- source: methods | section: Plasma Metabolomics analysis | sentences: S267
  > Metabolite confirmation was performed with tandem MS-MS experiments on Thermo QE HF, Orbitrap Fusion, or Finnigan LTQ FT Ultra mass spectrometers.
