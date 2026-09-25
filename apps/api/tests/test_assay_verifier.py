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
    check_quote_verbatim,
    check_source_section,
    derive_record_verdict,
    get_evidence,
    get_name,
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
    "platform": "BD LSRFortessa",
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
    assert fields["evidence.sentence_ids"] == ["S2"]


def test_the_normalized_name_is_never_verified_against_the_paper():
    """It is a judgement about the technique, not a claim about the text.

    Every other field reports something the paper states, so the verifier can ask whether the
    text supports it. `normalized_name` is expected to use words the paper never wrote -- that
    is the whole reason it exists, since "Surface and intracellular cytokine staining" has to
    become "flow cytometry" to retrieve the right OBI term. Verifying it would draw a
    NOT_SUPPORTED on nearly every entry and bury round 2 in REVIEW lines for working output.
    """
    entry = {**ENTRY, "normalized_name": "flow cytometry"}

    assert "normalized_name" not in dict(proposed_fields(entry))


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
            {"field_name": "platform", "proposed_value": "BD LSRFortessa",
             "verdict": SUPPORTED, "reason": "named in S2"},
        ],
        "record_verdict": ACCEPT,
    })

    result = await verify_assay("flow cytometry", ENTRY, SOURCE, "Paper", _FakeClient(body))

    by_name = {v["field_name"]: v for v in result["field_verifications"]}
    assert by_name["platform"]["verdict"] == SUPPORTED
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


def _judge_says_source_is_fine() -> str:
    """A verifier answer that supports every field, `source` included."""
    return json.dumps({
        "assay_id": "phosphoflow analysis", "assay_identity_verdict": "SUPPORTED",
        "field_verifications": [
            {"field_name": f, "verdict": "SUPPORTED", "reason": "ok"}
            for f in ("name_in_paper", "sample_type", "readouts", "source",
                      "evidence.quote", "evidence.sentence_ids")],
        "conflict_detected": False, "record_verdict": "ACCEPT",
    })


@pytest.mark.asyncio
async def test_a_source_claim_its_evidence_contradicts_is_overruled(monkeypatch):
    """The real SDY212 defect: source "methods", evidence in [results], judge said fine.

    Over a 30-paper run the judge returned 2 `source` verdicts across 171 assays while the free
    check found 2 mismatches on different entries -- which then reached the finished registry
    because nothing flagged them for correction.
    """
    from app.agent import assay_verifier

    source_text = "## Results  [results]\n[S10] cell subset frequencies and function were assessed."
    result = await assay_verifier.verify_assay(
        "phosphoflow analysis", _SOURCE_ENTRY, source_text, "A Paper",
        _FakeClient(_judge_says_source_is_fine()))

    source = next(v for v in result["field_verifications"] if v["field_name"] == "source")
    assert source["verdict"] == "CONTRADICTED", "the judge's SUPPORTED was allowed to stand"
    assert "evidence sits in results" in source["reason"]
    # And it must pull the record down, which is what queues round 3 to repair the field.
    assert result["record_verdict"] == "REVIEW"


@pytest.mark.asyncio
async def test_an_aligned_source_is_confirmed_not_merely_left_alone(monkeypatch):
    from app.agent import assay_verifier

    entry = {**_SOURCE_ENTRY}
    source_text = ("## Materials and Methods  [methods]\n"
                   "[S10] cell subset frequencies and function were assessed.")
    result = await assay_verifier.verify_assay(
        "phosphoflow analysis", entry, source_text, "A Paper",
        _FakeClient(_judge_says_source_is_fine()))

    source = next(v for v in result["field_verifications"] if v["field_name"] == "source")
    assert source["verdict"] == "SUPPORTED"
    assert result["source_check"]["status"] == "aligned"


@pytest.mark.asyncio
async def test_the_judge_keeps_the_field_when_the_check_cannot_run(monkeypatch):
    """No sentence_ids -- every registry predating that field must pass through quietly."""
    from app.agent import assay_verifier

    entry = {**_SOURCE_ENTRY, "evidence": {"section": "x", "sentence_ids": [], "quote": "q"}}
    judged = json.loads(_judge_says_source_is_fine())
    judged["field_verifications"] = [
        {"field_name": "source", "verdict": "NOT_SUPPORTED", "reason": "judge's own doubt"}
        if v["field_name"] == "source" else v for v in judged["field_verifications"]]

    result = await assay_verifier.verify_assay(
        "phosphoflow analysis", entry, "## Results  [results]\n[S10] text.", "A Paper",
        _FakeClient(json.dumps(judged)))

    source = next(v for v in result["field_verifications"] if v["field_name"] == "source")
    assert source["verdict"] == "NOT_SUPPORTED"
    assert source["reason"] == "judge's own doubt"
    assert result["source_check"]["verdict"] is None


def test_measurement_role_and_parent_hint_are_not_proposed_values():
    """Both say what the paper *does* with an assay, not what its text states, so there is no
    span to check them against -- the same reason normalized_name is skipped."""
    entry = {**ENTRY, "measurement_role": "sub_step", "parent_hint": "LC-MS"}

    fields = dict(proposed_fields(entry))
    assert "measurement_role" not in fields
    assert "parent_hint" not in fields
