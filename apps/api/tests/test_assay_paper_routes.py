"""POST /agent/assay-papers: adding a paper to the corpus, and refusing to pretend it worked.

NCBI is stubbed in every test. The endpoint makes no model call, so what is worth asserting is
that each way of failing comes back as a status a caller can act on differently -- and that the
one success path hands back a row the picker can select as-is.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent import assay_service, jats_fetcher
from app.main import app

_FULL_TEXT = """<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p></sec></body></article>"""

_ABSTRACT_ONLY = """<article><front><article-meta><article-title>A Paper</article-title>
<abstract><p>Only an abstract.</p></abstract></article-meta></front></article>"""


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    xml_root, registry_root = tmp_path / "JAT_XML", tmp_path / "assay_registries"
    xml_root.mkdir()
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    # PDF_ROOT is redirected at an empty directory so the listing cannot pick up the
    # repo's real PDFs: available_papers offers PDF-only papers too.
    _pdf_root = tmp_path / "pdf"
    _pdf_root.mkdir(exist_ok=True)
    monkeypatch.setattr(assay_service, "PDF_ROOT", _pdf_root)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)
    return xml_root


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(jats_fetcher, "REQUEST_DELAY_S", 0)


@pytest.fixture
def ncbi(monkeypatch):
    state = {"pmc_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC999/", "body": _FULL_TEXT,
             "raises": None, "calls": 0}

    async def _fake_pmid_to_pmc_url(_pmid):
        state["calls"] += 1
        return state["pmc_url"]

    class _FakeClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, _url, params=None):
            state["calls"] += 1
            if state["raises"] is not None:
                raise state["raises"]
            return httpx.Response(200, text=state["body"],
                                  request=httpx.Request("GET", "https://example.test"))

    monkeypatch.setattr(jats_fetcher, "pmid_to_pmc_url", _fake_pmid_to_pmc_url)
    monkeypatch.setattr(jats_fetcher.httpx, "AsyncClient", _FakeClient)
    return state


@pytest.fixture
def client():
    return TestClient(app)


def _add(client, **body):
    return client.post("/agent/assay-papers", json=body)


# ── the success path ──────────────────────────────────────────────────────────

def test_adding_a_paper_returns_the_row_the_picker_will_show(corpus, ncbi, client):
    """The summary comes back with the response so the client can select the new paper without
    re-listing the corpus first."""
    response = _add(client, pubmed_id="34252919", study_accession="SDY2189")

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["paper"]["pubmed_id"] == "34252919"
    assert body["paper"]["study_accession"] == "SDY2189"
    assert body["paper"]["paper_title"] == "A Paper"
    assert body["paper"]["has_registry"] is False
    assert body["paper"]["assays"] is None
    assert (corpus / "SDY2189_34252919.xml").exists()


def test_the_new_paper_is_then_listed_alongside_the_rest(corpus, ncbi, client):
    _add(client, pubmed_id="34252919", study_accession="SDY2189")

    papers = client.get("/agent/assay-papers").json()["papers"]

    assert [p["study_accession"] for p in papers] == ["SDY2189"]


def test_an_accession_is_accepted_in_any_case_and_filed_in_one(corpus, ncbi, client):
    body = _add(client, pubmed_id="34252919", study_accession="sdy2189").json()

    assert body["paper"]["study_accession"] == "SDY2189"
    assert (corpus / "SDY2189_34252919.xml").exists()


def test_adding_the_same_paper_twice_is_idempotent_rather_than_an_error(corpus, ncbi, client):
    """Re-downloading would renumber the sentences a stored registry cites, so the second ask
    makes no request at all -- and is still a success."""
    _add(client, pubmed_id="34252919", study_accession="SDY2189")
    calls_after_first = ncbi["calls"]

    response = _add(client, pubmed_id="34252919", study_accession="SDY2189")

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert "already in the corpus" in response.json()["message"]
    assert ncbi["calls"] == calls_after_first


def test_forcing_refetches_a_paper_already_on_disk(corpus, ncbi, client):
    (corpus / "SDY2189_34252919.xml").write_text("<article>stale</article>")

    response = _add(client, pubmed_id="34252919", study_accession="SDY2189", force=True)

    assert response.json()["created"] is True
    assert (corpus / "SDY2189_34252919.xml").read_text() == _FULL_TEXT


# ── the failures, each distinguishable ────────────────────────────────────────

def test_an_accession_without_the_sdy_prefix_is_refused_before_any_request(corpus, ncbi, client):
    """It would be written as a filename that reads back with the halves swapped."""
    response = _add(client, pubmed_id="34252919", study_accession="ABC123")

    assert response.status_code == 400
    assert "SDY" in response.json()["detail"]
    assert ncbi["calls"] == 0
    assert list(corpus.iterdir()) == []


def test_a_pmc_id_in_the_pubmed_field_is_refused(corpus, ncbi, client):
    response = _add(client, pubmed_id="PMC7665312", study_accession="SDY2189")

    assert response.status_code == 400
    assert ncbi["calls"] == 0


def test_a_paper_with_no_open_access_record_is_a_404(corpus, ncbi, client):
    ncbi["pmc_url"] = None

    response = _add(client, pubmed_id="34252919", study_accession="SDY2189")

    assert response.status_code == 404
    assert response.json()["detail"].startswith("Cannot fetch this paper's content online:")
    assert list(corpus.iterdir()) == []


def test_the_status_does_not_depend_on_the_wording_of_the_message(corpus, ncbi, client,
                                                                  monkeypatch):
    """404 and 422 are chosen by exception type. They were once chosen by a substring of the
    message, so rewording one sentence moved a status code."""
    from app.agent import jats_fetcher

    async def _reworded(*_a, **_k):
        raise jats_fetcher.PaperNotInPMCError("something else entirely")

    monkeypatch.setattr("app.api.routes.fetch_jats", _reworded)

    response = _add(client, pubmed_id="34252919", study_accession="SDY2189")

    assert response.status_code == 404


def test_a_paper_pmc_will_not_serve_in_full_is_a_422_naming_the_reason(corpus, ncbi, client):
    """Different from a 404: the paper exists, and the reason says what to do instead."""
    ncbi["body"] = _ABSTRACT_ONLY

    response = _add(client, pubmed_id="34252919", study_accession="SDY2189")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail.startswith("Cannot fetch this paper's content online:")
    assert "only the abstract" in detail
    assert list(corpus.iterdir()) == []


def test_ncbi_being_unreachable_is_a_502_rather_than_a_bad_paper(corpus, ncbi, client):
    ncbi["raises"] = httpx.ConnectError("no route to host")

    response = _add(client, pubmed_id="34252919", study_accession="SDY2189")

    assert response.status_code == 502
    assert list(corpus.iterdir()) == []


# ── the gate still applies to a paper added this way ──────────────────────────

def test_a_newly_added_paper_cannot_be_sized_and_says_so(corpus, ncbi, client):
    """Nothing has been extracted, so rounds 2-4 have nothing to size from. The estimate reports
    that rather than inventing a number, and the run gate accepts the unknown as an
    acknowledgement -- which is what lets a brand-new paper be run at all."""
    _add(client, pubmed_id="34252919", study_accession="SDY2189")

    estimate = client.post("/agent/assays/estimate",
                           json={"pubmed_id": "34252919", "study_accession": "SDY2189"}).json()

    assert estimate["total_calls_known"] is False
    assert estimate["total_calls"] is None
    assert estimate["caveat"] is None
    # Five assay rounds, then the web run's data step (this paper names no accession: 0).
    assert [r["calls"] for r in estimate["rounds"]] == [1, None, None, None, 0, 0]


def test_a_newly_added_paper_still_has_to_pass_the_cost_gate(corpus, ncbi, client):
    """Being new is not an exemption: a run that acknowledged nothing is refused."""
    _add(client, pubmed_id="34252919", study_accession="SDY2189")

    response = client.post("/agent/assays/runs",
                           json={"pubmed_id": "34252919", "study_accession": "SDY2189"})

    assert response.status_code == 400
    assert "estimate" in response.json()["detail"]


# ── uploading a PDF (for a paper PMC will not serve) ──────────────────────────

_PDF = b"%PDF-1.4\n% a paper\n%%EOF\n"


def _upload(client, data=_PDF, pubmed_id="34252919", study_accession="SDY2189", force=False):
    return client.post(
        "/agent/assay-papers/upload",
        data={"pubmed_id": pubmed_id, "study_accession": study_accession,
              "force": "true" if force else "false"},
        files={"file": ("paper.pdf", data, "application/pdf")},
    )


def test_an_uploaded_pdf_is_filed_where_the_pipeline_looks_for_one(corpus, client):
    response = _upload(client)

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["paper"]["study_accession"] == "SDY2189"
    assert body["paper"]["paper_source"] == "SDY2189_34252919.pdf"
    stored = assay_service.PDF_ROOT / "uploads" / "SDY2189_34252919.pdf"
    assert stored.read_bytes() == _PDF
    # From here the paper runs as a PDF paper: its registry is the _pdf directory.
    assert assay_service.locate_paper_pdf("34252919", "SDY2189") == stored
    assert assay_service.registry_dir("34252919", "SDY2189").name == "34252919_SDY2189_pdf"


def test_a_file_that_is_not_a_pdf_is_refused(corpus, client):
    response = _upload(client, data=b"<html>not a paper</html>")

    assert response.status_code == 415
    assert not (assay_service.PDF_ROOT / "uploads").exists()


def test_an_upload_with_identifiers_that_cannot_be_filed_is_refused(corpus, client):
    assert _upload(client, pubmed_id="PMC123").status_code == 400
    assert _upload(client, study_accession="2189").status_code == 400


def test_an_upload_for_a_paper_whose_xml_is_on_disk_is_refused(corpus, client):
    """The XML always wins, so a stored PDF would silently never be read."""
    (corpus / "SDY2189_34252919.xml").write_text("<article/>", encoding="utf-8")

    response = _upload(client)

    assert response.status_code == 409
    assert "already on disk" in response.json()["detail"]


def test_an_existing_pdf_is_kept_unless_forced(corpus, client):
    _upload(client)
    stored = assay_service.PDF_ROOT / "uploads" / "SDY2189_34252919.pdf"

    again = _upload(client, data=_PDF + b"% second\n")
    assert again.json()["created"] is False
    assert stored.read_bytes() == _PDF

    forced = _upload(client, data=_PDF + b"% second\n", force=True)
    assert forced.json()["created"] is True
    assert stored.read_bytes() == _PDF + b"% second\n"


def test_forcing_replaces_the_pdf_already_in_use_rather_than_adding_a_shadowed_copy(corpus,
                                                                                    client):
    """locate_paper_pdf returns the first match, so a second copy elsewhere would never be read."""
    existing = assay_service.PDF_ROOT / "26papers" / "SDY2189_34252919.pdf"
    existing.parent.mkdir()
    existing.write_bytes(_PDF)

    _upload(client, data=_PDF + b"% new\n", force=True)

    assert existing.read_bytes() == _PDF + b"% new\n"
    assert not (assay_service.PDF_ROOT / "uploads").exists()
