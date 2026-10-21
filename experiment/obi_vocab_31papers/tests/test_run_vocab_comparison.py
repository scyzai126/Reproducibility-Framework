import json

import pytest

import run_vocab_comparison as rvc


def _registry(tmp_path, name="1_SDY1"):
    reg = tmp_path / "stability" / name
    reg.mkdir(parents=True)
    assays = {"enzyme-linked immunosorbent assay": {
        "name_in_paper": ["ELISA"], "standard_technique_name": "enzyme-linked immunosorbent assay",
        "sample_type": "plasma", "readouts": "IgG"}}
    (reg / "assays.json").write_text(json.dumps(assays))
    (reg / "assays_benchmark.json").write_text(json.dumps({
        "enzyme-linked immunosorbent assay": {"name_in_paper": ["ELISA"], "aliases": [], "generate_claim": True,
                                              "source": "methods", "evidence": {"quote": "ELISA was done."}}}))
    return reg


def test_dry_run_never_reaches_the_mapper_and_writes_nothing(tmp_path, monkeypatch, capsys):
    from app.agent import assay_obi_mapper as mapper

    _registry(tmp_path)
    monkeypatch.setattr(mapper, "enrich_assays_with_obi", lambda *a, **k: pytest.fail("mapper called"))
    rvc.run_map(["pruned", "full"], dry_run=True, source=tmp_path / "stability", runs_dir=tmp_path / "runs")
    out = capsys.readouterr().out
    assert "arm pruned" in out and "arm full" in out and "nothing called" in out
    # ELISA: free on the pruned index (childless exact hit), paid on the full one (53 children)
    assert "1 entries, 0 reach the paid step" in out
    assert "1 entries, 1 reach the paid step" in out
    assert not (tmp_path / "runs").exists()


def test_map_writes_the_four_files_and_is_resumable(tmp_path, monkeypatch, capsys):
    from app.agent import assay_obi_mapper as mapper

    reg = _registry(tmp_path)
    calls = []

    def fake_enrich(assays, terms_path, **_):
        calls.append(terms_path.name)
        return {k: {**v, "obi_id": "OBI:0000661", "obi_label": "enzyme-linked immunosorbent assay",
                    "resource": "embedding_llm", "obi_confidence": 0.5, "obi_granularity": "EXACT"}
                for k, v in assays.items()}

    monkeypatch.setattr(mapper, "enrich_assays_with_obi", fake_enrich)
    rvc.run_map(["pruned", "full"], dry_run=False, source=tmp_path / "stability", runs_dir=tmp_path / "runs")
    assert calls == ["obi_assay_pruned_index.json", "obi_assay_full_index.json"]
    for arm in ("pruned", "full"):
        out = tmp_path / "runs" / arm / "1_SDY1"
        assert sorted(p.name for p in out.iterdir()) == ["assays.json", "assays_OBI.json", "assays_benchmark.json", "raw.json"]
    # the patch is undone after the full arm
    assert mapper._EMBEDDINGS_PATH.name == "obi_assay_pruned_embeddings.json"
    # a second run skips what is mapped, --force redoes it
    rvc.run_map(["pruned"], dry_run=False, source=tmp_path / "stability", runs_dir=tmp_path / "runs")
    assert len(calls) == 2 and "skip 1_SDY1" in capsys.readouterr().out
    rvc.run_map(["pruned"], dry_run=False, source=tmp_path / "stability", runs_dir=tmp_path / "runs", force=True)
    assert len(calls) == 3
    assert sorted(p.name for p in reg.iterdir()) == ["assays.json", "assays_benchmark.json"]


def _arm_output(tmp_path, arm, picks):
    out = tmp_path / "runs" / arm / "1_SDY1"
    out.mkdir(parents=True)
    (out / "assays_OBI.json").write_text(json.dumps({
        k: {"obi_id": i, "obi_label": l, "resource": "embedding_llm"} for k, (i, l) in picks.items()}))
    return out


def test_report_diffs_the_arms_against_the_curator(tmp_path):
    _arm_output(tmp_path, "pruned", {
        "same": ("OBI:0000916", "flow cytometry assay"),
        "pruned_right": ("OBI:0000911", "real time reverse-transcription polymerase chain reaction assay"),
        "full_right": ("OBI:0000661", "enzyme-linked immunosorbent assay")})
    _arm_output(tmp_path, "full", {
        "same": ("OBI:0000916", "flow cytometry assay"),
        "pruned_right": ("OBI:0001170", "reverse transcription polymerase chain reaction assay"),
        "full_right": ("OBI:1110151", "ELISA measuring epitope specific interferon-gamma production by T cells")})
    comparison = tmp_path / "comparison"
    comparison.mkdir()
    scorer_report = {"totals": {"papers": 1, "benchmark_total": 3, "ours_total": 3, "matched": 3, "exact": 2,
                                "missed": 0, "extra": 0, "obi_exact_rate": 2 / 3, "obi_recall": 2 / 3,
                                "status_counts": {"MATCH": 2, "MATCH_OBI_CONFLICT": 1}},
                     "papers": [{"registry_dir": str(tmp_path / "runs" / "pruned" / "1_SDY1"), "rows": [
                         {"status": "MATCH", "benchmark": {"obi_id": "OBI:0000916", "obi_label": "flow cytometry assay"},
                          "ours": [{"key": "same"}]},
                         {"status": "MATCH", "benchmark": {"obi_id": "OBI:0000911", "obi_label": "real time RT-PCR"},
                          "ours": [{"key": "pruned_right"}]},
                         {"status": "MATCH_OBI_CONFLICT", "benchmark": {"obi_id": "OBI:1110151", "obi_label": "ELISA measuring ..."},
                          "ours": [{"key": "full_right"}]}]}]}
    (comparison / "pruned.json").write_text(json.dumps(scorer_report))
    (comparison / "full.json").write_text(json.dumps(scorer_report))
    summary = rvc.run_report(runs_dir=tmp_path / "runs", comparison_dir=comparison, reference_dir=None)
    rows = summary["diffs"]["pruned_vs_full"]
    assert [r["key"] for r in rows] == ["pruned_right", "full_right"]
    assert rows[0]["agrees_with_curator"] == "pruned" and not rows[0]["full_term_is_compositional"]
    assert rows[1]["agrees_with_curator"] == "full" and rows[1]["full_term_is_compositional"]
    assert rows[1]["full_term_outside_pruned_index"]
    counts = summary["diff_counts"]["pruned_vs_full"]
    assert counts["changed"] == 2 and counts["full_term_compositional"] == 1
    assert (comparison / "summary.md").exists() and (comparison / "diff.json").exists()
    assert "| 1_SDY1 | full_right |" in (comparison / "summary.md").read_text()


def test_score_runs_the_v2_comparator_on_a_registry(tmp_path):
    reg = _registry(tmp_path)
    (reg / "assays_OBI.json").write_text(json.dumps({"enzyme-linked immunosorbent assay": {
        "obi_id": "OBI:0000661", "obi_label": "enzyme-linked immunosorbent assay", "resource": "exact_original"}}))
    bench = tmp_path / "bench"
    bench.mkdir()
    (bench / "SDY1_assays.json").write_text(json.dumps({"ELISA": {
        "name_in_paper": "ELISA", "aliases": [], "generate_claim": True,
        "OBI ontology": {"obi_id": "OBI:0000661", "obi_label": "enzyme-linked immunosorbent assay"},
        "evidence_location": {"type": "text", "section": "Methods", "quote": "ELISA was done."}}}))
    report = rvc.score_dir(tmp_path / "stability", tmp_path / "comparison" / "x", benchmark_dir=bench)
    assert report["totals"]["papers"] == 1 and report["totals"]["exact"] == 1
    assert "obi_exact_rate" in report["totals"]
    assert (tmp_path / "comparison" / "x.json").exists() and (tmp_path / "comparison" / "x.html").exists()
