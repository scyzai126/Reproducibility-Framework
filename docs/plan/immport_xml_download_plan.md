# ImmPort assay corpus — step 2: download every paper's XML into one folder

## Context

Step 1 (done, commit b31f105 on `feature/immport-assay-corpus`) wrote `/Volumes/Extreme SSD/HIPC papers/papers_all.csv`: 1,313 PMIDs, one row each, with every study the paper belongs to and a `primary_sdy`. The user now wants the full text of those papers downloaded, **XML first, all into one folder**, and **a separate list of the PMIDs that got XML**. Papers PMC cannot serve are listed with the reason so the PDF step can pick them up later. Free: NCBI only, no model calls.

Verified: 1,242 of the 1,313 have a PMC record (NCBI ID converter, this session); some of those will come back abstract-only or publisher-blocked, which only the efetch response reveals (`jats_fetcher.unavailable_reason`). 36 of the papers already have XML in `data/JAT_XML/<SDY>_<pmid>.xml`; copying those instead of refetching keeps the sentence numbering their existing registries cite.

Reusable code (no changes to it):
- `scripts/download_pmc_corpus.py`: `fetch_batch(session, pmcids)` (efetch POST, 50 ids, returns `<pmc-articleset>`), `split_articleset(xml)`, `article_record(xml)` (pmcid/pmid/title from `<front>` only), `_params(extra)` (tool/email/api_key), `request_delay()` (0.4 s, 0.11 s with `NCBI_API_KEY`), `EFETCH_URL`. Loaded the way `run_assay_batch.py` imports `run_assay_pipeline` (sys.path insert of `scripts/`).
- `apps/api/app/agent/jats_fetcher.py`: `unavailable_reason(xml, soup)`, `validate_identifiers(pmid, sdy)`.
- `apps/api/app/agent/immport_corpus.py`: `PAPERS_DIR`, `PAPER_COLUMNS`, `write_csv`, `STUDY_SEP`.
- NCBI ID converter `https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids=a,b,c&format=json` accepts up to 200 ids per request (`ncbi_utils.pmid_to_pmc_url` does one id per request with a process-local cache, so it is not used here).

## Deliverables (all under `/Volumes/Extreme SSD/HIPC papers/`)

```
xml/<primary_sdy>_<pmid>.xml   every full text PMC served, one folder (the name the assay pipeline reads)
papers_xml.csv                 pmid, study_accessions, primary_sdy, pmcid, file, bytes   — papers WITH xml
papers_no_xml.csv              pmid, study_accessions, primary_sdy, pmcid, reason        — papers without (→ PDF step)
```
Every PMID of `papers_all.csv` lands in exactly one of the two lists. Both lists are rebuilt from disk + this run's outcomes on every invocation, so a resumed run yields complete lists.

## Implementation

### 1. `apps/api/app/agent/immport_corpus.py` — additions

- Constants: `XML_DIR_NAME = "xml"`, `PAPERS_XML_NAME`, `PAPERS_NO_XML_NAME`, `XML_COLUMNS`, `NO_XML_COLUMNS`, `IDCONV_URL`, `IDCONV_BATCH = 200`.
- `read_papers(path) -> list[dict]` — `papers_all.csv` rows with `studies` split on `STUDY_SEP`.
- `xml_name(primary_sdy, pmid) -> str` — `<SDY>_<pmid>.xml`, after `validate_identifiers`.
- `existing_xml(xml_dir) -> dict[str, Path]` — `{pmid: path}` for files already in the folder (parse the stem with `assay_service.split_stem`), ignoring macOS `._*` AppleDouble files the ExFAT drive grows.
- `parse_idconv(payload) -> dict[str, str | None]` — idconv JSON `records[]` → `{str(pmid): pmcid or None}` (pmid comes back as int for some records; an `errmsg`/`status: error` record is None).
- `benchmark_xml(pmid, studies, xml_root=None) -> Path | None` — the paper's file under `assay_service.XML_ROOT` for any of its studies.

### 2. `scripts/download_immport_xml.py` (new)

```
python3 scripts/download_immport_xml.py [--papers-dir "/Volumes/Extreme SSD/HIPC papers"]
                                        [--dry-run] [--limit N] [--force] [--retry-failed]
```
Sync `requests.Session`. Steps:
1. Read `papers_all.csv`; refuse to run if the dir does not exist. `xml/` is created under it.
2. **Resume**: PMIDs with a file in `xml/` are SKIP (unless `--force`). A `papers_no_xml.csv` from a previous run is read so papers already known as `no PMC record` / `abstract-only` / `publisher-blocked` are not re-asked unless `--retry-failed` (transport failures are always retried).
3. **Benchmark copy**: `benchmark_xml` found → `shutil.copyfile` into `xml/<primary_sdy>_<pmid>.xml`, line `COPY`.
4. **ID conversion**: remaining PMIDs in chunks of 200 → `parse_idconv`; no pmcid → outcome `no open-access PubMed Central record`.
5. **Fetch**: PMCIDs in chunks of 50 via `fetch_batch` → `split_articleset` → `article_record`, keyed by pmcid. Per requested paper: not returned → `PubMed Central returned no article for it`; `unavailable_reason` → that reason; returned `pmid` ≠ requested → `failed: idconv/efetch pmid mismatch` (never filed under the wrong id); else write via `<name>.tmp` + `os.replace`, line `OK`.
6. `requests.RequestException` on a batch marks each of its papers `failed: request failed: …` and the next batch still runs.
7. After every batch, rebuild and write both CSVs (`write_csv`), so Ctrl-C loses nothing already fetched.
8. Summary: fetched / copied / skipped / no xml by reason; the two list paths; a reminder that `papers_no_xml.csv` is the PDF step's input.

`--dry-run`: reads the list and the folder, prints how many would be copied, how many need idconv (→ ⌈n/200⌉ requests), how many would be fetched (→ ⌈n/50⌉ requests), writes nothing, calls nothing. `--limit N` caps the number of papers fetched this run (for a first small test). Honors `NCBI_API_KEY` / `NCBI_EMAIL` via `_params` like the corpus downloader.

Lines: `OK    <pmid>  -> <file>  (<chars>)`, `COPY  <pmid>  <- data/JAT_XML/<file>`, `SKIP  <pmid>  already in xml/`, `FAIL  <pmid>  <reason>`.

### 3. Tests

- `apps/api/tests/test_immport_corpus.py` — add: `read_papers` splits studies; `xml_name` validates; `existing_xml` ignores `._` files and reads both stem orders; `parse_idconv` on pmcid / error / int-pmid records; `benchmark_xml` finds a non-primary study's file.
- `apps/api/tests/test_download_immport_xml.py` (new; importlib loader like `test_pmc_corpus.py`): stub the idconv GET (canned payload with one no-PMC id) and `fetch_batch` with a hand-built articleset reusing `test_pmc_corpus`'s `_article` shape (good article, abstract-only, requested-but-missing, pmid mismatch). Assert: files named `<SDY>_<pmid>.xml`; `papers_xml.csv` + `papers_no_xml.csv` partition the input with the right reasons; a benchmark XML is copied, not fetched (stub asserts it was never asked); a paper already in `xml/` is skipped; `--dry-run` writes nothing and makes no request; a `RequestException` batch is marked failed and the next batch runs; `--limit 1` fetches one; `--retry-failed` re-asks a known-unavailable paper.

### 4. Nothing else changes. No `.gitignore` entry (everything lands on the SSD).

## Verification

1. `cd apps/api && ../../.venv/bin/python -m pytest tests/test_immport_corpus.py tests/test_download_immport_xml.py -q` green; full suite still only the 10 known subject-query failures.
2. `.venv/bin/python scripts/download_immport_xml.py --dry-run` → ~36 copies, ~1,277 idconv (7 requests), then fetch count.
3. `.venv/bin/python scripts/download_immport_xml.py --limit 20` → inspect 20 `OK` lines and the two CSVs.
4. Full run (~7 idconv + ~25 efetch requests; a few minutes). Then:
   - `ls "/Volumes/Extreme SSD/HIPC papers/xml" | grep -vc '^\._'` equals the data-row count of `papers_xml.csv`;
   - rows of `papers_xml.csv` + rows of `papers_no_xml.csv` = 1,313; no PMID in both (`cut -d, -f1 | sort | uniq -d`);
   - the "no xml by reason" table in the summary is reported to the user as-is.
5. Commit on `feature/immport-assay-corpus`; copy this plan to `docs/plan/immport_xml_download_plan.md`.

## Later steps

- **Step 3**: PDFs for `papers_no_xml.csv` into `HIPC papers/pdf/` (hand-collected; the repo's `data/pdf/15papers` has 5 of the known PMC-unavailable ones).
- **Step 4**: the assay run over `xml/` into `HIPC result/<pmid>_<SDY>/`, tranches with `--dry-run` + go-ahead each (design in `docs/plan/immport_assay_corpus_plan.md`, to be re-pointed at the SSD paths).
