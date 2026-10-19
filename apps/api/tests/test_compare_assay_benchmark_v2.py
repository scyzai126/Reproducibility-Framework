"""The v2 benchmark comparison: reading hand-edited benchmark JSON, one-to-one pairing, SPLIT rows,
and entries whose identity the verifier did not support.

Fixtures are inline; nothing here reads the real corpus or the OBI release.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

_INDEX = [
    {"id": "OBI:0000916", "label": "flow cytometry assay", "synonyms": []},
    {"id": "OBI:0000661", "label": "enzyme-linked immunosorbent assay", "synonyms": ["ELISA"]},
]
_OBO = """format-version: 1.2

[Term]
id: OBI:0000070
name: assay

[Term]
id: OBI:0000916
name: flow cytometry assay
is_a: OBI:0000070

[Term]
id: OBI:0000661
name: enzyme-linked immunosorbent assay
is_a: OBI:0000070
"""


@pytest.fixture(scope="module")
def mod():
    scripts = str(_REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    path = _REPO_ROOT / "scripts" / "compare_assay_benchmark_v2.py"
    spec = importlib.util.spec_from_file_location("compare_assay_benchmark_v2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def obi(mod, tmp_path):
    index = tmp_path / "index.json"
    index.write_text(json.dumps(_INDEX))
    obo = tmp_path / "obi.obo"
    obo.write_text(_OBO)
    return mod.ObiGraph(index_path=index, obo_path=obo)


def _entry(name, obi_id=None, quote="q"):
    entry = {"name_in_paper": name, "aliases": [], "generate_claim": True,
             "evidence_location": {"section": "Methods", "quote": quote}}
    if obi_id:
        entry["OBI ontology"] = {"obi_id": obi_id}
    return entry


def test_valid_json_is_not_repaired(mod, tmp_path):
    path = tmp_path / "ok.json"
    path.write_text(json.dumps({"a": _entry("a")}))
    data, repair, error = mod.load_lenient(path)
    assert list(data) == ["a"] and repair is None and error is None


def test_trailing_commas_are_removed_but_not_inside_strings(mod, tmp_path):
    path = tmp_path / "f.json"
    path.write_text('{"a": {"name_in_paper": "x, }", "aliases": ["y",],},}')
    data, repair, _ = mod.load_lenient(path)
    assert data == {"a": {"name_in_paper": "x, }", "aliases": ["y"]}}
    assert "trailing commas" in repair
    assert path.read_text().endswith(",},}")  # the file on disk is untouched


def test_missing_brace_mid_file_does_not_nest_later_entries(mod, tmp_path):
    path = tmp_path / "f.json"
    path.write_text('{"a": {"name_in_paper": "a", "x": 1,\n "b": {"name_in_paper": "b"}\n}')
    data, repair, _ = mod.load_lenient(path)
    assert list(data) == ["a", "b"]
    assert data["a"] == {"name_in_paper": "a", "x": 1}
    assert "un-nested 1" in repair


def test_unrepairable_json_reports_error(mod, tmp_path):
    path = tmp_path / "f.json"
    path.write_text('{"a": nonsense}')
    data, _, error = mod.load_lenient(path)
    assert data is None and error


def test_benchmark_rows_are_not_merged_before_matching(mod, obi):
    bench = {"ICS": _entry("ICS", "OBI:0000916"), "Ki67 flow": _entry("Ki67 flow", "OBI:0000916"),
             "SBA": _entry("SBA")}
    rows = mod.prepare_benchmark(bench, obi)
    assert list(rows) == ["ICS", "Ki67 flow", "SBA"]
    assert [r["merged_from"] for r in rows.values()] == [["ICS"], ["Ki67 flow"], ["SBA"]]
    assert [r["obi_id"] for r in rows.values()] == ["OBI:0000916", "OBI:0000916", None]


# ── pairing ──────────────────────────────────────────────────────────────────

_ARRAY_INDEX = [
    {"id": "OBI:0001985", "label": "microarray assay", "synonyms": []},
    {"id": "OBI:0001274", "label": "genotyping by array assay", "synonyms": []},
    {"id": "OBI:0002031", "label": "genotyping by SNP array assay", "synonyms": []},
    {"id": "OBI:0001463", "label": "transcription profiling by array assay", "synonyms": []},
    {"id": "OBI:0000916", "label": "flow cytometry assay", "synonyms": []},
]
_ARRAY_OBO = """format-version: 1.2

[Term]
id: OBI:0001985
name: microarray assay

[Term]
id: OBI:0001274
name: genotyping by array assay
is_a: OBI:0001985

[Term]
id: OBI:0002031
name: genotyping by SNP array assay
is_a: OBI:0001274

[Term]
id: OBI:0001463
name: transcription profiling by array assay

[Term]
id: OBI:0000916
name: flow cytometry assay
"""

_GENO_Q = "Genotyping was performed on Illumina HumanOmniExpress microarrays following the manufacturer's instructions."
_EXPR_Q = "cRNA was hybridized onto Illumina HumanHT-12v3 or HumanHT-12v4 Expression BeadChips following the manufacturer's protocol."


@pytest.fixture
def array_obi(mod, tmp_path):
    index = tmp_path / "array_index.json"
    index.write_text(json.dumps(_ARRAY_INDEX))
    obo = tmp_path / "array.obo"
    obo.write_text(_ARRAY_OBO)
    return mod.ObiGraph(index_path=index, obo_path=obo)


#: What assay_verifier.mark_identity_reviews leaves on an entry the judge did not support.
_REVIEW = {"verdict": "NOT_SUPPORTED", "reason": "a purpose clause, not an assay name"}


def _ours(name, obi_id, label, quote="…", aliases=(), review=None):
    entry = {"name_in_paper": [name], "aliases": list(aliases), "generate_claim": True,
             "source": "methods", "evidence": {"section": "Methods", "quote": quote},
             "_obi": {"obi_id": obi_id, "obi_label": label}}
    if review:
        entry["identity_review"] = review
    return entry


def _compare(mod, obi, tmp_path, bench, ours):
    registry = tmp_path / "registry"
    registry.mkdir(exist_ok=True)
    (registry / "assays_benchmark.json").write_text(
        json.dumps({k: {f: v for f, v in e.items() if f != "_obi"} for k, e in ours.items()}))
    (registry / "assays_OBI.json").write_text(json.dumps({k: e["_obi"] for k, e in ours.items()}))
    return mod.compare_paper(mod.prepare_benchmark(bench, obi), registry, obi)


def _pairs(result):
    return {(r["benchmark"] or {}).get("key"): (r["status"], [o["key"] for o in r["ours"]])
            for r in result["rows"]}


def _rows(result, status):
    return [r for r in result["rows"] if r["status"] == status]


def test_a_shared_ancestor_does_not_steal_the_entry_that_also_shares_the_quote(mod, array_obi, tmp_path):
    """SDY1276: the expression array's term is an ancestor of our SNP array's, but the genotyping
    row shares the SNP array's sentence too, so it wins it; the expression rows pair by sentence."""
    bench = {"global gene expression analysis": _entry("global gene expression analysis",
                                                       "OBI:0001985", _EXPR_Q),
             "whole-genome genotyping": _entry("whole-genome genotyping", "OBI:0001274", _GENO_Q)}
    ours = {"genotyping by SNP array assay": _ours("genotyping", "OBI:0002031",
                                                   "genotyping by SNP array assay", _GENO_Q),
            "transcription profiling by array assay": _ours(
                "global transcript abundance", "OBI:0001463",
                "transcription profiling by array assay", _EXPR_Q)}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    pairs = _pairs(result)
    assert pairs["whole-genome genotyping"] == ("MATCH_GRANULARITY", ["genotyping by SNP array assay"])
    assert pairs["global gene expression analysis"] == ("MATCH_OBI_CONFLICT",
        ["transcription profiling by array assay"])
    assert result["metrics"]["extra"] == 0


def test_one_agent_entry_is_never_counted_under_two_benchmark_rows(mod, array_obi, tmp_path):
    bench = {"genotyping array": _entry("genotyping array", "OBI:0001274", "a"),
             "expression array": _entry("expression array", "OBI:0001985", "b")}
    ours = {"genotyping by SNP array assay": _ours("SNP chip", "OBI:0002031",
                                                   "genotyping by SNP array assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    claimed = [o["key"] for r in result["rows"] if r["benchmark"] for o in r["ours"]]
    assert claimed == ["genotyping by SNP array assay"]
    assert result["metrics"]["missed"] == 1


def test_a_second_agent_entry_on_a_paired_term_is_its_own_split_row(mod, array_obi, tmp_path):
    """The benchmark row keeps its one partner and its MATCH; the extra entry is a SPLIT row of
    its own, pointing back at the row it splits, and counts against precision like an EXTRA."""
    bench = {"flow cytometry": _entry("flow cytometry", "OBI:0000916")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay"),
            "flow cytometry assay (2)": _ours("FACS staining", "OBI:0000916",
                                              "flow cytometry assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert [r["status"] for r in result["rows"]] == ["MATCH", "SPLIT"]
    assert _pairs(result)["flow cytometry"] == ("MATCH", ["flow cytometry assay"])
    split = result["rows"][1]
    assert split["benchmark"] is None and split["split_of"] == "flow cytometry"
    assert [o["key"] for o in split["ours"]] == ["flow cytometry assay (2)"]
    m = result["metrics"]
    assert (m["matched"], m["exact"], m["split"], m["extra"], m["unsupported_extra"]) == (1, 1, 1, 0, 0)
    assert m["matched"] + m["extra"] + m["split"] + m["unsupported_extra"] == m["ours_total"] == 2


def test_a_shared_sentence_pairs_entries_whose_terms_are_unrelated(mod, array_obi, tmp_path):
    bench = {"gene array": _entry("gene array", "OBI:0001985", _EXPR_Q)}
    ours = {"transcription profiling by array assay": _ours(
        "expression profiling", "OBI:0001463", "transcription profiling by array assay", _EXPR_Q)}

    row = _compare(mod, array_obi, tmp_path, bench, ours)["rows"][0]

    assert (row["status"], row["tier"]) == ("MATCH_OBI_CONFLICT", "evidence")
    assert "shared evidence sentence" in row["signals"]


def test_quotes_that_only_share_some_words_do_not_pair(mod, array_obi, tmp_path):
    bench = {"gene array": _entry("gene array", "OBI:0001985", _EXPR_Q)}
    ours = {"transcription profiling by array assay": _ours(
        "expression profiling", "OBI:0001463", "transcription profiling by array assay",
        "Total RNA was extracted from PAXgene tubes and quantified on a Bioanalyzer before use.")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert sorted(r["status"] for r in result["rows"]) == ["EXTRA", "MISSED"]


def test_an_acronym_pairs_as_a_whole_word(mod, array_obi, tmp_path):
    """SDY1596: the curator's `CFU` and the agent's `CFU counts`, neither with an OBI term."""
    bench = {"colony-forming units": {**_entry("colony-forming units"), "aliases": ["CFU"]}}
    ours = {"culturable microbial count assay": _ours(
        "culturable microbial count assay", None, None, aliases=["CFU counts"])}

    row = _compare(mod, array_obi, tmp_path, bench, ours)["rows"][0]

    assert (row["status"], row["tier"]) == ("MATCH_OBI_UNMAPPED", "short_name")


def test_a_two_letter_word_is_too_short_to_pair(mod, array_obi, tmp_path):
    bench = {"MN": _entry("MN")}
    ours = {"MN titers": _ours("MN titers", None, None)}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert sorted(r["status"] for r in result["rows"]) == ["EXTRA", "MISSED"]


def test_a_leftover_child_term_is_extra_not_a_split(mod, array_obi, tmp_path):
    """SDY984: a second assay on a child term is a different assay, not a split of the first."""
    bench = {"genotyping array": _entry("genotyping array", "OBI:0001274")}
    ours = {"genotyping by array assay": _ours("genotyping array", "OBI:0001274",
                                               "genotyping by array assay"),
            "genotyping by SNP array assay": _ours("SNP chip", "OBI:0002031",
                                                   "genotyping by SNP array assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert sorted(r["status"] for r in result["rows"]) == ["EXTRA", "MATCH"]


def test_unpaired_rows_on_the_paired_term_are_missed_not_folded(mod, array_obi, tmp_path):
    """SDY1289: four curated flow panels against the agent's one flow cytometry entry. One pairs;
    the other three are MISSED -- folding them onto the paired row hid every over-fold of round 5."""
    bench = {name: _entry(name, "OBI:0000916", f"{name} quote")
             for name in ("flow cytometry", "ICS panel", "Ki67 panel", "Th1/Th2 panel")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert [r["status"] for r in result["rows"]] == ["MATCH", "MISSED", "MISSED", "MISSED"]
    assert _pairs(result)["flow cytometry"] == ("MATCH", ["flow cytometry assay"])
    assert all(r["benchmark"]["merged_from"] == [r["benchmark"]["key"]] for r in result["rows"])
    assert result["metrics"]["benchmark_total"] == 4 and result["metrics"]["missed"] == 3
    assert result["merged_groups"] == []


def test_a_curated_assay_under_a_generic_term_keeps_its_own_partner(mod, array_obi, tmp_path):
    """SDY1289/SDY1294: the curator filed CFSE under `flow cytometry assay`; the agent kept it
    separate on its own term. Both pair, the term disagreement shows, and nothing is EXTRA."""
    bench = {"CFSE labeling": _entry("CFSE labeling", "OBI:0000916"),
             "flow cytometry": _entry("flow cytometry", "OBI:0000916")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay"),
            "CFSE proliferation assay": _ours("CFSE labeling", "OBI:0003582",
                                              "CFSE proliferation assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert _pairs(result) == {"CFSE labeling": ("MATCH_OBI_CONFLICT", ["CFSE proliferation assay"]),
                              "flow cytometry": ("MATCH", ["flow cytometry assay"])}
    assert result["metrics"]["extra"] == 0


def test_a_leftover_on_the_paired_term_is_missed_even_when_its_sibling_paired_by_name(mod, array_obi, tmp_path):
    """SDY1289: two curated `microarray assay` rows against the agent's one transcription-profiling
    entry: the one sharing the name pairs with a term disagreement, the other is a miss."""
    bench = {"gene array": _entry("gene array", "OBI:0001985"),
             "microarray analysis": _entry("microarray analysis", "OBI:0001985")}
    ours = {"transcription profiling by array assay": _ours(
        "gene array", "OBI:0001463", "transcription profiling by array assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert _pairs(result) == {"gene array": ("MATCH_OBI_CONFLICT", ["transcription profiling by array assay"]),
                              "microarray analysis": ("MISSED", [])}
    assert result["metrics"]["benchmark_total"] == 2


def test_unmapped_leftovers_are_missed(mod, array_obi, tmp_path):
    bench = {"SBA": _entry("SBA"), "SBA titre": _entry("SBA titre")}
    ours = {"SBA": _ours("SBA", None, None)}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert sorted(r["status"] for r in result["rows"]) == ["MATCH_OBI_UNMAPPED", "MISSED"]


def test_two_curated_rows_on_one_term_pair_with_the_agent_s_kept_apart_entries(mod, array_obi, tmp_path):
    """SDY1640: the curator lists ICS and flow cytometry on the same term, and round 5 keeps the
    agent's two apart under `<label> — <wording>`. Each pairs with its own; nothing is SPLIT or MISSED."""
    bench = {"intracellular cytokine staining assay": _entry("intracellular cytokine staining assay",
                                                             "OBI:0000916", "ICS quote"),
             "flow cytometry": _entry("flow cytometry", "OBI:0000916", "flow quote")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay"),
            "flow cytometry assay — intracellular cytokine staining": _ours(
                "intracellular cytokine staining", "OBI:0000916", "flow cytometry assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert _pairs(result) == {
        "intracellular cytokine staining assay": ("MATCH", ["flow cytometry assay — intracellular cytokine staining"]),
        "flow cytometry": ("MATCH", ["flow cytometry assay"])}
    m = result["metrics"]
    assert (m["matched"], m["split"], m["missed"], m["extra"]) == (2, 0, 0, 0)


# ── identity_review ──────────────────────────────────────────────────────────


def test_an_unpaired_reviewed_entry_is_unsupported_extra(mod, array_obi, tmp_path):
    """SDY212: the judge called the entry a section heading, the curator did not list it. It is
    reported, but not as the agent's precision error: the registry already flags it."""
    bench = {"flow cytometry": _entry("flow cytometry", "OBI:0000916")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay"),
            "Quantification of IAV in lung": _ours("Quantification of IAV in lung", None, None,
                                                   review=_REVIEW)}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert [r["status"] for r in result["rows"]] == ["MATCH", "UNSUPPORTED_EXTRA"]
    row = result["rows"][1]
    assert row["benchmark"] is None and [o["key"] for o in row["ours"]] == ["Quantification of IAV in lung"]
    assert "NOT_SUPPORTED" in row["reason"] and _REVIEW["reason"] in row["reason"]
    m = result["metrics"]
    assert (m["extra"], m["unsupported_extra"], m["ours_total"]) == (0, 1, 2)


def test_a_reviewed_entry_is_never_a_split_partner(mod, array_obi, tmp_path):
    """SDY1630: `measuring degranulation by NK cells` sits on the flow cytometry term but the judge
    did not support it as an assay. It must not become the paired row's SPLIT."""
    bench = {"flow cytometry": _entry("flow cytometry", "OBI:0000916")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay"),
            "measuring degranulation by NK cells": _ours("measuring degranulation by NK cells",
                                                         "OBI:0000916", "flow cytometry assay",
                                                         review=_REVIEW)}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert [r["status"] for r in result["rows"]] == ["MATCH", "UNSUPPORTED_EXTRA"]
    assert result["metrics"]["split"] == 0 and result["metrics"]["unsupported_extra"] == 1


def test_a_paired_reviewed_entry_keeps_its_status_and_is_flagged(mod, array_obi, tmp_path):
    bench = {"flow cytometry": _entry("flow cytometry", "OBI:0000916")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay",
                                          review=_REVIEW)}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    row = result["rows"][0]
    assert row["status"] == "MATCH" and row["reviewed"] is True
    assert row["ours"][0]["identity_review"] == _REVIEW
    assert result["metrics"]["matched"] == 1 and result["metrics"]["unsupported_extra"] == 0
    assert not any(r.get("reviewed") for r in _rows(result, "MISSED"))


# ── discovering registries ───────────────────────────────────────────────────


def _write_pair(root, study, pmid, bench, ours):
    bench_dir = root / "bench"
    bench_dir.mkdir(exist_ok=True)
    (bench_dir / f"{study}_assays_AS_v2.json").write_text(json.dumps(bench))
    registry = root / "reg" / f"{pmid}_{study}"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "assays_benchmark.json").write_text(
        json.dumps({k: {f: v for f, v in e.items() if f != "_obi"} for k, e in ours.items()}))
    (registry / "assays_OBI.json").write_text(json.dumps({k: e["_obi"] for k, e in ours.items()}))
    return bench_dir, root / "reg"


def test_discover_pairs_reads_the_given_registry_dir(mod, tmp_path):
    bench_dir, registry_dir = _write_pair(tmp_path, "SDY1", "11", {}, {})

    pairs, skipped = mod.discover_pairs(None, bench_dir, registry_dir)

    assert skipped == []
    assert [(p["study"], p["pmid"], p["registry"]) for p in pairs] == [("SDY1", "11", registry_dir / "11_SDY1")]


def test_registry_dir_flag_reaches_discovery_and_an_outside_path_is_written_absolute(mod, array_obi, tmp_path, monkeypatch, capsys):
    bench = {"flow cytometry": _entry("flow cytometry", "OBI:0000916")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay")}
    bench_dir, registry_dir = _write_pair(tmp_path, "SDY1", "11", bench, ours)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(mod, "ObiGraph", lambda: array_obi)
    monkeypatch.setattr(mod, "OUT_DIR", out_dir)
    monkeypatch.setattr(sys, "argv", ["x", "--benchmark-dir", str(bench_dir),
                                      "--registry-dir", str(registry_dir), "--out-stem", "t"])

    mod.main()

    report = json.loads((out_dir / "t.json").read_text())
    assert report["registry_dir"] == str(registry_dir.resolve())
    assert report["papers"][0]["registry_dir"] == str((registry_dir / "11_SDY1").resolve())
    assert report["papers"][0]["benchmark_file"].startswith("/")
    assert report["totals"]["matched"] == 1 and report["totals"]["registries_without_benchmark"] == []
    out = capsys.readouterr().out
    assert "precision 100.0% (v1 100.0%)" in out and f"wrote {out_dir / 't'}" in out
    assert "MERGED" not in out


# ── Overall statistics ────────────────────────────────────────────────────────

def _paper(rows, bench, ours, matched, exact, missed, extra, split=0, unsupported_extra=0):
    return {"study": "SDY1", "pmid": "1", "benchmark_file": "b.json", "registry_dir": "r",
            "repair": None, "merged_groups": [],
            "metrics": {"benchmark_total": bench, "ours_total": ours, "matched": matched,
                        "exact": exact, "missed": missed, "extra": extra, "split": split,
                        "unsupported_extra": unsupported_extra,
                        "recall": matched / bench if bench else 0.0},
            "rows": [{"status": s, "tier": None, "signals": [], "reason": "",
                      "benchmark": None, "ours": []} for s in rows]}


def test_overall_totals_count_statuses_and_rates(mod):
    papers = [_paper(["MATCH", "MATCH", "MISSED", "EXTRA"], 3, 3, 2, 2, 1, 1),
              _paper(["MATCH_GRANULARITY", "EXTRA"], 1, 2, 1, 0, 0, 1)]

    t = mod.overall_totals(papers)

    assert t["status_counts"]["MATCH"] == 2
    assert t["status_counts"]["MATCH_GRANULARITY"] == 1
    assert t["status_counts"]["MISSED"] == 1
    assert t["status_counts"]["EXTRA"] == 2
    assert t["benchmark_total"] == 4 and t["ours_total"] == 5 and t["matched"] == 3
    assert t["split"] == 0 and t["unsupported_extra"] == 0
    assert t["recall"] == pytest.approx(3 / 4)
    assert t["precision"] == t["precision_v1"] == pytest.approx(3 / 5)
    assert t["f1"] == t["f1_v1"] == pytest.approx(2 * 0.6 * 0.75 / (0.6 + 0.75))
    assert t["obi_exact_rate"] == pytest.approx(2 / 3)
    assert t["obi_recall"] == pytest.approx(2 / 4)


def test_unsupported_extras_leave_precision_but_not_precision_v1(mod):
    papers = [_paper(["MATCH", "MATCH", "SPLIT", "UNSUPPORTED_EXTRA"], 2, 4, 2, 2, 0, 0,
                     split=1, unsupported_extra=1)]

    t = mod.overall_totals(papers)

    assert t["split"] == 1 and t["unsupported_extra"] == 1
    assert t["status_counts"]["SPLIT"] == 1 and t["status_counts"]["UNSUPPORTED_EXTRA"] == 1
    assert t["matched"] == 2  # SPLIT is not a match in v2
    assert t["precision"] == pytest.approx(2 / 3)
    assert t["precision_v1"] == pytest.approx(2 / 4)
    assert t["f1"] == pytest.approx(2 * (2 / 3) * 1.0 / (2 / 3 + 1.0))
    assert t["f1_v1"] == pytest.approx(2 * 0.5 * 1.0 / 1.5)


def test_overall_totals_with_nothing_scored_are_zero_not_errors(mod):
    t = mod.overall_totals([])

    assert t["recall"] == t["precision"] == t["f1"] == t["obi_exact_rate"] == t["obi_recall"] == 0.0
    assert t["precision_v1"] == t["f1_v1"] == 0.0
    assert t["split"] == t["unsupported_extra"] == 0
    assert all(n == 0 for n in t["status_counts"].values())


def test_html_shows_total_row(mod):
    papers = [_paper(["MATCH", "MISSED", "EXTRA"], 2, 2, 1, 1, 1, 1)]
    report = {"benchmark_dir": "b", "registry_dir": "r", "papers": papers,
              "totals": {"papers": 1, "skipped": [], "registries_without_benchmark": [],
                         **mod.overall_totals(papers)}}

    page = mod.render_html(report)

    assert "Overall statistics" not in page
    assert "<tfoot><tr><td>Total</td>" in page
    assert "<span>precision</span>" not in page and "<span>F1</span>" not in page


def test_html_renders_split_and_unsupported_extra(mod):
    papers = [_paper(["MATCH", "SPLIT", "UNSUPPORTED_EXTRA"], 1, 3, 1, 1, 0, 0,
                     split=1, unsupported_extra=1)]
    report = {"benchmark_dir": "b", "registry_dir": "r", "papers": papers,
              "totals": {"papers": 1, "skipped": [], "registries_without_benchmark": [],
                         **mod.overall_totals(papers)}}

    page = mod.render_html(report)

    assert page.count("--unsupp:#") == 3  # light, dark-by-preference, dark-by-toggle
    assert ".unsupp{" in page and ".unsupp-c{" in page and ".tag.review{" in page
    assert 'value="UNSUPPORTED_EXTRA"' in page  # legend / filter
    assert 'data-status="UNSUPPORTED_EXTRA"' in page and 'data-status="SPLIT"' in page
    assert "<span>split</span>" in page and "<span>unsupported extra</span>" in page
    assert "after merge" not in page and "merged into one row" not in page and "(raw " not in page
    assert "<span>precision</span>" not in page
