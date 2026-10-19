# Microarray vs. transcription profiling by array assay

In OBI these are two different kinds of thing. A **microarray** is the physical chip. A **transcription profiling by array assay** is one experiment you can run with that chip. These definitions come from `data/OBI/obi.obo`.

| | `microarray` (OBI:0400147) | `transcription profiling by array assay` (OBI:0001463) |
|---|---|---|
| What it is | A **material**, a "processed material… a physical immobilisation matrix in which substances that bind the analyte are placed in regular spatial position" | An **assay**, "a transcription profiling assay that uses array technology" |
| Parent | `assay array` (OBI:0001865) | `transcription profiling assay` (OBI:0000424) |
| Synonyms | Child `DNA microarray` (OBI:0400148): "DNA Chip", "DNA-array" | "RNA profiling by array assay" |
| Example | An Affymetrix HG-U133 Plus 2.0 chip | Measuring gene expression in PBMCs by hybridising labelled RNA/cDNA to that chip |

## Why this matters for assay mapping

- **A gene expression microarray in a paper should map to OBI:0001463.** The word "microarray" alone names the device, and `microarray` is not an assay term.
- **The same kind of chip can be used for other assays**, each with its own OBI assay term:
  - genotyping (SNP arrays)
  - DNA methylation profiling (e.g. Illumina 450K/EPIC)
  - ChIP-chip
  - protein or antibody arrays (`protein microarray` OBI:0400149 is the device for these)

  So "microarray" on its own doesn't tell you which assay was done. Use the readout (transcripts, methylation, genotype, protein) to pick the term.
- **The RNA-seq counterpart** is "transcription profiling by high throughput sequencing". Both it and OBI:0001463 sit under the same parent, `transcription profiling assay`.
