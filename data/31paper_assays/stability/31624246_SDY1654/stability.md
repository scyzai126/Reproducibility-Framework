# Extraction stability: 31624246_SDY1654

Runs: v1 (3 entries), run1 (4 entries), run2 (4 entries)

| shape | v1 | run1 | run2 |
|---|---|---|---|
| stable | Single-Cell RNA-seq | Single-Cell RNA-seq | Single-Cell RNA-seq |
| stable | flow cytometry | flow cytometry | flow cytometry |
| stable | Quantitative real-time PCR | Quantitative real-time PCR | Quantitative real-time PCR |
| presence | — | proliferation assays | proliferation assays |

Stable 3 / 4 clusters; split 0; presence 1

## Field drift over stable clusters

| field | same | reworded | changed |
|---|---|---|---|
| standard_technique_name | 2 | 1 | 0 |
| sample_type | 1 | 0 | 2 |
| readouts | 0 | 0 | 3 |
| aliases | 0 | 3 | 0 |
| generate_claim | 3 | 0 | 0 |
| evidence.quote | 1 | 1 | 1 |
| source | 3 | 0 | 0 |

## Values that moved

- **Single-Cell RNA-seq** / standard_technique_name (reworded): v1: "RNA sequencing"; run1: "single-cell RNA sequencing"; run2: "single-cell RNA sequencing"
- **Single-Cell RNA-seq** / sample_type (changed): v1: "CD3 + enriched cells from donor tissue and blood"; run1: "CD3-positive enriched T cells from lung, lung-draining lymph node, bone marrow, and peripheral blood"; run2: "CD3-positive enriched T cells from lung, lung-draining lymph nodes, bone marrow, and peripheral blood"
- **Single-Cell RNA-seq** / readouts (changed): v1: "single-cell transcript sequences and gene expression profiles"; run1: "single-cell transcript sequences and molecular counts for gene expression profiling"; run2: "single-cell transcript sequences and molecular counts for gene expression profiles"
- **Single-Cell RNA-seq** / aliases (reworded): v1: ["scRNA-seq", "Chromium 3′-scRNA-seq"]; run1: ["single-cell RNA-seq", "scRNA-seq", "Chromium 3′-scRNA-seq"]; run2: ["single-cell RNA-seq", "scRNA-seq", "Chromium 3′-scRNA-seq"]
- **Single-Cell RNA-seq** / evidence.quote (changed): v1: "We pooled all of the libraries for a given donor, each of which was barcoded with a unique Illumina sample index, for sequencing in a single Illumina flow cell."; run1: "We barcoded captured mRNA was barcoded during cDNA synthesis and converted the barcoded cDNA into pooled single-cell RNA-seq libraries for Illumina sequencing using the Chromium Single Cell 3′ Solution (10x Genomics) according to the manufacturer’s instructions."; run2: "We barcoded captured mRNA was barcoded during cDNA synthesis and converted the barcoded cDNA into pooled single-cell RNA-seq libraries for Illumina sequencing using the Chromium Single Cell 3′ Solution (10x Genomics) according to the manufacturer’s instructions."
- **flow cytometry** / readouts (changed): v1: "T cell surface marker expression and intracellular NME1 protein expression"; run1: "fluorescence of T cell surface markers"; run2: "fluorescence of T cell surface markers"
- **flow cytometry** / aliases (reworded): v1: []; run1: []; run2: ["Flow cytometry and proliferation assays"]
- **flow cytometry** / evidence.quote (reworded): v1: "To evaluate the expression of T cell surface markers by flow cytometry, we incubated tissue and blood cell suspensions with Human TruStain FcX (BioLegend) and stained with following fluorochrome-conjugated antibodies"; run1: "To evaluate the expression of T cell surface markers by flow cytometry, we incubated tissue and blood cell suspensions with Human TruStain FcX (BioLegend) and stained with following fluorochrome-conjugated antibodies: CD3 (UCHT1, BD Biosciences; OKT3, BioLegend), CD4 (SK3, BD Biosciences; SK3, Tonbo Biosciences), CD8 (SK1, BioLegend; RPA-T8, BD Biosciences), CCR7 (G043H7; BioLegend), CD45RA (HI100; BioLegend), CD25 (BC96; BioLegend), CD127 (A019D5; BioLegend), CD69 (FN50; BioLegend), CD103 (Ber-ACT8; BioLegend), CD45 (HI30; BioLegend), and Fixable Viability Dye eFluor 780 (eBioscience)."; run2: "To evaluate the expression of T cell surface markers by flow cytometry, we incubated tissue and blood cell suspensions with Human TruStain FcX (BioLegend) and stained with following fluorochrome-conjugated antibodies: CD3 (UCHT1, BD Biosciences; OKT3, BioLegend), CD4 (SK3, BD Biosciences; SK3, Tonbo Biosciences), CD8 (SK1, BioLegend; RPA-T8, BD Biosciences), CCR7 (G043H7; BioLegend), CD45RA (HI100; BioLegend), CD25 (BC96; BioLegend), CD127 (A019D5; BioLegend), CD69 (FN50; BioLegend), CD103 (Ber-ACT8; BioLegend), CD45 (HI30; BioLegend), and Fixable Viability Dye eFluor 780 (eBioscience)."
- **Quantitative real-time PCR** / sample_type (changed): v1: "sorted live CD4 + and CD8 + T cells"; run1: "sorted live CD4-positive and CD8-positive T cells from peripheral blood mononuclear cells"; run2: "sorted live CD4-positive and CD8-positive T cells from peripheral blood mononuclear cells"
- **Quantitative real-time PCR** / readouts (changed): v1: "NME1, IL2RA, IFIT3 and TBP mRNA expression fold changes"; run1: "NME1, IL2RA, IFIT3, and TBP cDNA amplification measured by cycle threshold and fold change in mRNA expression"; run2: "NME1, IL2RA, IFIT3, and TBP cDNA amplification measured by cycle threshold and fold change"
- **Quantitative real-time PCR** / aliases (reworded): v1: ["qPCR", "Quntitative PCR (qPCR)"]; run1: ["quantitative real-time PCR (qPCR)", "qPCR", "Quntitative PCR (qPCR)"]; run2: ["quantitative real-time PCR (qPCR)", "qPCR", "Quntitative PCR (qPCR)"]

31624246_SDY1654: 3 runs, 3/4 clusters stable; inventory moved by: recall moved 1 cluster(s); field drift on stable entries: 6 changed, 5 reworded of 21 compared
