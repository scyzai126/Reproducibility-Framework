"""Tests for input detection and routing logic across all use cases."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.orchestrator import _extract_pubmed_id_from_text, _detect_json_type
from app.agent.paper_reader import extract_pubmed_id_from_filename

# Real PDF fixture from the data folder
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAMPLE_PDF = _REPO_ROOT / "data" / "32788292.pdf"


# ── _extract_pubmed_id_from_text ─────────────────────────────────────────────

class TestExtractPubmedIdFromText:

    def test_pubmed_full_url(self):
        pid, url, cleaned = _extract_pubmed_id_from_text(
            "Check https://pubmed.ncbi.nlm.nih.gov/32788292 for healthy subjects"
        )
        assert pid == "32788292"
        assert url == "https://pubmed.ncbi.nlm.nih.gov/32788292"
        assert "healthy subjects" in cleaned
        assert "32788292" not in cleaned

    def test_pmc_full_url(self):
        pid, url, cleaned = _extract_pubmed_id_from_text(
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC7665312/ find plasma samples"
        )
        assert pid == "7665312"
        assert "pmc.ncbi.nlm.nih.gov" in url
        assert "find plasma samples" in cleaned

    def test_europepmc_url(self):
        pid, url, _ = _extract_pubmed_id_from_text("europepmc.org/article/MED/32788292")
        assert pid == "32788292"
        assert url is not None

    def test_bare_pmc_id(self):
        pid, url, cleaned = _extract_pubmed_id_from_text("Find subjects in PMC7665312")
        assert pid == "7665312"
        assert url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC7665312/"
        assert "PMC7665312" not in cleaned

    def test_bare_pmc_id_case_insensitive(self):
        pid, url, _ = _extract_pubmed_id_from_text("pmc7665312 healthy subjects")
        assert pid == "7665312"

    def test_pmid_with_colon(self):
        pid, url, cleaned = _extract_pubmed_id_from_text("PMID:32788292 find subjects")
        assert pid == "32788292"
        assert url is None  # must be resolved via NCBI API
        assert "find subjects" in cleaned

    def test_pmid_without_colon(self):
        pid, url, _ = _extract_pubmed_id_from_text("PMID32788292 find subjects")
        assert pid == "32788292"
        assert url is None

    def test_pmid_with_space(self):
        pid, url, _ = _extract_pubmed_id_from_text("PMID 32788292")
        assert pid == "32788292"
        assert url is None

    def test_pmid_lowercase(self):
        pid, url, _ = _extract_pubmed_id_from_text("pmid:32788292")
        assert pid == "32788292"
        assert url is None

    def test_no_id_returns_none(self):
        pid, url, cleaned = _extract_pubmed_id_from_text("find healthy subjects")
        assert pid is None
        assert url is None
        assert cleaned == "find healthy subjects"

    def test_sdy_accession_not_matched(self):
        # SDY accessions are handled separately in orchestrator, not here
        pid, url, _ = _extract_pubmed_id_from_text("Find subjects in SDY1669")
        assert pid is None
        assert url is None


# ── extract_pubmed_id_from_filename ──────────────────────────────────────────

class TestExtractPubmedIdFromFilename:

    def test_pmid_prefix(self):
        assert extract_pubmed_id_from_filename("PMID32788292.pdf") == "32788292"

    def test_bare_digits(self):
        assert extract_pubmed_id_from_filename("32788292.pdf") == "32788292"

    def test_pmc_prefix_still_extracts_digits(self):
        # PMC prefix no longer special — digits extracted and treated as PMID
        assert extract_pubmed_id_from_filename("PMC7665312.pdf") == "7665312"

    def test_no_digits_returns_none(self):
        assert extract_pubmed_id_from_filename("mypaper.pdf") is None

    def test_empty_filename(self):
        assert extract_pubmed_id_from_filename(".pdf") is None


# ── _detect_json_type ─────────────────────────────────────────────────────────

class TestDetectJsonType:

    def test_claims_json(self):
        import json
        assert _detect_json_type(json.dumps({"claims": [], "study_accession": "SDY1669"})) == "claims"

    def test_signature_json(self):
        import json
        assert _detect_json_type(json.dumps({"participant_group": [], "study_accession": "SDY1669"})) == "signature"

    def test_plain_text(self):
        assert _detect_json_type("Find healthy subjects in SDY1669") == "plain"

    def test_invalid_json(self):
        assert _detect_json_type("{not valid json}") == "plain"


# ── ncbi_utils.pmid_to_pmc_url ───────────────────────────────────────────────

class TestPmidToPmcUrl:

    @pytest.mark.asyncio
    async def test_successful_conversion(self):
        from app.agent.ncbi_utils import pmid_to_pmc_url, _pmc_url_cache
        _pmc_url_cache.clear()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "records": [{"pmid": "32788292", "pmcid": "PMC7665312"}]
        }
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await pmid_to_pmc_url("32788292")

        assert result == "https://pmc.ncbi.nlm.nih.gov/articles/PMC7665312/"

    @pytest.mark.asyncio
    async def test_no_pmc_record_returns_none(self):
        from app.agent.ncbi_utils import pmid_to_pmc_url, _pmc_url_cache
        _pmc_url_cache.clear()

        mock_response = MagicMock()
        mock_response.json.return_value = {"records": [{"pmid": "99999999"}]}
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await pmid_to_pmc_url("99999999")

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_avoids_second_api_call(self):
        from app.agent.ncbi_utils import pmid_to_pmc_url, _pmc_url_cache
        _pmc_url_cache.clear()
        _pmc_url_cache["11111111"] = "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/"

        with patch("httpx.AsyncClient") as mock_cls:
            result = await pmid_to_pmc_url("11111111")
            mock_cls.assert_not_called()

        assert result == "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/"

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self):
        from app.agent.ncbi_utils import pmid_to_pmc_url, _pmc_url_cache
        _pmc_url_cache.clear()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("network error"))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await pmid_to_pmc_url("32788292")

        assert result is None


def _mock_session(fetchone_value=None):
    """Return an AsyncMock session where execute().fetchone() returns fetchone_value."""
    mock_result = MagicMock()
    mock_result.fetchone.return_value = fetchone_value
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    return session


# ── run_agent_from_paper — filename validation ────────────────────────────────

class TestRunAgentFromPaperFilename:

    @pytest.mark.asyncio
    async def test_no_digits_in_filename_raises(self):
        from app.agent.orchestrator import run_agent_from_paper
        with patch("app.agent.orchestrator.extract_pdf_text", return_value="paper text"):
            with pytest.raises(ValueError, match="rename the file"):
                await run_agent_from_paper(b"", "mypaper.pdf", AsyncMock())

    @pytest.mark.asyncio
    async def test_valid_filename_passes_validation_fails_on_db(self):
        """Filename with digits passes filename check — DB lookup fails with clear error."""
        from app.agent.orchestrator import run_agent_from_paper
        with patch("app.agent.orchestrator.extract_pdf_text", return_value="paper text"):
            with pytest.raises(ValueError, match="No study found"):
                await run_agent_from_paper(b"", "32788292.pdf", _mock_session(fetchone_value=None))

    @pytest.mark.skipif(not _SAMPLE_PDF.exists(), reason="sample PDF not found in data/")
    def test_real_pdf_extracts_text(self):
        """Real PDF in data/ can be parsed and filename yields the correct PMID."""
        from app.agent.paper_reader import extract_pdf_text
        pdf_bytes = _SAMPLE_PDF.read_bytes()
        text = extract_pdf_text(pdf_bytes)
        assert len(text) > 100, "Expected substantial text extracted from PDF"
        pmid = extract_pubmed_id_from_filename(_SAMPLE_PDF.name)
        assert pmid == "32788292"


# ── run_agent_from_text — no paper source ────────────────────────────────────

class TestRunAgentFromTextNoPaperSource:

    @pytest.mark.asyncio
    async def test_plain_question_without_source_returns_clarification(self):
        from app.agent.orchestrator import run_agent_from_text
        result = await run_agent_from_text("find healthy subjects with plasma samples", _mock_session())
        assert result.get("type") == "clarification"
        assert "question" in result

    @pytest.mark.asyncio
    async def test_sdy_not_in_immport_raises(self):
        from app.agent.orchestrator import run_agent_from_text
        with pytest.raises(ValueError, match="not found in ImmPort"):
            await run_agent_from_text("Find healthy subjects in SDY9999", _mock_session(fetchone_value=None))

    @pytest.mark.asyncio
    async def test_pmid_with_no_pmc_article_raises(self):
        from app.agent.orchestrator import run_agent_from_text
        from app.agent.ncbi_utils import _pmc_url_cache
        _pmc_url_cache.clear()

        with patch("app.agent.orchestrator.pmid_to_pmc_url", return_value=None):
            with pytest.raises(ValueError, match="no open-access PMC article"):
                await run_agent_from_text("PMID:99999999 find healthy subjects", _mock_session())

    @pytest.mark.asyncio
    async def test_pmid_not_linked_to_immport_returns_no_immport(self):
        """Papers not in ImmPort return a no_immport response with extracted claims instead of raising."""
        from app.agent.orchestrator import run_agent_from_text
        from app.agent.ncbi_utils import _pmc_url_cache
        _pmc_url_cache.clear()

        fake_claims = [{"claim_id": "claim_1", "claim_text": "Some finding.", "sources": []}]
        with patch("app.agent.orchestrator.pmid_to_pmc_url", return_value="https://pmc.ncbi.nlm.nih.gov/articles/PMC7665312/"), \
             patch("app.agent.orchestrator.fetch_paper_content_async", return_value=("paper text", "32788292")), \
             patch("app.agent.orchestrator.parse_paper_claims_noimmport", return_value=fake_claims):
            result = await run_agent_from_text("PMID:32788292 find healthy subjects", _mock_session(fetchone_value=None))

        assert result["type"] == "no_immport"
        assert result["paper_claims"] == fake_claims
        assert result["subject_results"] == []
