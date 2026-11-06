"""The corpus assay runner: papers in parallel, results on the drive, nothing lost to a neighbour.

Every test stubs `assay_report`. What the runner decides -- where a paper's files go, how many
papers are in flight, what a failure or a timeout does to the rest, what the run record and the
logs hold -- does not depend on what the pipeline answers.
"""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from app.agent import assay_ledger, assay_service, immport_corpus

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_runner():
    path = _REPO_ROOT / "scripts" / "run_immport_assays.py"
    spec = importlib.util.spec_from_file_location("run_immport_assays", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


@pytest.fixture
def drive(tmp_path, monkeypatch, runner):
    """papers_xml.csv with three papers, their XML, an empty result folder, and the pipeline's
    original roots left pointing at a decoy so an overwrite would be visible."""
    papers = tmp_path / "HIPC papers"
    (papers / "xml").mkdir(parents=True)
    rows = []
    for pmid, studies in (("111", ["SDY1"]), ("222", ["SDY2"]), ("333", ["SDY3", "SDY30"])):
        (papers / "xml" / f"{studies[0]}_{pmid}.xml").write_text("<article/>")
        rows.append({"pmid": pmid, "study_accessions": ";".join(studies),
                     "primary_sdy": studies[0], "pmcid": f"PMC{pmid}",
                     "file": f"{studies[0]}_{pmid}.xml", "bytes": 10})
    immport_corpus.write_csv(papers / immport_corpus.PAPERS_XML_NAME, rows,
                             immport_corpus.XML_COLUMNS)
    result = tmp_path / "HIPC result"
    result.mkdir()
    decoy = tmp_path / "decoy_registry_root"
    decoy.mkdir()
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", decoy)
    monkeypatch.setattr(assay_service, "CACHE_ROOT", decoy)
    monkeypatch.setattr(runner, "CORPUS_ROOT", tmp_path / "31paper_assays")
    monkeypatch.setattr(runner, "AsyncOpenAI", lambda **kwargs: object())
    return papers, result, decoy


def _fake_report(calls, *, fails=(), sleep=0.0, in_flight=None, ledger=None):
    """An assay_report that writes the files a real one would, where registry_dir says."""
    async def _run(pmid, sdy, client, verify=True, correct=True):
        calls.append(pmid)
        if in_flight is not None:
            in_flight["now"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["now"])
        try:
            await asyncio.sleep(sleep)
            if pmid in fails:
                raise RuntimeError("boom")
            out_dir = assay_service.registry_dir(pmid, sdy)
            out_dir.mkdir(parents=True, exist_ok=True)
            for name in ("assays.json", "assays_OBI.json", "assays_benchmark.json"):
                (out_dir / name).write_text("{}\n")
            if ledger is not None:
                assay_ledger.append_row({"date": "2099-01-01T00:00:00", "pubmed_id": pmid,
                                         "study_accession": sdy, "registry_dir": str(out_dir),
                                         "rounds": "x", "model": "m", "calls": 25,
                                         "prompt_tokens": 1, "cached_tokens": 0,
                                         "completion_tokens": 1, "reasoning_tokens": 0,
                                         "usd": ledger, "price_date": "2026-11-04"})
            return {"paper_source": f"{sdy}_{pmid}.xml", "paper_source_kind": "xml",
                    "paper_title": "T", "rounds": {}, "assays": {},
                    "meta": {"llm_calls": 25}}
        finally:
            if in_flight is not None:
                in_flight["now"] -= 1
    return _run


def _fake_report_result(result):
    print(f"{result['paper_source']} [xml]: 'T'")
    print("  REVIEW  not folded: flow cytometry (2)")
    print("  VOTE  2 of 3: qPCR")


def _main(runner, papers, result, *argv):
    return runner.main(["run", "--papers-dir", str(papers), "--result-dir", str(result), *argv])


def _runs(result):
    return {r["pmid"]: r for r in immport_corpus.read_csv(result / immport_corpus.RUNS_NAME)}


# ── the deliverable ───────────────────────────────────────────────────────────

def test_results_land_on_the_drive_and_never_in_the_pipelines_own_roots(drive, runner, monkeypatch):
    papers, result, decoy = drive
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(seen))
    monkeypatch.setattr(runner, "report_result", _fake_report_result)

    assert _main(runner, papers, result, "--parallel", "2") == 0

    assert sorted(seen) == ["111", "222", "333"]
    for name in ("111_SDY1", "222_SDY2", "333_SDY3"):
        assert (result / name / "assays_benchmark.json").exists()
    assert list(decoy.iterdir()) == []
    runs = _runs(result)
    assert runs["111"]["status"] == "done"
    assert runs["111"]["calls"] == "25"
    assert runs["111"]["flags"] == "REVIEW=1;VOTE=1"
    assert "REVIEW  not folded" in (result / "logs" / "111.log").read_text()
    assert list((result / "logs").glob("tranche_*.txt"))


def test_parallel_bounds_the_papers_in_flight(drive, runner, monkeypatch):
    papers, result, _ = drive
    in_flight = {"now": 0, "max": 0}
    monkeypatch.setattr(runner, "assay_report",
                        _fake_report([], sleep=0.05, in_flight=in_flight))
    monkeypatch.setattr(runner, "report_result", _fake_report_result)

    assert _main(runner, papers, result, "--parallel", "2") == 0
    assert in_flight["max"] == 2

    in_flight = {"now": 0, "max": 0}
    monkeypatch.setattr(runner, "assay_report",
                        _fake_report([], sleep=0.05, in_flight=in_flight))
    assert _main(runner, papers, result, "--parallel", "1", "--force") == 0
    assert in_flight["max"] == 1


# ── failures ──────────────────────────────────────────────────────────────────

def test_a_failed_paper_is_recorded_and_the_others_finish(drive, runner, monkeypatch, capsys):
    papers, result, _ = drive
    monkeypatch.setattr(runner, "assay_report", _fake_report([], fails=("222",)))
    monkeypatch.setattr(runner, "report_result", _fake_report_result)

    assert _main(runner, papers, result) == 0

    runs = _runs(result)
    assert runs["222"]["status"] == "failed"
    assert runs["222"]["error"] == "RuntimeError: boom"
    assert runs["111"]["status"] == runs["333"]["status"] == "done"
    assert not (result / "222_SDY2" / "assays_benchmark.json").exists()
    assert "FAILED  222: RuntimeError: boom" in capsys.readouterr().out


def test_a_paper_past_the_timeout_is_failed(drive, runner, monkeypatch):
    papers, result, _ = drive
    monkeypatch.setattr(runner, "assay_report", _fake_report([], sleep=0.5))
    monkeypatch.setattr(runner, "report_result", _fake_report_result)

    assert _main(runner, papers, result, "--paper-timeout", "0.05", "--only", "111") == 0
    assert _runs(result)["111"]["status"] == "failed"
    assert "Timeout" in _runs(result)["111"]["error"]


# ── the queue ─────────────────────────────────────────────────────────────────

def test_done_papers_are_skipped_unless_forced_and_limit_takes_the_first(drive, runner, monkeypatch):
    papers, result, _ = drive
    (result / "111_SDY1").mkdir()
    (result / "111_SDY1" / "assays_benchmark.json").write_text("{}")
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(seen))
    monkeypatch.setattr(runner, "report_result", _fake_report_result)

    assert _main(runner, papers, result, "--limit", "1") == 0
    assert seen == ["222"]

    seen.clear()
    assert _main(runner, papers, result, "--force", "--only", "111") == 0
    assert seen == ["111"]


def test_a_paper_with_no_assays_is_finished_without_a_marker(drive, runner, monkeypatch, capsys):
    """Round 1 finding nothing writes no assays_benchmark.json; the run record says done."""
    papers, result, _ = drive

    async def _nothing_found(pmid, sdy, client, verify=True, correct=True):
        out_dir = assay_service.registry_dir(pmid, sdy)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "assays.json").write_text("{}\n")  # no benchmark file
        return {"paper_source": f"{sdy}_{pmid}.xml", "paper_source_kind": "xml",
                "paper_title": "T", "rounds": {}, "assays": {}, "meta": {"llm_calls": 3}}

    monkeypatch.setattr(runner, "assay_report", _nothing_found)
    monkeypatch.setattr(runner, "report_result", _fake_report_result)
    assert _main(runner, papers, result, "--only", "111") == 0
    assert _runs(result)["111"]["status"] == "done"

    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(seen))
    assert _main(runner, papers, result) == 0
    assert "111" not in seen  # recorded done: not re-run
    assert sorted(seen) == ["222", "333"]
    runner.main(["status", "--papers-dir", str(papers), "--result-dir", str(result)])
    assert "finished        : 3" in capsys.readouterr().out


def test_a_benchmark_registry_is_copied_not_run(drive, runner, monkeypatch, capsys):
    papers, result, _ = drive
    bench = runner.CORPUS_ROOT / "assay_result_v3" / "333_SDY30"  # filed under the other study
    bench.mkdir(parents=True)
    (bench / "assays_benchmark.json").write_text(json.dumps({"ELISA": {}}))
    (bench / "assays.json").write_text("{}")
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(seen))
    monkeypatch.setattr(runner, "report_result", _fake_report_result)

    assert _main(runner, papers, result) == 0
    assert "333" not in seen
    assert json.loads((result / "333_SDY3" / "assays_benchmark.json").read_text()) == {"ELISA": {}}
    assert _runs(result)["333"]["status"] == "reused"
    assert "REUSED  333" in capsys.readouterr().out

    seen.clear()
    assert _main(runner, papers, result, "--no-reuse-benchmark", "--force", "--only", "333") == 0
    assert seen == ["333"]


# ── money ─────────────────────────────────────────────────────────────────────

def test_dry_run_calls_nothing_and_prices_from_the_ledger(drive, runner, monkeypatch, capsys):
    papers, result, _ = drive
    for usd in (0.30, 0.50):
        assay_ledger.append_row({"date": "2026-11-04T00:00:00", "pubmed_id": "9", "study_accession": "SDY9",
                                 "registry_dir": str(result / "9_SDY9"), "rounds": "x", "model": "m",
                                 "calls": 20, "prompt_tokens": 1, "cached_tokens": 0,
                                 "completion_tokens": 1, "reasoning_tokens": 0, "usd": usd,
                                 "price_date": "2026-11-04"})
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(seen))

    assert _main(runner, papers, result, "--dry-run") == 0
    assert seen == []
    assert not (result / "logs").exists()
    out = capsys.readouterr().out
    assert "to run           : 3" in out
    assert "$0.40/paper median" in out
    assert "from 2 ledger row(s)" in out
    assert "nothing called" in out


def test_max_usd_stops_launching_papers(drive, runner, monkeypatch):
    papers, result, _ = drive
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(seen, ledger=0.40))
    monkeypatch.setattr(runner, "report_result", _fake_report_result)

    assert _main(runner, papers, result, "--parallel", "1", "--max-usd", "0.50") == 0
    assert len(seen) == 2  # the second paper crosses $0.50; the third is never launched
    assert len([r for r in _runs(result).values() if r["status"] == "done"]) == 2


# ── status ────────────────────────────────────────────────────────────────────

def test_status_counts_disk_and_the_run_record(drive, runner, monkeypatch, capsys):
    papers, result, _ = drive
    monkeypatch.setattr(runner, "assay_report", _fake_report([], fails=("222",), ledger=0.40))
    monkeypatch.setattr(runner, "report_result", _fake_report_result)
    assert _main(runner, papers, result) == 0

    assert runner.main(["status", "--papers-dir", str(papers), "--result-dir", str(result),
                        "--failed", "--flags"]) == 0
    out = capsys.readouterr().out
    assert "papers with XML : 3" in out
    assert "finished        : 2" in out
    assert "failed          : 1" in out
    assert "pending         : 1" in out
    assert "FAILED  222: RuntimeError: boom" in out
    assert "FLAGGED 111: REVIEW=1;VOTE=1" in out


def test_a_missing_drive_is_a_clear_exit(runner, tmp_path, capsys):
    assert runner.main(["run", "--papers-dir", str(tmp_path / "nope"),
                        "--result-dir", str(tmp_path)]) == 1
    assert "Mount the drive" in capsys.readouterr().err
