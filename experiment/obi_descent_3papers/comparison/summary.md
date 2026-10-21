# OBI tree descent vs stored embedding mapping, three papers

| metric | embedding | descend | hybrid |
|---|---|---|---|
| papers scored | 3 | 3 | 3 |
| curated rows | 18 | 18 | 18 |
| agent entries | 18 | 18 | 18 |
| matched | 18 | 17 | 18 |
| exact (same OBI term as curator) | 11 | 10 | 11 |
| obi_exact_rate | 61.1% | 58.8% | 61.1% |
| obi_recall | 61.1% | 55.6% | 61.1% |
| unresolved (no term) | 0 | 0 | 0 |
| lookup errors | 0 | 0 | 0 |
| walks that backed off | 0 | 0 | 0 |
| calls spent | 41 | 37 | 11 |
| MATCH | 11 | 10 | 11 |
| MATCH_GRANULARITY | 2 | 1 | 2 |
| MATCH_OBI_CONFLICT | 3 | 4 | 3 |
| MATCH_OBI_UNMAPPED | 2 | 2 | 2 |
| MISSED | 0 | 1 | 0 |
| EXTRA | 0 | 1 | 0 |

## embedding vs descend: entries that chose different terms (5)

counts: {'embedding': 2, 'descend': 1, 'no curated term': 1, 'neither': 1}

| registry | entry | embedding | descend | curator | agrees | path (calls) | replies |
|---|---|---|---|---|---|---|---|
| 19029902_SDY1264 | serum neutralization of viral infectivity assay | OBI:0000872 serum neutralization of viral infectivity assay | OBI:0003796 pathogen neutralization assay | OBI:0000872 serum neutralization of viral infectivity assay | embedding | OBI:0003796 (2) | OBI:0000070:81; OBI:0003796:stop broad |
| 19029902_SDY1264 | transcription profiling by array assay | OBI:0001463 transcription profiling by array assay | OBI:0001985 microarray assay | OBI:0001463 transcription profiling by array assay | embedding | OBI:0001985 (1) | OBI:0001985:stop broad |
| 24336226_SDY1260 | cytometric bead array assay | OBI:0000920 cytometric bead array assay | OBI:0003116 antibody detection by cytometric bead array assay | OBI:0003116 antibody detection by cytometric bead array assay | descend | OBI:0000443 → OBI:0000920 → OBI:0003116 (3) | OBI:0000070:8; OBI:0000443:11; OBI:0000920:2 exact |
| 24336226_SDY1260 | bacterial neutralization assay | OBI:0003797 bacterial neutralization assay | OBI:0000743 immune response assay | —  | no curated term | OBI:0000743 (2) | OBI:0000070:16; OBI:0000743:stop broad |
| 28854372_SDY1373 | bulk RNA-seq assay | OBI:0003090 bulk RNA-seq assay | OBI:0000424 transcription profiling assay | OBI:0002571 polyA-selected RNA sequencing assay | neither | OBI:0000424 (2) | OBI:0000070:5; OBI:0000424:stop broad |

## embedding vs hybrid: entries that chose different terms (2)

counts: {'embedding': 1, 'hybrid': 1}

| registry | entry | embedding | hybrid | curator | agrees | path (calls) | replies |
|---|---|---|---|---|---|---|---|
| 19029902_SDY1264 | serum neutralization of viral infectivity assay | OBI:0000872 serum neutralization of viral infectivity assay | OBI:0000865 96-well neutralization assay | OBI:0000872 serum neutralization of viral infectivity assay | embedding | OBI:0000872 → OBI:0000865 (1) | OBI:0000872:1 broad |
| 24336226_SDY1260 | cytometric bead array assay | OBI:0000920 cytometric bead array assay | OBI:0003116 antibody detection by cytometric bead array assay | OBI:0003116 antibody detection by cytometric bead array assay | hybrid | OBI:0000920 → OBI:0003116 (1) | OBI:0000920:2 exact |

## Rows the embedding mapping got wrong, under each arm (7)

| registry | entry | curator | embedding | descend | hybrid |
|---|---|---|---|---|---|
| 19029902_SDY1264 | reverse transcription polymerase chain reaction assay | OBI:0000911 | OBI:0001170 (MATCH_OBI_CONFLICT) | OBI:0001170 (MATCH_OBI_CONFLICT, 2 calls) | OBI:0001170 (MATCH_OBI_CONFLICT, 0 calls) |
| 19029902_SDY1264 | fluorescence microscopy assay | — | CHMO:0000087 (MATCH_OBI_UNMAPPED) | CHMO:0000087 (MATCH_OBI_UNMAPPED, 5 calls) | CHMO:0000087 (MATCH_OBI_UNMAPPED, 1 calls) |
| 19029902_SDY1264 | western blot assay | OBI:0001978 | OBI:0000854 (MATCH_GRANULARITY) | OBI:0000854 (MATCH_GRANULARITY, 4 calls) | OBI:0000854 (MATCH_GRANULARITY, 1 calls) |
| 24336226_SDY1260 | cytometric bead array assay | OBI:0003116 | OBI:0000920 (MATCH_GRANULARITY) | OBI:0003116 (MATCH, 3 calls) | OBI:0003116 (MATCH, 1 calls) |
| 24336226_SDY1260 | bacterial neutralization assay | — | OBI:0003797 (MATCH_OBI_UNMAPPED) | OBI:0000743 (MATCH_OBI_UNMAPPED, 2 calls) | OBI:0003797 (MATCH_OBI_UNMAPPED, 0 calls) |
| 28854372_SDY1373 | cytometric bead array assay | OBI:0002970 | OBI:0000920 (MATCH_OBI_CONFLICT) | OBI:0000920 (MATCH_OBI_CONFLICT, 3 calls) | OBI:0000920 (MATCH_OBI_CONFLICT, 1 calls) |
| 28854372_SDY1373 | bulk RNA-seq assay | OBI:0002571 | OBI:0003090 (MATCH_OBI_CONFLICT) | OBI:0000424 (MATCH_OBI_CONFLICT, 2 calls) | OBI:0003090 (MATCH_OBI_CONFLICT, 0 calls) |
