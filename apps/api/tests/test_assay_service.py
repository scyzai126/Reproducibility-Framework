"""The /agent/assays pipeline: locate the paper, extract, verify, and do not overspend."""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent import assay_service
from app.agent.assay_extractor import TRIMMED_FIELDS
from app.agent.assay_service import (
    NothingToDoError,
    PaperNotFoundError,
    assay_report,
    correct_report,
    locate_paper_xml,
    quote_report,
    registry_dir,
)
from app.main import app

_XML = """<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p></sec></body></article>"""

_ENTRY = {
    "name_in_paper": "flow cytometry", "aliases": [], "platform": "LSRII",
    "sample_type": None, "readouts": "cell frequencies", "source": "methods",
    "evidence": {"section": "Methods", "sentence_ids": ["S1"],
                 "quote": "Cells were analyzed on an LSRII."},
}


@pytest.fixture
def paper(tmp_path, monkeypatch):
    """A one-paper repo: XML on disk under both roots redirected into tmp_path."""
    xml_root, registry_root = tmp_path / "JAT_XML", tmp_path / "assay_registries"
    xml_root.mkdir()
    (xml_root / "SDY1_111.xml").write_text(_XML, encoding="utf-8")
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)
    return registry_root / "111_SDY1"


class _Client:
    """Counts calls and returns a canned body per call."""

    def __init__(self, *bodies):
        self.bodies, self.calls = list(bodies), 0
        self.chat = type("c", (), {"completions": self})()

    async def create(self, **_):
        body = self.bodies[min(self.calls, len(self.bodies) - 1)]
        self.calls += 1
        message = type("m", (), {"content": body})()
        return type("r", (), {"choices": [type("c", (), {"message": message})()]})()


def _extraction_body() -> str:
    return json.dumps({"flow cytometry": _ENTRY})


def _verification_body() -> str:
    """A judge that answers for every field the entry proposed.

    Answering for none is not the same as supporting them: proposed_fields enumerates what
    the extraction offered, and a field the judge skipped comes back NOT_REPORTED and is
    queued for re-extraction. A fixture that returned no verifications would therefore make
    round 3 bill for the whole entry.
    """
    fields = ["name_in_paper", "platform", "readouts", "source",
              "evidence.quote", "evidence.sentence_ids"]
    return json.dumps({
        "assay_id": "flow cytometry", "assay_identity_verdict": "SUPPORTED",
        "field_verifications": [{"field_name": f, "verdict": "SUPPORTED", "reason": "ok"}
                                for f in fields],
        "conflict_detected": False, "record_verdict": "ACCEPT",
    })


# ── locating the paper ────────────────────────────────────────────────────────

def test_the_xml_is_found_under_either_naming_order(paper, tmp_path):
    """Registry dirs are <pmid>_<SDY> and XML files <SDY>_<pmid>; both are tried."""
    assert locate_paper_xml("111", "SDY1").name == "SDY1_111.xml"


def test_one_identifier_is_enough(paper):
    assert locate_paper_xml("", "SDY1") is not None
    assert locate_paper_xml("111", "") is not None


def test_a_partial_match_does_not_count_as_the_paper(paper):
    """"11" is a substring of "111" but not the paper's identifier."""
    assert locate_paper_xml("11", "") is None


def test_the_registry_directory_uses_the_pmid_first_spelling(paper):
    assert registry_dir("111", "SDY1").name == "111_SDY1"


@pytest.mark.asyncio
async def test_a_missing_paper_raises_rather_than_extracting_from_nothing(paper):
    with pytest.raises(PaperNotFoundError):
        await assay_report("999", "SDY999", _Client("{}"))


# ── cost ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_cold_paper_runs_all_three_rounds(paper):
    """1 extraction + 1 assay verified + 0 flagged fields to repair."""
    client = _Client(_extraction_body(), _verification_body())

    result = await assay_report("111", "SDY1", client)

    assert client.calls == 2
    assert result["meta"]["llm_calls"] == 2
    assert [r["source"] for r in result["rounds"].values()] == [
        "extracted", "verified", "corrected"]
    for name in ("assays.json", "assays_verification.json", "assays_corrections.json"):
        assert (paper / name).exists(), name


@pytest.mark.asyncio
async def test_a_second_request_for_the_same_paper_spends_nothing(paper):
    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))
    client = _Client("SHOULD NOT BE CALLED")

    result = await assay_report("111", "SDY1", client)

    assert client.calls == 0
    assert result["meta"]["llm_calls"] == 0
    assert {r["source"] for r in result["rounds"].values()} == {"cache"}
    assert result["assays"]["flow cytometry"]["platform"] == "LSRII"


@pytest.mark.asyncio
async def test_refresh_re_extracts_and_re_verifies(paper):
    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))
    client = _Client(_extraction_body(), _verification_body())

    result = await assay_report("111", "SDY1", client, refresh=True)

    assert client.calls == 2
    assert result["rounds"]["extract"]["source"] == "extracted"


@pytest.mark.asyncio
async def test_a_fresh_registry_invalidates_a_stored_verification(paper):
    """The stored report judged different entries, so reusing it would misattribute verdicts."""
    (paper).mkdir(parents=True)
    (paper / "assays_verification.json").write_text('{"summary": {}, "results": []}')
    client = _Client(_extraction_body(), _verification_body())

    result = await assay_report("111", "SDY1", client, refresh=True)

    assert result["rounds"]["verify"]["source"] == "verified"


@pytest.mark.asyncio
async def test_verification_can_be_skipped(paper):
    client = _Client(_extraction_body())

    result = await assay_report("111", "SDY1", client, verify=False)

    assert client.calls == 1
    assert result["verification"] is None
    # Correction acts on verdicts, so skipping round 2 skips round 3 with it.
    assert result["rounds"]["verify"]["source"] == "skipped"
    assert result["rounds"]["correct"]["source"] == "skipped"


# ── the free check runs regardless ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_quote_check_runs_on_a_cached_answer_too(paper):
    """It costs nothing and does not depend on a model's opinion, so it is never skipped."""
    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))

    result = await assay_report("111", "SDY1", _Client("UNUSED"))

    assert result["quote_check"]["verified"] == 1
    assert result["quote_check"]["missing"] == 0


def test_quote_report_counts_each_status():
    source = "[S1] Cells were analyzed on an LSRII."
    registry = {
        "a": _ENTRY,
        "b": {**_ENTRY, "evidence": {"sentence_ids": ["S1"], "quote": "Run on a NovaSeq."}},
        "c": {**_ENTRY, "evidence": {"sentence_ids": ["S1"], "quote": None}},
    }

    report = quote_report(registry, source)

    assert (report["verified"], report["missing"], report["no_quote"]) == (1, 1, 1)


# ── the route ─────────────────────────────────────────────────────────────────

def test_the_route_rejects_a_request_with_no_identifier():
    response = TestClient(app).post("/agent/assays", json={})

    assert response.status_code == 400


def test_the_route_reports_an_unknown_paper_as_404(paper):
    response = TestClient(app).post("/agent/assays", json={"study_accession": "SDY999"})

    assert response.status_code == 404


# ── the free correction preview ───────────────────────────────────────────────

def _flagged_verification() -> dict:
    return {"summary": {}, "results": [{
        "assay_id": "flow cytometry", "record_verdict": "REVIEW",
        "assay_identity_verdict": "SUPPORTED",
        "field_verifications": [
            {"field_name": "platform", "verdict": "NOT_SUPPORTED", "reason": "unstated"},
            {"field_name": "readouts", "verdict": "SUPPORTED"},
        ]}]}


# ── correcting ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_correcting_sets_rejected_assays_aside_without_calling_for_them(paper):
    """A rejected assay is removed, not re-extracted -- so it costs no call."""
    paper.mkdir(parents=True)
    (paper / "assays.json").write_text(json.dumps({"GSEA": _ENTRY}))
    (paper / "assays_verification.json").write_text(json.dumps({"results": [{
        "assay_id": "GSEA", "record_verdict": "REJECT",
        "assay_identity_verdict": "CONTRADICTED",
        "field_verifications": [{"field_name": "name_in_paper", "verdict": "CONTRADICTED",
                                 "reason": "not an assay"}]}]}))
    client = _Client("SHOULD NOT BE CALLED")

    result = await correct_report("111", "SDY1", client)

    assert client.calls == 0
    assert result["corrected"] == {}
    assert result["dropped"]["GSEA"]["reason"] == "not an assay"
    assert json.loads((paper / "assays_rejected.json").read_text())["GSEA"]["reason"] == "not an assay"


@pytest.mark.asyncio
async def test_keep_rejected_retains_the_entry(paper):
    paper.mkdir(parents=True)
    (paper / "assays.json").write_text(json.dumps({"GSEA": _ENTRY}))
    (paper / "assays_verification.json").write_text(json.dumps({"results": [{
        "assay_id": "GSEA", "record_verdict": "REJECT",
        "assay_identity_verdict": "CONTRADICTED", "field_verifications": []}]}))

    result = await correct_report("111", "SDY1", _Client("{}"), drop_rejected_entries=False)

    assert list(result["corrected"]) == ["GSEA"]
    assert not (paper / "assays_rejected.json").exists()


@pytest.mark.asyncio
async def test_correcting_does_not_touch_the_live_registry(paper):
    """The corrected registry is a separate file until promoted."""
    paper.mkdir(parents=True)
    (paper / "assays.json").write_text(json.dumps({"flow cytometry": _ENTRY}))
    (paper / "assays_verification.json").write_text(json.dumps(_flagged_verification()))

    await correct_report("111", "SDY1", _Client('{"value": null, "sentence_ids": []}'))

    live = json.loads((paper / "assays.json").read_text())
    assert live["flow cytometry"]["platform"] == "LSRII"
    assert json.loads((paper / "assays_corrected.json").read_text())["flow cytometry"]["platform"] is None



def test_the_route_returns_the_corrected_registry(paper):
    """One endpoint, three rounds: what comes back is the post-correction set."""
    import app.api.routes as routes

    client = _Client(_extraction_body(), _verification_body())
    routes._get_client = lambda: client
    response = TestClient(app).post(
        "/agent/assays", json={"study_accession": "SDY1", "pubmed_id": "111"})

    assert response.status_code == 200
    body = response.json()
    assert list(body["assays"]) == ["flow cytometry"]
    assert [r["source"] for r in body["rounds"].values()] == ["extracted", "verified", "corrected"]


# ── the trimmed deliverable ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_run_writes_a_benchmark_registry_beside_the_full_one(paper):
    """assays.json keeps all seven fields because every pass in the chain works from them;
    assays_benchmark.json is the reading view and carries only the four."""
    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))

    full = json.loads((paper / "assays.json").read_text())
    trimmed = json.loads((paper / "assays_benchmark.json").read_text())

    assert tuple(trimmed["flow cytometry"]) == TRIMMED_FIELDS
    assert trimmed["flow cytometry"]["evidence"]["sentence_ids"] == ["S1"]
    # The pipeline's own record is untouched -- the trim is a projection, not a schema.
    assert full["flow cytometry"]["platform"] == "LSRII"
    assert full["flow cytometry"]["readouts"] == "cell frequencies"


@pytest.mark.asyncio
async def test_the_benchmark_registry_is_rewritten_on_a_cached_run(paper):
    """Written on every request, not only a paid one: a benchmark file that lagged assays.json
    would be worse than none, because nothing about it would say it was stale."""
    client = _Client(_extraction_body(), _verification_body())
    await assay_report("111", "SDY1", client)
    (paper / "assays_benchmark.json").unlink()
    spent = client.calls

    result = await assay_report("111", "SDY1", client)

    assert client.calls == spent, "a cached run must not spend anything"
    assert (paper / "assays_benchmark.json").exists()
    assert result["meta"]["benchmark_path"].endswith("assays_benchmark.json")
