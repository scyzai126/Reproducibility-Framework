# Assay comparison: registry folders vs benchmark

- **Registry:** `data/claims/assay_registries/<pmid>_<SDY>/assays_benchmark.json` (the pipeline deliverable, keyed by OBI label). `assays_OBI.json` in the same folder is used only to tell a real OBI key from an unmapped one (`obi_label: null`, key = paper name).
- **Benchmark:** `data/benchmark_assay/SDY*_*.json`
- **Step 1 — abstraction:** every paper wording in the registry's `name_in_paper` list is paired with a benchmark entry by name + aliases (auto-paired; uncertain pairs checked by hand against the evidence quotes). One registry entry can hold several wordings, so pairing is per wording.
- **Step 2 — OBI mapping:** for each benchmark assay that was found, compare its OBI label with the OBI key of the registry entry/entries its wordings belong to (case-insensitive).
- Row-level data: `assay_comparison_registry_folders.csv` (same folder). The earlier report `assay_comparison.md` used the older top-level `assays_OBI_<pmid>.json` files.
- `23844129_SDY1364` has no benchmark file and is not compared.

> ⚠️ **SDY1328 / 26742691 excluded from totals** — the benchmark file describes a TB CD4 T-cell study (RNA-seq, CyTOF, ABCB1, AIM); none of those appear in PMID 26742691. The registry matches the paper (EM131 hepatitis B cohort: ELISA, microarray, FCM, multiplex ELISA, CBC). A draft replacement benchmark is in `SDY1328_26742691_assays_draft.json`.

## Overall (26 papers)

| Metric | Value |
|---|---|
| Benchmark assays | 125 |
| Registry entries (OBI keys) | 139 |
| Registry paper wordings | 148 |
| **Step 1 — abstraction** | |
| Benchmark assays found in registry | 122 (97.6%) |
| Missing in registry | 3 |
| Extra registry wordings (not in benchmark) | 19 |
| Split (1 benchmark → ≥2 registry wordings) | 10 |
| Merged (several benchmark → 1 registry wording) | 5 |
| **Step 2 — OBI (over found)** | |
| Same OBI | 75 (61.5%) |
| Different OBI (incl. partly same) | 31 |
| Registry unmapped | 12 |
| Benchmark unmapped | 3 |
| Both unmapped | 1 |

## Per paper

| SDY | PMID | Bench | Reg entries | Reg wordings | Found | Missing | Extra | Split | Merged | OBI same | OBI diff | Reg unmapped | Bench unmapped |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SDY80 | 24725414 | 4 | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 2 | 2 | 0 | 0 |
| SDY180 | 23601689 | 7 | 6 | 6 | 6 | 1 | 0 | 0 | 0 | 2 | 2 | 2 | 0 |
| SDY212 | 25834109 | 7 | 9 | 10 | 7 | 0 | 2 | 1 | 0 | 6 | 0 | 1 | 0 |
| SDY984 | 28502771 | 10 | 9 | 11 | 9 | 1 | 0 | 2 | 0 | 5 | 2 | 2 | 0 |
| SDY1260 | 24336226 | 6 | 6 | 7 | 6 | 0 | 0 | 1 | 0 | 5 | 0 | 0 | 0 |
| SDY1264 | 19029902 | 4 | 9 | 9 | 4 | 0 | 4 | 1 | 0 | 2 | 2 | 0 | 0 |
| SDY1276 | 23878721 | 3 | 4 | 4 | 3 | 0 | 1 | 0 | 0 | 1 | 2 | 0 | 0 |
| SDY1288 | 30150281 | 5 | 7 | 7 | 5 | 0 | 2 | 0 | 0 | 2 | 2 | 0 | 1 |
| SDY1289 | 19047440 | 12 | 9 | 9 | 12 | 0 | 0 | 0 | 5 | 7 | 4 | 1 | 0 |
| SDY1294 | 28687661 | 4 | 6 | 6 | 4 | 0 | 2 | 0 | 0 | 3 | 1 | 0 | 0 |
| SDY1325 | 28137280 | 5 | 5 | 5 | 5 | 0 | 0 | 0 | 0 | 3 | 1 | 0 | 1 |
| SDY1328 ⚠️ | 26742691 | 5 | 4 | 5 | 0 | 5 | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| SDY1364 | 23266342 | 3 | 3 | 4 | 3 | 0 | 0 | 1 | 0 | 3 | 0 | 0 | 0 |
| SDY1373 | 28854372 | 4 | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 2 | 2 | 0 | 0 |
| SDY1389 | 30111633 | 5 | 6 | 6 | 5 | 0 | 1 | 0 | 0 | 3 | 2 | 0 | 0 |
| SDY1393 | 36656789 | 3 | 3 | 3 | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| SDY1596 | 32005538 | 2 | 3 | 3 | 2 | 0 | 1 | 0 | 0 | 2 | 0 | 0 | 0 |
| SDY1630 | 32059780 | 3 | 4 | 5 | 3 | 0 | 0 | 2 | 0 | 1 | 0 | 2 | 0 |
| SDY1640 | 32473127 | 5 | 6 | 7 | 5 | 0 | 2 | 0 | 0 | 2 | 1 | 2 | 0 |
| SDY1654 | 31624246 | 4 | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 3 | 1 | 0 | 0 |
| SDY1655 | 32717743 | 3 | 3 | 3 | 3 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 0 |
| SDY1669 | 32788292 | 7 | 8 | 9 | 7 | 0 | 1 | 1 | 0 | 4 | 2 | 0 | 1 |
| SDY1708 | 34128959 | 3 | 4 | 4 | 3 | 0 | 1 | 0 | 0 | 3 | 0 | 0 | 0 |
| SDY1991 | 35455361 | 2 | 4 | 4 | 2 | 0 | 2 | 0 | 0 | 0 | 1 | 1 | 0 |
| SDY1995 | 35062294 | 4 | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 2 | 2 | 0 | 0 |
| SDY2189 | 34252919 | 10 | 9 | 10 | 9 | 1 | 0 | 1 | 0 | 7 | 2 | 0 | 0 |

## Step 1 differences (abstraction)

| SDY | Type | Benchmark name | Registry wording(s) |
|---|---|---|---|
| SDY180 | MISSING in registry | In Vitro Stimulation with Innate Immune Ligands | — |
| SDY212 | SPLIT into 2 | multiparametric flow cytometry | phosphoflow analysis ; flow cytometry |
| SDY212 | EXTRA in registry | — | Leukocyte subset frequency determination |
| SDY212 | EXTRA in registry | — | tetramer staining |
| SDY984 | SPLIT into 2 | Viral DNA detection | PCR ; partial sequencing of amplicons |
| SDY984 | SPLIT into 2 | Plasma Metabolomics analysis | LC-MS analysis ; tandem MS-MS experiments |
| SDY984 | MISSING in registry | In vitro stimulation of PBMCs with Zostavax® | — |
| SDY1260 | SPLIT into 2 | ELISA | ELISA ; ELISA kits |
| SDY1264 | SPLIT into 2 | Assay for yellow fever virus (YFV) neutralizing antibodies | cytopathic effect (CPE) ; plaque reduction neutralization test (PRNT) |
| SDY1264 | EXTRA in registry | — | RT-PCR |
| SDY1264 | EXTRA in registry | — | Immunofluorescence |
| SDY1264 | EXTRA in registry | — | immunoblot analysis |
| SDY1264 | EXTRA in registry | — | ELISA |
| SDY1276 | EXTRA in registry | — | Whole-genome genotyping |
| SDY1288 | EXTRA in registry | — | IgM capture ELISA |
| SDY1288 | EXTRA in registry | — | CHIKV viral titer assays |
| SDY1289 | MERGED with other benchmark entries | gene array | gene array |
| SDY1289 | MERGED with other benchmark entries | flow cytometry (Ki67 proliferation assay) | flow cytometric analysis |
| SDY1289 | MERGED with other benchmark entries | polychromatic flow cytometry (intracellular cytokine staining) | flow cytometric analysis |
| SDY1289 | MERGED with other benchmark entries | FACS analysis of PBMCs (central memory Th1/Th2 phenotyping) | flow cytometric analysis |
| SDY1289 | MERGED with other benchmark entries | microarray analysis (VaxDesign/MIMIC samples) | gene array |
| SDY1294 | EXTRA in registry | — | NK-mediated ADCC assay |
| SDY1294 | EXTRA in registry | — | intracellular cytokine staining |
| SDY1328 | MISSING in registry | RNA sequencing | — |
| SDY1328 | MISSING in registry | flow cytometry | — |
| SDY1328 | MISSING in registry | ABCB1 activity assay | — |
| SDY1328 | MISSING in registry | mass cytometry | — |
| SDY1328 | MISSING in registry | TB-specific reactivity of sorted CD4 T cell subsets | — |
| SDY1328 | EXTRA in registry | — | ELISA |
| SDY1328 | EXTRA in registry | — | multiplex ELISA |
| SDY1328 | EXTRA in registry | — | microarray |
| SDY1328 | EXTRA in registry | — | Polychromatic FCM |
| SDY1328 | EXTRA in registry | — | complete blood count |
| SDY1364 | SPLIT into 2 | flow cytometry | Surface and intracellular cytokine staining ; surface staining |
| SDY1389 | EXTRA in registry | — | HLA multimer staining |
| SDY1596 | EXTRA in registry | — | culturable microbial count assay |
| SDY1630 | SPLIT into 2 | flow cytometry analysis | flow cytometry analysis ; High-dimensional parameter flow cytometric analysis of NK cell subsets |
| SDY1630 | SPLIT into 2 | in vitro cytokine stimulation and functional assays | In vitro cytokine stimulation and functional assays of NK cells ; measuring degranulation by NK cells |
| SDY1640 | EXTRA in registry | — | OC43 and NL63 coronavirus RBD ELISA |
| SDY1640 | EXTRA in registry | — | lateral flow assay |
| SDY1669 | SPLIT into 2 | enzyme-linked immunosorbent assay (ELISA) | enzyme-linked immunosorbent assay (ELISA) ; highly sensitive ELISA enabled by single molecule array (SIMoA) technology |
| SDY1669 | EXTRA in registry | — | intracellular staining assay |
| SDY1708 | EXTRA in registry | — | Hi-C data |
| SDY1991 | EXTRA in registry | — | DENV-specific IgG ELISAs |
| SDY1991 | EXTRA in registry | — | IFN-γ Secretion Assay |
| SDY2189 | SPLIT into 2 | Focus reduction neutralization titre assay | Focus reduction neutralization titre assay ; FRNT assay against the variants of concern |
| SDY2189 | MISSING in registry | Single-molecule array | — |

## Step 2 differences (OBI mapping, found assays only)

| SDY | Benchmark name | Registry wording(s) | Benchmark OBI | Registry OBI | Result |
|---|---|---|---|---|---|
| SDY80 | transcriptome analyses using microarrays | microarray | transcription profiling by array assay | microarray assay | DIFFERENT |
| SDY80 | microneutralization assay | Virus-neutralizing titers | 96-well neutralization assay | serum neutralization of viral infectivity assay | DIFFERENT |
| SDY180 | Microarray Assay | microarray | transcription profiling by array assay | microarray assay | DIFFERENT |
| SDY180 | Virus-Neutralization Assay | Virus-neutralization assays | serum neutralization of viral infectivity assay | pathogen neutralization assay | DIFFERENT |
| SDY180 | Commercial immunoassays (pneumococcal polysaccharide antibody) | commercial immunoassays | single-value binding of antibody with reporter to antigen assay | (none: key "commercial immunoassays") | registry unmapped |
| SDY180 | Multiplex Cytokine Analysis | Multiplex Cytokine Analysis | cytometric bead array assay | (none: key "Multiplex Cytokine Analysis") | registry unmapped |
| SDY212 | single nucleotide polymorphism assay | Single-nucleotide polymorphism assay | genotyping by array assay | (none: key "Single-nucleotide polymorphism assay") | registry unmapped |
| SDY984 | Zostavax-specific IgG/IgA ELISA | Zostavax®-specific IgG/IgA ELISA | enzyme-linked immunosorbent assay | (none: key "Zostavax®-specific IgG/IgA ELISA") | registry unmapped |
| SDY984 | Viral DNA detection | PCR ; partial sequencing of amplicons | polymerase chain reaction assay | polymerase chain reaction assay ; amplicon sequencing assay | partly same |
| SDY984 | PBMC Transcriptomics analysis | Human U133 Plus 2.0 Arrays | transcription profiling by array assay | (none: key "Human U133 Plus 2.0 Arrays") | registry unmapped |
| SDY984 | Plasma Metabolomics analysis | LC-MS analysis ; tandem MS-MS experiments | liquid chromatography mass spectrometry assay | liquid chromatography mass spectrometry assay ; tandem mass spectrometry assay | partly same |
| SDY1264 | Luminex assay | Multiplex analysis | cytometric bead array assay | multiplex bead-based protein state immunoassay | DIFFERENT |
| SDY1264 | Assay for yellow fever virus (YFV) neutralizing antibodies | cytopathic effect (CPE) ; plaque reduction neutralization test (PRNT) | pathogen neutralization assay | serum neutralization of viral infectivity assay ; (none: key "plaque reduction neutralization test (PRNT)") | DIFFERENT |
| SDY1276 | global gene expression analysis | Measurement of global transcript abundance | transcription profiling by array assay | transcription profiling assay | DIFFERENT |
| SDY1276 | neutralizing antibody test [gc=false] | Neutralizing antibody tests | serum neutralization of viral infectivity assay | pathogen neutralization assay | DIFFERENT |
| SDY1288 | multiplex ELISA-based assay (Luminex) | multiplex ELISA‐based assay | (none) | multiplex bead-based protein state immunoassay | benchmark unmapped |
| SDY1288 | RNA-seq | RNA‐seq | bulk RNA-seq assay | RNA-seq assay | DIFFERENT |
| SDY1288 | Inhibition ELISA | Inhibition ELISA | enzyme-linked immunosorbent assay | competitive inhibition of binding assay | DIFFERENT |
| SDY1289 | gene array | gene array | transcription profiling by array assay | microarray assay | DIFFERENT |
| SDY1289 | cytometric bead assay (CBA) | CBA | cytometric bead array assay | antibody detection by cytometric bead array assay | DIFFERENT |
| SDY1289 | multiplex cytokine analysis | multiplex cytokine analysis | cytometric bead array assay | (none: key "multiplex cytokine analysis") | registry unmapped |
| SDY1289 | polychromatic flow cytometry (MIMIC DC/T cell co-culture) | CD4 + T cell stimulation assay | flow cytometry assay | T cell activation induced marker assay | DIFFERENT |
| SDY1289 | microarray analysis (VaxDesign/MIMIC samples) | gene array | transcription profiling by array assay | microarray assay | DIFFERENT |
| SDY1294 | microarray analysis | microarray hybridization | transcription profiling by array assay | microarray assay | DIFFERENT |
| SDY1325 | human complement serum bactericidal assay | Serum bactericidal assay | (none) | bacterial neutralization assay | benchmark unmapped |
| SDY1325 | Illumina® Human HT12v4.0 Expression BeadChip microarray | microarray | transcription profiling by array assay | microarray assay | DIFFERENT |
| SDY1373 | Cytokine and Chemokine Multiplex Analysis | Cytokine and Chemokine Multiplex Analysis | multiplex bead-based protein state immunoassay | cytometric bead array assay | DIFFERENT |
| SDY1373 | Next-Generation RNA Sequencing | Next-Generation RNA Sequencing | polyA-selected RNA sequencing assay | RNA-seq assay | DIFFERENT |
| SDY1389 | Whole-Transcriptome Profiling by RNA-Sequencing | RNA-Sequencing | polyA-selected RNA sequencing assay | RNA-seq assay | DIFFERENT |
| SDY1389 | Human T cell receptor (TCR) sequencing and analysis | TCR sequencing | amplicon sequencing assay | T cell receptor repertoire sequencing assay | DIFFERENT |
| SDY1630 | in vitro cytokine stimulation and functional assays | In vitro cytokine stimulation and functional assays of NK cells ; measuring degranulation by NK cells | assay detecting IFN-gamma production | (none: key "In vitro cytokine stimulation and functional assays of NK cells") ; (none: key "measuring degranulation by NK cells") | registry unmapped |
| SDY1630 | whole transcriptome profiling by RNA sequencing (RNA-seq) | Whole transcriptome profiling of NK cell subsets | RNA-seq assay | (none: key "Whole transcriptome profiling of NK cell subsets") | registry unmapped |
| SDY1640 | intracellular cytokine staining assay | Intracellular cytokine staining assay | immuno staining assay | cytometry assay | DIFFERENT |
| SDY1640 | flow cytometry | Direct ex vivo PBMC immune cell phenotyping | flow cytometry assay | (none: key "Direct ex vivo PBMC immune cell phenotyping") | registry unmapped |
| SDY1640 | cytokine bead assay | Cytokine bead assays | analyte detection by flow based bead assay | (none: key "Cytokine bead assays") | registry unmapped |
| SDY1654 | quantitative real-time PCR (qPCR) | Quantitative real-time PCR | real time reverse-transcription polymerase chain reaction assay | real time polymerase chain reaction assay | DIFFERENT |
| SDY1655 | Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71) | Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71) | cytometric bead array assay | (none: key "Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71)") | registry unmapped |
| SDY1669 | bulk RNA sequencing (RNA-seq) | bulk RNA sequencing (RNA-seq) analysis | RNA-seq assay | bulk RNA-seq assay | DIFFERENT |
| SDY1669 | PCR quantitation of bacterial 16S ribosomal RNA (rRNA) gene product | PCR quantitation of bacterial 16 S ribosomal RNA (rRNA) gene product | real time polymerase chain reaction assay | organism detection by PCR assay | DIFFERENT |
| SDY1669 | TLR4-based reporter assay | TLR4-based reporter assay | (none) | reporter cell line analyte detection bioassay | benchmark unmapped |
| SDY1991 | RNA-Sequencing Assay | Microscaled RNA-Seq | RNA-seq assay | bulk RNA-seq assay | DIFFERENT |
| SDY1991 | flow cytometry | flow cytometry-based neutralization assays | flow cytometry assay | (none: key "flow cytometry-based neutralization assays") | registry unmapped |
| SDY1995 | RNA Sequencing | RNA Sequencing | RNA-seq assay | RNA sequencing assay | DIFFERENT |
| SDY1995 | Reverse transcription-PCR [gc=false] | reverse transcription-PCR | real time reverse-transcription polymerase chain reaction assay | reverse transcription polymerase chain reaction assay | DIFFERENT |
| SDY2189 | Intracellular cytokine staining assay | Intracellular cytokine staining assay | cytokine assay | immuno staining assay | DIFFERENT |
| SDY2189 | Bead-based antigen arrays | Bead-based antigen arrays | antibody detection by cytometric bead array assay | antigen specific antibodies assay | DIFFERENT |

## Full detail per paper

### SDY80 / PMID 24725414

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| flow cytometric analyses | flow cytometric analyses | found | flow cytometry assay | flow cytometry assay | same |
| transcriptome analyses using microarrays | microarray | found | transcription profiling by array assay | microarray assay | DIFFERENT |
| microneutralization assay | Virus-neutralizing titers | found | 96-well neutralization assay | serum neutralization of viral infectivity assay | DIFFERENT |
| ELISpot assays | ELISpot assays | found | enzyme-linked immunospot assay | enzyme-linked immunospot assay | same |

### SDY180 / PMID 23601689

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| Microarray Assay | microarray | found | transcription profiling by array assay | microarray assay | DIFFERENT |
| Flow Cytometry | Flow Cytometry | found | flow cytometry assay | flow cytometry assay | same |
| Hemagglutinin Inhibition Assay | Hemagglutinin Inhibition Assays | found | viral hemagglutination inhibition assay | viral hemagglutination inhibition assay | same |
| Virus-Neutralization Assay | Virus-neutralization assays | found | serum neutralization of viral infectivity assay | pathogen neutralization assay | DIFFERENT |
| Commercial immunoassays (pneumococcal polysaccharide antibody) | commercial immunoassays | found | single-value binding of antibody with reporter to antigen assay | (none: key "commercial immunoassays") | registry unmapped |
| Multiplex Cytokine Analysis | Multiplex Cytokine Analysis | found | cytometric bead array assay | (none: key "Multiplex Cytokine Analysis") | registry unmapped |
| In Vitro Stimulation with Innate Immune Ligands | — | MISSING in registry | transcription profiling by array assay | — | — |

### SDY212 / PMID 25834109

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| CMV IgG ELISA | ELISA | found | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | same |
| multiparametric flow cytometry | phosphoflow analysis ; flow cytometry | SPLIT into 2 | flow cytometry assay | flow cytometry assay | same |
| Luminex system | Luminex | found | cytometric bead array assay | cytometric bead array assay | same |
| whole blood microarray | microarray | found | microarray assay | microarray assay | same |
| hemagglutination-inhibition (HAI) assay | Hemagglutination inhibition assay | found | viral hemagglutination inhibition assay | viral hemagglutination inhibition assay | same |
| single nucleotide polymorphism assay | Single-nucleotide polymorphism assay | found | genotyping by array assay | (none: key "Single-nucleotide polymorphism assay") | registry unmapped |
| plaque assay | plaque assay | found | viral plaque assay | viral plaque assay | same |
| — | Leukocyte subset frequency determination | EXTRA in registry | — | differential leukocyte count assay | — |
| — | tetramer staining | EXTRA in registry | — | (none: key "tetramer staining") | — |

### SDY984 / PMID 28502771

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| Flow cytometry | Flow cytometry | found | flow cytometry assay | flow cytometry assay | same |
| Zostavax-specific IFN-γ, IL-4 and IL-21 ELISPOT | Zostavax®-specific IFN-γ, IL-4 and IL-21 ELISPOT | found | enzyme-linked immunospot assay | enzyme-linked immunospot assay | same |
| Zostavax-specific and total IgG B cell ELISPOT | Zostavax®-specific and total IgG B cell ELISPOT | found | enzyme-linked immunospot assay | enzyme-linked immunospot assay | same |
| Zostavax-specific IgG/IgA ELISA | Zostavax®-specific IgG/IgA ELISA | found | enzyme-linked immunosorbent assay | (none: key "Zostavax®-specific IgG/IgA ELISA") | registry unmapped |
| Viral DNA detection | PCR ; partial sequencing of amplicons | SPLIT into 2 | polymerase chain reaction assay | polymerase chain reaction assay ; amplicon sequencing assay | partly same |
| Multiplex cytokine assays | Luminex assays | found | cytometric bead array assay | cytometric bead array assay | same |
| PBMC Transcriptomics analysis | Human U133 Plus 2.0 Arrays | found | transcription profiling by array assay | (none: key "Human U133 Plus 2.0 Arrays") | registry unmapped |
| Plasma Metabolomics analysis | LC-MS analysis ; tandem MS-MS experiments | SPLIT into 2 | liquid chromatography mass spectrometry assay | liquid chromatography mass spectrometry assay ; tandem mass spectrometry assay | partly same |
| In vitro stimulation of PBMCs with Zostavax® | — | MISSING in registry | flow cytometry assay | — | — |
| Cytokine Bead Array (CBA) | Cytokine Bead Array (CBA) | found | cytometric bead array assay | cytometric bead array assay | same |

### SDY1260 / PMID 24336226

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| ELISA | ELISA ; ELISA kits | SPLIT into 2 | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | same |
| Luminex | Luminex | found | cytometric bead array assay | cytometric bead array assay | same |
| flow cytometry | flow cytometry | found | flow cytometry assay | flow cytometry assay | same |
| ELISpot | ELISpot | found | enzyme-linked immunospot assay | enzyme-linked immunospot assay | same |
| SBA | serum bactericidal titers (SBA) | found | (none) | (none: key "serum bactericidal titers (SBA)") | both unmapped |
| microarray | DNA microarray | found | microarray assay | microarray assay | same |

### SDY1264 / PMID 19029902

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| microarray | microarray | found | microarray assay | microarray assay | same |
| Luminex assay | Multiplex analysis | found | cytometric bead array assay | multiplex bead-based protein state immunoassay | DIFFERENT |
| Flow cytometric analysis | Flow cytometric analysis | found | flow cytometry assay | flow cytometry assay | same |
| Assay for yellow fever virus (YFV) neutralizing antibodies | cytopathic effect (CPE) ; plaque reduction neutralization test (PRNT) | SPLIT into 2 | pathogen neutralization assay | serum neutralization of viral infectivity assay ; (none: key "plaque reduction neutralization test (PRNT)") | DIFFERENT |
| — | RT-PCR | EXTRA in registry | — | real time reverse-transcription polymerase chain reaction assay | — |
| — | Immunofluorescence | EXTRA in registry | — | immunocytochemistry | — |
| — | immunoblot analysis | EXTRA in registry | — | western blot assay | — |
| — | ELISA | EXTRA in registry | — | enzyme-linked immunosorbent assay | — |

### SDY1276 / PMID 23878721

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| global gene expression analysis | Measurement of global transcript abundance | found | transcription profiling by array assay | transcription profiling assay | DIFFERENT |
| hemagglutination inhibition (HAI) test | Hemagglutination inhibition (HAI) tests | found | viral hemagglutination inhibition assay | viral hemagglutination inhibition assay | same |
| neutralizing antibody test [gc=false] | Neutralizing antibody tests | found | serum neutralization of viral infectivity assay | pathogen neutralization assay | DIFFERENT |
| — | Whole-genome genotyping | EXTRA in registry | — | genotyping assay | — |

### SDY1288 / PMID 30150281

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| mass cytometry (CyTOF) | mass cytometry | found | cytometry time of flight assay | cytometry time of flight assay | same |
| multiplex ELISA-based assay (Luminex) | multiplex ELISA‐based assay | found | (none) | multiplex bead-based protein state immunoassay | benchmark unmapped |
| RNA-seq | RNA‐seq | found | bulk RNA-seq assay | RNA-seq assay | DIFFERENT |
| real-time RT–PCR | real-time RT–PCR | found | real time reverse-transcription polymerase chain reaction assay | real time reverse-transcription polymerase chain reaction assay | same |
| Inhibition ELISA | Inhibition ELISA | found | enzyme-linked immunosorbent assay | competitive inhibition of binding assay | DIFFERENT |
| — | IgM capture ELISA | EXTRA in registry | — | enzyme-linked immunosorbent assay | — |
| — | CHIKV viral titer assays | EXTRA in registry | — | (none: key "CHIKV viral titer assays") | — |

### SDY1289 / PMID 19047440

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| gene array | gene array | MERGED with other benchmark entries | transcription profiling by array assay | microarray assay | DIFFERENT |
| quantitative real-time PCR (qPCR) | qPCR | found | real time polymerase chain reaction assay | real time polymerase chain reaction assay | same |
| IL-1β ELISA | IL-1β ELISA | found | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | same |
| flow cytometry (Ki67 proliferation assay) | flow cytometric analysis | MERGED with other benchmark entries | flow cytometry assay | flow cytometry assay | same |
| CFSE labeling | CFSE labeling | found | carboxyfluorescein succinimidyl ester staining assay | carboxyfluorescein succinimidyl ester staining assay | same |
| cytometric bead assay (CBA) | CBA | found | cytometric bead array assay | antibody detection by cytometric bead array assay | DIFFERENT |
| polychromatic flow cytometry (intracellular cytokine staining) | flow cytometric analysis | MERGED with other benchmark entries | flow cytometry assay | flow cytometry assay | same |
| FACS analysis of PBMCs (central memory Th1/Th2 phenotyping) | flow cytometric analysis | MERGED with other benchmark entries | flow cytometry assay | flow cytometry assay | same |
| multiplex cytokine analysis | multiplex cytokine analysis | found | cytometric bead array assay | (none: key "multiplex cytokine analysis") | registry unmapped |
| polychromatic flow cytometry (MIMIC DC/T cell co-culture) | CD4 + T cell stimulation assay | found | flow cytometry assay | T cell activation induced marker assay | DIFFERENT |
| microarray analysis (VaxDesign/MIMIC samples) | gene array | MERGED with other benchmark entries | transcription profiling by array assay | microarray assay | DIFFERENT |
| lysis plaque assay [gc=false] | lysis plaque assay | found | viral plaque assay | viral plaque assay | same |

### SDY1294 / PMID 28687661

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| microarray analysis | microarray hybridization | found | transcription profiling by array assay | microarray assay | DIFFERENT |
| flow cytometry | flow cytometry | found | flow cytometry assay | flow cytometry assay | same |
| plaque reduction neutralization test (PRNT) | plaque reduction neutralization test (PRNT) | found | pathogen neutralization assay | pathogen neutralization assay | same |
| immunofluorescence assay | fluorescence microscopy | found | fluorescence microscopy assay | fluorescence microscopy assay | same |
| — | NK-mediated ADCC assay | EXTRA in registry | — | cell-cell killing assay | — |
| — | intracellular cytokine staining | EXTRA in registry | — | (none: key "intracellular cytokine staining") | — |

### SDY1325 / PMID 28137280

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| human complement serum bactericidal assay | Serum bactericidal assay | found | (none) | bacterial neutralization assay | benchmark unmapped |
| B-cell enzyme-linked immunospot assay | B-cell enzyme-linked immunospot assay | found | enzyme-linked immunospot assay | enzyme-linked immunospot assay | same |
| flow cytometric characterisation of B cells and plasma cells | flow cytometric characterisation of B cells and plasma cells | found | flow cytometry assay | flow cytometry assay | same |
| Illumina® Human HT12v4.0 Expression BeadChip microarray | microarray | found | transcription profiling by array assay | microarray assay | DIFFERENT |
| quantitative real-time PCR | Quantitative real-time PCR | found | real time reverse-transcription polymerase chain reaction assay | real time reverse-transcription polymerase chain reaction assay | same |

### SDY1328 / PMID 26742691

> ⚠️ benchmark file describes a different paper (TB CD4 T cells); the registry matches PMID 26742691 (EM131 hepatitis B cohort) — excluded from totals

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| RNA sequencing | — | MISSING in registry | RNA-seq assay | — | — |
| flow cytometry | — | MISSING in registry | flow cytometry assay | — | — |
| ABCB1 activity assay | — | MISSING in registry | flow cytometry assay | — | — |
| mass cytometry | — | MISSING in registry | cytometry time of flight assay | — | — |
| TB-specific reactivity of sorted CD4 T cell subsets | — | MISSING in registry | T cell activation induced marker assay | — | — |
| — | ELISA | EXTRA in registry | — | enzyme-linked immunosorbent assay | — |
| — | multiplex ELISA | EXTRA in registry | — | enzyme-linked immunosorbent assay | — |
| — | microarray | EXTRA in registry | — | microarray assay | — |
| — | Polychromatic FCM | EXTRA in registry | — | flow cytometry assay | — |
| — | complete blood count | EXTRA in registry | — | (none: key "complete blood count") | — |

### SDY1364 / PMID 23266342

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| ELISpot | ex vivo IFNγ ELISpot assay | found | enzyme-linked immunospot assay | enzyme-linked immunospot assay | same |
| flow cytometry | Surface and intracellular cytokine staining ; surface staining | SPLIT into 2 | flow cytometry assay | flow cytometry assay | same |
| ELISA | IgG enzyme linked immunosorbent assay (ELISA) | found | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | same |

### SDY1373 / PMID 28854372

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| Flow Cytometry Analysis | Flow Cytometry Analysis | found | flow cytometry assay | flow cytometry assay | same |
| Cytokine and Chemokine Multiplex Analysis | Cytokine and Chemokine Multiplex Analysis | found | multiplex bead-based protein state immunoassay | cytometric bead array assay | DIFFERENT |
| ELISA | ELISA | found | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | same |
| Next-Generation RNA Sequencing | Next-Generation RNA Sequencing | found | polyA-selected RNA sequencing assay | RNA-seq assay | DIFFERENT |

### SDY1389 / PMID 30111633

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| Flow cytometry and sorting | flow cytometry | found | flow cytometry assay | flow cytometry assay | same |
| Whole-Transcriptome Profiling by RNA-Sequencing | RNA-Sequencing | found | polyA-selected RNA sequencing assay | RNA-seq assay | DIFFERENT |
| CyTOF Sample Preparation and Analysis | CyTOF | found | cytometry time of flight assay | cytometry time of flight assay | same |
| T cell proliferation assays | T cell proliferation assays | found | cell proliferation assay | cell proliferation assay | same |
| Human T cell receptor (TCR) sequencing and analysis | TCR sequencing | found | amplicon sequencing assay | T cell receptor repertoire sequencing assay | DIFFERENT |
| — | HLA multimer staining | EXTRA in registry | — | (none: key "HLA multimer staining") | — |

### SDY1393 / PMID 36656789

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| flow cytometry | flow cytometry | found | flow cytometry assay | flow cytometry assay | same |
| RNA-seq | RNA‐seq | found | RNA-seq assay | RNA-seq assay | same |
| HAI [gc=false] | hemagglutination inhibition assay | found | viral hemagglutination inhibition assay | viral hemagglutination inhibition assay | same |

### SDY1596 / PMID 32005538

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| Luminex | fluorescent bead-based multianalyte xMAP technology cytokine kit | found | cytometric bead array assay | cytometric bead array assay | same |
| Flow Cytometry | flow cytometry | found | flow cytometry assay | flow cytometry assay | same |
| — | culturable microbial count assay | EXTRA in registry | — | (none: key "culturable microbial count assay") | — |

### SDY1630 / PMID 32059780

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| flow cytometry analysis | flow cytometry analysis ; High-dimensional parameter flow cytometric analysis of NK cell subsets | SPLIT into 2 | flow cytometry assay | flow cytometry assay | same |
| in vitro cytokine stimulation and functional assays | In vitro cytokine stimulation and functional assays of NK cells ; measuring degranulation by NK cells | SPLIT into 2 | assay detecting IFN-gamma production | (none: key "In vitro cytokine stimulation and functional assays of NK cells") ; (none: key "measuring degranulation by NK cells") | registry unmapped |
| whole transcriptome profiling by RNA sequencing (RNA-seq) | Whole transcriptome profiling of NK cell subsets | found | RNA-seq assay | (none: key "Whole transcriptome profiling of NK cell subsets") | registry unmapped |

### SDY1640 / PMID 32473127

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| Activation Induced Marker (AIM) assay | Activation induced cell marker assay | found | T cell activation induced marker assay | T cell activation induced marker assay | same |
| intracellular cytokine staining assay | Intracellular cytokine staining assay | found | immuno staining assay | cytometry assay | DIFFERENT |
| flow cytometry | Direct ex vivo PBMC immune cell phenotyping | found | flow cytometry assay | (none: key "Direct ex vivo PBMC immune cell phenotyping") | registry unmapped |
| SARS-CoV-2 RBD ELISA | SARS-CoV-2 RBD ELISA | found | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | same |
| cytokine bead assay | Cytokine bead assays | found | analyte detection by flow based bead assay | (none: key "Cytokine bead assays") | registry unmapped |
| — | OC43 and NL63 coronavirus RBD ELISA | EXTRA in registry | — | enzyme-linked immunosorbent assay | — |
| — | lateral flow assay | EXTRA in registry | — | (none: key "lateral flow assay") | — |

### SDY1654 / PMID 31624246

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| single cell RNA-sequencing (scRNA-seq) | Single-Cell RNA-seq | found | single-cell RNA sequencing assay | single-cell RNA sequencing assay | same |
| flow cytometry | flow cytometry | found | flow cytometry assay | flow cytometry assay | same |
| proliferation assay | proliferation assays | found | cell proliferation assay | cell proliferation assay | same |
| quantitative real-time PCR (qPCR) | Quantitative real-time PCR | found | real time reverse-transcription polymerase chain reaction assay | real time polymerase chain reaction assay | DIFFERENT |

### SDY1655 / PMID 32717743

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| RT-qPCR | RT-qPCR | found | real time reverse-transcription polymerase chain reaction assay | real time reverse-transcription polymerase chain reaction assay | same |
| Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71) | Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71) | found | cytometric bead array assay | (none: key "Human Cytokine Array/Chemokine Array 71–403 Plex Panel (HD71)") | registry unmapped |
| flow cytometry | flow cytometry | found | flow cytometry assay | flow cytometry assay | same |

### SDY1669 / PMID 32788292

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| phospho-CyTOF | mass cytometry | found | cytometry time of flight assay | cytometry time of flight assay | same |
| Olink multiplex inflammation panel | Olink multiplex inflammation panel | found | Olink assay | Olink assay | same |
| enzyme-linked immunosorbent assay (ELISA) | enzyme-linked immunosorbent assay (ELISA) ; highly sensitive ELISA enabled by single molecule array (SIMoA) technology | SPLIT into 2 | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | same |
| cellular indexing of transcriptomes and epitopes by sequencing (CITE-seq) | cellular indexing of transcriptomes and epitopes by sequencing (CITE-seq) | found | cellular indexing of transcriptomes and epitopes by sequencing | cellular indexing of transcriptomes and epitopes by sequencing | same |
| bulk RNA sequencing (RNA-seq) | bulk RNA sequencing (RNA-seq) analysis | found | RNA-seq assay | bulk RNA-seq assay | DIFFERENT |
| PCR quantitation of bacterial 16S ribosomal RNA (rRNA) gene product | PCR quantitation of bacterial 16 S ribosomal RNA (rRNA) gene product | found | real time polymerase chain reaction assay | organism detection by PCR assay | DIFFERENT |
| TLR4-based reporter assay | TLR4-based reporter assay | found | (none) | reporter cell line analyte detection bioassay | benchmark unmapped |
| — | intracellular staining assay | EXTRA in registry | — | cytometry assay | — |

### SDY1708 / PMID 34128959

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| Mass cytometry | Mass cytometry | found | cytometry time of flight assay | cytometry time of flight assay | same |
| scRNA-seq | scRNA-seq | found | single-cell RNA sequencing assay | single-cell RNA sequencing assay | same |
| scATAC-seq | scATAC-seq | found | single-cell ATAC-seq | single-cell ATAC-seq | same |
| — | Hi-C data | EXTRA in registry | — | carbon-copy chromosome conformation capture assay followed by sequencing assay | — |

### SDY1991 / PMID 35455361

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| RNA-Sequencing Assay | Microscaled RNA-Seq | found | RNA-seq assay | bulk RNA-seq assay | DIFFERENT |
| flow cytometry | flow cytometry-based neutralization assays | found | flow cytometry assay | (none: key "flow cytometry-based neutralization assays") | registry unmapped |
| — | DENV-specific IgG ELISAs | EXTRA in registry | — | enzyme-linked immunosorbent assay | — |
| — | IFN-γ Secretion Assay | EXTRA in registry | — | cytokine assay | — |

### SDY1995 / PMID 35062294

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| RNA Sequencing | RNA Sequencing | found | RNA-seq assay | RNA sequencing assay | DIFFERENT |
| Flow Cytometry | flow cytometry | found | flow cytometry assay | flow cytometry assay | same |
| ELISA [gc=false] | ELISA | found | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | same |
| Reverse transcription-PCR [gc=false] | reverse transcription-PCR | found | real time reverse-transcription polymerase chain reaction assay | reverse transcription polymerase chain reaction assay | DIFFERENT |

### SDY2189 / PMID 34252919

| Benchmark name | Registry wording(s) | Step 1 | Benchmark OBI | Registry OBI | Step 2 |
|---|---|---|---|---|---|
| ELISA | Anti-spike binding enzyme-linked immunosorbent assay | found | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | same |
| Focus reduction neutralization titre assay | Focus reduction neutralization titre assay ; FRNT assay against the variants of concern | SPLIT into 2 | serum neutralization of viral infectivity assay | serum neutralization of viral infectivity assay | same |
| Intracellular cytokine staining assay | Intracellular cytokine staining assay | found | cytokine assay | immuno staining assay | DIFFERENT |
| Bead-based antigen arrays | Bead-based antigen arrays | found | antibody detection by cytometric bead array assay | antigen specific antibodies assay | DIFFERENT |
| CyTOF analysis of whole-blood samples | CyTOF analysis of whole-blood samples | found | cytometry time of flight assay | cytometry time of flight assay | same |
| Plasma protein profiling using multiplex Olink panel | Olink multiplex proximity extension assay (PEA) inflammation panel | found | Olink assay | Olink assay | same |
| Single-molecule array | — | MISSING in registry | (none) | — | — |
| Bulk transcriptomics | Bulk transcriptomics | found | bulk RNA-seq assay | bulk RNA-seq assay | same |
| CITE-seq | CITE-seq | found | cellular indexing of transcriptomes and epitopes by sequencing | cellular indexing of transcriptomes and epitopes by sequencing | same |
| RNA isolation and qPCR | RNA isolation and qPCR | found | real time reverse-transcription polymerase chain reaction assay | real time reverse-transcription polymerase chain reaction assay | same |
