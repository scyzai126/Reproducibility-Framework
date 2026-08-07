from pathlib import Path

from app.agent.claim_filter import (
    DOWNSTREAM_CLAIM_TYPES,
    MISSING_POLARITY_KEY,
    MISSING_TYPE_KEY,
    filter_claims_for_downstream,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _claim(claim_type: str | None, polarity: str = "affirm") -> dict:
    entry: dict = {
        "claim": f"a {claim_type} claim",
        "sources": [{"type": "text"}],
        "polarity": polarity,
    }
    if claim_type is not None:
        entry["claim_type"] = claim_type
    return entry


def test_keeps_only_the_three_downstream_types():
    claims = {f"claim_{i}": _claim(t) for i, t in enumerate(
        [
            "induction_vs_reference",
            "group_difference",
            "extremum",
            "trajectory_segment",
            "magnitude_comparison",
            "association",
            "prediction",
            "dependency",
            "descriptive",
        ],
        start=1,
    )}

    kept, dropped, _ = filter_claims_for_downstream(claims)

    assert list(kept) == ["claim_1", "claim_2", "claim_3"]
    assert sum(dropped.values()) == 6
    assert dropped["descriptive"] == 1


def test_preserves_original_keys_and_order():
    claims = {
        "claim_9": _claim("extremum"),
        "claim_2": _claim("association"),
        "claim_5": _claim("group_difference"),
        "claim_1": _claim("induction_vs_reference"),
    }

    kept, _, _ = filter_claims_for_downstream(claims)

    assert list(kept) == ["claim_9", "claim_5", "claim_1"]


def test_claim_values_pass_through_verbatim():
    entry = {
        "claim": "IFNγ responses increased at day 7 relative to baseline.",
        "claim_type": "induction_vs_reference",
        "polarity": "affirm",
        "assay": {"name_in_paper": "ELISpot assays"},
        "sources": [{"type": "text", "section": "Results", "quote": "..."}],
    }

    kept, _, _ = filter_claims_for_downstream({"claim_1": entry})

    assert kept["claim_1"] == entry
    assert kept["claim_1"] is entry


def test_missing_and_invented_types_are_dropped_and_tallied():
    claims = {
        "claim_1": _claim(None),
        "claim_2": {"claim": "no type key at all"},
        "claim_3": {"claim": "explicit null", "claim_type": None},
        "claim_4": _claim("group_comparison_over_time"),
        "claim_5": _claim("group_difference"),
    }

    kept, dropped, _ = filter_claims_for_downstream(claims)

    assert list(kept) == ["claim_5"]
    assert dropped[MISSING_TYPE_KEY] == 3
    assert dropped["group_comparison_over_time"] == 1


def test_null_polarity_claims_carry_forward_and_are_tallied():
    """A stated absence is reproducible — the verifier runs the same operation, only the
    expected answer flips — so it is kept, not filtered out with the unusable types."""
    claims = {
        "claim_1": _claim("group_difference", polarity="null"),
        "claim_2": _claim("induction_vs_reference", polarity="affirm"),
        "claim_3": _claim("extremum", polarity="null"),
        "claim_4": _claim("association", polarity="null"),
    }

    kept, dropped, kept_polarity = filter_claims_for_downstream(claims)

    assert list(kept) == ["claim_1", "claim_2", "claim_3"]
    assert kept_polarity == {"null": 2, "affirm": 1}
    assert dropped == {"association": 1}


def test_missing_polarity_is_tallied_rather_than_assumed():
    claims = {"claim_1": {"claim": "no polarity key", "claim_type": "extremum"}}

    _, _, kept_polarity = filter_claims_for_downstream(claims)

    assert kept_polarity == {MISSING_POLARITY_KEY: 1}


def test_empty_input():
    assert filter_claims_for_downstream({}) == ({}, {}, {})


def test_downstream_types_exist_in_the_prompt_vocabulary():
    """A rename in claim_types.txt must fail here rather than silently emptying the filter."""
    vocabulary = (_REPO_ROOT / "apps/api/app/prompts/claim_types.txt").read_text(encoding="utf-8")

    for claim_type in DOWNSTREAM_CLAIM_TYPES:
        assert f"`{claim_type}`" in vocabulary
