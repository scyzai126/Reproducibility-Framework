# ImmPort assay corpus — step 1: the full paper list

## Context

Goal (unchanged): assay registries for every paper linked to an ImmPort study, claims out of scope. The user wants to proceed in steps. **This step is only the list**: every PMID in ImmPort, deduplicated, written to the external drive. The XML/PDF split (needs PMC downloads) and the assay run come after, as separate steps.

Verified this session:
- Local MySQL mirror `immport_dr62`, table `study_pubmed`: 1,562 rows → **1,313 usable distinct PMIDs**; 28 rows unusable ("TBD", "Not Applicable", PMC ids, "PMID:" labels). 117 PMIDs belong to >1 study (max 27 studies for one PMID), so one row per PMID with all its studies is what "no duplicates" means.
- `apps/api/app/agent/paper_resolver.py:109 normalize_row_pmid(value) -> (pmid, unusable_reason)` already cleans one `study_pubmed.pubmed_id` value. Reuse it, do not copy it.
- Destination `/Volumes/Extreme SSD/HIPC papers/` exists and is empty (ExFAT, 1.9 TB free). `HIPC result/` also exists, reserved for the later assay run.
- Script bootstrap pattern: `scripts/run_assay_batch.py` (sys.path insert of `apps/api`). DB access pattern: `app.database.async_session()` with `sqlalchemy.text`, as `paper_resolver` does; no LIMIT.

## Deliverable

`/Volumes/Extreme SSD/HIPC papers/papers_all.csv` — one row per PMID, sorted by PMID, columns:

| column | meaning |
|---|---|
| `pmid` | PubMed ID (digits only) |
| `study_accessions` | every study the PMID is linked to, `;`-separated, sorted numerically (`SDY80;SDY1119`) |
| `primary_sdy` | the lowest-numbered study, used later to name `<SDY>_<pmid>.xml` |
| `n_studies` | count of studies |

Plus `/Volumes/Extreme SSD/HIPC papers/papers_unusable.csv` — the 28 rows that cannot name a paper: `study_accession`, `raw_value`, `reason` (from `normalize_row_pmid`), so nothing from the table is silently dropped.

Stdout summary: rows read, usable PMIDs, PMIDs shared by >1 study, unusable rows, output paths.

## Implementation

### 1. `apps/api/app/agent/immport_corpus.py` (new, small; grows in later steps)

Pure functions, no engine import:
- `async study_pubmed_rows(session) -> list[tuple[str, str]]` — `SELECT study_accession, pubmed_id FROM study_pubmed`.
- `group_papers(rows) -> tuple[dict[str, list[str]], list[dict]]` — `normalize_row_pmid` per row; usable → `{pmid: sorted studies}`; unusable → `[{study_accession, raw_value, reason}]`.
- `sdy_key(sdy) -> int` and `primary_sdy(studies) -> str` — numeric order (`SDY80` before `SDY1119`).
- `paper_rows(grouped) -> list[dict]` — the CSV rows above, sorted by int(pmid).
- `write_csv(path, rows, columns)` — write to `<name>.tmp` in the same directory, then `os.replace`.

### 2. `scripts/build_immport_paper_list.py` (new)

```
python3 scripts/build_immport_paper_list.py [--out-dir "/Volumes/Extreme SSD/HIPC papers"]
```
Default `--out-dir` is the SSD path. Exits with a clear message if the directory does not exist (drive not mounted) rather than creating it somewhere else. Opens `app.database.async_session()`, calls the module functions, writes the two CSVs, prints the summary. No model calls, no network.

### 3. Tests: `apps/api/tests/test_immport_corpus.py`

No DB: `group_papers` routes "TBD" / "Not Applicable" / "PMC1234567" / "PMID: 123" rows the way `normalize_row_pmid` does and groups a PMID across studies; `primary_sdy(["SDY1119","SDY80"]) == "SDY80"`; `paper_rows` joins studies with `;` and sorts by numeric PMID; `write_csv` leaves no `.tmp` and keeps the old file when writing raises.

### 4. `.gitignore`: nothing (outputs are on the SSD). No other files touched.

## Verification

1. From `apps/api`: `../../.venv/bin/python -m pytest tests/test_immport_corpus.py` green; full suite unchanged apart from the 10 known-red subject-query tests.
2. `.venv/bin/python scripts/build_immport_paper_list.py` → summary shows 1,313 usable / 28 unusable / 117 shared.
3. `wc -l` on `papers_all.csv` = 1,314 (header + 1,313); `cut -d, -f1 | sort | uniq -d` prints nothing (no duplicate PMIDs).

## Later steps (not in this step)

- **Step 2, split XML vs PDF**: bulk-fetch full text from PMC into `HIPC papers/xml/<SDY>_<pmid>.xml` (idconv 200/request, efetch 50/request, reusing `scripts/download_pmc_corpus.py` helpers and `jats_fetcher.unavailable_reason`); write `papers_xml.csv` and `papers_pdf.csv` (needs a PDF, with reason); `HIPC papers/pdf/` for hand-collected PDFs. Free.
- **Step 3, assay run**: `assay_report` per paper into `HIPC result/<pmid>_<SDY>/`, resumable, tranches with `--dry-run` and a go-ahead each (≈ $0.40/paper, ≈ $400–480 total, 40–60 h sequential). The earlier full design is in `docs/plan/immport_assay_corpus_plan.md`; its layout will be updated to the SSD paths when step 3 is planned.
- Branch: `feature/immport-assay-corpus`, cut from the current branch before any code.
