# Assay extraction vs. curated benchmark

9 papers · 29 benchmark assays · 45 extracted assays

The benchmark is a **recall reference, not an exhaustive list** — on some papers it records one assay where the paper describes nine. Recall is therefore the headline metric and no precision figure is given; our unmatched assays are listed as EXTRA with their paper evidence to be judged individually.

## Totals

| Study | PMID | Benchmark | Ours | Matched | Missed | Extra | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| SDY1260 | 24336226 | 6 | 6 | 6 | 0 | 0 | 100% |
| SDY1264 | 19029902 | 1 | 9 | 1 | 0 | 8 | 100% |
| SDY1364 | 23266342 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY1393 | 36656789 | 3 | 3 | 3 | 0 | 0 | 100% |
| SDY1596 | 32005538 | 1 | 3 | 1 | 0 | 2 | 100% |
| SDY1708 | 34128959 | 3 | 4 | 3 | 0 | 1 | 100% |
| SDY1991 | 35455361 | 2 | 4 | 2 | 0 | 2 | 100% |
| SDY1995 | 35062294 | 2 | 4 | 2 | 0 | 2 | 100% |
| SDY2189 | 34252919 | 8 | 9 | 8 | 0 | 1 | 100% |
| **All** | | **29** | **45** | **29** | **0** | **16** | **100%** |

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

`data/claims/assay_registries/24336226_SDY1260/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `enzyme-linked immunosorbent assay` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `Luminex assay` | `cytometric bead array assay` | obi_exact | **MATCH** |
| `flow cytometry assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| `enzyme-linked immunospot assay` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `serum bactericidal activity assay` | `serum bactericidal titers (SBA)` | name | **MATCH_OBI_UNMAPPED** |
| `microarray assay` | `microarray assay` | obi_exact | **MATCH** |

### Conflicts (1)

**MATCH_OBI_UNMAPPED — `serum bactericidal activity assay`**  
we mapped this assay to no OBI term

- `serum bactericidal titers (SBA)` — source: methods | section: Measurement of serum bactericidal titers (SBA) | sentences: S292, S293, S294, S295, S296, S297, S298
  > Serum samples collected at days 0, 7, 30, 180 and year 2 were added undiluted to microtiter plates (Costar) and then serially diluted (3-fold) in Hank’s balanced salt solution (HBSS, GIBCO/Invitrogen). A pre-determined dilution of meningococcal reference bacterial stock (serogroup A, strain F8238 or serogroup C, strain C11) from a 4 h active culture grown in brain heart infusion (BHI) agar supplem …


---

## SDY1264 (19029902) — 1 benchmark / 9 ours

`data/claims/assay_registries/19029902_SDY1264/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `microarray assay` | `microarray assay` | obi_exact | **MATCH** |
| — | `multiplex bead-based protein state immunoassay` | — | **EXTRA** |
| — | `flow cytometry assay` | — | **EXTRA** |
| — | `serum neutralization of viral infectivity assay` | — | **EXTRA** |
| — | `plaque reduction neutralization test (PRNT)` | — | **EXTRA** |
| — | `real time reverse-transcription polymerase chain reaction assay` | — | **EXTRA** |
| — | `immunocytochemistry` | — | **EXTRA** |
| — | `western blot assay` | — | **EXTRA** |
| — | `enzyme-linked immunosorbent assay` | — | **EXTRA** |

### Extra assays not in the benchmark (8)

**`multiplex bead-based protein state immunoassay`** — OBI:0002970 multiplex bead-based protein state immunoassay  
- source: methods | section: Multiplex analysis | sentences: S165, S166
  > Assays were performed with the Beadlyte Human 22-Plex Multi-Cytokine Detection System with the addition of interferon-α2 and IL-1 receptor-α Beadmates to make a 24-plex assay (Upstate). Samples were run in duplicate following the manufacturer’s protocol on a Bio-Plex Luminex-100 station (Bio-Rad).

**`flow cytometry assay`** — OBI:0000916 flow cytometry assay  
- source: methods | section: Multiplex analysis | sentences: S169, S170, S171, S172, S173, S174, S175
  > Flow cytometric analysis. PBMCs from all time points for an individual were thawed, stained and acquired in parallel. Monocytes were gated as HLA-DR + CD14 + with the addition of CD16 to delineate the subpopulation of inflammatory monocytes. Myeloid DCs were gated as lineage cocktail HLA-DR + CD11c + , and plasmacytoid DCs were gated as lineage cocktail HLA-DR + CD123 + . CD86 expression was used …

**`serum neutralization of viral infectivity assay`** — OBI:0000872 serum neutralization of viral infectivity assay  
- source: methods | section: Assay for yellow fever virus (YFV) neutralizing antibodies | sentences: S179, S180, S181, S182
  > YFV neutralizing antibodies were measured by cytopathic effect (CPE) (trial 1) or by plaque reduction neutralization test (PRNT) (trial 2). In brief, for neutralizing antibodies by CPE, plasma dilutions in triplicate were incubated with 1,000 plaque-forming units of YFV at 37 °C for 1 h in 96-well flat-bottomed plates. Five thousand Vero cells were added to each well and the plates stained with cr …

**`plaque reduction neutralization test (PRNT)`** — no OBI term  
- source: methods | section: Assay for yellow fever virus (YFV) neutralizing antibodies | sentences: S179, S183, S184, S185
  > YFV neutralizing antibodies were measured by cytopathic effect (CPE) (trial 1) or by plaque reduction neutralization test (PRNT) (trial 2). For the PRNT, various dilutions of the sera were incubated overnight at 4 °C with 200 plaque-forming units of YFV. Vero cell monolayers in drained six-well plates were incubated with this virus-serum mixture for 1 h at 37 °C. The wells were overlaid with a mix …

**`real time reverse-transcription polymerase chain reaction assay`** — OBI:0000911 real time reverse-transcription polymerase chain reaction assay  
- source: methods | section: RNA isolation and microarray and RT-PCR data generation | sentences: S196, S197, S198
  > For RT-PCR analysis, Applied Biosystems constructed a custom TaqMan Gene Expression Plate Assay for 48 genes in their database. Two-step RT-PCR was performed. Values obtained by RT-PCR of genes from the custom TaqMan Gene Expression plate (Applied Biosystems) were normalized to the average cycling threshold value of the ‘housekeeping’ genes encoding 18S rRNA (Hs99999901_s1), β-actin (Hs99999903_m1 …

**`immunocytochemistry`** — OBI:0002174 immunocytochemistry  
- source: methods | section: Data analysis | sentences: S208, S209, S210, S211, S212, S213
  > BHK cells were cultured on cover slips in 24-well plate and stimulated with YF-17D. Cells were fixed with 3.7% formaldehyde and permeabilized with 0.5% saponin (Sigma). Cells were then incubated with anti-TIAR (C-18) (Santa Cruz 1749, 1:50) for 2 h at room temperature. After washing, cells were incubated with donkey anti-goat secondary antibody coupled to fluorescein isothiocyanate (Santa Cruz 202 …

**`western blot assay`** — OBI:0000854 western blot assay  
- source: methods | section: Data analysis | sentences: S214, S215, S216, S217
  > For immunoblot analysis, human total PBMC or BHK cells were lysed with 100 μl of M-PER mammalian protein extraction reagent (Pierce) containing Halt pro-tease inhibitor, EDTA and phosphatase inhibitor (Pierce). Equal amounts of protein were subjected to SDS-PAGE and transferred onto PVDF membranes. The blot was detected with anti-eIF2α and anti-phospho-eIF2α (Cell Signaling 9722) and developed wit …

**`enzyme-linked immunosorbent assay`** — OBI:0000661 enzyme-linked immunosorbent assay  
- source: methods | section: Data analysis | sentences: S218
  > C3a in plasma was measured by ELISA (Quidel A015).


---

## SDY1364 (23266342) — 3 benchmark / 3 ours

`data/claims/assay_registries/23266342_SDY1364/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `enzyme-linked immunospot assay` | `enzyme-linked immunospot assay` | obi_exact | **MATCH** |
| `flow cytometry assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| `enzyme-linked immunosorbent assay` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |

---

## SDY1393 (36656789) — 3 benchmark / 3 ours

`data/claims/assay_registries/36656789_SDY1393/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `flow cytometry assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| `RNA-seq assay` | `RNA-seq assay` | obi_exact | **MATCH** |
| `viral hemagglutination inhibition assay` | `viral hemagglutination inhibition assay` | obi_exact | **MATCH** |

---

## SDY1596 (32005538) — 1 benchmark / 3 ours

`data/claims/assay_registries/32005538_SDY1596/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `Luminex assay` | `cytometric bead array assay` | obi_exact | **MATCH** |
| — | `flow cytometry assay` | — | **EXTRA** |
| — | `culturable microbial count assay` | — | **EXTRA** |

### Extra assays not in the benchmark (2)

**`flow cytometry assay`** — OBI:0000916 flow cytometry assay  
- source: methods | section: Relative quantitation of bacterial RNA by flow cytometry | sentences: S21
  > Mean fluorescence intensity of the RNA dye was assessed by flow cytometry (LSR Fortessa, BD Biosciences).

**`culturable microbial count assay`** — no OBI term  
- source: methods | section: BCG culture in vitro | sentences: S23, S24, S25, S26, S27
  > Actual CFU counts were obtained by the culturable microbial count assay and used as a proxy for mycobacterial viability. Actual CFU were compared to estimated CFU calculated based on information on the vaccine inserts provided by the respective manufacturer, and verified by the WHO National Institute for Biological Standards and Controls (NIBSCs) for prequalified manufacturers ( Table 1 ). BCG via …


---

## SDY1708 (34128959) — 3 benchmark / 4 ours

`data/claims/assay_registries/34128959_SDY1708/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `cytometry time of flight assay` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `single-cell RNA sequencing assay` | `single-cell RNA sequencing assay` | obi_exact | **MATCH** |
| `single-cell ATAC-seq` | `single-cell ATAC-seq` | obi_exact | **MATCH** |
| — | `carbon-copy chromosome conformation capture assay followed by sequencing assay` | — | **EXTRA** |

### Extra assays not in the benchmark (1)

**`carbon-copy chromosome conformation capture assay followed by sequencing assay`** — OBI:0002042 carbon-copy chromosome conformation capture assay followed by sequencing assay  
- source: results | section: NF-κB inactivity may underlie poor pro-inflammatory cytokine production in peripheral monocytes of severe COVID-19 patients | sentences: S141, S142
  > We identified a putative enhancer downstream of IL1B , which shows linkage to the IL1B promoter via single-cell coaccessibility analysis and chromosome conformation capture Hi-C data from the THP-1 monocytic cell line ( Fig. 5 D ; see Materials and methods; Phanstiel et al., 2017 ).


---

## SDY1991 (35455361) — 2 benchmark / 4 ours

`data/claims/assay_registries/35455361_SDY1991/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RNA-seq assay` | `bulk RNA-seq assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `flow cytometry assay` | `flow cytometry-based neutralization assays` | name_containment | **MATCH_OBI_UNMAPPED** |
| — | `enzyme-linked immunosorbent assay` | — | **EXTRA** |
| — | `cytokine assay` | — | **EXTRA** |

### Conflicts (1)

**MATCH_OBI_UNMAPPED — `flow cytometry assay`**  
we mapped this assay to no OBI term

- `flow cytometry-based neutralization assays` — source: methods | section: 2.2. Serology | sentences: S19
  > The serology was performed by DENV-specific IgG ELISAs and flow cytometry-based neutralization assays, as previously described [ 26 ].


### Extra assays not in the benchmark (2)

**`enzyme-linked immunosorbent assay`** — OBI:0000661 enzyme-linked immunosorbent assay  
- source: methods | section: 2.2. Serology | sentences: S19
  > The serology was performed by DENV-specific IgG ELISAs and flow cytometry-based neutralization assays, as previously described [ 26 ].

**`cytokine assay`** — OBI:0002766 cytokine assay  
- source: methods | section: 2.4. IFN-γ Capture Assay and Cell Sorting for RNA-Seq | sentences: S24, S25
  > After overnight resting, cells were stimulated with DENV CD8 megapool (1 ug/mL final concentration) for 3 h at 37 °C. IFNγ producing cells were labeled using an IFN-γ Secretion Assay–Detection kit (PE) (catalog #130-054-202, Miltenyi Biotec, Bergisch Gladbach, North Rhine-Westphalia, Germany) according to manufacturer’s instructions.


---

## SDY1995 (35062294) — 2 benchmark / 4 ours

`data/claims/assay_registries/35062294_SDY1995/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `RNA-seq assay` | `RNA sequencing assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `flow cytometry assay` | `flow cytometry assay` | obi_exact | **MATCH** |
| — | `enzyme-linked immunosorbent assay` | — | **EXTRA** |
| — | `reverse transcription polymerase chain reaction assay` | — | **EXTRA** |

### Extra assays not in the benchmark (2)

**`enzyme-linked immunosorbent assay`** — OBI:0000661 enzyme-linked immunosorbent assay  
- source: methods | section: 2.2. Dengue Serology and PCR Tests | sentences: S32
  > DENV serology tests were performed with anti-DENV IgG and IgM ELISA as previously described [ 12 ].

**`reverse transcription polymerase chain reaction assay`** — OBI:0001170 reverse transcription polymerase chain reaction assay  
- source: methods | section: 2.2. Dengue Serology and PCR Tests | sentences: S33
  > Reverse transcription-PCR was performed by using the DV1 and DV3 primer set [ 13 ] and the ALD 1 and ALD 2 primer set [ 14 ] in one reaction with details specified previously [ 15 ].


---

## SDY2189 (34252919) — 8 benchmark / 9 ours

`data/claims/assay_registries/34252919_SDY2189/assays_benchmark.json`

| Benchmark assay | Our assay | Tier | Status |
|---|---|---|---|
| `enzyme-linked immunosorbent assay` | `enzyme-linked immunosorbent assay` | obi_exact | **MATCH** |
| `RNA-seq assay` | `bulk RNA-seq assay` | obi_ancestry | **MATCH_GRANULARITY** |
| `cellular indexing of transcriptomes and epitopes by sequencing` | `cellular indexing of transcriptomes and epitopes by sequencing` | obi_exact | **MATCH** |
| `cytometry time of flight assay` | `cytometry time of flight assay` | obi_exact | **MATCH** |
| `?Neutralizing Antibody Titer Assay?` | `serum neutralization of viral infectivity assay` | name_containment | **MATCH_OBI_UNMAPPED** |
| `Olink assay` | `Olink assay` | obi_exact | **MATCH** |
| `flow cytometry assay` | `immuno staining assay` | name | **MATCH_OBI_CONFLICT** |
| `?` | `antigen specific antibodies assay` | name | **MATCH_OBI_UNMAPPED** |
| — | `real time reverse-transcription polymerase chain reaction assay` | — | **EXTRA** |

### Conflicts (3)

**MATCH_OBI_UNMAPPED — `?Neutralizing Antibody Titer Assay?`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `serum neutralization of viral infectivity assay` — source: methods | section: Focus reduction neutralization titre assay | sentences: S134, S135, S136, S137, S138, S139, S140, S141
  > Neutralization assays with authentic SARS-CoV-2 virus (infectious clone SARS-CoV-2 derived from 2019-nCoV/USA_WA1/2020 strain) were performed as previously described 31 . Sera samples were serially diluted (threefold) in serum-free Dulbecco’s modified Eagle’s medium (DMEM) in duplicate wells and incubated with 100–200 focus-forming units infectious clone derived SARS-CoV-2-mNG virus 32 at 37 °C fo …

**MATCH_OBI_CONFLICT — `flow cytometry assay`**  
benchmark maps this assay to OBI:0000916 flow cytometry assay; we mapped it to OBI:0001632 immuno staining assay

- `immuno staining assay` — source: methods | section: Intracellular cytokine staining assay | sentences: S166, S167, S168, S169, S170, S179, S180
  > Antigen-specific T cell responses were measured using the intracellular cytokine staining assay as previously described 35 . Live frozen PBMCs were revived, counted and resuspended at a density of 2 million live cells per ml in complete RPMI (RPMI supplemented with 10% FBS and antibiotics). The cells were rested overnight at 37 °C in a CO 2 incubator. The next morning, the cells were counted again …

**MATCH_OBI_UNMAPPED — `?`**  
the benchmark key is not an OBI term, so the mapping cannot be compared

- `antigen specific antibodies assay` — source: methods | section: Bead-based antigen arrays | sentences: S182, S186, S189, S190, S191, S192
  > We used an existing bead-based autoantigen array, and a cytokine array with expanded content that was based on recent COVID-19 studies 16 . Antigens were coupled to carboxylated magnetic beads (MagPlex-C, Luminex) such that each antigen was linked to beads with unique barcodes, as previously described 16 , 36 , 37 . Serum samples were tested at 1:100 dilution in 0.05% PBS-Tween supplemented with 1 …


### Extra assays not in the benchmark (1)

**`real time reverse-transcription polymerase chain reaction assay`** — OBI:0000911 real time reverse-transcription polymerase chain reaction assay  
- source: methods | section: RNA isolation and qPCR | sentences: S308, S311, S314, S315
  > RNA was isolated using Aurum Total RNA minikit (Biorad, cat. no. 7326820) following the manufacturer’s protocol. cDNA was synthesized using iScript Advanced cDNA synthesis kit (Biorad, cat. no. 1725038) using 150 ng total RNA in 20 μl volume. The cDNA samples were diluted 5-fold by adding 80 μl sterile nuclease-free water and 5 μl of cDNA was used for PCR reaction. The PCRs were carried out using …
