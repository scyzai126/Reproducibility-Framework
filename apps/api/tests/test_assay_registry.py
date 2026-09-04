"""The assay registry is now derived from the claims instead of extracted separately, so
these tests pin the de-duplication rule the old reconciliation step used to enforce."""

from app.agent.assay_registry import (
    claim_assay_name,
    load_verified_registry,
    merge_verified,
    normalize_assay_name,
    registry_from_claims,
)


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


def test_normalize_folds_plural_and_analysis_suffixes():
    """Methods writes 'assays', a claim writes 'assay' -- they must reach the same key."""
    assert normalize_assay_name("HAI antibody titer assays") == "hai antibody titer"
    assert normalize_assay_name("HAI antibody titer assay") == "hai antibody titer"
    assert normalize_assay_name("Microarray Analyses") == "microarray"
    assert normalize_assay_name("Flow Cytometry Analysis") == "flow cytometry"


def test_merge_verified_fills_the_fields_claims_cannot_carry():
    claims_registry = registry_from_claims({
        "claim_1": _claim("hemagglutination-inhibition (HAI) antibody titer assay"),
    })
    merged = merge_verified(claims_registry, {
        "hemagglutination-inhibition (HAI) antibody titer assays": {
            "name_in_paper": "hemagglutination-inhibition (HAI) antibody titer assays",
            "aliases": ["HAI assays"],
            "platform": None,
            "sample_type": "plasma",
            "readouts": "strain-specific HAI antibody titers",
        },
    })

    entry = merged["hemagglutination-inhibition (HAI) antibody titer assay"]
    assert entry["sample_type"] == "plasma"
    assert entry["readouts"] == "strain-specific HAI antibody titers"
    assert entry["aliases"] == ["HAI assays"]
    # A null platform is not copied -- absence stays absence.
    assert not entry.get("platform")


def test_merge_verified_keeps_an_entry_the_verified_registry_never_saw():
    """An assay only the claims name must keep its entry, or that claim loses resolution."""
    merged = merge_verified(
        registry_from_claims({"claim_1": _claim("ELISPOT")}),
        {"microarray": {"platform": "Affymetrix", "readouts": "gene expression"}},
    )

    assert list(merged) == ["ELISPOT"]
    assert merged["ELISPOT"] == {
        "name_in_paper": "ELISPOT", "aliases": [], "sample_type": "", "readouts": "",
    }


def test_merge_verified_does_not_duplicate_an_alias_already_present():
    claims_registry = registry_from_claims({
        "claim_1": _claim("flow cytometry"),
        "claim_2": _claim("FACS analysis"),
    })
    merged = merge_verified(claims_registry, {
        "flow cytometry": {"aliases": ["FACS analysis", "FACS"], "platform": "LSRII (BD)"},
    })

    entry = merged["flow cytometry"]
    assert entry["aliases"] == ["FACS analysis", "FACS"]
    assert entry["platform"] == "LSRII (BD)"


def test_load_verified_registry_is_silent_when_there_is_nothing_on_disk():
    assert load_verified_registry("00000000", "SDY00000") == {}
    assert load_verified_registry("", "SDY1119") == {}
