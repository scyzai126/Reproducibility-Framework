# Extraction stability: 24336226_SDY1260

Runs: v1 (7 entries), v2 (9 entries), run1 (7 entries), run2 (8 entries), run3 (8 entries), run4 (8 entries)

| shape | v1 | v2 | run1 | run2 | run3 | run4 |
|---|---|---|---|---|---|---|
| stable | DNA microarray | DNA microarray | DNA microarray | DNA microarray | DNA microarray | DNA microarray |
| split | ELISA / ELISA kits | ELISA / ELISA kits / ELISA (2) | ELISA / ELISA kits | ELISA / ELISA kits | ELISA / ELISA kits | ELISA / ELISA kits |
| stable | Luminex | anti-Diphtheria IgG by Luminex | anti-Diphtheria IgG by Luminex | anti-DT IgG capture microsphere assay | anti-DT IgG capture microsphere assay | Luminex |
| stable | serum bactericidal titers (SBA) | serum bactericidal titers (SBA) | serum bactericidal titers (SBA) | serum bactericidal titers (SBA) | serum bactericidal titers (SBA) | serum bactericidal titers (SBA) |
| stable | flow cytometry | FACS | flow cytometry | flow cytometry | flow cytometry | flow cytometry |
| stable | ELISpot | ELISpot | ELISpot | ELISpot | ELISpot | ELISpot |
| presence | — | FACS staining | — | flow cytometry for DC activation | FACS staining | FACS staining |

Stable 5 / 7 clusters; split 1; presence 1

Duplicate keys: v2: ELISA (2)

## Field drift over stable clusters

| field | same | reworded | changed |
|---|---|---|---|
| standard_technique_name | 1 | 1 | 3 |
| sample_type | 2 | 2 | 1 |
| readouts | 2 | 0 | 3 |
| aliases | 0 | 1 | 4 |
| generate_claim | 5 | 0 | 0 |
| evidence.quote | 3 | 0 | 2 |
| source | 5 | 0 | 0 |

## Values that moved

- **DNA microarray** / standard_technique_name (changed): v1: "microarray"; v2: "transcription profiling by array"; run1: "transcription profiling by array"; run2: "transcription profiling by array"; run3: "transcription profiling by array"; run4: "transcription profiling by array"
- **DNA microarray** / sample_type (changed): v1: "PBMCs"; v2: "PBMCs"; run1: "peripheral blood mononuclear cells"; run2: "peripheral blood mononuclear cells"; run3: "peripheral blood mononuclear cells"; run4: "peripheral blood mononuclear cells"
- **DNA microarray** / aliases (changed): v1: ["DNA microarrays", "gene expression profile"]; v2: []; run1: ["DNA microarrays"]; run2: ["DNA microarrays"]; run3: ["microarray", "DNA microarrays"]; run4: ["DNA microarrays", "DNA microarray experiment"]
- **Luminex** / standard_technique_name (changed): v1: "bead based multiplex assay"; v2: "Luminex"; run1: "Luminex"; run2: "Luminex"; run3: "Luminex"; run4: "luminex"
- **Luminex** / readouts (changed): v1: "anti-diphtheria toxoid IgG levels"; v2: "diphtheria toxoid-specific IgG levels"; run1: "diphtheria toxoid-specific IgG quantified as median fluorescence intensity-based arbitrary units per milliliter"; run2: "diphtheria toxoid-specific IgG quantified by median fluorescence intensity"; run3: "DT-specific IgG titer expressed as arbitrary units per milliliter based on median fluorescence intensity"; run4: "diphtheria toxoid-specific IgG titer expressed from median fluorescence intensity"
- **Luminex** / aliases (changed): v1: ["anti- DT IgG capture microsphere assay"]; v2: ["anti- DT IgG capture microsphere assay"]; run1: ["anti- DT IgG capture microsphere assay"]; run2: []; run3: ["Measurement of anti-Diphtheria IgG by Luminex", "Luminex"]; run4: ["Measurement of anti-Diphtheria IgG by Luminex", "anti- DT IgG capture microsphere assay"]
- **Luminex** / evidence.quote (changed): v1: "Fluorescent microspheres (Luminex Corp, Austin, TX) were covalently conjugated to DT (List Biologicals, Campbell, CA) and used to capture and quantify DT specific IgG in sera based on previous method with minor modifications 53 ."; v2: "Immune response to Diphtheria toxoid (DT) carrier protein was assessed at Days 0, 7 and 30 using anti- DT IgG capture microsphere assay."; run1: "Immune response to Diphtheria toxoid (DT) carrier protein was assessed at Days 0, 7 and 30 using anti- DT IgG capture microsphere assay."; run2: "Immune response to Diphtheria toxoid (DT) carrier protein was assessed at Days 0, 7 and 30 using anti- DT IgG capture microsphere assay."; run3: "Immune response to Diphtheria toxoid (DT) carrier protein was assessed at Days 0, 7 and 30 using anti- DT IgG capture microsphere assay."; run4: "Fluorescent microspheres (Luminex Corp, Austin, TX) were covalently conjugated to DT (List Biologicals, Campbell, CA) and used to capture and quantify DT specific IgG in sera based on previous method with minor modifications 53 ."
- **serum bactericidal titers (SBA)** / standard_technique_name (reworded): v1: "serum bactericidal assay"; v2: "serum bactericidal assay"; run1: "serum bactericidal assay"; run2: "serum bactericidal assay"; run3: "serum bactericidal assay"; run4: "bactericidal assay"
- **serum bactericidal titers (SBA)** / sample_type (reworded): v1: "serum samples"; v2: "serum"; run1: "serum"; run2: "serum"; run3: "serum"; run4: "serum"
- **serum bactericidal titers (SBA)** / readouts (changed): v1: "bactericidal activity titers against meningococcal strains"; v2: "bactericidal activity titers against meningococcal strains"; run1: "bactericidal killing titers against meningococcal strains"; run2: "bactericidal killing titers against meningococcal serogroups"; run3: "bactericidal titers determined from 50% killing"; run4: "serum dilution yielding 50% bacterial killing"
- **serum bactericidal titers (SBA)** / aliases (changed): v1: ["SBA", "Serum bactericidal assay (SBA)"]; v2: ["SBA"]; run1: ["SBA"]; run2: ["SBA"]; run3: ["Measurement of serum bactericidal titers (SBA)", "SBA"]; run4: ["Measurement of serum bactericidal titers (SBA)", "SBA"]
- **serum bactericidal titers (SBA)** / evidence.quote (changed): v1: "Continuous titers were determined by interpolation of the serum dilution yielding 50% killing as compared to the T 60 growth control plate average."; v2: "Serum samples collected at days 0, 7, 30, 180 and year 2 were added undiluted to microtiter plates (Costar) and then serially diluted (3-fold) in Hank’s balanced salt solution (HBSS, GIBCO/Invitrogen)."; run1: "Serum samples collected at days 0, 7, 30, 180 and year 2 were added undiluted to microtiter plates (Costar) and then serially diluted (3-fold) in Hank’s balanced salt solution (HBSS, GIBCO/Invitrogen)."; run2: "Continuous titers were determined by interpolation of the serum dilution yielding 50% killing as compared to the T 60 growth control plate average."; run3: "Continuous titers were determined by interpolation of the serum dilution yielding 50% killing as compared to the T 60 growth control plate average."; run4: "Continuous titers were determined by interpolation of the serum dilution yielding 50% killing as compared to the T 60 growth control plate average."
- **flow cytometry** / sample_type (reworded): v1: "whole blood cells"; v2: "blood"; run1: "whole blood cells"; run2: "whole blood cells"; run3: "whole blood cells"; run4: "whole blood cells"
- **flow cytometry** / readouts (changed): v1: "frequency of blood antibody secreting cells identified as CD3 neg, CD20 neg, CD38 hi, CD27 hi, CD19+ cells"; v2: "frequency of antibody secreting cells"; run1: "frequency of antibody secreting cells identified as CD3 neg, CD20 neg, CD38 hi, CD27 hi, CD19+ cells"; run2: "frequency of blood antibody secreting cells identified as CD3 neg, CD20 neg, CD38 hi, CD27 hi, CD19+ cells"; run3: "frequency of blood antibody secreting cells identified as CD3 negative CD20 negative CD38 high CD27 high CD19 positive cells"; run4: "frequency of blood antibody secreting cells identified as CD3 neg, CD20 neg, CD38 hi, CD27 hi, CD19 + cells"
- **flow cytometry** / aliases (changed): v1: ["FACS"]; v2: ["flow cytometry"]; run1: ["FACS"]; run2: ["FACS"]; run3: ["FACS"]; run4: ["FACS"]
- **ELISpot** / standard_technique_name (changed): v1: "enzyme linked immunospot"; v2: "ELISpot"; run1: "enzyme linked immunospot assay"; run2: "enzyme linked immunospot"; run3: "enzyme-linked immunospot"; run4: "enzyme-linked immunospot assay"
- **ELISpot** / aliases (reworded): v1: []; v2: []; run1: []; run2: []; run3: ["Measurement of antibody secreting cells by FACS and ELISpot"]; run4: ["Measurement of antibody secreting cells by FACS and ELISpot"]

24336226_SDY1260: 6 runs, 5/7 clusters stable; inventory moved by: split rule moved 1 cluster(s), recall moved 1 cluster(s), 1 duplicate key(s); field drift on stable entries: 13 changed, 4 reworded of 35 compared
