# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# ── Backend ──────────────────────────────────────────
# Install dependencies
pip install -r requirements.txt

# Run the FastAPI server (http://localhost:8000)
uvicorn app.main:app --reload

# Run all tests
pytest

# Run a single test file
pytest tests/test_query_builder.py

# ── Frontend ─────────────────────────────────────────
# Install dependencies (first time only)
cd frontend && npm install

# Start the Next.js dev server (http://localhost:3000)
cd frontend && npm run dev

# NOTE: never run `npm run build` during development.
# HMR handles live reload automatically while `npm run dev` is running.
# Only delete .next and restart if you see a "Cannot find module" webpack error.
```

## Environment

Copy `.env.example` to `.env` and fill in:
- `OPENAI_API_KEY` — OpenAI key (model defaults to `gpt-5.4`)
- `MYSQL_URL` — async MySQL URL, e.g. `mysql+aiomysql://user:pass@localhost:3306/claim_reproduce`

Tests stub these out automatically via `tests/conftest.py`.

## Architecture

This is an AI agent that takes a **signature JSON** file (ImmPort study format) and returns which database subjects match the paper's participant groups. It exposes a **ChatGPT-style web UI** and a REST API.

### Full stack

```
apps/web/          Next.js 15 + React 19 + Tailwind CSS (port 3000)
apps/api/app/      FastAPI backend (port 8000)
```

The frontend proxies `/backend/*` → `http://localhost:8000/*` via `next.config.ts` rewrites, so both servers must be running.

### Frontend components (`apps/web/src/`)

```
app/
  page.tsx           Main chat page — session state, message list, upload handler
  layout.tsx         Root layout
  globals.css        Tailwind directives
components/
  Sidebar.tsx        Left sidebar: "New analysis" button + session history (localStorage)
  ChatInput.tsx      Bottom input bar — file upload (📎) OR paste/type raw JSON
  ChatMessage.tsx    User bubble + assistant bubble with JSON result viewer
lib/
  api.ts             runAgentUpload(file) → POST /backend/agent/run-upload
  types.ts           ChatMessage, ChatSession, AgentResponse, SubjectResult
```

**Two ways to submit input from the UI:**
1. Click the 📎 paperclip → pick a `.json` file → press Enter or ↑
2. Paste or type JSON directly in the chatbox → press Enter or ↑ (wrapped into a virtual `input.json` and sent to the same endpoint)

Sessions (up to 20) persist in browser `localStorage` under key `chat_sessions`.

### Backend pipeline (`apps/api/app/agent/orchestrator.py:run_agent`)

```
POST /agent/run-upload  (multipart file upload — used by the UI)
POST /agent/run         (JSON body with file_path string — for direct API calls)

  → file_reader          read uploaded temp file content
  → signature_parser     extract participant groups + study_accession
  → description_analyzer (OpenAI) extract cohort/assay_method/tissue_type/condition per group
  → study_sync           ensure study data is present in local DB (downloads from ImmPort if needed)
  → query_builder        resolve terms → DB accessions, build parameterized SQL
  → execute queries      against ImmPort MySQL
  → return JSON          { study_accession, subject_results[] } + write logs/agent_run.log
```

### Key design: two-step accession resolution (`query_builder.py`)

When a group references a cohort name or assay method, `_resolve_accession()` does:
1. **SQL LIKE** match on `name`/`description` columns — returns immediately if exactly 1 hit
2. **LLM fallback** — fetches all candidates for the study, asks OpenAI to pick the best match

This applies to both arm resolution (`arm_or_cohort` table → `arm_accession`) and experiment resolution (`experiment` table → `experiment_accession`).

### SQL query shape (`query_builder._build_query`)

All queries join `expsample → expsample_2_biosample → biosample` with an optional `LEFT JOIN immune_exposure`. Active filters are driven by `OPTIONAL_FILTERS` list (experiment, study, tissue_type, condition). Arm membership is handled separately via a subquery on `arm_2_subject`.

### LLM prompt

The description analyzer system prompt lives in `apps/api/app/prompts/description_analyzer.txt` (not inline). Modify it there to change how groups are parsed from paper text.

## Repository Guidelines for Claude Code

### Scope & File Modifications
- **Minimize Scope:** Modify *only* the specific files explicitly requested or required to complete the task.
- **Do Not Touch:** Do not modify configuration files, build scripts, or unrelated module files unless specifically asked.
- **Refactoring Boundary:** Do not perform general refactoring, code formatting, or style cleanup outside the target lines/files of the current issue.
- **Diff Check:** Before completing a prompt, list all changed files and confirm no extraneous edits were introduced.

### Testing
- **New Feature → New Test:** When adding a new module or feature under `apps/api/app/agent/`, add a corresponding `apps/api/tests/test_*.py` covering its core logic.
- **Run Before Completing:** Before finishing a prompt that touched backend code, run `pytest` (from `apps/api/`) and confirm the suite passes. If a failure is pre-existing and unrelated to the current change, call it out explicitly rather than silently leaving it red.
- **Keep Tests in Sync:** If a refactor renames or removes a module, update or remove the tests that import it in the same change — don't leave a test importing a deleted module.

### Paper / LLM Runs (cost control)
- **No unprompted paper runs:** When a piece of work is finished, do NOT test it by running the pipeline on a new PDF paper unless the user explicitly asks. LLM calls over a full paper are expensive — finish with unit tests and a summary instead, and let the user decide when to spend a real paper run.
- **One LLM step at a time:** When the user does ask to test with a PDF, run only the single LLM call that step involves and then stop and report. Do NOT chain into the following calls (claim extraction, reconciliation, OBI mapping, group classification) unless the user explicitly tells you to continue.
- **Assay extraction is the exception — it runs the full chain.** When the user asks for a paper's assays, run `scripts/run_assay_pipeline.py`, which does extract → verify → correct → promote → map → canonicalize in one command. Round 1 makes three extraction calls and votes them into one registry (`assay_consensus`): an entry fewer than two of the three found goes to `assays_minority.json` and is printed as a `MINORITY` line, not delivered; one exactly two found is delivered and printed as a `VOTE` line (5 of 178 entries over v3), since the verifier judges fields and never whether every call listed the assay. **This is the only way to run a paper.** There is no single-call extraction path and none is to be reintroduced: `scripts/run_assay_stability.py` was deleted for being one, because a registry produced without the vote is not one the pipeline would ever deliver, and nothing in the file says which way it was made. Never answer a question about a paper's assays from an unvoted extraction, whatever directory it is written to. An unverified registry cannot be told apart from a verified one by reading it, so stopping after round 1 hands back something that looks finished and is not. First report the `--dry-run` call estimate (free) and wait for a go-ahead before the paid run. The deliverable is `assays_benchmark.json`, **keyed by the assay's OBI label** (an assay OBI has no term for keeps its paper name as the key) and carrying per entry exactly `name_in_paper` — a list of every wording the paper used — `aliases`, `generate_claim` (`true` / `false` / `null`: whether the paper reports a finding drawn from this assay — a label to compare against the curated benchmark, never a filter, since an assay the paper performed is an entry either way), `source` (`methods` / `results`), and `evidence` (section / sentence_ids / quote), plus `additional_evidence` on an entry that round 5 folded another onto the same OBI term (same `obi_id` and the same measurement identity — the extraction's own triple of `standard_technique_name`, `sample_type` and `readouts`, none of them conflicting; a field absent on one side never blocks, and `sample_type` is compared by containment so `'sera samples'` and `'samples'` agree while `'serum'` and `'cell supernatants'` do not. **Several entries on one OBI term are correct and expected**, because one entry is one measurement and not one technique — the curators write two rows on one term in 5 of the 31 benchmark papers, and OBI has no term for most assay functions, its compositional labels being pruned from the vocabulary. Two entries on one term that differ on any leg are kept apart under `<label> (2)` and printed as a `REVIEW  not folded` line. `obi_granularity` is no longer a leg: BROAD describes the term, not the assay, and the re-pick that exists to rescue a BROAD mapping changed 0 of 27 across the corpus, so keeping it would split a paper's one measurement for good. A BROAD mapping keeps its category term and round 5 makes no call: the re-pick that used to ask once more for a finer term was removed 2026-10-30 after 52 asks across the corpus changed nothing correctly (27 `none` over round 4's top-20; over all 701 terms 24 `none` and 1 move onto a term whose definition contradicts the record) — the pruned vocabulary has no term for ICS, degranulation, PRNT or FRNT, so there is nothing finer to find; evidence in `experiment/obi_repick_fulllist/` and `docs/assay_workflow_review_2026-10-30.md`; an unmapped assay keeps its own entry and is reported `UNMAPPED`. `docs/assay_entry_grain.md` has the evidence and the before/after score). **Round 6 (`judge`) then asks once about each fold round 5 refused on `readouts` or `sample_type`** — never on the technique — and folds the pair only on a literal `SAME`, printed as `JUDGED  SAME: <reason>` under the `MERGED` line; a `DIFFERENT` verdict leaves the `REVIEW  not folded` line and adds `JUDGED  DIFFERENT: <reason>` under it. `readouts` stays in the identity triple and gets no lenient string match: of the 14 pairs it kept apart across the corpus, 13 are two rows in the curated benchmark (the vote's lenient match released 1), so the leg is binary and the only way to recover a wording-only pair is to ask. Measured 2026-11-02 on v3: 20 asked, 1 `SAME` (SDY2189's FRNT), 19 `DIFFERENT`, precision 88.1% → 88.6%, recall unchanged; `docs/readouts_vote_and_fold_adjudication_2026-11-02.md`. Round 1's own lenient vote delivers, among agreeing rewordings, the one sharing the most content words with the others rather than the shortest, so a detail two of three runs wrote survives (28 `readouts` changed over v3, no fold affected), and `identity_review` (`verdict` + `reason`) on an entry whose identity the verifier left NOT_SUPPORTED or NOT_REPORTED — nothing repairs an identity, so this mark is the only place the doubt reaches the file. Every model reply a run paid for is kept in `assays_raw.json`, by round, so a wrong entry is diagnosed from disk rather than by re-running. Each reply there also carries the call's `usage` (prompt, cached, completion, reasoning tokens), and the run prints a per-round usage block with a list-price dollar estimate (`assay_trace.LIST_PRICE_USD_PER_MTOK`, dated); the three full-paper rounds send their first call alone before the rest so OpenAI's prefix cache can serve calls 2..N, and pass `prompt_cache_key` so one paper's calls share a cache — `docs/plan/assay_token_cost_plan.md`. Every paid run also appends one row (tokens + list-price USD at run time) to `data/assay_usage_ledger.csv`; `scripts/assay_usage_report.py` sums it by month and `--backfill <result_dir>` adds runs made before the ledger existed. Point the user at that file, not `assays.json`, which keeps the full record every pass in the chain works from. The extraction asks the model for seven fields — `name_in_paper`, `standard_technique_name`, `aliases`, `sample_type`, `readouts`, `generate_claim`, `evidence` (section + quote) — and `source` and `evidence.sentence_ids` are then derived from the quote by code, so neither is a value anyone proposed. `standard_technique_name` and `generate_claim` are the two the verifier does not rule on, being judgements rather than values copied from a span; a registry written before `generate_claim` existed reads as `null`. `platform`, `measurement_role` and `parent_hint` were removed; a registry on disk from before that still carries them and every reader tolerates it. Report every `WARNING`, `REVIEW` (including `REVIEW  not folded`), `JUDGED`, `REJECT`, `DROPPED`, `MINORITY`, `VOTE` and `MERGED` line the script prints rather than summarising them away. To canonicalize a registry built before round 5 existed, `scripts/run_assay_merge.py <registry_dir>` runs that round alone — it calls nothing, and `--dry-run` shows what would change. `--judge` runs round 6 after it (paid, one call per refused pair; `--judge --dry-run` reports the count).
- **The ImmPort-wide corpus runs through `scripts/run_immport_assays.py`.** The corpus lives on the external drive: `/Volumes/Extreme SSD/HIPC papers/` holds `papers_all.csv` (every PMID in `study_pubmed`, one row each; `scripts/build_immport_paper_list.py`), `xml/<SDY>_<pmid>.xml` and `papers_xml.csv` / `papers_no_xml.csv` (`scripts/download_immport_xml.py`, free), and `/Volumes/Extreme SSD/HIPC result/<pmid>_<SDY>/` holds each paper's registry, with `logs/<pmid>.log` and `assay_runs.csv` beside them. `run` is `assay_service.assay_report` per paper — the same voted chain, nothing new — with `--parallel P` papers in flight (default 4) and `--limit N` per tranche; a paper whose `assays_benchmark.json` exists is skipped, so a run resumes where it stopped. Always `run --dry-run` first and wait for a go-ahead before each paid tranche; report the tranche summary's `FAILED` and `FLAGGED` lines, and the per-paper logs' `WARNING`/`REVIEW`/… lines they point to, rather than summarising them. `status` reads the drive and the ledger.
- **Re-parsing overwrites the old result:** When the user asks to parse a paper, write the output over that paper's existing result files in place (e.g. `data/claims/<paper>/claims.json`) — do not create a timestamped/suffixed copy, a new sibling directory, or otherwise keep the previous run alongside it. Only preserve the old result if the user explicitly asks you to.

## Repo / Git Etiquette

### Branch Strategy
- **Never commit directly to main** unless the user asks or for small changes
- Use feature branches for all work
- Descriptive branch names: `feature/transcript-selector`, `fix/gemini-timeout`

### Commit Practices
- Commit frequently as you work
- Write clear, descriptive commit messages
- Keep commits focused on single changes

### Issue Tracking
- Create GitHub issues for all planned features
- Reference issues in commit messages when applicable
- Use issues to track bugs and enhancements

### Worktrees
- Native Claude Code worktrees live in `.claude/worktrees/` (used by `EnterWorktree`)
- Legacy feature worktrees may exist in `.trees/` (gitignored)
- When a branch is in a worktree, work directly in the worktree path instead of `git checkout`
