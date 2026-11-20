"""A paper's supplementary files: what the JATS XML lists, how to fetch them, and their text.

The assay chain reads the main text only. jats_parser drops `<supplementary-material>` on
purpose, and what it drops is a file name and a caption, never the supplement's prose -- so a
method described only in a supplement has never reached the extractor. This module gets that
prose: it lists the files a paper's XML names, unpacks the archive Europe PMC serves for the
paper, reads the PDFs and .docx files in it, and renders the text in the same shape
parse_jats_xml produces (`## heading  [bucket]` blocks, `[S<n>]` sentence markers), so every
pass of the chain can read a supplement exactly as it reads a paper.

Nothing here calls a model. Network access is one GET per paper, made by the script that
drives this module (scripts/download_paper_supplements.py), not by anything in here.
"""

import io
import re
import zipfile
from pathlib import Path

from lxml import etree

from app.agent.jats_parser import MAX_PAPER_CHARS, number_sentences
from app.agent.paper_reader import extract_pdf_text

_REPO_ROOT = Path(__file__).resolve().parents[4]
#: `<SDY>_<pmid>/files/` holds what was downloaded, `<SDY>_<pmid>/supplement.txt` the rendered
#: text. Named like the XML (`<SDY>_<pmid>`), since that is what a supplement belongs to.
SUPPLEMENT_ROOT = _REPO_ROOT / "data" / "supplements"

#: One zip of every supplementary file of an article. Measured 2026-11-13 on PMC5583508: this
#: answers 200 where PMC's own `/articles/<PMCID>/bin/<href>` and the OA service answer 404.
EPMC_SUPPLEMENT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles"

_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"

#: No single member of a supplement archive is read past this; a larger one is a dataset.
MAX_MEMBER_BYTES = 200 * 1024 * 1024

_TEXT_KINDS = {"pdf", "docx"}
_KIND_BY_SUFFIX = {
    ".pdf": "pdf", ".docx": "docx", ".doc": "doc",
    ".xlsx": "table", ".xls": "table", ".csv": "table", ".tsv": "table", ".txt": "table",
    ".zip": "archive", ".gz": "archive", ".tar": "archive",
    ".jpg": "image", ".jpeg": "image", ".gif": "image", ".png": "image", ".tif": "image",
    ".tiff": "image", ".eps": "image",
    ".pptx": "slides", ".ppt": "slides",
    ".mp4": "video", ".mov": "video", ".avi": "video",
}


def file_kind(name: str) -> str:
    """pdf / docx / doc / table / archive / image / slides / video / other, from the suffix."""
    return _KIND_BY_SUFFIX.get(Path(name).suffix.lower(), "other")


def is_readable(name: str) -> bool:
    """Whether this module can turn the file into text. A legacy .doc is not."""
    return file_kind(name) in _TEXT_KINDS


_ARTICLE_COPY = re.compile(r"article\s+plus\s+supplement", re.IGNORECASE)


def is_article_copy(caption: str) -> bool:
    """Cell Press's "Document S2. Article plus Supplemental Information": the paper itself
    bound with its supplement. Reading it would hand the main text back as supplement."""
    return bool(_ARTICLE_COPY.search(caption or ""))


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _text(node) -> str:
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def _parse(raw: bytes):
    return etree.fromstring(raw, etree.XMLParser(recover=True, resolve_entities=False,
                                                 no_network=True, huge_tree=True))


def pmcid_from_xml(raw: bytes) -> str | None:
    """`PMC1234567` from the article's own `<article-id>`, or None."""
    root = _parse(raw)
    if root is None:
        return None
    for node in root.iter():
        if _local(node.tag) != "article-id":
            continue
        if node.get("pub-id-type") in ("pmc", "pmcid", "pmcaid"):
            digits = re.sub(r"\D", "", _text(node))
            if digits:
                return "PMC" + digits
    return None


def listed_supplements(raw: bytes) -> list[dict]:
    """The supplementary files a JATS XML names: `[{"href", "caption"}]`, in document order.

    Two shapes exist in the corpus. Most publishers wrap each file in
    `<supplementary-material>` with a `<media xlink:href>` inside (or the href on the wrapper
    itself); BMC writes bare `<media>` under an "Additional files" section with no wrapper.
    A wrapper that carries no href at all -- Science's, which only points at the journal's own
    site -- is still listed, with `href` None, because "this paper has a supplement PMC does
    not hold" is exactly what the caller needs to know.
    """
    root = _parse(raw)
    if root is None:
        return []
    found: list[dict] = []
    seen: set[str] = set()

    def _add(href: str | None, caption: str) -> None:
        if href and href in seen:
            return
        if href:
            seen.add(href)
        found.append({"href": href, "caption": caption})

    for node in root.iter():
        name = _local(node.tag)
        if name == "supplementary-material":
            caption = _text(node)
            hrefs = [node.get(_XLINK_HREF)] + [
                child.get(_XLINK_HREF) for child in node.iter() if _local(child.tag) == "media"]
            hrefs = [h for h in hrefs if h]
            if not hrefs:
                _add(None, caption)
            for href in hrefs:
                _add(href, caption)
        elif name == "media":
            if any(_local(parent.tag) == "supplementary-material"
                   for parent in node.iterancestors()):
                continue
            _add(node.get(_XLINK_HREF), _text(node))
    return found


def safe_extract(archive: bytes, dest: Path) -> list[Path]:
    """Unpack a supplement zip into `dest`, flat, and return the files written.

    The archive is untrusted. Every member is written under its base name only, so a path like
    `../../x` or `/etc/x` cannot leave `dest`; directories, empty names and members larger than
    MAX_MEMBER_BYTES are skipped; nothing is executed and no nested archive is opened. A name
    that repeats keeps its first copy.

    A zero-byte member is not written: Europe PMC answers some author manuscripts with an
    archive holding one empty placeholder, and a file with nothing in it is not a download. An
    empty file already at the target is such a placeholder and is replaced.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        for info in bundle.infolist():
            name = Path(info.filename.replace("\\", "/")).name
            if info.is_dir() or not name or name.startswith("."):
                continue
            if info.file_size == 0 or info.file_size > MAX_MEMBER_BYTES:
                continue
            target = dest / name
            if target.exists() and target.stat().st_size > 0:
                continue
            with bundle.open(info) as member:
                target.write_bytes(member.read(MAX_MEMBER_BYTES))
            written.append(target)
    return written


_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(data: bytes) -> str:
    """The paragraphs of a .docx, one per line. Tables come through cell by cell."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            document = bundle.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        return ""
    root = _parse(document)
    if root is None:
        return ""
    lines = []
    for paragraph in root.iter(_W_NS + "p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == _W_NS + "t":
                parts.append(node.text or "")
            elif node.tag in (_W_NS + "tab", _W_NS + "br"):
                parts.append(" ")
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


#: A PDF text layer is cut at this, far above any supplement's prose. What sits past it in
#: practice is hundreds of pages of tables.
_PDF_TEXT_CAP = 2_000_000


def file_text(path: Path) -> str:
    """Plain text of one supplementary file, or "" when it is not a kind this module reads."""
    kind = file_kind(path.name)
    try:
        if kind == "pdf":
            return extract_pdf_text(path.read_bytes(), max_chars=_PDF_TEXT_CAP)
        if kind == "docx":
            return docx_text(path.read_bytes())
    except Exception:  # noqa: BLE001 - a corrupt download is a file with no text, not a crash
        return ""
    return ""


_PREFIX = r"^\s*(?:\d+[.)]?\s+|[IVX]+\.\s+)?"
_SUPP = r"(?:supplement(?:ary|al)|supporting|extended|online|detailed|additional|si)"

#: A line that opens a supplementary methods section. Whole-line and short: the phrase inside a
#: sentence ("as described in Supplementary Methods") or a contents line ("Document S1.
#: Supplemental Experimental Procedures, Figures S1-S6") is a pointer, not a heading.
_METHODS_HEADING = re.compile(
    _PREFIX + r"(?:" + _SUPP + r"\s+)?(?:information\s*[:\-–]?\s*)?(?:" + _SUPP + r"\s+)?"
    r"(?:"
    r"materials?\s+(?:and|&)\s+methods"
    r"|methods(?:\s+(?:and|&)\s+materials?)?"
    r"|methods\s+summary"
    r"|experimental\s+procedures"
    r"|experimental\s+methods"
    r"|methodology"
    r"|notes?(?:\s+\d+)?"
    r"|text(?:\s+S?\d+)?"
    r")\s*[:.]?\s*$",
    re.IGNORECASE,
)

#: A line that closes one: the figures, tables and references that follow the methods in a
#: supplement. Matched at the start of a line of any length, since a legend is one long line.
_OTHER_HEADING = re.compile(
    r"^\s*(?:"
    + _SUPP + r"\s+(?:figures?|figs?\.?|tables?|data(?:sets?)?|references|results|discussion|"
    r"movies?|videos?|files?|legends?)\b"
    r"|(?:figure|fig\.?|table|movie|video|dataset|data\s+file)\s+S?\d+\s*[.:|]"
    r"|(?:figure|fig\.?|table)\s+S\d+\b"
    r"|references?\s*$"
    r"|(?:figure|table)\s+legends?\s*$"
    r")",
    re.IGNORECASE,
)

_MAX_HEADING_CHARS = 90
#: "Supplementary Note" and "Supplementary Text" are only method headings with the qualifier:
#: a bare "Notes" or "Text" line is a table footer or a column header.
_NEEDS_QUALIFIER = re.compile(r"^(?:notes?|text)\b", re.IGNORECASE)


def is_methods_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_CHARS:
        return False
    if not _METHODS_HEADING.match(stripped):
        return False
    bare = re.sub(_PREFIX, "", stripped)
    return not _NEEDS_QUALIFIER.match(bare)


def is_other_heading(line: str) -> bool:
    return bool(_OTHER_HEADING.match(line))


def _join(lines: list[str]) -> str:
    """Reflow hard-wrapped PDF lines into one paragraph, closing a hyphenated line break."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line or line.isdigit():
            # A bare number on its own line is a manuscript line number or a page number.
            continue
        if out.endswith("-") and len(out) > 1 and out[-2].isalpha() and line[0].islower():
            out = out[:-1] + line
        elif out:
            out += " " + line
        else:
            out = line
    return re.sub(r"\s+", " ", out).strip()


def split_blocks(text: str) -> list[dict]:
    """Cut one file's text into `[{"heading", "bucket", "body"}]`, in order.

    A two-state walk over the lines: a methods heading opens a `methods` block, a figure /
    table / references heading opens an `other` block, and every line in between belongs to
    the block that is open. Sub-headings inside the methods ("Flow cytometry") open nothing,
    so they stay in the methods prose where they belong. Text before the first heading is
    `other`. Blocks with no prose are dropped.
    """
    blocks: list[dict] = []
    heading, bucket, lines = "", "other", []

    def _close() -> None:
        body = _join(lines)
        if body:
            blocks.append({"heading": heading, "bucket": bucket, "body": body})

    for line in text.splitlines():
        if is_methods_heading(line):
            if bucket == "methods" and not _join(lines):
                heading = line.strip()
                continue
            _close()
            heading, bucket, lines = line.strip(), "methods", []
        elif is_other_heading(line) and bucket == "methods":
            _close()
            heading, bucket, lines = "", "other", [line]
        else:
            lines.append(line)
    _close()
    return blocks


def methods_chars(blocks: list[dict]) -> int:
    return sum(len(block["body"]) for block in blocks if block["bucket"] == "methods")


def render(files: list[tuple[str, str]], max_chars: int = MAX_PAPER_CHARS) -> str:
    """Render supplementary files as the chain's source text, methods first.

    `files` is `[(file name, plain text)]`. Each block becomes `## <file>: <heading>  [bucket]`
    over one paragraph, and the whole is sentence-numbered by jats_parser.number_sentences --
    the format assay_extractor.has_methods_section and jats_parser.sentence_sections read
    back. Methods blocks of every file go before any other block, so the cut at `max_chars`
    (the cap the main text is held to) falls on figure legends and tables, never on methods.
    The cut is at a block boundary; a block that would cross it is truncated and is the last.
    """
    ordered: list[tuple[str, dict]] = []
    per_file = [(name, split_blocks(text)) for name, text in files]
    for wanted in ("methods", "other"):
        for name, blocks in per_file:
            ordered.extend((name, block) for block in blocks if block["bucket"] == wanted)

    parts: list[str] = []
    used = 0
    for name, block in ordered:
        title = f"{name}: {block['heading']}" if block["heading"] else name
        head = f"## {title}  [{block['bucket']}]"
        room = max_chars - used - len(head) - 2
        if room <= 0:
            break
        body = block["body"][:room]
        parts.append(f"{head}\n{body}")
        used += len(head) + len(body) + 2
    return number_sentences("\n\n".join(parts)) if parts else ""
