# v9 claim prompts: workflow

v9 has no extraction prompt of its own. Claims are extracted by the same
`apps/api/app/prompts/claim_abstraction_prompt_v8.md` as the current workflow, with one call per
pass. The two v9 prompts in `apps/api/app/prompts/claims_v9/` only check and fix those claims
afterwards:

```
v8 prompt (5 passes, 1 call each)  →  claims
        │
        ▼
verify_claim.txt          1 call per claim     "is each field right?"
        │   (claims judged "not a claim" are dropped)
        ▼
correct_claim_field.txt   1 call per flagged field   "what does the paper say?"
        │
        ▼
corrected claims → filter
```

Run with `python3 scripts/run_claim_pipeline.py <xml> <out_dir>`. The chain is in
`apps/api/app/agent/claim_pipeline.py`. Both prompts are modelled on the assay ones:
`verify_assays.txt` and `correct_assay_field.txt`.

---

## 1. `claims_v9/verify_claim.txt`: the checker

**Input:** the whole paper with each sentence numbered (`[S1] …`), followed by one claim and the
list of its fields to check. The paper goes first so the prompt cache can reuse it across claims.

### Step 1: is this a claim at all?
- **Real claim:** `SUPPORTED`. A finding of no difference still counts.
- **Unclear:** `NOT_SUPPORTED`.
- **Not a claim:** `CONTRADICTED`, with one reason:
  - `cited-background`
  - `definition`
  - `external-import`
  - `interpretation`
  - `not-executable`
  - `not-stated-in-words` (a value read off a figure or table that the authors never state)
  - `methods-statement`

### Step 2: each field gets SUPPORTED, NOT_SUPPORTED or CONTRADICTED

| Field | Rule |
|---|---|
| `finding` (the text after "showed") | Must be stated in Results or a legend, with no added comparator, direction or target. Spelling out "the two groups" as the actual group names is fine. |
| `claim_type` | Judged against `claim_types.txt` and its tie-break order. A change within one group over time is not `group_difference`. Two findings joined in one sentence should be split. |
| `polarity` | `affirm` if the paper reports the effect, `null` if it reports its absence. |
| `assay`, `sample_type` | Methods may be used, but the value must belong to this finding's data, not just appear nearby. |
| `head_metadata` (N, cohort, ages, days) | A value the opening doesn't mention is never a failure; only a stated value the paper contradicts is. |
| `sources[i].quote` | Does the quote support the finding? Whether it's copied exactly was already checked in code. |

### Step 3: output
JSON with each field's verdict, the exact text span it relied on, and a one-sentence reason. The
prompt must not suggest a corrected value.

### Code around the prompt (`claim_verifier.py`)
- **Before the call,** free checks with no LLM: every quote must appear word for word in the paper,
  the claim type must be in the vocabulary, polarity must be `affirm` or `null`, and the claim must
  contain "showed". A failed free check overrides the model's verdict on that field.
- **After the call,** code sets the claim's overall verdict from the field verdicts:
  - **REJECT** if it isn't a claim. It moves to `not_a_claim.json` and stays recoverable.
  - **REVIEW** if any field isn't `SUPPORTED`.
  - **ACCEPT** otherwise.

---

## 2. `claims_v9/correct_claim_field.txt`: the blind fixer

Runs once per flagged field. **Input:** the numbered paper, a description of the finding, and
one question. The rejected value is never shown.

| Field | What the finding description contains | Question asked |
|---|---|---|
| `finding` | the claim's source quotes | "What finding do the authors state in these sentences?" |
| `claim_type` | the finding + quotes | "Which vocabulary type names the operation?" |
| `polarity` | the finding + quotes | "Effect present or absent?" |
| `assay` / `sample_type` | quotes | "Which technique or specimen produced this finding?" |
| `sources` | the finding | "Which sentence states it? Quote it exactly." |

**Rules it follows:**
- Answer `null` rather than guess what's typical.
- A term in the same paragraph isn't evidence.
- The finding must be stated in words.
- Use only the paper.

**Output:** `{value, sentence_ids, reason}`.

### Code around the prompt (`claim_corrector.py`)
- **Same as the current value:** REAFFIRMED.
- **Different:** REPLACED.
  - For a finding, the claim keeps its opening and gets the new finding after "showed".
  - For an assay or sample type, the wording in the opening is updated too.
  - For a quote, the new one is only used if it appears word for word in the paper.
- **Null:** CLEARED. A cleared finding means the paper doesn't state it, so the claim is dropped.
- **Never corrected:** `head_metadata` is only reported, because it bundles several values into
  one sentence.

---

See also `docs/claim_abstraction_workflows.md` for the comparison with the current workflow and
the SDY1364 benchmark result.
