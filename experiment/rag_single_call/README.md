# RAG single call: bare prompt + the 701-term OBI vocabulary

*2026-11-02. `run_rag.py`, `prompt.txt`. Status: **run 3 times on all 31 papers** (93 calls);
raw replies in `runs/r<k>/<registry>/raw.json`, scores in `comparison/summary.md`.*

One gpt-5.4 call per paper. The prompt puts the agent's 701 pruned OBI assay terms first,
rendered as the agent's round-4 picker renders a candidate (id | label | synonyms | definition |
descendants) so the ~40.6k-token prefix caches, then the bare prompt's instructions
(`experiment/llm_baseline/prompt.txt`), now asking for an id from the list or `null`. Same input
as the agent's round 1 (`arms.paper_input`), default temperature, three runs. No retrieval, no
vote, no verification, no fold. It is the obvious repair of the bare call's term problem
(`experiment/llm_baseline/llm_baseline_vs_agent.md`): hand the model the vocabulary.

```
./.venv/bin/python experiment/rag_single_call/run_rag.py run --runs 3 --dry-run   # count, free
./.venv/bin/python experiment/rag_single_call/run_rag.py run --runs 3             # 93 calls, resumable
./.venv/bin/python experiment/rag_single_call/run_rag.py score                    # both scorer modes, free
./.venv/bin/python experiment/rag_single_call/run_rag.py report                   # comparison/summary.md
```

An id is kept when it is in the vocabulary (`id_status: valid`); another live OBI id is
`outside_vocabulary`, an invented one `nonexistent`, and both score as unmapped. Over the three
runs the model gave 641 valid ids, 1 nonexistent, 38 `null`, and none outside the list.

## Result (strict scorer, 158 curated rows; mean of 3 runs, range in `comparison/summary.md`)

| | agent | RAG single call |
|---|---|---|
| entries | 177 | 227 (223–229) |
| matched | 156 | 157 (156–157) |
| EXTRA | 4 | 33 (32–34) |
| exact OBI term | 140 | 120 (118–121) |
| OBI ok (same or parent/child) | 145 | 137 (135–138) |
| wrong term (CONFLICT) | 5 | 13 (10–16) |
| recall / precision / F1 | 98.7% / 88.1% / 0.931 | 99.2% / 69.1% / 0.815 |
| rows with the same status in all 3 runs | — | 149 of 158 |
| calls per run | 512 | 31 |

Cost per run: 1,515,821 prompt tokens, of which 925,184 were cached in run 1 and 1,498,368 in
runs 2 and 3 (86% over the three), plus ~18.4k completion tokens.

**What the vocabulary buys.** Exact terms go from 75 (bare call, its labels read for it) to 120,
extras from 69 to 33, and no id is invented. That is most of the gap to the agent closed by one
prompt change.

**What is left (20 exact, 19 points of precision).** The misses are the ones the round-4 study
found for a 701-line list (`docs/obi_fulllist_llm_vs_embedding.md`): the model goes to a
familiar neighbour and stops. Over three runs: `flow cytometry assay` → `immuno staining assay`
(4), the real-time RT-PCR term → `transcription profiling by RT-PCR assay` or the plain
real-time PCR term (9), `serum neutralization of viral infectivity assay` → `pathogen
neutralization assay` (3), `cytometric bead array assay` → ELISA (3), `bulk RNA-seq assay` →
`polyA-selected RNA sequencing assay` (3), `microscopy assay` → `parasite detection assay` (3).
The extras are a parent term listed beside the child it also gave (`polymerase chain reaction
assay`, `reverse transcription PCR assay`: 15), `null` entries for things it could not name
(14), and clinical-chemistry panels the curators do not file (platelet count, hematocrit, AST,
ALT: 12). Nine curated rows change status between runs. The agent's remaining edge is what the
single call does not have: 20 retrieved candidates with definitions in front of one pick, the
verifier, and the vote.

Tests: `tests/test_run_rag.py` (prompt shape and the id statuses; no call).
