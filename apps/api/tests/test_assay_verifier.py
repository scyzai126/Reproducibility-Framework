import asyncio
import json

import pytest

from app.agent.assay_verifier import (
    ACCEPT,
    CONTRADICTED,
    NOT_REPORTED,
    NOT_SUPPORTED,
    REJECT,
    REVIEW,
    SUPPORTED,
    build_summary,
    check_alias_verbatim,
    check_quote_verbatim,
    check_source_section,
    derive_record_verdict,
    get_evidence,
    get_name,
    identity_reviews,
    mark_identity_reviews,
    proposed_fields,
    sentence_index,
    verify_assay,
    verify_registry,
)

SOURCE = (
    "## Materials and Methods\n"
    "[S1] PBMCs were thawed and rested overnight. "
    "[S2] Cells were acquired on a BD LSRFortessa flow cytometer. "
    "[S3] Serum antibody titers were measured by ELISA.\n"
    "## Results\n"
    "[S4] Frequencies of IFN-g producing cells rose by day 7.\n"
)

ENTRY = {
    "name_in_paper": "flow cytometry",
    "aliases": ["FACS"],
    "sample_type": "PBMCs",
    "readouts": "cytokine-producing cell frequencies",
    "source": "methods",
    "evidence": {
        "section": "Materials and Methods",
        "sentence_ids": ["S2"],
        "quote": "Cells were acquired on a BD LSRFortessa flow cytometer.",
    },
}


def test_sentence_index_maps_ids_to_text_without_markers():
    index = sentence_index(SOURCE)

    assert index["S1"] == "PBMCs were thawed and rested overnight."
    assert "[S" not in index["S2"]
    assert "BD LSRFortessa" in index["S2"]


def test_quote_check_accepts_a_verbatim_quote_from_the_cited_sentence():
    check = check_quote_verbatim(ENTRY, SOURCE)

    assert check["status"] == "found"
    assert check["verdict"] == SUPPORTED


def test_quote_check_contradicts_a_fabricated_quote():
    entry = {**ENTRY, "evidence": {**ENTRY["evidence"],
                                   "quote": "Cells were acquired on a NovaSeq 6000."}}

    check = check_quote_verbatim(entry, SOURCE)

    assert check["status"] == "missing"
    assert check["verdict"] == CONTRADICTED


def test_quote_check_rejects_a_quote_lifted_from_an_uncited_sentence():
    """A real sentence is still wrong evidence when it is not the one cited -- but it is a
    miscitation, not a fabrication, and the sentence that does hold it is reported."""
    entry = {**ENTRY, "evidence": {**ENTRY["evidence"],
                                   "quote": "Serum antibody titers were measured by ELISA."}}

    check = check_quote_verbatim(entry, SOURCE)

    assert check["status"] == "misattributed"
    assert check["verdict"] == NOT_SUPPORTED
    assert check["located_ids"] == ["S3"]


def test_quote_check_tolerates_whitespace_and_line_breaks():
    entry = {**ENTRY, "evidence": {**ENTRY["evidence"],
                                   "quote": "Cells were acquired\n   on a BD LSRFortessa"}}

    assert check_quote_verbatim(entry, SOURCE)["status"] == "found"


def test_quote_check_tolerates_parser_inserted_spacing():
    """The JATS parser writes "( Figure 4 )"; a faithful quote says "(Figure 4)".

    Comparing on whitespace flagged 36 of 156 corpus entries as fabricated, almost all of
    them this one artifact.
    """
    source = "[S1] Transcripts correlated with the antibody response ( Figure 4 ) in both arms."
    entry = {"name_in_paper": "microarray",
             "evidence": {"sentence_ids": ["S1"],
                          "quote": "correlated with the antibody response (Figure 4)"}}

    assert check_quote_verbatim(entry, source)["status"] == "found"


def test_quote_check_tolerates_typographic_dash_variants():
    """Papers use U+2010 HYPHEN; a model retyping the sentence writes ASCII "-"."""
    source = "[S1] Diagnosis was confirmed by real\u2010time RT\u2013PCR in the acute sample."
    entry = {"name_in_paper": "real-time RT-PCR",
             "evidence": {"sentence_ids": ["S1"],
                          "quote": "confirmed by real-time RT-PCR in the acute sample"}}

    assert check_quote_verbatim(entry, source)["status"] == "found"


def test_quote_check_still_catches_a_reconstructed_quote():
    """Normalizing typography must not excuse two fragments spliced with an ellipsis."""
    source = "[S1] Expression profiles of 594 genes were measured across all donors. "\
             "[S2] Of these, 211 were found to change significantly after vaccination."
    entry = {"name_in_paper": "gene array",
             "evidence": {"sentence_ids": ["S1"],
                          "quote": "Expression profiles of 594 genes ... were found to "
                                   "change significantly"}}

    check = check_quote_verbatim(entry, source)
    assert check["status"] == "misattributed"
    assert check["verdict"] != SUPPORTED


def test_quote_check_tolerates_a_trailing_period_the_excerpt_added():
    """Truncating a clause and closing it with a period is quoting, not fabricating."""
    source = "[S1] Frequencies rose in the elderly cohort ( Fig. 3b, p = 0.01 ) at day 7."
    entry = {"name_in_paper": "flow cytometry",
             "evidence": {"sentence_ids": ["S1"],
                          "quote": "Frequencies rose in the elderly cohort."}}

    check = check_quote_verbatim(entry, source)

    assert check["status"] == "found"
    assert "trailing punctuation" in check["detail"]


def test_quote_check_on_a_numbered_source_requires_sentence_ids():
    """A sentence-numbered source can be cited, so an entry that cites nothing is misattributed
    -- verbatim, but untraceable -- and the ids it should have carried are recovered."""
    entry = {
        "name_in_paper": "ELISA",
        "evidence_location": {"type": "text", "section": "Methods",
                              "quote": "Serum antibody titers were measured by ELISA."},
    }

    check = check_quote_verbatim(entry, SOURCE)

    assert check["status"] == "misattributed"
    assert check["located_ids"] == ["S3"]


def test_quote_check_searches_the_whole_document_when_the_source_has_no_markers():
    """A PDF text layer has no [S<n>] markers, so no ids is the correct citation there."""
    entry = {"evidence": {"sentence_ids": [],
                          "quote": "Serum antibody titers were measured by ELISA."}}

    check = check_quote_verbatim(entry, "Serum antibody titers were measured by ELISA.")

    assert check["status"] == "found"
    assert "whole document" in check["detail"]


def test_quote_check_on_a_source_without_markers_refuses_invented_ids():
    entry = {"evidence": {"sentence_ids": ["S4"],
                          "quote": "Serum antibody titers were measured by ELISA."}}

    check = check_quote_verbatim(entry, "Serum antibody titers were measured by ELISA.")

    assert check["status"] == "misattributed"
    assert check["located_ids"] == []


def test_quote_check_flags_a_sentence_id_that_does_not_exist():
    entry = {**ENTRY, "evidence": {**ENTRY["evidence"], "sentence_ids": ["S999"]}}

    check = check_quote_verbatim(entry, SOURCE)

    assert check["unknown_sentence_ids"] == ["S999"]
    # Verbatim, so not a fabrication -- but an id the source lacks is not a citation.
    assert check["status"] == "misattributed"
    assert check["verdict"] == NOT_SUPPORTED
    assert check["located_ids"] == ["S2"]


def test_a_quote_too_short_to_pin_down_is_not_supported():
    """"ELISA ... performed" matches almost any paper once whitespace is ignored."""
    source = "[S1] Antibodies were measured by ELISA and the assay was performed in duplicate."
    entry = {"evidence": {"sentence_ids": ["S1"], "quote": "ELISA ... performed"}}

    check = check_quote_verbatim(entry, source)

    assert check["status"] == "too_short"
    assert check["verdict"] == NOT_SUPPORTED


def test_a_quote_of_nothing_but_an_ellipsis_is_not_found():
    entry = {"evidence": {"sentence_ids": ["S1"], "quote": "..."}}

    assert check_quote_verbatim(entry, SOURCE)["status"] != "found"


def test_quote_check_reports_an_entry_with_no_quote_at_all():
    check = check_quote_verbatim({"name_in_paper": "ELISA"}, SOURCE)

    assert check["status"] == "no_quote"
    assert check["verdict"] is None


def test_old_schema_entries_are_read_under_their_own_field_names():
    entry = {
        "original_name": "gene array",
        "confidence": 0.95,
        "claim_role": "primary",
        "evidence_location": {"type": "text", "section": "Results", "quote": "q"},
    }

    assert get_name("gene array", entry) == "gene array"
    assert get_evidence(entry)["section"] == "Results"

    fields = dict(proposed_fields(entry))
    assert "original_name" in fields
    assert "evidence_location.quote" in fields
    # Removed on purpose by the current schema, so not values to verify.
    assert "confidence" not in fields and "claim_role" not in fields


def test_registry_key_is_the_name_when_no_name_field_exists():
    """The claims-derived registries carry only sample_type and readouts."""
    assert get_name("Bulk RNA-seq", {"sample_type": "whole blood"}) == "Bulk RNA-seq"


def test_proposed_fields_enumerates_aliases_and_skips_nulls():
    entry = {**ENTRY, "aliases": ["FACS", "flow"], "platform": None}

    fields = dict(proposed_fields(entry))

    assert fields["aliases[0]"] == "FACS"
    assert fields["aliases[1]"] == "flow"
    assert "platform" not in fields
    assert fields["evidence.quote"] == ENTRY["evidence"]["quote"]


def test_the_derived_sentence_ids_are_never_sent_for_verification():
    """They are derived from the quote by code, so there is nothing for a judge to rule on.

    The prompt has told the judge to skip them for a while; this set had not, so every entry of
    an XML paper came back NOT_REPORTED on the field, derive_record_verdict forced the record to
    REVIEW, and assay_corrector.field_group billed one round-3 evidence correction per assay for
    a value nobody had objected to. Measured on SDY1264 and SDY1669: 9/9 REVIEW on both.
    """
    entry = {**ENTRY, "evidence": {**ENTRY["evidence"], "sentence_ids": ["S2"]}}

    fields = dict(proposed_fields(entry))

    assert "evidence.sentence_ids" not in fields
    # The quote is still verified: whether it appears verbatim is round 2's core check.
    assert "evidence.quote" in fields


def test_an_old_registrys_evidence_location_ids_are_held_back_too():
    """Registries on disk spell it `evidence_location`; the flattened name is what is checked,
    so the other spelling has to be in the set as well or it slips straight past."""
    entry = {"name_in_paper": "ELISA",
             "evidence_location": {"quote": "Titers were measured by ELISA.",
                                   "sentence_ids": ["S7"]}}

    fields = dict(proposed_fields(entry))

    assert "evidence_location.sentence_ids" not in fields
    assert "evidence_location.quote" in fields


def test_a_record_with_every_field_supported_reaches_accept():
    """The regression this guards: one unanswerable field is enough to hold every record at
    REVIEW, which leaves the verdict carrying no information at all."""
    supported = [{"field_name": f, "verdict": SUPPORTED}
                 for f in ("name_in_paper", "sample_type", "evidence.quote")]

    assert derive_record_verdict(SUPPORTED, supported) == ACCEPT


def test_the_technique_is_never_verified_against_the_paper():
    """It is a judgement about the technique, not a claim about the text.

    Every other field reports something the paper states, so the verifier can ask whether the
    text supports it. `standard_technique_name` is expected to use words the paper never wrote -- that
    is the whole reason it exists, since "Surface and intracellular cytokine staining" has to
    become "flow cytometry" to retrieve the right OBI term. Verifying it would draw a
    NOT_SUPPORTED on nearly every entry and bury round 2 in REVIEW lines for working output.
    """
    entry = {**ENTRY, "standard_technique_name": "flow cytometry"}

    assert "standard_technique_name" not in dict(proposed_fields(entry))


def test_generate_claim_is_never_a_proposed_field():
    """The other judgement field, and excluded for the same reason as technique.

    "The paper reports no finding drawn from this assay" is a statement about the whole paper;
    no single span supports or contradicts it, so a judge asked to rule can only guess. Keeping
    it out is also what keeps it free -- a flagged field bills one correction call each, so
    verifying it would cost up to one call per assay in round 3.
    """
    for answer in (True, False):
        assert "generate_claim" not in dict(proposed_fields({**ENTRY, "generate_claim": answer}))


def test_record_verdict_derivation():
    ok = [{"verdict": SUPPORTED}, {"verdict": SUPPORTED}]

    assert derive_record_verdict(SUPPORTED, ok) == ACCEPT
    assert derive_record_verdict(CONTRADICTED, ok) == REJECT
    assert derive_record_verdict(NOT_SUPPORTED, ok) == REVIEW
    assert derive_record_verdict(SUPPORTED, [{"verdict": CONTRADICTED}]) == REVIEW
    # A field nobody answered for has not been cleared.
    assert derive_record_verdict(SUPPORTED, [{"verdict": NOT_REPORTED}]) == REVIEW
    # A value the extraction proposed and the judge declined to support is a defect.
    assert derive_record_verdict(SUPPORTED, [{"verdict": NOT_SUPPORTED}]) == REVIEW


def test_an_unstated_field_is_compliance_and_still_reaches_accept():
    """The absence case is a field that produces no verification at all, not one verdicted
    NOT_SUPPORTED: proposed_fields skips nulls, so absence never reaches the judge."""
    entry = {"name_in_paper": "ELISA", "platform": None, "sample_type": "serum"}

    assert [f for f, _ in proposed_fields(entry)] == ["name_in_paper", "sample_type"]
    assert derive_record_verdict(
        SUPPORTED, [{"verdict": SUPPORTED}, {"verdict": SUPPORTED}]
    ) == ACCEPT


class _FakeClient:
    """Minimal stand-in for AsyncOpenAI: returns a canned body, or raises."""

    def __init__(self, body: str | None = None, error: Exception | None = None):
        self._body, self._error = body, error
        outer = self

        class _Completions:
            async def create(self, **_kwargs):
                if outer._error:
                    raise outer._error
                message = type("M", (), {"content": outer._body})()
                return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

        self.chat = type("Chat", (), {"completions": _Completions()})()


@pytest.mark.asyncio
async def test_verify_assay_reports_a_field_the_judge_skipped():
    body = json.dumps({
        "assay_identity_verdict": SUPPORTED,
        "field_verifications": [
            {"field_name": "name_in_paper", "proposed_value": "flow cytometry",
             "verdict": SUPPORTED, "reason": "stated in Methods"},
            {"field_name": "readouts", "proposed_value": "cytokine-producing cell frequencies",
             "verdict": SUPPORTED, "reason": "named in S4"},
        ],
        "record_verdict": ACCEPT,
    })

    result = await verify_assay("flow cytometry", ENTRY, SOURCE, "Paper", _FakeClient(body))

    by_name = {v["field_name"]: v for v in result["field_verifications"]}
    assert by_name["readouts"]["verdict"] == SUPPORTED
    assert by_name["sample_type"]["verdict"] == NOT_REPORTED
    # Skipped fields keep the record out of ACCEPT even though the judge asked for it.
    assert result["record_verdict"] == REVIEW
    assert result["model_record_verdict"] == ACCEPT


@pytest.mark.asyncio
async def test_deterministic_quote_check_overrides_the_judge():
    entry = {**ENTRY, "evidence": {**ENTRY["evidence"], "quote": "acquired on a NovaSeq 6000"}}
    body = json.dumps({
        "assay_identity_verdict": SUPPORTED,
        "field_verifications": [
            {"field_name": "evidence.quote", "proposed_value": "acquired on a NovaSeq 6000",
             "verdict": SUPPORTED, "reason": "looks fine to me"},
        ],
        "record_verdict": ACCEPT,
    })

    result = await verify_assay("flow cytometry", entry, SOURCE, "Paper", _FakeClient(body))

    quote = next(v for v in result["field_verifications"] if v["field_name"] == "evidence.quote")
    assert quote["verdict"] == CONTRADICTED
    assert result["record_verdict"] == REVIEW


@pytest.mark.asyncio
async def test_a_failed_call_becomes_an_error_record_rather_than_raising():
    result = await verify_assay(
        "flow cytometry", ENTRY, SOURCE, "Paper", _FakeClient(error=RuntimeError("boom"))
    )

    assert result["record_verdict"] == "ERROR"
    assert "boom" in result["error"]
    assert all(v["verdict"] == NOT_REPORTED for v in result["field_verifications"])


@pytest.mark.asyncio
async def test_unparseable_response_becomes_an_error_record():
    result = await verify_assay("flow cytometry", ENTRY, SOURCE, "Paper", _FakeClient("not json"))

    assert result["record_verdict"] == "ERROR"


def test_summary_tallies_alias_positions_together():
    results = [
        {"record_verdict": REVIEW, "quote_check": {"status": "found"},
         "field_verifications": [
             {"field_name": "aliases[0]", "verdict": CONTRADICTED},
             {"field_name": "aliases[2]", "verdict": CONTRADICTED},
             {"field_name": "sample_type", "verdict": SUPPORTED},
         ]},
        {"record_verdict": ACCEPT, "quote_check": {"status": "missing"},
         "field_verifications": [{"field_name": "aliases[0]", "verdict": NOT_SUPPORTED}]},
    ]

    summary = build_summary(results)

    assert summary["field_issues"]["aliases[]"] == {CONTRADICTED: 2, NOT_SUPPORTED: 1}
    assert "sample_type" not in summary["field_issues"]
    assert summary["quotes_missing"] == 1
    assert summary["review"] == 1 and summary["accept"] == 1


def test_a_quote_that_elides_its_own_middle_is_still_verbatim():
    """Excerpting with " ... " is a quoting convention, not a fabrication -- comparing the
    joined string produced the one false MISSING in a 156-entry corpus survey."""
    source = ("[S1] Expression profiles of 594 genes, measured across five seasons, were "
              "found to change significantly after vaccination.")
    entry = {"evidence": {"sentence_ids": ["S1"], "quote":
             "Expression profiles of 594 genes ... were found to change significantly"}}

    assert check_quote_verbatim(entry, source)["status"] == "found"


def test_elided_fragments_found_out_of_order_are_not_verbatim():
    """Order is required: two spans found back-to-front are not a faithful excerpt, and
    accepting them would trade the false positive for a false negative."""
    source = "[S1] Expression profiles of 594 genes were found to change significantly."
    entry = {"evidence": {"sentence_ids": ["S1"], "quote":
             "were found to change significantly ... Expression profiles of 594 genes"}}

    assert check_quote_verbatim(entry, source)["status"] == "missing"


def test_a_fabricated_quote_is_not_rescued_by_an_ellipsis():
    source = "[S1] Cells were analyzed on the LSRII flow cytometer (BD)."
    entry = {"evidence": {"sentence_ids": ["S1"], "quote":
             "Cells were analyzed ... on a NovaSeq 6000"}}

    result = check_quote_verbatim(entry, source)
    assert result["status"] == "missing"
    assert result["verdict"] == CONTRADICTED


def test_source_methods_is_aligned_when_its_evidence_sits_in_methods():
    entry = {"source": "methods", "evidence": {"sentence_ids": ["S2"], "quote": "x"}}

    assert check_source_section(entry, {"S1": "results", "S2": "methods"})["status"] == "aligned"


def test_source_methods_is_a_mismatch_when_its_evidence_sits_in_results():
    """The classification pass claimed Methods established the technique; the sentence it
    cites is in Results. Either the structure was misread or the evidence points elsewhere."""
    entry = {"source": "methods", "evidence": {"sentence_ids": ["S1"], "quote": "x"}}

    result = check_source_section(entry, {"S1": "results", "S2": "methods"})

    assert result["status"] == "mismatch"
    assert "S1 in [results]" in result["detail"]


def test_source_results_is_a_mismatch_only_when_every_sentence_is_in_methods():
    sections = {"S1": "results", "S2": "methods"}

    assert check_source_section(
        {"source": "results", "evidence": {"sentence_ids": ["S2"]}}, sections
    )["status"] == "mismatch"
    # One Methods sentence quoted alongside a Results one is not a wrong classification.
    assert check_source_section(
        {"source": "results", "evidence": {"sentence_ids": ["S1", "S2"]}}, sections
    )["status"] == "aligned"


def test_captions_and_other_sections_support_a_results_source():
    """`other` is a Results section the publisher did not label; captions sit with Results."""
    sections = {"S1": "other", "S2": "captions"}

    for sid in ("S1", "S2"):
        entry = {"source": "results", "evidence": {"sentence_ids": [sid]}}
        assert check_source_section(entry, sections)["status"] == "aligned"


def test_an_entry_the_map_cannot_place_is_unknown_not_a_mismatch():
    """Most registries on disk predate sentence_ids and `source`; they must pass quietly."""
    sections = {"S1": "methods"}

    assert check_source_section({"source": "methods", "evidence": {}}, sections)["status"] == "unknown"
    assert check_source_section({"evidence": {"sentence_ids": ["S1"]}}, sections)["status"] == "unknown"
    assert check_source_section(
        {"source": "methods", "evidence": {"sentence_ids": ["S99"]}}, sections
    )["status"] == "unknown"


# ── the paper sits in a shared prefix, and the calls run at once ──────────────

class _RecordingClient:
    """Records every prompt it is handed, and how many calls overlapped in flight.

    `delays` staggers completion so a test can tell "results came back in order" apart from
    "results were never reordered because nothing ran concurrently".
    """

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


_VERDICT_BODY = json.dumps({
    "assay_identity_verdict": SUPPORTED,
    "field_verifications": [],
    "record_verdict": ACCEPT,
})


def _registry(*names) -> dict:
    return {name: dict(ENTRY, name_in_paper=name) for name in names}


@pytest.mark.asyncio
async def test_the_paper_is_the_same_prefix_for_every_assay_in_a_registry():
    """Everything up to and including the source text must be byte-identical across calls.

    That prefix is what a provider's automatic prompt caching keys on. Putting a per-assay
    value above the paper -- which is where `section_name` used to sit -- makes every call a
    cache miss on the largest part of the prompt, so this is a cost contract, not a style one.
    """
    client = _RecordingClient(_VERDICT_BODY)
    await verify_registry(_registry("flow cytometry", "ELISA"), SOURCE, "Paper", client)

    assert len(client.prompts) == 2
    heads = {p[: p.index(SOURCE) + len(SOURCE)] for p in client.prompts}
    assert len(heads) == 1, "the paper is not in a shared prefix"
    # ...and the per-assay parts really do come after it.
    tail = len(next(iter(heads)))
    assert all(p.index("SECTION THE EXTRACTION CITED") >= tail for p in client.prompts)
    assert all(p.index("CANDIDATE ASSAY EXTRACTION") >= tail for p in client.prompts)


@pytest.mark.asyncio
async def test_verify_prompt_leaves_no_placeholder_unrendered():
    client = _RecordingClient(_VERDICT_BODY)
    await verify_registry(_registry("flow cytometry"), SOURCE, "Paper", client)
    for token in ("{paper_title}", "{section_name}", "{source_text}", "{candidate}"):
        assert token not in client.prompts[0]


@pytest.mark.asyncio
async def test_results_keep_registry_order_when_calls_finish_out_of_order():
    """The first call finishes last; the results must not follow completion order."""
    client = _RecordingClient(_VERDICT_BODY, delays=[0.03, 0.0, 0.0])
    names = ("flow cytometry", "ELISA", "microarray")
    results = await verify_registry(_registry(*names), SOURCE, "Paper", client)

    assert [r["assay_id"] for r in results] == list(names)
    assert client.peak_in_flight > 1, "calls did not actually overlap"


@pytest.mark.asyncio
async def test_concurrency_never_exceeds_the_bound():
    client = _RecordingClient(_VERDICT_BODY, delays=[0.01])
    names = tuple(f"assay {i}" for i in range(7))
    await verify_registry(_registry(*names), SOURCE, "Paper", client, max_concurrency=2)
    assert client.peak_in_flight == 2


# ── The section check outranks the judge on `source` ──────────────────────────

_SOURCE_ENTRY = {
    "name_in_paper": "phosphoflow analysis", "aliases": [], "platform": None,
    "sample_type": "PBMC", "readouts": "STAT phosphorylation", "source": "methods",
    "evidence": {"section": "Phosphorylation of intracellular proteins",
                 "sentence_ids": ["S10"], "quote": "cell subset frequencies and function"},
}


def _judge_says_every_field_is_fine() -> str:
    """A verifier answer that supports every field the extraction still proposes."""
    return json.dumps({
        "assay_id": "phosphoflow analysis", "assay_identity_verdict": "SUPPORTED",
        "field_verifications": [
            {"field_name": f, "verdict": "SUPPORTED", "reason": "ok"}
            for f in ("name_in_paper", "sample_type", "readouts", "evidence.quote")],
        "conflict_detected": False, "record_verdict": "ACCEPT",
    })


def test_source_is_derived_from_where_the_quote_sits_not_asked_for():
    """`source` used to be extracted and then overruled by this same arithmetic.

    The real SDY212 defect was source "methods" on evidence sitting in [results], which the judge
    called fine. Deriving it removes the disagreement rather than adjudicating it.
    """
    from app.agent.assay_verifier import derive_evidence_fields

    source_text = "## Results  [results]\n[S10] cell subset frequencies and function were assessed."
    assays = {"phosphoflow analysis": {
        "name_in_paper": "phosphoflow analysis",
        "source": "methods",          # a stale value, or one a model volunteered
        "evidence": {"section": "Methods", "sentence_ids": [],
                     "quote": "cell subset frequencies and function"},
    }}

    derive_evidence_fields(assays, source_text)
    entry = assays["phosphoflow analysis"]
    assert entry["source"] == "results", "the document must outrank the proposed value"
    assert entry["evidence"]["sentence_ids"] == ["S10"], "ids come from locating the quote"


def test_a_methods_quote_derives_methods():
    from app.agent.assay_verifier import derive_evidence_fields

    source_text = ("## Materials and Methods  [methods]\n"
                   "[S10] cell subset frequencies and function were assessed.")
    assays = {"phosphoflow analysis": {
        "evidence": {"section": "Methods", "sentence_ids": [], "quote": "frequencies and function"},
    }}

    derive_evidence_fields(assays, source_text)
    assert assays["phosphoflow analysis"]["source"] == "methods"


def test_a_quote_that_cannot_be_placed_derives_nothing_rather_than_guessing():
    """A PDF text layer carries no markers, and "methods" is the stronger claim to assert blindly."""
    from app.agent.assay_verifier import derive_evidence_fields

    assays = {"phosphoflow analysis": {
        "evidence": {"section": "Methods", "sentence_ids": [], "quote": "nowhere in this paper"},
    }}

    derive_evidence_fields(assays, "## Results  [results]\n[S10] unrelated text.")
    entry = assays["phosphoflow analysis"]
    assert entry["source"] is None
    assert entry["evidence"]["sentence_ids"] == []


def test_source_is_no_longer_a_field_the_judge_is_asked_about():
    """It is derived, so asking the judge to rule on it would be second-guessing arithmetic."""
    from app.agent.assay_verifier import proposed_fields as _proposed

    fields = dict(_proposed({**ENTRY, "source": "methods"}))
    assert "source" not in fields
    assert "sample_type" in fields


def test_removed_fields_on_an_older_registry_are_not_proposed_values():
    """A registry written before the trim still carries these; none is a value to verify."""
    entry = {**ENTRY, "measurement_role": "sub_step", "parent_hint": "LC-MS",
             "platform": "BD LSRFortessa"}

    fields = dict(proposed_fields(entry))
    assert "measurement_role" not in fields
    assert "parent_hint" not in fields


# ── a canonical registry's entries ───────────────────────────────────────────

def test_get_name_reads_the_first_wording_of_a_canonical_entry():
    """After round 5 `name_in_paper` is a list and the key is an OBI label, which is not what
    the paper called anything."""
    entry = {"name_in_paper": ["ELISA", "ELISA kits"], "aliases": []}

    assert get_name("enzyme-linked immunosorbent assay", entry) == "ELISA"


def test_get_name_falls_back_to_the_key_past_an_empty_list():
    assert get_name("ELISA", {"name_in_paper": [], "aliases": []}) == "ELISA"


def test_additional_evidence_is_never_a_proposed_field():
    """Round 5 writes other entries' records there; nobody proposed it for this one."""
    entry = {"name_in_paper": "ELISA", "aliases": [], "sample_type": "serum",
             "additional_evidence": [{"name_in_paper": "ELISA kits"}]}

    assert [f for f, _ in proposed_fields(entry)] == ["name_in_paper", "sample_type"]


# ── aliases: the string check settles presence, the judge settles reference ──

def _judge(*fields, identity=SUPPORTED) -> str:
    return json.dumps({
        "assay_identity_verdict": identity,
        "field_verifications": [
            {"field_name": name, "proposed_value": value, "verdict": verdict, "reason": reason}
            for name, value, verdict, reason in fields],
        "record_verdict": ACCEPT,
    })


def test_alias_check_folds_case_and_spacing_between_tokens_not_inside_them():
    assert check_alias_verbatim("flow  Cytometer", SOURCE)["status"] == "found"
    assert check_alias_verbatim("CyTOF", SOURCE)["status"] == "missing"
    assert check_alias_verbatim("IF", SOURCE)["status"] == "too_short"


def test_an_alias_inside_another_word_is_not_found():
    """The old check dropped every space and looked for a substring, so a three-letter acronym
    was "found" inside almost any paper: HAI in chair, ICS in statistics, PCR in top crater."""
    assert check_alias_verbatim("HAI", "[S1] Participants sat on a chair.")["status"] == "missing"
    assert check_alias_verbatim("ICS", "[S1] Statistics were computed in R.")["status"] == "missing"
    assert check_alias_verbatim("PCR", "[S1] Samples from the top crater.")["status"] == "missing"


def test_a_three_letter_acronym_is_found_where_it_stands_alone():
    assert check_alias_verbatim("HAI", "[S1] HAI titers were measured.")["status"] == "found"
    assert check_alias_verbatim("HAI", "[S1] Titers (HAI) rose.")["status"] == "found"
    assert check_alias_verbatim("HAI", "[S1] An HAI-specific response.")["status"] == "found"
    assert check_alias_verbatim("ICS", "[S1] Cytokines were measured by ICS.")["status"] == "found"


def test_a_three_letter_alias_must_match_in_its_own_case():
    """Three letters that are an acronym are also, somewhere, an English word."""
    assert check_alias_verbatim("AIM", "[S1] The aim of this study was safety.")["status"] == "missing"
    assert check_alias_verbatim("AIM", "[S1] An AIM assay was run.")["status"] == "found"


def test_an_alias_tolerates_dash_and_space_variants_between_its_tokens():
    for wording in ("RT–PCR", "RT PCR", "RTPCR", "RT-PCR"):
        assert check_alias_verbatim("RT-PCR", f"[S1] Measured by {wording}.")["status"] == "found", wording
    assert check_alias_verbatim("Flow cytometry", "[S1] by flow\ncytometry.")["status"] == "found"
    assert check_alias_verbatim("qPCR", "[S1] QPCR was run.")["status"] == "found"
    assert check_alias_verbatim("CyTOF", "[S1] on a cytof instrument.")["status"] == "found"


@pytest.mark.asyncio
async def test_a_reference_objection_phrased_as_not_appear_is_not_a_wording_objection():
    """"Does not appear to be used as a name for this assay" is about what the words refer to,
    not whether they are in the paper; the string check has nothing to say against it."""
    entry = {**ENTRY, "aliases": ["ELISA"]}
    body = _judge(("aliases[0]", "ELISA", NOT_SUPPORTED,
                   "The term does not appear to be used as a name for this flow cytometry assay."))

    result = await verify_assay("flow cytometry", entry, SOURCE, "Paper", _FakeClient(body))

    alias = next(v for v in result["field_verifications"] if v["field_name"] == "aliases[0]")
    assert alias["verdict"] == NOT_SUPPORTED


@pytest.mark.asyncio
async def test_a_verbatim_alias_the_judge_called_absent_is_supported():
    """36 of the 39 aliases the judge rejected across the corpus are in the paper; "does not
    appear verbatim" is a string claim, and the string check refutes it."""
    entry = {**ENTRY, "aliases": ["Flow Cytometer"]}
    body = _judge(("aliases[0]", "Flow Cytometer", NOT_SUPPORTED,
                   "This exact alias does not appear verbatim in the source text."))

    result = await verify_assay("flow cytometry", entry, SOURCE, "Paper", _FakeClient(body))

    alias = next(v for v in result["field_verifications"] if v["field_name"] == "aliases[0]")
    assert alias["verdict"] == SUPPORTED
    assert "wording" in alias["reason"]


@pytest.mark.asyncio
async def test_a_verbatim_alias_the_judge_called_a_readout_stays_unsupported():
    """Reference is the judge's call: the string check only says the words are there."""
    entry = {**ENTRY, "aliases": ["frequencies"]}
    body = _judge(("aliases[0]", "frequencies", NOT_SUPPORTED,
                   "This phrase refers to a readout rather than an alternate name for the assay."))

    result = await verify_assay("flow cytometry", entry, SOURCE, "Paper", _FakeClient(body))

    alias = next(v for v in result["field_verifications"] if v["field_name"] == "aliases[0]")
    assert alias["verdict"] == NOT_SUPPORTED


@pytest.mark.asyncio
async def test_an_absent_alias_is_unsupported_whatever_the_judge_said():
    body = _judge(("aliases[0]", "FACS", SUPPORTED, "FACS is used throughout"))

    result = await verify_assay("flow cytometry", ENTRY, SOURCE, "Paper", _FakeClient(body))

    alias = next(v for v in result["field_verifications"] if v["field_name"] == "aliases[0]")
    assert alias["verdict"] == NOT_SUPPORTED
    assert "does not appear" in alias["reason"]


@pytest.mark.asyncio
async def test_a_contradicted_alias_is_never_rescued_by_being_in_the_text():
    """A platform name is in the paper by definition; that is not what CONTRADICTED is about."""
    entry = {**ENTRY, "aliases": ["BD LSRFortessa"]}
    body = _judge(("aliases[0]", "BD LSRFortessa", CONTRADICTED,
                   "This is the instrument, not an alias for the assay."))

    result = await verify_assay("flow cytometry", entry, SOURCE, "Paper", _FakeClient(body))

    alias = next(v for v in result["field_verifications"] if v["field_name"] == "aliases[0]")
    assert alias["verdict"] == CONTRADICTED


# ── the quote check only lowers a verdict ────────────────────────────────────

@pytest.mark.asyncio
async def test_a_verbatim_quote_keeps_the_judges_semantic_objection():
    """The prompt asks for NOT_SUPPORTED when a verbatim quote establishes nothing about the
    assay being performed; the string check used to overwrite that with SUPPORTED."""
    body = _judge(("evidence.quote", ENTRY["evidence"]["quote"], NOT_SUPPORTED,
                   "The quote names the instrument but does not show this assay was performed."))

    result = await verify_assay("flow cytometry", ENTRY, SOURCE, "Paper", _FakeClient(body))

    quote = next(v for v in result["field_verifications"] if v["field_name"] == "evidence.quote")
    assert quote["verdict"] == NOT_SUPPORTED
    assert "instrument" in quote["reason"]


@pytest.mark.asyncio
async def test_a_verbatim_quote_the_judge_skipped_takes_the_string_checks_support():
    """Presence is the one thing known about a quote nobody ruled on."""
    body = _judge(("name_in_paper", "flow cytometry", SUPPORTED, "ok"))

    result = await verify_assay("flow cytometry", ENTRY, SOURCE, "Paper", _FakeClient(body))

    quote = next(v for v in result["field_verifications"] if v["field_name"] == "evidence.quote")
    assert quote["verdict"] == SUPPORTED


# ── the prompt tells the judge what it is and is not asked ──────────────────

def test_the_verify_prompt_states_the_naming_convention_and_leaves_presence_to_code():
    from app.agent.claim_parser import _load_prompt
    prompt = _load_prompt("verify_assays.txt")

    assert "technique this name denotes" in prompt
    assert "checked by code" in prompt


def test_the_verify_prompt_forbids_rejecting_an_assay_over_a_product_name():
    """SDY1655's only cytokine measurement was deleted with the reason "a product/panel name
    rather than an assay technique name". The extraction prompt's rule that a product name is
    not the assay *name* had been read as a rule about whether the assay *exists*."""
    from app.agent.claim_parser import _load_prompt
    prompt = _load_prompt("verify_assays.txt")

    reject_section = prompt[prompt.index("**REJECT**"):prompt.index("## Output")]
    assert "not grounds for REJECT" in reject_section
    for named in ("product", "panel", "kit", "vendor"):
        assert named in reject_section


# ── identity reviews ─────────────────────────────────────────────────────────

def _record(assay_id, identity, reason=None, error=None, record_verdict=REVIEW):
    fields = [{"field_name": "name_in_paper", "verdict": identity, "reason": reason or ""}]
    record = {"assay_id": assay_id, "assay_identity_verdict": identity,
              "field_verifications": fields, "record_verdict": record_verdict}
    if error:
        record["error"] = error
    return record


def test_identity_reviews_name_the_unsupported_and_the_unjudged_only():
    verification = {"results": [
        _record("ELISA", SUPPORTED, "stated in Methods", record_verdict=ACCEPT),
        _record("Multiplex analysis", NOT_SUPPORTED, "This is a section heading."),
        _record("viremia", CONTRADICTED, "an endpoint, not an assay", record_verdict=REJECT),
        _record("qPCR", NOT_REPORTED, error="TimeoutError: slow", record_verdict="ERROR"),
    ]}

    assert identity_reviews(verification) == {
        "Multiplex analysis": {"verdict": NOT_SUPPORTED, "reason": "This is a section heading."},
        "qPCR": {"verdict": NOT_REPORTED, "reason": "TimeoutError: slow"},
    }


def test_mark_identity_reviews_writes_the_field_onto_matching_entries_only():
    assays = {"ELISA": {"name_in_paper": "ELISA"}, "Multiplex analysis": {"name_in_paper": "Multiplex analysis"}}
    verification = {"results": [_record("Multiplex analysis", NOT_SUPPORTED, "a heading")]}

    mark_identity_reviews(assays, verification)

    assert assays["Multiplex analysis"]["identity_review"] == {"verdict": NOT_SUPPORTED, "reason": "a heading"}
    assert "identity_review" not in assays["ELISA"]


def test_the_review_mark_is_never_a_proposed_field():
    entry = {"name_in_paper": "ELISA", "aliases": [],
             "identity_review": {"verdict": NOT_SUPPORTED, "reason": "a heading"}}

    assert [f for f, _ in proposed_fields(entry)] == ["name_in_paper"]
