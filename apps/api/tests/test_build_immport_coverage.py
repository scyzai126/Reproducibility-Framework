"""scripts/build_immport_coverage.py stores the Corpus tab's "In ImmPort" column.

It is free unless asked: SQL only by default, the model fallback only with `--llm`, and
`--llm --dry-run` prints the bill -- cached versus new rows -- without calling or writing anything.
No test here opens a database or reaches a model; `sweep` is replaced.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

_ROWS = [{"study": "19029902_SDY1264", "assay": "Neut Ab"},
         {"study": "19029902_SDY1264", "assay": "Mass spec"}]


def _report(statuses):
    rows = [{"study": r["study"], "study_accession": "SDY1264", "assay": r["assay"], "status": s}
            for r, s in zip(_ROWS, statuses)]
    return {"rows": rows, "stats": {"total": len(rows), "matched": statuses.count("matched"),
                                    "absent": statuses.count("absent"), "no_experiments": 0,
                                    "studies_without_experiments": []}}


@pytest.fixture
def script(tmp_path, monkeypatch):
    """The script, pointed at a tmp registry root holding a two-row table, with a fake sweep."""
    path = _REPO_ROOT / "scripts" / "build_immport_coverage.py"
    spec = importlib.util.spec_from_file_location("build_immport_coverage", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "REGISTRY_ROOT", tmp_path)
    (tmp_path / module.TABLE_NAME).write_text(json.dumps(_ROWS), encoding="utf-8")

    module.sweeps = []

    async def fake_sweep(rows, use_llm):
        module.sweeps.append(use_llm)
        return _report(["matched", "absent"])

    monkeypatch.setattr(module, "sweep", fake_sweep)
    return module


def _run(module, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["build_immport_coverage.py", *argv])
    return module.main()


def test_the_default_run_is_sql_only_and_stores_the_report(script, monkeypatch, tmp_path):
    assert _run(script, monkeypatch) == 0

    assert script.sweeps == [False]
    stored = json.loads((tmp_path / script.COVERAGE_NAME).read_text(encoding="utf-8"))
    assert stored["llm"] is False
    assert stored["generated_at"]
    assert [r["status"] for r in stored["rows"]] == ["matched", "absent"]
    assert stored["stats"]["matched"] == 1


def test_llm_is_used_only_when_asked(script, monkeypatch, tmp_path):
    _run(script, monkeypatch, "--llm")

    assert script.sweeps == [True]
    assert json.loads((tmp_path / script.COVERAGE_NAME).read_text(encoding="utf-8"))["llm"] is True


def test_a_dry_run_sweeps_sql_only_and_writes_nothing(script, monkeypatch, tmp_path):
    _run(script, monkeypatch, "--llm", "--dry-run")

    assert script.sweeps == [False]
    assert not (tmp_path / script.COVERAGE_NAME).exists()


def test_the_bill_splits_absent_rows_into_cached_and_new(script):
    report = _report(["absent", "absent"])
    cache = {"SDY1264::Neut Ab": {"experiment_accession": None}}

    assert script.llm_bill(report, cache) == (1, 1)


def test_a_missing_table_is_reported_not_swept(script, monkeypatch, tmp_path):
    (tmp_path / script.TABLE_NAME).unlink()

    assert _run(script, monkeypatch) == 1
    assert script.sweeps == []
