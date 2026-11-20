"""The corpus batch runner: every runnable paper, resumable, and no paper lost to another's failure.

Every test here stubs `assay_report`. A real run is upwards of 600 calls, and none of what this
script decides -- which papers to run, where the deliverable lands, what a failure does to the
rest of the queue -- depends on what the pipeline actually answers.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_runner():
    """Import scripts/run_assay_batch.py, which is not an importable package."""
    path = _REPO_ROOT / "scripts" / "run_assay_batch.py"
    spec = importlib.util.spec_from_file_location("run_assay_batch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


@pytest.fixture
def corpus(tmp_path, runner, monkeypatch):
    """Two papers on disk, with the registry root redirected into tmp_path."""
    xml_dir = tmp_path / "JAT_XML"
    xml_dir.mkdir()
    (xml_dir / "SDY1_111.xml").write_text("<article/>", encoding="utf-8")
    (xml_dir / "SDY2_222.xml").write_text("<article/>", encoding="utf-8")

    registry_root = tmp_path / "assay_registries"
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir()
    monkeypatch.setattr(runner, "REGISTRY_ROOT", registry_root)
    monkeypatch.setattr(runner, "PDF_ROOT", pdf_dir)
    monkeypatch.setattr(runner, "registry_dir",
                        lambda pmid, sdy: registry_root / f"{pmid}_{sdy}")
    monkeypatch.setattr(runner, "_get_client", lambda: object())
    monkeypatch.setattr(runner, "report_result", lambda result: None)
    return xml_dir, registry_root


def _fake_report(runner, registry_root, calls, *, fails=(), undelivered=()):
    """An assay_report that writes the seven files a real one would, and records the paper.

    A pmid in `undelivered` gets what a run whose OBI round failed gets: rounds 1-3 on disk,
    no assays_OBI.json, no assays_benchmark.json, and a result whose benchmark_path is None.
    """
    async def _run(pmid, sdy, client, verify=True, correct=True):
        calls.append(pmid)
        if pmid in fails:
            raise RuntimeError("boom")
        out_dir = registry_root / f"{pmid}_{sdy}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in ("assays.json", "assays_verification.json", "assays_corrections.json",
                     "assays_corrected.json", "assays_precorrection.json"):
            (out_dir / name).write_text("{}\n", encoding="utf-8")
        if pmid in undelivered:
            return {"meta": {"llm_calls": 3, "benchmark_path": None},
                    "rounds": {"obi": {"source": "failed", "calls": 0}}}
        (out_dir / "assays_benchmark.json").write_text("{}\n", encoding="utf-8")
        (out_dir / "assays_OBI.json").write_text(
            json.dumps({"flow cytometry": {"obi_id": f"OBI:{pmid}"}}) + "\n", encoding="utf-8")
        return {"meta": {"llm_calls": 3,
                         "benchmark_path": str(out_dir / "assays_benchmark.json")},
                "rounds": {}}
    return _run


# ── the deliverable ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_each_paper_is_run_into_its_own_registry_directory(corpus, runner, monkeypatch):
    xml_dir, registry_root = corpus
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, seen))

    await runner.main(xml_dir, [], force=False, dry=False)

    assert sorted(seen) == ["111", "222"]
    assert (registry_root / "111_SDY1" / "assays_benchmark.json").exists()
    # No flat copy: the ones this script used to write drifted from their registries.
    assert not list(registry_root.glob("assays_OBI_*.json"))


@pytest.mark.asyncio
async def test_the_pmid_is_taken_from_the_sdy_prefixed_half(corpus, runner, monkeypatch):
    """XML files are <SDY>_<pmid> while registries are <pmid>_<SDY>; the halves are identified
    by which starts with "SDY", not by position."""
    xml_dir, registry_root = corpus
    (xml_dir / "333_SDY3.xml").write_text("<article/>", encoding="utf-8")
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, seen))

    await runner.main(xml_dir, [], force=False, dry=False)

    assert "333" in seen
    assert (registry_root / "333_SDY3" / "assays_benchmark.json").exists()


def test_a_pdf_only_paper_is_in_the_queue_and_a_pdf_of_an_xml_paper_is_not(
        corpus, runner, tmp_path):
    """The pipeline falls back to a paper's PDF, so a PDF-only paper is runnable."""
    xml_dir, _ = corpus
    (tmp_path / "pdf" / "SDY4_444.pdf").write_bytes(b"%PDF")
    (tmp_path / "pdf" / "SDY1_111.pdf").write_bytes(b"%PDF")

    papers = runner.discover(xml_dir, [])

    assert [(pmid, path.suffix) for pmid, _, path in papers] == [
        ("111", ".xml"), ("222", ".xml"), ("444", ".pdf")]


# ── resuming ──────────────────────────────────────────────────────────────────

def _finish(registry_root: Path, stem: str) -> None:
    (registry_root / stem).mkdir(parents=True, exist_ok=True)
    (registry_root / stem / "assays_benchmark.json").write_text("{}\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_a_finished_paper_is_not_paid_for_twice(corpus, runner, monkeypatch):
    xml_dir, registry_root = corpus
    _finish(registry_root, "111_SDY1")
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, seen))

    await runner.main(xml_dir, [], force=False, dry=False)

    assert seen == ["222"], "the finished paper was re-run"


@pytest.mark.asyncio
async def test_force_re_runs_a_finished_paper(corpus, runner, monkeypatch):
    """The pipeline never reuses anything; --force is how you get that after a prompt edit."""
    xml_dir, registry_root = corpus
    _finish(registry_root, "111_SDY1")
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, seen))

    await runner.main(xml_dir, [], force=True, dry=False)

    assert sorted(seen) == ["111", "222"]


@pytest.mark.asyncio
async def test_only_restricts_the_queue(corpus, runner, monkeypatch):
    xml_dir, registry_root = corpus
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, seen))

    await runner.main(xml_dir, ["222"], force=False, dry=False)

    assert seen == ["222"]


# ── one paper's failure is one paper's ────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_failing_paper_does_not_stop_the_queue(corpus, runner, monkeypatch):
    """Every earlier paper is already on disk and every later one is independent."""
    xml_dir, registry_root = corpus
    seen = []
    monkeypatch.setattr(runner, "assay_report",
                        _fake_report(runner, registry_root, seen, fails=("111",)))

    await runner.main(xml_dir, [], force=False, dry=False)

    assert sorted(seen) == ["111", "222"], "the second paper was skipped after the first failed"
    assert not (registry_root / "111_SDY1" / "assays_benchmark.json").exists()
    assert (registry_root / "222_SDY2" / "assays_benchmark.json").exists()


@pytest.mark.asyncio
async def test_a_paper_without_its_deliverable_is_not_done(corpus, runner, monkeypatch, capsys):
    """A run whose OBI round failed returns normally but withholds assays_benchmark.json. It is
    listed with the failures, not the finished papers, and the next resume runs it again --
    counted done, it would have been skipped on every resume with no file to say why."""
    xml_dir, registry_root = corpus
    seen = []
    monkeypatch.setattr(runner, "assay_report",
                        _fake_report(runner, registry_root, seen, undelivered=("111",)))

    await runner.main(xml_dir, [], force=False, dry=False)
    out = capsys.readouterr().out

    assert (registry_root / "111_SDY1" / "assays.json").exists()
    assert not (registry_root / "111_SDY1" / "assays_benchmark.json").exists()
    assert "1 done, 0 skipped, 1 failed" in out
    assert "NOT DELIVERED  111" in out
    assert "FAILED  111: OBI mapping did not run" in out

    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, seen))
    await runner.main(xml_dir, [], force=False, dry=False)
    assert seen == ["111", "222", "111"], "the undelivered paper was not picked up on resume"


# ── the dry run spends nothing ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_dry_run_makes_no_call(corpus, runner, monkeypatch, capsys):
    xml_dir, registry_root = corpus
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, seen))
    # The same estimator the single-paper CLI and the web cost gate use.
    monkeypatch.setattr(runner, "estimate", lambda pmid, sdy: 30 if pmid == "111" else None)

    await runner.main(xml_dir, [], force=False, dry=True)

    assert seen == []
    out = capsys.readouterr().out
    assert "~30 calls for the 1 that have run before" in out
    assert "plus 1 that cannot be sized" in out


@pytest.mark.asyncio
async def test_result_version_routes_every_paper_under_that_folder(corpus, runner, monkeypatch,
                                                                   tmp_path):
    """--result-version: each paper's folder is created under data/benchmark_agent_assays/<NAME>/ before
    the run, so done_path and the pipeline land there instead of in the cache."""
    xml_dir, _registry_root = corpus
    from app.agent import assay_service
    corpus_root = tmp_path / "corpus"
    monkeypatch.setattr(assay_service, "CORPUS_ROOT", corpus_root)
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_dir)
    monkeypatch.setattr(assay_service, "PDF_ROOT", tmp_path / "pdf")
    # The real registry_dir, so the test proves the folder it finds is the version's.
    monkeypatch.setattr(runner, "registry_dir", assay_service.registry_dir)
    seen = []
    monkeypatch.setattr(runner, "assay_report",
                        _fake_report(runner, corpus_root / "assay_result_v3", seen))

    await runner.main(xml_dir, [], force=False, dry=False, result_version="assay_result_v3")

    assert sorted(seen) == ["111", "222"]
    assert (corpus_root / "assay_result_v3" / "111_SDY1" / "assays_benchmark.json").exists()
    assert runner.done_path("222", "SDY2") == corpus_root / "assay_result_v3" / "222_SDY2" / "assays_benchmark.json"
