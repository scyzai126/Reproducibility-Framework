"""Parse JATS XML from PubMed Central into structured plain text for LLM consumption."""

import re
from typing import Optional, Union

from lxml import etree

MAX_PAPER_CHARS = 120000


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_extended_data_refs(text: str) -> str:
    """Remove parenthetical Extended Data references from paragraph text."""
    text = re.sub(r"\(\s*Extended Data[^)]*\)", "", text)
    text = re.sub(r",?\s*Extended Data\s+(?:Fig|Table)s?\.?\s*[\w\d,\s–\-]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_dedicated_section_header(title: str, canon: str) -> bool:
    """True only when a title is a short standalone section label (e.g. 'Results',
    'METHODS'), not a long descriptive sentence that merely contains a keyword
    (e.g. 'COVID-19 results in functional impairment of blood myeloid cells')."""
    return len((title or "").split()) <= 4 and _canonical_section(title) == canon


def _canonical_section(title: str) -> Optional[str]:
    t = (title or "").strip().lower()
    if "abstract" in t or t == "summary":
        return "abstract"
    if "introduction" in t or t == "background":
        return "introduction"
    if "result" in t or "finding" in t:
        return "results"
    if "method" in t or "materials" in t or "procedure" in t or "experimental" in t or "study design" in t:
        return "methods"
    if "discussion" in t or "conclusion" in t:
        return "discussion"
    if "supplementary" in t or "supplemental" in t or "supporting information" in t:
        return "supplementary"
    if t in {"references", "reference", "bibliography", "literature cited",
             "cited literature", "works cited", "citations", "citation list",
             "reference list", "list of references", "sources",
             "notes and references", "endnotes", "footnotes"}:
        return "references"
    return None


def _parse_xml(xml_text: str):
    parser = etree.XMLParser(recover=True, huge_tree=True)
    return etree.fromstring(xml_text.encode("utf-8"), parser=parser)


def _is_named(node, names: Union[str, set[str]]) -> bool:
    if not isinstance(getattr(node, "tag", None), str):
        return False
    wanted = {names} if isinstance(names, str) else names
    return etree.QName(node).localname in wanted


def _direct_child(node, name: str):
    for child in node:
        if _is_named(child, name):
            return child
    return None


def _descendants(node, name: str) -> list:
    return node.xpath(f'.//*[local-name()="{name}"]')


def _first_descendant(node, name: str):
    matches = _descendants(node, name)
    return matches[0] if matches else None


def _text_content(node) -> str:
    if node is None:
        return ""
    return _clean_text(" ".join(t.strip() for t in node.itertext() if t and t.strip()))


def _nearest_ancestor(node, names: Union[str, set[str]]):
    parent = node.getparent()
    while parent is not None:
        if _is_named(parent, names):
            return parent
        parent = parent.getparent()
    return None


def _has_ancestor(node, names: Union[str, set[str]]) -> bool:
    return _nearest_ancestor(node, names) is not None


def _table_body_text(table_wrap) -> str:
    table_parts = [_text_content(table) for table in _descendants(table_wrap, "table")]
    table_parts = [part for part in table_parts if part]
    return " ".join(table_parts)


def _primary_abstracts(root) -> list:
    abstracts = _descendants(root, "abstract")
    if not abstracts:
        return []
    untyped = [a for a in abstracts if not (a.get("abstract-type") or "").strip()]
    if untyped:
        return untyped
    canonical = [
        a for a in abstracts
        if (a.get("abstract-type") or "").strip().lower() in {"abstract", "summary"}
    ]
    return canonical or abstracts[:1]


def _extract_figure_caption_parts(tag) -> tuple[str, str]:
    """Return (title, body) from a JATS <caption> element.

    In JATS XML the <caption> element contains an optional <title> (the short
    figure heading) followed by the legend content — <p> tags, lists, notes,
    inline markup, etc. There is no <legend> element in JATS; all legend text
    lives inside <caption>.

    We extract the title separately and then collect ALL remaining caption
    content (not just <p> tags) so nothing is dropped.
    """
    cap = _first_descendant(tag, "caption")
    if cap is None:
        return "", ""
    title_tag = _direct_child(cap, "title")
    title = _text_content(title_tag)
    # Collect text from every child element except the <title> tag so that
    # lists, notes, and other non-<p> markup are included.
    body_parts = [
        _text_content(child)
        for child in cap
        if child is not title_tag and isinstance(getattr(child, "tag", None), str)
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
    if not xml_text.strip():
        return ""

    root = _parse_xml(xml_text)
    if root is None:
        return ""
    section_records: list[tuple[int, str, str, str]] = []
    order = 0

    # Abstract often sits outside <sec>.
    for abstract in _primary_abstracts(root):
        para = [_text_content(p) for p in _descendants(abstract, "p")]
        para = [p for p in para if p]
        if not para:
            raw = _text_content(abstract)
            if raw:
                para = [raw]
        if para:
            section_records.append((order, "abstract", "Abstract", "\n".join(para)))
            order += 1

    # Walk all sections in document order across the entire paper.
    body_sections: list = _descendants(root, "sec")

    for sec in body_sections:
        title_tag = _direct_child(sec, "title")
        sec_title = _text_content(title_tag)
        sec_type = sec.get("sec-type") or ""
        header = sec_title or sec_type or "Section"

        # Determine canonical section type; if unrecognized, inherit from the
        # nearest ancestor <sec> so subsections of Results/Methods are included.
        canon = _canonical_section(sec_title) or _canonical_section(sec_type)
        if canon is None:
            ancestor = sec.getparent()
            while ancestor is not None:
                if not _is_named(ancestor, "sec"):
                    ancestor = ancestor.getparent()
                    continue
                anc_title_tag = _direct_child(ancestor, "title")
                anc_title = _text_content(anc_title_tag)
                anc_canon = _canonical_section(anc_title) or _canonical_section(ancestor.get("sec-type") or "")
                if anc_canon is not None:
                    canon = anc_canon
                    break
                ancestor = ancestor.getparent()
        if canon is None and _nearest_ancestor(sec, "sec") is None:
            # Some journals (notably Science) do not wrap main findings in a
            # parent "Results" section; instead each result heading is a
            # top-level body <sec> with generic sec-types like "subjects" or
            # "other1". Treat these as Results unless the title matched a more
            # specific canonical section above.
            canon = "results"

        paragraphs: list[str] = []
        for p in _descendants(sec, "p"):
            # Skip p-tags nested inside figure/table nodes and keep only p for this exact sec.
            if _has_ancestor(p, {"fig", "table-wrap"}):
                continue
            if _nearest_ancestor(p, "sec") is not sec:
                continue
            txt = _strip_extended_data_refs(_text_content(p))
            if txt:
                paragraphs.append(txt)
        if not paragraphs:
            # Keep header-only entries for recognized sections so e.g. "Results"
            # appears as a label even when all content lives in child subsections.
            if canon in {"abstract", "results", "methods"}:
                section_records.append((order, canon, str(header), ""))
                order += 1
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

    section_blocks: list[str] = []
    seen_section_bodies: set[str] = set()
    has_results = False
    for _, canon, header, body in ordered_sections:
        normalized = _clean_text(body)
        if normalized in seen_section_bodies:
            continue
        if normalized:
            seen_section_bodies.add(normalized)
        section_blocks.append(f"## {header}\n{body}".rstrip())
        if canon == "results":
            has_results = True

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

    for fig in _descendants(root, "fig"):
        label_tag = _first_descendant(fig, "label")
        label = _text_content(label_tag) if label_tag is not None else "Figure"
        if "extended data" in label.lower():
            continue
        cap_title, cap_body = _extract_figure_caption_parts(fig)
        _append_fig_block(label, cap_title, cap_body)

    # Supplementary materials with captions (not already inside a <fig>).
    for supp in _descendants(root, "supplementary-material"):
        if _has_ancestor(supp, "fig"):
            continue
        label_tag = _first_descendant(supp, "label")
        label = _text_content(label_tag) if label_tag is not None else "Supplementary"
        cap_title, cap_body = _extract_figure_caption_parts(supp)
        if cap_title or cap_body:
            _append_fig_block(label, cap_title, cap_body)

    has_figures = bool(fig_blocks)

    # ── Tables ───────────────────────────────────────────────────────────────
    tbl_blocks: list[str] = []
    seen_tbl: set = set()

    for wrap in _descendants(root, "table-wrap"):
        label_tag = _first_descendant(wrap, "label")
        label = _text_content(label_tag) if label_tag is not None else "Table"
        cap_title, cap_body = _extract_figure_caption_parts(wrap)
        table_body = _table_body_text(wrap)
        key = (label, cap_title, cap_body, table_body)
        if key in seen_tbl or not (label or cap_title or cap_body):
            continue
        seen_tbl.add(key)
        lines = [f"[{label}]"]
        if cap_title:
            lines.append(f"  Title: {cap_title}")
        if cap_body:
            lines.append(f"  Caption: {cap_body}")
        if table_body:
            lines.append(f"  Body: {table_body}")
        tbl_blocks.append("\n".join(lines))

    # ── Fallback ─────────────────────────────────────────────────────────────
    # Trigger fallback if any of results, methods, or figures are missing.
    # Strip references, supplementary, discussion, acknowledgments, and
    # introduction before sending the remaining full text to the LLM.
    has_dedicated_results = any(
        rec[1] == "results" and _is_dedicated_section_header(rec[2], "results")
        for rec in section_records
    )
    has_dedicated_methods = any(
        rec[1] == "methods" and _is_dedicated_section_header(rec[2], "methods")
        for rec in section_records
    )
    if not has_dedicated_results or not has_dedicated_methods or not has_figures:
        _FALLBACK_EXCLUDED_CANON = {
            "references", "supplementary", "discussion", "introduction",
        }
        fallback_blocks: list[str] = []

        # Abstract from article-meta (outside body).
        # If the abstract has labeled subsections (structured abstract), emit each
        # with its title so the LLM gets Context / Objective / Methods / Results headers.
        for abstract in _primary_abstracts(root):
            secs = _descendants(abstract, "sec")
            if secs:
                for sec in secs:
                    title_tag = _direct_child(sec, "title")
                    sec_title = _text_content(title_tag)
                    paras = [_text_content(p) for p in _descendants(sec, "p")]
                    paras = [p for p in paras if p]
                    if paras:
                        header = sec_title or "Abstract"
                        fallback_blocks.append(f"## {header}\n" + "\n".join(paras))
            else:
                para = [_text_content(p) for p in _descendants(abstract, "p")]
                para = [p for p in para if p]
                if not para:
                    raw = _text_content(abstract)
                    if raw:
                        para = [raw]
                if para:
                    fallback_blocks.append("## Abstract\n" + "\n".join(para))

        # Walk all body <sec> nodes, emit ## Title + paragraphs.
        # Skip: <sec> inside <abstract> (already handled above), excluded canon types,
        # and children of already-excluded sections.
        excluded_ids: set = set()
        for sec in _descendants(root, "sec"):
            # Skip abstract subsections — abstract is handled separately above.
            if _has_ancestor(sec, "abstract"):
                continue
            # Skip if an ancestor section was excluded.
            if any(id(sec) == eid for eid in excluded_ids):
                continue
            node = sec.getparent()
            skip = False
            while node is not None:
                if id(node) in excluded_ids:
                    skip = True
                    break
                node = node.getparent()
            if skip:
                continue

            title_tag = _direct_child(sec, "title")
            sec_title = _text_content(title_tag)
            sec_type = sec.get("sec-type") or ""
            canon = _canonical_section(sec_title) or _canonical_section(sec_type)
            if canon in _FALLBACK_EXCLUDED_CANON:
                excluded_ids.add(id(sec))
                continue

            paragraphs = []
            for p in _descendants(sec, "p"):
                if _has_ancestor(p, {"fig", "table-wrap"}):
                    continue
                if _nearest_ancestor(p, "sec") is not sec:
                    continue
                txt = _strip_extended_data_refs(_text_content(p))
                if txt:
                    paragraphs.append(txt)
            if paragraphs:
                header = sec_title or sec_type or "Section"
                fallback_blocks.append(f"## {header}\n" + "\n".join(paragraphs))

        # Figures (skip Extended Data figures).
        fig_lines = []
        for fig in _descendants(root, "fig"):
            label_tag = _first_descendant(fig, "label")
            label = _text_content(label_tag) if label_tag is not None else "Figure"
            if "extended data" in label.lower():
                continue
            cap_title, cap_body = _extract_figure_caption_parts(fig)
            if label or cap_title or cap_body:
                lines = [f"[{label}]"]
                if cap_title:
                    lines.append(f"  Title: {cap_title}")
                if cap_body:
                    lines.append(f"  Caption: {cap_body}")
                fig_lines.append("\n".join(lines))
        if fig_lines:
            fallback_blocks.append("--- Figures ---\n" + "\n\n".join(fig_lines))

        return _truncate_blocks(fallback_blocks, MAX_PAPER_CHARS)

    blocks = list(section_blocks)
    if fig_blocks:
        blocks.append("--- Figures ---\n" + "\n\n".join(fig_blocks))
    if tbl_blocks:
        blocks.append("--- Tables ---\n" + "\n\n".join(tbl_blocks))

    return _truncate_blocks(blocks, MAX_PAPER_CHARS)
