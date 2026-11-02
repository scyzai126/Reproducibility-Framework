# Comparison arms vs the assay agent, benchmark v5 (31 papers)

Repeat runs are `mean (min–max)`. Calls are per run; the agent's 512 cover all five rounds.

## Scorer mode: default

| metric | agent | bare LLM ×3 (strict ids) | bare LLM ×3 (labels read) | dictionary, pruned/paper | dictionary, pruned/methods | dictionary, full/paper | agent, old same-term fold |
|---|---|---|---|---|---|---|---|
| curated rows | 157 | 157.7 (157–158) | 157.3 (157–158) | 156 | 157 | 156 | 153 |
| entries | 177 | 249.3 (244–252) | 249.3 (244–252) | 484 | 349 | 494 | 155 |
| matched | 156 | 153.7 (152–155) | 155.0 (153–156) | 141 | 124 | 141 | 151 |
| MISSED | 1 | 4.0 (3–5) | 2.3 (1–4) | 15 | 33 | 15 | 2 |
| EXTRA | 4 | 95.0 (91–97) | 69.3 (67–72) | 342 | 225 | 352 | 4 |
| exact (same OBI term as curator) | 140 | 13.7 (12–15) | 75.3 (73–77) | 80 | 64 | 80 | 136 |
| OBI ok (same or parent/child) | 145 | 24.3 (23–26) | 94.7 (93–96) | 108 | 91 | 108 | 141 |
| obi_exact_rate | 89.7% | 8.9% (7.7%–9.7%) | 48.6% (46.8%–50.3%) | 56.7% | 51.6% | 56.7% | 90.1% |
| obi_recall | 92.4% | 15.4% (14.6%–16.5%) | 60.2% (59.2%–61.1%) | 69.2% | 58.0% | 69.2% | 92.2% |
| wrong term (CONFLICT) | 5 | 116.0 (114–119) | 50.0 (45–54) | 31 | 31 | 31 | 4 |
| no usable term (UNMAPPED) | 6 | 13.3 (13–14) | 10.3 (9–12) | 2 | 2 | 2 | 6 |
| recall | 99.4% | 97.5% (96.8%–98.1%) | 98.5% (97.5%–99.4%) | 90.4% | 79.0% | 90.4% | 98.7% |
| precision | 88.1% | 61.6% (61.1%–62.3%) | 62.2% (61.9%–62.7%) | 29.1% | 35.5% | 28.5% | 97.4% |
| F1 | 93.4% | 75.5% (75.1%–75.8%) | 76.2% (76.1%–76.3%) | 44.1% | 49.0% | 43.4% | 98.1% |
| term-only pairs | 6 | 2.7 (2–4) | 5.7 (5–6) | 15 | 14 | 15 | 7 |
| calls | 512 | 31.0 (31–31) | 31.0 (31–31) | 0 | 0 | 0 | 512 |

Not yet run: RAG single call ×3, OntoGPT, NCBO Annotator, pruned/paper, NCBO Annotator, pruned/methods.

## Scorer mode: strict

| metric | agent | bare LLM ×3 (strict ids) | bare LLM ×3 (labels read) | dictionary, pruned/paper | dictionary, pruned/methods | dictionary, full/paper | agent, old same-term fold |
|---|---|---|---|---|---|---|---|
| curated rows | 158 | 158.0 (158–158) | 158.0 (158–158) | 158 | 158 | 158 | 158 |
| entries | 177 | 249.3 (244–252) | 249.3 (244–252) | 484 | 349 | 494 | 155 |
| matched | 156 | 153.7 (152–155) | 155.0 (153–156) | 141 | 124 | 141 | 151 |
| MISSED | 2 | 4.3 (3–6) | 3.0 (2–5) | 17 | 34 | 17 | 7 |
| EXTRA | 4 | 94.7 (91–97) | 69.3 (67–72) | 341 | 224 | 351 | 4 |
| exact (same OBI term as curator) | 140 | 13.3 (12–14) | 75.3 (73–77) | 79 | 63 | 79 | 136 |
| OBI ok (same or parent/child) | 145 | 23.0 (22–24) | 94.7 (93–96) | 108 | 91 | 108 | 141 |
| obi_exact_rate | 89.7% | 8.7% (7.7%–9.2%) | 48.6% (46.8%–50.3%) | 56.0% | 50.8% | 56.0% | 90.1% |
| obi_recall | 91.8% | 14.6% (13.9%–15.2%) | 59.9% (58.9%–60.8%) | 68.4% | 57.6% | 68.4% | 89.2% |
| wrong term (CONFLICT) | 5 | 117.0 (114–120) | 50.0 (45–54) | 31 | 31 | 31 | 4 |
| no usable term (UNMAPPED) | 6 | 13.7 (13–15) | 10.3 (9–12) | 2 | 2 | 2 | 6 |
| recall | 98.7% | 97.3% (96.2%–98.1%) | 98.1% (96.8%–98.7%) | 89.2% | 78.5% | 89.2% | 95.6% |
| precision | 88.1% | 61.6% (61.1%–62.3%) | 62.2% (61.9%–62.7%) | 29.1% | 35.5% | 28.5% | 97.4% |
| F1 | 93.1% | 75.5% (75.1%–75.6%) | 76.1% (76.1%–76.1%) | 43.9% | 48.9% | 43.3% | 96.5% |
| term-only pairs | 6 | 1.3 (1–2) | 5.7 (5–6) | 14 | 13 | 14 | 7 |
| calls | 512 | 31.0 (31–31) | 31.0 (31–31) | 0 | 0 | 0 | 512 |

Not yet run: RAG single call ×3, OntoGPT, NCBO Annotator, pruned/paper, NCBO Annotator, pruned/methods.

