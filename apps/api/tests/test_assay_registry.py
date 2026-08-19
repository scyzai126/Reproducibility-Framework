"""The assay registry is now derived from the claims instead of extracted separately, so
these tests pin the de-duplication rule the old reconciliation step used to enforce."""

from app.agent.assay_registry import claim_assay_name, registry_from_claims


def _claim(assay: str | None) -> dict:
    return {"claim": "...", "assay": {"name_in_paper": assay} if assay is not None else {}}


def test_one_entry_per_assay_with_the_first_wording_as_the_key():
    registry = registry_from_claims({
        "claim_1": _claim("flow cytometry"),
        "claim_2": _claim("flow cytometry"),
    })

    assert list(registry) == ["flow cytometry"]
    assert registry["flow cytometry"]["name_in_paper"] == "flow cytometry"
    assert registry["flow cytometry"]["aliases"] == []


def test_wordings_that_normalize_alike_collapse_into_aliases():
    """'Flow Cytometry assay' and 'flow  cytometry' are the same technique named twice."""
    registry = registry_from_claims({
        "claim_1": _claim("flow cytometry"),
        "claim_2": _claim("Flow Cytometry assay"),
        "claim_3": _claim("flow  cytometry"),
        "claim_4": _claim("Flow Cytometry assay"),
    })

    assert list(registry) == ["flow cytometry"]
    assert registry["flow cytometry"]["aliases"] == ["Flow Cytometry assay", "flow  cytometry"]


def test_distinct_assays_stay_separate_in_claim_order():
    registry = registry_from_claims({
        "claim_1": _claim("ELISA"),
        "claim_2": _claim("mass cytometry"),
        "claim_3": _claim("ELISA"),
    })

    assert list(registry) == ["ELISA", "mass cytometry"]


def test_reads_the_v5_published_field_when_there_is_no_assay_object():
    """claim_abstraction_v5 writes the name as `assay_method_in_paper`, not `assay`."""
    registry = registry_from_claims({
        "claim_1": {"claim": "...", "assay_method_in_paper": "qRT-PCR"},
    })

    assert list(registry) == ["qRT-PCR"]


def test_claims_with_no_usable_assay_name_contribute_nothing():
    registry = registry_from_claims({
        "claim_1": _claim(None),
        "claim_2": _claim("   "),
        "claim_3": {"claim": "..."},
        "claim_4": _claim("ELISA"),
    })

    assert list(registry) == ["ELISA"]


def test_entries_carry_the_fields_obi_enrichment_and_query_building_read():
    entry = registry_from_claims({"claim_1": _claim("Luminex")})["Luminex"]

    # sample_type/readouts are empty by design -- claims do not carry them.
    assert entry == {
        "name_in_paper": "Luminex",
        "aliases": [],
        "sample_type": "",
        "readouts": "",
    }


def test_claim_assay_name_prefers_the_assay_object_over_the_published_field():
    name = claim_assay_name({
        "assay": {"name_in_paper": "mass cytometry"},
        "assay_method_in_paper": "CyTOF",
    })

    assert name == "mass cytometry"
