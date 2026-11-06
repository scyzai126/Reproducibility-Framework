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

## Status (2026-11-06)

- Runner built, tested (31 tests) and committed (77d7e5a). CLAUDE.md paragraph added. Pointer-only-Methods fix committed (a349ae6).
- **Output files decision (user, 2026-11-06): keep all five rounds and all ten files.** The files cost no tokens; the only cuttable round (OBI, ~20%) stays. No code change.
- Pilot complete: 35 papers run + 27 reused from the curated v3 set.

| | |
|---|---|
| assay entries | 149 |
| OBI-mapped | 134 (90%) |
| zero-assay papers | 2, both reviews (correct) |
| calls / cost | 738 / $7.23 |
| median s/paper at P=4 | 37 (max 102) |

  Flag totals: REVIEW 61, MINORITY 19, UNMAPPED 15, DROPPED 14, JUDGED 9, VOTE 8, REJECT 6, CORRECT REFUSED 3.

## Pilot quality review (2026-11-06) — verdict: good enough to run the corpus

**Correct.** Entry lists track the Methods sub-headings closely on bench-science papers (21220454: 13 entries over 13 assay subsections; 19931408: 14, with three thymidine-incorporation measurements correctly kept apart by round 6 on specimen and readout). Alias folding works: 17156490 returns one bead-assay entry whose `aliases` hold both the Beadlyte kit and the BD CBA naming, so its two MINORITY lines were absorbed, not lost. Evidence quotes are present and verifiable on every entry inspected. DROPPED/REJECT correctly removed readouts and endpoints posing as assays (urinary cotinine, plaque-forming units, fasting plasma glucose). The corrector's quote guard rejected 3 replacement quotes absent from the document.

**Known weakness, accepted by the user (keep, flag only — no prompt change).** Clinical-trial, cohort-design and survey papers have no bench assays, and the extractor fills their registries with procedures instead: height/weight measurement (19459814), blood/nasal/dust/air collection and the Edinburgh Postnatal Depression Scale (20571137), `survey` (21158924). These are most of the 15 UNMAPPED entries and are therefore separable downstream by the absent OBI term, with no re-run. Two already carry `identity_review` NOT_SUPPORTED.

**Known precision error, deferred by the user.** 19459814 holds the same protocol biopsies twice, as `histopathology assay` and `histological assay`, because round 5 only compares entries that already share an OBI term. Measure its frequency over the full corpus before designing a cross-term fold.

## Next: the remaining ~1,038 papers

1. `run --dry-run` (free) — report pending count, `n × median $` (median now rests on 35 corpus rows, $0.13–0.15, far under the $0.40 benchmark figure), hours at P=4.
2. Go-ahead, then tranches of `run --limit 200 --parallel 4`, dry-run + go-ahead before each. Projection: ~$137 and ~2.5 h total at the pilot's 37 s/paper.
3. After each tranche: report the summary's FAILED and FLAGGED lines verbatim, then `status`.
4. After the corpus: count cross-term duplicate pairs and UNMAPPED procedure entries over all 1,100 papers; decide the fold fix and any prompt exclusion then, on real frequencies.

## Done: a pointer-only Methods section triggers structure 3 (2026-11-06, commit a349ae6)

**Why the three zero-assay papers came back empty.** The extraction prompt (`apps/api/app/prompts/extract_assays.txt`) does read Results, but under two different rules:
- Structure 1/2 (a `[methods]` section exists): the inventory is built from Methods only; Results, `[other]` and captions can add an entry only when a sentence states the technique was performed on this study's samples. A result sentence or a caption that reports a result admits nothing.
- Structure 3 (no `[methods]` section): the inventory is built from abstract, main text and captions; "performed here" replaces "described in Methods". Code decides which applies: `assay_extractor.has_methods_section` (line 353) checks only whether the tag `[methods]` occurs, and `build_prompt` prepends `NO_METHODS_NOTE` when it does not.

19541535 and 20667703 are reviews: structure 3 applied, every assay mention is cited work, so `{}` is correct. 20495560 (Nature Immunology) has a Methods section that is one sentence ("Methods ... are available in the online version"), so `has_methods_section` returned True, structure 1 applied with an empty Methods inventory, and the strict Results rule admitted nothing, 3 votes of 3. Corpus scan: 1,018 of 1,100 XMLs have substantive Methods, 81 have none (structure 3 applies correctly), 1 is pointer-only.

**Change (small, in the shared extractor):**
- `apps/api/app/agent/assay_extractor.py`: `has_methods_section(source_text)` returns True only when the text under `[methods]`-tagged headings (prose before the `--- Figures ---` banner) totals at least `MIN_METHODS_CHARS = 300`; a pointer-only section counts as absent. `build_prompt` and `assay_service` (`no_methods` flag, line 1027) need no change since both call it.
- `apps/api/tests/test_assay_extractor.py`: a source whose only `[methods]` section is a 90-character pointer gets `NO_METHODS_NOTE`; a real Methods section still does not.
- Re-run 20495560 alone (`run --only 20495560 --force`, ~3 calls, ~$0.05) and compare against the captions' assays (intracellular cytokine staining, serum IgE/IgG ELISA, etc.). Report the result; if still `{}`, the paper joins the PDF list.

## Out of scope
- PDF route for the 213 papers in `papers_no_xml.csv`; OpenAI Batch API; multi-process sharding (only if one process's event loop proves to be the bottleneck, which at 32 concurrent HTTP calls it will not); retries on the OBI mapper's own sync clients; linking registries to ImmPort experiment rows; exposing corpus papers in the web UI.
