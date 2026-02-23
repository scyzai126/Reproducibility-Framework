# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload

# Run all tests
pytest

# Run a single test file
pytest tests/test_query_builder.py

```

## Environment

Copy `.env.example` to `.env` and fill in:
- `OPENAI_API_KEY` — OpenAI key (model defaults to `gpt-4o`)
- `MYSQL_URL` — async MySQL URL, e.g. `mysql+aiomysql://user:pass@localhost:3306/claim_reproduce`

Tests stub these out automatically via `tests/conftest.py`.

## Architecture

This is an AI agent that takes a **signature JSON** file (ImmPort study format) and returns which database subjects match the paper's participant groups.

### Pipeline (`app/agent/orchestrator.py:run_agent`)

```
POST /agent/run  {"file_path": "..."}
  → file_reader        read JSON/CSV/TXT from disk
  → signature_parser   extract participant groups + study_accession
  → description_analyzer  (OpenAI) extract cohort/assay_method/tissue_type/condition per group
  → query_builder      resolve terms → DB accessions, then build parameterized SQL
  → execute queries    against ImmPort MySQL
  → return subject_results per group + write logs/agent_run.log
```

### Key design: two-step accession resolution (`query_builder.py`)

When a group references a cohort name or assay method, `_resolve_accession()` does:
1. **SQL LIKE** match on `name`/`description` columns — returns immediately if exactly 1 hit
2. **LLM fallback** — fetches all candidates for the study, asks OpenAI to pick the best match

This applies to both arm resolution (`arm_or_cohort` table → `arm_accession`) and experiment resolution (`experiment` table → `experiment_accession`).

### SQL query shape (`query_builder._build_query`)

All queries join `expsample → expsample_2_biosample → biosample` with an optional `LEFT JOIN immune_exposure`. Active filters are driven by `OPTIONAL_FILTERS` list (experiment, study, tissue_type, condition). Arm membership is handled separately via a subquery on `arm_2_subject`.

### LLM prompt

The description analyzer system prompt lives in `app/prompts/description_analyzer.txt` (not inline). Modify it there to change how groups are parsed from paper text.