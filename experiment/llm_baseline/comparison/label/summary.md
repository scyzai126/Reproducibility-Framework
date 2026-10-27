# Bare LLM baseline vs the assay agent, against benchmark v5

| metric | agent | r1 | r2 | r3 | baseline mean (min-max) |
|---|---|---|---|---|---|
| curated rows | 157 | 157 | 158 | 157 | 157.3 (157-158) |
| entries | 177 | 244 | 252 | 252 | 249.3 (244-252) |
| matched | 156 | 153 | 156 | 156 | 155.0 (153-156) |
| MISSED | 1 | 4 | 2 | 1 | 2.3 (1-4) |
| EXTRA | 4 | 72 | 67 | 69 | 69.3 (67-72) |
| exact (same OBI term as curator) | 140 | 77 | 76 | 73 | 75.3 (73-77) |
| OBI ok (same or parent/child) | 145 | 96 | 95 | 93 | 94.7 (93-96) |
| obi_exact_rate | 89.7% | 50.3% | 48.7% | 46.8% | 48.6% (46.8%-50.3%) |
| obi_recall | 92.4% | 61.1% | 60.1% | 59.2% | 60.2% (59.2%-61.1%) |
| wrong term (CONFLICT) | 5 | 45 | 51 | 54 | 50.0 (45-54) |
| no usable term (UNMAPPED) | 6 | 12 | 10 | 9 | 10.3 (9-12) |
| calls | 512 | 31 | 31 | 31 | 31.0 (31-31) |
| ids: valid | — | 16 | 23 | 15 | 18.0 (15-23) |
| ids: label_mismatch | — | 211 | 216 | 224 | 217.0 (211-224) |
| ids: obsolete | — | 2 | 2 | 0 | 1.3 (0-2) |
| ids: nonexistent | — | 13 | 8 | 12 | 11.0 (8-13) |
| ids: none | — | 2 | 3 | 1 | 2.0 (1-3) |

Curated rows with the same baseline status in every run: 114 / 157.  Valid OBI terms per paper present in every run: 99 / 340.

## Rows where the agent and the baseline majority disagree (56)

counts: {'baseline_missed': 2, 'baseline_wrong_term': 41, 'agent_worse': 3, 'baseline_fake_id': 10}

| registry | curated | curator | agent | baseline (per run) | baseline terms (r1) | reason |
|---|---|---|---|---|---|---|
| 19029902_SDY1264 | Assay for yellow fever virus (YFV) neutralizing antibodies | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MISSED / MISSED / MATCH_OBI_UNMAPPED | — | baseline_missed |
| 19047440_SDY1289 | cytometric bead assay (CBA) | OBI:0003799 analyte detection by flow based bead assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001232 assay measuring epitope specific RANTES production by T cells | baseline_wrong_term |
| 19047440_SDY1289 | gene array | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001985 microarray assay | baseline_wrong_term |
| 19047440_SDY1289 | multiplex cytokine analysis | OBI:0000920 cytometric bead array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001232 assay measuring epitope specific RANTES production by T cells | baseline_wrong_term |
| 19047440_SDY1289 | quantitative real-time PCR (qPCR) | OBI:0000893 real time polymerase chain reaction assay | MATCH_OBI_CONFLICT | MATCH / MATCH_OBI_UNMAPPED / MATCH | OBI:0000893 real time polymerase chain reaction assay | agent_worse |
| 20078211_SDY1293_pdf | GeneChip analysis | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH | OBI:0400148 DNA microarray | baseline_wrong_term |
| 20078211_SDY1293_pdf | real-time polymerase chain reaction | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 21357945_SDY1276_pdf | Microarray Analysis | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0400148 DNA microarray | baseline_wrong_term |
| 21357945_SDY1276_pdf | Neutralizing antibody tests | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001470 epitope specific interleukin-17F production by T cells | baseline_wrong_term |
| 23151505_SDY1291_pdf | Affymetrix Exon Microarray | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002118 exome sequencing assay | baseline_wrong_term |
| 23151505_SDY1291_pdf | RT-qPCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 23601689_SDY180 | Microarray Assay | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0400148 DNA microarray | baseline_wrong_term |
| 23601689_SDY180 | Multiplex Cytokine Analysis | OBI:0000920 cytometric bead array assay | MATCH | MATCH_OBI_CONFLICT / MATCH / MATCH_OBI_CONFLICT | OBI:0003044 parasite species identification by PCR assay | baseline_fake_id |
| 23601689_SDY180 | Virus-Neutralization Assay | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001475 in vivo assay measuring T cell epitope specific protection from infectious challenge based on pathogen burden | baseline_wrong_term |
| 23844129_SDY1364 | quantitative_RT_PCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 23878721_SDY1276 | neutralizing antibody test | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | None None | baseline_fake_id |
| 23878721_SDY1276 | whole-genome genotyping | OBI:0002031 genotyping by SNP array assay | MATCH | MATCH_GRANULARITY / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000435 genotyping assay | baseline_wrong_term |
| 24336226_SDY1260 | microarray | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0400148 DNA microarray | baseline_wrong_term |
| 24725414_SDY80 | microneutralization_assay | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001473 in vivo assay measuring T cell epitope specific protection after tumor burden challenge | baseline_wrong_term |
| 25834109_SDY212 | Luminex system | OBI:0000920 cytometric bead array assay | MATCH | MATCH / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000920 cytometric bead array assay | baseline_wrong_term |
| 25834109_SDY212 | plaque assay | OBI:0003798 viral plaque assay | MATCH | MISSED / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | — | baseline_wrong_term |
| 25834109_SDY212 | snp_genotyping_array | OBI:0002031 genotyping by SNP array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001352 allele information | baseline_wrong_term |
| 25834109_SDY212 | whole_blood_microarray | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH / MATCH_OBI_CONFLICT | OBI:0400148 DNA microarray | baseline_wrong_term |
| 26742691_SDY1328 | microarray | OBI:0001463 transcription profiling by array assay | MATCH | MATCH / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001463 transcription profiling by array assay | baseline_wrong_term |
| 28137280_SDY1325 | Illumina® Human HT12v4.0 Expression BeadChip microarray | OBI:0001463 transcription profiling by array assay | MATCH | MATCH / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001463 transcription profiling by array assay | baseline_wrong_term |
| 28137280_SDY1325 | human complement serum bactericidal assay | OBI:0003797 bacterial neutralization assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002767 amplicon sequencing assay | baseline_wrong_term |
| 28137280_SDY1325 | quantitative real-time PCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 28502771_SDY984 | PBMC Transcriptomics analysis | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0400148 DNA microarray | baseline_wrong_term |
| 28502771_SDY984 | Plasma Metabolomics analysis | OBI:0003097 liquid chromatography mass spectrometry assay | MATCH_OBI_CONFLICT | MATCH / MATCH_GRANULARITY / MATCH | OBI:0003097 liquid chromatography mass spectrometry assay | agent_worse |
| 28502771_SDY984 | Viral DNA detection | OBI:0000893 real time polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000415 polymerase chain reaction | baseline_wrong_term |
| 28502771_SDY984 | partial sequencing of amplicons | OBI:0002767 amplicon sequencing assay | MATCH | MISSED / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | — | baseline_wrong_term |
| 28687661_SDY1294 | NK-mediated ADCC assay | OBI:0000882 cell-cell killing assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT | OBI:0002673 enrichment culture medium | baseline_fake_id |
| 28687661_SDY1294 | immunofluorescence_assay | OBI:0001632 immuno staining assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001636 grant | baseline_wrong_term |
| 28687661_SDY1294 | microarray analysis | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MISSED / MISSED | OBI:0400148 DNA microarray | baseline_missed |
| 28687661_SDY1294 | plaque_reduction_neutralization_test | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | None None | baseline_fake_id |
| 28854372_SDY1373 | Next-Generation RNA Sequencing | OBI:0002571 polyA-selected RNA sequencing assay | MATCH_OBI_CONFLICT | MATCH_GRANULARITY / MATCH_GRANULARITY / MATCH_GRANULARITY | OBI:0001177 RNA sequencing assay | agent_worse |
| 30111633_SDY1389 | HLA multimer reagents | OBI:1110179 MHC tetramer/multimer assay measuring binding of a T cell epitope:MHC:TCR complex | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED | None None | baseline_fake_id |
| 30111633_SDY1389 | Human T cell receptor (TCR) sequencing and analysis | OBI:0002990 T cell receptor repertoire sequencing assay | MATCH | MATCH_OBI_CONFLICT / MATCH / MATCH_OBI_CONFLICT | OBI:0000415 polymerase chain reaction | baseline_wrong_term |
| 30150281_SDY1288 | real-time RT–PCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 30150281_SDY1288 | virus_isolation | OBI:0001187 infectious agent detection assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT | OBI:0600047 sequencing assay | baseline_fake_id |
| 31624246_SDY1654 | quantitative real-time PCR (qPCR) | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 32473127_SDY1640 | Activation Induced Marker (AIM) assay | OBI:0003230 T cell activation induced marker assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED / MATCH_GRANULARITY | OBI:0001639 assay measuring epitope specific Ig-mediated histamine release | baseline_fake_id |
| 32473127_SDY1640 | cytokine bead assay | OBI:0003799 analyte detection by flow based bead assay | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED | None None | baseline_fake_id |
| 32473127_SDY1640 | intracellular cytokine staining assay | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED | OBI:0001807 cytometric bead array assay measuring epitope specific interleukin-3 production by T cells | baseline_fake_id |
| 32717743_SDY1655 | Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71) | OBI:0003115 antigen detection by cytometric bead array assay | MATCH_GRANULARITY | MATCH_OBI_CONFLICT / MATCH_GRANULARITY / MATCH_OBI_CONFLICT | OBI:0002762 single-nucleus ATAC-seq | baseline_wrong_term |
| 32717743_SDY1655 | RT-qPCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 32717743_SDY1655 | intracellular_cytokine_staining | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001772 assay measuring epitope specific interleukin-17F production by T cells | baseline_wrong_term |
| 32788292_SDY1669 | Olink multiplex inflammation panel | OBI:0003112 Olink assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003094 fluorescence in-situ hybridization assay | baseline_wrong_term |
| 32788292_SDY1669 | PCR quantitation of bacterial 16S ribosomal RNA (rRNA) gene product | OBI:0000893 real time polymerase chain reaction assay | MATCH_GRANULARITY | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000626 DNA sequencing assay | baseline_wrong_term |
| 32788292_SDY1669 | TLR4-based reporter assay | OBI:0003793 bacterial lipopolysaccharide detection in plasma assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002082 reporter gene assay | baseline_fake_id |
| 32788292_SDY1669 | cellular indexing of transcriptomes and epitopes by sequencing (CITE-seq) | OBI:0003788 cellular indexing of transcriptomes and epitopes by sequencing | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002631 single-cell RNA sequencing assay | baseline_wrong_term |
| 34252919_SDY2189 | Focus reduction neutralization titre assay | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0600016 pooling specimens | baseline_wrong_term |
| 34252919_SDY2189 | Intracellular cytokine staining assay | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001673 nano-cap analysis of gene expression assay, OBI:0000916 flow cytometry assay | baseline_wrong_term |
| 34252919_SDY2189 | RNA isolation and qPCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000626 DNA sequencing assay | baseline_wrong_term |
| 35062294_SDY1995 | Reverse transcription-PCR | OBI:0001170 reverse transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH | OBI:0000415 polymerase chain reaction | baseline_wrong_term |
| 35455361_SDY1991 | flow cytometry-based neutralization assays | OBI:0003796 pathogen neutralization assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003094 fluorescence in-situ hybridization assay | baseline_wrong_term |
