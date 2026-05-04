"""Parse PMC JATS XML into semantic blocks with rich provenance metadata."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

MAX_PAPER_CHARS = 120_000

CLAIM_PRIORITY: dict[str, str] = {
    "results_like":    "highest",
    "figure_legend":   "highest",
    "table_caption":   "highest",
    "abstract":        "medium",
    "methods_like":    "medium",
    "body_section":    "medium",
    "supplementary":   "exclude",
    "discussion_like": "exclude",
    "introduction":    "exclude",
    # boilerplate — stripped before the LLM sees the paper
    "acknowledgments":     "exclude",
    "author_contributions": "exclude",
    "funding":             "exclude",
    "competing_interests": "exclude",
    "data_availability":   "exclude",
    "code_availability":   "exclude",
    "ethics_only":         "exclude",
    "rights_permissions":  "exclude",
}

# Standardised JATS sec-type values we trust unambiguously
_SECTYPE_RESULTS    = {"results", "results-section"}
_SECTYPE_METHODS    = {"methods", "materials", "materials-methods", "methods-section"}
_SECTYPE_DISCUSSION = {"discussion", "conclusions", "conclusion"}
_SECTYPE_INTRO      = {"intro", "introduction"}
_SECTYPE_EXCLUDE    = {
    "acknowledgments": "acknowledgments",
    "acknowledgements": "acknowledgments",
    "data-availability": "data_availability",
}

# Title substrings we trust for semantic labels
_TITLE_RESULTS       = ("result",)
_TITLE_METHODS       = ("method", "material")
_TITLE_DISCUSSION    = ("discussion", "conclusion")
_TITLE_INTRO         = ("introduction",)
_TITLE_SUPPLEMENTARY = ("supplementary", "supporting information", "supplemental")

# Title substrings for exclude labels
_TITLE_EXCLUDE: list[tuple[str, str]] = [
    ("acknowledgment",    "acknowledgments"),
    ("acknowledgement",   "acknowledgments"),
    ("author contribution", "author_contributions"),
    ("conflict of interest", "competing_interests"),
    ("competing interest",   "competing_interests"),
    ("data avail",           "data_availability"),   # catches "data availability", "data and software availability"
    ("code avail",           "code_availability"),   # catches "code availability statement"
    ("software avail",       "data_availability"),   # catches "software availability"
    ("funding",              "funding"),
    ("financial support",    "funding"),
    ("ethic",                "ethics_only"),
    ("copyright",            "rights_permissions"),
    ("rights and permission", "rights_permissions"),
    ("extended data",        "data_availability"),
]


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    clipped = value[:limit]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped


def _extract_caption_parts(tag) -> tuple[str, str]:
    cap = tag.find("caption")
    if not cap:
        return "", ""
    title_tag = cap.find("title")
    title = clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
    body_parts = [
        clean_text(child.get_text(" ", strip=True))
        for child in cap.children
        if child is not title_tag and hasattr(child, "get_text")
    ]
    body = " ".join(p for p in body_parts if p)
    return title, body


def _location_of(tag) -> str:
    for ancestor in tag.parents:
        if ancestor.name in ("front", "article-meta"):
            return "front"
        if ancestor.name == "body":
            return "body"
        if ancestor.name == "back":
            return "back"
        if ancestor.name == "floats-group":
            return "floats"
    return "body"


def _make_label(label: str, confidence: float) -> dict:
    return {
        "semantic_labels": {label: confidence},
        "primary_label": label,
        "primary_label_confidence": confidence,
        "claim_priority": CLAIM_PRIORITY.get(label, "medium"),
    }


def _results_is_first_word(t: str) -> bool:
    """Return True if 'result' or 'results' is the first word after stripping leading section numbers."""
    t = re.sub(r'^\d+(\.\d+)*\.?\s*', '', t).strip()
    first = t.split()[0] if t.split() else ""
    return first in ('result', 'results')


def _label_block(tag_type: str, title: str, sec_type: str, location: str, parent_title: str) -> dict:
    """Assign a label only when the signal is unambiguous. Everything else → body_section."""
    t  = (title    or "").strip().lower()
    st = (sec_type or "").strip().lower()

    # 1. tag_type is definitive — no guessing needed
    if tag_type == "abstract":       return _make_label("abstract",       1.0)
    if tag_type == "figure_legend":  return _make_label("figure_legend",  1.0)
    if tag_type == "table_caption":  return _make_label("table_caption",  1.0)
    if tag_type == "supplementary":  return _make_label("supplementary",  1.0)

    # 2. Exclude boilerplate via sec-type
    if st in _SECTYPE_EXCLUDE:
        return _make_label(_SECTYPE_EXCLUDE[st], 1.0)

    # 3. Exclude boilerplate via title keywords (checked before semantic labels
    #    so "Funding and acknowledgments" doesn't get scored as something else)
    for kw, lbl in _TITLE_EXCLUDE:
        if kw in t:
            return _make_label(lbl, 1.0)

    # 4. Semantic labels — standardised sec-type takes priority over title keywords
    if st in _SECTYPE_RESULTS:    return _make_label("results_like",    1.0)
    if st in _SECTYPE_METHODS:    return _make_label("methods_like",    1.0)
    if st in _SECTYPE_DISCUSSION: return _make_label("discussion_like", 1.0)
    if st in _SECTYPE_INTRO:      return _make_label("introduction",    1.0)

    if _results_is_first_word(t):                  return _make_label("results_like",    0.9)
    if any(kw in t for kw in _TITLE_METHODS):    return _make_label("methods_like",    0.9)
    if any(kw in t for kw in _TITLE_DISCUSSION): return _make_label("discussion_like", 0.9)
    if any(kw in t for kw in _TITLE_INTRO):      return _make_label("introduction",    0.9)
    if t == "background":                         return _make_label("introduction",    0.9)

    # 5. Supplementary by title keyword (top-level "Supporting information" sections)
    if any(kw in t for kw in _TITLE_SUPPLEMENTARY): return _make_label("supplementary", 0.9)

    # 6. Inherit label from parent section title (covers numbered subsections
    #    like "2.1. Study Cohort" whose parent is "2. Materials and Methods")
    pt = (parent_title or "").strip().lower()
    if _results_is_first_word(pt):                 return _make_label("results_like",    0.8)
    if any(kw in pt for kw in _TITLE_METHODS):    return _make_label("methods_like",    0.8)
    if any(kw in pt for kw in _TITLE_DISCUSSION): return _make_label("discussion_like", 0.8)
    if any(kw in pt for kw in _TITLE_INTRO):      return _make_label("introduction",    0.8)

    # 7. Everything else — honest fallback
    return _make_label("body_section", 0.5)


# Maps title keywords → canonical sec-type, used when the attribute is absent
_TITLE_TO_SECTYPE: dict[str, str] = {
    "result":       "results",
    "method":       "methods",
    "material":     "materials",
    "discussion":   "discussion",
    "conclusion":   "conclusions",
    "introduction": "intro",
    "background":   "intro",
}


def _resolve_sec_type(sec) -> str:
    """Return an effective sec-type by walking up the <sec> ancestry.

    Checks, in order for each node:
      1. The explicit sec-type attribute.
      2. A sec-type inferred from the section's title keywords.
    This lets subsections (which rarely carry sec-type) inherit from their
    parent sections even when the parent has no sec-type attribute.
    """
    node = sec
    while node is not None:
        st = node.get("sec-type", "")
        if st:
            return st
        title_tag = node.find("title", recursive=False)
        if title_tag:
            t = title_tag.get_text(" ", strip=True).lower()
            if _results_is_first_word(t):
                return "results"
            for kw, inferred in _TITLE_TO_SECTYPE.items():
                if kw == "result":
                    continue  # handled above with stricter regex
                if kw in t:
                    return inferred
        node = node.find_parent("sec")
    return ""


def extract_paper_blocks(soup: BeautifulSoup) -> list[dict]:
    """Extract all content blocks in document order. Exclude-priority blocks are dropped."""
    pos_map = {id(tag): i for i, tag in enumerate(soup.descendants)}
    raw_blocks: list[dict] = []
    seen_texts: set[str] = set()
    counter = 0

    def _emit(tag_type, title, parent_title, sec_type, location, text, xrefs, anchor):
        nonlocal counter
        norm = clean_text(text)
        if not norm or norm in seen_texts:
            return
        seen_texts.add(norm)
        label_info = _label_block(tag_type, title, sec_type, location, parent_title)
        if label_info["claim_priority"] == "exclude":
            return
        raw_blocks.append({
            "block_id":    f"{tag_type}_{counter}",
            "tag_type":    tag_type,
            "title":       title,
            "parent_title": parent_title,
            "location":    location,
            "text":        norm,
            "order":       pos_map.get(id(anchor), counter * 10_000),
            "xref_targets": [r for r in xrefs if r],
            "char_count":  len(norm),
            **label_info,
        })
        counter += 1

    # Abstract
    for abstract in soup.find_all("abstract"):
        paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in abstract.find_all("p")]
        paragraphs = [p for p in paragraphs if p]
        if not paragraphs:
            raw = clean_text(abstract.get_text(" ", strip=True))
            if raw:
                paragraphs = [raw]
        if paragraphs:
            xrefs = [x.get("rid", "") for x in abstract.find_all("xref")]
            _emit("abstract", "Abstract", "", "", "front", "\n".join(paragraphs), xrefs, abstract)

    # Sections
    for sec in soup.find_all("sec"):
        title_tag  = sec.find("title", recursive=False)
        sec_title  = clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
        header     = sec_title or sec.get("sec-type") or ""
        sec_type   = _resolve_sec_type(sec)
        location   = _location_of(sec)

        parent_sec   = sec.find_parent("sec")
        parent_title = ""
        if parent_sec:
            pt = parent_sec.find("title", recursive=False)
            parent_title = clean_text(pt.get_text(" ", strip=True)) if pt else ""

        paragraphs: list[str] = []
        xrefs: list[str] = []
        for p in sec.find_all("p"):
            if p.find_parent(["fig", "table-wrap"]) is not None:
                continue
            if p.find_parent("sec") is not sec:
                continue
            txt = clean_text(p.get_text(" ", strip=True))
            if txt:
                paragraphs.append(txt)
            xrefs.extend(x.get("rid", "") for x in p.find_all("xref"))

        if paragraphs:
            _emit("sec_paragraph", header, parent_title, sec_type, location,
                  "\n".join(paragraphs), xrefs, sec)

    # Figures
    seen_fig: set[tuple] = set()
    for fig in soup.find_all("fig"):
        label_tag = fig.find("label")
        label     = clean_text(label_tag.get_text(" ", strip=True)) if label_tag else "Figure"
        fig_title, caption = _extract_caption_parts(fig)
        text = " ".join(p for p in [fig_title, caption] if p)
        key  = (label, text)
        if key in seen_fig or not text:
            continue
        if "extended data" in label.lower():
            continue
        seen_fig.add(key)
        xrefs = [x.get("rid", "") for x in fig.find_all("xref")]
        _emit("figure_legend", label, "", "", _location_of(fig), text, xrefs, fig)

    # Tables
    seen_tbl: set[tuple] = set()
    for table in soup.find_all("table-wrap"):
        label_tag = table.find("label")
        label     = clean_text(label_tag.get_text(" ", strip=True)) if label_tag else "Table"
        tbl_title, caption = _extract_caption_parts(table)
        text = " ".join(p for p in [tbl_title, caption] if p)
        key  = (label, text)
        if key in seen_tbl or not text:
            continue
        if "extended data" in label.lower():
            continue
        seen_tbl.add(key)
        xrefs = [x.get("rid", "") for x in table.find_all("xref")]
        _emit("table_caption", label, "", "", _location_of(table), text, xrefs, table)

    # Supplementary material
    for supp in soup.find_all("supplementary-material"):
        if supp.find_parent("fig") is not None:
            continue
        label_tag = supp.find("label")
        label     = clean_text(label_tag.get_text(" ", strip=True)) if label_tag else "Supplementary"
        supp_title, caption = _extract_caption_parts(supp)
        text = " ".join(p for p in [supp_title, caption] if p)
        if not text:
            text = clean_text(supp.get_text(" ", strip=True))
        if text:
            _emit("supplementary", label, "", "", _location_of(supp), text, [], supp)

    raw_blocks.sort(key=lambda b: b["order"])
    for i, b in enumerate(raw_blocks):
        b["order"] = i

    return raw_blocks


def _extract_references(soup: BeautifulSoup) -> list[str]:
    refs: list[str] = []
    for ref in soup.find_all("ref"):
        text = clean_text(ref.get_text(" ", strip=True))
        if text:
            refs.append(text)
    return refs


def _has_sufficient_coverage(blocks: list[dict]) -> bool:
    """Return True only if results, figures/tables, and methods are all present.

    All three must exist — if any one is missing, the structured parse is
    considered incomplete and the caller should fall back to raw text.
    """
    labels = {b["primary_label"] for b in blocks}
    has_results  = "results_like" in labels
    has_figures  = bool(labels & {"figure_legend", "table_caption"})
    has_methods  = "methods_like" in labels
    return has_results and has_figures and has_methods


def _strip_excluded_secs(soup: BeautifulSoup) -> None:
    """Decompose exclude-priority <sec> tags in-place before fallback text extraction.

    Walks top-down so that decomposing a parent automatically removes its children,
    avoiding double-decompose errors on already-removed tags.
    """
    to_remove = []
    removed_ids: set[int] = set()
    for sec in soup.find_all("sec"):
        if id(sec) in removed_ids:
            continue
        title_tag = sec.find("title", recursive=False)
        sec_title = clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
        sec_type = _resolve_sec_type(sec)
        location = _location_of(sec)
        label_info = _label_block("sec_paragraph", sec_title, sec_type, location, "")
        if label_info["claim_priority"] == "exclude":
            # mark all descendants so we skip them in the loop
            for child in sec.find_all("sec"):
                removed_ids.add(id(child))
            to_remove.append(sec)
    for sec in to_remove:
        sec.decompose()


def parse_jats_xml_to_json(xml_text: str) -> dict:
    """Parse JATS XML into semantic blocks with rich provenance metadata."""
    soup = BeautifulSoup(xml_text, "xml")

    references = _extract_references(soup)
    for ref_list in soup.find_all("ref-list"):
        ref_list.decompose()

    blocks = extract_paper_blocks(soup)
    use_blocks = bool(blocks) and _has_sufficient_coverage(blocks)
    raw_text = ""
    if not use_blocks:
        _strip_excluded_secs(soup)
        raw_text = _truncate_text(clean_text(soup.get_text(separator=" ", strip=True)), MAX_PAPER_CHARS)

    return {
        "parse_mode": "blocks" if use_blocks else "fallback",
        "blocks":     blocks if use_blocks else [],
        "references": references,
        "raw_text":   raw_text,
    }
