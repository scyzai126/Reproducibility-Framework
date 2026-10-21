import json

import pytest

import exp_obi_flat1794 as flat


@pytest.fixture(scope="module")
def index_1794():
    return flat.build_index()


def test_the_index_is_the_whole_assay_branch(index_1794):
    assert len(index_1794) == 1794
    assert all("definition" in t and "n_descendants" in t and "parents" in t for t in index_1794)
    by_id = {t["id"]: t for t in index_1794}
    assert [p["id"] for p in by_id["OBI:1110172"]["parents"]] == ["OBI:0000916", "OBI:0001414"]  # an ICS child
    assert by_id["OBI:1110172"]["parents"][0]["label"] == "flow cytometry assay"
    ids = {t["id"] for t in index_1794}
    live = {t["id"] for t in json.loads(
        (flat.REPO_ROOT / "data" / "OBI" / "obi_assay_pruned_index.json").read_text())}
    assert live < ids
    # the compositional terms the prune removed are back
    assert "OBI:1110151" in ids  # ELISA measuring epitope specific IFN-gamma production by T cells
    assert "OBI:1110207" in ids  # assay detecting IFN-gamma production


def test_the_patch_admits_compositional_terms_and_does_not_leak(tmp_path, index_1794):
    from app.agent import assay_obi_mapper as mapper

    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index_1794))
    with flat.Unpruned(tmp_path / "no_vectors.json"):
        ids = mapper._term_ids(index_path)
        assert "OBI:1110151" in ids
        assert mapper._EMBEDDINGS_PATH == tmp_path / "no_vectors.json"
        # the lookup now resolves the paper's bare technique word onto a term with children
        assert mapper._index_children(index_path).get("OBI:0000661")  # ELISA has 53 of them
    # restored: the live filter is back and the caches were cleared with it
    assert mapper._EMBEDDINGS_PATH.name == "obi_assay_pruned_embeddings.json"
    assert "OBI:1110151" not in mapper._term_ids(index_path)
    assert "OBI:1110151" not in mapper._term_ids(mapper._OBI_TERMS_PATH)


def test_plan_calls_charges_an_exact_hit_that_gained_children(tmp_path, index_1794):
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index_1794))
    assays = {
        "enzyme-linked immunosorbent assay": {
            "name_in_paper": ["ELISA"], "standard_technique_name": "enzyme-linked immunosorbent assay"},
        "Olink assay": {"name_in_paper": ["Olink assay"], "standard_technique_name": "Olink assay"},
    }
    with flat.Unpruned(tmp_path / "no_vectors.json"):
        planned = dict(flat.plan_calls(assays, index_path))
    # ELISA is free on the live index (childless there) but has 53 children here, so it is
    # pinned into the paid step; Olink is a childless exact hit in both.
    assert planned == {"enzyme-linked immunosorbent assay": 3}


def test_rows_to_embed_reuses_rows_already_in_the_output(tmp_path, index_1794):
    import build_obi_embeddings as builder

    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index_1794[:5]))
    out = tmp_path / "emb.json"
    assert flat.rows_to_embed(index_path, out) == 5
    out.write_text(json.dumps([
        {"id": t["id"], "embed_input": builder.build_embed_input(t), "embedding": [0.0]}
        for t in index_1794[:2]]))
    assert flat.rows_to_embed(index_path, out) == 3


def test_map_dry_run_calls_nothing_and_writes_nothing(tmp_path, index_1794, monkeypatch):
    from app.agent import assay_obi_mapper as mapper

    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index_1794))
    registry = tmp_path / "1_SDY1"
    registry.mkdir()
    (registry / "assays.json").write_text(json.dumps(
        {"ELISA": {"name_in_paper": ["ELISA"], "standard_technique_name": "ELISA"}}))
    monkeypatch.setattr(mapper, "enrich_assays_with_obi",
                        lambda *a, **k: pytest.fail("the dry run reached the mapper"))
    result = flat.map_registry(registry, dry_run=True, results_dir=tmp_path / "results",
                               index_path=index_path, embeddings_path=tmp_path / "none.json")
    assert result is None
    assert not (tmp_path / "results").exists()


def test_map_writes_beside_the_experiment_not_into_the_registry(tmp_path, index_1794, monkeypatch):
    from app.agent import assay_obi_mapper as mapper

    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index_1794))
    vectors = tmp_path / "emb.json"
    vectors.write_text("[]")
    registry = tmp_path / "1_SDY1"
    registry.mkdir()
    (registry / "assays.json").write_text(json.dumps(
        {"ELISA": {"name_in_paper": ["ELISA"], "standard_technique_name": "ELISA"}}))

    def fake_enrich(assays, terms_path, **_):
        assert terms_path == index_path
        return {k: {**v, "obi_id": "OBI:1110151", "resource": "embedding_llm",
                    "obi_label": "ELISA measuring epitope specific interferon-gamma production by T cells"}
                for k, v in assays.items()}

    monkeypatch.setattr(mapper, "enrich_assays_with_obi", fake_enrich)
    out = flat.map_registry(registry, dry_run=False, results_dir=tmp_path / "results",
                            index_path=index_path, embeddings_path=vectors)
    written = json.loads((tmp_path / "results" / "1_SDY1" / "assays_OBI.json").read_text())
    assert written == out and written["ELISA"]["obi_id"] == "OBI:1110151"
    assert (tmp_path / "results" / "1_SDY1" / "raw.json").exists()
    assert sorted(p.name for p in registry.iterdir()) == ["assays.json"]
