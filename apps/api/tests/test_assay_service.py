"""The /agent/assays pipeline: locate the paper, extract, verify, and do not overspend."""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent import assay_service
from app.agent.assay_extractor import TRIMMED_FIELDS, AssayExtractionError
from app.agent.assay_service import (
    NothingToDoError,
    PaperNotFoundError,
    assay_report,
    locate_paper_xml,
    quote_report,
    registry_dir,
)
from app.main import app

_XML = """<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p></sec></body></article>"""

_ENTRY = {
    "name_in_paper": "flow cytometry", "aliases": [], "sample_type": None,
    "readouts": "cell frequencies",
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
    """A one-paper repo: XML on disk under all three roots redirected into tmp_path.

    PDF_ROOT is redirected too, and at an empty directory: without that these tests would walk
    the real data/pdf on every lookup, and a paper that happens to have a PDF there would take
    the PDF route inside a test that means to exercise the XML one.
    """
    xml_root, registry_root = tmp_path / "JAT_XML", tmp_path / "assay_registries"
    pdf_root = tmp_path / "pdf"
    xml_root.mkdir()
    pdf_root.mkdir()
    (xml_root / "SDY1_111.xml").write_text(_XML, encoding="utf-8")
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    monkeypatch.setattr(assay_service, "PDF_ROOT", pdf_root)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)
    # Not a benchmark paper (no folder under REGISTRY_ROOT), so its run lands in the cache.
    return assay_service.CACHE_ROOT / "111_SDY1"


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
    """assays.json keeps every field because every pass in the chain works from them;
    assays_benchmark.json is the reading view and carries only the four."""
    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))

    full = json.loads((paper / "assays.json").read_text())
    trimmed = json.loads((paper / "assays_benchmark.json").read_text())

    assert tuple(trimmed["flow cytometry assay"]) == TRIMMED_FIELDS
    assert trimmed["flow cytometry assay"]["evidence"]["sentence_ids"] == ["S1"]
    assert trimmed["flow cytometry assay"]["name_in_paper"] == ["flow cytometry"]
    # The pipeline's own record is untouched -- the trim is a projection, not a schema.
    assert full["flow cytometry assay"]["readouts"] == "cell frequencies"
    assert full["flow cytometry assay"]["standard_technique_name"] is None
    # And `source` is derived, not taken from the extraction: the fixture never proposes one.
    assert full["flow cytometry assay"]["source"] == "methods"


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
        "groups_merged": 1, "entries_folded": 1, "broad_unfolded": []}


@pytest.mark.asyncio
async def test_a_broad_mapping_is_delivered_under_its_own_name_and_reported(paper, monkeypatch):
    """Two entries on one term, but round 4 could only name the family for the second: it is
    not folded, keeps its paper name as its key, and the round says so."""
    def _broad_on_kits(assays, *_args, **_kwargs):
        return {key: {**entry, "obi_id": "OBI:0000916", "obi_label": "flow cytometry assay",
                      "resource": "embedding_llm", "obi_confidence": "high",
                      "obi_granularity": "BROAD" if key == "ELISA kits" else "EXACT"}
                for key, entry in assays.items()}
    monkeypatch.setattr(assay_service, "enrich_assays_with_obi", _broad_on_kits)

    result = await assay_report("111", "SDY1", _Client(_two_assays_body(), _verification_body()))

    assert list(json.loads((paper / "assays.json").read_text())) == [
        "flow cytometry assay", "ELISA kits"]
    assert list(json.loads((paper / "assays_OBI.json").read_text())) == [
        "flow cytometry assay", "ELISA kits"]
    assert result["rounds"]["canonicalize"]["broad_unfolded"] == ["ELISA kits"]
    assert result["merges"]["summary"]["broad_unfolded"] == ["ELISA kits"]
    benchmark = json.loads((paper / "assays_benchmark.json").read_text())
    assert benchmark["ELISA kits"]["name_in_paper"] == ["ELISA kits"]
    assert "additional_evidence" not in benchmark["flow cytometry assay"]


@pytest.mark.asyncio
async def test_a_run_that_folds_nothing_still_writes_its_own_merges_file(paper):
    """Rewritten, never left over: the key_map joins this run's verification to its registry,
    and a stale file from an earlier run would read as this run's findings."""
    paper.mkdir(parents=True)
    (paper / "assays_merges.json").write_text('{"summary": {"groups_merged": 9}}')

    result = await assay_report("111", "SDY1",
                                _Client(_extraction_body(), _verification_body()))

    assert result["rounds"]["canonicalize"]["source"] == "canonical"
    assert result["merges"]["results"] == []
    stored = json.loads((paper / "assays_merges.json").read_text())
    assert stored["summary"]["groups_merged"] == 0
    assert set(stored["key_map"]) == {"flow cytometry"}


# ── Source resolution: XML first, PDF as the fallback ─────────────────────────

@pytest.fixture
def pdf_only_paper(tmp_path, monkeypatch):
    """A repo where SDY2/222 exists only as a PDF -- the shape of the four corpus papers PMC
    will not serve as full text."""
    xml_root, registry_root = tmp_path / "JAT_XML", tmp_path / "assay_registries"
    pdf_root = tmp_path / "pdf"
    xml_root.mkdir()
    (pdf_root / "26papers").mkdir(parents=True)
    (pdf_root / "26papers" / "SDY2_222.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    monkeypatch.setattr(assay_service, "PDF_ROOT", pdf_root)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)
    return pdf_root / "26papers" / "SDY2_222.pdf"


def test_xml_wins_when_a_paper_has_both(paper, tmp_path):
    """The PDF route loses the section tags and sentence markers, so it is only ever a
    fallback: a paper with an XML must never be routed through it."""
    (assay_service.PDF_ROOT / "SDY1_111.pdf").write_bytes(b"%PDF-1.4 fake")

    kind, path = assay_service.locate_paper_source("111", "SDY1")

    assert (kind, path.name) == ("xml", "SDY1_111.xml")


def test_a_pdf_is_found_when_there_is_no_xml(pdf_only_paper):
    kind, path = assay_service.locate_paper_source("222", "SDY2")

    assert (kind, path.name) == ("pdf", "SDY2_222.pdf")


def test_a_pdf_is_found_in_a_nested_directory_whose_name_has_a_space(tmp_path, monkeypatch):
    """data/pdf/19 papers/ is a real directory. A locator that joined a path instead of
    walking would miss everything in it."""
    pdf_root = tmp_path / "pdf"
    (pdf_root / "19 papers").mkdir(parents=True)
    (pdf_root / "19 papers" / "SDY3_333.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(assay_service, "XML_ROOT", tmp_path / "empty")
    monkeypatch.setattr(assay_service, "PDF_ROOT", pdf_root)

    assert assay_service.locate_paper_pdf("333", "SDY3").name == "SDY3_333.pdf"


def test_a_pdf_only_paper_gets_a_registry_dir_marked_pdf(pdf_only_paper):
    """A registry built from a PDF has no sentence ids, so its folder says where it came from."""
    assert assay_service.registry_dir("222", "SDY2").name == "222_SDY2_pdf"


def test_an_xml_paper_keeps_the_plain_registry_dir_even_with_a_pdf(paper):
    (assay_service.PDF_ROOT / "SDY1_111.pdf").write_bytes(b"%PDF-1.4 fake")

    assert assay_service.registry_dir("111", "SDY1").name == "111_SDY1"


def test_an_existing_pdf_registry_dir_is_found_without_the_pdf(tmp_path, monkeypatch):
    """The registry outlives its source: deleting the PDF must not orphan what it built."""
    registry_root = tmp_path / "assay_registries"
    (registry_root / "444_SDY4_pdf").mkdir(parents=True)
    monkeypatch.setattr(assay_service, "XML_ROOT", tmp_path / "empty")
    monkeypatch.setattr(assay_service, "PDF_ROOT", tmp_path / "empty")
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)

    assert assay_service.registry_dir("444", "SDY4").name == "444_SDY4_pdf"


# ── Benchmark papers stay put; any other paper lives in the cache ─────────────

def test_a_benchmark_paper_keeps_its_folder_under_the_registry_root(paper):
    (assay_service.REGISTRY_ROOT / "111_SDY1").mkdir(parents=True)

    assert assay_service.registry_dir("111", "SDY1") == assay_service.REGISTRY_ROOT / "111_SDY1"
    assert not assay_service.is_cached("111", "SDY1")


def test_a_new_paper_lives_in_the_cache(paper):
    assert assay_service.registry_dir("111", "SDY1") == assay_service.CACHE_ROOT / "111_SDY1"
    assert assay_service.is_cached("111", "SDY1")


def test_a_new_pdf_only_paper_gets_a_pdf_folder_in_the_cache(pdf_only_paper):
    assert assay_service.registry_dir("222", "SDY2") == assay_service.CACHE_ROOT / "222_SDY2_pdf"


def test_a_cached_paper_is_found_again_after_its_source_is_gone(tmp_path, monkeypatch):
    (assay_service.CACHE_ROOT / "555_SDY5_pdf").mkdir(parents=True)
    monkeypatch.setattr(assay_service, "XML_ROOT", tmp_path / "empty")
    monkeypatch.setattr(assay_service, "PDF_ROOT", tmp_path / "empty")
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", tmp_path / "registries")

    assert assay_service.registry_dir("555", "SDY5") == assay_service.CACHE_ROOT / "555_SDY5_pdf"


def test_a_new_paper_s_run_is_listed_as_having_a_registry(paper):
    registry = assay_service.registry_dir("111", "SDY1")
    registry.mkdir(parents=True)
    (registry / "assays.json").write_text("{}", encoding="utf-8")

    [listed] = [p for p in assay_service.available_papers() if p["study_accession"] == "SDY1"]
    assert listed["has_registry"]


@pytest.mark.parametrize("stem", ["21357945_SDY1276_pdf", "21357945_SDY1276_PDF",
                                  "SDY1276_21357945_pdf"])
def test_split_stem_ignores_the_pdf_marker(stem):
    assert assay_service.split_stem(stem) == ("21357945", "SDY1276")


def test_a_paper_with_neither_source_resolves_to_nothing(paper):
    assert assay_service.locate_paper_source("999", "SDY9") is None


def test_estimate_run_prices_a_pdf_only_paper_instead_of_raising(pdf_only_paper, monkeypatch):
    """The cost gate is the reason this matters: before the PDF route these four papers could
    not even be quoted, so there was no way to decide whether to run them."""
    monkeypatch.setattr(assay_service, "extract_pdf_text",
                        lambda *_a, **_k: "Cells were analyzed on an LSRII.")

    estimate = assay_service.estimate_run("222", "SDY2")

    assert estimate["paper_source_kind"] == "pdf"
    assert estimate["paper_source"] == "SDY2_222.pdf"
    # Round 1 is one call whichever source it reads; the PDF rides along as a file part.
    assert estimate["rounds"][0]["calls"] == 1


def test_estimate_run_still_refuses_a_paper_with_no_source_at_all(paper):
    with pytest.raises(PaperNotFoundError) as exc:
        assay_service.estimate_run("999", "SDY9")

    # Both places looked are named, so the message says what to do about it.
    assert "JATS XML" in str(exc.value) and "PDF" in str(exc.value)


def test_available_papers_offers_a_pdf_only_paper(pdf_only_paper):
    """assay_report can run it, so hiding it would be the listing invariant broken the other
    way round: runnable but not offered."""
    listed = {p["study_accession"]: p for p in assay_service.available_papers()}

    assert listed["SDY2"]["paper_source_kind"] == "pdf"
    assert listed["SDY2"]["paper_source"] == "SDY2_222.pdf"


def test_available_papers_lists_a_paper_with_both_sources_once_as_xml(paper):
    (assay_service.PDF_ROOT / "SDY1_111.pdf").write_bytes(b"%PDF-1.4 fake")

    listed = [p for p in assay_service.available_papers() if p["study_accession"] == "SDY1"]

    assert len(listed) == 1
    assert listed[0]["paper_source_kind"] == "xml"



# ── a paper with no Methods section ───────────────────────────────────────────

_XML_NO_METHODS = """<article><front><article-meta><article-title>A Report</article-title>
</article-meta></front><body><p>Titers were measured with the inhibition ELISA.</p></body></article>"""


@pytest.mark.asyncio
async def test_round_one_says_when_the_paper_has_no_methods_section(paper):
    """So a run that finds little or nothing can say why, instead of just skipping four rounds."""
    (assay_service.XML_ROOT / "SDY1_111.xml").write_text(_XML_NO_METHODS, encoding="utf-8")

    result = await assay_report("111", "SDY1", _Client("{}"))

    assert result["rounds"]["extract"]["assays"] == 0
    assert result["rounds"]["extract"]["no_methods"] is True


@pytest.mark.asyncio
async def test_a_paper_with_methods_carries_no_such_flag(paper):
    result = await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))

    assert "no_methods" not in result["rounds"]["extract"]


# ── derived fields follow a repaired quote ───────────────────────────────────

_XML_WITH_RESULTS = """<article><front><article-meta><article-title>A Paper</article-title>
</article-meta></front><body><sec sec-type="methods"><title>Methods</title>
<p>Cells were analyzed on an LSRII.</p></sec><sec sec-type="results"><title>Results</title>
<p>Monocyte frequencies rose after vaccination.</p></sec></body></article>"""


@pytest.fixture
def paper_with_results(paper, monkeypatch):
    (assay_service.XML_ROOT / "SDY1_111.xml").write_text(_XML_WITH_RESULTS, encoding="utf-8")
    return paper


@pytest.mark.asyncio
async def test_source_and_ids_are_re_derived_after_an_evidence_repair(paper_with_results):
    """SDY1264: four repaired quotes had moved into the abstract while `source` still said
    `methods` -- derived once from the extracted quote and never again. The corrected registry
    is derived from the quote it actually carries."""
    # A paraphrased quote fails the free verbatim check, which outranks the judge, so the
    # evidence field is queued for the blind repair; the repair answers with a Results sentence.
    paraphrased = json.dumps({"flow cytometry": {
        **_ENTRY, "evidence": {**_ENTRY["evidence"], "quote": "Cells were run on an LSRII."}}})
    repair = json.dumps({"value": "Monocyte frequencies rose after vaccination.", "reason": "."})
    client = _Client(paraphrased, _verification_body(), repair)

    result = await assay_report("111", "SDY1", client)

    entry = result["assays"]["flow cytometry assay"]
    assert entry["evidence"]["quote"] == "Monocyte frequencies rose after vaccination."
    assert entry["source"] == "results"
    assert entry["evidence"]["sentence_ids"] == ["S2"]
    assert result["quote_check"]["source_mismatch"] == 0
    stored = json.loads((paper_with_results / "assays_corrected.json").read_text())
    assert stored["flow cytometry"]["source"] == "results"


# ── the stored read makes the same concessions the run does ──────────────────

def test_a_stored_pdf_registry_is_not_warned_about_missing_sentence_ids(pdf_only_paper, monkeypatch):
    """A PDF entry has no ids and no derived `source` by contract. The stored read demanded
    both, so every entry of a finished PDF paper came back with two warnings."""
    folder = assay_service.CACHE_ROOT / "222_SDY2_pdf"
    folder.mkdir(parents=True)
    entry = {**_ENTRY, "name_in_paper": ["flow cytometry"], "source": None,
             "evidence": {**_ENTRY["evidence"], "sentence_ids": []}}
    (folder / "assays.json").write_text(json.dumps({"flow cytometry assay": entry}))
    (folder / "assays_OBI.json").write_text(json.dumps({"flow cytometry assay": {
        **entry, "obi_id": "OBI:0000916", "obi_label": "flow cytometry assay",
        "resource": "exact_original"}}))
    monkeypatch.setattr(assay_service, "extract_pdf_text", lambda *_a, **_k: "Cells were analyzed on an LSRII.")

    stored = assay_service.stored_registry("222", "SDY2")

    assert stored["contract_warnings"] == []


# ── the judge's doubt about an identity reaches the file ─────────────────────

def _judge_doubts_the_identity() -> str:
    body = json.loads(_verification_body())
    body["assay_identity_verdict"] = "NOT_SUPPORTED"
    for field in body["field_verifications"]:
        if field["field_name"] == "name_in_paper":
            field["verdict"] = "NOT_SUPPORTED"
            field["reason"] = "This is a section heading rather than a stated assay name."
    body["record_verdict"] = "REVIEW"
    return json.dumps(body)


@pytest.mark.asyncio
async def test_an_unsupported_identity_is_marked_in_the_registry_and_the_deliverable(paper):
    """14 of the corpus's 170 entries were NOT_SUPPORTED on identity and shipped unmarked; the
    REVIEW line in the terminal was the only trace. Now the file says so, under the key the
    entry is delivered under."""
    client = _Client(_extraction_body(), _judge_doubts_the_identity())

    result = await assay_report("111", "SDY1", client)

    review = {"verdict": "NOT_SUPPORTED",
              "reason": "This is a section heading rather than a stated assay name."}
    assert result["assays"]["flow cytometry assay"]["identity_review"] == review
    assert json.loads((paper / "assays.json").read_text())["flow cytometry assay"]["identity_review"] == review
    assert json.loads((paper / "assays_benchmark.json").read_text())["flow cytometry assay"]["identity_review"] == review


@pytest.mark.asyncio
async def test_a_supported_identity_leaves_the_entry_exactly_as_before(paper):
    client = _Client(_extraction_body(), _verification_body())

    result = await assay_report("111", "SDY1", client)

    assert "identity_review" not in result["assays"]["flow cytometry assay"]
    assert "identity_review" not in json.loads((paper / "assays_benchmark.json").read_text())["flow cytometry assay"]


# ── every reply the run paid for is kept ─────────────────────────────────────

@pytest.mark.asyncio
async def test_the_run_keeps_every_model_reply_by_round(paper):
    client = _Client(_extraction_body(), _verification_body())

    result = await assay_report("111", "SDY1", client)

    raw = json.loads((paper / "assays_raw.json").read_text())
    # Keyed by extraction call, however many there were: the registry is their vote.
    assert raw["extract"] == {"run1": {"reply": _extraction_body(), "source_kind": "xml"}}
    assert raw["verify"]["flow cytometry"]["reply"] == _verification_body()
    assert result["meta"]["raw_path"].endswith("assays_raw.json")


@pytest.mark.asyncio
async def test_a_stale_raw_file_does_not_survive_into_a_new_run(paper):
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "assays_raw.json").write_text(json.dumps({"obi": {"ghost": {"reply": "none"}}}))

    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))

    assert "obi" not in json.loads((paper / "assays_raw.json").read_text()) or \
        "ghost" not in json.loads((paper / "assays_raw.json").read_text())["obi"]


# ── round 1 is three extractions, voted ──────────────────────────────────────

class _ExtractionClient(_Client):
    """The first `n` calls are extraction replies (one body each), then the verification."""

    def __init__(self, extractions: list[str], *rest: str):
        super().__init__(*extractions, *rest)


def _dc_panel_body(with_panel: bool) -> str:
    panel = {"flow cytometry for DC activation": {
        **_ENTRY, "name_in_paper": "flow cytometry for DC activation",
        "readouts": "CD80 and CD86 on DCs",
        "evidence": {"section": "Methods", "quote": "Cells were analyzed on an LSRII."}}}
    return json.dumps({"flow cytometry": _ENTRY, **(panel if with_panel else {})})


@pytest.mark.asyncio
async def test_round_one_makes_three_calls_and_delivers_the_majority(paper, monkeypatch):
    """SDY1260's DC panel in one run of three: reported as MINORITY, not delivered."""
    monkeypatch.setattr(assay_service, "EXTRACTIONS", 3)
    client = _ExtractionClient([_dc_panel_body(False), _dc_panel_body(True), _dc_panel_body(False)],
                               _verification_body())

    result = await assay_report("111", "SDY1", client)

    assert result["rounds"]["extract"] == {"source": "extracted", "calls": 3, "extractions": 3,
                                           "assays": 1, "minority": 1}
    assert client.calls == 4
    assert result["meta"]["llm_calls"] == 4
    assert list(result["assays"]) == ["flow cytometry assay"]
    assert list(result["minority"]) == ["flow cytometry for DC activation"]
    assert result["minority"]["flow cytometry for DC activation"]["runs"] == ["run2"]
    stored = json.loads((paper / "assays_minority.json").read_text())
    assert list(stored) == ["flow cytometry for DC activation"]
    raw = json.loads((paper / "assays_raw.json").read_text())
    assert sorted(raw["extract"]) == ["run1", "run2", "run3"]


@pytest.mark.asyncio
async def test_an_entry_two_of_three_calls_found_is_delivered(paper, monkeypatch):
    monkeypatch.setattr(assay_service, "EXTRACTIONS", 3)
    client = _ExtractionClient([_dc_panel_body(True), _dc_panel_body(True), _dc_panel_body(False)],
                               _verification_body())

    result = await assay_report("111", "SDY1", client)

    assert result["rounds"]["extract"]["minority"] == 0
    assert not (paper / "assays_minority.json").exists()
    # Two assays, both mapped by the stub to one term, so round 5 folds them: the panel
    # survives as a second wording rather than disappearing.
    assert result["assays"]["flow cytometry assay"]["name_in_paper"] == [
        "flow cytometry", "flow cytometry for DC activation"]


@pytest.mark.asyncio
async def test_a_stale_minority_file_is_cleared_by_a_run_that_has_none(paper, monkeypatch):
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "assays_minority.json").write_text("{\"ghost\": {}}")

    await assay_report("111", "SDY1", _Client(_extraction_body(), _verification_body()))

    assert not (paper / "assays_minority.json").exists()


def test_the_estimate_prices_round_one_at_the_extraction_count(paper, monkeypatch):
    monkeypatch.setattr(assay_service, "EXTRACTIONS", 3)

    rounds = {r["name"]: r for r in assay_service.estimate_run("111", "SDY1")["rounds"]}

    assert rounds["extract"]["calls"] == 3 and rounds["extract"]["extractions"] == 3


@pytest.mark.asyncio
async def test_one_unparseable_extraction_reply_of_three_is_voted_around(paper, monkeypatch):
    """One bad reply out of three used to raise and lose all three paid calls. Now the vote
    runs over the two that parsed (unanimity, since needed = 2 of 2) and the failure is a
    finding on the round, with the bad reply kept in the trace."""
    monkeypatch.setattr(assay_service, "EXTRACTIONS", 3)
    client = _ExtractionClient([_dc_panel_body(True), "{not json", _dc_panel_body(False)],
                               _verification_body())

    result = await assay_report("111", "SDY1", client)

    failed = result["rounds"]["extract"]["failed_runs"]
    assert [f["run"] for f in failed] == ["run2"]
    assert failed[0]["error"].startswith("AssayExtractionError: model returned unparseable JSON")
    assert result["rounds"]["extract"]["calls"] == 3  # paid for, failed or not
    assert client.calls == 4
    assert list(result["assays"]) == ["flow cytometry assay"]
    assert result["minority"]["flow cytometry for DC activation"]["runs"] == ["run1"]
    raw = json.loads((paper / "assays_raw.json").read_text())
    assert raw["extract"]["run2"]["reply"] == "{not json"


@pytest.mark.asyncio
async def test_two_failed_extraction_calls_of_three_fail_the_run_but_keep_the_trace(
        paper, monkeypatch):
    """Fewer than two replies is nothing to vote over, so the run fails as before -- but the
    replies that did arrive are written first, because they are the only diagnostic."""
    monkeypatch.setattr(assay_service, "EXTRACTIONS", 3)
    client = _ExtractionClient(["{not json", "[]", _dc_panel_body(False)], _verification_body())

    with pytest.raises(AssayExtractionError, match="run1, run2"):
        await assay_report("111", "SDY1", client)

    raw = json.loads((paper / "assays_raw.json").read_text())
    assert sorted(raw["extract"]) == ["run1", "run2", "run3"]
    assert not (paper / "assays_precorrection.json").exists()
    assert not (paper / "assays.json").exists()


@pytest.mark.asyncio
async def test_a_single_extraction_that_fails_still_fails_the_run(paper):
    with pytest.raises(AssayExtractionError):
        await assay_report("111", "SDY1", _Client("{not json"))
