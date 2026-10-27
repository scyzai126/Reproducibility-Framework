# Bare LLM baseline vs the assay agent, against benchmark v5

| metric | agent | r1 | r2 | r3 | baseline mean (min-max) |
|---|---|---|---|---|---|
| curated rows | 157 | 157 | 158 | 158 | 157.7 (157-158) |
| entries | 177 | 244 | 252 | 252 | 249.3 (244-252) |
| matched | 156 | 152 | 154 | 155 | 153.7 (152-155) |
| MISSED | 1 | 5 | 4 | 3 | 4.0 (3-5) |
| EXTRA | 4 | 91 | 97 | 97 | 95.0 (91-97) |
| exact (same OBI term as curator) | 140 | 14 | 15 | 12 | 13.7 (12-15) |
| OBI ok (same or parent/child) | 145 | 24 | 26 | 23 | 24.3 (23-26) |
| obi_exact_rate | 89.7% | 9.2% | 9.7% | 7.7% | 8.9% (7.7%-9.7%) |
| obi_recall | 92.4% | 15.3% | 16.5% | 14.6% | 15.4% (14.6%-16.5%) |
| wrong term (CONFLICT) | 5 | 114 | 115 | 119 | 116.0 (114-119) |
| no usable term (UNMAPPED) | 6 | 14 | 13 | 13 | 13.3 (13-14) |
| calls | 512 | 31 | 31 | 31 | 31.0 (31-31) |
| ids: valid | — | 16 | 23 | 15 | 18.0 (15-23) |
| ids: label_mismatch | — | 211 | 216 | 224 | 217.0 (211-224) |
| ids: obsolete | — | 2 | 2 | 0 | 1.3 (0-2) |
| ids: nonexistent | — | 13 | 8 | 12 | 11.0 (8-13) |
| ids: none | — | 2 | 3 | 1 | 2.0 (1-3) |

Curated rows with the same baseline status in every run: 112 / 157.  Valid OBI terms per paper present in every run: 52 / 408.

## Rows where the agent and the baseline majority disagree (126)

counts: {'baseline_missed': 2, 'baseline_wrong_term': 105, 'baseline_fake_id': 16, 'agent_worse': 3}

| registry | curated | curator | agent | baseline (per run) | baseline terms (r1) | reason |
|---|---|---|---|---|---|---|
| 19029902_SDY1264 | Assay for yellow fever virus (YFV) neutralizing antibodies | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MISSED / MISSED / MATCH_OBI_UNMAPPED | — | baseline_missed |
| 19029902_SDY1264 | ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001051 DNA extract | baseline_wrong_term |
| 19029902_SDY1264 | Flow cytometric analysis | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 19029902_SDY1264 | Luminex assay | OBI:0000920 cytometric bead array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002630 Illumina NovaSeq 6000 | baseline_wrong_term |
| 19029902_SDY1264 | immunoblot assay | OBI:0001978 immunoblot assay | MATCH_GRANULARITY | MATCH_OBI_CONFLICT / MISSED / MATCH_OBI_CONFLICT | OBI:0001557 material storage service | baseline_wrong_term |
| 19047440_SDY1289 | CFSE labeling | OBI:0003582 cell proliferation assay using carboxyfluorescein succinimidyl ester staining | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED | OBI:0002014 DNA methylation profiling by ChIP-chip assay | baseline_fake_id |
| 19047440_SDY1289 | cytometric bead assay (CBA) | OBI:0003799 analyte detection by flow based bead assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001232 assay measuring epitope specific RANTES production by T cells | baseline_wrong_term |
| 19047440_SDY1289 | flow cytometry (Ki67 proliferation assay) | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 19047440_SDY1289 | multiplex cytokine analysis | OBI:0000920 cytometric bead array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001232 assay measuring epitope specific RANTES production by T cells | baseline_wrong_term |
| 19047440_SDY1289 | quantitative real-time PCR (qPCR) | OBI:0000893 real time polymerase chain reaction assay | MATCH_OBI_CONFLICT | MATCH / MATCH_OBI_UNMAPPED / MATCH | OBI:0000893 real time polymerase chain reaction assay | agent_worse |
| 20078211_SDY1293_pdf | malaria thick blood smears | OBI:0002119 microscopy assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002142 Nanostring nCounter miRNA expression assay | baseline_wrong_term |
| 20078211_SDY1293_pdf | real-time polymerase chain reaction | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 21357945_SDY1276_pdf | Hemagglutination inhibition (HAI) tests | OBI:0000875 viral hemagglutination inhibition assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 21357945_SDY1276_pdf | Microarray Analysis | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001271 RNA-seq assay | baseline_wrong_term |
| 21357945_SDY1276_pdf | Neutralizing antibody tests | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001470 epitope specific interleukin-17F production by T cells | baseline_wrong_term |
| 23151505_SDY1291_pdf | Affymetrix Exon Microarray | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002118 exome sequencing assay | baseline_wrong_term |
| 23151505_SDY1291_pdf | Flow Cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003094 fluorescence in-situ hybridization assay | baseline_wrong_term |
| 23151505_SDY1291_pdf | Multiplex Cytokine Analysis | OBI:0000920 cytometric bead array assay | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED | None None | baseline_fake_id |
| 23151505_SDY1291_pdf | RT-qPCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 23266342_SDY1364 | ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH | OBI:0001057 high performance liquid chromatography instrument | baseline_wrong_term |
| 23266342_SDY1364 | flow cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 23601689_SDY180 | Commercial immunoassays (pneumococcal polysaccharide antibody) | OBI:0002773 single-value binding of antibody with reporter to antigen assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002608 oropharyngeal swab specimen | baseline_wrong_term |
| 23601689_SDY180 | Flow Cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 23601689_SDY180 | Hemagglutinin Inhibition Assay | OBI:0000875 viral hemagglutination inhibition assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001631 electron microscopy imaging assay | baseline_wrong_term |
| 23601689_SDY180 | Microarray Assay | OBI:0001463 transcription profiling by array assay | MATCH | MATCH / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001463 transcription profiling by array assay | baseline_wrong_term |
| 23601689_SDY180 | Multiplex Cytokine Analysis | OBI:0000920 cytometric bead array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT | OBI:0003044 parasite species identification by PCR assay | baseline_fake_id |
| 23601689_SDY180 | Virus-Neutralization Assay | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001475 in vivo assay measuring T cell epitope specific protection from infectious challenge based on pathogen burden | baseline_wrong_term |
| 23844129_SDY1364 | IFN_gamma_ELISpot | OBI:0600031 enzyme-linked immunospot assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000016 regulation-assigned role | baseline_wrong_term |
| 23844129_SDY1364 | Illumina microarray | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH | OBI:0001863 shotgun bisulfite-seq assay | baseline_wrong_term |
| 23844129_SDY1364 | flow_cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 23844129_SDY1364 | quantitative_RT_PCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 23844129_SDY1364 | western_blot | OBI:0000854 western blot assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001087 lyophilizer | baseline_wrong_term |
| 23878721_SDY1276 | hemagglutination inhibition (HAI) test | OBI:0000875 viral hemagglutination inhibition assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000718 pathogen role | baseline_wrong_term |
| 23878721_SDY1276 | neutralizing antibody test | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | None None | baseline_fake_id |
| 23878721_SDY1276 | whole-genome genotyping | OBI:0002031 genotyping by SNP array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000727 k-nearest neighbors | baseline_wrong_term |
| 24336226_SDY1260 | ELISpot | OBI:0600031 enzyme-linked immunospot assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002138 temperature value specification | baseline_wrong_term |
| 24336226_SDY1260 | Luminex | OBI:0003116 antibody detection by cytometric bead array assay | MATCH_GRANULARITY | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003094 fluorescence in-situ hybridization assay | baseline_wrong_term |
| 24336226_SDY1260 | flow cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 24336226_SDY1260 | microarray | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH / MATCH_OBI_CONFLICT | OBI:0000869 polyA RNA extract | baseline_wrong_term |
| 24725414_SDY80 | ELISpot assays | OBI:0600031 enzyme-linked immunospot assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001232 assay measuring epitope specific RANTES production by T cells | baseline_wrong_term |
| 24725414_SDY80 | flow cytometric analyses | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 24725414_SDY80 | microneutralization_assay | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001473 in vivo assay measuring T cell epitope specific protection after tumor burden challenge | baseline_wrong_term |
| 24725414_SDY80 | transcriptome analyses using microarrays | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED | OBI:0001456 assay measuring epitope specific macrophage inflammatory protein-1 gamma production by T cells | baseline_fake_id |
| 25367297_SDY404_pdf | Flow Cytometry with Intracellular Cytokine Staining | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000626 DNA sequencing assay | baseline_wrong_term |
| 25367297_SDY404_pdf | Western Blot Analysis | OBI:0000854 western blot assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 25367297_SDY404_pdf | hemagglutination_inhibition_assay | OBI:0000875 viral hemagglutination inhibition assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001675 ELISA measuring epitope specific interleukin-17A production by T cells | baseline_wrong_term |
| 25834109_SDY212 | CMV IgG ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001051 DNA extract | baseline_wrong_term |
| 25834109_SDY212 | Luminex system | OBI:0000920 cytometric bead array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001238 ELISA measuring epitope specific interleukin-9 production by T cells | baseline_wrong_term |
| 25834109_SDY212 | hemagglutination inhibition assay | OBI:0000875 viral hemagglutination inhibition assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001631 electron microscopy imaging assay | baseline_wrong_term |
| 25834109_SDY212 | multiparametric flow cytometry | OBI:0000916 flow cytometry assay | MATCH | MISSED / MISSED / MISSED | — | baseline_missed |
| 25834109_SDY212 | plaque assay | OBI:0003798 viral plaque assay | MATCH | MISSED / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | — | baseline_wrong_term |
| 25834109_SDY212 | snp_genotyping_array | OBI:0002031 genotyping by SNP array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001352 allele information | baseline_wrong_term |
| 25834109_SDY212 | tetramer staining | OBI:1110179 MHC tetramer/multimer assay measuring binding of a T cell epitope:MHC:TCR complex | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 26742691_SDY1328 | GM1-enzyme-linked immunosorbent assay | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001051 DNA extract | baseline_wrong_term |
| 26742691_SDY1328 | polychromatic FCM | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 28137280_SDY1325 | B-cell enzyme-linked immunospot assay | OBI:0600031 enzyme-linked immunospot assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002130 Illumina Infinium Omni5Exome-4 Kit | baseline_wrong_term |
| 28137280_SDY1325 | flow cytometric characterisation of B cells and plasma cells | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 28137280_SDY1325 | human complement serum bactericidal assay | OBI:0003797 bacterial neutralization assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002767 amplicon sequencing assay | baseline_wrong_term |
| 28137280_SDY1325 | quantitative real-time PCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 28502771_SDY984 | Flow cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000626 DNA sequencing assay | baseline_wrong_term |
| 28502771_SDY984 | Plasma Metabolomics analysis | OBI:0003097 liquid chromatography mass spectrometry assay | MATCH_OBI_CONFLICT | MATCH_OBI_CONFLICT / MATCH_GRANULARITY / MATCH_GRANULARITY | OBI:0002399 unilateral oophorectomy history | agent_worse |
| 28502771_SDY984 | Viral DNA detection | OBI:0000893 real time polymerase chain reaction assay | MATCH | MATCH / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 28502771_SDY984 | Zostavax-specific IFN-γ, IL-4 and IL-21 ELISPOT | OBI:0600031 enzyme-linked immunospot assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002816 chromatography vial | baseline_wrong_term |
| 28502771_SDY984 | Zostavax-specific IgG/IgA ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001057 high performance liquid chromatography instrument | baseline_wrong_term |
| 28502771_SDY984 | Zostavax-specific and total IgG B cell ELISPOT | OBI:0600031 enzyme-linked immunospot assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002816 chromatography vial | baseline_wrong_term |
| 28502771_SDY984 | cytokine bead array assay | OBI:0000920 cytometric bead array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002993 prevalence of blood meal specimens from a host organism | baseline_wrong_term |
| 28502771_SDY984 | partial sequencing of amplicons | OBI:0002767 amplicon sequencing assay | MATCH | MISSED / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | — | baseline_wrong_term |
| 28687661_SDY1294 | NK-mediated ADCC assay | OBI:0000882 cell-cell killing assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT | OBI:0002673 enrichment culture medium | baseline_fake_id |
| 28687661_SDY1294 | flow_cytometry_immunophenotyping | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 28687661_SDY1294 | immunofluorescence_assay | OBI:0001632 immuno staining assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001636 grant | baseline_wrong_term |
| 28687661_SDY1294 | microarray analysis | OBI:0001463 transcription profiling by array assay | MATCH | MATCH_OBI_CONFLICT / MATCH / MISSED | OBI:0001483 cell collecting | baseline_wrong_term |
| 28687661_SDY1294 | plaque_reduction_neutralization_test | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | None None | baseline_fake_id |
| 28854372_SDY1373 | Cytokine and Chemokine Multiplex Analysis | OBI:0003799 analyte detection by flow based bead assay | MATCH_GRANULARITY | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003044 parasite species identification by PCR assay | baseline_wrong_term |
| 28854372_SDY1373 | ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001057 high performance liquid chromatography instrument | baseline_wrong_term |
| 28854372_SDY1373 | Flow Cytometry Analysis | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 28854372_SDY1373 | Next-Generation RNA Sequencing | OBI:0002571 polyA-selected RNA sequencing assay | MATCH_OBI_CONFLICT | MATCH_GRANULARITY / MATCH_GRANULARITY / MATCH_GRANULARITY | OBI:0001271 RNA-seq assay | agent_worse |
| 30111633_SDY1389 | CyTOF Sample Preparation and Analysis | OBI:0002115 cytometry time of flight assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003094 fluorescence in-situ hybridization assay | baseline_wrong_term |
| 30111633_SDY1389 | Flow cytometry and sorting | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 30111633_SDY1389 | HLA multimer reagents | OBI:1110179 MHC tetramer/multimer assay measuring binding of a T cell epitope:MHC:TCR complex | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED | None None | baseline_fake_id |
| 30111633_SDY1389 | Human T cell receptor (TCR) sequencing and analysis | OBI:0002990 T cell receptor repertoire sequencing assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000626 DNA sequencing assay | baseline_wrong_term |
| 30111633_SDY1389 | T cell proliferation assays | OBI:0000891 cell proliferation assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002048 Illumina HiSeq 3000 | baseline_wrong_term |
| 30150281_SDY1288 | IgM_capture_ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001057 high performance liquid chromatography instrument | baseline_wrong_term |
| 30150281_SDY1288 | Inhibition ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001057 high performance liquid chromatography instrument | baseline_wrong_term |
| 30150281_SDY1288 | mass cytometry (CyTOF) | OBI:0002115 cytometry time of flight assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003117 3D molecular structure determination assay | baseline_wrong_term |
| 30150281_SDY1288 | multiplex ELISA-based assay (Luminex) | OBI:0000920 cytometric bead array assay | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED | None None | baseline_fake_id |
| 30150281_SDY1288 | real-time RT–PCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000694 animal feeding | baseline_wrong_term |
| 30150281_SDY1288 | virus_isolation | OBI:0001187 infectious agent detection assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT | OBI:0600047 sequencing assay | baseline_fake_id |
| 31624246_SDY1654 | flow cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 31624246_SDY1654 | proliferation assay | OBI:0000891 cell proliferation assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002766 cytokine assay | baseline_wrong_term |
| 31624246_SDY1654 | quantitative real-time PCR (qPCR) | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 32005538_SDY1596 | Flow Cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001234 epigenetic modification identification objective | baseline_wrong_term |
| 32005538_SDY1596 | Luminex | OBI:0000920 cytometric bead array assay | MATCH | MATCH_OBI_CONFLICT / MISSED / MATCH_OBI_CONFLICT | OBI:0001680 Sos-recruitment assay | baseline_wrong_term |
| 32059780_SDY1630 | flow cytometry analysis | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 32473127_SDY1640 | Activation Induced Marker (AIM) assay | OBI:0003230 T cell activation induced marker assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT | OBI:0001639 assay measuring epitope specific Ig-mediated histamine release | baseline_fake_id |
| 32473127_SDY1640 | SARS-CoV-2 RBD ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003094 fluorescence in-situ hybridization assay | baseline_wrong_term |
| 32473127_SDY1640 | cytokine bead assay | OBI:0003799 analyte detection by flow based bead assay | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED | None None | baseline_fake_id |
| 32473127_SDY1640 | flow cytometry | OBI:0000916 flow cytometry assay | MATCH | MISSED / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | — | baseline_wrong_term |
| 32473127_SDY1640 | intracellular cytokine staining assay | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED | OBI:0001807 cytometric bead array assay measuring epitope specific interleukin-3 production by T cells | baseline_fake_id |
| 32717743_SDY1655 | Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71) | OBI:0003115 antigen detection by cytometric bead array assay | MATCH_GRANULARITY | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002762 single-nucleus ATAC-seq | baseline_wrong_term |
| 32717743_SDY1655 | RT-qPCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000893 real time polymerase chain reaction assay | baseline_wrong_term |
| 32717743_SDY1655 | flow cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 32717743_SDY1655 | intracellular_cytokine_staining | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001772 assay measuring epitope specific interleukin-17F production by T cells | baseline_wrong_term |
| 32788292_SDY1669 | Olink multiplex inflammation panel | OBI:0003112 Olink assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003094 fluorescence in-situ hybridization assay | baseline_wrong_term |
| 32788292_SDY1669 | PCR quantitation of bacterial 16S ribosomal RNA (rRNA) gene product | OBI:0000893 real time polymerase chain reaction assay | MATCH_GRANULARITY | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000626 DNA sequencing assay | baseline_wrong_term |
| 32788292_SDY1669 | TLR4-based reporter assay | OBI:0003793 bacterial lipopolysaccharide detection in plasma assay | MATCH | MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | None None | baseline_fake_id |
| 32788292_SDY1669 | cellular indexing of transcriptomes and epitopes by sequencing (CITE-seq) | OBI:0003788 cellular indexing of transcriptomes and epitopes by sequencing | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0002631 single-cell RNA sequencing assay | baseline_wrong_term |
| 32788292_SDY1669 | enzyme-linked immunosorbent assay (ELISA) | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001051 DNA extract | baseline_wrong_term |
| 32788292_SDY1669 | intracellular staining assay | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001801 detection of specific nucleic acids with complementary probes assay measuring epitope specific interleukin-8 production by T cells | baseline_wrong_term |
| 32788292_SDY1669 | phospho-CyTOF | OBI:0002115 cytometry time of flight assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 34128959_SDY1708 | Mass cytometry | OBI:0002115 cytometry time of flight assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003094 fluorescence in-situ hybridization assay | baseline_wrong_term |
| 34252919_SDY2189 | Bead-based antigen arrays | OBI:0003116 antibody detection by cytometric bead array assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED / MISSED | OBI:0003094 fluorescence in-situ hybridization assay | baseline_fake_id |
| 34252919_SDY2189 | CITE-seq | OBI:0003788 cellular indexing of transcriptomes and epitopes by sequencing | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003424 alanine aminotransferase activity level assay | baseline_wrong_term |
| 34252919_SDY2189 | CyTOF analysis of whole-blood samples | OBI:0002115 cytometry time of flight assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_UNMAPPED / MATCH_OBI_CONFLICT | OBI:0002762 single-nucleus ATAC-seq | baseline_fake_id |
| 34252919_SDY2189 | ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000711 library preparation | baseline_wrong_term |
| 34252919_SDY2189 | Focus reduction neutralization titre assay | OBI:0000872 serum neutralization of viral infectivity assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0600016 pooling specimens | baseline_wrong_term |
| 34252919_SDY2189 | Intracellular cytokine staining assay | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001673 nano-cap analysis of gene expression assay | baseline_wrong_term |
| 34252919_SDY2189 | Plasma protein profiling using multiplex Olink panel | OBI:0003112 Olink assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003116 antibody detection by cytometric bead array assay | baseline_wrong_term |
| 34252919_SDY2189 | RNA isolation and qPCR | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000626 DNA sequencing assay | baseline_wrong_term |
| 35062294_SDY1995 | ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_OBI_CONFLICT / MATCH / MATCH_OBI_CONFLICT | OBI:0001051 DNA extract | baseline_wrong_term |
| 35062294_SDY1995 | Flow Cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 35062294_SDY1995 | Reverse transcription-PCR | OBI:0001170 reverse transcription polymerase chain reaction assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000415 polymerase chain reaction | baseline_wrong_term |
| 35455361_SDY1991 | ELISA | OBI:0000661 enzyme-linked immunosorbent assay | MATCH | MATCH_GRANULARITY / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:1110154 ELISA measuring epitope specific interleukin-5 production by T cells | baseline_wrong_term |
| 35455361_SDY1991 | IFN-γ Capture Assay | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
| 35455361_SDY1991 | flow cytometry-based neutralization assays | OBI:0003796 pathogen neutralization assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0003094 fluorescence in-situ hybridization assay | baseline_wrong_term |
| 36656789_SDY1393 | HAI | OBI:0000875 viral hemagglutination inhibition assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0001082 protein separation apparatus | baseline_wrong_term |
| 36656789_SDY1393 | flow cytometry | OBI:0000916 flow cytometry assay | MATCH | MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT / MATCH_OBI_CONFLICT | OBI:0000716 ChIP-seq assay | baseline_wrong_term |
