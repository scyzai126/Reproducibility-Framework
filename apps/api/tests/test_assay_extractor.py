"""Extraction validates its output on the way out rather than trusting the model."""

import pytest

from app.agent.assay_extractor import (
    AssayExtractionError,
    ENTRY_FIELDS,
    TRIMMED_FIELDS,
    NO_METHODS_NOTE,
    build_prompt,
    clean_entry,
    clean_registry,
    contract_warnings,
    parse_registry_json,
    trim_registry,
)


def _raw(**over) -> dict:
    entry = {
        "name_in_paper": "flow cytometry",
        "normalized_name": "flow cytometry",
        "aliases": ["FACS"],
        "sample_type": "PBMCs",
        "readouts": "cell frequencies",
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
    and an empty string would read as a stated-but-blank specimen."""
    entry = clean_entry("ELISA", _raw(sample_type="", readouts=None))

    assert entry["sample_type"] is None
    assert entry["readouts"] is None


def test_aliases_that_are_not_strings_are_dropped():
    entry = clean_entry("ELISA", _raw(aliases=["ELISA kits", None, 7, "  "]))

    assert entry["aliases"] == ["ELISA kits"]


def test_a_missing_aliases_list_becomes_empty_not_null():
    entry = clean_entry("ELISA", _raw(aliases=None))

    assert entry["aliases"] == []


def test_evidence_is_always_the_three_field_shape():
    entry = clean_entry("ELISA", _raw(evidence=None))

    assert entry["evidence"] == {"section": None, "sentence_ids": [], "quote": None}


def test_sentence_ids_a_model_volunteers_are_dropped_not_kept():
    """They are derived from the quote afterwards, so a guess is only a worse value to overwrite."""
    entry = clean_entry("ELISA", _raw(evidence={"sentence_ids": [318, "S9"], "quote": "x"}))

    assert entry["evidence"]["sentence_ids"] == []


def test_a_source_a_model_volunteers_is_dropped_not_kept():
    """`source` is derived from where the quote sits. Accepting an unasked-for answer would let a
    judgement outrank the document, which is the disagreement deriving it exists to remove."""
    entry = clean_entry("ELISA", _raw(source="discussion"))

    assert entry["source"] is None


def test_source_starts_null_so_a_registry_never_asserts_an_underived_provenance():
    entry = clean_entry("ELISA", _raw())

    assert entry["source"] is None


def test_generate_claim_keeps_a_real_boolean_either_way():
    assert clean_entry("ELISA", _raw(generate_claim=True))["generate_claim"] is True
    assert clean_entry("ELISA", _raw(generate_claim=False))["generate_claim"] is False


@pytest.mark.parametrize("answer", ["true", "yes", 1, 0, None, {}, []])
def test_generate_claim_accepts_nothing_but_a_boolean(answer):
    """A value in a shape the contract does not define is not an answer.

    `1` is the trap: `1 in (True, False)` is True in Python, so a truthiness or membership
    check would read a formatting slip as the paper having reported a finding it may not have.
    """
    assert clean_entry("ELISA", _raw(generate_claim=answer))["generate_claim"] is None


def test_an_unanswered_generate_claim_stays_null_rather_than_defaulting_to_false():
    """"The paper drew nothing from this assay" and "nobody said" must stay distinguishable:
    the first is a finding about the paper, the second is a gap in our own extraction."""
    assert clean_entry("ELISA", _raw())["generate_claim"] is None


def test_generate_claim_reaches_the_deliverable():
    """It is in TRIMMED_FIELDS because assays_benchmark.json is the file held against the
    curated benchmark, which carries the same field."""
    trimmed = trim_registry(clean_registry({"ELISA": _raw(generate_claim=False)}))

    assert trimmed["ELISA"]["generate_claim"] is False


def test_an_old_registry_without_generate_claim_trims_to_null_rather_than_raising():
    """The 38 registries on disk predate the field. Every reader uses .get(), so they keep
    working and read as "not answered" -- the same tolerance platform and measurement_role get."""
    trimmed = trim_registry({"ELISA": {"name_in_paper": "ELISA", "aliases": [],
                                       "evidence": {"quote": "..."}}})

    assert trimmed["ELISA"]["generate_claim"] is None


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
    assert any("quote could not be located" in w for w in warnings)
    assert any("source could not be derived" in w for w in warnings)


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
    # The derived fields are filled in later by derive_evidence_fields, so they are checked
    # separately; this pins the quote check, which is the one the extraction can fail.
    warnings = contract_warnings(registry, expect_sentence_ids=False)

    assert any("ELISA" in w and "no evidence quote" in w for w in warnings)
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
    warnings = contract_warnings(registry, expect_sentence_ids=False)

    assert any("ELISA: aliases is None" in w for w in warnings)
    assert any("Luminex: aliases is 'FACS'" in w for w in warnings)
    assert not any("flow cytometry" in w for w in warnings)


def test_trim_registry_keeps_only_the_deliverable_fields():
    """The trimmed view answers "which assay, called what else, established where".
    sample_type and readouts answer a different question and stay in assays.json."""
    trimmed = trim_registry(clean_registry({"flow cytometry": _raw()}))

    assert tuple(trimmed["flow cytometry"]) == TRIMMED_FIELDS
    assert trimmed["flow cytometry"]["aliases"] == ["FACS"]
    assert "sample_type" not in trimmed["flow cytometry"]


def test_trim_registry_carries_a_merged_entrys_second_write_up():
    """`additional_evidence` is round 5's only output, and the deliverable is where it is read.

    It is carried only where it exists: an entry nothing merged into keeps exactly the fields
    it had before the round existed, so no stored deliverable gains a null key.
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


# ── a paper with no Methods section (structure 3) ─────────────────────────────

def test_a_paper_with_no_methods_section_is_told_structure_3_applies():
    """SDY1171: a short report whose methods sit in a supplement. Left to infer it, the model
    took the Methods-only path and returned {} for a paper that names its assay."""
    prompt = build_prompt("## Abstract  [abstract]\n[S1] a\n\n## Main text  [other]\n[S2] b",
                          "A Paper")

    assert NO_METHODS_NOTE + "## Abstract" in prompt


def test_a_paper_with_a_methods_section_gets_the_prompt_unchanged():
    source = "## Methods  [methods]\n[S1] Cells were analyzed."

    assert NO_METHODS_NOTE not in build_prompt(source, "A Paper")
    assert source in build_prompt(source, "A Paper")


# ── an answer wrapped in an envelope is never mistaken for "no assays" ─────────

def test_a_registry_wrapped_in_an_object_is_unwrapped():
    assert list(clean_registry({"assays": {"ELISA": _raw()}})) == ["ELISA"]


def test_a_registry_wrapped_as_a_list_is_keyed_by_name_in_paper():
    registry = clean_registry({"assays": [_raw(name_in_paper="iELISA"),
                                          _raw(name_in_paper="RT-PCR")]})

    assert list(registry) == ["iELISA", "RT-PCR"]


def test_an_object_with_keys_but_no_entries_is_an_error_not_an_empty_registry():
    with pytest.raises(AssayExtractionError, match="no assay entries"):
        clean_registry({"note": "the paper has no Methods section"})


def test_a_repeated_key_keeps_both_entries(caplog):
    """Two analyte-split entries can strip to one bare name; json.loads would keep only the last."""
    raw = ('{"Luminex": {"name_in_paper": "Luminex", "readouts": "antibody titers"},'
           ' "Luminex": {"name_in_paper": "Luminex", "readouts": "cytokines"}}')

    parsed = parse_registry_json(raw)

    assert list(parsed) == ["Luminex", "Luminex (2)"]
    assert parsed["Luminex (2)"]["readouts"] == "cytokines"
    assert "duplicate key" in caplog.text


def test_unparseable_registry_json_raises_the_extraction_error():
    with pytest.raises(AssayExtractionError):
        parse_registry_json("{not json")
