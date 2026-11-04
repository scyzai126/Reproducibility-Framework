# Assay pipeline token cost: record real usage (A) and warm the prompt cache (B)

## Context

The assay chain (`scripts/run_assay_pipeline.py` → `assay_service.assay_report`) counts cost in
API calls only. Nothing reads `response.usage`, so the real bill per paper is unknown: a
char-based estimate over the v3 corpus gives ~$0.36–$1.47 per paper (median ~$0.59, ~$21 for
31 papers at gpt-5.4 list price), but that estimate cannot see two things that decide the
actual number — how many prompt tokens OpenAI served from its prefix cache ($0.25/M instead of
$2.50/M) and how many hidden reasoning tokens gpt-5.4 billed as output ($15/M).

~90% of the estimated cost is rounds 1–3 re-sending the full paper on every call (3 extraction
calls + one verify call per assay + one correction call per flagged field). All three prompts
already put the stable part first (template → title → full paper) and the per-entry part last,
so OpenAI's automatic prefix caching *should* discount calls 2..N — but every round fires its
calls concurrently (`asyncio.gather` under a semaphore of 8), so the first batch arrives before
any cache entry exists and likely all miss.

The user chose, of the options presented, only the two that change no result:

- **A.** Record usage per call into `assays_raw.json` and report it per run.
- **B.** Warm the cache: send the first call of each full-paper round alone, then the rest
  concurrently, and pass `prompt_cache_key` so the paper's calls route to the same cache.

Everything else (lower `reasoning_effort`, flex/Batch tier, batched verification, trimmed
context, cheaper model) is deferred until A shows what the real split is.

## Part A — record real token usage

### A1. `apps/api/app/agent/assay_trace.py`

- Add `usage_fields(resp) -> dict`: reads `resp.usage` with `getattr` defaults and returns
  `{"prompt": int, "cached": int, "completion": int, "reasoning": int}`; returns `{}` when
  `resp` has no `usage` (every existing test fake lacks it — see `_FakeClient` in
  `tests/test_assay_verifier.py:343`, `tests/test_assay_service.py:89`). `cached` comes from
  `usage.prompt_tokens_details.cached_tokens`, `reasoning` from
  `usage.completion_tokens_details.reasoning_tokens`. Pattern to copy:
  `UsageTracker.record` in `apps/api/app/agent/claim_abstraction_v5.py:225`.
- Add `usage_summary(raw: dict) -> dict`: walks a grouped trace (the shape `Trace.as_json()` /
  `assays_raw.json` has: round → key → [field →] payload) and sums every payload's `usage`
  into `{"by_round": {round: {calls, prompt, cached, completion, reasoning}}, "total": {...}}`.
  `calls` counts every payload, with or without `usage`, so a fake/failed call still counts.
  Derived from the file rather than stored, so `Trace.write`'s merge (`run_assay_merge.py --map`
  adding an `obi` block later) needs no change and a reader of any `assays_raw.json` can
  recompute it.
- Add `LIST_PRICE_USD_PER_MTOK = {"gpt-5.4": {"input": 2.50, "cached": 0.25, "output": 15.00}}`
  with a dated comment (2026-11-04, OpenAI list price, standard tier) and
  `estimate_usd(summary_total, model) -> float | None` (None when the model is not in the
  table). Formula: `(prompt - cached)*input + cached*cached_price + completion*output`, per
  million. Completion already includes reasoning tokens.

### A2. Pass `usage=usage_fields(resp)` at every record site

| file | line | round |
|---|---|---|
| `app/agent/assay_extractor.py` | 395 | extract (xml) |
| `app/agent/assay_extractor_pdf.py` | 99 | extract (pdf) |
| `app/agent/assay_verifier.py` | 761 | verify |
| `app/agent/assay_corrector.py` | 311 | correct |
| `app/agent/assay_obi_mapper.py` | ~468 (`_pick` trace record) and 688 (`obi_fulllist`) | obi |
| `app/agent/assay_fold_judge.py` | 109 | judge |

Each is a one-argument addition to the existing `assay_trace.record(...)` call. When
`usage_fields` returns `{}` do not add the key (keeps `test_assay_trace.py`'s exact-dict
assertions and old raw files unchanged).

### A3. Report it

- `assay_service._run_rounds` (`apps/api/app/agent/assay_service.py`, the `return {` at the
  end, ~line 1226): add `"usage": assay_trace.usage_summary(trace.as_json())` to the result.
- `scripts/run_assay_pipeline.py:report_result` (line 218): after the per-round `call(s)`
  lines print one line per round with tokens and one total line, e.g.
  `usage: 21 calls, 150,312 prompt (41,200 cached), 14,283 completion (2,900 reasoning) ≈ $0.52 at gpt-5.4 list price (2026-11-04)`.
  The `≈ $` part is omitted when `estimate_usd` returns None. `run_assay_batch.py` calls the
  same `report_result`, so the batch gets it for free; add a batch total line there only if it
  already prints a batch-level summary (check `scripts/run_assay_batch.py` when implementing).
- `scripts/run_assay_merge.py`: the rounds it runs (`--map`, `--judge`) record through the
  same sites, so no change beyond printing the same usage line from the written file.

## Part B — make the prefix cache hit

### B1. Warm-first in the three full-paper rounds

- `assay_verifier.verify_registry` (line 783): await `_verify_one(keys[0])` alone, then
  `gather` the remaining keys. Order of results is preserved by building the list as
  `[first] + list(await gather(...))`. Progress lines and `on_item` unchanged.
- `assay_corrector.correct_registry` (line 348): same shape over `plan`.
- `assay_service._run_rounds` round 1 (lines ~940–946): await the first `_extraction_attempt`
  alone, then gather the rest. Applies to both the xml and pdf branches. Failure handling after
  `outcomes` is unchanged (the first outcome is just prepended).
- Document in each docstring why: calls 2..N share the first call's prefix only if the first
  has finished (OpenAI caches a prefix after a request completes). Cost: one call's latency per
  round added to wall-clock.

### B2. `prompt_cache_key`

- Add `paper_cache_key(source_text: str) -> str` to `apps/api/app/agent/assay_extractor.py`
  (sha1 of the text, first 16 hex, prefixed `assay-`). The verifier and corrector already
  import from the extractor module; the extractor PDF path can use the pdf text layer's key.
- Pass `prompt_cache_key=paper_cache_key(source_text)` in the `chat.completions.create` calls
  of extract (xml + pdf), verify and correct. openai SDK is 2.30.0 in the venv, which accepts
  the parameter. Every test fake's `create(**kwargs)` already swallows unknown kwargs.
- OBI pick, fulllist and judge calls: no key. Their prompts carry no paper; the shared prefix
  is the template alone (~2.4k tokens) and caches by itself.

### B3. No behaviour change

Prompts, model, temperature, seed and parsing are untouched, so outputs are identical modulo
model nondeterminism. No benchmark re-run is needed for B.

## Tests (`apps/api/tests/`, run with `../../.venv/bin/python -m pytest` from `apps/api`)

- `test_assay_trace.py`: `usage_fields` on a `SimpleNamespace` usage with and without the
  `*_details` objects, and on a response without `usage` (→ `{}`); `usage_summary` over a
  grouped dict mixing payloads with and without `usage` (calls counted, tokens summed per round
  and in total); `estimate_usd` for a known and an unknown model.
- `test_assay_verifier.py` / `test_assay_extractor.py`: one test each where the fake response
  carries a `usage` object and the active trace's record has the expected `usage` dict.
- `test_assay_verifier.py` and `test_assay_corrector.py`: warm-first ordering — a fake client
  whose `create` records call start order and blocks the first call on an `asyncio.Event`;
  assert no second call starts until the first returns, and that results come back in registry
  order.
- `test_assay_service.py`: the result dict carries `usage` with `total.calls` equal to the
  recorded calls; a fake client with `**kwargs` keeps working.
- `test_run_assay_pipeline.py`: `report_result` prints the usage line and omits the `$` part
  for an unknown model.

## Verification

1. `pytest` from `apps/api` passes.
2. `python scripts/run_assay_pipeline.py <registry_dir> --dry-run` is unchanged (free).
3. One paid single-paper run (ask the user first, ~$0.4–0.6, e.g. `36656789_SDY1393`, the
   cheapest paper). Then read `assays_raw.json`:
   - extract `run2`/`run3` show `cached` ≈ their `prompt`; `run1` shows `cached` 0.
   - verify and correct: every call after the first shows `cached` ≈ template + paper tokens.
   - the printed usage line gives the first real per-paper dollar figure and the reasoning
     share, which decides whether option C (`reasoning_effort`) is worth an eval.
4. Diff check: only the files named above plus tests and the plan doc are touched.

## Docs

- Copy this plan to `docs/plan/assay_token_cost_plan.md` (project rule: plans live in
  `docs/plan/`). After the paid run, add the measured numbers to that file rather than a new
  write-up.
- CLAUDE.md "Assay extraction" paragraph: one sentence that `assays_raw.json` now carries
  per-call `usage` and the run prints a usage/cost line.

## Out of scope (deferred until A has numbers)

reasoning_effort, flex / Batch tier, batching several assays per verify call, sending only
relevant sections, cheaper model for verify/correct, and a dollar figure in `--dry-run`
(could later be "last run cost $x" read from the stored usage).

## Status

- 2026-11-04: A and B implemented on `feature/assay-token-usage-cache`; unit tests added
  (trace, verifier, corrector, extractor, service, CLI printer). The paid single-paper
  measurement (verification step 3) has not been run yet; its numbers go here when it has.
