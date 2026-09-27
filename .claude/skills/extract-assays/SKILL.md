---
name: extract-assays
description: Extract the assays a paper used, verified and mapped to OBI terms, with this repo's assay pipeline. Use when the user asks what assays a paper used, asks to extract / verify / correct / map a paper's assays to OBI, or wants assays_benchmark.json for a paper given by PMID, ImmPort SDY, or a data/31paper_assays/<PMID>_<SDY> folder.
---

# Extract a paper's assays

One command runs the whole chain: extract → verify → correct → promote → map to OBI → canonicalize.
It is `scripts/run_assay_pipeline.py`, the same code `POST /agent/assays` and the Extract tab run.

## Why it is one chain

An unverified registry looks exactly like a verified one when you read it. So **never stop after
round 1 (extraction)**: run the chain end to end, or don't run it.

| Round | What | Cost |
|---|---|---|
| 1 | `prompts/extract_assays.txt` (XML) or `extract_assays_pdf.txt` (PDF fallback) builds the registry | 1 call |
| 2 | `verify_assays.txt` judges every entry | 1 call per assay |
| 3 | `correct_assay_field.txt` repairs what round 2 refused, then promotes | 1 call per flagged field |
| 4 | `resolver_obi_assay.txt` maps each name to an OBI term (an exact vocabulary match is free) | 2–3 calls per unmatched name |
| 5 | Canonicalize: key by OBI label, fold duplicates | free |

Nothing is reused between runs: re-running a paper pays for every round again.

## Workflow

### 1. Identify the paper
- By IDs: `--pmid <PMID> --sdy <SDY>`
- By folder: `data/31paper_assays/<PMID>_<SDY>` (a `_pdf` suffix means the paper has no JATS XML)

### 2. Dry run first (free), then wait
```bash
python3 scripts/run_assay_pipeline.py --pmid 34252919 --sdy SDY2189 --dry-run
# or
python3 scripts/run_assay_pipeline.py data/31paper_assays/34252919_SDY2189 --dry-run
```
Report the projected call count per round and the source it will read (JATS XML or PDF).
**Stop and wait for the user's go-ahead** before the paid run. A 10-assay paper is 30+ calls.

### 3. The paid run
The same command without `--dry-run`. Run it in the background for large papers and read the
log when it finishes.

### 4. Report
- Every `WARNING`, `REVIEW`, `REJECT`, `DROPPED` and `MERGED` line the script prints, verbatim.
  Don't summarise them away.
- The assays found: OBI label → the paper's wording(s), and whether the paper reports a finding
  from each one (`generate_claim`).

### 5. Point at the right file
The deliverable is **`<registry_dir>/assays_benchmark.json`**, not `assays.json`.
- It is keyed by the assay's OBI label. An assay OBI has no term for keeps its paper name as the key.
- Each entry has exactly these fields:
  - `name_in_paper`: every wording the paper used, as a list.
  - `aliases`.
  - `generate_claim`: `true` / `false` / `null`. Whether the paper reports a finding from this
    assay. It is a label to compare against the benchmark, never a filter.
  - `source`: `methods` / `results`.
  - `evidence`: `section` / `sentence_ids` / `quote`.
  - `additional_evidence`: only on an entry that round 5 folded another one into.

`assays.json` holds the full record every round works from. `assays_OBI.json`,
`assays_verification.json`, `assays_corrections.json` and `assays_merges.json` sit beside it for
auditing.

## Notes
- **PDF fallback:** a paper with no JATS XML is read from its PDF. Its entries then have
  `sentence_ids: []`, and round 2 checks quotes against the whole document.
- **Re-parsing overwrites in place.** Don't keep a timestamped copy unless the user asks for one.
- **Old registries:** to canonicalize a registry built before round 5 existed, run
  `python3 scripts/run_assay_merge.py <registry_dir>`. It makes no calls; add `--dry-run` to
  preview it.
- **Older fields:** a registry from before `generate_claim` existed reads it as `null`. The
  removed fields `platform`, `measurement_role` and `parent_hint` may still be on disk, and every
  reader tolerates them.
- **Corpus view:** the web app's Assays page, Corpus tab, shows every paper's assays.
