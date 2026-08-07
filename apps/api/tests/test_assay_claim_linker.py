"""Linking a claim to an assay must never remove the claim.

apply_verdicts decides which registry entry each claim belongs to; attach_assay_links
writes that decision onto the claims. A claim the validator could not place stays in the
output flagged `link_status: "unlinked"` — whether a claim reaches the validator at all
depends on a string match, so a verdict from that pass cannot justify dropping a finding.
"""

from app.agent.assay_claim_linker import (
    UNLINKED_STATUS,
    apply_verdicts,
    attach_assay_links,
    match_claims_exact,
)

ASSAYS = {
    "flow cytometry": {"name_in_paper": "flow cytometry", "aliases": ["FACS"]},
    "Measurement of global transcript abundance": {
        "name_in_paper": "Measurement of global transcript abundance",
        "aliases": [],
    },
}


def _claim(text: str, assay_name: str) -> dict:
    return {"claim": text, "claim_type": "group_difference", "assay": {"name_in_paper": assay_name}}


def test_exact_match_uses_aliases_and_normalization():
    claims = {
        "claim_1": _claim("a", "FACS"),
        "claim_2": _claim("b", "Flow Cytometry Analysis"),
        "claim_3": _claim("c", "Illumina HumanHT-12 Expression BeadChips"),
    }
    matched, unmatched = match_claims_exact(claims, ASSAYS)

    assert matched == {"claim_1": "flow cytometry", "claim_2": "flow cytometry"}
    assert unmatched == ["claim_3"]


def test_invalid_verdict_reports_without_resolving():
    claims = {"claim_1": _claim("a", "Illumina HumanHT-12 Expression BeadChips")}
    verdicts = {"claim_1": {"verdict": "invalid", "reason": "cis-eQTL needs genotyping too"}}

    resolved, merged, unlinked = apply_verdicts(claims, {}, verdicts, ASSAYS)

    assert resolved == {}
    assert merged == ASSAYS
    assert unlinked == [
        {"claim_key": "claim_1", "claim": "a", "reason": "cis-eQTL needs genotyping too"}
    ]


def test_attach_assay_links_keeps_the_unlinked_claim():
    claims = {
        "claim_1": _claim("linked one", "FACS"),
        "claim_2": _claim("unlinked one", "Illumina HumanHT-12 Expression BeadChips"),
    }
    resolved = {"claim_1": "flow cytometry"}
    unlinked = [{"claim_key": "claim_2", "claim": "unlinked one", "reason": "misattributed"}]

    final = attach_assay_links(claims, resolved, ASSAYS, unlinked)

    assert list(final) == ["claim_1", "claim_2"], "no claim is dropped, order preserved"
    # Linked claims take the registry's canonical wording so they agree on the assay name.
    assert final["claim_1"]["assay"] == {"name_in_paper": "flow cytometry"}
    # The unlinked claim keeps its own name and carries why it stayed unlinked.
    assert final["claim_2"]["assay"] == {
        "name_in_paper": "Illumina HumanHT-12 Expression BeadChips",
        "link_status": UNLINKED_STATUS,
        "link_note": "misattributed",
    }
    assert final["claim_2"]["claim_type"] == "group_difference", "only `assay` is rewritten"


def test_attach_assay_links_flags_a_claim_with_no_verdict_at_all():
    claims = {"claim_1": _claim("orphan", "some assay")}

    final = attach_assay_links(claims, {}, ASSAYS, [])

    assert final["claim_1"]["assay"]["link_status"] == UNLINKED_STATUS
    assert final["claim_1"]["assay"]["link_note"], "an unlinked claim always says why"


def test_new_assay_verdict_grows_the_registry_and_links():
    claims = {"claim_1": _claim("a", "ELISpot")}
    entry = {"name_in_paper": "ELISpot", "aliases": [], "sample_type": "PBMCs"}
    verdicts = {"claim_1": {"verdict": "new_assay", "new_assay": entry}}

    resolved, merged, unlinked = apply_verdicts(claims, {}, verdicts, ASSAYS)
    final = attach_assay_links(claims, resolved, merged, unlinked)

    assert resolved == {"claim_1": "ELISpot"}
    assert merged["ELISpot"] == entry
    assert unlinked == []
    assert final["claim_1"]["assay"] == {"name_in_paper": "ELISpot"}
