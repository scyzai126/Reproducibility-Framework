"""POST /agent/assays/resolve over HTTP.

The resolver's own behaviour is covered in test_paper_resolver.py; what is tested here is the
route around it — which failures are statuses and which are ordinary answers, that the database
session is injected and a dead one does not become a 500, and that a lookup this page runs on
every submission costs no model call.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import app.api.routes as routes
from app.agent import assay_jobs, assay_service
from app.database import get_session
from app.main import app

_XML = """<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p></sec></body></article>"""


class _NeverCalled:
    """A model client that fails the test if anything asks it for a completion."""

    def __init__(self):
        self.calls = 0
        self.chat = type("c", (), {"completions": self})()

    async def create(self, **_):
        self.calls += 1
        raise AssertionError("a free endpoint made a model call")


class _FakeSession:
    def __init__(self, rows=None, raises=None):
        self.rows, self.raises = rows or [], raises
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        if self.raises is not None:
            raise self.raises
        rows = self.rows
        return type("R", (), {
            "mappings": lambda self: type("M", (), {"all": lambda self: rows})()})()


def _row(study_accession, pubmed_id, year=2021):
    return {"study_accession": study_accession, "pubmed_id": pubmed_id,
            "title": f"Paper {pubmed_id}", "journal": "J Immunol", "year": year,
            "authors": "A. Author", "doi": "10.1000/x"}


@pytest.fixture(autouse=True)
def clean_jobs():
    assay_jobs.reset()
    yield
    assay_jobs.reset()


@pytest.fixture(autouse=True)
def no_spending(monkeypatch):
    client = _NeverCalled()
    monkeypatch.setattr(routes, "_get_client", lambda: client)
    return client


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    xml_root, registry_root = tmp_path / "JAT_XML", tmp_path / "assay_registries"
    xml_root.mkdir()
    registry_root.mkdir()
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    # PDF_ROOT is redirected at an empty directory so the listing cannot pick up the
    # repo's real PDFs: available_papers offers PDF-only papers too.
    _pdf_root = tmp_path / "pdf"
    _pdf_root.mkdir(exist_ok=True)
    monkeypatch.setattr(assay_service, "PDF_ROOT", _pdf_root)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)
    return xml_root


@pytest.fixture
def client():
    """A TestClient whose database session is ours, restored afterwards."""
    def _make(session):
        async def _override():
            yield session
        app.dependency_overrides[get_session] = _override
        return TestClient(app)

    yield _make
    app.dependency_overrides.pop(get_session, None)


def _resolve(test_client, query):
    return test_client.post("/agent/assays/resolve", json={"query": query})


# ── ordinary answers ──────────────────────────────────────────────────────────

def test_one_match_comes_back_with_what_the_caller_needs_to_run_it(corpus, client):
    response = _resolve(client(_FakeSession([_row("SDY2189", "34252919")])), "SDY2189")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    candidate = body["candidates"][0]
    assert (candidate["pubmed_id"], candidate["study_accession"]) == ("34252919", "SDY2189")
    assert candidate["title"] == "Paper 34252919"
    assert candidate["has_xml"] is False
    assert candidate["active_job_id"] is None


def test_a_study_with_six_papers_returns_six(corpus, client):
    """The case a resolver that picked would get wrong five times out of six."""
    rows = [_row("SDY212", pmid, year=year) for pmid, year in
            [("23591775", 2013), ("24337376", 2014), ("25834109", 2015),
             ("27746093", 2016), ("30842675", 2019), ("31636302", 2019)]]

    body = _resolve(client(_FakeSession(rows)), "SDY212").json()

    assert body["total"] == 6
    assert len({c["pubmed_id"] for c in body["candidates"]}) == 6
    assert all(c["year"] for c in body["candidates"])


def test_no_match_is_a_200_with_a_reason_rather_than_a_404(corpus, client):
    """For a chat turn, "nothing matched, here is what I checked" beats an exception."""
    response = _resolve(client(_FakeSession([])), "SDY9999")

    assert response.status_code == 200
    assert response.json()["candidates"] == []
    assert response.json()["reason"]


def test_a_string_that_is_not_an_identifier_is_a_400(corpus, client):
    response = _resolve(client(_FakeSession()), "flow cytometry")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "SDY2189" in detail and "34252919" in detail


def test_an_empty_query_is_a_400(corpus, client):
    assert _resolve(client(_FakeSession()), "   ").status_code == 400


# ── the database is not required ──────────────────────────────────────────────

def test_an_unreachable_database_is_still_a_200(corpus, client):
    """A dead database costs discovery of new papers, not the page."""
    (corpus / "SDY2189_34252919.xml").write_text(_XML, encoding="utf-8")
    session = _FakeSession(raises=OperationalError("SELECT 1", {}, Exception("down")))

    response = _resolve(client(session), "SDY2189")

    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["warning"]
    assert body["total"] == 1
    assert body["candidates"][0]["in_db"] is False
    assert body["candidates"][0]["has_xml"] is True


# ── cost and wiring ───────────────────────────────────────────────────────────

def test_resolving_costs_no_model_call(corpus, client, no_spending):
    """This runs on every submission; it is a database read."""
    _resolve(client(_FakeSession([_row("SDY2189", "34252919")])), "SDY2189")

    assert no_spending.calls == 0


def test_the_route_is_not_swallowed_by_the_job_path_parameter(corpus, client):
    """/assays/resolve must not be read as /assays/runs/{job_id} or similar."""
    response = _resolve(client(_FakeSession([_row("SDY2189", "34252919")])), "SDY2189")

    assert response.status_code == 200
    assert response.json()["shape"] == "study_accession"


def test_a_run_already_under_way_is_reported_so_it_can_be_adopted(corpus, client):
    job = assay_jobs.create("34252919", "SDY2189")
    job.state = "running"

    body = _resolve(client(_FakeSession([_row("SDY2189", "34252919")])), "SDY2189").json()

    assert body["candidates"][0]["active_job_id"] == job.id
