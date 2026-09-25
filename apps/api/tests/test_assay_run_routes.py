"""The assay workspace endpoints: which of them spend, and what stops the one that does.

`assay_report` is stubbed in every test that reaches it. A real run is upwards of twenty calls,
and nothing these routes decide -- whether a run is allowed to start, what a poller sees, what a
free read returns -- depends on what the pipeline actually answers.

The tests that matter most are the ones about *not* spending: the endpoints that must make no
call at all, and the guards that stand between a request and a second bill for the same paper.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.agent import assay_jobs, assay_service
from app.main import app

_XML = """<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p></sec></body></article>"""

_ENTRY = {
    "name_in_paper": "flow cytometry", "aliases": [], "platform": "LSRII",
    "sample_type": None, "readouts": "cell frequencies", "source": "methods",
    "evidence": {"section": "Methods", "sentence_ids": ["S1"],
                 "quote": "Cells were analyzed on an LSRII."},
}


class _NeverCalled:
    """A client that fails the test if anything asks it for a completion."""

    def __init__(self):
        self.calls = 0
        self.chat = type("c", (), {"completions": self})()

    async def create(self, **_):
        self.calls += 1
        raise AssertionError("a free endpoint made a model call")


@pytest.fixture(autouse=True)
def clean_jobs():
    assay_jobs.reset()
    yield
    assay_jobs.reset()


@pytest.fixture(autouse=True)
def no_spending(monkeypatch):
    """Every test starts with a client that refuses to be used."""
    client = _NeverCalled()
    monkeypatch.setattr(routes, "_get_client", lambda: client)
    return client


@pytest.fixture(autouse=True)
def vocabulary(monkeypatch):
    monkeypatch.setattr(assay_service, "_build_lookup",
                        lambda: {"flow cytometry": "OBI:0000916"})


@pytest.fixture
def paper(tmp_path, monkeypatch):
    """One paper on disk, with nothing extracted for it yet."""
    xml_root, registry_root = tmp_path / "JAT_XML", tmp_path / "assay_registries"
    xml_root.mkdir()
    (xml_root / "SDY1_111.xml").write_text(_XML, encoding="utf-8")
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    # PDF_ROOT is redirected at an empty directory so the listing cannot pick up the
    # repo's real PDFs: available_papers offers PDF-only papers too.
    _pdf_root = tmp_path / "pdf"
    _pdf_root.mkdir(exist_ok=True)
    monkeypatch.setattr(assay_service, "PDF_ROOT", _pdf_root)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)
    return registry_root / "111_SDY1"


@pytest.fixture
def extracted(paper):
    """...and now it has been run once."""
    paper.mkdir(parents=True)
    (paper / "assays.json").write_text(json.dumps({"flow cytometry": _ENTRY}), encoding="utf-8")
    (paper / "assays_benchmark.json").write_text(
        json.dumps({"flow cytometry": {k: _ENTRY[k] for k in
                                       ("name_in_paper", "aliases", "source", "evidence")}}),
        encoding="utf-8")
    (paper / "assays_verification.json").write_text(
        json.dumps({"summary": {}, "results": []}), encoding="utf-8")
    return paper


@pytest.fixture
def client():
    """The context-manager form, deliberately.

    Without it TestClient spins up a fresh event loop per request and tears it down on the way
    out, which cancels the task a run was just started on -- so every job would arrive back
    "cancelled" and the tests would be measuring the test client rather than the endpoints.
    Under uvicorn there is one long-lived loop, which is what this reproduces.
    """
    with TestClient(app) as test_client:
        yield test_client


def _stub_report(monkeypatch, **overrides):
    """Replace the chain with something instant, and record what it was asked for."""
    seen = {}

    async def _fake(pubmed_id, study_accession, _client, **kwargs):
        seen.update({"pubmed_id": pubmed_id, "study_accession": study_accession, **kwargs})
        on_progress = kwargs.get("on_progress")
        if on_progress is not None:
            on_progress({"round": "extract", "state": "done", "calls": 1, "assays": 1})
        if overrides.get("raises") is not None:
            raise overrides["raises"]
        if overrides.get("hangs"):
            await asyncio.sleep(60)
        return {"study_accession": study_accession, "pubmed_id": pubmed_id,
                "assays": {"flow cytometry assay": _ENTRY}, "rounds": {},
                "meta": {"llm_calls": 4}}

    monkeypatch.setattr(routes, "assay_report", _fake)
    return seen


def _poll(client, job_id: str, until=("done", "error", "cancelled"), tries: int = 50) -> dict:
    """Poll the way the browser does, until the run reaches a terminal state."""
    for _ in range(tries):
        body = client.get(f"/agent/assays/runs/{job_id}").json()
        if body["state"] in until:
            return body
    raise AssertionError(f"run {job_id} never reached {until}")


# ── the free endpoints spend nothing ──────────────────────────────────────────

def test_the_paper_list_offers_every_study_with_an_xml(extracted, client, no_spending):
    response = client.get("/agent/assay-papers")

    assert response.status_code == 200
    papers = response.json()["papers"]
    assert [(p["pubmed_id"], p["study_accession"]) for p in papers] == [("111", "SDY1")]
    assert papers[0]["has_registry"] is True
    assert papers[0]["assays"] == 1
    assert no_spending.calls == 0


def test_a_paper_that_has_never_been_run_is_still_offered(paper, client):
    """The XML is the gate, not the registry."""
    papers = client.get("/agent/assay-papers").json()["papers"]

    assert papers[0]["has_registry"] is False
    assert papers[0]["assays"] is None


def test_the_estimate_costs_nothing_and_sizes_what_it_can(extracted, client, no_spending):
    response = client.post("/agent/assays/estimate",
                           json={"pubmed_id": "111", "study_accession": "SDY1"})

    assert response.status_code == 200
    body = response.json()
    assert {r["name"]: r["calls"] for r in body["rounds"]} == {
        "extract": 1, "verify": 1, "correct": 0, "obi": 0, "canonicalize": 0}
    assert body["total_calls_known"] is True
    assert no_spending.calls == 0


def test_the_stored_registry_is_served_without_a_single_call(extracted, client, no_spending):
    """This is what makes the page useful before anything has been paid for -- and what a
    caller falls back to when the backend restarted and lost its job."""
    response = client.get("/agent/assays/registry",
                          params={"pubmed_id": "111", "study_accession": "SDY1"})

    assert response.status_code == 200
    body = response.json()
    assert list(body["benchmark"]) == ["flow cytometry"]
    # Recomputed, not read back: a registry that was fine when written can stop matching if the
    # paper's XML is re-fetched.
    assert body["quote_check"]["verified"] == 1
    assert no_spending.calls == 0


def test_the_stored_read_still_names_the_assays_obi_has_no_term_for(extracted, client):
    """A stored registry keeps no round record, so the unmapped names would go unreported --
    and an unmapped entry looks exactly like a mapped one in the registry itself. Rebuilt from
    the stored mapping rather than dropped."""
    (extracted / "assays_OBI.json").write_text(json.dumps({
        "flow cytometry": {**_ENTRY, "obi_id": "OBI:0000916", "resource": "exact_original"},
        "SIMoA": {**_ENTRY, "obi_id": None, "resource": "unresolved"},
    }), encoding="utf-8")

    body = client.get("/agent/assays/registry",
                      params={"pubmed_id": "111", "study_accession": "SDY1"}).json()

    assert body["rounds"]["obi"]["source"] == "mapped"
    assert body["rounds"]["obi"]["unresolved"] == ["SIMoA"]


def test_a_registry_that_was_never_mapped_says_so_rather_than_reporting_no_gaps(extracted,
                                                                                client):
    """"Round 4 never ran" and "round 4 found nothing unmapped" are different facts, and the
    keys are only OBI labels in the second case."""
    body = client.get("/agent/assays/registry",
                      params={"pubmed_id": "111", "study_accession": "SDY1"}).json()

    assert body["rounds"]["obi"] == {"source": "skipped"}


def test_a_paper_with_nothing_extracted_has_no_registry_to_read(paper, client):
    response = client.get("/agent/assays/registry",
                          params={"pubmed_id": "111", "study_accession": "SDY1"})

    assert response.status_code == 404
    assert "nothing has been extracted" in response.json()["detail"]


def test_the_free_endpoints_refuse_a_request_naming_no_paper(client):
    assert client.post("/agent/assays/estimate", json={}).status_code == 400
    assert client.get("/agent/assays/registry").status_code == 400


def test_estimating_a_paper_with_no_xml_is_a_404(paper, client):
    assert client.post("/agent/assays/estimate",
                       json={"study_accession": "SDY999"}).status_code == 404


# ── the cost gate ─────────────────────────────────────────────────────────────

def test_a_run_that_never_asked_what_it_costs_is_refused(extracted, client, monkeypatch):
    """CLAUDE.md's rule, enforced in the protocol rather than in one front end: a client must
    have asked for the estimate before it can start a run."""
    seen = _stub_report(monkeypatch)

    response = client.post("/agent/assays/runs",
                           json={"pubmed_id": "111", "study_accession": "SDY1"})

    assert response.status_code == 400
    assert "estimate" in response.json()["detail"]
    # And nothing was started: the refusal is before the task, not after it.
    assert seen == {}
    assert assay_jobs._JOBS == {}


def test_a_run_may_acknowledge_that_the_cost_could_not_be_sized(paper, client, monkeypatch):
    """A paper that has never been run reports total_calls as null, and a caller that saw that
    has nothing to echo back -- but it did see the gate."""
    _stub_report(monkeypatch)

    response = client.post("/agent/assays/runs",
                           json={"pubmed_id": "111", "study_accession": "SDY1",
                                 "acknowledged_unknown": True})

    assert response.status_code == 202


def test_starting_a_run_returns_an_id_immediately_rather_than_holding_the_connection(
        extracted, client, monkeypatch):
    seen = _stub_report(monkeypatch)

    response = client.post("/agent/assays/runs",
                           json={"pubmed_id": "111", "study_accession": "SDY1",
                                 "acknowledged_calls": 2})

    assert response.status_code == 202
    body = response.json()
    assert body["id"]
    assert body["acknowledged_calls"] == 2
    assert body["estimate"]["total_calls"] == 2
    assert _poll(client, body["id"])["state"] == "done"
    assert (seen["pubmed_id"], seen["study_accession"]) == ("111", "SDY1")


def test_the_result_is_attached_once_the_run_finishes(extracted, client, monkeypatch):
    _stub_report(monkeypatch)

    job_id = client.post("/agent/assays/runs",
                         json={"pubmed_id": "111", "study_accession": "SDY1",
                               "acknowledged_calls": 2}).json()["id"]

    finished = _poll(client, job_id)
    assert list(finished["result"]["assays"]) == ["flow cytometry assay"]
    assert finished["progress"]["calls"] == 4


def test_an_estimate_that_moved_is_recorded_rather_than_blocking_the_run(
        extracted, client, monkeypatch):
    """Rounds 2 and 3 were always approximate, so refusing over a moved approximation would
    block the papers the estimate is most useful on."""
    _stub_report(monkeypatch)

    body = client.post("/agent/assays/runs",
                       json={"pubmed_id": "111", "study_accession": "SDY1",
                             "acknowledged_calls": 99}).json()

    assert body["estimate_drift"] == {"acknowledged": 99, "estimated": 2}
    assert _poll(client, body["id"])["state"] == "done"


def test_a_run_for_a_paper_with_no_xml_fails_before_it_spends(paper, client, monkeypatch):
    seen = _stub_report(monkeypatch)

    response = client.post("/agent/assays/runs",
                           json={"study_accession": "SDY999", "acknowledged_unknown": True})

    assert response.status_code == 404
    assert seen == {}


# ── the double-spend guard ────────────────────────────────────────────────────

def test_a_second_run_for_the_same_paper_is_refused_with_the_first_ones_id(
        extracted, client, monkeypatch):
    """Two tabs, or a double-click. The only mistake on this page that costs money, so the
    refusal hands back the id to adopt rather than telling the caller to try again."""
    _stub_report(monkeypatch, hangs=True)

    first = client.post("/agent/assays/runs",
                        json={"pubmed_id": "111", "study_accession": "SDY1",
                              "acknowledged_calls": 2}).json()
    second = client.post("/agent/assays/runs",
                         json={"pubmed_id": "111", "study_accession": "SDY1",
                               "acknowledged_calls": 2})

    assert second.status_code == 409
    assert first["id"] in second.json()["detail"]
    client.post(f"/agent/assays/runs/{first['id']}/cancel")


def test_a_different_paper_is_not_blocked_by_a_run_in_flight(extracted, tmp_path, client,
                                                             monkeypatch):
    _stub_report(monkeypatch, hangs=True)
    (assay_service.XML_ROOT / "SDY2_222.xml").write_text(_XML, encoding="utf-8")

    first = client.post("/agent/assays/runs",
                        json={"pubmed_id": "111", "study_accession": "SDY1",
                              "acknowledged_calls": 2}).json()
    second = client.post("/agent/assays/runs",
                         json={"pubmed_id": "222", "study_accession": "SDY2",
                               "acknowledged_unknown": True})

    assert second.status_code == 202
    for job_id in (first["id"], second.json()["id"]):
        client.post(f"/agent/assays/runs/{job_id}/cancel")


# ── polling, stopping, and losing the backend ─────────────────────────────────

def test_a_failed_run_reports_why_rather_than_staying_on_running_forever(
        extracted, client, monkeypatch):
    from app.agent.assay_extractor import AssayExtractionError
    _stub_report(monkeypatch, raises=AssayExtractionError("the model returned no JSON"))

    job_id = client.post("/agent/assays/runs",
                         json={"pubmed_id": "111", "study_accession": "SDY1",
                               "acknowledged_calls": 2}).json()["id"]

    finished = _poll(client, job_id)
    assert finished["state"] == "error"
    assert "no JSON" in finished["error"]


def test_stopping_a_run_is_terminal_and_keeps_what_it_already_spent(extracted, client,
                                                                    monkeypatch):
    _stub_report(monkeypatch, hangs=True)
    job_id = client.post("/agent/assays/runs",
                         json={"pubmed_id": "111", "study_accession": "SDY1",
                               "acknowledged_calls": 2}).json()["id"]

    response = client.post(f"/agent/assays/runs/{job_id}/cancel")

    assert response.status_code == 200
    finished = _poll(client, job_id)
    assert finished["state"] == "cancelled"
    # Round 1 reported before the stub hung. Stopping is not a refund.
    assert finished["progress"]["calls"] == 1


def test_stopping_a_finished_run_says_there_was_nothing_to_stop(extracted, client, monkeypatch):
    _stub_report(monkeypatch)
    job_id = client.post("/agent/assays/runs",
                         json={"pubmed_id": "111", "study_accession": "SDY1",
                               "acknowledged_calls": 2}).json()["id"]
    _poll(client, job_id)

    assert client.post(f"/agent/assays/runs/{job_id}/cancel").status_code == 409


def test_polling_a_run_the_backend_no_longer_remembers_points_at_the_files_it_wrote(client):
    """Under `uvicorn --reload` this is the normal case, not an edge one -- so the 404 says
    where the result actually is rather than reading as a lost run."""
    response = client.get("/agent/assays/runs/nosuchjob")

    assert response.status_code == 404
    assert "registry directory" in response.json()["detail"]


def test_stopping_a_run_the_backend_no_longer_remembers_is_a_404(client):
    assert client.post("/agent/assays/runs/nosuchjob/cancel").status_code == 404
