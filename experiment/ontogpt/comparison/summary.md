# OntoGPT (SPIRES, grounded to OBI by OAK) vs the assay agent, benchmark v5 — full vocabulary

## Scorer mode: default

| metric | agent | r1 |
|---|---|---|
| curated rows | 157 | 158 |
| entries | 177 | 263 |
| matched | 156 | 155 |
| MISSED | 1 | 3 |
| EXTRA | 4 | 107 |
| exact (same OBI term as curator) | 140 | 22 |
| OBI ok (same or parent/child) | 145 | 23 |
| obi_exact_rate | 89.7% | 14.2% |
| obi_recall | 92.4% | 14.6% |
| wrong term (CONFLICT) | 5 | 3 |
| no usable term (UNMAPPED) | 6 | 129 |
| recall | 99.4% | 98.1% |
| precision | 88.1% | 58.9% |
| F1 | 93.4% | 73.6% |
| term-only pairs | 6 | 0 |
| calls | 512 | 31 |
| ids: valid | — | 28 |
| ids: outside_vocabulary | — | 10 |
| ids: none | — | 225 |
| tokens: prompt_tokens | — | 337777 |
| tokens: completion_tokens | — | 1977 |
| tokens: cached_tokens | — | 0 |

## Scorer mode: strict

| metric | agent | r1 |
|---|---|---|
| curated rows | 158 | 158 |
| entries | 177 | 263 |
| matched | 156 | 155 |
| MISSED | 2 | 3 |
| EXTRA | 4 | 107 |
| exact (same OBI term as curator) | 140 | 22 |
| OBI ok (same or parent/child) | 145 | 23 |
| obi_exact_rate | 89.7% | 14.2% |
| obi_recall | 91.8% | 14.6% |
| wrong term (CONFLICT) | 5 | 3 |
| no usable term (UNMAPPED) | 6 | 129 |
| recall | 98.7% | 98.1% |
| precision | 88.1% | 58.9% |
| F1 | 93.1% | 73.6% |
| term-only pairs | 6 | 0 |
| calls | 512 | 31 |
| ids: valid | — | 28 |
| ids: outside_vocabulary | — | 10 |
| ids: none | — | 225 |
| tokens: prompt_tokens | — | 337777 |
| tokens: completion_tokens | — | 1977 |
| tokens: cached_tokens | — | 0 |

