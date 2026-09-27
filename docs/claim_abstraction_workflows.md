# Claim abstraction: the two workflows

Both workflows take a paper's JATS XML (`data/JAT_XML/<SDY>_<PMID>.xml`) and produce reproduction-ready
claims. Both use the same extraction prompt, `apps/api/app/prompts/claim_abstraction_prompt_v8.md`,
and the same claim-type vocabulary, `claim_types.txt`. They differ in how they make the result
reliable:

- **Current (v8):** repeat the extraction and keep the most common result.
- **v9:** extract once, then check and fix each claim, the way the assay pipeline does.

---

## 1. Current workflow (v8): sampling

**Run:** `python3 scripts/run_claim_doc.py <xml> <out_dir> [--runs 5] [--audit]`, then
`scripts/run_claim_filter.py <out_dir>` and `scripts/run_groups_noassay.py`.
**Code:** `apps/api/app/agent/claim_abstraction_v5.py`

```
XML → split into  prose (Abstract + Results + Methods)  |  legends (all figure/table captions)

Pass 1  prose only           → draft claims        5 calls at temperature 1.0, keep the modal count
Pass 2  draft + all legends  → reconciled claims   5 calls at temperature 1.0, keep the modal count
Pass 3  claims + legends     → provenance audit    1 call   (a "demote" verdict removes the claim)
Pass 4  abstract + claims    → coverage report     1 call   (report only)
Pass 5  claim set            → merge/naming ideas  1 call   (report only)
                                                   ───────
                                                   13 calls
→ claims.json  (claim, claim_type, assay_method_in_paper, sources)
→ claim_filter (free) → claim_filtered.json
→ classify_groups (1 call per claim) → claims_groups.json
```

**How "keep the modal count" works:** each sampled pass runs 5 times. Code counts the claims in each
reply, finds the most common count, and keeps the first reply with that count. The other 4 replies
are discarded. It steadies how many claims come out, but never checks whether they are right.

**Known gaps:**
- `polarity`, the contrast, targets and timepoints are dropped when `claims.json` is written.
- Pass 5's proposed merges and naming fixes are never applied.
- The optional judge `scripts/run_claim_validate.py` (`claim_validator.py`) runs separately. It is
  closed-book, and its metadata check needs the PDF.

---

## 2. v9: extract once, then verify → correct

**Run:** `python3 scripts/run_claim_pipeline.py <xml> <out_dir> [--dry-run] [--audit]`
**Code:** `apps/api/app/agent/claim_pipeline.py`, `claim_verifier.py`, `claim_corrector.py`
**New prompts:** `apps/api/app/prompts/claims_v9/verify_claim.txt`, `correct_claim_field.txt`

```
1. Extract       the same 5 passes, one call each (temperature 0)            5 calls
2. Free checks   no LLM: quote verbatim in paper, claim_type in vocabulary,
                 polarity is affirm/null, claim has its "… showed" head
3. Verify        1 call per claim, reading the whole paper                   ~N calls
                 per-field verdict SUPPORTED / NOT_SUPPORTED / CONTRADICTED on:
                 finding, claim_type, polarity, assay, sample_type,
                 head metadata, each source quote
                 record verdict (derived in code): ACCEPT / REVIEW / REJECT
4. Drop          REJECT (not a claim) → not_a_claim.json, kept recoverable
5. Correct       1 call per flagged field, BLIND (never shown the rejected   ~flagged calls
                 value) → REAFFIRMED / REPLACED / CLEARED / UNCHANGED
                 finding CLEARED → claim dropped; head metadata only reported
6. Filter        claim_filter on the corrected claim types (free)
```

**Outputs:** `claims_precorrection.json`, `claims_verification.json`, `claims_corrections.json`,
`claims.json` (which now keeps `polarity`), `claim_filtered.json`, `not_a_claim.json`, and with
`--audit`, `claims_v9_audit.json`.

**Cost:** 5 + N claims + flagged fields. For SDY1364 that was 26 calls.

---

## 3. Side by side

| | Current (v8) | v9 |
|---|---|---|
| How it gets reliability | 5 samples per extraction pass, keep modal count | 1 extraction, then verify and blind-correct each claim |
| Checks claim content? | No | Yes, per field, against the whole paper |
| Fixes errors? | No | Yes, flagged fields are re-extracted blind |
| Removes non-claims? | Only pass 3 provenance demotions | Also REJECT (e.g. raw-data readings) and cleared findings |
| Keeps polarity in output | No | Yes |
| Audit trail | Claim-count tally | Verdict per field + action per correction |
| Can catch duplicates / under-split claims? | No | No (each claim is checked alone) |
| Can recover a claim never extracted? | No | No |
| Calls (SDY1364) | 13 | 26 |
| Tokens (SDY1364) | 287k | 282k (189k of it verification) |

---

## 4. Result on the SDY1364 benchmark

Benchmark: `data/benchmark_claim/claims_filtered_gs.json` (10 claims). One run each.
Details: `data/experiments/sdy1364_sampling_vs_verify/results.md`.

| | Current (v8) | 1 run, no fixes | v9 |
|---|---|---|---|
| Benchmark claims found | **10/10** | 8/10 | **10/10** |
| Claims matching the benchmark | **10 of 14** | 8 of 15 | 8 of 14 |
| Precision, counting real findings the benchmark lacks | **0.93** | 0.73 | 0.79 |

**Takeaway:** on this paper the current workflow is still better. v9 matched its recall, but it
made more errors (a duplicate, an under-split claim and a distorted claim). All three passed
verification. v9's fixes improved the evidence quotes but did not change any scored result. This
is one paper; SDY1260 (87-assertion benchmark) would be the next test.
