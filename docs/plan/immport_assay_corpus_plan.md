# ImmPort-wide assay extraction: manifest, bulk fetch, resumable tranche runner

## Context

The user wants the assay registry (`assays_benchmark.json`) for **every paper linked to an ImmPort study**. Claims are out of scope. Today the five-round assay chain (`assay_service.assay_report`) runs one paper at a time from `data/JAT_XML` (36 curated files), and `scripts/run_assay_batch.py` only sweeps that directory. Nothing enumerates the corpus, fetches XML in bulk by PMID, tracks per-paper status, or paces a ~1,200-paper spend.

Facts verified this session:
- `study_pubmed` in the local mirror (`immport_dr62`) has 1,562 rows → **1,313 usable distinct PMIDs** (28 rows unusable: "TBD", PMC ids, "PMID:" labels). 117 PMIDs belong to >1 study (max 27). Many-to-many both ways.
- NCBI ID converter: **1,242 of 1,313 have a PMC record**; a share of those will come back abstract-only or publisher-blocked (detected by `jats_fetcher.unavailable_reason`).
- Measured cost: $0.36–$0.40 per paper (21–25 calls; ledger `data/assay_usage_ledger.csv`). A registry folder is ~184 KB (100 KB is `assays_raw.json`). Output files are not the cost driver; rounds are, and the vote + verify rounds are mandatory per CLAUDE.md. Standard 10 files kept.
- Benchmark registries: `assay_result_v3` has 32 folders (31 papers, 4 of them `_pdf`); `assay_result_v4` has only 2. `assay_registry.RESULT_VERSION = "assay_result_v1"`, so `assay_service.REGISTRY_ROOT` defaults to v1 at import — overriding only `CACHE_ROOT` would let a benchmark paper overwrite its v1 registry (registry_dir checks REGISTRY_ROOT first, assay_service.py:297–315). Both roots must be overridden.
- `assay_obi_mapper` builds its own sync `OpenAI()` clients (lines 300, 460, 684); retries set on the AsyncOpenAI passed to `assay_report` cover rounds 1–3 and judge only. Installed `openai` 2.30.0 accepts `max_retries`/`timeout`.

Decisions made by the user: assays only; all `study_pubmed` PMIDs, PMC XML only (no PDF route); resumable sequential loop run in tranches with a go-ahead between tranches (not the Batch API); a multi-study paper is parsed once; no output-file trimming.

## Layout (all new, under `data/`)

```
data/immport_assays/manifest.jsonl              committed (~1,313 lines)
data/immport_assays/registries/<pmid>_<SDY>/    gitignored (standard 10 files each, ~250 MB total)
data/immport_assays/logs/<pmid>.log             gitignored (report_result output per attempt)
data/immport_assays/logs/tranche_<ts>.txt       gitignored (one summary per `run` invocation)
data/JAT_XML_immport/<SDY>_<pmid>.xml           gitignored (like JAT_XML_vaccine1000)
```

Separate dirs on purpose: `assay_service.available_papers()` walks `XML_ROOT` and `paper_resolver._local_state()` walks `REGISTRY_ROOT`/`CACHE_ROOT`, so the web UI and corpus table see nothing new; `run_assay_batch.py` keeps sweeping only the 36 curated papers.

## Part A — corpus module

### A1. `apps/api/app/agent/immport_corpus.py` (new)

Pure functions over rows/dicts/paths; no DB engine import (query takes a caller-supplied session, like `paper_resolver`). Reuse, don't copy: `paper_resolver.normalize_row_pmid` (line 109), `assay_service.split_stem`/`PDF_DIR_SUFFIX`/`XML_ROOT`, `assay_ledger.read_rows`.

Module-level patchable paths: `CORPUS_DIR`, `MANIFEST_PATH`, `XML_DIR`, `REGISTRY_DIR`, `LOG_DIR`; `DEFAULT_USD_PER_PAPER = 0.40`, `DEFAULT_SECONDS_PER_PAPER = 150`.

Functions:
- `async study_pubmed_rows(session)` — `SELECT study_accession, pubmed_id FROM study_pubmed ORDER BY ...`, no LIMIT.
- `group_papers(rows) -> ({pmid: sorted studies}, unusable[{study_accession, raw, reason}])`.
- `primary_sdy(studies)` — min by numeric part (`SDY80` < `SDY1119`); deterministic from the DB alone.
- `new_record(pmid, studies)` with schema: `pmid, studies[], primary_sdy, pmcid, fetch_status (pending|fetched|benchmark_copy|no_pmc|unavailable|failed), fetch_reason, xml_path, xml_bytes, run_status (pending|done|reused|failed), run_error, registry_dir, calls, usd, seconds, flags {prefix: count}, updated_at`.
- `read_manifest(path)` / `write_manifest(records, path)` — write to `.jsonl.tmp` then `os.replace` (crash-safe; full rewrite after every paper is cheap).
- `merge_enumeration(existing, grouped)` — adds new PMIDs, refreshes `studies`/`primary_sdy`, never drops or touches fetch/run fields.
- `benchmark_xml(pmid, studies)` — `<sdy>_<pmid>.xml` under `assay_service.XML_ROOT` for any sdy in `studies`.
- `benchmark_registry(pmid, studies, version_root)` — `<pmid>_<sdy>/assays_benchmark.json` for any sdy, **excluding `_pdf` folders**.
- `parse_idconv(payload) -> {str(pmid): pmcid|None}` (idconv returns int pmids for some records).
- `resolve_manifest_from_disk(record)` — disk wins for what disk can tell: registry with `assays_benchmark.json` → `done`; missing XML → fetch `pending`. Called on load by `run`/`status`, so a crash between the pipeline's last write and the manifest rewrite self-heals.
- `REPORT_PREFIXES = ("WARNING","REVIEW","JUDGED","REJECT","DROPPED","MINORITY","VOTE","MERGED","UNMAPPED","ERROR","OBI FAILED","CORRECT FAILED","CORRECT REFUSED")` and `count_report_lines(text)` (longest prefix wins) — matches what `report_result` prints (run_assay_pipeline.py:233–390).
- `cost_per_paper(ledger_rows) -> {median, max, n}` (fallback 0.40, n=0); `seconds_per_paper(records)`; `summarize(records, unusable, ledger_rows)` for `status`.

## Part B — the script

### B1. `scripts/run_immport_assays.py` (new): `enumerate | fetch | run | status`

Same sys.path bootstrap as `run_assay_batch.py`; imports `fetch_batch, split_articleset, article_record, _params, request_delay` from `scripts/download_pmc_corpus.py` and `report_result` from `scripts/run_assay_pipeline.py`.

**`enumerate`** (free, only subcommand that imports `app.database`): rows → `group_papers` → `merge_enumeration` → `write_manifest`. Prints rows read, unusable rows with reasons, usable PMIDs, shared PMIDs, new vs known.

**`fetch [--dry-run] [--limit N] [--retry-unavailable] [--force]`** (free, NCBI only; sync `requests.Session`), over records with `fetch_status in (pending, failed)`:
1. Benchmark copy: `benchmark_xml` found → `shutil.copyfile` to `XML_DIR/<primary_sdy>_<pmid>.xml`, status `benchmark_copy` (a copy, not a refetch, so sentence numbering matches the reused registry).
2. idconv in chunks of 200 → `parse_idconv` → `pmcid` or `no_pmc`. Manifest rewritten per chunk.
3. efetch in chunks of 50 via `fetch_batch` → `split_articleset` → `article_record` keyed by pmcid. Missing → `unavailable`; `unavailable_reason` non-None → `unavailable` with reason; pmid mismatch → `failed` (never filed under the wrong id); else `validate_identifiers` and write via temp name + replace, status `fetched`.
`--dry-run` prints copies to make, idconv/efetch request counts, writes nothing. OK/COPY/SKIP/FAIL lines plus a closing "unavailable by reason" table.

**`run [--dry-run] [--limit N] [--only PMID...] [--force] [--reuse-benchmark VERSION (default assay_result_v3) | --no-reuse-benchmark] [--paper-timeout S (1800)] [--max-usd X]`**

Startup reassigns module globals (the `use_result_version` pattern):
```python
assay_service.XML_ROOT = immport_corpus.XML_DIR
assay_service.PDF_ROOT = immport_corpus.CORPUS_DIR / "no_pdf"   # absent: PDF route off
assay_service.REGISTRY_ROOT = immport_corpus.REGISTRY_DIR
assay_service.CACHE_ROOT = immport_corpus.REGISTRY_DIR
```
With both roots equal and no PDF root, `registry_dir(pmid, primary_sdy)` resolves to `REGISTRY_DIR/<pmid>_<primary_sdy>` unconditionally; nothing under `data/31paper_assays` or `data/cache` can be written. `assay_ledger.record_run` (called inside `assay_report`, assay_service.py:896) appends rows with that `registry_dir`, which is how `status` separates corpus spend from benchmark spend.

Queue: `fetch_status in (fetched, benchmark_copy)` and `run_status != done` (or `--force`), `--only` filter, manifest order. Reuse pass first: `benchmark_registry` hit → `run_status=reused`, `registry_dir` → that folder, no call. Then `--limit N`.

`--dry-run`: queue length, reused count, `n × median` and `n × max` from `cost_per_paper(assay_ledger.read_rows())` (stating n rows measured), `n × seconds_per_paper`, "nothing called". Not `estimate_run` (cannot size a never-run paper).

Loop (sequential, per `run_assay_batch`'s rationale):
```
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, max_retries=5, timeout=600)
for each paper:
    tee stdout → console + LOG_DIR/<pmid>.log (truncate)
    try:
        result = await asyncio.wait_for(assay_report(pmid, primary_sdy, client, verify=True, correct=True), paper_timeout)
        report_result(result)
        record: done, calls=result["meta"]["llm_calls"], seconds, registry_dir,
                usd = newest ledger row for this pmid dated ≥ t0, flags = count_report_lines(log)
    except Exception as exc:        # incl. asyncio.TimeoutError
        record: failed, run_error=f"{type(exc).__name__}: {exc}"; continue
    write_manifest()
    if --max-usd and spent_this_run > max: stop
```
Tranche end → `LOG_DIR/tranche_<ts>.txt` + stdout: done/reused/failed/skipped, calls, $ this run (ledger), flags totalled by prefix, every failed paper with its error, and every paper with any WARNING/REVIEW/JUDGED/REJECT/DROPPED/MINORITY/VOTE/MERGED > 0 with counts and log path (lines are indexed, not summarised away).

Client built in the script (not `claim_parser._get_client()`, SDK-default 2 retries): `max_retries=5` lets SDK backoff absorb 429/5xx over a long run. `assay_obi_mapper`'s own sync clients unchanged (noted). `failed` papers are retried only under `--only`/`--force`.

**`status [--failed] [--unavailable] [--json]`** — manifest + ledger, after `resolve_manifest_from_disk`:
```
PMIDs usable 1313 (shared by >1 study 117); unusable study_pubmed rows 28
fetch: fetched N, benchmark_copy 36, no_pmc 71, unavailable M (by reason), failed F, pending P
run:   done D, reused R, failed F, pending P
spend: $X over D runs (ledger rows under data/immport_assays/registries), median $m/paper, remaining ≈ P × $m
flags: WARNING n, REVIEW n, JUDGED n, REJECT n, DROPPED n, MINORITY n, VOTE n, MERGED n, UNMAPPED n
```

### B2. `.gitignore`
Add `data/JAT_XML_immport/`, `data/immport_assays/registries/`, `data/immport_assays/logs/` with one-line comments (vaccine1000 entry is the model). Manifest stays tracked.

### B3. No changes to `assay_service`, `jats_fetcher`, `download_pmc_corpus`, `run_assay_batch`, `assay_ledger`
Everything needed is module-level and read at call time. The benchmark copy in `fetch` avoids adding a two-root lookup to `locate_paper_xml`.

## Tests (`apps/api/tests/`, run from `apps/api`: `../../.venv/bin/python -m pytest`)

`test_immport_corpus.py` (no DB, no network): `group_papers` routing of "TBD"/"Not Applicable"/"PMC…"/"PMID: 123" rows; `primary_sdy` numeric order; manifest round-trip and atomic write (old file intact when `json.dumps` raises); `merge_enumeration` preserves fetch/run fields; `parse_idconv` with pmcid/error/int-pmid records; `benchmark_registry` ignores `_pdf` and finds a non-primary study's folder; `count_report_lines` (`DROPPED ALIAS`→DROPPED, `REVIEW  not folded`→REVIEW, indented `JUDGED`, `OBI FAILED` not double-counted); `cost_per_paper` median and fallback; `resolve_manifest_from_disk` both directions.

`test_run_immport_assays.py` (importlib loader like `test_run_assay_batch.py:16`; monkeypatch `immport_corpus.*` paths to tmp): `fetch` with stubbed `fetch_batch` (reuse `test_pmc_corpus.py` articleset fixture) and idconv GET → filenames, statuses/reasons, benchmark XML copied not fetched, resume, `--dry-run` makes no request, `RequestException` → `failed` and next batch runs. `run` with `_fake_report`-style stub writing into `assay_service.registry_dir` → lands under tmp `REGISTRY_DIR`; a same-named folder under original `REGISTRY_ROOT` is not touched (overwrite guard); raising paper → `failed`, queue continues; `--limit 1`; reuse → `reused`, no call; `--no-reuse-benchmark`; `--force`; `--dry-run` prints `n × median` from stubbed ledger; `<pmid>.log` content and `flags`; `--max-usd` stops; stub sleeping past `--paper-timeout` → `failed`. `status` counts on a hand-built manifest.

## Verification

1. `pytest` from `apps/api` green (new + existing).
2. `python3 scripts/run_immport_assays.py enumerate` → 1,313 usable / 28 unusable; `git diff --stat data/immport_assays/manifest.jsonl`.
3. `fetch --dry-run` → request counts; `fetch` (free; ~7 idconv + ~25 efetch requests); `status`.
4. `run --dry-run --limit 20` → `20 × $0.40 ≈ $8`; **wait for go-ahead**.
5. Pilot `run --limit 20` → `status`, tranche summary; compare median $/paper and s/paper to the ledger; re-run `run --dry-run` so the remainder is projected from 22 rows.
6. Diff check: only Part A/B files, `.gitignore`, the manifest, tests, docs.

## Execution plan and cost

- Runnable ≈ 1,242 minus unavailable (unknown until `fetch`) minus 27 reused benchmark papers ≈ **1,100–1,200 papers**. At $0.36–$0.40: **≈ $400–$480**. At 2–3 min/paper sequential: **≈ 40–60 h** wall-clock.
- Order with go-ahead points (CLAUDE.md): enumerate → fetch → `run --dry-run --limit 20` → **go-ahead** → pilot 20 (~$8, ~1 h) → review summary + flags → **go-ahead** → tranches of `--limit 100` (~$40, ~4–5 h, ~11 tranches), each preceded by `run --dry-run --limit 100` and followed by `status`. If the pilot median holds, optionally 250-paper overnight tranches with `--max-usd 110` as backstop.
- Resumability: Ctrl-C/crash loses at most the in-flight paper (no `assays_benchmark.json`, manifest still pending); next `run` resumes.

## Docs

- `docs/plan/immport_assay_corpus_plan.md` — this plan (per the generated-docs rule; written as the first implementation step).
- CLAUDE.md "Paper / LLM Runs": one paragraph naming `scripts/run_immport_assays.py` as the corpus runner (it is `assay_report` per paper, the voted chain, nothing new), the `--dry-run` + go-ahead rule per tranche, and where manifest/registries/logs live.

## Out of scope / deferred

- PDF route for the 71 no-PMC papers and the unavailable ones; the 4 `_pdf` benchmark registries are not reused.
- Running papers in parallel; OpenAI Batch API; lowering reasoning effort.
- Retries/timeouts on `assay_obi_mapper`'s sync clients; recording embedding usage.
- Linking corpus registries to ImmPort experiment rows (`build_immport_coverage.py`), the corpus table, the web UI.
- Reconciling primary-SDY filename with the benchmark's filing study for reused papers (manifest records both; nothing renamed).

## Critical files
- `apps/api/app/agent/assay_service.py` (roots 94–105, locate_paper_xml 162–181, registry_dir 297–315, assay_report 822–897)
- `scripts/run_assay_batch.py` (loop shape, done_path, dry_run)
- `scripts/download_pmc_corpus.py` (fetch_batch 165, split_articleset 180, article_record 200, _params, request_delay)
- `apps/api/app/agent/paper_resolver.py` (normalize_row_pmid 109)
- `apps/api/app/agent/jats_fetcher.py` (unavailable_reason, validate_identifiers)
- `apps/api/tests/test_run_assay_batch.py`, `apps/api/tests/test_pmc_corpus.py` (test patterns)
