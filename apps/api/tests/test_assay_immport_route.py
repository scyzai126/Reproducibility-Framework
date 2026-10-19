"""GET /agent/assay-immport, the per-paper check, and the acknowledged resolve.

The corpus sweep runs on a page load, so the properties that matter are that it serves the
coverage scripts/build_immport_coverage.py stored when that matches the table, that without one
it sweeps SQL only and never pays, that a dead database degrades instead of 500ing, that the
per-paper check pays once per missed row and then reads the cache, and that /resolve still refuses
to run until it has been told the bill. No test here reaches a real model.
"""

import json

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.agent import assay_immport
from app.database import get_session
from app.main import app


class _NeverCalled:
    def __init__(self):
        self.calls = 0
        self.chat = type("c", (), {"completions": self})()

    async def create(self, **_):
        self.calls += 1
        raise AssertionError("a free endpoint made a model call")


class _FakeModel:
    """The experiment resolver's model: answers "NONE" to everything and counts the calls."""

    def __init__(self):
        self.calls = 0
        self.chat = type("c", (), {"completions": self})()

    async def create(self, **_):
        self.calls += 1
        message = type("m", (), {"content": "NONE"})()
        return type("r", (), {"choices": [type("ch", (), {"message": message})()]})()


class _FakeSession:
    def __init__(self, experiments=None, raises=None):
        self.experiments, self.raises = experiments or {}, raises

    async def execute(self, statement, params=None):
        if self.raises is not None:
            raise self.raises
        sql, params = str(statement), params or {}
        if "COUNT(*)" in sql:
            rows = [(s, len(e)) for s, e in self.experiments.items()
                    if s in set(params.get("studies") or [])]
        elif "measurement_technique FROM experiment WHERE experiment_accession" in sql:
            wanted = params.get("acc", "")
            rows = [(tech,) for e in self.experiments.values()
                    for acc, tech in e if acc == wanted]
        elif "pattern" not in params:
            # The LLM fallback's candidate list: every experiment in the study.
            rows = list(self.experiments.get(params.get("study_accession", ""), []))
        else:
            pattern = (params.get("pattern") or "").strip("%").lower()
            rows = [(acc, tech)
                    for acc, tech in self.experiments.get(params.get("study_accession", ""), [])
                    if pattern and pattern in tech.lower()]
        return type("R", (), {
            "fetchall": lambda self: rows,
            "fetchone": lambda self: rows[0] if rows else None,
            "keys": lambda self: ["experiment_accession", "measurement_technique"],
        })()


@pytest.fixture(autouse=True)
def no_spending(monkeypatch):
    client = _NeverCalled()
    monkeypatch.setattr(routes, "_get_client", lambda: client)
    return client


@pytest.fixture(autouse=True)
def resolver_model(monkeypatch, tmp_path):
    """The fallback's model, faked, and a cache of its own so none touches the one under data/."""
    fake = _FakeModel()
    monkeypatch.setattr("app.agent.query_builder._get_openai_client", lambda: fake)
    monkeypatch.setattr(assay_immport, "LLM_CACHE_PATH", tmp_path / "immport_llm_cache.json")
    return fake


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """A two-row corpus file standing in for data/31paper_assays/all_assays_OBI.json."""
    path = tmp_path / "all_assays_OBI.json"
    path.write_text(json.dumps([
        {"study": "19029902_SDY1264", "assay": "Neut Ab", "standard_technique_name": "Virus Neutralization",
         "obi_label": "serum neutralization assay"},
        {"study": "19029902_SDY1264", "assay": "Mass spec", "standard_technique_name": "Mass spectrometry",
         "obi_label": "mass spectrometry assay"},
    ]), encoding="utf-8")
    monkeypatch.setattr(routes, "_ASSAY_OBI_PATH", path)
    # No stored coverage unless a test writes one: the live sweep is what most tests exercise.
    monkeypatch.setattr(routes, "_ASSAY_IMMPORT_PATH", tmp_path / "assay_immport.json")
    return path


@pytest.fixture
def client():
    def _make(session):
        async def _override():
            yield session
        app.dependency_overrides[get_session] = _override
        return TestClient(app)

    yield _make
    app.dependency_overrides.pop(get_session, None)


_EXPERIMENTS = {"SDY1264": [("EXP16737", "Virus Neutralization")]}


def test_the_sweep_reports_coverage_for_every_corpus_row(corpus, client, resolver_model):
    response = client(_FakeSession(_EXPERIMENTS)).get("/agent/assay-immport")

    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 2
    assert body["stats"]["matched"] == 1
    assert body["stats"]["absent"] == 1
    assert body["rows"][0]["experiment_accession"] == "EXP16737"
    assert body["rows"][0]["measurement_technique"] == "Virus Neutralization"
    # Without stored coverage the sweep is SQL only: the row SQL missed stays absent, unpaid.
    assert resolver_model.calls == 0
    assert "build_immport_coverage.py" in body["warning"]


def test_a_page_load_never_pays(corpus, client, resolver_model):
    client(_FakeSession(_EXPERIMENTS)).get("/agent/assay-immport")
    client(_FakeSession(_EXPERIMENTS)).get("/agent/assay-immport")

    assert resolver_model.calls == 0


def _store(corpus, rows_for):
    """Write stored coverage beside the corpus fixture's table, as the script would."""
    stored = {"generated_at": "2026-09-26T00:00:00+00:00", "llm": True,
              "rows": [{"study": s, "study_accession": "SDY1264", "assay": a,
                        "experiment_accession": None, "measurement_technique": None,
                        "method": None, "status": "absent", "study_experiments": 1}
                       for s, a in rows_for],
              "stats": {"total": len(rows_for), "matched": 0, "absent": len(rows_for),
                        "no_experiments": 0, "unknown_study": 0, "resolvable": len(rows_for),
                        "studies_without_experiments": []}}
    routes._ASSAY_IMMPORT_PATH.write_text(json.dumps(stored), encoding="utf-8")


def test_stored_coverage_for_this_table_is_served_without_touching_immport(corpus, client):
    _store(corpus, [("19029902_SDY1264", "Neut Ab"), ("19029902_SDY1264", "Mass spec")])

    # A session that raises proves the database was never queried.
    body = client(_FakeSession(raises=RuntimeError("must not be queried"))).get(
        "/agent/assay-immport").json()

    assert body["degraded"] is False
    assert body["warning"] is None
    assert [r["assay"] for r in body["rows"]] == ["Neut Ab", "Mass spec"]


def test_a_benchmark_only_row_is_not_swept_counted_or_used_for_staleness(corpus, client):
    """A curator assay we missed is shown in the table but is not an assay of ours."""
    rows = json.loads(corpus.read_text(encoding="utf-8"))
    rows.append({"study": "19029902_SDY1264", "assay": "", "standard_technique_name": "", "obi_id": None,
                 "obi_label": None, "resource": None, "benchmark_assay": "YFV neutralization",
                 "benchmark_only": True})
    corpus.write_text(json.dumps(rows), encoding="utf-8")

    swept = client(_FakeSession(_EXPERIMENTS)).get("/agent/assay-immport").json()
    assert len(swept["rows"]) == 2

    # Stored coverage for our two assays still matches the table.
    _store(corpus, [("19029902_SDY1264", "Neut Ab"), ("19029902_SDY1264", "Mass spec")])
    stored = client(_FakeSession(raises=RuntimeError("must not be queried"))).get(
        "/agent/assay-immport").json()
    assert stored["warning"] is None

    stats = routes._assay_obi_stats(rows)
    assert stats["total_rows"] == 2
    assert "" not in stats["unresolved_names"]


def test_stored_coverage_for_a_different_table_is_ignored(corpus, client, resolver_model):
    _store(corpus, [("19029902_SDY1264", "an assay the table no longer has")])

    body = client(_FakeSession(_EXPERIMENTS)).get("/agent/assay-immport").json()

    assert body["stats"]["matched"] == 1  # the live sweep's answer, not the stored one
    assert "build_immport_coverage.py" in body["warning"]
    assert resolver_model.calls == 0


def test_the_rows_survive_the_response_model(corpus, client):
    """A report keyed the wrong way is dropped silently by the response model, and the table
    renders empty with correct-looking statistics above it."""
    body = client(_FakeSession(_EXPERIMENTS)).get("/agent/assay-immport").json()

    assert body["rows"], "rows were filtered out by the response model"
    assert body["stats"]["total"] == len(body["rows"])


def test_a_study_with_nothing_registered_is_reported_as_such(corpus, client, resolver_model):
    body = client(_FakeSession({"SDY1264": []})).get("/agent/assay-immport").json()

    assert body["stats"]["no_experiments"] == 2
    assert body["stats"]["studies_without_experiments"] == ["SDY1264"]
    # Nothing a model could rescue, so nothing was paid for.
    assert body["stats"]["resolvable"] == 0
    assert resolver_model.calls == 0


def test_an_unreachable_database_degrades_rather_than_failing_the_page(corpus, client):
    """The assay table is readable without ImmPort; it just cannot say anything about coverage."""
    response = client(_FakeSession(raises=RuntimeError("mysql is down"))).get(
        "/agent/assay-immport")

    assert response.status_code == 200
    assert response.json()["degraded"] is True
    assert response.json()["warning"]
    assert response.json()["rows"] == []


def test_a_missing_corpus_file_is_a_404(tmp_path, client, monkeypatch):
    monkeypatch.setattr(routes, "_ASSAY_OBI_PATH", tmp_path / "nope.json")

    assert client(_FakeSession()).get("/agent/assay-immport").status_code == 404


# ── the per-paper check ───────────────────────────────────────────────────────

def test_checking_one_paper_s_rows_falls_back_to_the_model(corpus, client, resolver_model):
    """SQL places the first row; the second goes to the model, which says none match."""
    response = client(_FakeSession(_EXPERIMENTS)).post(
        "/agent/assay-immport/check",
        json={"rows": [{"study": "19029902_SDY1264", "assay": "Neut Ab",
                        "standard_technique_name": "Virus Neutralization"},
                       {"study": "19029902_SDY1264", "assay": "Mass spec",
                        "standard_technique_name": "Mass spectrometry"}]})

    assert response.status_code == 200
    body = response.json()
    assert [r["status"] for r in body["rows"]] == ["matched", "absent"]
    assert body["rows"][0]["measurement_technique"] == "Virus Neutralization"
    assert resolver_model.calls == 1


def test_a_yes_here_means_what_a_yes_in_the_corpus_table_means(corpus, client):
    """Both run assay_immport.check_rows the same way, so the two must agree."""
    session = _FakeSession(_EXPERIMENTS)
    swept = client(session).get("/agent/assay-immport").json()
    matched = [r for r in swept["rows"] if r["status"] == "matched"][0]

    checked = client(_FakeSession(_EXPERIMENTS)).post(
        "/agent/assay-immport/check",
        json={"rows": [{"study": matched["study"], "assay": matched["assay"],
                        "standard_technique_name": "Virus Neutralization"}]}).json()

    assert checked["rows"][0]["experiment_accession"] == matched["experiment_accession"]


def test_checking_nothing_is_an_empty_answer_not_an_error(corpus, client):
    """A paper whose run found no assays has nothing to check, and that is not a failure."""
    response = client(_FakeSession(_EXPERIMENTS)).post(
        "/agent/assay-immport/check", json={"rows": []})

    assert response.status_code == 200
    assert response.json()["rows"] == []


def test_the_check_degrades_when_immport_is_unreachable(corpus, client):
    """The extracted registry is readable without ImmPort; only the column is lost."""
    response = client(_FakeSession(raises=RuntimeError("mysql is down"))).post(
        "/agent/assay-immport/check",
        json={"rows": [{"study": "19029902_SDY1264", "assay": "Neut Ab"}]})

    assert response.status_code == 200
    assert response.json()["degraded"] is True
    assert response.json()["rows"] == []


# ── the endpoint that spends ──────────────────────────────────────────────────

def test_resolving_without_acknowledging_the_bill_is_refused(corpus, client):
    response = client(_FakeSession(_EXPERIMENTS)).post(
        "/agent/assay-immport/resolve",
        json={"rows": [{"study": "19029902_SDY1264", "assay": "Mass spec"}]})

    assert response.status_code == 400
    assert "acknowledged_calls" in response.json()["detail"]


def test_resolving_nothing_is_refused_rather_than_charged_for(corpus, client):
    response = client(_FakeSession(_EXPERIMENTS)).post(
        "/agent/assay-immport/resolve", json={"rows": [], "acknowledged_calls": 0})

    assert response.status_code == 400


def test_an_acknowledged_resolve_runs(corpus, client):
    """It reaches the resolver; the row here still matches by SQL, so no model call happens."""
    response = client(_FakeSession(_EXPERIMENTS)).post(
        "/agent/assay-immport/resolve",
        json={"rows": [{"study": "19029902_SDY1264", "assay": "Neut Ab",
                        "standard_technique_name": "Virus Neutralization"}],
              "acknowledged_calls": 1})

    assert response.status_code == 200
    assert response.json()["rows"][0]["experiment_accession"] == "EXP16737"
