"""The corpus batch runner: one flat deliverable per paper, and no paper lost to another's failure.

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
    monkeypatch.setattr(runner, "REGISTRY_ROOT", registry_root)
    monkeypatch.setattr(runner, "registry_dir",
                        lambda pmid, sdy: registry_root / f"{pmid}_{sdy}")
    monkeypatch.setattr(runner, "_get_client", lambda: object())
    monkeypatch.setattr(runner, "report_result", lambda result: None)
    return xml_dir, registry_root


def _fake_report(runner, registry_root, calls, *, fails=()):
    """An assay_report that writes the seven files a real one would, and records the paper."""
    async def _run(pmid, sdy, client, verify=True, correct=True):
        calls.append(pmid)
        if pmid in fails:
            raise RuntimeError("boom")
        out_dir = registry_root / f"{pmid}_{sdy}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in ("assays.json", "assays_benchmark.json", "assays_verification.json",
                     "assays_corrections.json", "assays_corrected.json",
                     "assays_precorrection.json"):
            (out_dir / name).write_text("{}\n", encoding="utf-8")
        (out_dir / "assays_OBI.json").write_text(
            json.dumps({"flow cytometry": {"obi_id": f"OBI:{pmid}"}}) + "\n", encoding="utf-8")
        return {"meta": {"llm_calls": 3}, "rounds": {}}
    return _run


# ── the deliverable ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_each_paper_lands_as_one_flat_file_named_by_pmid(corpus, runner, monkeypatch):
    xml_dir, registry_root = corpus
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, seen))

    await runner.main(xml_dir, [], force=False, dry=False)

    assert sorted(seen) == ["111", "222"]
    assert (registry_root / "assays_OBI_111.json").exists()
    assert (registry_root / "assays_OBI_222.json").exists()
    assert json.loads((registry_root / "assays_OBI_111.json").read_text())[
        "flow cytometry"]["obi_id"] == "OBI:111"


@pytest.mark.asyncio
async def test_the_per_paper_trail_survives_the_copy(corpus, runner, monkeypatch):
    """The flat file is a copy. The verification and correction trail cost money to produce."""
    xml_dir, registry_root = corpus
    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, []))

    await runner.main(xml_dir, [], force=False, dry=False)

    paper_dir = registry_root / "111_SDY1"
    assert (paper_dir / "assays_OBI.json").exists(), "the source was moved, not copied"
    for name in ("assays.json", "assays_verification.json", "assays_corrections.json"):
        assert (paper_dir / name).exists(), name


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
    assert (registry_root / "assays_OBI_333.json").exists()


# ── resuming ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_finished_paper_is_not_paid_for_twice(corpus, runner, monkeypatch):
    xml_dir, registry_root = corpus
    registry_root.mkdir(parents=True, exist_ok=True)
    (registry_root / "assays_OBI_111.json").write_text("{}\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, seen))

    await runner.main(xml_dir, [], force=False, dry=False)

    assert seen == ["222"], "the finished paper was re-run"


@pytest.mark.asyncio
async def test_force_re_runs_a_finished_paper(corpus, runner, monkeypatch):
    """The pipeline never reuses anything; --force is how you get that after a prompt edit."""
    xml_dir, registry_root = corpus
    registry_root.mkdir(parents=True, exist_ok=True)
    (registry_root / "assays_OBI_111.json").write_text("{}\n", encoding="utf-8")
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
    assert not (registry_root / "assays_OBI_111.json").exists()
    assert (registry_root / "assays_OBI_222.json").exists()


@pytest.mark.asyncio
async def test_a_soft_obi_failure_leaves_no_flat_file(corpus, runner, monkeypatch):
    """Round 4 fails soft, so assay_report returns without writing assays_OBI.json."""
    xml_dir, registry_root = corpus

    async def _no_obi(pmid, sdy, client, verify=True, correct=True):
        (registry_root / f"{pmid}_{sdy}").mkdir(parents=True, exist_ok=True)
        return {"meta": {"llm_calls": 3}, "rounds": {}}

    monkeypatch.setattr(runner, "assay_report", _no_obi)

    await runner.main(xml_dir, [], force=False, dry=False)

    assert not list(registry_root.glob("assays_OBI_*.json"))


# ── the dry run spends nothing ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_dry_run_makes_no_call(corpus, runner, monkeypatch):
    xml_dir, registry_root = corpus
    seen = []
    monkeypatch.setattr(runner, "assay_report", _fake_report(runner, registry_root, seen))

    await runner.main(xml_dir, [], force=False, dry=True)

    assert seen == []
    assert not registry_root.exists() or not list(registry_root.glob("assays_OBI_*.json"))
