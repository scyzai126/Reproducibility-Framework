---
name: extract-data-repos
description: Find which data repositories hold a paper's own data (GEO, SRA, ImmPort, dbGaP, Zenodo, ...) and link to them, with this repo's data-availability pipeline. Use when the user asks where a paper's data lives, for its data repository, accession or deposited dataset, for its data availability statement, or to run this over one paper or the 31-paper benchmark corpus.
---

# Extract a paper's data repositories

`scripts/run_data_availability.py` separates a paper's **own deposited data** from data it reused
or only cited, checks each repository, and links to where the data sits. The step code is in
`apps/api/app/agent/data_availability.py`, and `data_availability_service.py` runs it for one
paper (the Extract tab calls that too).

## Pipeline, per paper

| Step | What | Cost |
|---|---|---|
| 1. Candidates | Regex finds every accession outside the reference list, with its sentence and the sentences either side. It records whether the Data Availability (DA) statement names each one: `in_da`, and `da_source` = `section` / `inline_label`. | free |
| 2. LLM judge | The model reads the full paper text plus each ID with its sentences and DA flag. For each ID it answers whether it is a real accession, whether the DA statement names it (its own reading), and its role: `this_study` / `public_data` / `reference` / `registration`. The prompt is `classify_data_availability.txt`. | **1 call per paper**, none if the paper names no ID |
| 3. Validate | Asks each repository whether the ID exists and which PMID owns it, and adds datasets the repository links to this PMID that the text never names. ImmPort IDs are checked against the local MySQL. | free (network) |
| 4. Combine | The LLM's role is final. Disagreements with the DA statement or the repository become `REVIEW` lines. | free |
| 5. Locate | For deposited, verified data: finds the landing page, download folder, file count and size. It lists files but never downloads them. | free (network) |

## Workflow

### 1. Pick the input
- One paper: `data/JAT_XML/<SDY>_<PMID>.xml` (preferred), or `data/pdf/**/<SDY>_<PMID>.pdf`.
- The benchmark: `--all`, the 31 papers in `data/31paper_assays/` (XML preferred, PDF fallback).
- A custom list: pass the paths through `xargs`, because zsh does not word-split `$VAR`:
  `xargs python3 scripts/run_data_availability.py < papers.txt`

### 2. Dry run first (free), then wait
```bash
python3 scripts/run_data_availability.py data/JAT_XML/SDY2189_34252919.xml --dry-run
python3 scripts/run_data_availability.py --all --dry-run
```
It reports the LLM calls, approximate input tokens, and the number of IDs found in the DA
statement per paper. It makes no network call and writes no files. **Wait for the user's
go-ahead** before the paid run. As a guide, one paper is roughly 10–30k tokens and all 31 are
about 450k.

### 3. The paid run
The same command without `--dry-run`. Run it in the background for many papers and capture the
log.
- `--no-validate` skips the repository lookups.
- `--no-locate` skips step 5.

### 4. Outputs
These go in `data/benchmark_assay/data_availability/` and are overwritten in place.
- **`<SDY>_<PMID>_llm.json`**: written before validation. It has every ID with its evidence
  sentences (each flagged `in_da`), `in_da_section`, `da_source`, `llm_in_da`, and the LLM's
  answer, sorted into `deposited` / `reused` / `referenced` / `registration` / `unclear`. It
  also has the DA statement, the DA-only `reviews`, `dropped` and `warnings`.
- **`<SDY>_<PMID>.json`**: the final answer, and only this study's own data.
  - `data_repositories[]`: `accession`, `repository`, `landing_page`, `download` (https/ftp),
    `access`, `file_count`, `total_size_bytes`, `status`, `owner_pmids`, `found_by` (`text` or
    `repository_link`), and `review`.
  - `unconfirmed[]`: deposited IDs the repository could not confirm, with `status` and `detail`.
  - Code repositories and reused, referenced or registration IDs stay in the `_llm` file.
- **`summary.md`**: a roll-up table, written only for multi-paper runs, and covering only the
  papers in that run.
- **Web app:** the Assays page's Corpus table reads the final files through
  `GET /agent/data-availability/corpus` and shows them in its Data availability column.

### 5. Report
- Every `REVIEW`, `DROPPED`, `WARNING`, `NOTE`, `UNCONFIRMED` and `SKIPPED` line, verbatim,
  grouped by paper.
- A table of paper → data repositories (with links) / unconfirmed / none.
- For each flagged line, say whether it's a real problem or noise.

## Known caveats
- **Transient NCBI errors** (HTTP 500) leave real GEO IDs `unconfirmed`. Re-running is free
  for a paper that made no LLM call; otherwise it costs that paper's one call.
- **The paper's own ImmPort study** shows up only when the text names it, or the repository
  links it to the PMID. It is often missing.
- **DA-mismatch reviews** ("the model reads it as in the DA statement; the pattern search found
  it outside it") are mostly noise on papers with no detected DA statement.
- **Sentence splitting** is local to this pipeline. It breaks after a closing quote and skips
  abbreviations like "Fig." and "et al.". The global `jats_parser.SENTENCE_SPLIT` is left alone
  because assay/claim `sentence_ids` depend on it.
- **Old-format files:** a final file without `data_repositories` is from before the two-file
  split. Re-run that paper to refresh it.
