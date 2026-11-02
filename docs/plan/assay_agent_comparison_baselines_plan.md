# Plan: comparison arms for the assay-extraction agent (paper write-up)

*2026-11-02. Status: approved scope, not started.*

## Context

The assay pipeline (`scripts/run_assay_pipeline.py`, rounds 1-5) is done and scored on the 31-paper /
157-row benchmark v5 by `scripts/compare_assay_benchmark_v2.py`: recall 156/157, exact OBI 140,
OBI recall 92.4%, precision 0.881, F1 0.934, 4 EXTRA / 1 MISSED, 512 LLM calls. For the paper we
need comparison arms that show what the agent adds over simpler and existing methods. Today the only
baseline is one bare gpt-5.4 call; a reviewer will ask for a non-LLM baseline, a published tool, and
an honest scorer.

## Scope chosen by the user

| id | arm | cost | status |
|---|---|---|---|
| S | fix the scorer, then rescore every arm with it | free | **first** |
| A1 | NCBO BioPortal Annotator (OBI) | free, needs a BioPortal API key | new |
| B1 | lexical dictionary match over OBI labels + synonyms | free | new |
| C3 | agent without round-5 fold (scoring only) | free | new |
| B3 | RAG single call: bare prompt + the 701-term vocabulary | ~31 calls × 3 runs | new, paid |
| A2 | OntoGPT / SPIRES with the same model, grounded to OBI | ~31 calls | new, paid |
| — | bare LLM ×3 | done | `experiment/llm_baseline/llm_baseline_vs_agent.md` |
| — | round-4 ablations (full list, vocab, top-K, re-pick) | done | `docs/obi_fulllist_llm_vs_embedding.md`, `docs/obi_vocab_full_vs_pruned_v3.md`, `experiment/obi_topk/README.md` |

Declined for now: embedding top-1 without pick, text2term, 1-vs-3 extraction, no-verify/correct,
model swap, second curator. They stay listed at the end as options.

## Conventions every arm follows

- Lives under `experiment/<arm>/` with `README.md`, `run_<arm>.py`, `prompt.txt` if any, `runs/`,
  `comparison/`, `tests/` — the layout of `experiment/llm_baseline/`.
- Same input as the agent's round 1: `paper_input()` in
  `experiment/llm_baseline/run_llm_baseline.py` (XML parse with `[S<n>]` markers stripped; a `_pdf`
  registry uses the PDF's `haystack` text). Reuse it, do not re-implement.
- Writes the two files the comparator reads, `assays_benchmark.json` (keyed by OBI label, ` (2)` on a
  repeat) and `assays_OBI.json`, via `to_registry()` from the same script, so every arm is scored by
  identical code. `evidence.sentence_ids` and `source` are derived from the quote by code there.
- Scored with `scripts/compare_assay_benchmark_v2.py --registry-dir experiment/<arm>/runs/r<k>`,
  in both scorer modes (below). The summary table reuses `arm_column()` / `summary_table()` from
  `run_llm_baseline.py`; move those two into a small shared module `experiment/common/arms.py` so
  five arms do not copy them.
- Nothing is written under `data/`; no file in `experiment/` is a way to run a paper (CLAUDE.md).
- Paid arms print a `--dry-run` call count and wait for a go-ahead.

## S. Scorer: add a strict mode, keep the default (do first)

Two known leniencies in `compare_assay_benchmark_v2.py` (Tier 3 of the 2026-10-19 review):

1. `compare_paper` lines 404-414: a curated row left unpaired folds onto a paired row on the same OBI
   id, so it is never MISSED. This hides agent over-folding and shrinks the denominator (157 vs 158).
2. `pair_score` / `match_tier`: a pair on tier `obi_exact` or `obi_ancestry` needs no name or quote
   signal, so a curator row can pair with the wrong agent entry on the same term.

Change: add `--strict` to the comparator.
- strict: no leftover fold (leftovers are MISSED; `benchmark_total` is the raw row count); a term-only
  pair with zero `pair_signals` is refused unless it is the only candidate on both sides, and the
  count of such pairs is reported as `term_only_pairs`.
- default: unchanged, so every historical number stays reproducible.
- `overall_totals` gains the new counters; the HTML gets a mode banner.
- Tests in `apps/api/tests/test_compare_assay_benchmark_v2.py` (new): one synthetic paper per
  leniency showing the two modes differ exactly there.
- Rescore `data/31paper_assays/assay_result_v3/` in both modes; also confirm the scored v3 registries
  carry no hand-set `manual_review` mapping (the v1 SDY1293 one must not be in v3).
- Write `docs/assay_scorer_strict_mode.md` with the agent's default-vs-strict numbers.

Every arm below is reported in both modes.

## A1. NCBO BioPortal Annotator

- `experiment/ncbo_annotator/run_ncbo.py`. POST each paper's text to
  `https://data.bioontology.org/annotator` with `ontologies=OBI`, `longest_only=true`,
  `exclude_synonyms=false`, `apikey=$BIOPORTAL_API_KEY` (free account; add the key to `.env`,
  read via `settings`). Cache every response under `runs/raw/<registry>.json` so reruns are free.
- Adapter: keep annotations whose class PURL maps to an id in the full assay subtree (the 1794-term
  index `data/OBI/obi_assay_full_index.json`); report the 701-pruned restriction as a second column.
  One entry per distinct term; `name_in_paper` = the distinct matched surface strings; quote = the
  sentence of the first match (from the numbered `haystack`).
- Variants, both free: whole-paper text (primary, same input as every arm) and Methods-only.
- Expect high EXTRA and misses on paper wordings (Luminex, PRNT, CBA). That is the point.

## B1. Lexical dictionary baseline

- `experiment/dictionary_baseline/run_dictionary.py`. Vocabulary from
  `data/OBI/obi_assay_pruned_index.json` (701; fields `id, label, synonyms, is_a, definition`) and
  the full 1794 index. Normalise with `normalize` from `scripts/compare_assay_benchmark.py`; match
  label and synonyms with word boundaries, longest match first, case-insensitive, over the same
  paper text. Drop single generic tokens (`assay`, `FM`-style ≤2-char synonyms) by a short
  stoplist recorded in the README.
- Same adapter shape as A1 (one entry per term, surface strings, first-match sentence).
- Variants: pruned / full × whole-paper / Methods-only. All free.

## C3. Agent without round-5 fold (scoring only)

- `experiment/no_fold/build_unfolded.py`. For each v3 registry, rebuild the pre-fold registry:
  entries from `assays_corrected.json` (round-3 output, keyed by the extractor's wording), each
  given the OBI mapping of its canonical key through `assays_merges.json["key_map"]` (31 of 32 v3
  dirs have it; the one without uses `_recover_key_map` in `apps/api/app/agent/assay_service.py:465`).
  Write `assays_benchmark.json` / `assays_OBI.json` keyed by the original wording.
- Score both modes. This is the ablation that shows what round 5 buys in precision and costs in
  exact matches (`docs/assay_entry_grain.md` has the old-rule numbers for context).

## B3. RAG single call (paid, ~31 calls per run, 3 runs)

- `experiment/rag_single_call/`, a copy of the `llm_baseline` runner with one change: the prompt
  puts the 701 pruned terms first, rendered as `_candidate_line` in
  `apps/api/app/agent/assay_obi_mapper.py` renders a candidate (id | label | synonyms), so the
  prefix caches, then the bare prompt's instructions, and asks for an id **from the list** or `none`.
- Strict scoring only (an id outside the list is unmapped); no relabel step needed.
- Default temperature, 3 runs, `--dry-run` first; report calls and cached tokens.

## A2. OntoGPT / SPIRES (paid, ~31 calls)

- `experiment/ontogpt/`. `pip install ontogpt` into the repo `.venv` (pin the version in the
  README). Template `assay_paper.yaml` (LinkML): class `Paper` with multivalued `assays` of
  `Assay`, a `NamedEntity` annotated `annotators: sqlite:obo:obi`. Run
  `ontogpt extract -t assay_paper.yaml -m <gpt-5.4 id litellm accepts> -i <text>` per paper, with
  `OPENAI_API_KEY` from `.env`. Save the YAML replies under `runs/raw/`.
- Adapter: each `named_entities` item with an `OBI:`/`CHMO:` id becomes a mapped entry; an `AUTO:`
  id becomes an unmapped entry keyed by its label. Quote = first sentence containing the label.
- Risks to check at implementation: whether the installed OntoGPT accepts the gpt-5.4 model name,
  and whether it chunks a long paper into several calls (then the call count is more than 31; the
  dry-run estimate is the number of chunks). One run; add a second only if the first shows it is
  needed for a stability column.

## Reporting

- `experiment/common/compare_arms.py`: one table over any set of scored registry dirs, columns
  matched / MISSED / EXTRA / exact OBI / OBI recall (same or parent-child) / CONFLICT / UNMAPPED /
  stability across runs / LLM calls + tokens, in default and strict modes.
- Write-up `docs/assay_agent_vs_baselines.md`: main table (agent, bare LLM, NCBO, dictionary, RAG
  single call, OntoGPT), ablation table (no-fold plus the round-4 ablations already done), and the
  per-arm "where it loses" examples in the style of `llm_baseline_vs_agent.md`.

## Order of work

1. S scorer strict mode + tests + rescore v3 (free).
2. B1 dictionary, C3 no-fold (free, no external dependency).
3. A1 NCBO once the API key is in `.env` (free).
4. B3 RAG single call: dry-run, go-ahead, run ×3.
5. A2 OntoGPT: install, dry-run estimate, go-ahead, run.
6. `compare_arms.py` table + `docs/assay_agent_vs_baselines.md`.

Each step is its own commit on a feature branch (`feature/assay-baselines`), with the arm's
README and the `pytest` run from `apps/api` with the repo-root `.venv`.

## Verification

- `apps/api`: `../../.venv/bin/python -m pytest` passes, including the new comparator tests and one
  adapter test per arm (`experiment/<arm>/tests/`, on a stored raw reply, no network).
- Each free arm scores all 31 papers end to end in both modes with no skipped registry.
- Paid arms: dry-run count printed and acknowledged before the run; raw replies on disk so any
  wrong entry is diagnosed without a rerun.
- The final table reproduces the agent's stored numbers in default mode (156 matched, 140 exact,
  4 EXTRA) before any baseline column is read.

## Options not taken (for later)

Embedding top-1 without the LLM pick (free, candidate lists are in `assays_raw.json["obi"]`);
text2term mapping of `name_in_paper` strings; 1-vs-3 extraction; no verify/correct
(`assay_report` flags at `assay_service.py:818-880`); cheaper OpenAI model via `OPENAI_MODEL`;
a second curator on ~10 papers for an inter-curator ceiling; ImmPort `experiment` records as a
"what the repository has" reference via `scripts/build_immport_coverage.py`.
