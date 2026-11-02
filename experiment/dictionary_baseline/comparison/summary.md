# Dictionary baseline vs the assay agent, against benchmark v5

Agent: `data/31paper_assays/assay_result_v3`. Dictionary variants: `<vocab>_<scope>`.

## Scorer mode: default

| metric | agent | full_methods | full_paper | pruned_methods | pruned_paper |
|---|---|---|---|---|---|
| curated rows | 157 | 157 | 156 | 157 | 156 |
| entries | 177 | 354 | 494 | 349 | 484 |
| matched | 156 | 124 | 141 | 124 | 141 |
| MISSED | 1 | 33 | 15 | 33 | 15 |
| EXTRA | 4 | 230 | 352 | 225 | 342 |
| exact (same OBI term as curator) | 140 | 64 | 80 | 64 | 80 |
| OBI ok (same or parent/child) | 145 | 91 | 108 | 91 | 108 |
| obi_exact_rate | 89.7% | 51.6% | 56.7% | 51.6% | 56.7% |
| obi_recall | 92.4% | 58.0% | 69.2% | 58.0% | 69.2% |
| wrong term (CONFLICT) | 5 | 31 | 31 | 31 | 31 |
| no usable term (UNMAPPED) | 6 | 2 | 2 | 2 | 2 |
| recall | 99.4% | 79.0% | 90.4% | 79.0% | 90.4% |
| precision | 88.1% | 35.0% | 28.5% | 35.5% | 29.1% |
| F1 | 93.4% | 48.5% | 43.4% | 49.0% | 44.1% |
| term-only pairs | 6 | 14 | 15 | 14 | 15 |
| calls | 512 | 0 | 0 | 0 | 0 |

## Scorer mode: strict

| metric | agent | full_methods | full_paper | pruned_methods | pruned_paper |
|---|---|---|---|---|---|
| curated rows | 158 | 158 | 158 | 158 | 158 |
| entries | 177 | 354 | 494 | 349 | 484 |
| matched | 156 | 124 | 141 | 124 | 141 |
| MISSED | 2 | 34 | 17 | 34 | 17 |
| EXTRA | 4 | 229 | 351 | 224 | 341 |
| exact (same OBI term as curator) | 140 | 63 | 79 | 63 | 79 |
| OBI ok (same or parent/child) | 145 | 91 | 108 | 91 | 108 |
| obi_exact_rate | 89.7% | 50.8% | 56.0% | 50.8% | 56.0% |
| obi_recall | 91.8% | 57.6% | 68.4% | 57.6% | 68.4% |
| wrong term (CONFLICT) | 5 | 31 | 31 | 31 | 31 |
| no usable term (UNMAPPED) | 6 | 2 | 2 | 2 | 2 |
| recall | 98.7% | 78.5% | 89.2% | 78.5% | 89.2% |
| precision | 88.1% | 35.0% | 28.5% | 35.5% | 29.1% |
| F1 | 93.1% | 48.4% | 43.3% | 48.9% | 43.9% |
| term-only pairs | 6 | 13 | 14 | 13 | 14 |
| calls | 512 | 0 | 0 | 0 | 0 |

## Most frequent EXTRA terms: full_methods (default mode)

| OBI label | papers |
|---|---|
| protein assay | 22 |
| blood assay | 19 |
| immune response assay | 15 |
| monocyte assay | 15 |
| cytokine assay | 15 |
| lymphocyte assay | 11 |
| ChIP assay | 9 |
| neutrophil assay | 8 |
| binding assay | 7 |
| sequencing assay | 6 |
| respiratory assay | 5 |
| albumin assay | 4 |
| fluorogenic PCR assay | 4 |
| in live organism assay | 4 |
| growth factor assay | 4 |

## Most frequent EXTRA terms: full_paper (default mode)

| OBI label | papers |
|---|---|
| protein assay | 29 |
| immune response assay | 27 |
| blood assay | 21 |
| cytokine assay | 20 |
| monocyte assay | 19 |
| binding assay | 13 |
| lymphocyte assay | 13 |
| in live organism assay | 11 |
| neutrophil assay | 10 |
| ChIP assay | 9 |
| cell differentiation assay | 8 |
| growth factor assay | 8 |
| macrophage assay | 8 |
| respiratory assay | 7 |
| sequencing assay | 7 |

## Most frequent EXTRA terms: pruned_methods (default mode)

| OBI label | papers |
|---|---|
| protein assay | 22 |
| blood assay | 19 |
| immune response assay | 15 |
| monocyte assay | 15 |
| cytokine assay | 15 |
| lymphocyte assay | 11 |
| ChIP assay | 9 |
| neutrophil assay | 8 |
| binding assay | 7 |
| sequencing assay | 6 |
| respiratory assay | 5 |
| albumin assay | 4 |
| fluorogenic PCR assay | 4 |
| in live organism assay | 4 |
| growth factor assay | 4 |

## Most frequent EXTRA terms: pruned_paper (default mode)

| OBI label | papers |
|---|---|
| protein assay | 29 |
| immune response assay | 27 |
| blood assay | 21 |
| cytokine assay | 20 |
| monocyte assay | 19 |
| binding assay | 13 |
| lymphocyte assay | 13 |
| in live organism assay | 11 |
| neutrophil assay | 10 |
| ChIP assay | 9 |
| cell differentiation assay | 8 |
| growth factor assay | 8 |
| macrophage assay | 8 |
| respiratory assay | 7 |
| sequencing assay | 7 |

