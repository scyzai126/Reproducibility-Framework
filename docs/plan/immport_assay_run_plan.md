# ImmPort assay corpus — step 3: run the assay pipeline over the 1,100 XML papers, in parallel tranches

## Context

Steps 1–2 (commits b31f105, b4b3845 on `feature/immport-assay-corpus`) put the corpus on the SSD: `/Volumes/Extreme SSD/HIPC papers/xml/<SDY>_<pmid>.xml` (1,100 papers) and `papers_xml.csv` (pmid, study_accessions, primary_sdy, pmcid, file, bytes). The user now asks how to process those 1,100 papers in batches and how to run them in parallel. Results go to `/Volumes/Extreme SSD/HIPC result/` (decided earlier).

What one paper costs today (measured, `data/assay_usage_ledger.csv`): 21–25 calls, $0.36–$0.40, ~3 min wall-clock, run by `assay_service.assay_report(pmid, sdy, client, verify=True, correct=True)` — the voted five-round chain, the only sanctioned way to produce a registry. Sequentially, 1,100 papers ≈ $420 and ≈ 55 h. Parallelism cuts the hours, not the dollars.

Facts verified for running papers concurrently in one process:
- `assay_verifier`/`assay_corrector` build a fresh `asyncio.Semaphore(8)` per call (assay_verifier.py:821, assay_corrector.py:382), so N papers in flight = up to 8·N concurrent OpenAI calls.
- The usage trace is a `ContextVar` started inside `assay_report` (assay_trace.py:86–96, assay_service.py:886); asyncio copies the context into each task, so concurrent papers record separately. `assay_ledger.record_run` appends its row synchronously in the `finally` (assay_service.py:896). Round 4's OBI mapper runs in a worker thread with its own sync client.
- Each paper writes only inside its own `registry_dir(pmid, sdy)`; the roots are module globals read at call time. `registry_dir` checks `REGISTRY_ROOT` (default `data/31paper_assays/assay_result_v1`) before `CACHE_ROOT`, so **both** must be re-pointed or a benchmark paper would overwrite its v1 registry.
- No retry/timeout is configured on the shared client (`claim_parser._get_client`, SDK default 2 retries); the SDK backs off on 429 by itself when `max_retries` is raised.
- `data/31paper_assays/assay_result_v3` holds XML-based registries for 27 of the 36 curated papers (4 more are `_pdf`); copying them saves 27 runs (~$11).
- Benchmark XML copies in `HIPC papers/xml` carry the same sentence numbering as `data/JAT_XML`, so a copied v3 registry's quotes still match.

## How batching and parallelism work (the answer to the question)

- **Unit of work**: one paper = one `assay_report` call, writing `HIPC result/<pmid>_<primary_sdy>/` (10 standard files; `assays_benchmark.json` written last = done marker).
- **Batches (tranches)**: `--limit N` takes the first N not-yet-done papers from `papers_xml.csv` order; a paper whose done marker exists is skipped, so each invocation continues where the last stopped. `--dry-run` before each tranche prints `N × median $/paper` from the ledger and the projected hours; CLAUDE.md requires a go-ahead before every paid tranche.
- **Parallel papers**: `--parallel P` (default 4) keeps P papers in flight via `asyncio.Semaphore(P)` + `asyncio.create_task`, one process, one `AsyncOpenAI(max_retries=5, timeout=600)` client. P=4 ≈ 32 concurrent calls at peak; wall-clock ≈ 55 h / P ≈ 14 h at P=4, ≈ 7 h at P=8. The pilot decides P: if per-paper time at P=4 stays near 3–4 min there is headroom; if it stretches to >8 min or `RateLimitError` surfaces after the SDK's 5 retries, drop to 2.
- **Output ordering**: tasks return the result dict; `report_result` (the WARNING/REVIEW/… lines) is printed by the main loop as each task completes, under a per-paper banner, and tee'd to `HIPC result/logs/<pmid>.log`, so lines from two papers never interleave.
- **Stop conditions**: `--max-usd X` stops launching new papers once this run's ledger spend crosses X (in-flight papers finish); Ctrl-C cancels in-flight tasks, whose folders have no done marker and are re-run next time.
- **Suggested schedule**: pilot `--limit 20 --parallel 4` (~$8, ~20 min) → review summary → tranches of `--limit 200 --parallel 4` (~$80, ~3 h each, 5–6 tranches), or one overnight `--max-usd 450` run if the pilot is clean.

## Implementation

### 1. `apps/api/app/agent/immport_corpus.py` — additions
- `RESULT_DIR = Path("/Volumes/Extreme SSD/HIPC result")`, `RESULT_LOG_DIR_NAME = "logs"`, `RUNS_NAME = "assay_runs.csv"`, `RUN_COLUMNS = ("pmid","primary_sdy","study_accessions","status","registry_dir","calls","usd","seconds","flags","error","finished_at")`.
- `read_xml_papers(papers_dir)` — `papers_xml.csv` rows with `studies` split.
- `done_marker(result_dir, pmid, sdy) -> Path` — `<pmid>_<sdy>/assays_benchmark.json`.
- `benchmark_registry(pmid, studies, version_root) -> Path | None` — an XML-based (non-`_pdf`) `<pmid>_<sdy>/` holding `assays_benchmark.json` under any of the paper's studies.
- `REPORT_PREFIXES` and `count_report_lines(text) -> dict[str,int]` — counts WARNING/REVIEW/JUDGED/REJECT/DROPPED/MINORITY/VOTE/MERGED/UNMAPPED/ERROR lines (longest prefix wins) in a captured `report_result` text.
- `cost_per_paper(ledger_rows, under: Path) -> {median, max, n}` over ledger rows whose `registry_dir` is under `under` (corpus spend only), falling back to all rows, then to $0.40 with n=0.
- `summarize_runs(rows) -> dict` for `status`.

### 2. `scripts/run_immport_assays.py` (new)

```
python3 scripts/run_immport_assays.py run    [--limit N] [--parallel P] [--only PMID...] [--force]
                                             [--dry-run] [--max-usd X] [--paper-timeout S]
                                             [--reuse-benchmark assay_result_v3 | --no-reuse-benchmark]
python3 scripts/run_immport_assays.py status [--failed] [--flags]
```
Common: `--papers-dir`, `--result-dir` default to the SSD paths; refuse to run if either is missing.

**Startup** (before any work, the `use_result_version` pattern):
```python
assay_service.XML_ROOT = papers_dir / "xml"
assay_service.PDF_ROOT = result_dir / "no_pdf"      # absent → PDF route off
assay_service.REGISTRY_ROOT = result_dir
assay_service.CACHE_ROOT = result_dir
```
With both roots equal and no PDF root, `registry_dir(pmid, primary_sdy)` is `result_dir/<pmid>_<primary_sdy>` unconditionally and nothing under `data/` can be written; ledger rows carry that `registry_dir`.

**Queue**: `papers_xml.csv` order; skip if done marker exists (unless `--force`); `--only` filter; reuse pass: `benchmark_registry` hit → `shutil.copytree` into `result_dir/<pmid>_<primary_sdy>` (status `reused`, no call); then `--limit`.

**`--dry-run`**: prints pending / reused / skipped counts, `n × median` and `n × max` $ (stating how many ledger rows the median rests on), hours at the chosen `--parallel` from measured seconds/paper (fallback 180 s), "nothing called".

**Loop**:
```python
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, max_retries=5, timeout=600)
sem = asyncio.Semaphore(parallel)
async def one(paper):
    async with sem:
        if max_usd and spent() >= max_usd: return ("stopped", paper, None)
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(assay_report(pmid, sdy, client, verify=True, correct=True), paper_timeout)
            return ("done", paper, result, time.monotonic() - t0)
        except Exception as exc:              # incl. asyncio.TimeoutError
            return ("failed", paper, exc, time.monotonic() - t0)
for task in asyncio.as_completed([one(p) for p in queue]):
    status, paper, payload, secs = await task
    # main loop only: print banner + report_result(result) into a StringIO, tee to stdout and logs/<pmid>.log,
    # count flags, read this paper's newest ledger row for calls/usd, append a row to assay_runs.csv (atomic rewrite)
```
`spent()` sums this run's ledger rows (by `registry_dir` under `result_dir` and date ≥ start). `assay_runs.csv` is rewritten atomically (`write_csv`) after every completion by the main loop — single writer.

**End of run**: `logs/tranche_<timestamp>.txt` + stdout: done / reused / failed / stopped, calls, $ this run, seconds/paper median at this `--parallel`, flag totals by prefix, every failed paper with its error, every paper with any flag > 0 with counts and its log path.

**`status`**: counts from `papers_xml.csv` × disk × `assay_runs.csv`: with XML, done, reused, failed, pending; $ spent (ledger rows under `result_dir`), median $/paper, projected remaining; flag totals. `--failed` lists errors, `--flags` lists flagged papers.

### 3. Tests
- `apps/api/tests/test_immport_corpus.py` — add: `benchmark_registry` ignores `_pdf` and finds a non-primary study's folder; `count_report_lines` (`DROPPED ALIAS`→DROPPED, `REVIEW  not folded`→REVIEW, indented `JUDGED`, `OBI FAILED` not counted as ERROR); `cost_per_paper` prefers rows under the result dir, falls back to 0.40/n=0; `done_marker`.
- `apps/api/tests/test_run_immport_assays.py` (new; importlib loader like `test_run_assay_batch.py`; monkeypatch `immport_corpus.PAPERS_DIR/RESULT_DIR` to tmp; stub `assay_report` à la `_fake_report` writing into `assay_service.registry_dir(pmid, sdy)`):
  - results land under tmp `result_dir/<pmid>_<SDY>/`, and a same-named folder under the original `REGISTRY_ROOT` is untouched (overwrite guard);
  - `--parallel 3`: a stub that records concurrent in-flight count observes ≤ 3 and > 1;
  - a raising paper is `failed` with its error and the others finish; a stub sleeping past `--paper-timeout` is `failed`;
  - `--limit 1`, `--only`, `--force`, resume (done marker → skipped);
  - reuse copies the benchmark folder and calls nothing; `--no-reuse-benchmark` runs it;
  - `--dry-run` calls nothing and prints `n × median` from a stubbed ledger;
  - `logs/<pmid>.log` holds the stubbed `report_result` lines and `assay_runs.csv` has the flag counts;
  - `--max-usd` stops launching after the crossing paper (stub ledger rows);
  - `status` counts on a hand-built `assay_runs.csv`.

### 4. CLAUDE.md "Paper / LLM Runs": one paragraph naming `scripts/run_immport_assays.py` as the corpus runner (it is `assay_report` per paper, the voted chain), the `--dry-run` + go-ahead rule per tranche, and where results/logs live. `.gitignore`: nothing (all on the SSD).

## Verification
1. `cd apps/api && ../../.venv/bin/python -m pytest tests/test_immport_corpus.py tests/test_run_immport_assays.py -q` green; full suite still only the 10 known subject-query failures.
2. `run --dry-run` → 1,100 with XML, 27 reusable, ~1,073 pending, `≈ $0.40 × 1,073`, hours at P=4.
3. **Go-ahead**, then pilot `run --limit 20 --parallel 4` (~$8). Check: 20 folders with `assays_benchmark.json`, 20 ledger rows under `HIPC result`, tranche summary's flag lines reported verbatim, median seconds/paper at P=4.
4. `run --dry-run` again (projection now rests on 22 rows). **Go-ahead** per tranche of `--limit 200`; `status` after each.
5. Commit on `feature/immport-assay-corpus`; copy this plan to `docs/plan/immport_assay_run_plan.md`.

## Out of scope
- PDF route for the 213 papers in `papers_no_xml.csv`; OpenAI Batch API; multi-process sharding (only if one process's event loop proves to be the bottleneck, which at 32 concurrent HTTP calls it will not); retries on the OBI mapper's own sync clients; linking registries to ImmPort experiment rows; exposing corpus papers in the web UI.
