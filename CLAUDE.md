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
- `OPENAI_API_KEY` — OpenAI key (model defaults to `gpt-4o`)
- `MYSQL_URL` — async MySQL URL, e.g. `mysql+aiomysql://user:pass@localhost:3306/claim_reproduce`

Tests stub these out automatically via `tests/conftest.py`.

## Architecture

This is an AI agent that takes a **signature JSON** file (ImmPort study format) and returns which database subjects match the paper's participant groups. It exposes a **ChatGPT-style web UI** and a REST API.

### Full stack

```
frontend/          Next.js 15 + React 19 + Tailwind CSS (port 3000)
app/               FastAPI backend (port 8000)
```

The frontend proxies `/backend/*` → `http://localhost:8000/*` via `next.config.ts` rewrites, so both servers must be running.

### Frontend components (`frontend/src/`)

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

### Backend pipeline (`app/agent/orchestrator.py:run_agent`)

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

### API response shape

```json
{
  "study_accession": "SDY1669",
  "subject_results": [
    {
      "group_id": "1",
      "group_name": "Healthy individuals",
      "arm_accession": "ARM5346",
      "experiment_accession": "EXP15660",
      "tissue_type": "",
      "condition": "healthy",
      "subjects": [{ "subject_accession": "SUB255603", ... }],
      "error": null
    }
  ]
}
```

The UI renders this as a formatted JSON block in the assistant chat bubble.

### LLM prompt

The description analyzer system prompt lives in `app/prompts/description_analyzer.txt` (not inline). Modify it there to change how groups are parsed from paper text.
