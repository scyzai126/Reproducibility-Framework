# Full-list LLM (701 terms) vs embedding top-20, 10 worst papers of assay_result_v3

Papers: 19029902_SDY1264, 24336226_SDY1260, 26742691_SDY1328, 28854372_SDY1373, 28502771_SDY984, 19047440_SDY1289, 32473127_SDY1640, 32005538_SDY1596, 32059780_SDY1630, 32717743_SDY1655

| metric | fulllist | embedding | v3_reference |
|---|---|---|---|
| papers scored | 10 | 10 | 10 |
| curated rows | 55 | 55 | 55 |
| agent entries | 70 | 70 | 70 |
| matched | 55 | 55 | 55 |
| exact (same OBI term as curator) | 41 | 40 | 40 |
| OBI ok (same or parent/child) | 47 | 44 | 44 |
| obi_exact_rate | 74.5% | 72.7% | 72.7% |
| obi_recall | 85.5% | 80.0% | 80.0% |
| MATCH | 41 | 40 | 40 |
| MATCH_GRANULARITY | 6 | 4 | 4 |
| MATCH_OBI_CONFLICT | 4 | 5 | 5 |
| MATCH_OBI_UNMAPPED | 4 | 6 | 6 |
| SPLIT | 8 | 8 | 9 |
| MISSED | 0 | 0 | 0 |
| EXTRA | 4 | 5 | 4 |

Full-list spend: {'calls': 66, 'prompt_tokens': 2575585, 'cached_tokens': 2443008, 'completion_tokens': 342}

## Per entry, embedding vs fulllist ({'same': 61, 'won': 5, 'lost': 3, 'changed': 1})

| registry | entry | curator | fulllist | embedding | v3_reference | verdict |
|---|---|---|---|---|---|---|
| 19047440_SDY1289 | real time reverse-transcription polymerase chain reaction assay | real time polymerase chain reaction assay | real time polymerase chain reaction assay (MATCH) | real time reverse-transcription polymerase chain reaction assay (MATCH_OBI_CONFLICT) | real time reverse-transcription polymerase chain reaction assay (MATCH_OBI_CONFLICT) | won |
| 26742691_SDY1328 | complete blood count | hematology assay | hematology assay (MATCH) | — (MATCH_OBI_UNMAPPED) | — (MATCH_OBI_UNMAPPED) | won |
| 26742691_SDY1328 | multiplex ELISA protocol Human Inflammation multianalyte profiling | cytometric bead array assay | cytometric bead array assay (MATCH) | — (MATCH_OBI_UNMAPPED) | — (MATCH_OBI_UNMAPPED) | won |
| 26742691_SDY1328 | surface HBV antibody assay | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | surface HBV antibody assay (EXTRA) | surface HBV antibody assay (EXTRA) | won |
| 28502771_SDY984 | cytometric bead array assay (2) | cytometric bead array assay | cytometric bead array assay (MATCH) | analyte detection by flow based bead assay (EXTRA) | cytometric bead array assay (MATCH) | won |
| 19047440_SDY1289 | analyte detection by flow based bead assay | analyte detection by flow based bead assay | cytometric bead array assay (MATCH_GRANULARITY) | analyte detection by flow based bead assay (MATCH) | analyte detection by flow based bead assay (MATCH) | lost |
| 32005538_SDY1596 | flow cytometry assay | flow cytometry assay | cell viability assay (EXTRA) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | lost |
| 32059780_SDY1630 | bulk RNA-seq assay | bulk RNA-seq assay | RNA-seq assay (MATCH_GRANULARITY) | bulk RNA-seq assay (MATCH) | bulk RNA-seq assay (MATCH) | lost |
| 32005538_SDY1596 | blood assay | — | — (EXTRA) | blood assay (EXTRA) | blood assay (EXTRA) | changed |
| 19029902_SDY1264 | cytometric bead array assay | cytometric bead array assay | cytometric bead array assay (MATCH) | cytometric bead array assay (MATCH) | cytometric bead array assay (MATCH) | same |
| 19029902_SDY1264 | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | same |
| 19029902_SDY1264 | flow cytometry assay | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 19029902_SDY1264 | fluorescence microscopy assay | — | fluorescence microscopy assay (MATCH_OBI_UNMAPPED) | fluorescence microscopy assay (MATCH_OBI_UNMAPPED) | fluorescence microscopy assay (MATCH_OBI_UNMAPPED) | same |
| 19029902_SDY1264 | reverse transcription polymerase chain reaction assay | real time reverse-transcription polymerase chain reaction assay | reverse transcription polymerase chain reaction assay (MATCH_OBI_CONFLICT) | reverse transcription polymerase chain reaction assay (MATCH_OBI_CONFLICT) | reverse transcription polymerase chain reaction assay (MATCH_OBI_CONFLICT) | same |
| 19029902_SDY1264 | serum neutralization of viral infectivity assay | serum neutralization of viral infectivity assay | serum neutralization of viral infectivity assay (MATCH) | serum neutralization of viral infectivity assay (MATCH) | serum neutralization of viral infectivity assay (MATCH) | same |
| 19029902_SDY1264 | serum neutralization of viral infectivity assay (2) | serum neutralization of viral infectivity assay | serum neutralization of viral infectivity assay (MATCH) | serum neutralization of viral infectivity assay (MATCH) | serum neutralization of viral infectivity assay (MATCH) | same |
| 19029902_SDY1264 | transcription profiling by array assay | transcription profiling by array assay | transcription profiling by array assay (MATCH) | transcription profiling by array assay (MATCH) | transcription profiling by array assay (MATCH) | same |
| 19029902_SDY1264 | western blot assay | immunoblot assay | western blot assay (MATCH_GRANULARITY) | western blot assay (MATCH_GRANULARITY) | western blot assay (MATCH_GRANULARITY) | same |
| 19047440_SDY1289 | cell proliferation assay using carboxyfluorescein succinimidyl ester staining | cell proliferation assay using carboxyfluorescein succinimidyl ester staining | cell proliferation assay using carboxyfluorescein succinimidyl ester staining (MATCH) | cell proliferation assay using carboxyfluorescein succinimidyl ester staining (MATCH) | cell proliferation assay using carboxyfluorescein succinimidyl ester staining (MATCH) | same |
| 19047440_SDY1289 | cytometric bead array assay | cytometric bead array assay | cytometric bead array assay (MATCH) | cytometric bead array assay (MATCH) | cytometric bead array assay (MATCH) | same |
| 19047440_SDY1289 | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | same |
| 19047440_SDY1289 | flow cytometry assay | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 19047440_SDY1289 | flow cytometry assay (2) | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 19047440_SDY1289 | flow cytometry assay (3) | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 19047440_SDY1289 | transcription profiling by array assay | transcription profiling by array assay | transcription profiling by array assay (MATCH) | transcription profiling by array assay (MATCH) | transcription profiling by array assay (MATCH) | same |
| 24336226_SDY1260 | bacterial neutralization assay | — | bacterial neutralization assay (MATCH_OBI_UNMAPPED) | bacterial neutralization assay (MATCH_OBI_UNMAPPED) | bacterial neutralization assay (MATCH_OBI_UNMAPPED) | same |
| 24336226_SDY1260 | cytometric bead array assay | antibody detection by cytometric bead array assay | cytometric bead array assay (MATCH_GRANULARITY) | cytometric bead array assay (MATCH_GRANULARITY) | cytometric bead array assay (MATCH_GRANULARITY) | same |
| 24336226_SDY1260 | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | same |
| 24336226_SDY1260 | enzyme-linked immunosorbent assay (2) | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | same |
| 24336226_SDY1260 | enzyme-linked immunospot assay | enzyme-linked immunospot assay | enzyme-linked immunospot assay (MATCH) | enzyme-linked immunospot assay (MATCH) | enzyme-linked immunospot assay (MATCH) | same |
| 24336226_SDY1260 | flow cytometry assay | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 24336226_SDY1260 | flow cytometry assay (2) | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 24336226_SDY1260 | transcription profiling by array assay | transcription profiling by array assay | transcription profiling by array assay (MATCH) | transcription profiling by array assay (MATCH) | transcription profiling by array assay (MATCH) | same |
| 26742691_SDY1328 | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | same |
| 26742691_SDY1328 | enzyme-linked immunosorbent assay (2) | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | same |
| 26742691_SDY1328 | flow cytometry assay | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 26742691_SDY1328 | transcription profiling by array assay | transcription profiling by array assay | transcription profiling by array assay (MATCH) | transcription profiling by array assay (MATCH) | transcription profiling by array assay (MATCH) | same |
| 28502771_SDY984 | amplicon sequencing assay | amplicon sequencing assay | amplicon sequencing assay (MATCH) | amplicon sequencing assay (MATCH) | amplicon sequencing assay (MATCH) | same |
| 28502771_SDY984 | cytometric bead array assay | cytometric bead array assay | cytometric bead array assay (MATCH) | cytometric bead array assay (MATCH) | cytometric bead array assay (MATCH) | same |
| 28502771_SDY984 | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | same |
| 28502771_SDY984 | enzyme-linked immunospot assay | enzyme-linked immunospot assay | enzyme-linked immunospot assay (MATCH) | enzyme-linked immunospot assay (MATCH) | enzyme-linked immunospot assay (MATCH) | same |
| 28502771_SDY984 | enzyme-linked immunospot assay (2) | enzyme-linked immunospot assay | enzyme-linked immunospot assay (MATCH) | enzyme-linked immunospot assay (MATCH) | enzyme-linked immunospot assay (MATCH) | same |
| 28502771_SDY984 | flow cytometry assay | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 28502771_SDY984 | metabolomics by mass spectrometry assay | liquid chromatography mass spectrometry assay | metabolomics by mass spectrometry assay (MATCH_OBI_CONFLICT) | metabolomics by mass spectrometry assay (MATCH_OBI_CONFLICT) | metabolomics by mass spectrometry assay (MATCH_OBI_CONFLICT) | same |
| 28502771_SDY984 | polymerase chain reaction assay | — | polymerase chain reaction assay (EXTRA) | polymerase chain reaction assay (EXTRA) | polymerase chain reaction assay (EXTRA) | same |
| 28502771_SDY984 | real time polymerase chain reaction assay | real time polymerase chain reaction assay | real time polymerase chain reaction assay (MATCH) | real time polymerase chain reaction assay (MATCH) | real time polymerase chain reaction assay (MATCH) | same |
| 28502771_SDY984 | tandem mass spectrometry assay | — | tandem mass spectrometry assay (EXTRA) | tandem mass spectrometry assay (EXTRA) | tandem mass spectrometry assay (EXTRA) | same |
| 28502771_SDY984 | transcription profiling by array assay | transcription profiling by array assay | transcription profiling by array assay (MATCH) | transcription profiling by array assay (MATCH) | transcription profiling by array assay (MATCH) | same |
| 28854372_SDY1373 | bulk RNA-seq assay | polyA-selected RNA sequencing assay | bulk RNA-seq assay (MATCH_OBI_CONFLICT) | bulk RNA-seq assay (MATCH_OBI_CONFLICT) | bulk RNA-seq assay (MATCH_OBI_CONFLICT) | same |
| 28854372_SDY1373 | cytometric bead array assay | analyte detection by flow based bead assay | cytometric bead array assay (MATCH_GRANULARITY) | cytometric bead array assay (MATCH_GRANULARITY) | cytometric bead array assay (MATCH_GRANULARITY) | same |
| 28854372_SDY1373 | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | same |
| 28854372_SDY1373 | flow cytometry assay | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 32005538_SDY1596 | cytometric bead array assay | cytometric bead array assay | cytometric bead array assay (MATCH) | cytometric bead array assay (MATCH) | cytometric bead array assay (MATCH) | same |
| 32005538_SDY1596 | flow cytometry assay (2) | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 32005538_SDY1596 | population count assay | — | population count assay (MATCH_OBI_UNMAPPED) | population count assay (MATCH_OBI_UNMAPPED) | population count assay (MATCH_OBI_UNMAPPED) | same |
| 32059780_SDY1630 | flow cytometry assay | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 32059780_SDY1630 | flow cytometry assay (2) | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 32059780_SDY1630 | flow cytometry assay (3) | assay detecting IFN-gamma production | flow cytometry assay (MATCH_OBI_CONFLICT) | flow cytometry assay (MATCH_OBI_CONFLICT) | flow cytometry assay (MATCH_OBI_CONFLICT) | same |
| 32059780_SDY1630 | flow cytometry assay (4) | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 32473127_SDY1640 | T cell activation induced marker assay | T cell activation induced marker assay | T cell activation induced marker assay (MATCH) | T cell activation induced marker assay (MATCH) | T cell activation induced marker assay (MATCH) | same |
| 32473127_SDY1640 | analyte detection by flow based bead assay | analyte detection by flow based bead assay | analyte detection by flow based bead assay (MATCH) | analyte detection by flow based bead assay (MATCH) | analyte detection by flow based bead assay (MATCH) | same |
| 32473127_SDY1640 | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | same |
| 32473127_SDY1640 | enzyme-linked immunosorbent assay (2) | enzyme-linked immunosorbent assay | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | enzyme-linked immunosorbent assay (MATCH) | same |
| 32473127_SDY1640 | flow cytometry assay | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 32473127_SDY1640 | flow cytometry assay (2) | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 32473127_SDY1640 | single-value binding of antibody with reporter to antigen assay | — | single-value binding of antibody with reporter to antigen assay (MATCH_OBI_UNMAPPED) | single-value binding of antibody with reporter to antigen assay (MATCH_OBI_UNMAPPED) | single-value binding of antibody with reporter to antigen assay (MATCH_OBI_UNMAPPED) | same |
| 32717743_SDY1655 | cytometric bead array assay | antigen detection by cytometric bead array assay | cytometric bead array assay (MATCH_GRANULARITY) | cytometric bead array assay (MATCH_GRANULARITY) | cytometric bead array assay (MATCH_GRANULARITY) | same |
| 32717743_SDY1655 | flow cytometry assay | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 32717743_SDY1655 | flow cytometry assay (2) | flow cytometry assay | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | flow cytometry assay (MATCH) | same |
| 32717743_SDY1655 | real time reverse-transcription polymerase chain reaction assay | real time reverse-transcription polymerase chain reaction assay | real time reverse-transcription polymerase chain reaction assay (MATCH) | real time reverse-transcription polymerase chain reaction assay (MATCH) | real time reverse-transcription polymerase chain reaction assay (MATCH) | same |
