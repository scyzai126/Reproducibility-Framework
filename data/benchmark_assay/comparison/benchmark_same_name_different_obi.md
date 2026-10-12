# Benchmark: same assay name, different OBI

Benchmark files read: 31 (`_v2` preferred over older files for the same paper). Names match after lowercasing and dropping parentheticals, punctuation and the words assay/analysis/test.

## Same name in paper -> different OBI (5)

### intracellular cytokine staining

| study | pmid | name_in_paper | OBI |
|---|---|---|---|
| SDY1640 | 32473127 | intracellular cytokine staining assay | immuno staining assay (OBI:0001632) |
| SDY2189 | 34252919 | Intracellular cytokine staining assay | cytokine assay (OBI:0002766) |

### microarray

| study | pmid | name_in_paper | OBI |
|---|---|---|---|
| SDY1260 | 24336226 | microarray | microarray assay (OBI:0002631) |
| SDY1264 | 19029902 | microarray | microarray assay (OBI:0002631) |
| SDY1276 | 21357945 | Microarray Analysis | transcription profiling by array assay (OBI:0001463) |
| SDY1289 | 19047440 | microarray analysis (VaxDesign/MIMIC samples) | transcription profiling by array assay (OBI:0001463) |
| SDY1294 | 28687661 | microarray analysis | transcription profiling by array assay (OBI:0001463) |
| SDY1328 | 26742691 | microarray | transcription profiling by array assay (OBI:0001463) |
| SDY180 | 23601689 | Microarray Assay | transcription profiling by array assay (OBI:0001463) |

### quantitative real time pcr

| study | pmid | name_in_paper | OBI |
|---|---|---|---|
| SDY1289 | 19047440 | quantitative real-time PCR (qPCR) | real time polymerase chain reaction assay (OBI:0000893) |
| SDY1325 | 28137280 | quantitative real-time PCR | real time reverse-transcription polymerase chain reaction assay (OBI:0000911) |
| SDY1654 | 31624246 | quantitative real-time PCR (qPCR) | real time reverse-transcription polymerase chain reaction assay (OBI:0000911) |

### rna seq

| study | pmid | name_in_paper | OBI |
|---|---|---|---|
| SDY1288 | 30150281 | RNA-seq | bulk RNA-seq assay (OBI:0003090) |
| SDY1393 | 36656789 | RNA-seq | RNA-seq assay (OBI:0001271) |

### whole transcriptome profiling by rna sequencing

| study | pmid | name_in_paper | OBI |
|---|---|---|---|
| SDY1389 | 30111633 | Whole-Transcriptome Profiling by RNA-Sequencing | polyA-selected RNA sequencing assay (OBI:0003090) |
| SDY1630 | 32059780 | whole transcriptome profiling by RNA sequencing (RNA-seq) | RNA-seq assay (OBI:0001271) |

## id/label pair disagrees with obi.obo (2)

| benchmark obi_id | benchmark obi_label | obi.obo label for that id | studies |
|---|---|---|---|
| OBI:0002631 | microarray assay | single-cell RNA sequencing assay | SDY1260, SDY1264 |
| OBI:0003090 | polyA-selected RNA sequencing assay | bulk RNA-seq assay | SDY1389 |
