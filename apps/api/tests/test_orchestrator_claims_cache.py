"""Claim results are read from benchmark_claims first, then data/cache/claims, and written
only to data/cache/claims -- so a paper parsed once from the UI is not paid for again."""

import json

import pytest

from app.agent import orchestrator

_CLAIMS = {"claim_1": {"claim": "X rises after vaccination", "sources": []}}
_GROUPS = {"claim_1": {"claim": "X rises after vaccination", "groups": []}}


@pytest.fixture
def roots(tmp_path, monkeypatch):
    benchmark = tmp_path / "benchmark"
    cache = tmp_path / "cache"
    monkeypatch.setattr(orchestrator, "_DISK_CACHE_DIR", benchmark)
    monkeypatch.setattr(orchestrator, "_CLAIMS_CACHE_DIR", cache)
    monkeypatch.setattr(orchestrator, "load_verified_registry", lambda *a: {})
    monkeypatch.setattr(orchestrator, "_write_completeness_log", lambda report: None)
    return benchmark, cache


def _write(root, pmid, step, data):
    path = root / pmid / f"{step}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_benchmark_wins_over_cache(roots):
    benchmark, cache = roots
    _write(benchmark, "1", "groups", {"claim_1": {"from": "benchmark"}})
    _write(cache, "1", "groups", {"claim_1": {"from": "cache"}})
    assert orchestrator._load_disk_cache("1", "groups") == {"claim_1": {"from": "benchmark"}}


def test_cache_used_when_benchmark_missing(roots):
    _, cache = roots
    _write(cache, "2", "groups", _GROUPS)
    assert orchestrator._load_disk_cache("2", "groups") == _GROUPS


def test_miss_returns_none(roots):
    assert orchestrator._load_disk_cache("3", "groups") is None


def test_file_without_claim_keys_is_a_miss(roots):
    _, cache = roots
    _write(cache, "4", "claims", {"step1": {}, "step2": {}})
    assert orchestrator._load_disk_cache("4", "claims") is None


def test_save_goes_to_cache_never_benchmark(roots):
    benchmark, cache = roots
    orchestrator._save_disk_cache("5", "groups", _GROUPS)
    assert json.loads((cache / "5" / "groups.json").read_text()) == _GROUPS
    assert not (benchmark / "5").exists()


@pytest.mark.asyncio
async def test_fresh_run_caches_both_steps(roots, monkeypatch):
    _, cache = roots

    async def fake_parse(paper_text, study_accession, cached_step1=None):
        assert cached_step1 is None
        return _CLAIMS, _GROUPS

    monkeypatch.setattr(orchestrator, "parse_paper_claims_from_text", fake_parse)

    await orchestrator._run_full_paper_analysis("text", "SDY1", "6", [])

    assert json.loads((cache / "6" / "claims.json").read_text()) == _CLAIMS
    assert json.loads((cache / "6" / "groups.json").read_text()) == _GROUPS


@pytest.mark.asyncio
async def test_provided_step1_is_cached_before_step2_runs(roots, monkeypatch):
    """A step-2 failure must not lose the step-1 extraction that was already paid for."""
    _, cache = roots

    async def failing_parse(paper_text, study_accession, cached_step1=None):
        raise RuntimeError("step 2 failed")

    monkeypatch.setattr(orchestrator, "parse_paper_claims_from_text", failing_parse)

    with pytest.raises(RuntimeError):
        await orchestrator._run_full_paper_analysis("", "SDY1", "7", [], step1_claims=_CLAIMS)

    assert json.loads((cache / "7" / "claims.json").read_text()) == _CLAIMS
    assert not (cache / "7" / "groups.json").exists()


@pytest.mark.asyncio
async def test_cached_groups_skip_the_model(roots, monkeypatch):
    _, cache = roots
    _write(cache, "8", "groups", _GROUPS)

    async def must_not_run(*a, **k):
        raise AssertionError("model called despite a cache hit")

    monkeypatch.setattr(orchestrator, "parse_paper_claims_from_text", must_not_run)

    result = await orchestrator._run_full_paper_analysis("", "SDY1", "8", [])
    # Returned even though it matched no subjects.
    assert [(c["claim_id"], c["claim_text"]) for c in result["claims"]] == [
        (1, "X rises after vaccination")
    ]


@pytest.mark.asyncio
async def test_claim_ids_keep_their_claim_n_numbers(roots, monkeypatch):
    """Unmatched claims are not dropped, and ids are not renumbered to 1..N."""
    _, cache = roots
    _write(cache, "9", "groups", {
        "claim_1": {"claim": "first", "groups": []},
        "claim_3": {"claim": "third", "groups": []},
    })

    result = await orchestrator._run_full_paper_analysis("", "SDY1", "9", [])
    assert sorted((c["claim_id"], c["claim_text"]) for c in result["claims"]) == [
        (1, "first"), (3, "third")
    ]
