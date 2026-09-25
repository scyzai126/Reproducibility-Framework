"""The PDF route produces the same contract as the XML one, minus the sentence ids.

Round 1 is the only round that differs between the two sources, so these cover the seam:
what goes out on the request, what comes back through the shared cleaning, and -- the one that
matters most -- that a quote copied from a PDF still verifies against the PDF's text layer
without any sentence ids to narrow the search. That last check is the whole basis for keeping
verification on this route; if it rots, a PDF registry silently stops being checked.
"""

import json

import pytest

from app.agent.assay_extractor import (
    AssayExtractionError,
    ENTRY_FIELDS,
    contract_warnings,
)
from app.agent.assay_extractor_pdf import build_prompt, extract_assays_from_pdf
from app.agent.assay_verifier import check_quote_verbatim

PDF_BYTES = b"%PDF-1.4 not a real pdf, never parsed locally on this route"


def _entry(**over) -> dict:
    entry = {
        "name_in_paper": "microarray",
        "normalized_name": "transcription profiling by array",
        "aliases": ["Illumina Human HT12v3 Expression BeadChip"],
        "platform": "Illumina Human HT12v3 Expression BeadChip",
        "sample_type": "PBMCs",
        "readouts": "genome-wide gene expression",
        "measurement_role": "reported",
        "parent_hint": None,
        "source": "methods",
        "evidence": {
            "section": "Materials and Methods",
            "sentence_ids": [],
            "quote": "cRNA was hybridized onto Illumina Human HT12v3 Expression BeadChips.",
        },
    }
    entry.update(over)
    return entry


class _FakeClient:
    """Minimal stand-in for AsyncOpenAI that records the request it was given."""

    def __init__(self, body: str | None = None, error: Exception | None = None):
        self._body, self._error = body, error
        self.calls: list[dict] = []
        outer = self

        class _Completions:
            async def create(self, **kwargs):
                outer.calls.append(kwargs)
                if outer._error:
                    raise outer._error
                message = type("M", (), {"content": outer._body})()
                return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

        self.chat = type("Chat", (), {"completions": _Completions()})()


# ── The prompt ────────────────────────────────────────────────────────────────

def test_the_prompt_carries_the_title_and_no_source_text_placeholder():
    """The paper rides as a PDF file part, so the prompt interpolates only the title. A
    leftover {source_text} would ship the literal placeholder to the model."""
    rendered = build_prompt("Systems biology of vaccination")

    assert "Systems biology of vaccination" in rendered
    assert "{source_text}" not in rendered
    assert "{paper_title}" not in rendered


def test_the_prompt_never_asks_for_the_xml_format_markers():
    """extract_assays.txt tells the model the `[methods]` tag is authoritative and that every
    sentence carries an `[S<n>]` marker. A PDF has neither, and a prompt that still promised
    them would have the model cite ids it invented."""
    rendered = build_prompt("Any paper")

    for marker in ("[S<n>]", "[methods]", "[results]", "[abstract]", "--- Figures ---"):
        assert marker not in rendered, f"{marker} leaked into the PDF prompt"


def test_the_shared_rules_are_byte_identical_to_the_xml_prompt():
    """The two prompts are deliberately paired: only the input contract differs. This pins the
    shared half so an edit to one file cannot silently drift from the other."""
    from app.agent.claim_parser import _load_prompt

    xml, pdf = _load_prompt("extract_assays.txt"), _load_prompt("extract_assays_pdf.txt")

    for shared in ("## What counts as an entry", "## Naming each assay",
                   "## Filling the other fields"):
        assert shared in xml and shared in pdf

    def between(text: str, start: str, end: str) -> str:
        return text[text.index(start):text.index(end)]

    # The entry rules, the naming rules and the field-filling rules: everything about assays
    # rather than about the file format.
    rules = ("## What counts as an entry", "## Output")
    assert between(xml, *rules) == between(pdf, *rules)

    # The per-field rules after the JSON example, up to `source` -- where the two legitimately
    # part company. The example itself is skipped: its `sentence_ids` line is one of exactly
    # two intended differences in this stretch, the other being the `source`/`evidence` rules.
    fields = ("**Ten fields, no more.**", "- `source` — where the paper establishes")
    assert between(xml, *fields) == between(pdf, *fields)


# ── The request ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_pdf_is_sent_as_a_file_part_under_its_own_filename():
    client = _FakeClient(json.dumps({"microarray": _entry()}))

    await extract_assays_from_pdf(PDF_BYTES, "SDY1276_21357945.pdf", "A paper", client)

    content = client.calls[0]["messages"][1]["content"]
    file_part = next(p for p in content if p["type"] == "file")
    assert file_part["file"]["filename"] == "SDY1276_21357945.pdf"
    assert file_part["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert client.calls[0]["temperature"] == 0


@pytest.mark.asyncio
async def test_the_registry_is_reduced_to_the_same_eight_fields():
    """confidence and claim_role are what a model reaches for unprompted. The PDF route runs
    the same clean_registry as the XML one, so they must not come back through it either."""
    raw = _entry(confidence=0.95, claim_role="primary")
    client = _FakeClient(json.dumps({"microarray": raw}))

    registry = await extract_assays_from_pdf(PDF_BYTES, "p.pdf", "A paper", client)

    assert tuple(registry["microarray"]) == ENTRY_FIELDS


@pytest.mark.asyncio
async def test_an_unparseable_answer_raises_rather_than_returning_half_a_registry():
    client = _FakeClient("not json at all")

    with pytest.raises(AssayExtractionError):
        await extract_assays_from_pdf(PDF_BYTES, "p.pdf", "A paper", client)


@pytest.mark.asyncio
async def test_an_empty_answer_raises():
    client = _FakeClient("")

    with pytest.raises(AssayExtractionError):
        await extract_assays_from_pdf(PDF_BYTES, "p.pdf", "A paper", client)


# ── The warning signal ────────────────────────────────────────────────────────

def test_empty_sentence_ids_are_the_contract_on_this_route_and_do_not_warn():
    """Every PDF entry has empty ids by design. Warning per entry would fire on all of them at
    once, and CLAUDE.md requires every WARNING line be reported -- burying the real ones."""
    registry = {"microarray": _entry()}

    assert contract_warnings(registry, expect_sentence_ids=False) == []
    # The XML default still reports them, so the 34 XML papers are unaffected.
    assert contract_warnings(registry) == ["microarray: evidence cites no sentence_ids"]


def test_a_missing_quote_still_warns_on_the_pdf_route():
    """Silencing the ids must not silence the check that matters: a PDF entry leans entirely on
    its quote, so a missing one is worse here than on the XML route, not better."""
    registry = {"microarray": _entry(
        evidence={"section": "Methods", "sentence_ids": [], "quote": None})}

    assert contract_warnings(registry, expect_sentence_ids=False) == [
        "microarray: no evidence quote"]


# ── The regression that must not rot ──────────────────────────────────────────

def test_a_quote_verifies_against_a_pdf_text_layer_despite_ligatures_and_hyphenation():
    """The basis for keeping round 2 on this route.

    A PyMuPDF text layer carries typographic ligatures (`ﬁ`, `ﬂ`) and line-break hyphens the
    model will not reproduce when it quotes the paper, and with no sentence_ids the search
    falls back to the whole document. _squash absorbs both -- NFKC folds the ligatures, and
    every dash and all whitespace are dropped -- so a faithfully copied quote still resolves.
    If this ever fails, PDF registries are being verified against nothing.
    """
    pdf_text = (
        "Vaccine\nParticipants were immunized on day 0 with the 2008-2009\n"
        "trivalent inﬂuenza vaccine. Signiﬁ-\ncant gene ex-\npression changes were observed."
    )
    entry = _entry(evidence={
        "section": "Methods",
        "sentence_ids": [],
        "quote": "Participants were immunized on day 0 with the 2008-2009 trivalent "
                 "influenza vaccine.",
    })

    result = check_quote_verbatim(entry, pdf_text)

    assert result["status"] == "found"
    assert "whole document" in result["detail"]


def test_a_fabricated_quote_is_still_caught_without_sentence_ids():
    """The fallback widens the haystack; it must not disable the check."""
    entry = _entry(evidence={
        "section": "Methods",
        "sentence_ids": [],
        "quote": "Samples were analysed by mass cytometry on a Helios instrument.",
    })

    result = check_quote_verbatim(entry, "Participants received a trivalent inﬂuenza vaccine.")

    assert result["status"] == "missing"
