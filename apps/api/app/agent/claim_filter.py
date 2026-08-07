"""Select the claim types that carry forward into downstream reproduction work.

Claim extraction labels every claim with a `claim_type` from the closed vocabulary in
prompts/claim_types.txt. Only three of those types assert something reproducible against
ImmPort subject data — everything else (associations, predictive models, descriptive
statements) has no group/comparison structure to match subjects against, so it is filtered
out before group classification rather than paying an LLM call per claim for it.

Polarity is deliberately NOT a filter. A stated absence ("no significant difference between
arms") carries the type that names the operation plus `polarity: null`, and the verifier
runs that same operation either way — only the expected answer flips. Such claims used to
be typed `null_result` and dropped here; they now carry forward, so `filter_claims_for_
downstream` reports a polarity tally to keep the added volume visible.
"""

DOWNSTREAM_CLAIM_TYPES = ("induction_vs_reference", "group_difference", "extremum")

MISSING_TYPE_KEY = "(missing)"

MISSING_POLARITY_KEY = "(missing)"


def filter_claims_for_downstream(claims: dict) -> tuple[dict, dict, dict]:
    """Split claims into the downstream-actionable subset, a dropped-type tally, and a
    polarity tally over what was kept.

    Returns (kept, dropped_counts, kept_polarity). `kept` preserves the original claim keys
    and their order so every entry traces back to its claims.json counterpart, and each
    claim value passes through verbatim. `dropped_counts` maps each rejected claim_type to
    its count — an absent or null type lands under MISSING_TYPE_KEY, and an off-vocabulary
    value is counted under its own literal string. Nothing validates the model's emitted
    claim_type against the vocabulary, so that tally is how an invented value becomes
    visible; `kept_polarity` does the same job for polarity, whose only valid values are
    "affirm" and "null".
    """
    kept: dict = {}
    dropped: dict = {}
    kept_polarity: dict = {}
    for key, claim in claims.items():
        claim_type = claim.get("claim_type") if isinstance(claim, dict) else None
        if claim_type in DOWNSTREAM_CLAIM_TYPES:
            kept[key] = claim
            polarity = claim.get("polarity")
            bucket = polarity if isinstance(polarity, str) and polarity else MISSING_POLARITY_KEY
            kept_polarity[bucket] = kept_polarity.get(bucket, 0) + 1
        else:
            bucket = claim_type if isinstance(claim_type, str) and claim_type else MISSING_TYPE_KEY
            dropped[bucket] = dropped.get(bucket, 0) + 1
    return kept, dropped, kept_polarity
