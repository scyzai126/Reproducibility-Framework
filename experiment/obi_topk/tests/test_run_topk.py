import json

import numpy as np
import pytest

import run_topk as rt


def _registry(tmp_path):
    reg = tmp_path / "stability" / "1_SDY1"
    reg.mkdir(parents=True)
    (reg / "assays.json").write_text(json.dumps({
        "flow cytometry assay": {"name_in_paper": ["Flow cytometric analysis", "FACS panel"], "aliases": ["flow"],
                                 "standard_technique_name": "flow cytometry"},
        "Olink assay": {"name_in_paper": ["Olink assay"], "standard_technique_name": "Olink assay"},
    }))
    return reg


def test_queries_are_built_exactly_as_the_mapper_builds_them(tmp_path):
    from app.agent.assay_obi_mapper import _paper_query
    from app.agent.assay_service import _obi_query

    _registry(tmp_path)
    recs = rt.entries(tmp_path / "stability")
    flow = next(r for r in recs if r["key"] == "flow cytometry assay")
    assays = json.loads((tmp_path / "stability" / "1_SDY1" / "assays.json").read_text())
    original, normalized = _obi_query("flow cytometry assay", assays["flow cytometry assay"])
    assert flow["name"] == original and flow["technique_query"] == normalized
    assert flow["paper_query"] == _paper_query(original, ["FACS panel", "flow"])
    olink = next(r for r in recs if r["key"] == "Olink assay")
    assert olink["technique_query"] == ""  # same as the name: the mapper retrieves once
    assert rt.query_strings(recs) == [flow["paper_query"], "flow cytometry", "Olink assay"]


def test_embed_queries_dry_run_calls_nothing_and_the_cache_is_reused(tmp_path, monkeypatch):
    from app.agent import assay_obi_mapper as m

    _registry(tmp_path)
    cache = tmp_path / "q.json"
    monkeypatch.setattr(m, "_embed_query", lambda t: pytest.fail("embedded during dry run"))
    rt.embed_queries(True, cache_path=cache, source=tmp_path / "stability")
    assert not cache.exists()
    calls = []
    monkeypatch.setattr(m, "_embed_query", lambda t: calls.append(t) or np.ones(4))
    rt.embed_queries(False, cache_path=cache, source=tmp_path / "stability")
    assert len(calls) == 3 and len(json.loads(cache.read_text())) == 3
    rt.embed_queries(False, cache_path=cache, source=tmp_path / "stability")
    assert len(calls) == 3  # nothing re-embedded


def test_cached_queries_serve_vectors_and_refuse_unknown_text():
    from app.agent import assay_obi_mapper as m

    before = m._embed_query
    with rt.CachedQueries({"flow": [3.0, 4.0]}):
        assert np.allclose(m._embed_query("flow"), [0.6, 0.8])
        with pytest.raises(KeyError):
            m._embed_query("not cached")
    assert m._embed_query is before


def test_recall_places_the_curated_term_by_rank(tmp_path, monkeypatch):
    """A 4-term vocabulary with hand-made vectors: the curated term is 3rd by similarity, so it is
    on the list at K=3 and not at K=2; the compositional decoy is counted."""
    from app.agent import assay_obi_mapper as m

    terms = [
        {"id": "OBI:1", "label": "alpha assay", "synonyms": [], "definition": "", "n_descendants": 0, "parents": []},
        {"id": "OBI:2", "label": "beta assay measuring X", "synonyms": [], "definition": "", "n_descendants": 0, "parents": []},
        {"id": "OBI:3", "label": "gamma assay", "synonyms": [], "definition": "", "n_descendants": 0, "parents": []},
        {"id": "OBI:4", "label": "delta assay", "synonyms": [], "definition": "", "n_descendants": 0, "parents": []},
    ]
    index = tmp_path / "index.json"
    index.write_text(json.dumps(terms))
    vectors = {"OBI:1": [1, 0, 0], "OBI:2": [0.9, 0.1, 0], "OBI:3": [0.8, 0.2, 0], "OBI:4": [0, 0, 1]}
    rows = [{"id": t["id"], "label": t["label"], "text": t["label"], "embedding": vectors[t["id"]]} for t in terms]
    emb = tmp_path / "emb.json"
    emb.write_text(json.dumps(rows))
    monkeypatch.setattr(m, "_EMBEDDINGS_PATH", emb)
    monkeypatch.setattr(m, "_is_generic_assay_term", lambda i, l: True)
    for name in ("_load_embeddings", "_build_lookup", "_term_ids", "_index_children", "_index_parents", "_index_entries", "_term_details"):
        getattr(m, name).cache_clear()
    records = [{"registry": "r", "key": "k", "name": "my assay", "aliases": [], "paper_query": "my assay", "technique_query": ""}]
    cache = {"my assay": [1, 0, 0]}
    vocabs = {"pruned": {"index": index, "embeddings": emb}}
    try:
        result = rt.recall(cache, {("r", "k"): "OBI:3"}, records, ks=(2, 3), vocabs=vocabs, pruned_index=index)
    finally:
        for name in ("_load_embeddings", "_build_lookup", "_term_ids", "_index_children", "_index_parents", "_index_entries", "_term_details"):
            getattr(m, name).cache_clear()
    k2, k3 = result["vocabs"]["pruned"]["2"], result["vocabs"]["pruned"]["3"]
    assert k2["hits"] == 0 and k3["hits"] == 1 and k3["rows"][0]["rank"] == 3
    assert k3["rows"][0]["compositional"] == 1
    md = rt.render_recall(result)
    assert "| 3 |" in md and "OBI:3" in md


def test_widened_list_wraps_and_restores_the_mapper(monkeypatch):
    from app.agent import assay_obi_mapper as m

    seen = {}
    monkeypatch.setattr(m, "_top_k_candidates", lambda query, k=m.TOP_K, **kw: seen.setdefault("k", k) and [])
    monkeypatch.setattr(m, "_merge_candidates", lambda primary, *o, k=m.TOP_K, primary_slots=m.PRIMARY_SLOTS: seen.update(mk=k, ps=primary_slots) or [])
    top, merge = m._top_k_candidates, m._merge_candidates
    with rt.WidenedList(40):
        m._top_k_candidates("q")
        m._merge_candidates([])
    assert seen == {"k": 40, "mk": 40, "ps": 28}
    assert m._top_k_candidates is top and m._merge_candidates is merge
    assert m.TOP_K == 20 and m.PRIMARY_SLOTS == 14
