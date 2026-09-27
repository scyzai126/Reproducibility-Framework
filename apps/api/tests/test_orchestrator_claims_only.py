"""A paper with no single ImmPort study is never run silently: the user is asked, and a "yes"
extracts claims only -- no grouping, no study sync, no subject queries."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent import assay_service, jats_fetcher, orchestrator, pdf_direct

pytestmark = pytest.mark.asyncio

_V8 = {
    "claim_1": {
        "claim": "IFN genes rise at day 1",
        "claim_type": "induction_vs_reference",
        "assay": {"name_in_paper": "microarray"},
        "sources": [{"type": "text", "section": "Results", "quote": "q"}],
    },
    "claim_2": {"claim": "Cohort was 60% female", "claim_type": "descriptive", "sources": []},
}


def _session(studies: list[str]):
    result = MagicMock()
    result.fetchall.return_value = [(s,) for s in studies]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "_DISK_CACHE_DIR", tmp_path / "benchmark")
    monkeypatch.setattr(orchestrator, "_CLAIMS_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(orchestrator, "_PDF_DIR", tmp_path / "pdf")
    monkeypatch.setattr(orchestrator, "_write_workflow_log", lambda log: None)
    monkeypatch.setattr(assay_service, "XML_ROOT", tmp_path / "xml")
    monkeypatch.setattr("app.agent.claim_parser._get_client", lambda: object())
    calls = {"download": 0, "v8": 0, "pdf": []}
    state = {"download_error": None}

    async def fake_download(pmid):
        calls["download"] += 1
        if state["download_error"]:
            raise state["download_error"]
        return "<article/>", "PMC1"

    async def fake_v8(xml_text):
        calls["v8"] += 1
        return dict(_V8)

    async def fake_pdf(pdf_bytes, filename, client):
        calls["pdf"].append((pdf_bytes, filename))
        return {"claim_1": {"claim": "from pdf", "claim_type": "group_difference", "sources": []}}, []

    monkeypatch.setattr(jats_fetcher, "download_jats", fake_download)
    monkeypatch.setattr(orchestrator, "_v8_claims", fake_v8)
    monkeypatch.setattr(pdf_direct, "extract_claims_from_pdf_direct", fake_pdf)
    return tmp_path, calls, state


# ── the question ─────────────────────────────────────────────────────────────

async def test_multiple_studies_asks_and_lists_them():
    result = await orchestrator.run_agent_from_pubmed_id("123", _session(["SDY1", "SDY2"]))
    assert result["type"] == "immport_confirm"
    assert result["situation"] == "multiple_studies"
    assert result["study_options"] == ["SDY1", "SDY2"]
    assert "SDY1, SDY2" in result["question"]


async def test_uploaded_pdf_is_kept_for_the_answer(env, monkeypatch):
    tmp_path, _, _ = env
    monkeypatch.setattr(orchestrator, "extract_pdf_text", lambda b: "text")
    result = await orchestrator.run_agent_from_paper(b"%PDF-x", "123.pdf", _session([]))
    assert result["type"] == "immport_confirm" and result["situation"] == "not_in_immport"
    assert (tmp_path / "cache" / "123" / "uploaded.pdf").read_bytes() == b"%PDF-x"


async def test_one_study_does_not_ask(env):
    with patch.object(orchestrator, "_step1_claims_xml_first", AsyncMock(return_value=None)), \
         patch.object(orchestrator, "_run_paper_pipeline", AsyncMock(return_value={"type": "ran"})) as run:
        result = await orchestrator.run_agent_from_pubmed_id("123", _session(["SDY1"]))
    assert result == {"type": "ran"}
    assert run.call_args.args[2] == "SDY1"


async def test_yes_reply_routes_to_claims_only(env):
    with patch.object(orchestrator, "run_claims_only", AsyncMock(return_value={"type": "claims_only"})) as co:
        result = await orchestrator.run_agent_from_text("PMID:123 claims-only", _session([]))
    assert result == {"type": "claims_only"}
    assert co.call_args.args[0] == "123"


# ── the claims-only run ──────────────────────────────────────────────────────

async def test_claims_only_from_xml_keeps_every_claim_and_caches(env):
    tmp_path, calls, _ = env
    result = await orchestrator.run_claims_only("123", [])

    assert result["type"] == "claims_only" and result["pubmed_id"] == "123"
    assert [c["claim_type"] for c in result["paper_claims"]] == ["induction_vs_reference", "descriptive"]
    assert result["claims"] == [] and result["subject_results"] == []
    assert calls["download"] == 1 and calls["v8"] == 1
    cached = json.loads((tmp_path / "cache" / "123" / "claims_only.json").read_text())
    assert set(cached) == {"claim_1", "claim_2"}
    # Not where _load_disk_cache looks, so an ImmPort-backed run is never handed these.
    assert orchestrator._load_disk_cache("123", "claims") is None

    await orchestrator.run_claims_only("123", [])
    assert calls["v8"] == 1  # second call served from claims_only.json


async def test_claims_only_prefers_xml_on_disk(env):
    tmp_path, calls, _ = env
    (tmp_path / "xml").mkdir()
    (tmp_path / "xml" / "SDY9_123.xml").write_text("<article/>", encoding="utf-8")
    await orchestrator.run_claims_only("123", [])
    assert calls["download"] == 0 and calls["v8"] == 1


async def test_claims_only_falls_back_to_uploaded_pdf(env):
    tmp_path, calls, state = env
    state["download_error"] = jats_fetcher.PaperUnavailableError("publisher blocks XML")
    (tmp_path / "cache" / "123").mkdir(parents=True)
    (tmp_path / "cache" / "123" / "uploaded.pdf").write_bytes(b"%PDF")

    result = await orchestrator.run_claims_only("123", [])
    assert calls["v8"] == 0 and calls["pdf"] == [(b"%PDF", "uploaded.pdf")]
    assert result["paper_claims"][0]["claim_text"] == "from pdf"


async def test_claims_only_without_xml_or_pdf_raises(env):
    _, _, state = env
    state["download_error"] = jats_fetcher.PaperNotInPMCError("not in PMC")
    with pytest.raises(orchestrator.PaperSourceUnavailable, match="not in PMC"):
        await orchestrator.run_claims_only("123", [])
