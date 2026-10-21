# Pruned (701) vs full (1794) vocabulary, 31 papers

| metric | pruned | full | stability_reference |
|---|---|---|---|
| papers scored | 31 | 31 | 31 |
| curated rows | 161 | 161 | 161 |
| agent entries | 157 | 157 | 157 |
| matched | 150 | 150 | 150 |
| exact (same OBI term as curator) | 132 | 126 | 131 |
| obi_exact_rate | 88.0% | 84.0% | 87.3% |
| obi_recall | 82.0% | 78.3% | 81.4% |
| unresolved (no term) | 2 | 4 | 4 |
| lookup errors | 0 | 0 | 0 |
| calls spent | 434 | 449 | 434 |
| MATCH | 132 | 126 | 131 |
| MATCH_GRANULARITY | 5 | 7 | 5 |
| MATCH_OBI_CONFLICT | 7 | 9 | 7 |
| MATCH_OBI_UNMAPPED | 6 | 8 | 7 |
| MISSED | 11 | 11 | 11 |
| EXTRA | 2 | 2 | 3 |

## pruned vs full: entries that chose different terms (8)

counts: {'pruned': 6, 'neither': 2, 'changed': 8, 'full_term_compositional': 4, 'full_term_outside_pruned_index': 4}

| registry | entry | pruned | full | curator | agrees |
|---|---|---|---|---|---|
| 20078211_SDY1293_pdf | microscopy assay | OBI:0002119 microscopy assay | OBI:0002649 blood microbiology assay | OBI:0002119 microscopy assay | pruned |
| 23266342_SDY1364 | enzyme-linked immunospot assay | OBI:0600031 enzyme-linked immunospot assay | OBI:1110059 ELISPOT assay measuring epitope specific interferon-gamma production by T cells (compositional) | OBI:0600031 enzyme-linked immunospot assay | pruned |
| 23266342_SDY1364 | flow cytometry assay | OBI:0000916 flow cytometry assay | OBI:1110172 intracellular cytokine staining assay measuring epitope specific interferon-gamma production by T cells (compositional) | OBI:0000916 flow cytometry assay | pruned |
| 23844129_SDY1364 | enzyme-linked immunospot assay | OBI:0600031 enzyme-linked immunospot assay | OBI:1110059 ELISPOT assay measuring epitope specific interferon-gamma production by T cells (compositional) | OBI:0600031 enzyme-linked immunospot assay | pruned |
| 26742691_SDY1328 | complete blood count | OBI:0003040 blood assay | None None | OBI:0000630 hematology assay | neither |
| 32717743_SDY1655 | antigen detection by cytometric bead array assay | OBI:0003115 antigen detection by cytometric bead array assay | None None | OBI:0000920 cytometric bead array assay | neither |
| 32788292_SDY1669 | bacterial lipopolysaccharide detection in plasma assay | OBI:0003793 bacterial lipopolysaccharide detection in plasma assay | OBI:0000904 reporter cell line analyte detection bioassay | OBI:0003793 bacterial lipopolysaccharide detection in plasma assay | pruned |
| 35455361_SDY1991 | flow cytometry assay | OBI:0000916 flow cytometry assay | OBI:1110207 assay detecting IFN-gamma production (compositional) | OBI:0000916 flow cytometry assay | pruned |

## pruned vs stability_reference: entries that chose different terms (8)

counts: {'stability_reference': 1, 'no curated term': 3, 'pruned': 2, 'neither': 2}

| registry | entry | pruned | stability_reference | curator | agrees |
|---|---|---|---|---|---|
| 19029902_SDY1264 | real time reverse-transcription polymerase chain reaction assay | OBI:0001170 reverse transcription polymerase chain reaction assay | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | stability_reference |
| 19029902_SDY1264 | immunocytochemistry | CHMO:0000087 fluorescence microscopy assay | OBI:0002174 immunocytochemistry | —  | no curated term |
| 20078211_SDY1293_pdf | real time polymerase chain reaction assay | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | OBI:0000893 real time polymerase chain reaction assay | OBI:0000911 real time reverse-transcription polymerase chain reaction assay | pruned |
| 24336226_SDY1260 | cytometric bead array assay | OBI:0003116 antibody detection by cytometric bead array assay | OBI:0000920 cytometric bead array assay | OBI:0003116 antibody detection by cytometric bead array assay | pruned |
| 26742691_SDY1328 | complete blood count | OBI:0003040 blood assay | None None | OBI:0000630 hematology assay | neither |
| 28502771_SDY984 | analyte detection by flow based bead assay | OBI:0000920 cytometric bead array assay | OBI:0003799 analyte detection by flow based bead assay | —  | no curated term |
| 28687661_SDY1294 | immuno staining assay | OBI:0002119 microscopy assay | OBI:0001632 immuno staining assay | CHMO:0000087 fluorescence microscopy assay | neither |
| 32473127_SDY1640 | lateral flow assay | OBI:0000443 analyte assay | None None | —  | no curated term |
