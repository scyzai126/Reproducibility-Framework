# Assay workflow review, second pass (2026-10-30)

Follows `assay_workflow_review_2026-10-30_vote.md` (order-independent clustering, free alias
drop, docstrings). This pass read every round's code, the three prompts and the CLI again, and
measured each suspicion against the stored v3 replies (`assay_result_v3/*/assays_raw.json`). No
API call was made. Everything below is implemented on `feature/obi-repick-fulllist`, uncommitted.

## Findings and what changed

### 1. The vote's field fallbacks still depended on run order (fixed)

Pass 1 made cluster *membership* rotation-invariant and checked that (0 of 31 papers differ in
delivered count or minority set). Field values were not checked. Inside `_merge`, every "nothing
agrees" fallback read `values[0]`, i.e. whichever member sat in slot run1: name, quote,
`generate_claim` (`_vote`) and the three free-text fields (`_vote_text`, when no pair agrees or
on an equal-score tie). Rotating each delivered cluster's members: **22 of 178 delivered clusters
in 16 papers** changed at least one field with run order.

Pass 1 had made this worse: a lone entry attached in tier 2 is the dissenting run, and it sat in
slot run1 whenever it came from run1, so it won every fallback. SDY212: run1's lone "Tetramer
staining" quoted a Figure caption about viral titer; run2 and run3 named the assay alike and each
quoted a different Methods sentence; no quote had a majority, and in stored order the caption
would have been delivered. `generate_claim` flipped True/False/None by order on SDY984 nested PCR
and SDY1991 neutralization.

**Change** (`assay_consensus.consensus`, `_anchor_rank`): a cluster's members are ordered by
content before voting, never by slot: first-tier members before an attached one; then the member
whose quote the paper places in Methods, then one placed anywhere, then one not found; then the
longest quote (among sentences placed alike the fuller one pins the assay, the shorter is more
often "as described previously"); then the whole entry. Every fallback reads the first member, so
an entry nobody agreed on is one coherent write-up. `_vote`, `_vote_text` and `_merge` are
unchanged.

| check on the v3 replies | before | after |
|---|---|---|
| papers whose delivered registry differs across the 3 rotations, any field | 16 (22 clusters) | 0 |
| delivered entries whose value differs from the stored v3 extraction | | readouts 3, name 1, generate_claim 1, alias list 10 |

The alias-list differences are the attached members' wordings pass 1 already admitted plus the
name fallback moving one wording between name and aliases (SDY180 "Hemagglutinin Inhibition" /
"... assay").

### 2. A single-call extraction path still existed (removed, user decision)

`scripts/run_assay_extract.py` made one `extract_assays` call and wrote `assays.json` directly:
no vote, no verification, indistinguishable on disk from a finished registry, which is exactly
what CLAUDE.md forbids ("there is no single-call extraction path and none is to be reintroduced").
`scripts/run_assay_verify.py` re-ran round 2 alone and overwrote `assays_verification.json`,
leaving it inconsistent with the stored corrections; `scripts/run_assay_correct.py --promote`
copied `assays_corrected.json` over the canonical `assays.json`, skipping rounds 4 and 5 so the
registry, `assays_OBI.json` and `assays_benchmark.json` no longer agreed. None had a test.

**Change**: the three scripts are deleted. `scripts/run_claim_assay_link.py`, the one live
dependency, now uses `assay_service.split_stem`, `locate_paper_xml` and `paper_source_text`.
`assay_corrector.promote_registry`, which only the deleted script called, is removed with its
three tests. The entry points are now `run_assay_pipeline.py`, `run_assay_batch.py` and
`run_assay_merge.py` only.

### 3. The API result's `contract_warnings` described the wrong registry (fixed)

`_run_rounds` computed the warnings after round 1 (pre-correction, keyed by the extractor's
wording, without the OBI mapping) and returned that list. The CLI recomputed on the final registry
and ignored it, but the web UI (`apps/web/src/lib/findings.ts`) renders the returned one, so it
showed "quote could not be located" for a quote round 3 then repaired, under a key round 5 had
replaced. Now computed once, on the delivered registry with the mapping, the same call the CLI
makes. Test: a run whose only gap is repaired by round 3 returns no warning.

### 4. REVIEW lines now say what round 3 did (CLI)

Each unsupported field printed under a REVIEW record was a pre-correction verdict with no
outcome; in v3, 40 fields were re-extracted (REPLACED 32, REAFFIRMED 5, CLEARED 2, UNCHANGED 1)
and the terminal could not tell a settled doubt from a replaced, never re-judged value. Each
line now ends `→ round 3: REPLACED` / `REAFFIRMED` / `CLEARED` / `UNCHANGED (note)` /
`ERROR: ...`, or `not correctable` for the identity. The web findings panel was left as is.

### 5. Docstring drift, second batch (text only)

`assay_extractor.py` ("in one LLM call", "ten-field", run_assay_extract), `assay_extractor_pdf.py`
("one LLM call", "ten fields"), `assay_merger.py` ("single whole-paper call", `platform`),
`assay_verifier.py`, `assay_service.py` and `assay_registry.py` (references to the deleted
scripts), `run_assay_pipeline.py`, and `prompts/correct_assay_field.txt`, a live prompt that still
told the corrector `platform` "invites this most".

## Checked and fine (measured)

- **Abstract handling**: 0 delivered quotes in v3 are located outside Methods while another
  verbatim occurrence sits in Methods, so `locate_sentence_ids` taking the first occurrence
  misfiles nothing today. An abstract-only quote reading `source: results` stays latent (none).
- Quote check case sensitivity: 1 `missing` quote in v3, not recoverable case-insensitively.
- Same-run duplicate normalized names (tier 1 would merge them silently): 0 in 93 replies.
- XML and PDF extraction prompts: shared sections identical.
- Blocked folds: 21 in v3 (readouts 13, sample_type 6, technique 2: CPE vs PRNT, Luminex vs
  CBA, both legitimate). Adjudication stays open.
- `check_source_section` is tautological on a fresh run (source is derived from the same ids)
  but meaningful on `stored_registry` after an XML re-fetch, so it stays.

## Verification

- Touched test files: 101 passed (consensus, service, CLI); corrector and route tests pass.
- Full backend suite: 1305 passed, 2 skipped, 10 failed; the 10 are pre-existing on HEAD
  (`test_experiment_resolver`, `test_file_reader`, `test_input_routing`, `test_query_builder`)
  and unrelated to the assay chain.
- `--dry-run` on SDY1260 prints the same estimate as before; `run_claim_assay_link.py --help` imports.

## Still open

Blocked-fold adjudication, re-verifying REPLACED values with a call, atomic output across rounds
2-5, PDF-route sentence numbering, scoring `generate_claim`, decorrelating round 1,
`source: abstract`, the web findings panel's REVIEW lines (same gap as finding 4).
