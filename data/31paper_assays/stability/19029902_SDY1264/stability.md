# Extraction stability: 19029902_SDY1264

Runs: v1 (9 entries), v2 (9 entries), run1 (9 entries), run2 (10 entries), run3 (9 entries), run4 (9 entries)

| shape | v1 | v2 | run1 | run2 | run3 | run4 |
|---|---|---|---|---|---|---|
| stable | Multiplex analysis | Multiplex analysis | Multiplex analysis | Multiplex analysis | Multiplex analysis | Multiplex analysis |
| stable | Flow cytometric analysis | Flow cytometric analysis | Flow cytometric analysis | Flow cytometric analysis | Flow cytometric analysis | Flow cytometric analysis |
| stable pair (2) | cytopathic effect (CPE) / plaque reduction neutralization test (PRNT) | cytopathic effect (CPE) / plaque reduction neutralization test (PRNT) | neutralizing antibodies by cytopathic effect (CPE) / plaque reduction neutralization test (PRNT) | neutralizing antibodies by cytopathic effect (CPE) / plaque reduction neutralization test (PRNT) | neutralizing antibodies by CPE / plaque reduction neutralization test | neutralizing antibodies by CPE / plaque reduction neutralization test |
| stable | microarray | microarray | microarray | microarray | microarray | microarray |
| stable | RT-PCR | RT-PCR | RT-PCR | RT-PCR | RT-PCR | RT-PCR |
| stable | Immunofluorescence | Immunofluorescence | immunofluorescence | Immunofluorescence | immunofluorescence | Immunofluorescence |
| stable | immunoblot analysis | immunoblot analysis | immunoblot analysis | immunoblot analysis | immunoblot analysis | immunoblot analysis |
| stable | ELISA | ELISA | ELISA | ELISA | ELISA | ELISA |
| presence | — | — | — | flow cytometry using tetramers | — | — |

Stable 7 / 9 clusters; split 0; presence 1

## Field drift over stable clusters

| field | same | reworded | changed |
|---|---|---|---|
| standard_technique_name | 4 | 0 | 3 |
| sample_type | 1 | 2 | 4 |
| readouts | 2 | 1 | 4 |
| aliases | 1 | 5 | 1 |
| generate_claim | 7 | 0 | 0 |
| evidence.quote | 6 | 0 | 1 |
| source | 7 | 0 | 0 |

## Values that moved

- **Multiplex analysis** / sample_type (reworded): v1: "Plasma samples from CPTs"; v2: "plasma"; run1: "plasma"; run2: "plasma"; run3: "plasma"; run4: "plasma"
- **Multiplex analysis** / readouts (reworded): v1: "cytokine concentrations"; v2: "cytokine concentrations"; run1: "24 cytokine concentrations"; run2: "24 cytokine concentrations"; run3: "24 cytokine concentrations"; run4: "24 cytokine concentrations"
- **Multiplex analysis** / aliases (reworded): v1: ["24-plex assay", "24-plex Luminex assay"]; v2: []; run1: ["24-plex assay", "24-plex Luminex assay"]; run2: ["24-plex assay"]; run3: ["24-plex assay", "24-plex Luminex assay"]; run4: ["24-plex assay", "24-plex Luminex assay"]
- **Flow cytometric analysis** / sample_type (changed): v1: "PBMCs"; v2: "PBMCs"; run1: "peripheral blood mononuclear cells"; run2: "peripheral blood mononuclear cells"; run3: "peripheral blood mononuclear cells"; run4: "peripheral blood mononuclear cells"
- **Flow cytometric analysis** / readouts (changed): v1: "percentages of CD86+ antigen-presenting cells and CD38+ HLA-DR+ CD8+ T cells"; v2: "frequencies of monocytes, myeloid DCs, plasmacytoid DCs, percentage of CD86+ activated antigen-presenting cells, and percentage of CD38+ HLA-DR+ CD8+ CD3+ T cells"; run1: "percentages of CD86+ antigen-presenting cells and percentage of CD38+ HLA-DR+ CD8+ CD3+ T cells"; run2: "percentages of CD86+ antigen-presenting cells and percentage of CD38+ HLA-DR+ CD8+ CD3+ T cells"; run3: "percentages of CD86-positive monocytes, myeloid dendritic cells and plasmacytoid dendritic cells; percentage of CD38-positive HLA-DR-positive CD8-positive CD3-positive T cells"; run4: "percentages of CD86-positive monocytes, myeloid dendritic cells and plasmacytoid dendritic cells; percentage of CD38-positive HLA-DR-positive CD8-positive CD3-positive T cells"
- **Flow cytometric analysis** / aliases (reworded): v1: ["Flow cytometry", "flow cytometry"]; v2: []; run1: []; run2: []; run3: ["flow cytometry"]; run4: ["flow cytometry"]
- **microarray** / standard_technique_name (changed): v1: "microarray"; v2: "transcription profiling by array"; run1: "transcription profiling by array"; run2: "transcription profiling by array"; run3: "transcription profiling by array"; run4: "transcription profiling by array"
- **microarray** / sample_type (reworded): v1: "total peripheral blood mono-nuclear cells (PBMCs)"; v2: "PBMCs"; run1: "peripheral blood mononuclear cells"; run2: "peripheral blood mononuclear cells"; run3: "peripheral blood mononuclear cells"; run4: "peripheral blood mononuclear cells"
- **microarray** / readouts (changed): v1: "gene expression values"; v2: "gene expression levels"; run1: "gene expression intensity data"; run2: "gene expression intensities"; run3: "gene expression intensities"; run4: "gene expression intensity data"
- **microarray** / aliases (changed): v1: ["transcriptional profiling", "microarray analysis"]; v2: []; run1: ["microarray analysis"]; run2: ["microarray analysis"]; run3: ["microarray analysis", "Affymetrix Human Genome U133 Plus 2.0 Array"]; run4: ["microarray analysis", "Affymetrix Human Genome U133 Plus 2.0 Array"]
- **RT-PCR** / sample_type (changed): v1: "total RNA"; v2: null; run1: null; run2: "peripheral blood mononuclear cells"; run3: null; run4: null
- **RT-PCR** / readouts (changed): v1: "relative gene expression by cycling threshold values"; v2: "relative gene expression"; run1: "gene expression measured by cycling threshold values normalized to housekeeping genes"; run2: "relative gene expression by cycling threshold values"; run3: "relative gene expression measured by cycling threshold values"; run4: "gene expression measured by cycling threshold values normalized to housekeeping genes"
- **RT-PCR** / aliases (reworded): v1: []; v2: []; run1: ["Two-step RT-PCR", "TaqMan Gene Expression Plate Assay"]; run2: ["Two-step RT-PCR"]; run3: ["two-step RT-PCR"]; run4: ["Two-step RT-PCR", "relative RT-PCR expression"]
- **Immunofluorescence** / sample_type (changed): v1: "BHK cells"; v2: "BHK cells"; run1: "baby hamster kidney cells"; run2: "baby hamster kidney cells"; run3: "baby hamster kidney cells"; run4: "baby hamster kidney cells"
- **Immunofluorescence** / readouts (changed): v1: "TIAR staining and stress granule formation"; v2: "TIAR staining and stress granule formation"; run1: "TIAR immunofluorescence signal and stress granule formation"; run2: "TIAR immunofluorescence signal and stress granule formation"; run3: "TIAR staining and stress granule formation by fluorescence imaging"; run4: "TIAR staining and stress granule formation by fluorescence imaging"
- **Immunofluorescence** / aliases (reworded): v1: ["Fluorescence microscopy"]; v2: []; run1: []; run2: []; run3: []; run4: ["fluorescence microscopy"]
- **Immunofluorescence** / evidence.quote (changed): v1: "Immunofluorescence signal was detected using a LSM510 confocal microscope (Zeiss), and images were captured and analyzed using the Zeiss LSM Image Browser."; v2: "Immunofluorescence, immunoblot analysis and ELISA."; run1: "Immunofluorescence signal was detected using a LSM510 confocal microscope (Zeiss), and images were captured and analyzed using the Zeiss LSM Image Browser."; run2: "Immunofluorescence signal was detected using a LSM510 confocal microscope (Zeiss), and images were captured and analyzed using the Zeiss LSM Image Browser."; run3: "Immunofluorescence signal was detected using a LSM510 confocal microscope (Zeiss), and images were captured and analyzed using the Zeiss LSM Image Browser."; run4: "Immunofluorescence signal was detected using a LSM510 confocal microscope (Zeiss), and images were captured and analyzed using the Zeiss LSM Image Browser."
- **immunoblot analysis** / standard_technique_name (changed): v1: "immunoblot"; v2: "western blot"; run1: "western blot"; run2: "western blot"; run3: "western blot"; run4: "western blot"
- **immunoblot analysis** / sample_type (changed): v1: "human total PBMC or BHK cells"; v2: "human total PBMC or BHK cells"; run1: "human total peripheral blood mononuclear cells or baby hamster kidney cells"; run2: "human total peripheral blood mononuclear cells or baby hamster kidney cells"; run3: "human total peripheral blood mononuclear cells or baby hamster kidney cells"; run4: "human total peripheral blood mononuclear cells or baby hamster kidney cells"
- **immunoblot analysis** / aliases (reworded): v1: ["Immunoblot"]; v2: []; run1: ["Immunoblot"]; run2: []; run3: []; run4: ["Immunoblot"]
- **ELISA** / standard_technique_name (changed): v1: "ELISA"; v2: "ELISA"; run1: "enzyme linked immunosorbent assay"; run2: "ELISA"; run3: "enzyme-linked immunosorbent assay"; run4: "enzyme-linked immunosorbent assay"

19029902_SDY1264: 6 runs, 7/9 clusters stable; inventory moved by: recall moved 1 cluster(s); field drift on stable entries: 13 changed, 8 reworded of 49 compared
