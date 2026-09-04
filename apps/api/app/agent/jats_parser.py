"""Parse JATS XML from PubMed Central into structured plain text for LLM consumption."""

import re
from typing import Optional, Union

from lxml import etree

MAX_PAPER_CHARS = 120000

_EXCLUDED_CONTAINER_TAGS = {"ref-list", "supplementary-material"}
_EXCLUDED_EXACT_SECTION_LABELS = {
    "access options",
    "acknowledgement",
    "acknowledgements",
    "acknowledgment",
    "acknowledgments",
    "affiliations",
    "article metrics",
    "author contributions",
    "author contribution statement",
    "authors contributions",
    "background",
    "bibliography",
    "citation",
    "citation list",
    "citations",
    "code availability",
    "competing interest",
    "competing interests",
    "competing financial interests",
    "conclusion",
    "conclusions",
    "concluding remarks",
    "conflict of interest",
    "conflicts of interest",
    "consent for publication",
    "consent to participate",
    "contributions",
    "correspondence",
    "correspondence and requests for materials",
    "corresponding author",
    "data and materials availability",
    "data availability",
    "data sharing statement",
    "declaration of interests",
    "disclosure statement",
    "discussion",
    "discussion and conclusions",
    "discussions",
    "endnotes",
    "ethical approval",
    "introduction",
    "intro",
    "ethics approval",
    "ethics declarations",
    "footnotes",
    "financial support",
    "funding",
    "funding information",
    "grant support",
    "literature cited",
    "metrics",
    "publisher note",
    "publisher notes",
    "publisher s note",
    "reference",
    "reference list",
    "references",
    "similar articles",
    "software availability",
    "sources",
    "summary and conclusions",
    "supplemental information",
    "supplementary material",
    "supplementary materials",
    "supplementary information",
    "supplementary data",
    "supporting information",
    "works cited",
}
_EXCLUDED_SECTION_PHRASES = {
    "additional file",
    "additional information",
    "author contribution",
    "authors contribution",
    "author information",
    "availability of code",
    "availability of data",
    "availability of data and materials",
    "cite this article",
    "competing financial interests",
    "correspondence and requests",
    "declaration of competing interest",
    "declaration of interests",
    "declarations of interest",
    "ethics declarations",
    "list of references",
    "notes and references",
    "publisher s note",
    "rights and permissions",
}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_text(text).lower()).strip()


def _is_excluded_section_label(text: str) -> bool:
    label = _normalize_label(text)
    if not label:
        return False
    if "result" in label and "discussion" in label:
        return False
    if label in _EXCLUDED_EXACT_SECTION_LABELS:
        return True
    if "supplementary" in label or "supplemental" in label or "supporting information" in label:
        return True
    if label.startswith(("discussion", "conclusion", "references", "introduction")):
        return True
    if "data" in label and "availability" in label:
        return True
    if "code" in label and "availability" in label:
        return True
    if label.startswith("additional file"):
        return True
    return any(phrase in label for phrase in _EXCLUDED_SECTION_PHRASES)


def _strip_extended_data_refs(text: str) -> str:
    """Remove parenthetical Extended Data references from paragraph text."""
    text = re.sub(r"\(\s*Extended Data[^)]*\)", "", text)
    text = re.sub(r",?\s*Extended Data\s+(?:Fig|Table)s?\.?\s*[\w\d,\s–\-]+", "", text)
    return re.sub(r"\s+", " ", text).strip()



def _canonical_section(title: str) -> Optional[str]:
    t = (title or "").strip().lower()
    if "abstract" in t or t == "summary":
        return "abstract"
    if "introduction" in t or t == "background":
        return "introduction"
    if "supplementary" in t or "supplemental" in t or "supporting information" in t:
        return "supplementary"
    if "result" in t or "finding" in t:
        return "results"
    if "method" in t or "materials" in t or "procedure" in t or "experimental" in t or "study design" in t:
        return "methods"
    if "discussion" in t or "conclusion" in t:
        return "discussion"
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


def _section_header(sec) -> str:
    title_tag = _direct_child(sec, "title")
    sec_title = _text_content(title_tag)
    sec_type = sec.get("sec-type") or ""
    return sec_title or sec_type or "Section"


def _is_excluded_sec(sec) -> bool:
    title_tag = _direct_child(sec, "title")
    sec_title = _text_content(title_tag)
    sec_type = sec.get("sec-type") or ""
    return (
        _is_excluded_section_label(sec_title)
        or _is_excluded_section_label(sec_type)
    )


def _is_in_excluded_container(node) -> bool:
    current = node
    while current is not None:
        if _is_named(current, _EXCLUDED_CONTAINER_TAGS):
            return True
        if _is_named(current, "sec") and _is_excluded_sec(current):
            return True
        current = current.getparent()
    return False


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

    # Walk article body/back sections in document order. Abstract sections are
    # handled above, so collecting from these containers avoids duplicating
    # structured abstract subsections as regular body sections.
    section_containers = _descendants(root, "body") + _descendants(root, "back")
    body_sections = [
        sec
        for container in section_containers
        for sec in _descendants(container, "sec")
    ]

    for sec in body_sections:
        if _has_ancestor(sec, "abstract"):
            continue
        if _is_in_excluded_container(sec):
            continue

        header = _section_header(sec)
        sec_title = _text_content(_direct_child(sec, "title"))
        sec_type = sec.get("sec-type") or ""

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
        if canon is None:
            canon = "other"

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
            # Keep header-only entries so parent section labels are preserved
            # when all content lives in child subsections.
            if _direct_child(sec, "sec") is not None or canon in {"abstract", "results", "methods"}:
                section_records.append((order, canon, str(header), ""))
                order += 1
            continue
        section_records.append((order, canon, str(header), "\n".join(paragraphs)))
        order += 1

    section_blocks: list[str] = []
    for _, canon, header, body in section_records:
        section_blocks.append(f"## {header}\n{body}".rstrip())

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
        if _is_in_excluded_container(fig):
            continue
        label_tag = _first_descendant(fig, "label")
        label = _text_content(label_tag) if label_tag is not None else "Figure"
        if "extended data" in label.lower():
            continue
        cap_title, cap_body = _extract_figure_caption_parts(fig)
        _append_fig_block(label, cap_title, cap_body)

    # ── Tables ───────────────────────────────────────────────────────────────
    tbl_blocks: list[str] = []
    seen_tbl: set = set()

    for wrap in _descendants(root, "table-wrap"):
        if _is_in_excluded_container(wrap):
            continue
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

    blocks = list(section_blocks)
    if fig_blocks:
        blocks.append("--- Figures ---\n" + "\n\n".join(fig_blocks))
    if tbl_blocks:
        blocks.append("--- Tables ---\n" + "\n\n".join(tbl_blocks))

    return _truncate_blocks(blocks, MAX_PAPER_CHARS)


# ── Sentence numbering ────────────────────────────────────────────────────────
#
# Lives here rather than in .claude/skills/extract-assay-methods/scripts/jats_to_text.py,
# where it was written, because the HTTP route and the assay passes both need it and
# apps/api must not import from .claude/skills. The skill script now imports it from here,
# which is the direction that already holds: skill scripts import this package.
#
# Numbering is lossless -- deleting every `[S<n>] ` marker restores the parser's output byte
# for byte, which is what makes an extracted quote checkable against the source.

import itertools as _itertools

#: Abbreviations whose trailing period does not end a sentence, plus a single capital letter
#: (initials, and the "Inc." / "Fig." style already covered by name).
_ABBREVIATIONS = (
    r"(?<!\bi\.e)(?<!\be\.g)(?<!\bvs)(?<!\bFig)(?<!\bcf)(?<!\bca)(?<!\bno)(?<!\bDr)"
    r"(?<!\bInc)(?<!\bLtd)(?<!\bCo)(?<!\bet al)(?<!\bapprox)(?<!\bref)(?<!\bcat)"
    r"(?<!\bver)(?<!\bMr)(?<!\bSt)(?<![A-Z])"
)

#: Matches the whitespace separating two sentences. The lookahead is `[^\s]` rather than
#: `[A-Z]` on purpose: scientific sentences routinely open lowercase ("cRNA was
#: hybridized...", "mRNA levels...", "pH was..."), and requiring a capital silently glues
#: them onto the previous sentence.
SENTENCE_SPLIT = re.compile(_ABBREVIATIONS + r"(?<=[.!?])\s+(?=[^\s])")

#: `Title:`/`Caption:`/`Body:` prefix on a figure or table line -- the label is scaffolding,
#: the text after it is quotable content.
_CAPTION_FIELD = re.compile(r"^(\s*(?:Title|Caption|Body):\s*)(.*)$")

#: Structural lines that carry no prose: section headings, the figure/table banners, and a
#: bare `[Figure 1]` / `[Table 2]` label.
_STRUCTURAL = re.compile(r"^(?:##\s|---\s|\[[^\]]*\]\s*$)")

SENTENCE_MARKER = re.compile(r"\[S\d+\] ")


def _number_content(content: str, counter) -> str:
    """Insert `[S<n>] ` before each sentence in one line of prose.

    Markers are inserted around the original text rather than derived from splitting and
    rejoining it, so whatever whitespace separated two sentences survives intact and
    strip_sentence_ids() is an exact inverse.
    """
    if not content.strip():
        return content

    start = len(content) - len(content.lstrip())
    parts = [content[:start], f"[S{next(counter)}] "]

    pos = start
    for match in SENTENCE_SPLIT.finditer(content, start):
        parts.append(content[pos:match.end()])
        parts.append(f"[S{next(counter)}] ")
        pos = match.end()
    parts.append(content[pos:])

    return "".join(parts)


def number_sentences(text: str) -> str:
    """Prefix every sentence of prose in the parsed paper with a `[S<n>] ` marker."""
    counter = _itertools.count(1)
    numbered = []

    for line in text.split("\n"):
        if not line.strip() or _STRUCTURAL.match(line):
            numbered.append(line)
            continue

        caption = _CAPTION_FIELD.match(line)
        if caption:
            label, content = caption.groups()
            numbered.append(label + _number_content(content, counter))
        else:
            numbered.append(_number_content(line, counter))

    return "\n".join(numbered)


def strip_sentence_ids(text: str) -> str:
    """Inverse of number_sentences() -- used to check a quote against the raw parse."""
    return SENTENCE_MARKER.sub("", text)


def article_title(xml_text: Union[str, bytes]) -> Optional[str]:
    """The paper's title from JATS `<article-title>`, or None.

    Read from the XML rather than from parse_jats_xml's output, which carries no title at
    all -- its first line is `## Abstract`. Callers that guessed "the first line that is not
    a heading" were therefore handing whole abstracts to prompts as the paper's name.
    """
    try:
        root = etree.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except etree.XMLSyntaxError:
        return None

    node = root.find(".//front//article-meta//article-title")
    if node is None:
        node = root.find(".//article-title")
    if node is None:
        return None
    return " ".join("".join(node.itertext()).split()) or None
