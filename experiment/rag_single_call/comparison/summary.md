# RAG single call (bare prompt + 701-term vocabulary) vs the assay agent, benchmark v5

## Scorer mode: default

| metric | agent | r1 | r2 | r3 | mean (min-max) |
|---|---|---|---|---|---|
| curated rows | 157 | 158 | 158 | 158 | 158.0 (158-158) |
| entries | 177 | 228 | 223 | 229 | 226.7 (223-229) |
| matched | 156 | 157 | 156 | 157 | 156.7 (156-157) |
| MISSED | 1 | 1 | 2 | 1 | 1.3 (1-2) |
| EXTRA | 4 | 34 | 32 | 35 | 33.7 (32-35) |
| exact (same OBI term as curator) | 140 | 118 | 121 | 122 | 120.3 (118-122) |
| OBI ok (same or parent/child) | 145 | 135 | 138 | 138 | 137.0 (135-138) |
| obi_exact_rate | 89.7% | 75.2% | 77.6% | 77.7% | 76.8% (75.2%-77.7%) |
| obi_recall | 92.4% | 85.4% | 87.3% | 87.3% | 86.7% (85.4%-87.3%) |
| wrong term (CONFLICT) | 5 | 16 | 10 | 13 | 13.0 (10-16) |
| no usable term (UNMAPPED) | 6 | 6 | 8 | 6 | 6.7 (6-8) |
| recall | 99.4% | 99.4% | 98.7% | 99.4% | 99.2% (98.7%-99.4%) |
| precision | 88.1% | 68.9% | 70.0% | 68.6% | 69.1% (68.6%-70.0%) |
| F1 | 93.4% | 81.3% | 81.9% | 81.1% | 81.5% (81.1%-81.9%) |
| term-only pairs | 6 | 8 | 8 | 8 | 8.0 (8-8) |
| calls | 512 | 31 | 31 | 31 | 31.0 (31-31) |
| ids: valid | — | 216 | 209 | 216 | 213.7 (209-216) |
| ids: outside_vocabulary | — | 0 | 0 | 0 | 0.0 (0-0) |
| ids: obsolete | — | 0 | 0 | 0 | 0.0 (0-0) |
| ids: nonexistent | — | 0 | 1 | 0 | 0.3 (0-1) |
| ids: none | — | 12 | 13 | 13 | 12.7 (12-13) |
| tokens: prompt_tokens | — | 1515821 | 1515821 | 1515821 | 1515821.0 (1515821-1515821) |
| tokens: completion_tokens | — | 18330 | 18301 | 18703 | 18444.7 (18301-18703) |
| tokens: cached_tokens | — | 925184 | 1498368 | 1498368 | 1307306.7 (925184-1498368) |

Curated rows with the same status in every run: 147 / 157.

## Scorer mode: strict

| metric | agent | r1 | r2 | r3 | mean (min-max) |
|---|---|---|---|---|---|
| curated rows | 158 | 158 | 158 | 158 | 158.0 (158-158) |
| entries | 177 | 228 | 223 | 229 | 226.7 (223-229) |
| matched | 156 | 157 | 156 | 157 | 156.7 (156-157) |
| MISSED | 2 | 1 | 2 | 1 | 1.3 (1-2) |
| EXTRA | 4 | 34 | 32 | 34 | 33.3 (32-34) |
| exact (same OBI term as curator) | 140 | 118 | 121 | 121 | 120.0 (118-121) |
| OBI ok (same or parent/child) | 145 | 135 | 138 | 138 | 137.0 (135-138) |
| obi_exact_rate | 89.7% | 75.2% | 77.6% | 77.1% | 76.6% (75.2%-77.6%) |
| obi_recall | 91.8% | 85.4% | 87.3% | 87.3% | 86.7% (85.4%-87.3%) |
| wrong term (CONFLICT) | 5 | 16 | 10 | 13 | 13.0 (10-16) |
| no usable term (UNMAPPED) | 6 | 6 | 8 | 6 | 6.7 (6-8) |
| recall | 98.7% | 99.4% | 98.7% | 99.4% | 99.2% (98.7%-99.4%) |
| precision | 88.1% | 68.9% | 70.0% | 68.6% | 69.1% (68.6%-70.0%) |
| F1 | 93.1% | 81.3% | 81.9% | 81.1% | 81.5% (81.1%-81.9%) |
| term-only pairs | 6 | 8 | 8 | 7 | 7.7 (7-8) |
| calls | 512 | 31 | 31 | 31 | 31.0 (31-31) |
| ids: valid | — | 216 | 209 | 216 | 213.7 (209-216) |
| ids: outside_vocabulary | — | 0 | 0 | 0 | 0.0 (0-0) |
| ids: obsolete | — | 0 | 0 | 0 | 0.0 (0-0) |
| ids: nonexistent | — | 0 | 1 | 0 | 0.3 (0-1) |
| ids: none | — | 12 | 13 | 13 | 12.7 (12-13) |
| tokens: prompt_tokens | — | 1515821 | 1515821 | 1515821 | 1515821.0 (1515821-1515821) |
| tokens: completion_tokens | — | 18330 | 18301 | 18703 | 18444.7 (18301-18703) |
| tokens: cached_tokens | — | 925184 | 1498368 | 1498368 | 1307306.7 (925184-1498368) |

Curated rows with the same status in every run: 149 / 158.

