"""Extraction validates its output on the way out rather than trusting the model."""

import pytest

from app.agent.assay_extractor import (
    AssayExtractionError,
    ENTRY_FIELDS,
    build_prompt,
    clean_entry,
    clean_registry,
    contract_warnings,
)


def _raw(**over) -> dict:
    entry = {
        "name_in_paper": "flow cytometry",
        "aliases": ["FACS"],
        "platform": "BD LSRFortessa",
        "sample_type": "PBMCs",
        "readouts": "cell frequencies",
        "source": "methods",
        "evidence": {"section": "Methods", "sentence_ids": ["S318"], "quote": "…"},
    }
    entry.update(over)
    return entry


def test_an_entry_is_reduced_to_exactly_the_seven_fields():
    """confidence and claim_role are what a model reaches for unprompted; both were removed
    from this schema on purpose and must not come back through the extractor."""
    entry = clean_entry("flow cytometry", _raw(confidence=0.95, claim_role="primary"))

    assert tuple(entry) == ENTRY_FIELDS


def test_a_missing_name_falls_back_to_the_registry_key():
    entry = clean_entry("ELISA", _raw(name_in_paper=""))

    assert entry["name_in_paper"] == "ELISA"


def test_absent_optional_fields_become_null_not_empty_string():
    """`null` and "" are not the same downstream: merge_verified copies only truthy values,
    and an empty string would read as a stated-but-blank platform."""
    entry = clean_entry("ELISA", _raw(platform="", sample_type=None))

    assert entry["platform"] is None
    assert entry["sample_type"] is None


def test_aliases_that_are_not_strings_are_dropped():
    entry = clean_entry("ELISA", _raw(aliases=["ELISA kits", None, 7, "  "]))

    assert entry["aliases"] == ["ELISA kits"]


def test_a_missing_aliases_list_becomes_empty_not_null():
    entry = clean_entry("ELISA", _raw(aliases=None))

    assert entry["aliases"] == []


def test_evidence_is_always_the_three_field_shape():
    entry = clean_entry("ELISA", _raw(evidence=None))

    assert entry["evidence"] == {"section": None, "sentence_ids": [], "quote": None}


def test_sentence_ids_are_stringified():
    entry = clean_entry("ELISA", _raw(evidence={"sentence_ids": [318, "S9"], "quote": "x"}))

    assert entry["evidence"]["sentence_ids"] == ["318", "S9"]


def test_an_invented_source_value_is_preserved_not_silently_corrected():
    """Rewriting it to "methods" would hide the classification pass going wrong."""
    entry = clean_entry("ELISA", _raw(source="discussion"))

    assert entry["source"] == "discussion"
    assert contract_warnings({"ELISA": entry})


def test_an_omitted_source_defaults_to_methods():
    assert clean_entry("ELISA", _raw(source=None))["source"] == "methods"


def test_a_non_object_answer_is_an_error_not_an_empty_registry():
    """`{}` means the paper describes no assay; a list means the model broke the contract,
    and the two must not be indistinguishable."""
    with pytest.raises(AssayExtractionError):
        clean_registry([{"name_in_paper": "ELISA"}])


def test_an_empty_registry_is_allowed():
    assert clean_registry({}) == {}


def test_non_dict_entries_are_skipped_without_failing_the_paper():
    registry = clean_registry({"ELISA": _raw(), "junk": "not an entry"})

    assert list(registry) == ["ELISA"]


def test_contract_warnings_name_the_unusable_entries():
    registry = clean_registry({
        "ELISA": _raw(name_in_paper="ELISA",
                      evidence={"section": "Methods", "sentence_ids": [], "quote": None}),
        "flow cytometry": _raw(),
    })
    warnings = contract_warnings(registry)

    assert any("no evidence quote" in w for w in warnings)
    assert any("cites no sentence_ids" in w for w in warnings)
    assert not any("flow cytometry" in w for w in warnings)


def test_the_prompt_carries_the_paper_and_leaves_no_placeholders():
    prompt = build_prompt("[S1] Cells were analyzed on an LSRII.", "A Paper")

    assert "A Paper" in prompt and "[S1] Cells were analyzed" in prompt
    assert "{paper_title}" not in prompt and "{source_text}" not in prompt
    # The JSON example's braces must survive -- this prompt is rendered with .replace(),
    # not .format(), precisely so they can.
    assert '"name_in_paper"' in prompt
