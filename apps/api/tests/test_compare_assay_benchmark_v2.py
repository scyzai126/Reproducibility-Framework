"""The v2 benchmark comparison: reading hand-edited benchmark JSON, pairing, and folding same-OBI leftovers.

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


def test_missing_brace_balanced_by_a_stray_one_still_un_nests(mod, tmp_path):
    # Valid JSON: the `}` missing after "a" is made up by an extra one at the end.
    path = tmp_path / "f.json"
    path.write_text('{"a": {"name_in_paper": "a", "x": {"y": 1},\n "b": {"name_in_paper": "b"}\n}}')
    data, repair, _ = mod.load_lenient(path)
    assert list(data) == ["a", "b"]
    assert data["a"] == {"name_in_paper": "a", "x": {"y": 1}}
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


def _ours(name, obi_id, label, quote="…", aliases=()):
    return {"name_in_paper": [name], "aliases": list(aliases), "generate_claim": True,
            "source": "methods", "evidence": {"section": "Methods", "quote": quote},
            "_obi": {"obi_id": obi_id, "obi_label": label}}


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
    # The granularity pair counts toward OBI recall; the conflict pair is found but not on term.
    assert (result["metrics"]["exact"], result["metrics"]["obi_ok"]) == (0, 1)


def test_one_agent_entry_is_never_counted_under_two_benchmark_rows(mod, array_obi, tmp_path):
    bench = {"genotyping array": _entry("genotyping array", "OBI:0001274", "a"),
             "expression array": _entry("expression array", "OBI:0001985", "b")}
    ours = {"genotyping by SNP array assay": _ours("SNP chip", "OBI:0002031",
                                                   "genotyping by SNP array assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    claimed = [o["key"] for r in result["rows"] if r["benchmark"] for o in r["ours"]]
    assert claimed == ["genotyping by SNP array assay"]
    assert result["metrics"]["missed"] == 1


def test_two_agent_entries_on_one_benchmark_term_are_a_split(mod, array_obi, tmp_path):
    bench = {"flow cytometry": _entry("flow cytometry", "OBI:0000916")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay"),
            "flow cytometry assay (2)": _ours("FACS staining", "OBI:0000916",
                                              "flow cytometry assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    # The one-to-one pair keeps its own status; the second entry rides along as an annotation.
    [row] = result["rows"]
    assert row["status"] == "MATCH"
    assert [o["key"] for o in row["ours"]] == ["flow cytometry assay", "flow cytometry assay (2)"]
    assert row["also_on_term"] == ["flow cytometry assay (2)"]
    assert result["metrics"]["exact"] == 1 and result["metrics"]["split"] == 1
    assert result["metrics"]["extra"] == 0


def test_two_curated_rows_on_one_term_pair_one_to_one_by_name(mod, array_obi, tmp_path):
    """SDY1640 / SDY1655: the curator lists flow cytometry and ICS, both on `flow cytometry
    assay`; round 5 kept the agent's two apart on that term. Name decides, both MATCH, no split."""
    bench = {"flow cytometry": _entry("flow cytometry", "OBI:0000916"),
             "intracellular cytokine staining": _entry("intracellular cytokine staining", "OBI:0000916")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay"),
            "flow cytometry assay (2)": _ours("intracellular cytokine staining", "OBI:0000916",
                                              "flow cytometry assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert _pairs(result) == {"flow cytometry": ("MATCH", ["flow cytometry assay"]),
                              "intracellular cytokine staining": ("MATCH", ["flow cytometry assay (2)"])}
    assert result["metrics"]["split"] == 0 and result["metrics"]["exact"] == 2


def test_registry_dir_can_be_pointed_at_another_result_version(mod, tmp_path):
    other = tmp_path / "assay_result_v3"
    (other / "32473127_SDY1640").mkdir(parents=True)
    (other / "32473127_SDY1640" / "assays_benchmark.json").write_text("{}")
    bench_dir = tmp_path / "bench"
    bench_dir.mkdir()
    (bench_dir / "SDY1640_assays.json").write_text("{}")

    mod.use_registry_dir(other)
    pairs, skipped = mod.discover_pairs(None, bench_dir)

    assert mod.OUT_DIR == other.resolve() / "comparison"
    assert [p["registry"].name for p in pairs] == ["32473127_SDY1640"] and skipped == []


def test_the_default_benchmark_is_the_current_curated_version(mod):
    assert mod.BENCHMARK_DIR.name == "benchmark_assay_v5"


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


def test_unpaired_panels_on_the_paired_term_fold_into_one_row(mod, array_obi, tmp_path):
    """SDY1289: four curated flow panels against the agent's one flow cytometry entry."""
    bench = {name: _entry(name, "OBI:0000916", f"{name} quote")
             for name in ("flow cytometry", "ICS panel", "Ki67 panel", "Th1/Th2 panel")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert [r["status"] for r in result["rows"]] == ["MATCH"]
    row = result["rows"][0]["benchmark"]
    assert row["merged_from"] == ["flow cytometry", "ICS panel", "Ki67 panel", "Th1/Th2 panel"]
    assert [q["from"] for q in row["quotes"]] == row["merged_from"]
    assert result["metrics"]["benchmark_total"] == 1
    assert result["merged_groups"] == [row["merged_from"]]


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


def test_a_leftover_folds_even_when_its_sibling_paired_on_another_term(mod, array_obi, tmp_path):
    """SDY1289: two curated `microarray assay` rows against the agent's one transcription-profiling
    entry are one assay with a term disagreement, not a conflict plus a miss."""
    bench = {"gene array": _entry("gene array", "OBI:0001985"),
             "microarray analysis": _entry("microarray analysis", "OBI:0001985")}
    ours = {"transcription profiling by array assay": _ours(
        "gene array", "OBI:0001463", "transcription profiling by array assay")}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert [r["status"] for r in result["rows"]] == ["MATCH_OBI_CONFLICT"]
    assert result["rows"][0]["benchmark"]["merged_from"] == ["gene array", "microarray analysis"]


def test_unmapped_leftovers_never_fold(mod, array_obi, tmp_path):
    bench = {"SBA": _entry("SBA"), "SBA titre": _entry("SBA titre")}
    ours = {"SBA": _ours("SBA", None, None)}

    result = _compare(mod, array_obi, tmp_path, bench, ours)

    assert sorted(r["status"] for r in result["rows"]) == ["MATCH_OBI_UNMAPPED", "MISSED"]


# ── Overall statistics ────────────────────────────────────────────────────────

def _paper(rows, bench, ours, matched, exact, missed, extra, obi_ok=None):
    return {"study": "SDY1", "pmid": "1", "benchmark_file": "b.json", "registry_dir": "r",
            "repair": None, "benchmark_raw_total": bench, "merged_groups": [],
            "metrics": {"benchmark_total": bench, "ours_total": ours, "matched": matched,
                        "exact": exact, "missed": missed, "extra": extra,
                        "obi_ok": exact if obi_ok is None else obi_ok,
                        "recall": matched / bench if bench else 0.0},
            "rows": [{"status": s, "tier": None, "signals": [], "reason": "",
                      "benchmark": None, "ours": []} for s in rows]}


def test_overall_totals_count_statuses_and_rates(mod):
    papers = [_paper(["MATCH", "MATCH", "MISSED", "EXTRA"], 3, 3, 2, 2, 1, 1),
              _paper(["MATCH_GRANULARITY", "EXTRA"], 1, 2, 1, 0, 0, 1, obi_ok=1)]

    t = mod.overall_totals(papers)

    assert t["status_counts"]["MATCH"] == 2
    assert t["status_counts"]["MATCH_GRANULARITY"] == 1
    assert t["status_counts"]["MISSED"] == 1
    assert t["status_counts"]["EXTRA"] == 2
    assert t["benchmark_total"] == 4 and t["ours_total"] == 5 and t["matched"] == 3
    assert t["recall"] == pytest.approx(3 / 4)
    assert t["precision"] == pytest.approx(3 / 5)
    assert t["f1"] == pytest.approx(2 * 0.6 * 0.75 / (0.6 + 0.75))
    assert t["obi_exact_rate"] == pytest.approx(2 / 3)
    # A parent/child pairing counts as an OBI recall; only a name-made pairing does not.
    assert t["obi_recall"] == pytest.approx(3 / 4)


def test_overall_totals_with_nothing_scored_are_zero_not_errors(mod):
    t = mod.overall_totals([])

    assert t["recall"] == t["precision"] == t["f1"] == t["obi_exact_rate"] == t["obi_recall"] == 0.0
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


def test_html_spells_out_how_both_recalls_are_computed(mod):
    """The two tiles share a denominator, so the page has to say which statuses each admits."""
    papers = [_paper(["MATCH", "MATCH_GRANULARITY", "MATCH_OBI_CONFLICT", "MISSED"],
                     4, 4, 3, 1, 1, 0, obi_ok=2)]
    report = {"benchmark_dir": "b", "registry_dir": "r", "papers": papers,
              "totals": {"papers": 1, "skipped": [], "registries_without_benchmark": [],
                         **mod.overall_totals(papers)}}

    page = mod.render_html(report)

    assert '<div class="rates">' in page
    # recall: every matched tier over the benchmark rows.
    assert "<code>3 / 4</code>" in page
    assert "MATCH OBI CONFLICT (1)" in page
    # OBI recall: MATCH + MATCH GRANULARITY only, and the gap to recall named.
    assert "<code>(1 + 1) / 4</code>" in page and "<code>2 / 4</code>" in page
    assert "that gap is the 1 row " in page  # singular, not "1 rows"


# ── strict mode ───────────────────────────────────────────────────────────────

def test_strict_mode_never_folds_a_leftover(mod, array_obi, tmp_path):
    """The four flow panels again: strict scores them as the four rows the curator wrote."""
    bench = {name: _entry(name, "OBI:0000916", f"{name} quote")
             for name in ("flow cytometry", "ICS panel", "Ki67 panel", "Th1/Th2 panel")}
    ours = {"flow cytometry assay": _ours("flow cytometry", "OBI:0000916", "flow cytometry assay")}

    lenient = _compare(mod, array_obi, tmp_path, bench, ours)
    registry = tmp_path / "registry"
    strict = mod.compare_paper(mod.prepare_benchmark(bench, array_obi), registry, array_obi, strict=True)

    assert lenient["metrics"]["benchmark_total"] == 1 and lenient["metrics"]["missed"] == 0
    assert strict["metrics"]["benchmark_total"] == 4 and strict["metrics"]["missed"] == 3
    assert sorted(r["status"] for r in strict["rows"]) == ["MATCH", "MISSED", "MISSED", "MISSED"]
    assert strict["merged_groups"] == []


def test_strict_mode_takes_a_term_only_pair_after_every_pair_the_names_made(mod, array_obi, tmp_path):
    """Two curated rows on `flow cytometry assay`. The agent's flow entry shares no name with
    either; its ICS entry, on a term OBI does not know, contains the curator's "ICS panel".
    Default hands the ICS row to the flow entry on the shared term first and folds the real flow
    row into it, leaving the ICS entry EXTRA. Strict takes the containment pair first."""
    bench = {"ICS panel": _entry("ICS panel", "OBI:0000916", "ICS panel quote"),
             "flow cytometry": _entry("flow cytometry", "OBI:0000916", "flow quote")}
    ours = {"flow cytometry assay": _ours("FACS", "OBI:0000916", "flow cytometry assay"),
            "ICS staining": _ours("ICS panel staining", "OBI:0009999", "ICS staining")}

    lenient = _compare(mod, array_obi, tmp_path, bench, ours)
    registry = tmp_path / "registry"
    strict = mod.compare_paper(mod.prepare_benchmark(bench, array_obi), registry, array_obi, strict=True)

    # Default: the term-only pair is taken first, and the real flow row then folds into it as a
    # leftover on the same term, so the mistake is invisible.
    assert _pairs(lenient) == {"ICS panel": ("MATCH", ["flow cytometry assay"]),
                               None: ("EXTRA", ["ICS staining"])}
    assert lenient["merged_groups"] == [["ICS panel", "flow cytometry"]]
    assert _pairs(strict) == {"ICS panel": ("MATCH_OBI_CONFLICT", ["ICS staining"]),
                              "flow cytometry": ("MATCH", ["flow cytometry assay"])}
    # The pair the ontology alone made is counted, and the row says so.
    assert lenient["metrics"]["term_only_pairs"] == strict["metrics"]["term_only_pairs"] == 1
    flow_row = next(r for r in strict["rows"] if r["benchmark"] and r["benchmark"]["key"] == "flow cytometry")
    assert "term-only pair" in flow_row["reason"]


def test_a_shared_sentence_alone_does_not_outrank_a_term_only_pair_in_strict_mode(mod, array_obi, tmp_path):
    """A Methods sentence names several assays, so a shared sentence is not a name signal: the
    curated flow row still goes to the agent's flow entry on the term, not to the array entry
    quoted from the same sentence."""
    sentence = "PBMCs were analysed by flow cytometry and gene expression was measured on arrays in parallel."
    bench = {"flow cytometry": _entry("flow cytometry", "OBI:0000916", sentence)}
    ours = {"flow cytometry assay": _ours("FACS", "OBI:0000916", "flow cytometry assay", quote="elsewhere"),
            "transcription profiling by array assay": _ours(
                "expression arrays", "OBI:0001463", "transcription profiling by array assay", quote=sentence)}

    registry = tmp_path / "registry"
    _compare(mod, array_obi, tmp_path, bench, ours)
    strict = mod.compare_paper(mod.prepare_benchmark(bench, array_obi), registry, array_obi, strict=True)

    assert _pairs(strict)["flow cytometry"] == ("MATCH", ["flow cytometry assay"])


def test_overall_totals_sum_term_only_pairs_and_tolerate_old_reports(mod):
    old = _paper(["MATCH"], 1, 1, 1, 1, 0, 0)
    new = _paper(["MATCH", "MATCH"], 2, 2, 2, 2, 0, 0)
    new["metrics"]["term_only_pairs"] = 2

    assert mod.overall_totals([old, new])["term_only_pairs"] == 2


def test_html_names_the_scoring_mode(mod):
    papers = [_paper(["MATCH", "MISSED"], 2, 1, 1, 1, 1, 0)]
    totals = {"papers": 1, "skipped": [], "registries_without_benchmark": [], **mod.overall_totals(papers)}

    lenient = mod.render_html({"mode": "default", "benchmark_dir": "b", "registry_dir": "r",
                               "papers": papers, "totals": totals})
    strict = mod.render_html({"mode": "strict", "benchmark_dir": "b", "registry_dir": "r",
                              "papers": papers, "totals": totals})

    assert "— strict" not in lenient and "folds into a paired row" in lenient
    assert "— strict" in strict and "Strict mode: both denominators are the 2 rows" in strict


# ── the comparison-arms section ──────────────────────────────────────────────

_ARMS_TABLE = """# Comparison arms vs the assay agent

## Scorer mode: default

| metric | agent | RAG single call ×3 |
|---|---|---|
| entries | 999 | 1 |
| exact (same OBI term as curator) | 999 | 1 |

## Scorer mode: strict

| metric | agent | bare LLM ×3 (strict ids) | bare LLM ×3 (labels read) | RAG single call ×3 | OntoGPT | NCBO Annotator, pruned/paper | NCBO Annotator, pruned/methods | dictionary, pruned/paper | dictionary, pruned/methods | dictionary, full/paper | agent, old same-term fold |
|---|---|---|---|---|---|---|---|---|---|---|---|
| entries | 176 | 249 | 249 | 227 | 263 | 94 | 79 | 484 | 349 | 494 | 155 |
| matched | 156 | 154 | 155 | 157 | 155 | 60 | 48 | 141 | 124 | 141 | 151 |
| exact (same OBI term as curator) | 144 | 13 | 75 | 120 | 22 | 47 | 37 | 79 | 63 | 79 | 136 |
| F1 | 93.4% | 75.5% | 76.1% | 81.5% | 73.6% | 47.6% | 40.5% | 43.9% | 48.9% | 43.3% | 96.5% |
| calls | 532 | 31 | 31 | 31 | 31 | 0 | 0 | 0 | 0 | 0 | 512 |
"""


def test_parse_arms_table_reads_the_mode_asked_for(mod):
    strict = mod.parse_arms_table(_ARMS_TABLE, "strict")
    default = mod.parse_arms_table(_ARMS_TABLE, "default")

    assert strict["entries"]["agent"] == "176"
    assert strict["exact (same OBI term as curator)"]["RAG single call ×3"] == "120"
    # The default section must not bleed into the strict one, or the page shows the wrong mode.
    assert default["entries"]["agent"] == "999"
    assert mod.parse_arms_table(_ARMS_TABLE, "nonexistent") == {}


def test_baselines_html_renders_the_arms_and_explains_each(mod, tmp_path):
    path = tmp_path / "arms_table.md"
    path.write_text(_ARMS_TABLE, encoding="utf-8")

    html = mod.baselines_html({"exact": 144}, path=path, mode="strict")

    assert "Against other tools" in html
    assert "RAG single call" in html and "OntoGPT" in html and "NCBO Annotator" in html
    # The explanation of each arm is the point of the section, not decoration.
    assert "pasted into the context" in html          # what RAG single call is
    assert "no vocabulary in the prompt" in html.replace("\n", " ")
    assert ">144<" in html and ">120<" in html
    # The Methods-only and full-vocabulary variants are deliberately not shown.
    assert "pruned/methods" not in html and "full/paper" not in html
    assert "No stale warning expected" or True
    assert "Rebuild it with" not in html


def test_baselines_html_flags_a_stale_arms_table(mod, tmp_path):
    """The agent column is built from this same report; if it disagrees, it is out of date."""
    path = tmp_path / "arms_table.md"
    path.write_text(_ARMS_TABLE, encoding="utf-8")

    html = mod.baselines_html({"exact": 140}, path=path, mode="strict")

    assert "Rebuild it with" in html and "reads 144 exact where this run scored 140" in html


def test_baselines_html_is_omitted_when_the_scores_are_absent(mod, tmp_path):
    assert mod.baselines_html({"exact": 1}, path=tmp_path / "missing.md") == ""


def test_baselines_html_follows_the_page_mode(mod, tmp_path):
    """Arms scored the way the rows above them were: a default page must not show strict."""
    path = tmp_path / "arms_table.md"
    path.write_text(_ARMS_TABLE, encoding="utf-8")

    default = mod.baselines_html({"exact": 999}, path=path, mode="default")
    strict = mod.baselines_html({"exact": 144}, path=path, mode="strict")

    assert "default scorer" in default and ">999<" in default
    assert "strict scorer" in strict and ">144<" in strict
    assert "Rebuild it with" not in default and "Rebuild it with" not in strict


def test_html_embeds_the_arms_section(mod, tmp_path, monkeypatch):
    path = tmp_path / "arms_table.md"
    path.write_text(_ARMS_TABLE, encoding="utf-8")
    monkeypatch.setattr(mod, "BASELINES_PATH", path)
    papers = [_paper(["MATCH", "MISSED"], 2, 1, 1, 1, 1, 0)]
    totals = {"papers": 1, "skipped": [], "registries_without_benchmark": [], **mod.overall_totals(papers)}

    page = mod.render_html({"mode": "strict", "benchmark_dir": "b", "registry_dir": "r",
                            "papers": papers, "totals": totals})

    assert "Against other tools" in page and "What each arm is" in page
