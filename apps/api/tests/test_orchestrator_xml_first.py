"""Step-1 claims come from the paper's JATS XML (v8 abstraction) whenever PMC serves it; a PDF
is used only when it does not, and a cached paper is neither fetched nor extracted."""

import pytest

from app.agent import claim_abstraction_v5, jats_fetcher, orchestrator, pdf_direct

pytestmark = pytest.mark.asyncio

_V8_CLAIMS = {
    "claim_1": {
        "claim": "IFN genes rise at day 1",
        "claim_type": "induction_vs_reference",
        "polarity": "affirm",
        "assay": {"name_in_paper": "microarray"},
        "sources": [{"type": "text", "section": "Results", "quote": "q"}],
    },
    "claim_2": {
        "claim": "Cohort was 60% female",
        "claim_type": "descriptive",
        "polarity": "affirm",
        "assay": {"name_in_paper": ""},
        "sources": [],
    },
}
_PDF_STEP1 = {"assays": {}, "claim_1": {"claim": "from pdf", "sources": []}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Empty caches, an XML file on disk, and recorders on every paid/networked call."""
    monkeypatch.setattr(orchestrator, "_DISK_CACHE_DIR", tmp_path / "benchmark")
    monkeypatch.setattr(orchestrator, "_CLAIMS_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(orchestrator, "_PDF_DIR", tmp_path / "pdf")
    monkeypatch.setattr("app.agent.claim_parser._get_client", lambda: object())
    monkeypatch.setattr("app.agent.assay_obi_mapper.enrich_assays_with_obi", lambda reg: reg)

    xml_path = tmp_path / "SDY1_123.xml"
    xml_path.write_text("<article/>", encoding="utf-8")
    calls = {"fetch": 0, "v8": 0, "pdf": []}
    state = {"fetch_error": None}

    async def fake_fetch(pmid, sdy, **kw):
        calls["fetch"] += 1
        if state["fetch_error"]:
            raise state["fetch_error"]
        return {"path": str(xml_path), "created": False}

    async def fake_v8(xml_text, client, model, runs=1, **kw):
        calls["v8"] += 1
        assert runs == orchestrator.V8_RUNS
        return dict(_V8_CLAIMS), {}

    async def fake_pdf(pdf_bytes, filename, client):
        calls["pdf"].append((pdf_bytes, filename))
        return dict(_PDF_STEP1)

    monkeypatch.setattr(jats_fetcher, "fetch_jats", fake_fetch)
    monkeypatch.setattr(claim_abstraction_v5, "abstract_claims_from_document", fake_v8)
    monkeypatch.setattr(pdf_direct, "extract_step1_from_pdf_direct", fake_pdf)
    return tmp_path, calls, state


async def test_xml_available_runs_v8_and_keeps_filtered_claims(env):
    _, calls, _ = env
    log: list[str] = []
    step1 = await orchestrator._step1_claims_xml_first("123", "SDY1", log, pdf_bytes=b"%PDF")

    assert calls == {"fetch": 1, "v8": 1, "pdf": []}  # XML wins even with a PDF uploaded
    assert [k for k in step1 if k.startswith("claim_")] == ["claim_1"]  # descriptive dropped
    assert step1["claim_1"]["claim"] == "IFN genes rise at day 1"
    assert "microarray" in step1["assays"]
    assert "source: JATS XML" in log[-1]


async def test_xml_unavailable_uses_uploaded_pdf(env):
    _, calls, state = env
    state["fetch_error"] = jats_fetcher.PaperUnavailableError("publisher blocks XML")
    log: list[str] = []
    step1 = await orchestrator._step1_claims_xml_first(
        "123", "SDY1", log, pdf_bytes=b"%PDF", pdf_name="SDY1_123.pdf"
    )

    assert step1 == _PDF_STEP1
    assert calls["v8"] == 0 and calls["pdf"] == [(b"%PDF", "SDY1_123.pdf")]
    assert "publisher blocks XML" in log[-1]


async def test_xml_unavailable_uses_local_pdf(env):
    tmp_path, calls, state = env
    state["fetch_error"] = jats_fetcher.PaperNotInPMCError("not in PMC")
    (tmp_path / "pdf" / "sub").mkdir(parents=True)
    (tmp_path / "pdf" / "sub" / "SDY1_123.pdf").write_bytes(b"local")

    await orchestrator._step1_claims_xml_first("123", "SDY1", [])
    assert calls["pdf"] == [(b"local", "SDY1_123.pdf")]


async def test_no_xml_and_no_pdf_raises_with_reason(env):
    _, calls, state = env
    state["fetch_error"] = jats_fetcher.PaperUnavailableError("abstract-only XML")
    with pytest.raises(orchestrator.PaperSourceUnavailable, match="abstract-only XML"):
        await orchestrator._step1_claims_xml_first("123", "SDY1", [])
    assert calls["v8"] == 0 and calls["pdf"] == []


@pytest.mark.parametrize("step", ["groups", "claims"])
async def test_cached_paper_is_not_fetched(env, step):
    _, calls, _ = env
    orchestrator._save_disk_cache("123", step, {"claim_1": {"claim": "cached"}})
    assert await orchestrator._step1_claims_xml_first("123", "SDY1", []) is None
    assert calls == {"fetch": 0, "v8": 0, "pdf": []}
