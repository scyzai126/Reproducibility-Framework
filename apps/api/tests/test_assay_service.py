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


@pytest.fixture(autouse=True)
def stub_obi(monkeypatch):
    """Round 4 answers from a stub in this file, not from the real OBI vocabulary.

    These tests are about the chain -- what each round costs, what it writes, what it hands
    on -- and none of them is about which OBI term "flow cytometry" resolves to. Left live,
    they would pass or fail on the contents of data/OBI, so a vocabulary prune that dropped
    an unrelated term would break tests that never mention ontologies. Round 4's own
    behaviour is covered in test_assay_service_obi.py and test_assay_obi_mapper.py.
    """
    def _fake(assays, *_args, **_kwargs):
        return {key: {**entry, "obi_id": "OBI:0000916", "obi_label": "flow cytometry assay",
                      "resource": "exact_original", "obi_confidence": "high"}
                for key, entry in assays.items()}

    monkeypatch.setattr(assay_service, "enrich_assays_with_obi", _fake)
    return _fake


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
async def test_a_cold_paper_runs_all_five_rounds(paper):
    """1 extraction + 1 assay verified + 0 flagged fields + a free OBI match + a free re-key.

    Round 5 runs even on a single assay and still costs nothing: keying the registry by its OBI
    term is the point, and folding is only what happens when two entries land on one term.
    """
    client = _Client(_extraction_body(), _verification_body())

    result = await assay_report("111", "SDY1", client)

    assert client.calls == 2
    assert result["meta"]["llm_calls"] == 2
    assert [r["source"] for r in result["rounds"].values()] == [
        "extracted", "verified", "corrected", "mapped", "canonical"]
    for name in ("assays.json", "assays_verification.json", "assays_corrections.json"):
        assert (paper / name).exists(), name


@pytest.mark.asyncio
async def test_a_second_request_for_the_same_paper_pays_again(paper):
    """Nothing is served from disk, so a repeat costs what the first run cost."""
    first = _Client(_extraction_body(), _verification_body())
    await assay_report("111", "SDY1", first)
    second = _Client(_extraction_body(), _verification_body())

    result = await assay_report("111", "SDY1", second)

    assert second.calls == first.calls == 2
    assert result["meta"]["llm_calls"] == 2
    assert [r["source"] for r in result["rounds"].values()] == [
        "extracted", "verified", "corrected", "mapped", "canonical"]


@pytest.mark.asyncio
async def test_a_stored_verification_is_never_served_back(paper):
    """It judged whatever the previous run extracted, and this run extracts again.

    This is why round 1's cache could not be removed on its own: the rounds are reusable
    together or not at all.
    """
    paper.mkdir(parents=True)
    (paper / "assays_verification.json").write_text('{"summary": {}, "results": []}')
    client = _Client(_extraction_body(), _verification_body())

    result = await assay_report("111", "SDY1", client)

    assert result["rounds"]["verify"]["source"] == "verified"
    assert result["verification"]["results"], "the stored empty report was served back"


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
async def test_the_quote_check_runs_on_every_answer(paper):
    """It costs nothing and does not depend on a model's opinion, so it is never skipped."""
    result = await assay_report("111", "SDY1",
                                _Client(_extraction_body(), _verification_body()))

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
    """One endpoint, four rounds: what comes back is the post-correction set."""
    import app.api.routes as routes

    client = _Client(_extraction_body(), _verification_body())
    routes._get_client = lambda: client
    response = TestClient(app).post(
        "/agent/assays", json={"study_accession": "SDY1", "pubmed_id": "111"})

    assert response.status_code == 200
    body = response.json()
    # Keyed by the OBI term round 5 canonicalized it to, not by the paper's wording.
    assert list(body["assays"]) == ["flow cytometry assay"]
    assert [r["source"] for r in body["rounds"].values()] == [
        "extracted", "verified", "corrected", "mapped", "canonical"]


def test_the_route_returns_the_obi_terms_corrections_and_merges_it_computed(paper):
    """Three of the run's findings reach the caller, or they reach no one.

    assay_report returns `obi`, `corrections` and `merges`; AssayResponse used to declare none
    of them, and FastAPI filters the response through the model -- so the endpoint dropped every
    OBI term, every CORRECT FAILED record and every MERGED record on the way out. The CLI never
    noticed because report_result reads the dict directly. Two entries on one OBI term, so the
    merge report has something in it to lose.
    """
    import app.api.routes as routes

    routes._get_client = lambda: _Client(_two_assays_body(), _verification_body())
    response = TestClient(app).post(
        "/agent/assays", json={"study_accession": "SDY1", "pubmed_id": "111"})

    assert response.status_code == 200
    body = response.json()
    assert list(body["obi"]) == ["flow cytometry assay"]
    assert body["obi"]["flow cytometry assay"]["obi_id"] == "OBI:0000916"
    assert body["merges"]["results"][0]["folded"] == ["ELISA kits"]
    assert body["corrections"]["summary"]["assays"] == 2


# ── the trimmed deliverable ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_run_writes_a_benchmark_registry_beside_the_full_one(paper):
    """assays.json keeps all seven fields because every pass in the chain works from them;
    assays_benchmark.json is the reading view and carries only the four."""
    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))

    full = json.loads((paper / "assays.json").read_text())
    trimmed = json.loads((paper / "assays_benchmark.json").read_text())

    assert tuple(trimmed["flow cytometry assay"]) == TRIMMED_FIELDS
    assert trimmed["flow cytometry assay"]["evidence"]["sentence_ids"] == ["S1"]
    assert trimmed["flow cytometry assay"]["name_in_paper"] == ["flow cytometry"]
    # The pipeline's own record is untouched -- the trim is a projection, not a schema.
    assert full["flow cytometry assay"]["platform"] == "LSRII"
    assert full["flow cytometry assay"]["readouts"] == "cell frequencies"


@pytest.mark.asyncio
async def test_the_benchmark_registry_is_rewritten_on_every_run(paper):
    """A benchmark file that lagged assays.json would be worse than none, because nothing
    about it would say it was stale."""
    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))
    (paper / "assays_benchmark.json").unlink()

    result = await assay_report("111", "SDY1",
                                _Client(_extraction_body(), _verification_body()))

    assert (paper / "assays_benchmark.json").exists()
    assert result["meta"]["benchmark_path"].endswith("assays_benchmark.json")


# ── every file describes one run ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_precorrection_snapshot_describes_the_run_that_wrote_it(paper):
    """Not whichever run happened to be first.

    promote_registry writes the snapshot only when absent, which was correct while a finished
    paper was served from cache -- the first extraction was the only unrepaired version there
    would ever be. With every run re-extracting, that guard alone would pin the file forever.
    """
    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))
    second = json.dumps({"ELISA": {**_ENTRY, "name_in_paper": "ELISA"}})

    await assay_report("111", "SDY1", _Client(second, _verification_body()))

    snapshot = json.loads((paper / "assays_precorrection.json").read_text())
    assert list(snapshot) == ["ELISA"]


@pytest.mark.asyncio
async def test_a_stale_rejected_file_does_not_survive_a_run_that_rejects_nothing(paper):
    """Left behind, it would read as this run's findings."""
    paper.mkdir(parents=True)
    (paper / "assays_rejected.json").write_text('{"gone": {"entry": {}, "reason": "old"}}')

    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))

    assert not (paper / "assays_rejected.json").exists()


# ── round 5: one assay written up twice ───────────────────────────────────────

def _two_assays_body() -> str:
    """What an extraction looks like when it splits one technique across two subheadings."""
    return json.dumps({
        "ELISA": {**_ENTRY, "name_in_paper": "ELISA"},
        "ELISA kits": {**_ENTRY, "name_in_paper": "ELISA kits"},
    })


@pytest.mark.asyncio
async def test_two_entries_on_one_obi_term_leave_one_entry_keyed_by_that_term(paper):
    """The whole point of folding at registry time rather than at report time."""
    client = _Client(_two_assays_body(), _verification_body())

    result = await assay_report("111", "SDY1", client)

    assert result["rounds"]["canonicalize"]["source"] == "canonical"
    # Free: the OBI term is already on disk, and the rule reads it rather than asking anything.
    assert result["rounds"]["canonicalize"]["calls"] == 0
    assert list(json.loads((paper / "assays.json").read_text())) == ["flow cytometry assay"]
    # A mapping still keyed by a folded-away wording would read as an assay this paper reported.
    assert list(json.loads((paper / "assays_OBI.json").read_text())) == ["flow cytometry assay"]

    benchmark = json.loads((paper / "assays_benchmark.json").read_text())
    assert list(benchmark) == ["flow cytometry assay"]
    assert benchmark["flow cytometry assay"]["name_in_paper"] == ["ELISA", "ELISA kits"]
    # The second write-up's evidence survives the fold; it is the one thing the surviving
    # record cannot reconstruct.
    assert benchmark["flow cytometry assay"]["additional_evidence"][0]["name_in_paper"] == "ELISA kits"
    assert json.loads((paper / "assays_merges.json").read_text())["summary"] == {
        "groups_merged": 1, "entries_folded": 1}


@pytest.mark.asyncio
async def test_a_stale_merges_file_does_not_survive_a_run_that_folds_nothing(paper):
    """Same reason as assays_rejected.json: it would read as this run's findings."""
    paper.mkdir(parents=True)
    (paper / "assays_merges.json").write_text('{"summary": {"groups_merged": 9}}')

    result = await assay_report("111", "SDY1",
                                _Client(_extraction_body(), _verification_body()))

    assert result["rounds"]["canonicalize"]["source"] == "canonical"
    assert result["merges"]["results"] == []
    assert not (paper / "assays_merges.json").exists()
