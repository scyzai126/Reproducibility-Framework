# Extraction stability: 32059780_SDY1630

Runs: v1 (4 entries), run1 (5 entries), run2 (5 entries)

| shape | v1 | run1 | run2 |
|---|---|---|---|
| stable | Flow cytometry analysis and cell sorting | Flow cytometry analysis and cell sorting | Flow cytometry analysis and cell sorting |
| stable | In vitro cytokine stimulation and functional assays of NK cells | In vitro cytokine stimulation and functional assays of NK cells | In vitro cytokine stimulation and functional assays of NK cells |
| stable | For measuring degranulation by NK cells | measuring degranulation by NK cells | measuring degranulation by NK cells |
| stable | Whole transcriptome profiling of NK cell subsets | Whole transcriptome profiling of NK cell subsets | Whole transcriptome profiling of NK cell subsets |
| presence | — | High-dimensional parameter flow cytometric analysis of NK cell subsets | High-dimensional parameter flow cytometric analysis of NK cell subsets |

Stable 4 / 5 clusters; split 0; presence 1

## Field drift over stable clusters

| field | same | reworded | changed |
|---|---|---|---|
| standard_technique_name | 4 | 0 | 0 |
| sample_type | 0 | 0 | 4 |
| readouts | 0 | 1 | 3 |
| aliases | 1 | 1 | 2 |
| generate_claim | 4 | 0 | 0 |
| evidence.quote | 2 | 0 | 2 |
| source | 4 | 0 | 0 |

## Values that moved

- **Flow cytometry analysis and cell sorting** / sample_type (changed): v1: "cells from blood, BM, spleen, lung, intestinal, tonsil, and LN samples"; run1: null; run2: null
- **Flow cytometry analysis and cell sorting** / readouts (changed): v1: "NK cell frequencies, subset distribution, and surface and intracellular marker expression"; run1: "cell surface and intracellular marker expression on NK cells"; run2: "cell surface and intracellular marker expression on NK cells and subsets"
- **Flow cytometry analysis and cell sorting** / aliases (changed): v1: ["flow cytometric analysis", "flow cytometry", "high-dimensional flow cytometry profiling"]; run1: ["flow cytometric analysis", "flow cytometry"]; run2: ["flow cytometric analysis", "Flow cytometry analysis and cell sorting"]
- **Flow cytometry analysis and cell sorting** / evidence.quote (changed): v1: "Flow cytometry data were acquired on a BD LSRII and analyzed using FCS express 6 ( De Novo Software) and custom Python scripts."; run1: "For flow cytometric analysis, cells were stained in 96-well U-bottom plates in the dark using antibody panels (see Key Resources Table )."; run2: "For flow cytometric analysis, cells were stained in 96-well U-bottom plates in the dark using antibody panels (see Key Resources Table )."
- **In vitro cytokine stimulation and functional assays of NK cells** / sample_type (changed): v1: "sorted NK cells from freshly processed tissue sites"; run1: null; run2: null
- **In vitro cytokine stimulation and functional assays of NK cells** / readouts (reworded): v1: "intracellular IFN-γ production after cytokine stimulation"; run1: "intracellular IFN-γ production after cytokine stimulation of sorted NK cells"; run2: "intracellular IFN-γ production after cytokine stimulation"
- **In vitro cytokine stimulation and functional assays of NK cells** / aliases (reworded): v1: []; run1: []; run2: ["In vitro cytokine stimulation and functional assays of NK cells"]
- **For measuring degranulation by NK cells** / sample_type (changed): v1: "sorted, overnight rested NK cells"; run1: null; run2: null
- **For measuring degranulation by NK cells** / readouts (changed): v1: "CD107a expression as a measure of degranulation after co-culture with K562 cells"; run1: "CD107a expression as a degranulation readout after co-culture with K562 cells"; run2: "CD107a expression as a degranulation marker after co-culture with K562 cells"
- **Whole transcriptome profiling of NK cell subsets** / sample_type (changed): v1: "sorted CD56 bright CD16 − and CD56 dim CD16 + NK cells"; run1: "sorted CD56 bright CD16 − and CD56 dim CD16 + natural killer cells"; run2: "sorted CD56 bright CD16 − and CD56 dim CD16 + natural killer cells"
- **Whole transcriptome profiling of NK cell subsets** / readouts (changed): v1: "whole transcriptome gene expression profiles"; run1: "whole-transcriptome gene expression profiles"; run2: "whole-transcriptome gene expression profiles"
- **Whole transcriptome profiling of NK cell subsets** / aliases (changed): v1: ["whole transcriptome profiling by RNA sequencing (RNA-seq)", "RNA-seq"]; run1: ["whole transcriptome profiling", "RNA sequencing", "RNA-seq"]; run2: ["whole transcriptome profiling", "Whole transcriptome profiling of NK cell subsets"]
- **Whole transcriptome profiling of NK cell subsets** / evidence.quote (changed): v1: "Samples were sequenced at Genewiz (South Plainfield, NJ) using a HiSeq2500 system (Illumina)."; run1: "RNA was isolated from sorted CD56 bright CD16 − and CD56 dim CD16 + NK cells using the RNA Easy kit (QIAGEN cat # 74004) and library preparation was done using the SMART-Seq® ultra-low input RNA kit (Takara bio)."; run2: "RNA was isolated from sorted CD56 bright CD16 − and CD56 dim CD16 + NK cells using the RNA Easy kit (QIAGEN cat # 74004) and library preparation was done using the SMART-Seq® ultra-low input RNA kit (Takara bio)."

32059780_SDY1630: 3 runs, 4/5 clusters stable; inventory moved by: recall moved 1 cluster(s); field drift on stable entries: 11 changed, 2 reworded of 28 compared
