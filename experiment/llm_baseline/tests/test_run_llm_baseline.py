"""Offline tests for experiment/llm_baseline/run_llm_baseline.py. No API call."""

import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

OBO = """format-version: 1.2

[Term]
id: OBI:0000070
name: assay

[Term]
id: OBI:0000661
name: enzyme-linked immunosorbent assay
synonym: "ELISA" EXACT []
is_a: OBI:0000070 ! assay

[Term]
id: OBI:0000916
name: flow cytometry assay
is_a: OBI:0000070 ! assay

[Term]
id: OBI:0000999
name: obsolete old assay
is_obsolete: true
"""


@pytest.fixture(scope="module")
def mod():
    script = HERE.parent / "run_llm_baseline.py"
    spec = importlib.util.spec_from_file_location("run_llm_baseline", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ids(mod, tmp_path):
    obo = tmp_path / "tiny.obo"
    obo.write_text(OBO, encoding="utf-8")
    return mod.ObiIds(obo)


# ── id checking ──────────────────────────────────────────────────────────────

def test_id_status(ids):
    assert ids.status("OBI:0000661", "enzyme-linked immunosorbent assay") == "valid"
    assert ids.status("OBI:0000661", "ELISA") == "valid"  # a synonym is not a mismatch
    assert ids.status("OBI:0000916", "Flow cytometry") == "valid"  # nor a dropped "assay"
    assert ids.status("OBI:0000661", "flow cytometry assay") == "label_mismatch"
    assert ids.status("OBI:0000999", "old assay") == "obsolete"
    assert ids.status("OBI:1234567", "made-up assay") == "nonexistent"
    assert ids.status(None, "ELISA") == "none"


def test_canonical_id(mod):
    assert mod.ObiIds.canonical("OBI_0000661") == "OBI:0000661"
    assert mod.ObiIds.canonical(" obi:0000661 ") == "OBI:0000661"
    assert mod.ObiIds.canonical("ELISA") is None
    assert mod.ObiIds.canonical(None) is None


# ── reply -> registry ────────────────────────────────────────────────────────

def test_parse_reply(mod):
    assert mod.parse_reply('```json\n{"assays": [{"name_in_paper": "ELISA"}, 3]}\n```') == [
        {"name_in_paper": "ELISA"}]
    assert mod.parse_reply('[{"name_in_paper": "ELISA"}]') == [{"name_in_paper": "ELISA"}]
    assert mod.parse_reply("I could not find any assays.") is None


def test_to_registry_keys_and_statuses(mod, ids):
    bench, obi = mod.to_registry([
        {"name_in_paper": "ELISA", "quote": "Sera were tested by ELISA.",
         "obi_id": "OBI:0000661", "obi_label": "ELISA"},
        {"name_in_paper": "anti-spike ELISA", "obi_id": "OBI_0000661",
         "obi_label": "enzyme-linked immunosorbent assay"},
        {"name_in_paper": "FACS", "obi_id": "OBI:0000661", "obi_label": "flow cytometry assay"},
        {"name_in_paper": "Luminex", "obi_id": "OBI:7777777", "obi_label": "bead assay"},
        {"name_in_paper": "Western blot"},
    ], ids)
    assert list(bench) == ["enzyme-linked immunosorbent assay", "enzyme-linked immunosorbent assay (2)",
                           "enzyme-linked immunosorbent assay (3)", "bead assay", "Western blot"]
    assert bench["enzyme-linked immunosorbent assay"]["evidence"]["quote"] == "Sera were tested by ELISA."
    assert bench["Western blot"]["evidence"]["quote"] == ""
    assert bench["Western blot"]["name_in_paper"] == ["Western blot"]

    statuses = [e["id_status"] for e in obi.values()]
    assert statuses == ["valid", "valid", "label_mismatch", "nonexistent", "none"]
    # A label mismatch keeps the id and takes the OBO label; a made-up id is scored unmapped.
    assert obi["enzyme-linked immunosorbent assay (3)"]["obi_label"] == "enzyme-linked immunosorbent assay"
    assert obi["enzyme-linked immunosorbent assay (3)"]["claimed_label"] == "flow cytometry assay"
    assert obi["bead assay"]["obi_id"] is None
    assert obi["bead assay"]["claimed_id"] == "OBI:7777777"


# ── report ───────────────────────────────────────────────────────────────────

def _report(registry_dir, rows):
    return {"papers": [{"study": "SDY1", "registry_dir": str(registry_dir), "rows": rows}]}


def _row(status, key, ours=()):
    return {"status": status, "benchmark": {"key": key, "obi_id": "OBI:0000661",
                                            "obi_label": "enzyme-linked immunosorbent assay"},
            "ours": [{"key": k, "obi_id": None, "obi_label": None} for k in ours]}


def test_compare_reasons_and_stability(mod, tmp_path):
    runs = tmp_path / "runs"
    for n in ("r1", "r2", "r3"):
        mod._write(runs / n / "1_SDY1" / "assays_OBI.json",
                   {"bead assay": {"obi_id": None, "id_status": "nonexistent"}})
    agent = _report("x/1_SDY1", [_row("MATCH", "ELISA"), _row("MATCH", "Luminex"),
                                 _row("MISSED", "PCR"), _row("MATCH", "FACS")])
    base = _report("x/1_SDY1", [_row("MISSED", "ELISA"),
                                _row("MATCH_OBI_UNMAPPED", "Luminex", ["bead assay"]),
                                _row("MATCH", "PCR"), _row("MATCH", "FACS")])
    flaky = _report("x/1_SDY1", [_row("MISSED", "ELISA"),
                                 _row("MATCH_OBI_UNMAPPED", "Luminex", ["bead assay"]),
                                 _row("MATCH", "PCR"), _row("MATCH_OBI_CONFLICT", "FACS")])
    diff = mod.compare({"agent": agent, "r1": base, "r2": base, "r3": flaky}, runs)
    by_key = {r["curated"]: r for r in diff["rows"]}
    assert by_key["ELISA"]["reason"] == "baseline_missed"
    assert by_key["Luminex"]["reason"] == "baseline_fake_id"
    assert by_key["PCR"]["reason"] == "agent_worse"
    assert by_key["FACS"]["reason"] is None  # 2 of 3 runs match, so the majority agrees
    assert diff["same_status_all_runs"] == 3


def test_summary_table_mean_and_range(mod):
    cols = {"agent": {"exact": 140, "obi_recall": 0.9},
            "r1": {"exact": 100, "obi_recall": 0.6}, "r2": {"exact": 110, "obi_recall": 0.7}}
    table = mod.summary_table(cols)
    assert "| exact | 140 | 100 | 110 | 105.0 (100-110) |" in table
    assert "| obi_recall | 90.0% | 60.0% | 70.0% | 65.0% (60.0%-70.0%) |" in table


def test_majority_tie_goes_to_first_run(mod):
    assert mod.majority(["MATCH", "MISSED"]) == "MATCH"
    assert mod.majority(["MISSED", "MATCH", "MATCH"]) == "MATCH"
