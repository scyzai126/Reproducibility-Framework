"""The v2 benchmark comparison: reading hand-edited benchmark JSON and merging same-OBI rows.

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


def test_entries_sharing_an_obi_id_merge_under_its_label(mod, obi):
    bench = {
        "ICS": _entry("ICS", "OBI:0000916", "quote one"),
        "ELISA": _entry("ELISA", "OBI:0000661"),
        "Ki67 flow": _entry("Ki67 flow", "OBI:0000916", "quote two"),
    }
    merged = mod.merge_by_obi(bench, obi)
    assert list(merged) == ["flow cytometry assay", "ELISA"]
    flow = merged["flow cytometry assay"]
    assert flow["merged_from"] == ["ICS", "Ki67 flow"]
    assert flow["name_in_paper"] == ["ICS", "Ki67 flow"]
    assert [q["quote"] for q in flow["quotes"]] == ["quote one", "quote two"]
    assert "quote one" in flow["evidence_location"]["quote"] and "quote two" in flow["evidence_location"]["quote"]


def test_entries_without_an_obi_id_are_never_merged(mod, obi):
    bench = {"SBA": _entry("SBA"), "CFU": _entry("CFU")}
    merged = mod.merge_by_obi(bench, obi)
    assert list(merged) == ["SBA", "CFU"]
    assert all(v["obi_id"] is None for v in merged.values())
