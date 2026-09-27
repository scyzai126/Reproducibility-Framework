"""The corpus-wide read of stored data-availability records, and the route that serves it."""

import json

from fastapi.testclient import TestClient

from app.agent import assay_service, data_availability_service
from app.main import app

FINAL = {"pmid": "34252919", "study": "SDY2189", "title": "T",
         "data_repositories": [{"accession": "GSE171964", "repository": "GEO",
                                "landing_page": "https://geo/GSE171964"}],
         "unconfirmed": []}


def _write(path, content):
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


def test_stored_all_keys_final_records_by_the_corpus_spelling(tmp_path, monkeypatch):
    monkeypatch.setattr(data_availability_service, "OUT_DIR", tmp_path)
    _write(tmp_path / "SDY2189_34252919.json", FINAL)
    _write(tmp_path / "SDY2189_34252919_llm.json", {"pmid": "34252919", "deposited": []})
    _write(tmp_path / "SDY1669_32788292.json", {"pmid": "32788292", "deposited": []})  # old format
    _write(tmp_path / "SDY1_1.json", "not json")
    _write(tmp_path / "summary.md", "# x")
    assert data_availability_service.stored_all() == {"34252919_SDY2189": FINAL}


def test_stored_all_without_a_folder_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(data_availability_service, "OUT_DIR", tmp_path / "missing")
    assert data_availability_service.stored_all() == {}


def test_corpus_route_serves_every_paper(tmp_path, monkeypatch):
    monkeypatch.setattr(data_availability_service, "OUT_DIR", tmp_path)
    _write(tmp_path / "SDY2189_34252919.json", FINAL)
    resp = TestClient(app).get("/agent/data-availability/corpus")
    assert resp.status_code == 200
    assert resp.json() == {"papers": {"34252919_SDY2189": FINAL}}


def test_a_new_paper_s_files_go_beside_its_cached_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", tmp_path / "registries")
    monkeypatch.setattr(data_availability_service, "OUT_DIR", tmp_path / "data_availability")
    cache_dir = assay_service.CACHE_ROOT / "34252919_SDY2189"
    cache_dir.mkdir(parents=True)

    assert data_availability_service.out_dir_for("34252919", "SDY2189") == cache_dir
    _write(cache_dir / "SDY2189_34252919.json", FINAL)
    assert data_availability_service.stored("34252919", "SDY2189") == FINAL


def test_a_benchmark_paper_s_files_stay_in_the_corpus_folder(tmp_path, monkeypatch):
    registries = tmp_path / "registries"
    (registries / "34252919_SDY2189").mkdir(parents=True)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registries)
    monkeypatch.setattr(data_availability_service, "OUT_DIR", tmp_path / "data_availability")

    assert data_availability_service.out_dir_for("34252919", "SDY2189") == tmp_path / "data_availability"
