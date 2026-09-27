"""PDF-direct extraction parses a model response carrying raw control characters.

The model copies quotes from the PDF text layer, line breaks included, and strict JSON rejects
a literal newline inside a string -- which failed SDY1364's run after its extraction was paid for.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent import pdf_direct


@pytest.mark.asyncio
async def test_raw_newline_in_claim_is_parsed(monkeypatch):
    monkeypatch.setattr(pdf_direct, "_build_claims_prompt", lambda: "prompt")
    message = MagicMock()
    message.content = '{"claim_1": {"claim": "line1\nline2\ttabbed", "sources": []}}'
    resp = MagicMock()
    resp.choices = [MagicMock(message=message)]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)

    claims, unmatched = await pdf_direct.extract_claims_from_pdf_direct(b"%PDF", "x.pdf", client)

    assert claims == {"claim_1": {"claim": "line1\nline2\ttabbed", "sources": []}}
    assert unmatched == []
