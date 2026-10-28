# Would a longer candidate list (TOP_K 20 → 30 / 40 / 60) help the OBI picker?

> **2026-10-28 — rerun on `assay_result_v3`.** `run_topk.py` now reads the v3 registries and
> compares against the K=20 arm in `experiment/obi_vocab_v3/runs/pruned` (141 exact); the full
> vocabulary arm is gone. Stage 1 (`recall/recall_at_k.md`, 168 entries): the curated term is on
> the list for 163 at K=20, 164 at K=30, 165 at K=40 and 60. The one K=30 gain is SDY1260's
> `antibody detection by cytometric bead array assay` (a parent/child match at K=20); the K=40
> gain, SDY1328's complete blood count, the full-list fallback already maps. Ceiling: +1 exact,
> within run-to-run noise. Stage 2 not run; TOP_K stays 20. The sections below are the
> original 2026-10-21 run on the older registries.


*Experiment folder. No production file is changed; `TOP_K` is only wrapped in memory for the
duration of a stage-2 run. Nothing under `data/` is written.*

## Question

The mapper shows the picker the top 20 retrieved terms (plus exact-hit pins and OBI
neighbours). The 31-paper vocabulary comparison (`experiment/obi_vocab_31papers/`) found two
ways the full 1794-term pool loses to the pruned 701: decoys push the curator's term off the
20-slot list, or the picker takes a compositional term although the family term is on the list.
Widening K can only help the first. This folder measures how much.

## Stage 1: retrieval recall@K, replayed offline (done)

The mapper's two retrieval queries per entry (paper wording + aliases; standard technique name)
were embedded once and cached (`query_embeddings.json`, 193 distinct strings, 193 embedding
calls, no chat). `run_topk.py recall` then replays the mapper's own `_top_k_candidates` →
`_merge_candidates` → `_with_pinned` → `_with_neighbours` at each K, with the paper-wording
reserve scaled with K (14 of 20 → 21 of 30 → 28 of 40), and records where the curated term
lands. 145 of the 157 entries have a curated OBI term (from the K=20 pairing in
`experiment/obi_vocab_31papers/comparison/pruned.json`).

### Pruned vocabulary (701 terms)

| K | curated term on the list | recall | mean list length | compositional / outside-701 per list |
|---|---|---|---|---|
| 10 | 140 | 96.6% | 12.8 | 0.3 / 0 |
| **20 (today)** | **142** | **97.9%** | 21.6 | 0.3 / 0 |
| 30 | 143 | 98.6% | 30.9 | 0.3 / 0 |
| 40 | 144 | 99.3% | 40.1 | 0.3 / 0 |
| 60 | 144 | 99.3% | 58.8 | 0.3 / 0 |

The three entries whose curated term is off the K=20 list:

| paper | entry | curated | K=30 | K=40 | K=60 |
|---|---|---|---|---|---|
| SDY1655 | 71-plex Luminex panel | `OBI:0000920` cytometric bead array | rank 13 | 17 | 25 |
| SDY1328 | complete blood count | `OBI:0000630` hematology assay | — | rank 33 | 33 |
| SDY1328 | RBM multiplex "ELISA" panel | `OBI:0000920` cytometric bead array | — | — | — |

(SDY1655's term appears at rank 13 at K=30 but not at K=20 because it comes from the technique
query's pool, which only gets room once the paper-wording reserve stops filling the list.)

**Ceiling gain for the pruned pool: 1 entry at K=30, 2 at K=40, nothing more at K=60.** Both
recoverable entries were wrong at K=20 for exactly this reason (the picker chose the child
`antigen detection by CBA` and the broad `blood assay` because the curator's term was not
shown), so a wider list could turn them into matches, if the picker takes them. The list has no
decoy load to speak of at any K: the compositional and domain terms are not in this pool.

### Full vocabulary (1794 terms)

| K | curated term on the list | recall | mean list length | compositional / outside-701 per list |
|---|---|---|---|---|
| 10 | 137 | 94.5% | 16.8 | 7.2 / 7.8 |
| 20 | 139 | 95.9% | 25.8 | 10.0 / 11.2 |
| 30 | 139 | 95.9% | 35.0 | 13.0 / 15.1 |
| 40 | 140 | 96.6% | 44.1 | 15.9 / 19.2 |
| 60 | 141 | 97.2% | 63.1 | 22.9 / 28.8 |

Of the six curated terms off the K=20 list, K=40 brings back one (SDY1293 microscopy, rank 20)
and K=60 one more (SDY1373, rank 30); SDY1669's LPS term, rank 18 on the pruned list, is not
within the top 100 of either query on the full pool. Every extra slot is bought with a decoy:
at K=40 the list averages 16 compositional and 19 outside-701 terms out of 44. The full pool
stays behind the pruned pool at every K, including K=60 vs K=10.

### What stage 1 settles

- **Widening is pointless for the full vocabulary.** Its retrieval ceiling at K=60 (141) is
  below the pruned pool's at K=10 (140 ≈) and far below pruned K=20 (142), while the decoy load
  that caused 4 of its 7 wrong picks more than doubles.
- **For the pruned vocabulary the ceiling moves by at most 2 entries (K=40).** Whether the
  picker converts them, and whether a 40-line list costs anything elsewhere (the picker's
  variance between adjacent siblings is already the largest source of change between runs),
  is the stage-2 question. The 2026-10-19 decision to set TOP_K=20 was made on the same kind
  of measurement (87% at 10 → 91% at 20 on 150 rows); this replay says 20 → 40 buys 1.4
  points of retrieval ceiling.

## Stage 2: the picker at wider K (gated, paid)

`run_topk.py pick --vocab pruned --k 40` maps all 31 registries with the list widened to 40
(paper-wording reserve 28), query embeddings served from the cache, ≈150 chat calls, then
`pick-score` scores it with the v2 comparator and diffs it against the K=20 run in
`experiment/obi_vocab_31papers/runs/pruned/`. Not run yet.

## Layout

```
run_topk.py                 embed-queries | recall | pick | pick-score
tests/                      5 tests: ./.venv/bin/pytest experiment/obi_topk/tests
query_embeddings.json       193 cached query vectors (7.8 MB)
recall/recall_at_k.{json,md}   stage 1 output; the JSON has per-entry rank at every K
picks/                      stage 2 output (when run)
```
