# Pruned (701) vs full (1794) vocabulary, assay_result_v3 against benchmark v5

| metric | pruned | full | noncompositional | v3_reference |
|---|---|---|---|---|
| papers scored | 31 | 31 | 31 | 31 |
| curated rows | 157 | 157 | 157 | 157 |
| agent entries | 177 | 177 | 177 | 177 |
| matched | 156 | 156 | 156 | 156 |
| exact (same OBI term as curator) | 141 | 130 | 140 | 140 |
| OBI ok (same or parent/child) | 145 | 139 | 144 | 145 |
| obi_exact_rate | 90.4% | 83.3% | 89.7% | 89.7% |
| obi_recall | 92.4% | 88.5% | 91.7% | 92.4% |
| unresolved (no term) | 2 | 3 | 2 | 2 |
| lookup errors | 0 | 0 | 0 | 0 |
| calls spent | 495 | 510 | 495 | 338 |
| MATCH | 141 | 130 | 140 | 140 |
| MATCH_GRANULARITY | 4 | 9 | 4 | 5 |
| MATCH_OBI_CONFLICT | 5 | 10 | 6 | 5 |
| MATCH_OBI_UNMAPPED | 6 | 7 | 6 | 6 |
| MISSED | 1 | 1 | 1 | 1 |
| EXTRA | 5 | 4 | 5 | 4 |

## pruned vs full: entries that chose different terms (15)

counts: {'pruned': 12, 'no curated term': 1, 'full': 1, 'neither': 1, 'changed': 15, 'full_term_compositional': 7, 'full_term_outside_pruned_index': 7}

| registry | entry | pruned | full | curator | agrees |
|---|---|---|---|---|---|
| 19047440_SDY1289 | cell proliferation assay using carboxyfluorescein succinimidyl ester staining | OBI:0003582 cell proliferation assay using carboxyfluorescein succinimidyl ester staining | OBI:0002096 carboxyfluorescein succinimidyl ester staining assay measuring epitope specific proliferation of T cells (compositional) | OBI:0003582 cell proliferation assay using carboxyfluorescein succinimidyl ester staining | pruned |
| 19047440_SDY1289 | analyte detection by flow based bead assay | OBI:0003799 analyte detection by flow based bead assay | OBI:0000920 cytometric bead array assay | OBI:0003799 analyte detection by flow based bead assay | pruned |
| 20078211_SDY1293_pdf | microscopy assay | OBI:0002119 microscopy assay | OBI:0002649 blood microbiology assay | OBI:0002119 microscopy assay | pruned |
| 23266342_SDY1364 | enzyme-linked immunospot assay | OBI:0600031 enzyme-linked immunospot assay | OBI:1110059 ELISPOT assay measuring epitope specific interferon-gamma production by T cells (compositional) | OBI:0600031 enzyme-linked immunospot assay | pruned |
| 23844129_SDY1364 | enzyme-linked immunospot assay | OBI:0600031 enzyme-linked immunospot assay | OBI:1110059 ELISPOT assay measuring epitope specific interferon-gamma production by T cells (compositional) | OBI:0600031 enzyme-linked immunospot assay | pruned |
| 28502771_SDY984 | cytometric bead array assay (2) | OBI:0003799 analyte detection by flow based bead assay | OBI:0000920 cytometric bead array assay | —  | no curated term |
| 28687661_SDY1294 | immuno staining assay | OBI:0001632 immuno staining assay | OBI:0001501 fluorescence detection assay | OBI:0001632 immuno staining assay | pruned |
| 28687661_SDY1294 | cell-cell killing assay | OBI:0000882 cell-cell killing assay | OBI:0001642 assay measuring epitope specific antibody-dependent cellular cytotoxicity (compositional) | OBI:0000882 cell-cell killing assay | pruned |
| 32059780_SDY1630 | flow cytometry assay (3) | OBI:0000916 flow cytometry assay | OBI:1110207 assay detecting IFN-gamma production (compositional) | OBI:1110207 assay detecting IFN-gamma production | full |
| 32473127_SDY1640 | analyte detection by flow based bead assay | OBI:0003799 analyte detection by flow based bead assay | OBI:0000920 cytometric bead array assay | OBI:0003799 analyte detection by flow based bead assay | pruned |
| 32717743_SDY1655 | cytometric bead array assay | OBI:0000920 cytometric bead array assay | None None | OBI:0003115 antigen detection by cytometric bead array assay | neither |
| 32788292_SDY1669 | polymerase chain reaction assay | OBI:0000893 real time polymerase chain reaction assay | OBI:0002692 polymerase chain reaction assay | OBI:0000893 real time polymerase chain reaction assay | pruned |
| 32788292_SDY1669 | bacterial lipopolysaccharide detection in plasma assay | OBI:0003793 bacterial lipopolysaccharide detection in plasma assay | OBI:0000904 reporter cell line analyte detection bioassay | OBI:0003793 bacterial lipopolysaccharide detection in plasma assay | pruned |
| 34252919_SDY2189 | enzyme-linked immunosorbent assay | OBI:0000661 enzyme-linked immunosorbent assay | OBI:0001657 ELISA measuring binding of a B cell epitope:antibody complex (compositional) | OBI:0000661 enzyme-linked immunosorbent assay | pruned |
| 35455361_SDY1991 | flow cytometry assay | OBI:0000916 flow cytometry assay | OBI:1110207 assay detecting IFN-gamma production (compositional) | OBI:0000916 flow cytometry assay | pruned |

## pruned vs noncompositional: entries that chose different terms (1)

counts: {'pruned': 1, 'changed': 1, 'noncompositional_term_compositional': 0, 'noncompositional_term_outside_pruned_index': 0}

| registry | entry | pruned | noncompositional | curator | agrees |
|---|---|---|---|---|---|
| 20078211_SDY1293_pdf | microscopy assay | OBI:0002119 microscopy assay | OBI:0002649 blood microbiology assay | OBI:0002119 microscopy assay | pruned |

## pruned vs v3_reference: entries that chose different terms (2)

counts: {'no curated term': 1, 'pruned': 1, 'changed': 2, 'v3_reference_term_compositional': 0, 'v3_reference_term_outside_pruned_index': 0}

| registry | entry | pruned | v3_reference | curator | agrees |
|---|---|---|---|---|---|
| 28502771_SDY984 | cytometric bead array assay (2) | OBI:0003799 analyte detection by flow based bead assay | OBI:0000920 cytometric bead array assay | —  | no curated term |
| 32788292_SDY1669 | polymerase chain reaction assay | OBI:0000893 real time polymerase chain reaction assay | OBI:0002692 polymerase chain reaction assay | OBI:0000893 real time polymerase chain reaction assay | pruned |
