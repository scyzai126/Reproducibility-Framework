"""Extraction validates its output on the way out rather than trusting the model."""

import pytest

from app.agent.assay_extractor import (
    AssayExtractionError,
    ENTRY_FIELDS,
    TRIMMED_FIELDS,
    build_prompt,
    clean_entry,
    clean_registry,
    contract_warnings,
    trim_registry,
)


def _raw(**over) -> dict:
    entry = {
        "name_in_paper": "flow cytometry",
        "normalized_name": "flow cytometry",
        "aliases": ["FACS"],
        "platform": "BD LSRFortessa",
        "sample_type": "PBMCs",
        "readouts": "cell frequencies",
        "measurement_role": "reported",
        "parent_hint": None,
        "source": "methods",
        "evidence": {"section": "Methods", "sentence_ids": ["S318"], "quote": "…"},
    }
    entry.update(over)
    return entry


def test_an_entry_is_reduced_to_exactly_the_contract_fields():
    """confidence and claim_role are what a model reaches for unprompted; both were removed
    from this schema on purpose and must not come back through the extractor."""
    entry = clean_entry("flow cytometry", _raw(confidence=0.95, claim_role="primary"))

    assert tuple(entry) == ENTRY_FIELDS


def test_a_missing_name_falls_back_to_the_registry_key():
    entry = clean_entry("ELISA", _raw(name_in_paper=""))

    assert entry["name_in_paper"] == "ELISA"


def test_a_missing_normalized_name_stays_null_and_does_not_echo_the_key():
    """Unlike name_in_paper, this one has no fallback, and that asymmetry is the point.

    An omitted normalization means the model declined to name a technique. Echoing the paper's
    own wording back would turn that silence into an assertion -- and the OBI mapper trusts
    this field as an exact-match key without any further adjudication, so a fabricated value
    here becomes an unchallenged ontology term.
    """
    assert clean_entry("ELISA", _raw(normalized_name=""))["normalized_name"] is None
    assert clean_entry("ELISA", _raw(normalized_name=None))["normalized_name"] is None
    assert clean_entry("ELISA", _raw(normalized_name="   "))["normalized_name"] is None


def test_a_normalized_name_that_is_not_a_string_is_dropped():
    assert clean_entry("ELISA", _raw(normalized_name=["flow cytometry"]))["normalized_name"] is None


def test_an_old_schema_entry_without_the_field_still_parses():
    """The 44 registries on disk predate the field; reading one must not fail or invent a value."""
    raw = _raw()
    del raw["normalized_name"]

    entry = clean_entry("flow cytometry", raw)

    assert entry["normalized_name"] is None
    assert tuple(entry) == ENTRY_FIELDS


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


def test_an_omitted_source_becomes_null_and_warns():
    """Defaulting to "methods" asserted the stronger provenance claim on exactly the entries
    where the model declined to say. The null is not the point; the warning is."""
    entry = clean_entry("ELISA", _raw(source=None))

    assert entry["source"] is None
    assert any("source is None" in w for w in contract_warnings({"ELISA": entry}))


def test_a_blank_source_is_treated_as_omitted():
    assert clean_entry("ELISA", _raw(source="   "))["source"] is None


def test_contract_warnings_report_an_old_schema_entry_instead_of_raising():
    """Most stored registries predate the current schema, and assay_service runs this on
    registries loaded from disk -- subscripting turned a stale cache into a 500."""
    old_schema = {
        "ELISA": {
            "name_in_paper": "ELISA",
            "aliases": [],
            "readouts": "cytokine concentrations",
            "sample_type": "serum",
            "evidence_location": "Methods",
            "claim_role": "primary",
            "confidence": "high",
        }
    }
    warnings = contract_warnings(old_schema)

    assert any("no evidence quote" in w for w in warnings)
    assert any("cites no sentence_ids" in w for w in warnings)
    assert any("source is None" in w for w in warnings)


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


def test_contract_warnings_flag_aliases_that_are_not_a_list():
    """`[]` is a real answer -- plenty of assays are named one way only -- but `null` or a bare
    string is a defect that reads as "no aliases" downstream instead of as the gap it is. The
    correction round can clear the field, and assay_service runs this over registries loaded
    from disk, so nothing else would catch it."""
    registry = {
        "ELISA": {**_raw(name_in_paper="ELISA"), "aliases": None},
        "Luminex": {**_raw(name_in_paper="Luminex"), "aliases": "FACS"},
        "flow cytometry": _raw(),
    }
    warnings = contract_warnings(registry)

    assert any("ELISA: aliases is None" in w for w in warnings)
    assert any("Luminex: aliases is 'FACS'" in w for w in warnings)
    assert not any("flow cytometry" in w for w in warnings)


def test_trim_registry_keeps_only_the_deliverable_fields():
    """The trimmed view answers "which assay, called what else, established where". platform,
    sample_type and readouts answer a different question and stay in assays.json."""
    trimmed = trim_registry(clean_registry({"flow cytometry": _raw()}))

    assert tuple(trimmed["flow cytometry"]) == TRIMMED_FIELDS
    assert trimmed["flow cytometry"]["aliases"] == ["FACS"]
    assert trimmed["flow cytometry"]["evidence"]["sentence_ids"] == ["S318"]


def test_trim_registry_carries_a_merged_entrys_second_write_up():
    """`additional_evidence` is round 5's only output, and the deliverable is where it is read.

    It is carried only where it exists: an entry nothing merged into keeps exactly the four
    fields it had before the round existed, so no stored deliverable gains a null key.
    """
    merged = {**clean_entry("ELISA", _raw()), "name_in_paper": "ELISA",
              "additional_evidence": [{"name_in_paper": "ELISA kits", "source": "methods",
                                       "evidence": {"section": "In vitro DC activation",
                                                    "sentence_ids": ["S348"], "quote": "..."}}]}

    trimmed = trim_registry({"ELISA": merged, "flow cytometry": clean_entry("flow cytometry", _raw())})

    assert tuple(trimmed["ELISA"]) == TRIMMED_FIELDS + ("additional_evidence",)
    assert trimmed["ELISA"]["additional_evidence"][0]["evidence"]["sentence_ids"] == ["S348"]
    assert tuple(trimmed["flow cytometry"]) == TRIMMED_FIELDS


def test_trim_registry_reports_an_old_schema_entry_rather_than_dropping_it():
    """Registries stored before the current schema carry `evidence_location`. Such an entry
    comes back with a null evidence field -- a visible gap beats a silently missing assay."""
    trimmed = trim_registry({
        "ELISA": {"name_in_paper": "ELISA", "aliases": [],
                  "evidence_location": {"quote": "..."}, "confidence": "high"},
        "junk": "not an entry",
    })

    assert list(trimmed) == ["ELISA"]
    assert trimmed["ELISA"]["evidence"] is None
    assert "confidence" not in trimmed["ELISA"]


def test_the_prompt_carries_the_paper_and_leaves_no_placeholders():
    prompt = build_prompt("[S1] Cells were analyzed on an LSRII.", "A Paper")

    assert "A Paper" in prompt and "[S1] Cells were analyzed" in prompt
    assert "{paper_title}" not in prompt and "{source_text}" not in prompt
    # The JSON example's braces must survive -- this prompt is rendered with .replace(),
    # not .format(), precisely so they can.
    assert '"name_in_paper"' in prompt


# ── measurement_role / parent_hint ────────────────────────────────────────────

def test_an_invented_role_becomes_none_and_is_reported():
    """Not corrected to the nearest valid role: that would hide the model going wrong."""
    registry = clean_registry({"ELISA": _raw(name_in_paper="ELISA", measurement_role="primary")})

    assert registry["ELISA"]["measurement_role"] is None
    assert any("ELISA: measurement_role is None" in w for w in contract_warnings(registry))


def test_every_documented_role_is_kept():
    for role in ("reported", "sub_step", "screening", "unreported"):
        assert clean_entry("x", _raw(measurement_role=role))["measurement_role"] == role


def test_a_sub_step_must_name_its_parent():
    registry = clean_registry({
        "flow cytometry": _raw(),
        "tandem MS": _raw(name_in_paper="tandem MS", measurement_role="sub_step"),
    })

    assert "tandem MS: sub_step has no parent_hint" in contract_warnings(registry)


def test_a_parent_hint_resolves_by_wording_even_after_the_registry_is_rekeyed():
    """Round 5 keys entries by OBI label but keeps every wording in name_in_paper."""
    registry = {
        "liquid chromatography mass spectrometry assay": {
            **_raw(name_in_paper=["LC-MS analysis"])},
        "tandem mass spectrometry assay": _raw(
            name_in_paper="tandem mass spectrometry assay", measurement_role="sub_step",
            parent_hint="LC-MS analysis"),
    }

    assert not any("parent_hint" in w for w in contract_warnings(registry))


def test_a_parent_hint_naming_nothing_is_reported():
    registry = clean_registry({
        "flow cytometry": _raw(),
        "tandem MS": _raw(name_in_paper="tandem MS", measurement_role="sub_step",
                          parent_hint="LC-MS"),
    })

    assert "tandem MS: parent_hint 'LC-MS' names no other entry" in contract_warnings(registry)


def test_a_parent_hint_on_a_non_sub_step_is_reported():
    registry = clean_registry({"flow cytometry": _raw(parent_hint="ELISA")})

    assert any("parent_hint 'ELISA' set on a 'reported' entry" in w
               for w in contract_warnings(registry))


def test_the_deliverable_carries_the_role_but_not_the_parent_hint():
    trimmed = trim_registry(clean_registry({"flow cytometry": _raw()}))

    assert trimmed["flow cytometry"]["measurement_role"] == "reported"
    assert "parent_hint" not in trimmed["flow cytometry"]
