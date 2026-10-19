"""The corrector repairs only what a verification flagged, and only from a blind re-read."""

import asyncio
import json

import pytest

from app.agent.assay_corrector import (
    CLEARED,
    REAFFIRMED,
    REPLACED,
    UNCHANGED,
    apply_correction,
    correct_field,
    build_prompt,
    correct_registry,
    decide,
    drop_rejected,
    field_group,
    flagged_alias_indices,
    flagged_groups,
    promote_registry,
    rejected_assays,
    uncorrectable_flags,
)

_SOURCE = "[S1] Cells were analyzed on the LSRII flow cytometer (BD). [S2] PBMCs were thawed and rested overnight."


def _entry(**over) -> dict:
    entry = {
        "name_in_paper": "flow cytometry",
        "aliases": ["FACS analysis", "Flow cytometry"],
        "sample_type": "PBMCs",
        "readouts": "cell frequencies",
        "source": "methods",
        "evidence": {"section": "Methods", "sentence_ids": ["S1"],
                     "quote": "Cells were analyzed on the LSRII flow cytometer (BD)."},
    }
    entry.update(over)
    return entry


def _verification(*fields) -> dict:
    return {"field_verifications": [
        {"field_name": name, "verdict": verdict, "reason": "..."} for name, verdict in fields
    ]}


# ── what gets flagged ─────────────────────────────────────────────────────────

def test_alias_indices_collapse_into_one_question():
    """aliases[0] and aliases[3] are one rule failing, so they cost one call, not two."""
    groups = flagged_groups(_verification(
        ("aliases[0]", "NOT_SUPPORTED"), ("aliases[3]", "NOT_SUPPORTED"),
    ))
    assert groups == ["aliases"]


def test_supported_fields_are_not_reopened():
    groups = flagged_groups(_verification(
        ("readouts", "SUPPORTED"), ("sample_type", "CONTRADICTED"),
    ))
    assert groups == ["sample_type"]


def test_not_supported_is_flagged_even_when_the_record_says_accept():
    """derive_record_verdict ignores NOT_SUPPORTED, so triggering on the record would
    skip exactly the fields this pass exists to repair."""
    result = {"record_verdict": "ACCEPT",
              **_verification(("aliases[2]", "NOT_SUPPORTED"))}
    assert flagged_groups(result) == ["aliases"]


def test_evidence_quote_and_ids_are_one_question():
    groups = flagged_groups(_verification(
        ("evidence.quote", "CONTRADICTED"), ("evidence.sentence_ids", "NOT_SUPPORTED"),
    ))
    assert groups == ["evidence"]


def test_assay_identity_is_reported_not_corrected():
    result = _verification(("name_in_paper", "CONTRADICTED"))
    assert field_group("name_in_paper") is None
    assert flagged_groups(result) == []
    assert [f["field_name"] for f in uncorrectable_flags(result)] == ["name_in_paper"]


# ── the three-way vote ────────────────────────────────────────────────────────

def test_matching_blind_answer_reaffirms_the_original():
    assert decide("PBMCs", "pbmcs ") == REAFFIRMED


def test_differing_blind_answer_replaces():
    assert decide("NextSeq 2000", "LSRII flow cytometer (BD)") == REPLACED


def test_null_blind_answer_clears_a_value_that_was_there():
    assert decide("NextSeq 2000", None) == CLEARED


def test_null_blind_answer_over_an_already_empty_field_changes_nothing():
    assert decide(None, None) == UNCHANGED


# ── applying it ───────────────────────────────────────────────────────────────

def test_a_cleared_specimen_becomes_null_rather_than_a_guess():
    entry = _entry()
    record = apply_correction(entry, "sample_type", None, _SOURCE)

    assert record["action"] == CLEARED
    assert record["previous"] == "PBMCs"
    assert entry["sample_type"] is None


def test_a_flagged_alias_the_blind_read_did_not_confirm_is_dropped():
    entry = _entry()
    record = apply_correction(entry, "aliases", ["FACS analysis"], _SOURCE,
                              flagged_aliases={1})

    assert record["action"] == REPLACED
    assert entry["aliases"] == ["FACS analysis"]
    assert record["dropped"] == ["Flow cytometry"]


def test_an_unflagged_alias_survives_a_blind_read_that_words_it_differently():
    """Measured regression on SDY1119: pruning the whole list to the blind answer destroyed
    "fluorescence-activated cell sorting (FACS) measurements", which the judge SUPPORTED."""
    entry = _entry(aliases=["fluorescence-activated cell sorting (FACS) measurements",
                            "FACS analysis", "Flow cytometry"])
    apply_correction(entry, "aliases", ["FACS analysis", "Flow Cytometry Analysis"],
                     _SOURCE, flagged_aliases={2})

    assert entry["aliases"] == [
        "fluorescence-activated cell sorting (FACS) measurements", "FACS analysis",
    ]


def test_aliases_are_not_expanded_beyond_what_was_there():
    """The pass was scoped to flagged fields; adding new aliases would be expansion."""
    entry = _entry()
    apply_correction(entry, "aliases", ["FACS analysis", "Flow cytometry", "FACS"], _SOURCE,
                     flagged_aliases={0, 1})

    assert entry["aliases"] == ["FACS analysis", "Flow cytometry"]


def test_flagged_alias_indices_reads_only_the_unsupported_positions():
    result = {"field_verifications": [
        {"field_name": "aliases[0]", "verdict": "SUPPORTED"},
        {"field_name": "aliases[2]", "verdict": "NOT_SUPPORTED"},
        {"field_name": "platform", "verdict": "CONTRADICTED"},
    ]}

    assert flagged_alias_indices(result) == {2}


def test_a_replacement_quote_that_is_not_verbatim_is_rejected():
    entry = _entry()
    blind = {"quote": "Cells were run on a NovaSeq 6000.", "sentence_ids": ["S1"]}
    record = apply_correction(entry, "evidence", blind, _SOURCE)

    assert record["action"] == UNCHANGED
    assert "rejected" in record["note"]
    assert entry["evidence"]["quote"].startswith("Cells were analyzed")


def test_a_verbatim_replacement_quote_lands():
    entry = _entry()
    blind = {"quote": "PBMCs were thawed and rested overnight.", "sentence_ids": ["S2"]}
    record = apply_correction(entry, "evidence", blind, _SOURCE)

    assert record["action"] == REPLACED
    assert entry["evidence"]["quote"] == "PBMCs were thawed and rested overnight."
    assert entry["evidence"]["sentence_ids"] == ["S2"]


def test_evidence_is_never_blanked():
    """An entry with no quotable support is a finding for a human, not a silent deletion."""
    entry = _entry()
    record = apply_correction(entry, "evidence", {"quote": None, "sentence_ids": []}, _SOURCE)

    assert record["action"] == UNCHANGED
    assert entry["evidence"]["quote"].startswith("Cells were analyzed")


# ── blindness ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("group", ["sample_type", "readouts"])
def test_the_prompt_never_shows_the_disputed_value(group):
    """The whole premise: a corrector shown the rejected string edits the string.

    The fixture values are deliberately unlike the examples the questions carry, so a hit
    means the entry leaked rather than that the question named a common specimen."""
    entry = _entry(sample_type="bronchoalveolar lavage fluid",
                   readouts="tetramer-positive clonotype counts")
    prompt = build_prompt(entry, group, _SOURCE, "A Paper")

    assert entry[group] not in prompt
    assert "CONTRADICTED" not in prompt and "NOT_SUPPORTED" not in prompt


def test_the_evidence_question_does_not_quote_the_evidence_back():
    entry = _entry()
    prompt = build_prompt(entry, "evidence", _SOURCE, "A Paper")

    assert entry["evidence"]["quote"] not in prompt.split("ORIGINAL SOURCE TEXT")[0]


# ── rejected assays: removal, not repair ──────────────────────────────────────

def _verification_results(*results) -> dict:
    return {"results": list(results)}


def _rejected(assay_id, reason="computational analysis, not an assay") -> dict:
    return {"assay_id": assay_id, "record_verdict": "REJECT",
            "assay_identity_verdict": "CONTRADICTED",
            "field_verifications": [{"field_name": "name_in_paper",
                                     "verdict": "CONTRADICTED", "reason": reason}]}


def _accepted(assay_id) -> dict:
    return {"assay_id": assay_id, "record_verdict": "ACCEPT",
            "assay_identity_verdict": "SUPPORTED", "field_verifications": []}


def test_rejected_assays_carry_the_reason_the_judge_gave():
    reasons = rejected_assays(_verification_results(_rejected("GSEA"), _accepted("ELISA")))

    assert reasons == {"GSEA": "computational analysis, not an assay"}


def test_a_contradicted_identity_counts_even_without_a_reject_record():
    """derive_record_verdict should already give REJECT, but the identity verdict is the
    substantive signal and must not depend on the derived one agreeing."""
    result = {**_rejected("GSEA"), "record_verdict": "REVIEW"}

    assert "GSEA" in rejected_assays(_verification_results(result))


def test_drop_rejected_keeps_everything_else_and_carries_the_entry_out():
    assays = {"GSEA": {"name_in_paper": "GSEA"}, "ELISA": {"name_in_paper": "ELISA"}}
    kept, dropped = drop_rejected(
        assays, _verification_results(_rejected("GSEA"), _accepted("ELISA")))

    assert list(kept) == ["ELISA"]
    assert dropped["GSEA"]["entry"] == {"name_in_paper": "GSEA"}
    assert dropped["GSEA"]["reason"] == "computational analysis, not an assay"


def test_drop_rejected_does_not_mutate_its_input():
    assays = {"GSEA": {"name_in_paper": "GSEA"}}
    drop_rejected(assays, _verification_results(_rejected("GSEA")))

    assert list(assays) == ["GSEA"]


def test_a_product_named_assay_with_a_supported_identity_is_kept():
    """SDY1655: the judge deleted "Human Cytokine Array/Chemokine Array 71-403 Plex Panel
    (HD71)", the paper's only cytokine measurement, for being named after the panel. Only a
    CONTRADICTED identity or a REJECT record removes an entry; a quarrel with the name is a
    field verdict on `standard_technique_name` and must leave the record standing."""
    panel = "Human Cytokine Array/Chemokine Array 71-403 Plex Panel (HD71)"
    result = {"assay_id": panel, "record_verdict": "REVIEW",
              "assay_identity_verdict": "SUPPORTED",
              "field_verifications": [{"field_name": "standard_technique_name",
                                       "verdict": "NOT_SUPPORTED",
                                       "reason": "names the panel, not the technique"}]}
    kept, dropped = drop_rejected({panel: {"name_in_paper": panel}},
                                  _verification_results(result))

    assert list(kept) == [panel] and dropped == {}


def test_a_review_record_is_repaired_not_dropped():
    """REVIEW means a field is wrong, which correction fixes; only identity is fatal."""
    result = {"assay_id": "ELISA", "record_verdict": "REVIEW",
              "assay_identity_verdict": "SUPPORTED",
              "field_verifications": [{"field_name": "platform", "verdict": "NOT_SUPPORTED"}]}
    kept, dropped = drop_rejected({"ELISA": {}}, _verification_results(result))

    assert list(kept) == ["ELISA"] and dropped == {}


def test_promote_installs_the_corrected_registry_and_snapshots_the_original(tmp_path):
    (tmp_path / "assays.json").write_text('{"a": {"platform": "WRONG"}}')
    (tmp_path / "assays_corrected.json").write_text('{"a": {"platform": null}}')

    result = promote_registry(tmp_path)

    assert result["snapshot_written"] is True
    assert (tmp_path / "assays.json").read_text() == '{"a": {"platform": null}}'
    assert (tmp_path / "assays_precorrection.json").read_text() == '{"a": {"platform": "WRONG"}}'


def test_re_promoting_does_not_clobber_the_original_snapshot(tmp_path):
    """The first snapshot is the only unrepaired version there will ever be."""
    (tmp_path / "assays.json").write_text('{"a": {"platform": "WRONG"}}')
    (tmp_path / "assays_corrected.json").write_text('{"a": {"platform": null}}')
    promote_registry(tmp_path)
    (tmp_path / "assays_corrected.json").write_text('{"a": {"platform": "SECOND"}}')

    result = promote_registry(tmp_path)

    assert result["snapshot_written"] is False
    assert (tmp_path / "assays_precorrection.json").read_text() == '{"a": {"platform": "WRONG"}}'


def test_promoting_with_nothing_corrected_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        promote_registry(tmp_path)


# ── the paper sits in a shared prefix, and the calls run at once ──────────────

def test_the_paper_is_the_same_prefix_for_every_question():
    """Everything up to and including the source text is byte-identical across questions.

    That prefix is what a provider's automatic prompt caching keys on, so the assay name and
    the question have to come after the paper, not before it. A per-field value above the
    source text makes every correction call a cache miss on the bulk of the prompt.
    """
    prompts = [build_prompt(_entry(), group, _SOURCE, "Paper")
               for group in ("sample_type", "readouts", "aliases", "evidence")]

    heads = {p[: p.index(_SOURCE) + len(_SOURCE)] for p in prompts}
    assert len(heads) == 1, "the paper is not in a shared prefix"

    tail = len(next(iter(heads)))
    assert all(p.index("## The question") >= tail for p in prompts)


def test_correct_prompt_leaves_no_placeholder_unrendered():
    prompt = build_prompt(_entry(), "sample_type", _SOURCE, "Paper")
    for token in ("{assay_name}", "{locator}", "{question}", "{paper_title}", "{source_text}"):
        assert token not in prompt


class _RecordingClient:
    """Records every prompt handed to it, and how many calls overlapped in flight."""

    def __init__(self, body: str, delays: list[float] | None = None):
        self.prompts: list[str] = []
        self.in_flight = 0
        self.peak_in_flight = 0
        outer = self

        class _Completions:
            async def create(self, **kwargs):
                outer.prompts.append(kwargs["messages"][0]["content"])
                outer.in_flight += 1
                outer.peak_in_flight = max(outer.peak_in_flight, outer.in_flight)
                delay = (delays or [0.0])[(len(outer.prompts) - 1) % len(delays or [0.0])]
                await asyncio.sleep(delay)
                outer.in_flight -= 1
                message = type("M", (), {"content": body})()
                return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

        self.chat = type("Chat", (), {"completions": _Completions()})()


def _flagged(*keys, field: str = "sample_type") -> dict:
    return {"results": [
        {"assay_id": key, "record_verdict": "REVIEW",
         "field_verifications": [{"field_name": field, "verdict": "NOT_SUPPORTED",
                                  "reason": "..."}]}
        for key in keys
    ]}


_BLIND_BODY = json.dumps({"value": "whole blood", "sentence_ids": ["S1"], "reason": "..."})


@pytest.mark.asyncio
async def test_corrected_registry_keeps_registry_order_when_calls_finish_out_of_order():
    """The first call finishes last; neither the registry nor the records may follow that."""
    keys = ("flow cytometry", "ELISA", "microarray")
    assays = {key: _entry(name_in_paper=key) for key in keys}
    client = _RecordingClient(_BLIND_BODY, delays=[0.03, 0.0, 0.0])

    corrected, records = await correct_registry(
        assays, _flagged(*keys), _SOURCE, "Paper", client)

    assert list(corrected) == list(keys)
    assert [r["assay_id"] for r in records] == list(keys)
    assert all(entry["sample_type"] == "whole blood" for entry in corrected.values())
    assert client.peak_in_flight > 1, "calls did not actually overlap"


@pytest.mark.asyncio
async def test_correction_concurrency_never_exceeds_the_bound():
    keys = tuple(f"assay {i}" for i in range(7))
    assays = {key: _entry(name_in_paper=key) for key in keys}
    client = _RecordingClient(_BLIND_BODY, delays=[0.01])

    await correct_registry(assays, _flagged(*keys), _SOURCE, "Paper", client,
                           max_concurrency=2)
    assert client.peak_in_flight == 2


@pytest.mark.asyncio
async def test_every_field_is_asked_against_the_entry_as_extraction_left_it():
    """No correction may be visible to another correction's prompt.

    `_locator` quotes the entry's evidence, so a repaired quote landing mid-run would change
    what a later field is asked about. Running the calls first and writing after is what
    guarantees that, rather than `_QUESTIONS` happening to order evidence last.
    """
    original_quote = _entry()["evidence"]["quote"]
    verification = {"results": [{
        "assay_id": "flow cytometry", "record_verdict": "REVIEW",
        "field_verifications": [
            {"field_name": "sample_type", "verdict": "NOT_SUPPORTED", "reason": "..."},
            {"field_name": "evidence.quote", "verdict": "NOT_SUPPORTED", "reason": "..."},
        ],
    }]}
    body = json.dumps({"value": "PBMCs were thawed and rested overnight.", "sentence_ids": ["S2"], "reason": "..."})
    client = _RecordingClient(body)

    corrected, _ = await correct_registry(
        {"flow cytometry": _entry()}, verification, _SOURCE, "Paper", client)

    # The evidence quote really was replaced...
    assert corrected["flow cytometry"]["evidence"]["quote"] == "PBMCs were thawed and rested overnight."
    # ...and the specimen question was still asked against the quote extraction wrote.
    specimen_prompt = next(p for p in client.prompts if "tissue or specimen" in p)
    assert original_quote in specimen_prompt


# ── A bare-list alias answer is the answer, not an error ──────────────────────

class _CannedClient:
    """Returns one canned body, verbatim."""

    def __init__(self, body: str):
        outer = self

        class _Completions:
            async def create(self, **_kwargs):
                message = type("M", (), {"content": body})()
                return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

        self.chat = type("Chat", (), {"completions": _Completions()})()


@pytest.mark.asyncio
async def test_an_unwrapped_alias_list_is_used_rather_than_discarded():
    """The prompt asks for {"value": ...}; the aliases question asks for "a JSON list".

    A model following the question literally returned the bare list, and the strict parser threw
    away a call already paid for -- 12 of 41 alias re-extractions across the corpus, every ERROR
    in it. The entry then kept exactly the aliases the verifier had objected to.
    """
    from app.agent.assay_corrector import correct_field

    value, error = await correct_field(
        _entry(), "aliases", _SOURCE, "Paper", _CannedClient('["FACS", "flow cytometry"]'))

    assert error is None
    assert value == ["FACS", "flow cytometry"]


@pytest.mark.asyncio
async def test_the_wrapped_shape_still_works():
    from app.agent.assay_corrector import correct_field

    value, error = await correct_field(
        _entry(), "aliases", _SOURCE, "Paper",
        _CannedClient('{"value": ["FACS"], "sentence_ids": ["S1"], "reason": "ok"}'))

    assert error is None
    assert value == ["FACS"]


@pytest.mark.asyncio
async def test_a_bare_list_for_evidence_still_errors():
    """Its sentence_ids come from a sibling key, not from `value`.

    Coercing would yield {"quote": None, "sentence_ids": []} -> CLEARED -> remapped to
    UNCHANGED, which reads as "checked, nothing to change" when nothing was checked.
    """
    from app.agent.assay_corrector import correct_field

    value, error = await correct_field(
        _entry(), "evidence", _SOURCE, "Paper", _CannedClient('["some quote"]'))

    assert value is None
    assert error == "corrector returned list, not an object"


@pytest.mark.asyncio
async def test_a_bare_list_for_a_scalar_field_still_errors():
    """A list is not an answer to "what specimen was this assay performed on"."""
    from app.agent.assay_corrector import correct_field

    value, error = await correct_field(
        _entry(), "sample_type", _SOURCE, "Paper", _CannedClient('["PBMCs", "serum"]'))

    assert value is None
    assert error == "corrector returned list, not an object"


def test_the_aliases_question_names_the_field_it_wants_the_list_in():
    """The wording that invited the bare list in the first place."""
    from app.agent.assay_corrector import _QUESTIONS

    assert "`value`" in _QUESTIONS["aliases"]
    assert "do not return it on its own" in _QUESTIONS["aliases"]


def test_the_technique_has_no_repair_question():
    """Nothing to re-extract: no blind question about the paper can recover a technique
    judgement, and the verifier never flags it anyway (it is in _NOT_PROPOSED). field_group
    returning None is what keeps a future schema field from silently acquiring a wrong
    corrector question -- pinned here so the eighth field's arrival stays deliberate."""
    assert field_group("standard_technique_name") is None


# ── evidence is compared quote to quote ───────────────────────────────────────

def test_an_identical_re_extracted_quote_is_reaffirmed():
    """The blind answer is {"quote", "sentence_ids"}; the value on file is the quote string.
    Comparing the two whole meant an identical quote never read as REAFFIRMED."""
    entry = _entry()
    blind = {"quote": entry["evidence"]["quote"], "sentence_ids": ["S1"]}

    assert apply_correction(entry, "evidence", blind, _SOURCE)["action"] == REAFFIRMED


def test_a_verbatim_quote_with_wrong_ids_lands_with_the_ids_it_was_found_in():
    entry = _entry()
    blind = {"quote": "PBMCs were thawed and rested overnight.", "sentence_ids": ["S9"]}

    record = apply_correction(entry, "evidence", blind, _SOURCE)

    assert record["action"] == REPLACED
    assert entry["evidence"]["sentence_ids"] == ["S2"]
    assert "sentence_ids set" in record["note"]


def test_a_pdf_replacement_quote_drops_the_ids_it_invented():
    source = "Cells were analyzed on the LSRII flow cytometer (BD). PBMCs were thawed overnight."
    entry = _entry()
    blind = {"quote": "PBMCs were thawed overnight.", "sentence_ids": ["S2"]}

    record = apply_correction(entry, "evidence", blind, source)

    assert record["action"] == REPLACED
    assert entry["evidence"]["sentence_ids"] == []


# ── a failed call is not an answer ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_empty_reply_is_an_error_not_a_cleared_field():
    """Read as `{}` an empty body became `value: None`, which decide() scores as CLEARED: a
    specimen the paper states, wiped because one call returned nothing. The verifier draws the
    same line."""
    value, error = await correct_field(_entry(), "sample_type", _SOURCE, "A Paper",
                                       _CannedClient(""))

    assert value is None
    assert error == "corrector returned an empty reply"


@pytest.mark.asyncio
async def test_an_empty_reply_leaves_the_registry_entry_as_it_was():
    corrected, records = await correct_registry(
        {"flow cytometry": _entry()}, {"results": [{"assay_id": "flow cytometry",
                                                   **_verification(("sample_type", "NOT_SUPPORTED"))}]},
        _SOURCE, "A Paper", _CannedClient(""))

    assert corrected["flow cytometry"]["sample_type"] == "PBMCs"
    assert records[0]["corrections"][0]["action"] == "ERROR"


def test_a_bare_string_alias_answer_is_one_alias_not_its_letters():
    """Iterating "FACS analysis" as-is read it as a bag of characters, none of which matched
    the flagged alias it had just confirmed, so the alias was dropped."""
    entry = _entry()

    record = apply_correction(entry, "aliases", "FACS analysis", _SOURCE, flagged_aliases={0, 1})

    assert entry["aliases"] == ["FACS analysis"]
    assert record["dropped"] == ["Flow cytometry"]
