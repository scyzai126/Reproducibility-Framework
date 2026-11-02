# Round-5 fold ablation: delivered v3 vs unfolded vs the old same-term fold

`agent` is the delivered v3 corpus (round 5's identity fold); `unfolded` is round 3's registry with round 4's terms; `term_fold` folds every entry on a shared OBI term.

## Scorer mode: default

| metric | agent | term_fold | unfolded |
|---|---|---|---|
| curated rows | 157 | 153 | 157 |
| entries | 177 | 155 | 177 |
| matched | 156 | 151 | 156 |
| MISSED | 1 | 2 | 1 |
| EXTRA | 4 | 4 | 4 |
| exact (same OBI term as curator) | 140 | 136 | 140 |
| OBI ok (same or parent/child) | 145 | 141 | 145 |
| obi_exact_rate | 89.7% | 90.1% | 89.7% |
| obi_recall | 92.4% | 92.2% | 92.4% |
| wrong term (CONFLICT) | 5 | 4 | 5 |
| no usable term (UNMAPPED) | 6 | 6 | 6 |
| recall | 99.4% | 98.7% | 99.4% |
| precision | 88.1% | 97.4% | 88.1% |
| F1 | 93.4% | 98.1% | 93.4% |
| term-only pairs | 6 | 7 | 6 |
| calls | 512 | 0 | 0 |

## Scorer mode: strict

| metric | agent | term_fold | unfolded |
|---|---|---|---|
| curated rows | 158 | 158 | 158 |
| entries | 177 | 155 | 177 |
| matched | 156 | 151 | 156 |
| MISSED | 2 | 7 | 2 |
| EXTRA | 4 | 4 | 4 |
| exact (same OBI term as curator) | 140 | 136 | 140 |
| OBI ok (same or parent/child) | 145 | 141 | 145 |
| obi_exact_rate | 89.7% | 90.1% | 89.7% |
| obi_recall | 91.8% | 89.2% | 91.8% |
| wrong term (CONFLICT) | 5 | 4 | 5 |
| no usable term (UNMAPPED) | 6 | 6 | 6 |
| recall | 98.7% | 95.6% | 98.7% |
| precision | 88.1% | 97.4% | 88.1% |
| F1 | 93.1% | 96.5% | 93.1% |
| term-only pairs | 6 | 7 | 6 |
| calls | 512 | 0 | 0 |

