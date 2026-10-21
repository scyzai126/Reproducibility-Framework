import json

import pytest

import run_descent_comparison as rdc


def _registry(tmp_path, name="1_SDY1264"):
    reg = tmp_path / "source" / name
    reg.mkdir(parents=True)
    assays = {
        "enzyme-linked immunosorbent assay": {
            "name_in_paper": ["ELISA"], "standard_technique_name": "enzyme-linked immunosorbent assay",
            "sample_type": "plasma", "readouts": "IgG"},
        "western blot assay": {
            "name_in_paper": ["immunoblot analysis"], "standard_technique_name": "western blot",
            "sample_type": "PBMC lysate", "readouts": "protein bands"},
    }
    (reg / "assays.json").write_text(json.dumps(assays))
    (reg / "assays_benchmark.json").write_text(json.dumps({k: {"name_in_paper": v["name_in_paper"]}
                                                           for k, v in assays.items()}))
    (reg / "assays_OBI.json").write_text(json.dumps({
        "enzyme-linked immunosorbent assay": {**assays["enzyme-linked immunosorbent assay"],
                                              "obi_id": "OBI:0000661", "resource": "exact_original"},
        "western blot assay": {**assays["western blot assay"], "obi_id": "OBI:0000854",
                               "resource": "embedding_llm"},
    }))
    return reg


def test_registries_are_the_chosen_papers_in_order(tmp_path):
    for name in ("3_SDY1260", "1_SDY1264", "2_SDY1373", "9_SDY9999"):
        _registry(tmp_path, name)

    assert [d.name for d in rdc.registries(tmp_path / "source")] == ["1_SDY1264", "2_SDY1373", "3_SDY1260"]
    assert [d.name for d in rdc.registries(tmp_path / "source", only="sdy1373")] == ["2_SDY1373"]


def test_dry_run_estimates_under_the_descent_and_writes_nothing(tmp_path, monkeypatch, capsys):
    from app.agent import assay_obi_mapper as mapper

    _registry(tmp_path)
    monkeypatch.setattr(mapper, "enrich_assays_with_obi", lambda *a, **k: pytest.fail("mapper called"))

    rdc.run_map(dry_run=True, source=tmp_path / "source", runs_dir=tmp_path / "runs")

    out = capsys.readouterr().out
    # descend: ELISA is a childless exact hit (free); the immunoblot misses the vocabulary and
    # walks from the root, billed the descent's typical depth -- not the embedding path's 3.
    assert "2 entries, 1 reach the paid step, ~3 calls (1-5 each by depth)" in out
    assert "      3  western blot assay" in out
    # hybrid: one call per stored pick with children -- western blot (OBI:0000854) has one in
    # the live index, ELISA (OBI:0000661) none.
    assert "2 entries, 1 reach the paid step, ~1 calls (one per stored pick with children)" in out
    assert "      1  western blot assay" in out
    assert "nothing called" in out
    assert not (tmp_path / "runs").exists()


def test_map_copies_the_embedding_arm_and_walks_the_descend_arm_in_process(tmp_path, monkeypatch, capsys):
    from app.agent import assay_obi_mapper as mapper
    from app.config import settings

    reg = _registry(tmp_path)
    before = {p.name: p.read_text() for p in reg.iterdir()}
    seen = []

    def fake_enrich(assays, **_):
        seen.append(settings.OBI_MAPPING_STRATEGY)
        return {k: {**v, "obi_id": "OBI:0001978", "obi_label": "immunoblot assay", "resource": "descend_llm",
                    "obi_confidence": None, "obi_granularity": "EXACT",
                    "obi_path": ["OBI:0000443", "OBI:0001978"], "obi_calls": 2, "obi_backoff": False}
                for k, v in assays.items()}

    monkeypatch.setattr(mapper, "enrich_assays_with_obi", fake_enrich)
    monkeypatch.setattr(settings, "OBI_MAPPING_STRATEGY", "embedding")

    rdc.run_map(dry_run=False, source=tmp_path / "source", runs_dir=tmp_path / "runs", arms=("descend",))

    assert seen == ["descend"], "the walk ran under the descent strategy"
    assert settings.OBI_MAPPING_STRATEGY == "embedding", "and the setting was put back"
    emb = tmp_path / "runs" / "embedding" / "1_SDY1264"
    assert sorted(p.name for p in emb.iterdir()) == ["assays.json", "assays_OBI.json", "assays_benchmark.json"]
    assert json.loads((emb / "assays_OBI.json").read_text())["western blot assay"]["resource"] == "embedding_llm"
    des = tmp_path / "runs" / "descend" / "1_SDY1264"
    assert sorted(p.name for p in des.iterdir()) == ["assays.json", "assays_OBI.json", "assays_benchmark.json", "raw.json"]
    assert json.loads((des / "assays_OBI.json").read_text())["western blot assay"]["obi_id"] == "OBI:0001978"
    # the source registry is untouched
    assert {p.name: p.read_text() for p in reg.iterdir()} == before
    # resumable
    rdc.run_map(dry_run=False, source=tmp_path / "source", runs_dir=tmp_path / "runs", arms=("descend",))
    assert len(seen) == 1 and "skip 1_SDY1264" in capsys.readouterr().out
    rdc.run_map(dry_run=False, source=tmp_path / "source", runs_dir=tmp_path / "runs", force=True,
                arms=("descend",))
    assert len(seen) == 2


def test_the_hybrid_arm_descends_from_the_stored_pick_only_when_it_has_children(tmp_path, monkeypatch, capsys):
    from app.agent import assay_obi_mapper as mapper

    reg = _registry(tmp_path)
    seen = []

    def fake_descend(start_id, assay_name, **kw):
        seen.append((start_id, assay_name, kw["aliases"], kw["standard_technique_name"], kw["trace_round"]))
        return {"obi_id": "OBI:0001978", "obi_label": "immunoblot assay", "resource": "descend_llm",
                "confidence": None, "granularity": "EXACT", "path": [start_id, "OBI:0001978"],
                "calls": 1, "backoff": False}

    monkeypatch.setattr(mapper, "_descend", fake_descend)
    monkeypatch.setattr(mapper, "_index_children", lambda terms_path=None: {"OBI:0000854": ("OBI:x",)})

    rdc.run_map(dry_run=False, source=tmp_path / "source", runs_dir=tmp_path / "runs", arms=("hybrid",))

    # only the western blot pick has children; ELISA is handed back untouched and unpaid
    assert seen == [("OBI:0000854", "immunoblot analysis", None, "western blot", "obi_descend")]
    out = json.loads((tmp_path / "runs" / "hybrid" / "1_SDY1264" / "assays_OBI.json").read_text())
    assert out["western blot assay"]["obi_id"] == "OBI:0001978"
    assert out["western blot assay"]["resource"] == "embedding_llm_descended"
    assert out["western blot assay"]["obi_path"] == ["OBI:0000854", "OBI:0001978"]
    assert out["western blot assay"]["obi_calls"] == 1
    assert out["enzyme-linked immunosorbent assay"]["obi_id"] == "OBI:0000661"
    assert out["enzyme-linked immunosorbent assay"]["resource"] == "exact_original"
    assert out["enzyme-linked immunosorbent assay"]["obi_calls"] == 0
    assert "1_SDY1264: 2/2 mapped, 1 calls" in capsys.readouterr().out
    assert sorted(p.name for p in reg.iterdir()) == ["assays.json", "assays_OBI.json", "assays_benchmark.json"]


def test_the_setting_is_restored_when_the_mapper_raises(tmp_path, monkeypatch):
    from app.agent import assay_obi_mapper as mapper
    from app.config import settings

    _registry(tmp_path)
    monkeypatch.setattr(mapper, "enrich_assays_with_obi", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(settings, "OBI_MAPPING_STRATEGY", "embedding")

    with pytest.raises(RuntimeError):
        rdc.map_descend_one(tmp_path / "source" / "1_SDY1264", tmp_path / "runs")

    assert settings.OBI_MAPPING_STRATEGY == "embedding"


def test_the_summary_shows_the_walk_beside_each_changed_term():
    summary = {
        "totals": {
            "embedding": {"papers": 3, "benchmark_total": 20, "ours_total": 18, "matched": 17, "exact": 13,
                          "missed": 3, "extra": 1, "obi_exact_rate": 0.76, "obi_recall": 0.65,
                          "status_counts": {"MATCH": 13, "MATCH_OBI_CONFLICT": 3, "MISSED": 3},
                          "unresolved": 0, "errors": 0, "backoffs": 0, "calls": 41},
            "descend": {"papers": 3, "benchmark_total": 20, "ours_total": 18, "matched": 17, "exact": 15,
                        "missed": 3, "extra": 1, "obi_exact_rate": 0.88, "obi_recall": 0.75,
                        "status_counts": {"MATCH": 15, "MATCH_OBI_CONFLICT": 1, "MISSED": 3},
                        "unresolved": 0, "errors": 0, "backoffs": 1, "calls": 38},
        },
        "changed": {"descend": [{
            "registry": "1_SDY1264", "key": "western blot assay",
            "embedding": {"obi_id": "OBI:0000854", "obi_label": "western blot assay", "resource": "embedding_llm"},
            "descend": {"obi_id": "OBI:0001978", "obi_label": "immunoblot assay", "resource": "descend_llm",
                        "obi_path": ["OBI:0000443", "OBI:0001978"], "obi_calls": 2, "obi_backoff": False,
                        "obi_granularity": "EXACT",
                        "levels": [{"node": "OBI:0000070", "reply": "8", "n_candidates": 96},
                                   {"node": "OBI:0000443", "reply": "12 exact", "n_candidates": 79}]},
            "curator": {"obi_id": "OBI:0001978", "obi_label": "immunoblot assay"},
            "agrees_with_curator": "descend", "status": {"embedding": "MATCH_GRANULARITY", "descend": "MATCH"},
        }]},
        "per_entry": [{
            "registry": "1_SDY1264", "key": "western blot assay", "curator": {"obi_id": "OBI:0001978"},
            "embedding": {"obi_id": "OBI:0000854", "status": "MATCH_GRANULARITY"},
            "descend": {"obi_id": "OBI:0001978", "status": "MATCH", "obi_calls": 2},
        }],
        "changed_counts": {"descend": {"descend": 1}},
    }

    md = rdc.render_summary(summary)

    assert "| walks that backed off | 0 | 1 |" in md
    assert "| calls spent | 41 | 38 |" in md
    assert "OBI:0000443 → OBI:0001978 (2)" in md
    assert "OBI:0000070:8; OBI:0000443:12 exact" in md
    assert "| OBI:0000854 (MATCH_GRANULARITY) | OBI:0001978 (MATCH, 2 calls) |" in md
    assert "## embedding vs descend: entries that chose different terms (1)" in md
