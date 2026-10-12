# Curator review: 16 assays the agent found that the benchmark does not list

**What this is.** When the agent's assay registry (`data/31paper_assays/<pmid>_<SDY>/assays_benchmark.json`) was compared with the curated benchmark (`data/benchmark_assay/`), the agent had 20 assays the benchmark does not list (status EXTRA in `comparison/comparison.json`). Four of them are not real extras and are excluded (see the end of this file). This file lists the remaining 16, each with the paper evidence, what the benchmark lists for that paper, and our initial assessment. **The curator decides** whether each one should be added to the benchmark.

All quotes come from the evidence field of the agent's registry and were checked against the paper text in `data/JAT_XML/` (SDY1293 is PDF only and was not checked). `generate_claim` says whether the paper reports a finding drawn from the assay; it is the agent's judgement and has not been verified.

## Overview

| # | Paper | Agent's assay | Wording in paper | generate_claim | Initial assessment |
|---|---|---|---|---|---|
| 1 | SDY1264 / PMID 19029902 | enzyme-linked immunosorbent assay | ELISA | True | Suggest adding to the benchmark |
| 2 | SDY1294 / PMID 28687661 | NK-mediated ADCC assay | NK-mediated ADCC assay | True | Suggest adding to the benchmark |
| 3 | SDY1596 / PMID 32005538 | culturable microbial count assay | culturable microbial count assay | True | Suggest adding to the benchmark |
| 4 | SDY1669 / PMID 32788292 | flow cytometry assay | intracellular staining assay | True | Suggest adding to the benchmark |
| 5 | SDY1264 / PMID 19029902 | reverse transcription polymerase chain reaction assay | RT-PCR | True | Curator to decide |
| 6 | SDY1264 / PMID 19029902 | immunocytochemistry | Immunofluorescence | True | Curator to decide |
| 7 | SDY1264 / PMID 19029902 | immunoblot assay | immunoblot analysis | True | Curator to decide |
| 8 | SDY1293 / PMID 20078211 | microscopy assay | malaria thick blood smears | True | Curator to decide |
| 9 | SDY1991 / PMID 35455361 | pathogen neutralization assay | flow cytometry-based neutralization assays | False | Curator to decide |
| 10 | SDY1389 / PMID 30111633 | HLA multimer reagents | HLA multimer reagents | True | Suggest folding into an existing entry (our side) |
| 11 | SDY1655 / PMID 32717743 | enzyme-linked immunosorbent assay | ELISA | True | Suggest folding into an existing entry (our side) |
| 12 | SDY984 / PMID 28502771 | sequencing assay | partial sequencing of amplicons | False | Suggest folding into an existing entry (our side) |
| 13 | SDY984 / PMID 28502771 | tandem mass spectrometry assay | tandem MS-MS experiments | False | Suggest folding into an existing entry (our side) |
| 14 | SDY1288 / PMID 30150281 | virus isolation | virus isolation | False | Suggest not listing |
| 15 | SDY1640 / PMID 32473127 | polymerase chain reaction assay | viral PCR | True | Suggest not listing |
| 16 | SDY1991 / PMID 35455361 | reverse transcription polymerase chain reaction assay | reverse transcription-polymerase chain reaction (RT-PCR) | False | Suggest not listing |

By initial assessment: Suggest adding to the benchmark: 4; Curator to decide: 5; Suggest folding into an existing entry (our side): 4; Suggest not listing: 3.

---

## 1. SDY1264 / PMID 19029902 — enzyme-linked immunosorbent assay

**Agent entry** (`data/31paper_assays/19029902_SDY1264/assays_benchmark.json`)
- name_in_paper: ELISA
- aliases: (none)
- OBI: **OBI:0000661 enzyme-linked immunosorbent assay**
- generate_claim: True; source: methods

**Paper evidence** (section *Data analysis*, sentences S218; verbatim match with the JATS XML)
> "C3a in plasma was measured by ELISA (Quidel A015)."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1264_Assay_Hailong.json`): microarray; Luminex assay; Flow cytometric analysis; Assay for yellow fever virus (YFV) neutralizing antibodies

**Initial assessment: Suggest adding to the benchmark.** Measures plasma C3a: a real measurement on subject samples, and our registry records that the paper reports a finding from it (generate_claim = true). The benchmark has no ELISA entry for this paper.

---

## 2. SDY1294 / PMID 28687661 — NK-mediated ADCC assay

**Agent entry** (`data/31paper_assays/28687661_SDY1294/assays_benchmark.json`)
- name_in_paper: NK-mediated ADCC assay
- aliases: antibody-dependent cell-mediated cytotoxicity (ADCC) assay; ADCC activity
- OBI: (not mapped to an OBI term)
- generate_claim: True; source: methods

**Paper evidence** (section *Flow cytometry*, sentences S35; verbatim match with the JATS XML)
> "In the NK-mediated ADCC assay, target cells are coated with anti-P815 antibodies to serve as the Fc target cells for NK-mediated ADCC."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1294_assays_AS_v2.json`): microarray analysis; flow_cytometry_immunophenotyping; plaque_reduction_neutralization_test; immunofluorescence_assay

**Initial assessment: Suggest adding to the benchmark.** An NK-mediated ADCC functional assay: a distinct measurement technique, and the paper reports ADCC activity results. The benchmark has no matching entry for this paper.

---

## 3. SDY1596 / PMID 32005538 — culturable microbial count assay

**Agent entry** (`data/31paper_assays/32005538_SDY1596/assays_benchmark.json`)
- name_in_paper: culturable microbial count assay
- aliases: CFU counts; formation of CFU
- OBI: (not mapped to an OBI term)
- generate_claim: True; source: methods

**Paper evidence** (section *BCG culture in vitro*, sentences S23; verbatim match with the JATS XML)
> "Actual CFU counts were obtained by the culturable microbial count assay and used as a proxy for mycobacterial viability."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1596_Assay_Hailong.json`): Luminex; Flow Cytometry

**Initial assessment: Suggest adding to the benchmark.** CFU counts measure BCG mycobacterial viability: a distinct measurement, and the paper reports results from it. The benchmark has no matching entry for this paper.

---

## 4. SDY1669 / PMID 32788292 — flow cytometry assay

**Agent entry** (`data/31paper_assays/32788292_SDY1669/assays_benchmark.json`)
- name_in_paper: intracellular staining assay
- aliases: (none)
- OBI: **OBI:0000916 flow cytometry assay**
- generate_claim: True; source: results

**Paper evidence** (section *COVID-19 results in functional impairment of blood myeloid cells and pDCs*, sentences S44; verbatim match with the JATS XML)
> "To test this, we performed ex vivo stimulation of PBMCs from healthy or COVID-19–infected individuals, using a mixture of synthetic TLR7 and TLR 8 (TLR7/8) and TLR3 ligands, which are known to be expressed by viruses, and we performed an intracellular staining assay to detect cytokine responses."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1669_assays_AS_v2.json`): phospho-CyTOF; Olink multiplex inflammation panel; enzyme-linked immunosorbent assay (ELISA); cellular indexing of transcriptomes and epitopes by sequencing (CITE-seq); bulk RNA sequencing (RNA-seq); PCR quantitation of bacterial 16S ribosomal RNA (rRNA) gene product; TLR4-based reporter assay

**Initial assessment: Suggest adding to the benchmark.** Intracellular cytokine staining after stimulating PBMCs with TLR7/8 and TLR3 ligands; the paper uses it to report functional impairment of myeloid cells and pDCs. The benchmark has no matching entry for this paper.

---

## 5. SDY1264 / PMID 19029902 — reverse transcription polymerase chain reaction assay

**Agent entry** (`data/31paper_assays/19029902_SDY1264/assays_benchmark.json`)
- name_in_paper: RT-PCR
- aliases: (none)
- OBI: **OBI:0001170 reverse transcription polymerase chain reaction assay**
- generate_claim: True; source: methods

**Paper evidence** (section *RNA isolation and microarray and RT-PCR data generation*, sentences S47; verbatim match with the JATS XML)
> "For an independent verification of these genes, we assayed 10 day 3/day 0 and 15 day 7/day 0 changes in trial 1 by RT-PCR."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1264_Assay_Hailong.json`): microarray; Luminex assay; Flow cytometric analysis; Assay for yellow fever virus (YFV) neutralizing antibodies

**Initial assessment: Curator to decide.** RT-PCR is used to independently verify 10 day-3 and 15 day-7 gene changes from the microarray. It is a verification experiment whose readout overlaps the benchmark's existing microarray entry.

---

## 6. SDY1264 / PMID 19029902 — immunocytochemistry

**Agent entry** (`data/31paper_assays/19029902_SDY1264/assays_benchmark.json`)
- name_in_paper: Immunofluorescence
- aliases: Fluorescence microscopy
- OBI: **OBI:0002174 immunocytochemistry**
- generate_claim: True; source: methods

**Paper evidence** (section *Data analysis*, sentences S207; verbatim match with the JATS XML)
> "Immunofluorescence, immunoblot analysis and ELISA."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1264_Assay_Hailong.json`): microarray; Luminex assay; Flow cytometric analysis; Assay for yellow fever virus (YFV) neutralizing antibodies

**Initial assessment: Curator to decide.** The only evidence is the Methods subsection heading “Immunofluorescence, immunoblot analysis and ELISA.” It is a mechanistic side experiment.

---

## 7. SDY1264 / PMID 19029902 — immunoblot assay

**Agent entry** (`data/31paper_assays/19029902_SDY1264/assays_benchmark.json`)
- name_in_paper: immunoblot analysis
- aliases: (none)
- OBI: **OBI:0001978 immunoblot assay**
- generate_claim: True; source: methods

**Paper evidence** (section *Data analysis*, sentences S214; verbatim match with the JATS XML)
> "For immunoblot analysis, human total PBMC or BHK cells were lysed with 100 μl of M-PER mammalian protein extraction reagent (Pierce) containing Halt pro-tease inhibitor, EDTA and phosphatase inhibitor (Pierce)."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1264_Assay_Hailong.json`): microarray; Luminex assay; Flow cytometric analysis; Assay for yellow fever virus (YFV) neutralizing antibodies

**Initial assessment: Curator to decide.** Immunoblotting of lysed PBMC or BHK cells. It is a mechanistic side experiment.

---

## 8. SDY1293 / PMID 20078211 — microscopy assay

**Agent entry** (`data/31paper_assays/20078211_SDY1293_pdf/assays_benchmark.json`)
- name_in_paper: malaria thick blood smears
- aliases: (none)
- OBI: **OBI:0002119 microscopy assay**
- generate_claim: True; source: None

**Paper evidence** (section *Clinical specimens*, sentences none; PDF only; not checked against XML)
> "Infection with malaria was determined by detection of parasite in malaria thick blood smears during the 30 days after challenge."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1293_assays_AS_v2.json`): GeneChip analysis; real-time polymerase chain reaction

**Initial assessment: Curator to decide.** Thick blood smears detect parasites in the 30 days after challenge. If the paper groups subjects by infected / protected, this assay defines the groups and is worth listing; if it is only background, it can be left out.

---

## 9. SDY1991 / PMID 35455361 — pathogen neutralization assay

**Agent entry** (`data/31paper_assays/35455361_SDY1991/assays_benchmark.json`)
- name_in_paper: flow cytometry-based neutralization assays
- aliases: (none)
- OBI: **OBI:0003796 pathogen neutralization assay**
- generate_claim: False; source: methods

**Paper evidence** (section *2.2. Serology*, sentences S19; verbatim match with the JATS XML)
> "The serology was performed by DENV-specific IgG ELISAs and flow cytometry-based neutralization assays, as previously described [ 26 ]."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1991_Assay_Hailong.json`): RNA-Sequencing Assay; ELISA; flow cytometry; IFN-γ Capture Assay

**Initial assessment: Curator to decide.** A flow cytometry-based neutralization assay used for serological classification (“as previously described”); the paper reports no finding from it. If the paper groups subjects by primary / secondary infection, it may define the groups.

---

## 10. SDY1389 / PMID 30111633 — HLA multimer reagents

**Agent entry** (`data/31paper_assays/30111633_SDY1389/assays_benchmark.json`)
- name_in_paper: HLA multimer reagents
- aliases: CMV-multimer
- OBI: (not mapped to an OBI term)
- generate_claim: True; source: methods

**Paper evidence** (section *T cell proliferation assays*, sentences S36; verbatim match with the JATS XML)
> "Cells were stained with HLA multimer reagents containing epitopes of CMV (CMV-multimer) ( Table S2 ) as previously described."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1389_assay_AS.json`): Flow cytometry assay; Bulk RNA sequencing assay; cytometry time of flight assay; T cell proliferation assay; amplicon sequencing assay

**Initial assessment: Suggest folding into an existing entry (our side).** HLA multimers are a flow cytometry staining reagent, not a separate assay technique. They belong under the benchmark's existing “Flow cytometry and sorting” or “T cell proliferation assays” entry.

---

## 11. SDY1655 / PMID 32717743 — enzyme-linked immunosorbent assay

**Agent entry** (`data/31paper_assays/32717743_SDY1655/assays_benchmark.json`)
- name_in_paper: ELISA
- aliases: (none)
- OBI: **OBI:0000661 enzyme-linked immunosorbent assay**
- generate_claim: True; source: results

**Paper evidence** (section *Overview of COVID-19 immunological features*, sentences S23, S24; checked against the JATS XML: matches, except that “Extended Data Fig. 9” after “gating strategy in” is omitted)
> "We analysed PBMC and plasma samples from patients with moderate or severe COVID-19 and healthy HCW donors ( Fig. 1a , gating strategy in) by flow cytometry and ELISA to quantify leuko- cytes and soluble mediators, respectively."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1655_assays_AS_v2.json`): RT-qPCR; Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71); flow cytometry

**Initial assessment: Suggest folding into an existing entry (our side).** In the Results, “ELISA” is used loosely for the plasma soluble-mediator measurements. This is very likely the benchmark's “Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71)” (Eve Technologies multiplex panel), which was scored as missed. If confirmed, this is not an extra: our name and OBI mapping for HD71 are wrong, and that missed entry should go away too.

---

## 12. SDY984 / PMID 28502771 — sequencing assay

**Agent entry** (`data/31paper_assays/28502771_SDY984/assays_benchmark.json`)
- name_in_paper: partial sequencing of amplicons
- aliases: (none)
- OBI: **OBI:0600047 sequencing assay**
- generate_claim: False; source: methods

**Paper evidence** (section *Viral DNA detection*, sentences S245; verbatim match with the JATS XML)
> "The type of VZV DNA detected was identified on random positive samples by partial sequencing of amplicons to include codon 958 of ORF62, which distinguishes vaccine strain VZV (V-Oka) from wild type varicella"

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY984_assays_AS_v2.json`): Flow cytometry; Zostavax-specific IFN-γ, IL-4 and IL-21 ELISPOT; Zostavax-specific and total IgG B cell ELISPOT; Zostavax-specific IgG/IgA ELISA; Viral DNA detection; Multiplex cytokine assays; PBMC Transcriptomics analysis; Plasma Metabolomics analysis

**Initial assessment: Suggest folding into an existing entry (our side).** Partial amplicon sequencing of random positive samples to tell vaccine strain (V-Oka) from wild type. It is a sub-step of the benchmark's existing “Viral DNA detection” entry, and the paper reports no separate finding from it.

---

## 13. SDY984 / PMID 28502771 — tandem mass spectrometry assay

**Agent entry** (`data/31paper_assays/28502771_SDY984/assays_benchmark.json`)
- name_in_paper: tandem MS-MS experiments
- aliases: MS-MS
- OBI: **OBI:0003540 tandem mass spectrometry assay**
- generate_claim: False; source: methods

**Paper evidence** (section *Plasma Metabolomics analysis*, sentences S267; verbatim match with the JATS XML)
> "Metabolite confirmation was performed with tandem MS-MS experiments on Thermo QE HF, Orbitrap Fusion, or Finnigan LTQ FT Ultra mass spectrometers."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY984_assays_AS_v2.json`): Flow cytometry; Zostavax-specific IFN-γ, IL-4 and IL-21 ELISPOT; Zostavax-specific and total IgG B cell ELISPOT; Zostavax-specific IgG/IgA ELISA; Viral DNA detection; Multiplex cytokine assays; PBMC Transcriptomics analysis; Plasma Metabolomics analysis

**Initial assessment: Suggest folding into an existing entry (our side).** Tandem MS confirms metabolite identity. It is a sub-step of the benchmark's existing “Plasma Metabolomics analysis” entry, and the paper reports no separate finding from it.

---

## 14. SDY1288 / PMID 30150281 — virus isolation

**Agent entry** (`data/31paper_assays/30150281_SDY1288/assays_benchmark.json`)
- name_in_paper: virus isolation
- aliases: (none)
- OBI: (not mapped to an OBI term)
- generate_claim: False; source: methods

**Paper evidence** (section *Study participants*, sentences S155; verbatim match with the JATS XML)
> "Chikungunya cases were laboratory-confirmed by detection of CHIKV using real-time RT–PCR (Waggoner et al, 2016), in some cases followed by virus isolation, in acute-phase samples."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1288_assays_AS_v2.json`): mass cytometry (CyTOF); multiplex ELISA-based assay (Luminex); RNA-seq; real-time RT–PCR; Inhibition ELISA

**Initial assessment: Suggest not listing.** Used only to confirm chikungunya cases (in some samples, after RT–PCR). It is an inclusion criterion, not a study measurement, and the paper reports no finding from it.

---

## 15. SDY1640 / PMID 32473127 — polymerase chain reaction assay

**Agent entry** (`data/31paper_assays/32473127_SDY1640/assays_benchmark.json`)
- name_in_paper: viral PCR
- aliases: swab test viral PCR
- OBI: **OBI:0002692 polymerase chain reaction assay**
- generate_claim: True; source: results

**Paper evidence** (section *Immunological Phenotypes of Recovered COVID-19 Patients*, sentences S25; verbatim match with the JATS XML)
> "SARS-CoV-2 infection was determined by swab test viral PCR during the acute phase of the infection."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1640_assays_AS_v2.json`): Activation Induced Marker (AIM) assay; intracellular cytokine staining assay; flow cytometry; SARS-CoV-2 RBD ELISA; lateral_flow_serology; cytokine bead assay

**Initial assessment: Suggest not listing.** The acute-phase swab PCR only confirms that patients had SARS-CoV-2 infection. It is an inclusion criterion, not a study measurement.

---

## 16. SDY1991 / PMID 35455361 — reverse transcription polymerase chain reaction assay

**Agent entry** (`data/31paper_assays/35455361_SDY1991/assays_benchmark.json`)
- name_in_paper: reverse transcription-polymerase chain reaction (RT-PCR)
- aliases: (none)
- OBI: **OBI:0001170 reverse transcription polymerase chain reaction assay**
- generate_claim: False; source: methods

**Paper evidence** (section *2.1. Human Blood Samples*, sentences S12; verbatim match with the JATS XML)
> "The diagnosis of DENV infection was also confirmed if at least one of the following criteria was met in the acute phase serum: (1) positive reverse transcription-polymerase chain reaction (RT-PCR) of DENV RNA, (2) positive serology for dengue IgM, or (3) positive dengue-specific non-structural antigen-1 (NS1)."

**What the benchmark lists for this paper** (`data/benchmark_assay/SDY1991_Assay_Hailong.json`): RNA-Sequencing Assay; ELISA; flow cytometry; IFN-γ Capture Assay

**Initial assessment: Suggest not listing.** One of the diagnostic criteria for dengue infection. It is an inclusion criterion, not a study measurement, and the paper reports no finding from it.

---

## Appendix: the 4 excluded extras

| Paper | Agent's assay | Reason excluded |
|---|---|---|
| SDY1264 | cytopathic effect (CPE) | scorer pairing error: this is the benchmark's YFV neutralizing-antibody assay |
| SDY1264 | plaque reduction neutralization test (PRNT) | scorer pairing error: this is the benchmark's YFV neutralizing-antibody assay |
| SDY1991 | IFN-γ Capture Assay | scorer pairing error: the benchmark has an entry with the same name, but it was paired with our flow cytometry entry |
| SDY1288 | reverse transcription polymerase chain reaction assay | duplicate on our side: the same experiment as the already-matched real-time RT–PCR |
