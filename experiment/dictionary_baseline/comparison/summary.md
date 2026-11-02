# Dictionary baseline vs the assay agent, against benchmark v5

Agent: `data/31paper_assays/assay_result_v3`. Dictionary variants: `<vocab>_<scope>`.

## Scorer mode: default

| metric | agent | full_methods | full_paper | pruned_methods | pruned_paper |
|---|---|---|---|---|---|
| curated rows | 157 | 157 | 156 | 157 | 156 |
| entries | 177 | 290 | 418 | 286 | 410 |
| matched | 156 | 113 | 134 | 113 | 134 |
| MISSED | 1 | 44 | 22 | 44 | 22 |
| EXTRA | 4 | 177 | 283 | 173 | 275 |
| exact (same OBI term as curator) | 140 | 52 | 69 | 52 | 69 |
| OBI ok (same or parent/child) | 145 | 75 | 95 | 75 | 95 |
| obi_exact_rate | 89.7% | 46.0% | 51.5% | 46.0% | 51.5% |
| obi_recall | 92.4% | 47.8% | 60.9% | 47.8% | 60.9% |
| wrong term (CONFLICT) | 5 | 36 | 37 | 36 | 37 |
| no usable term (UNMAPPED) | 6 | 2 | 2 | 2 | 2 |
| recall | 99.4% | 72.0% | 85.9% | 72.0% | 85.9% |
| precision | 88.1% | 39.0% | 32.1% | 39.5% | 32.7% |
| F1 | 93.4% | 50.6% | 46.7% | 51.0% | 47.3% |
| term-only pairs | 6 | 10 | 12 | 10 | 12 |
| calls | 512 | 0 | 0 | 0 | 0 |

## Scorer mode: strict

| metric | agent | full_methods | full_paper | pruned_methods | pruned_paper |
|---|---|---|---|---|---|
| curated rows | 158 | 158 | 158 | 158 | 158 |
| entries | 177 | 290 | 418 | 286 | 410 |
| matched | 156 | 114 | 135 | 114 | 135 |
| MISSED | 2 | 44 | 23 | 44 | 23 |
| EXTRA | 4 | 176 | 282 | 172 | 274 |
| exact (same OBI term as curator) | 140 | 52 | 69 | 52 | 69 |
| OBI ok (same or parent/child) | 145 | 75 | 95 | 75 | 95 |
| obi_exact_rate | 89.7% | 45.6% | 51.1% | 45.6% | 51.1% |
| obi_recall | 91.8% | 47.5% | 60.1% | 47.5% | 60.1% |
| wrong term (CONFLICT) | 5 | 37 | 38 | 37 | 38 |
| no usable term (UNMAPPED) | 6 | 2 | 2 | 2 | 2 |
| recall | 98.7% | 72.2% | 85.4% | 72.2% | 85.4% |
| precision | 88.1% | 39.3% | 32.3% | 39.9% | 32.9% |
| F1 | 93.1% | 50.9% | 46.9% | 51.4% | 47.5% |
| term-only pairs | 6 | 10 | 12 | 10 | 12 |
| calls | 512 | 0 | 0 | 0 | 0 |

## Most frequent EXTRA terms: full_methods (default mode)

| OBI label | papers |
|---|---|
| blood assay | 18 |
| protein assay | 18 |
| immune response assay | 9 |
| cytokine assay | 9 |
| monocyte assay | 8 |
| ChIP assay | 8 |
| binding assay | 7 |
| lymphocyte assay | 6 |
| sequencing assay | 6 |
| respiratory assay | 5 |
| albumin assay | 4 |
| fluorogenic PCR assay | 4 |
| neutrophil assay | 4 |
| cell differentiation assay | 3 |
| cell death assay | 3 |

## Most frequent EXTRA terms: full_paper (default mode)

| OBI label | papers |
|---|---|
| protein assay | 27 |
| immune response assay | 22 |
| blood assay | 20 |
| cytokine assay | 14 |
| binding assay | 13 |
| monocyte assay | 11 |
| cell differentiation assay | 8 |
| ChIP assay | 8 |
| growth factor assay | 7 |
| respiratory assay | 7 |
| lymphocyte assay | 7 |
| sequencing assay | 7 |
| neutrophil assay | 6 |
| cell death assay | 6 |
| macrophage assay | 5 |

## Most frequent EXTRA terms: pruned_methods (default mode)

| OBI label | papers |
|---|---|
| blood assay | 18 |
| protein assay | 18 |
| immune response assay | 9 |
| cytokine assay | 9 |
| monocyte assay | 8 |
| ChIP assay | 8 |
| binding assay | 7 |
| lymphocyte assay | 6 |
| sequencing assay | 6 |
| respiratory assay | 5 |
| albumin assay | 4 |
| fluorogenic PCR assay | 4 |
| neutrophil assay | 4 |
| cell differentiation assay | 3 |
| cell death assay | 3 |

## Most frequent EXTRA terms: pruned_paper (default mode)

| OBI label | papers |
|---|---|
| protein assay | 27 |
| immune response assay | 22 |
| blood assay | 20 |
| cytokine assay | 14 |
| binding assay | 13 |
| monocyte assay | 11 |
| cell differentiation assay | 8 |
| ChIP assay | 8 |
| growth factor assay | 7 |
| respiratory assay | 7 |
| lymphocyte assay | 7 |
| sequencing assay | 7 |
| neutrophil assay | 6 |
| cell death assay | 6 |
| macrophage assay | 5 |

