"""Backward-compatible wrappers around the structured JATS parser."""

from app.agent.paper_context import render_paper_context_for_llm
from app.agent.paper_jats import MAX_PAPER_CHARS, clean_text as _clean_text, parse_jats_xml_to_json


def parse_jats_xml(xml_text: str) -> str:
    """Legacy wrapper returning prompt-friendly text from structured JATS parsing."""
    return render_paper_context_for_llm(parse_jats_xml_to_json(xml_text), char_limit=MAX_PAPER_CHARS)
