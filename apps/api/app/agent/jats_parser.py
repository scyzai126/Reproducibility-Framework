"""Parse JATS XML from PubMed Central into structured plain text for LLM consumption."""

import re

from bs4 import BeautifulSoup

MAX_PAPER_CHARS = 120000


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _canonical_section(title: str) -> str:
    t = (title or "").strip().lower()
    if "abstract" in t:
        return "abstract"
    if "introduction" in t or t == "background":
        return "introduction"
    if "result" in t:
        return "results"
    if "method" in t or "materials" in t:
        return "methods"
    if "discussion" in t or "conclusion" in t:
        return "discussion"
    return "other"



def _extract_figure_caption_parts(tag) -> tuple[str, str]:
    """Return (title, body) from a JATS <caption> element.

    In JATS XML the <caption> element contains an optional <title> (the short
    figure heading) followed by the legend content — <p> tags, lists, notes,
    inline markup, etc. There is no <legend> element in JATS; all legend text
    lives inside <caption>.

    We extract the title separately and then collect ALL remaining caption
    content (not just <p> tags) so nothing is dropped.
    """
    cap = tag.find("caption")
    if not cap:
        return "", ""
    title_tag = cap.find("title")
    title = _clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
    # Collect text from every child element except the <title> tag so that
    # lists, notes, and other non-<p> markup are included.
    body_parts = [
        _clean_text(child.get_text(" ", strip=True))
        for child in cap.children
        if child is not title_tag and hasattr(child, "get_text")
    ]
    body = " ".join(p for p in body_parts if p)
    return title, body


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


def parse_jats_xml(xml_text: str) -> str:
    """Extract structured text from JATS XML: sections, figures, and tables.

    Output order: abstract → introduction → results (including subsections) →
    methods (including subsections) → discussion → other sections →
    Figures block → Tables block.

    Subsections inherit their canonical type from the nearest ancestor <sec>
    so that e.g. "Innate immune activation" inside Results is sorted with
    Results rather than at the end.
    """
    soup = BeautifulSoup(xml_text, "xml")
    section_records: list[tuple[int, str, str, str]] = []
    order = 0

    # Abstract often sits outside <sec>.
    for abstract in soup.find_all("abstract"):
        para = [_clean_text(p.get_text(" ", strip=True)) for p in abstract.find_all("p")]
        para = [p for p in para if p]
        if not para:
            raw = _clean_text(abstract.get_text(" ", strip=True))
            if raw:
                para = [raw]
        if para:
            section_records.append((order, "abstract", "Abstract", "\n".join(para)))
            order += 1

    # Walk all sections in document order.
    for sec in soup.find_all("sec"):
        title_tag = sec.find("title", recursive=False)
        sec_title = _clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
        header = sec_title or sec.get("sec-type") or "Section"

        # Determine canonical section type; if "other", inherit from the nearest
        # ancestor <sec> so that subsections of Results/Methods are not sorted last.
        canon = _canonical_section(header)
        if canon == "other":
            for ancestor in sec.parents:
                if ancestor.name != "sec":
                    continue
                anc_title_tag = ancestor.find("title", recursive=False)
                anc_title = _clean_text(anc_title_tag.get_text(" ", strip=True)) if anc_title_tag else ""
                anc_canon = _canonical_section(anc_title or ancestor.get("sec-type") or "")
                if anc_canon != "other":
                    canon = anc_canon
                    break

        paragraphs: list[str] = []
        for p in sec.find_all("p"):
            # Skip p-tags nested inside figure/table nodes and keep only p for this exact sec.
            if p.find_parent(["fig", "table-wrap"]) is not None:
                continue
            if p.find_parent("sec") is not sec:
                continue
            txt = _clean_text(p.get_text(" ", strip=True))
            if txt:
                paragraphs.append(txt)
        if not paragraphs:
            continue
        section_records.append((order, canon, str(header), "\n".join(paragraphs)))
        order += 1

    # Reorder: key narrative sections first, then all others by document order.
    preferred = ["abstract", "introduction", "results", "methods", "discussion"]
    ordered_sections: list[tuple[int, str, str, str]] = []
    used: set[int] = set()
    for key in preferred:
        for rec in section_records:
            if rec[1] == key:
                ordered_sections.append(rec)
                used.add(id(rec))
    for rec in section_records:
        if id(rec) not in used:
            ordered_sections.append(rec)

    _INCLUDE_SECTIONS = {"results", "methods"}

    section_blocks: list[str] = []
    seen_section_bodies: set[str] = set()
    has_results = False
    has_methods = False
    for _, canon, header, body in ordered_sections:
        if canon not in _INCLUDE_SECTIONS:
            continue
        normalized = _clean_text(body)
        if not normalized or normalized in seen_section_bodies:
            continue
        seen_section_bodies.add(normalized)
        section_blocks.append(f"## {header}\n{body}")
        if canon == "results":
            has_results = True
        elif canon == "methods":
            has_methods = True

    # ── Figures ──────────────────────────────────────────────────────────────
    fig_blocks: list[str] = []
    seen_fig: set = set()

    def _append_fig_block(label: str, cap_title: str, cap_body: str) -> None:
        key = (label, cap_title, cap_body)
        if key in seen_fig or not (label or cap_title or cap_body):
            return
        seen_fig.add(key)
        lines = [f"[{label}]"]
        if cap_title:
            lines.append(f"  Title: {cap_title}")
        if cap_body:
            lines.append(f"  Caption: {cap_body}")
        fig_blocks.append("\n".join(lines))

    for fig in soup.find_all("fig"):
        label_tag = fig.find("label")
        label = _clean_text(label_tag.get_text(" ", strip=True)) if label_tag else "Figure"
        cap_title, cap_body = _extract_figure_caption_parts(fig)
        _append_fig_block(label, cap_title, cap_body)

    # Supplementary materials with captions (not already inside a <fig>).
    for supp in soup.find_all("supplementary-material"):
        if supp.find_parent("fig") is not None:
            continue
        label_tag = supp.find("label")
        label = _clean_text(label_tag.get_text(" ", strip=True)) if label_tag else "Supplementary"
        cap_title, cap_body = _extract_figure_caption_parts(supp)
        if cap_title or cap_body:
            _append_fig_block(label, cap_title, cap_body)

    has_figures = bool(fig_blocks)

    # ── Fallback ─────────────────────────────────────────────────────────────
    # If any of the three key sections is missing, the XML doesn't follow
    # standard JATS conventions. Send the full article text (minus the
    # reference list) so the LLM still has complete information.
    if not has_results or not has_methods or not has_figures:
        for ref_list in soup.find_all("ref-list"):
            ref_list.decompose()
        return _clean_text(soup.get_text(separator=" ", strip=True))[:MAX_PAPER_CHARS]

    blocks = list(section_blocks)
    if fig_blocks:
        blocks.append("--- Figures ---\n" + "\n\n".join(fig_blocks))

    return _truncate_blocks(blocks, MAX_PAPER_CHARS)
