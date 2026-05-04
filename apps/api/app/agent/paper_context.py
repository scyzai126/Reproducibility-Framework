"""Render structured paper content into prompt-friendly text."""

from __future__ import annotations

from app.agent.paper_jats import MAX_PAPER_CHARS, clean_text


def _truncate_blocks(blocks: list[str], limit: int) -> str:
    if not blocks:
        return ""
    sep = "\n\n"
    out: list[str] = []
    total = 0
    for block in blocks:
        prefix = "" if not out else sep
        chunk = f"{prefix}{block}"
        if total + len(chunk) <= limit:
            out.append(block)
            total += len(chunk)
            continue
        remaining = limit - total
        if remaining > 200:
            partial = chunk[:remaining]
            if " " in partial:
                partial = partial.rsplit(" ", 1)[0]
            out.append(partial.lstrip())
        break
    return sep.join(out)


def render_blocks_for_llm(blocks: list[dict], char_limit: int = MAX_PAPER_CHARS) -> str:
    """Render semantic blocks in document order into prompt-friendly text.

    Each block header embeds its primary_label and claim_priority so the LLM
    can apply its own focus rules via the system prompt.
    """
    text_blocks: list[str] = []
    for block in blocks:
        title = block.get("title") or ""
        text = block.get("text") or ""
        primary = block.get("primary_label", "")
        priority = block.get("claim_priority", "")
        tag_type = block.get("tag_type", "")

        if not clean_text(text):
            continue

        label_tag = f"[{primary} · {priority}]" if primary else ""

        if tag_type in ("figure_legend", "table_caption"):
            header = f"[{title}] {label_tag}".strip()
            text_blocks.append(f"{header}\n{text}")
        else:
            section_title = title or primary or "Section"
            text_blocks.append(f"## {section_title} {label_tag}\n{text}".strip())

    return _truncate_blocks(text_blocks, char_limit)


def render_paper_context_for_llm(paper_json: dict, char_limit: int = MAX_PAPER_CHARS) -> str:
    """Convert structured paper content into a compact context string for the LLM."""
    blocks = paper_json.get("blocks")
    if blocks:
        rendered = render_blocks_for_llm(blocks, char_limit)
        if rendered:
            return rendered

    return (paper_json.get("raw_text") or "")[:char_limit]
