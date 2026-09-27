"""Find where a paper's data lives, and separate its own data from data it reused or only cited.

Pipeline, per paper:
1. Candidates (free): every accession outside the reference list, by regex, with the sentence
   that names it and the sentences either side, and whether the paper's Data Availability
   statement names it (`in_da`, `da_source`). Table rows are read whole. Loose formats (PDB,
   GenBank-style, ...) are matched only when the same sentence names the resource.
2. The LLM (one call per paper): every text-named ID, each with its repository guess, the
   sentences naming it and whether the DA statement names it, plus the full paper text. For
   each it decides whether the string is really a repository ID, whether that repository holds
   this study's data, public data the study used, or is only a reference, and gives its own
   reading of whether the DA statement names it.
3. Validation (free, network + local ImmPort DB), after the LLM: accession_validator. Does the
   ID exist, and which paper does the repository say it belongs to? Datasets the repository
   links to this PMID but the text never names are added here.
4. combine(): the LLM's answer is final. Where the DA statement or the repository disagrees
   with it, a REVIEW line says so. An ID the LLM gave no answer for is `unclear`.

The paper text is built here rather than taken from jats_parser.parse_jats_xml, because that
function drops the Data Availability section on purpose -- the very section this module reads.
"""

import copy
import json
import logging
import re
from pathlib import Path
from typing import Callable, Optional

from openai import AsyncOpenAI

from app.agent.accession_validator import NOT_FOUND, PRIVATE, UNCHECKED, VERIFIED
from app.agent.claim_parser import _load_prompt, _strip_fences
from app.agent.jats_parser import (
    _clean_text,
    _descendants,
    _direct_child,
    _is_named,
    _parse_xml,
    _text_content,
    article_title,
)
from app.config import settings

logger = logging.getLogger(__name__)

# Final roles.
DEPOSITED = "deposited"
REUSED = "reused"
REFERENCED = "referenced"
REGISTRATION = "registration"
UNCLEAR = "unclear"
ROLES = (DEPOSITED, REUSED, REFERENCED, REGISTRATION, UNCLEAR)

# What the LLM is asked for, and the final role each answer maps to.
LLM_ROLES = ("this_study", "public_data", "reference", "registration")

# Ownership, from the repository record.
THIS_PAPER = "this_paper"
OTHER_PAPER = "other_paper"
UNLINKED = "unlinked"

#: Longest quote kept. A few journals fold a whole Data Availability paragraph into one
#: "sentence"; past this the quote is cut to a window around the accession (still verbatim).
MAX_QUOTE_CHARS = 400

#: Upper bound on the paper text sent to the model. The largest paper in the JATS corpus is
#: ~127k characters without references, so this truncates nothing there; it is a guard.
MAX_FULL_TEXT_CHARS = 200_000

#: Abbreviations whose period does not end a sentence. jats_parser's _ABBREVIATIONS has the
#: same list, but its lookbehinds sit after the period, so `(?<!\bFig)` sees "ig." and never
#: fires; here each one includes the period. A single capital ("J. Smith") must stand alone,
#: so "DNA." still ends a sentence.
_ABBREVIATION_GUARDS = "".join(
    rf"(?<!\b{a}\.)" for a in (r"i\.e", r"e\.g", "vs", "Fig", "cf", "ca", "no", "Dr", "Inc", "Ltd",
                              "Co", "et al", "approx", "ref", "cat", "ver", "Mr", "St", "[A-Z]"))

#: jats_parser.SENTENCE_SPLIT with working abbreviation guards, plus a boundary after a closing
#: quote: `Infections.” Data and ...`. Kept local: the global splitter numbers sentences for the
#: assay/claim registries, and changing it would shift their stored sentence_ids.
_SENTENCE_SPLIT = re.compile(
    rf"(?:{_ABBREVIATION_GUARDS}(?<=[.!?])|(?<=[.!?][”’\"']))\s+(?=[^\s])")

#: Invisible separator placed in front of each bibliographic citation's text, so a sentence
#: can be checked for "cites a reference" after it has been flattened to plain text.
_CITE = "⁣"


def _norm_zenodo(m: re.Match) -> str:
    return f"10.5281/zenodo.{m.group(1)}"


def _norm_github(m: re.Match) -> str:
    return f"github.com/{m.group(1)}/{m.group(2).removesuffix('.git')}".rstrip(".")


#: repository -> (pattern, normalizer or None, URL template). The normalizer turns a match into
#: the accession key, so `zenodo.6960` and `10.5281/zenodo.6960` merge into one entry.
ACCESSION_PATTERNS: dict[str, tuple[re.Pattern, Optional[Callable], str]] = {
    # GPL (array platform) is deliberately absent: it names a chip, not anyone's data.
    "GEO": (re.compile(r"\bG(?:SE|SM|DS)\d{3,}\b"), None,
            "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={}"),
    # S/E/D: the NCBI, ENA and DDBJ copies of the same archive.
    "SRA": (re.compile(r"\b[SED]R[PXR]\d{6,}\b"), None, "https://www.ncbi.nlm.nih.gov/sra/{}"),
    "BioProject": (re.compile(r"\bPRJ[EDN][A-Z]\d+\b"), None,
                   "https://www.ncbi.nlm.nih.gov/bioproject/{}"),
    "ImmPort": (re.compile(r"\bSDY\d+\b"), None, "https://www.immport.org/shared/study/{}"),
    "dbGaP": (re.compile(r"\bphs\d{6}(?:\.v\d+\.p\d+)?\b"), None,
              "https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id={}"),
    "ArrayExpress": (re.compile(r"\bE-[A-Z]{4}-\d+\b"), None,
                     "https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{}"),
    "PRIDE": (re.compile(r"\bPXD\d{6}\b"), None, "https://www.ebi.ac.uk/pride/archive/projects/{}"),
    "EGA": (re.compile(r"\bEGA[SD]\d+\b"), None, "https://ega-archive.org/search/{}"),
    "FlowRepository": (re.compile(r"\bFR-FCM-[A-Z0-9]{4}\b"), None, "https://flowrepository.org/id/{}"),
    "Zenodo": (re.compile(r"(?:\b10\.5281/)?\bzenodo\.(?:org/records?/)?(\d+)", re.I), _norm_zenodo,
               "https://doi.org/{}"),
    "figshare": (re.compile(r"\b10\.6084/m9\.figshare\.\d+(?:\.v\d+)?\b"), None, "https://doi.org/{}"),
    "GitHub": (re.compile(r"\bgithub\.com/([\w.-]+)/([\w-]+(?:\.[\w-]+)*)", re.I), _norm_github,
               "https://{}"),
    "ClinicalTrials.gov": (re.compile(r"\bNCT\d{8}\b"), None, "https://clinicaltrials.gov/study/{}"),
    # ---- sequencing and single-cell archives
    "BioSample": (re.compile(r"\bSAM(?:N|EA|D)\d{5,}\b"), None,
                  "https://www.ncbi.nlm.nih.gov/biosample/{}"),
    # China's National Genomics Data Center: GSA, GSA-Human and its BioProject.
    "GSA": (re.compile(r"\b(?:CRA|HRA)\d{6}\b|\bPRJCA\d{6}\b"), None,
            "https://ngdc.cncb.ac.cn/search/?dbId=&q={}"),
    "CNGB": (re.compile(r"\bCNP\d{7}\b"), None, "https://db.cngb.org/search/project/{}/"),
    "JGA": (re.compile(r"\bJGA[SD]\d{6}\b"), None, "https://ddbj.nig.ac.jp/search?query={}"),
    # ---- proteomics, metabolomics, structures, imaging
    "MassIVE": (re.compile(r"\bMSV\d{9}\b"), None,
                "https://massive.ucsd.edu/ProteoSAFe/QueryMSV?id={}"),
    "jPOST": (re.compile(r"\bJPST\d{6}\b"), None, "https://repository.jpostdb.org/entry/{}"),
    "MetaboLights": (re.compile(r"\bMTBLS\d+\b"), None, "https://www.ebi.ac.uk/metabolights/{}"),
    "EMDB": (re.compile(r"\bEMD-\d{4,5}\b"), None, "https://www.ebi.ac.uk/emdb/{}"),
    "BioStudies": (re.compile(r"\bS-(?:BSST|BIAD)\d+\b"), None, "https://www.ebi.ac.uk/biostudies/studies/{}"),
    # ---- sequences
    "GISAID": (re.compile(r"\bEPI_ISL_\d+\b"), None, "https://gisaid.org/{}"),
    # ---- DOI-based general and immune-repertoire repositories
    "immuneACCESS": (re.compile(r"\b10\.21417/[A-Za-z0-9]+(?:[./-][A-Za-z0-9]+)*"), None,
                     "https://doi.org/{}"),
    "Dryad": (re.compile(r"\b10\.5061/dryad\.[a-z0-9]+", re.I), None, "https://doi.org/{}"),
    "Mendeley Data": (re.compile(r"\b10\.17632/[a-z0-9]+(?:\.\d+)?", re.I), None, "https://doi.org/{}"),
    "Dataverse": (re.compile(r"\b10\.7910/DVN/[A-Z0-9]+", re.I), None, "https://doi.org/{}"),
    # ---- URL-based: the URL (without scheme) is the identifier
    "OSF": (re.compile(r"\bosf\.io/([a-z0-9]{5})\b", re.I), lambda m: f"osf.io/{m.group(1).lower()}",
            "https://{}"),
    "Synapse": (re.compile(r"\bsyn\d{6,}\b"), None, "https://www.synapse.org/#!Synapse:{}"),
    "CELLxGENE": (re.compile(r"\bcellxgene\.cziscience\.com/(?:collections|e)/[\w-]+", re.I), None,
                  "https://{}"),
    "HCA Data Portal": (re.compile(r"\bdata\.humancellatlas\.org/explore/projects/[\w-]+", re.I), None,
                        "https://{}"),
    "Cytobank": (re.compile(r"\b[\w-]+\.cytobank\.org(?:/[\w#?=&./-]*[\w=])?", re.I), None, "https://{}"),
    # Reference resources rather than records: every link to one (any subdomain, any page)
    # is the same resource, so each normalizes to its site and counts once per paper.
    "iReceptor": (re.compile(r"\b(?:[\w-]+\.)*ireceptor\.org(?:/[\w#?=&./-]*[\w=])?", re.I),
                  lambda m: "ireceptor.org", "https://gateway.ireceptor.org"),
    "VDJServer": (re.compile(r"\b(?:[\w-]+\.)*vdjserver\.org(?:/[\w#?=&./-]*[\w=])?", re.I),
                  lambda m: "vdjserver.org", "https://vdjserver.org"),
    "OAS": (re.compile(r"\bopig\.stats\.ox\.ac\.uk/webapps/oas(?:/[\w#?=&./-]*[\w=])?", re.I),
            lambda m: "opig.stats.ox.ac.uk/webapps/oas", "https://opig.stats.ox.ac.uk/webapps/oas"),
    "IEDB": (re.compile(r"\b(?:[\w-]+\.)*iedb\.org(?:/[\w#?=&./-]*[\w=])?", re.I),
             lambda m: "iedb.org", "https://www.iedb.org"),
    "VDJdb": (re.compile(r"\bvdjdb\.cdr3\.net(?:/[\w#?=&./-]*[\w=])?", re.I),
              lambda m: "vdjdb.cdr3.net", "https://vdjdb.cdr3.net"),
    # ---- further trial registrations
    "ISRCTN": (re.compile(r"\bISRCTN\d{8}\b"), None, "https://www.isrctn.com/{}"),
    "ChiCTR": (re.compile(r"\bChiCTR-?(?:[A-Z]{2,4}-)?\d{6,}\b"), None,
               "https://www.chictr.org.cn/searchprojEN.html?regno={}"),
    # ---- LOOSE formats: matched only with a context word in the same sentence (LOOSE_CONTEXT),
    # and listed last so a distinctive pattern above wins any overlap (find_accessions).
    "Single Cell Portal": (re.compile(r"\bSCP\d{1,5}\b"), None,
                           "https://singlecell.broadinstitute.org/single_cell/study/{}"),
    "Metabolomics Workbench": (re.compile(r"\bST\d{6}\b"), None,
                               "https://www.metabolomicsworkbench.org/data/DRCCMetadata.php?StudyID={}"),
    "PDB": (re.compile(r"\b[1-9](?=[A-Z0-9]{0,2}[A-Z])[A-Z0-9]{3}\b"), None, "https://www.rcsb.org/structure/{}"),
    "GenBank": (re.compile(r"\b[A-Z]{1,2}\d{5,6}(?:\.\d+)?\b"), None, "https://www.ncbi.nlm.nih.gov/nuccore/{}"),
    "EudraCT": (re.compile(r"\b(?:19|20)\d{2}-\d{6}-\d{2}\b"), None,
                "https://www.clinicaltrialsregister.eu/ctr-search/search?query={}"),
}

#: The loose formats above look like ordinary text (a PDB code is any digit + 3 characters, a
#: GenBank ID any 1-2 letters + 5-6 digits, which is also a grant number). They are matched only
#: when the same sentence names the resource; the LLM then confirms each one (`is_accession`).
LOOSE_CONTEXT: dict[str, re.Pattern] = {
    "Single Cell Portal": re.compile(r"Single Cell Portal|singlecell\.broadinstitute", re.I),
    "Metabolomics Workbench": re.compile(r"Metabolomics Workbench", re.I),
    "PDB": re.compile(r"\bPDB\b|Protein Data Bank"),
    "GenBank": re.compile(r"GenBank|\bDDBJ\b|\bEMBL\b|nucleotide sequence|NCBI Nucleotide", re.I),
    "EudraCT": re.compile(r"EudraCT", re.I),
}

#: Repositories that hold something other than data. Code is kept -- "where is the analysis
#: code" is part of reproducing a paper -- and a trial registration is kept as its own role,
#: but both are tagged so neither is ever mistaken for the data.
KIND_BY_REPOSITORY = {"GitHub": "code", "ClinicalTrials.gov": "registration", "EudraCT": "registration",
                      "ISRCTN": "registration", "ChiCTR": "registration"}

#: A section (or notes block) whose title or sec-type matches is a data-availability section.
#: Broader than jats_parser's exclusion rule: "Accession codes", "Major datasets" and a STAR
#: Methods "Deposited data" heading all say where the data went.
_DA_SECTION = re.compile(
    r"availability|accession (?:code|number)s?|major datasets|deposited data|data access|"
    r"data sharing|data deposition",
    re.I,
)

#: A DA statement written as a labelled paragraph rather than a titled section, e.g. "Data and
#: materials availability: ..." inside Acknowledgments, or "Accession codes: ..." inside
#: "Additional information". The colon is required: "accession numbers for the data are ..."
#: is prose, not a label.
_DA_INLINE_LABEL = re.compile(
    r"\b(?:data(?: and (?:materials|code|software))? availability|availability of data"
    r"(?: and materials)?|accession (?:codes?|numbers?)|data (?:access|sharing|deposition))"
    r"(?: statement)?\s*:",
    re.I,
)

#: A lead-in inside a DA section announcing that what follows is other people's data, e.g.
#: eLife's "The following previously published datasets were used".
_DA_REUSE_LEADIN = re.compile(
    r"previously published|\bwere (?:re)?used\b|publicly available data ?sets? (?:were|was) used",
    re.I,
)

#: How far past an inline label in PDF text the DA statement is taken to run. PDF text has no
#: paragraph markup to end it, so this bounds it.
MAX_PDF_DA_SPAN = 1500

#: Reuse wording inside the DA statement itself ("public data were downloaded from ..."),
#: passed to the model as a hint that a DA-listed ID may not be this study's own.
_REUSE_CUES = re.compile(
    r"\bdownloaded\b|\bobtained from\b|\bretrieved from\b|\bre-?analy[sz]"
    r"|\bpreviously (?:published|described|reported|generated|deposited)\b"
    r"|\bpublic(?:ly available)? data ?sets?\b|\bcompared (?:our|with|to)\b|\bmeta-analys[ie]s\b"
    r"|\bet al\.?,? \d{4}",
    re.I,
)


class DataAvailabilityError(RuntimeError):
    """The model returned something that is not a classification object at all."""


# --------------------------------------------------------------------------- text


def find_accessions(text: str) -> list[tuple[str, str, int, int]]:
    """Every accession in `text` as (accession, repository, start, end), in text order.

    `text` is one sentence (or table row). A loose-format repository is only matched when its
    context word is in that same sentence. Where two patterns claim overlapping text, the one
    listed first in ACCESSION_PATTERNS wins -- the distinctive formats come before the loose
    ones, so `ST000123` next to "GenBank" stays a Metabolomics Workbench ID only if that
    resource is named, and is never taken for a GenBank accession when a stricter match exists.
    """
    found = []
    for priority, (repo, (pattern, normalize, _)) in enumerate(ACCESSION_PATTERNS.items()):
        context = LOOSE_CONTEXT.get(repo)
        if context is not None and not context.search(text):
            continue
        for m in pattern.finditer(text):
            acc = normalize(m) if normalize else m.group(0)
            found.append((priority, acc, repo, m.start(), m.end()))

    kept: list[tuple[str, str, int, int]] = []
    for _, acc, repo, start, end in sorted(found):
        if any(start < k_end and k_start < end for _, _, k_start, k_end in kept):
            continue
        kept.append((acc, repo, start, end))
    return sorted(kept, key=lambda f: f[2])


def accession_url(accession: str, repository: str) -> str:
    return ACCESSION_PATTERNS[repository][2].format(accession)


def kind_of(repository: str) -> str:
    return KIND_BY_REPOSITORY.get(repository, "data")


def _ancestors(node) -> list:
    return [a for a in node.iterancestors() if isinstance(a.tag, str)]


def _block_title(node) -> str:
    """The heading of the nearest titled section-like ancestor: sec, notes, ack, fn-group."""
    for anc in _ancestors(node):
        if _is_named(anc, "table-wrap"):
            label = _text_content(_direct_child(anc, "label"))
            caption = _direct_child(anc, "caption")
            cap_title = _text_content(_direct_child(caption, "title")) if caption is not None else ""
            return "Table: " + (" ".join(p for p in (label, cap_title) if p) or "untitled")
        if _is_named(anc, {"sec", "notes", "ack", "fn-group", "app"}):
            title = _text_content(_direct_child(anc, "title"))
            if title:
                return title
            kind = anc.get("sec-type") or anc.get("notes-type") or ""
            if kind:
                return kind
    for anc in _ancestors(node):
        if _is_named(anc, {"sec", "notes", "ack", "fn-group", "app", "back", "body", "front"}):
            return anc.tag.split("}")[-1]
    return "article"


def _section_label(node) -> str:
    return " ".join(p for p in (_text_content(_direct_child(node, "title")),
                                node.get("sec-type") or "", node.get("notes-type") or "") if p)


def _da_ancestor(node):
    """The nearest enclosing DA-titled section-like element, or None."""
    for anc in _ancestors(node):
        if _is_named(anc, {"sec", "notes", "fn-group", "ack", "app"}):
            label = _section_label(anc)
            if label and _DA_SECTION.search(label):
                return anc
    return None


def _in_da_section(node) -> bool:
    return _da_ancestor(node) is not None


def _da_leadin(block, da_sec) -> bool:
    """True when, inside `da_sec`, something before `block` says the datasets are someone else's.

    Walks the preceding siblings of the block and of each ancestor up to the DA section, so a
    lead-in paragraph ("The following previously published datasets were used:") covers every
    dataset listed after it, whichever wrapper each one sits in.
    """
    node = block
    while node is not None and node is not da_sec:
        for sib in node.itersiblings(preceding=True):
            if isinstance(sib.tag, str) and _DA_REUSE_LEADIN.search(_text_content(sib)):
                return True
        node = node.getparent()
    return False


def _text_with_cite_marks(block) -> str:
    """The block's text, with _CITE in front of every bibliographic citation."""
    block = copy.deepcopy(block)
    for xref in block.xpath('.//*[local-name()="xref"][@ref-type="bibr"]'):
        xref.text = _CITE + (xref.text or "")
    return _clean_text(" ".join(t.strip() for t in block.itertext() if t and t.strip()))


def _row_text(tr) -> str:
    cells = [_text_content(c) for c in tr if isinstance(c.tag, str)]
    return " | ".join(c for c in cells if c)


def _blocks(root) -> list:
    """The prose units accessions are read from: paragraphs, and table rows as a unit each.

    A table row is kept whole because its cells only mean something together ("Raw data |
    This paper | GEO: GSE133383"). Paragraphs inside a table row are covered by the row. The
    reference list is skipped -- an accession there is a citation, and if the paper used the
    dataset it will also have named it in the text.
    """
    blocks = []
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        if not _is_named(node, {"p", "tr", "related-object"}):
            continue
        if any(_is_named(a, {"ref-list", "tr", "p", "related-object"}) for a in _ancestors(node)):
            continue
        blocks.append(node)
    return blocks


def _quote_window(sentence: str, start: int, end: int) -> str:
    if len(sentence) <= MAX_QUOTE_CHARS:
        return sentence
    half = (MAX_QUOTE_CHARS - (end - start)) // 2
    lo = max(0, start - half)
    hi = min(len(sentence), lo + MAX_QUOTE_CHARS)
    lo = max(0, hi - MAX_QUOTE_CHARS)
    return sentence[lo:hi].strip()


def _clip(text: str) -> str:
    return text if len(text) <= MAX_QUOTE_CHARS else text[:MAX_QUOTE_CHARS].rstrip() + " …"


def _paragraph_mentions(text: str, *, section: str, section_da: bool, is_row: bool,
                        leadin: bool, seen: set, max_da_span: Optional[int] = None) -> list[dict]:
    """Mentions in one paragraph (or table row) of text, which may carry _CITE marks.

    A mention is in the DA statement when the whole block sits in a DA-titled section
    (`section_da`), or when an inline DA label ("Data and materials availability:") appears in
    the paragraph at or before its sentence -- only the sentences from the label on count, so a
    label halfway through an Acknowledgments paragraph does not claim the thanks before it.
    """
    label = None if (section_da or is_row) else _DA_INLINE_LABEL.search(text)
    units = [text] if is_row else _SENTENCE_SPLIT.split(text)
    plain_units = [u.replace(_CITE, "") for u in units]

    mentions = []
    pos = 0
    for i, unit in enumerate(units):
        start_i = text.find(unit, pos)
        start_i = pos if start_i < 0 else start_i
        end_i = start_i + len(unit)
        pos = end_i

        after_label = (label is not None and end_i > label.start()
                       and (max_da_span is None or start_i < label.start() + max_da_span))
        da_source = "section" if section_da else "inline_label" if after_label else None
        da_leadin = leadin if section_da else bool(
            after_label and _DA_REUSE_LEADIN.search(text[label.start():start_i]))

        plain = plain_units[i]
        for acc, repo, start, end in find_accessions(plain):
            key = (acc, plain)
            if key in seen:
                continue
            seen.add(key)
            quote = _quote_window(plain, start, end)
            before = _clip(plain_units[i - 1]) if i > 0 else ""
            after = _clip(plain_units[i + 1]) if i + 1 < len(plain_units) else ""
            mentions.append({
                "accession": acc,
                "repository": repo,
                "section": section,
                "in_da_section": da_source is not None,
                "da_source": da_source,
                "da_leadin": da_leadin,
                "quote": quote,
                "context": " ".join(p for p in (before, quote, after) if p),
                "cites_reference": _CITE in unit,
            })
    return mentions


def extract_mentions(xml_text: str) -> list[dict]:
    """Every accession named outside the reference list, with where and how it was named.

    One dict per (accession, sentence): `accession`, `repository`, `section`, `in_da_section`,
    `da_source` (`section` / `inline_label` / None), `da_leadin` (a "previously published
    datasets" lead-in precedes it in the DA statement), `quote` (the sentence, verbatim,
    citation marks removed), `context` (the sentence with the one before and after it; a table
    row is its own context) and `cites_reference` (the sentence carries a bibliographic
    citation -- a strong sign the dataset is someone else's).
    """
    root = _parse_xml(xml_text)
    if root is None:
        return []

    mentions = []
    seen: set = set()
    for block in _blocks(root):
        is_row = _is_named(block, "tr")
        text = _row_text(block) if is_row else _text_with_cite_marks(block)
        if not text:
            continue
        da_sec = _da_ancestor(block)
        mentions += _paragraph_mentions(
            text, section=_block_title(block), section_da=da_sec is not None, is_row=is_row,
            leadin=da_sec is not None and _da_leadin(block, da_sec), seen=seen)
    return mentions


def data_availability_statement(xml_text: str) -> tuple[Optional[str], Optional[str]]:
    """`(text, source)` of the paper's data-availability statement, or `(None, None)`.

    `source` is `section` when a DA-titled section exists, else `inline_label` when a paragraph
    carries a DA label ("Data and materials availability: ..."), in which case the text runs
    from the label to the end of that paragraph.
    """
    root = _parse_xml(xml_text)
    if root is None:
        return None, None

    parts = []
    for node in root.iter():
        if not isinstance(node.tag, str) or not _is_named(node, {"sec", "notes"}):
            continue
        if any(_is_named(a, "ref-list") for a in _ancestors(node)):
            continue
        label = _section_label(node)
        if not label or not _DA_SECTION.search(label):
            continue
        # A DA section nested in another DA section is already covered by its parent.
        if any(_is_named(a, {"sec", "notes"}) and _DA_SECTION.search(_section_label(a) or "")
               for a in _ancestors(node)):
            continue
        body = [_text_content(p) for p in _descendants(node, "p")]
        text = " ".join(b for b in body if b) or _text_content(node)
        if text and text not in parts:
            parts.append(text)
    if parts:
        return "\n".join(parts), "section"

    for block in _blocks(root):
        if _is_named(block, "tr"):
            continue
        text = _text_content(block)
        match = _DA_INLINE_LABEL.search(text)
        if match and text[match.start():] not in parts:
            parts.append(text[match.start():])
    return ("\n".join(parts), "inline_label") if parts else (None, None)


# --------------------------------------------------------------------------- PDF text

#: A references heading on a line of its own. Only one in the second half of the text is taken
#: as the start of the reference list: "References" also turns up early, in a table of contents
#: or as the last word of a wrapped line.
_REFERENCES_HEADING = re.compile(
    r"(?im)^[ \t]*(?:references(?: and notes)?|references cited|literature cited|bibliography)[ \t]*$")

#: A DA heading alone on its line. PDF text has no section tags, so such a heading is turned
#: into an inline label ("Data availability:") and handled by the inline-label rule.
_DA_HEADING_LINE = re.compile(
    r"(?im)^[ \t]*((?:data(?: and (?:materials|code|software))? availability|availability of data"
    r"(?: and materials)?|accession (?:codes?|numbers?))(?: statement)?)[ \t]*$")


#: The first entry of a numbered reference list ("1. Rerks-Ngarm S, et al."), for journals
#: (PNAS) that print the list with no heading above it. A "2." entry must follow.
_FIRST_NUMBERED_REF = re.compile(r"(?m)^[ \t]*1\.[ \t]+[A-Z][\w'’-]+ [A-Z]{1,3}[,;. ]")
_SECOND_NUMBERED_REF = re.compile(r"(?m)^[ \t]*2\.[ \t]+[A-Z]")


def clean_pdf_text(raw: str) -> str:
    """PyMuPDF text made fit to search: hyphens rejoined, the reference list cut off.

    The list starts at the last references heading in the second half of the text; failing
    that, at a numbered "1. Surname X," entry in the second half that a "2." entry follows.
    """
    text = re.sub(r"([a-z])-\n([a-z])", r"\1\2", raw)
    half = len(text) / 2
    later = [m for m in _REFERENCES_HEADING.finditer(text) if m.start() > half]
    if later:
        text = text[:later[-1].start()]
    else:
        for m in _FIRST_NUMBERED_REF.finditer(text):
            if m.start() > half and _SECOND_NUMBERED_REF.search(text, m.end()):
                text = text[:m.start()]
                break
    return _DA_HEADING_LINE.sub(r"\1:", text).strip()


def _pdf_paragraphs(text: str) -> list[str]:
    return [p for p in (re.sub(r"\s+", " ", block).strip() for block in re.split(r"\n\s*\n", text)) if p]


def extract_mentions_from_text(text: str) -> list[dict]:
    """extract_mentions for plain text (a PDF): same regexes, same context window.

    Weaker than the XML route, and records built from it say so (`source_format: pdf`): there
    are no section titles (every mention's section is "PDF text"), no table rows, and no
    tagged citations (`cites_reference` is always False). DA statements are found only by
    their label, and run at most MAX_PDF_DA_SPAN characters past it.
    """
    mentions = []
    seen: set = set()
    for para in _pdf_paragraphs(text):
        mentions += _paragraph_mentions(para, section="PDF text", section_da=False, is_row=False,
                                        leadin=False, seen=seen, max_da_span=MAX_PDF_DA_SPAN)
    return mentions


def statement_from_text(text: str) -> tuple[Optional[str], Optional[str]]:
    """data_availability_statement for plain text: every inline-labelled span, or (None, None)."""
    parts = []
    for para in _pdf_paragraphs(text):
        match = _DA_INLINE_LABEL.search(para)
        if match:
            parts.append(para[match.start():match.start() + MAX_PDF_DA_SPAN])
    return ("\n".join(parts), "inline_label") if parts else (None, None)


def _pdf_raw_text(path: Path) -> tuple[str, Optional[str]]:
    import fitz  # pymupdf; imported here so the XML route never needs it

    from app.agent.paper_reader import extract_pdf_text

    data = path.read_bytes()
    title = (fitz.open(stream=data, filetype="pdf").metadata or {}).get("title") or None
    # A PDF's metadata title is often a file name or a journal code; keep only a real sentence.
    if title and len(title.split()) < 4:
        title = None
    return extract_pdf_text(data, max_chars=10**9), title


def load_paper(path: Path) -> dict:
    """Everything the pipeline needs from one paper file, XML or PDF.

    Files are named `<SDY>_<PMID>.xml|.pdf`. Returns `format`, `study`, `pmid`, `title`, `text`
    (what the model reads), `mentions`, `statement` and `statement_source`.
    """
    path = Path(path)
    study, _, pmid = path.stem.partition("_")
    if path.suffix.lower() == ".pdf":
        raw, title = _pdf_raw_text(path)
        text = clean_pdf_text(raw)
        statement, statement_source = statement_from_text(text)
        return {"format": "pdf", "study": study, "pmid": pmid, "title": title, "text": text,
                "mentions": extract_mentions_from_text(text),
                "statement": statement, "statement_source": statement_source}

    xml = path.read_text(encoding="utf-8")
    statement, statement_source = data_availability_statement(xml)
    return {"format": "xml", "study": study, "pmid": pmid, "title": article_title(xml),
            "text": full_text(xml), "mentions": extract_mentions(xml),
            "statement": statement, "statement_source": statement_source}


def benchmark_papers(assay_dir: Path, jats_dir: Path, pdf_root: Path) -> list[tuple[str, Optional[Path]]]:
    """The benchmark's papers as `(<SDY>_<PMID>, source file or None)`, XML preferred over PDF.

    `assay_dir` holds one folder per benchmark paper, named `<PMID>_<SDY>` with an optional
    `_pdf` suffix (the assay pipeline's naming, which is the reverse of the XML/PDF files').
    """
    papers = []
    for folder in sorted(p for p in Path(assay_dir).iterdir() if p.is_dir()):
        parts = folder.name.split("_")
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].upper().startswith("SDY"):
            continue
        stem = f"{parts[1]}_{parts[0]}"
        xml = Path(jats_dir) / f"{stem}.xml"
        pdfs = sorted(Path(pdf_root).rglob(f"{stem}.pdf"))
        papers.append((stem, xml if xml.exists() else pdfs[0] if pdfs else None))
    return papers


_HEADING_PARENTS = {"sec", "app", "notes", "ack", "abstract", "fn-group", "trans-abstract"}


def full_text(xml_text: str) -> str:
    """The whole article as plain text for the model: everything except the reference list.

    Unlike parse_jats_xml this keeps the Data Availability section, footnotes, acknowledgments,
    Introduction and Discussion -- a dataset "cited only as background" is exactly what the
    Introduction does, and the model cannot call something cited-only without seeing it.
    Section titles become `## ` headings; table rows become ` | `-joined lines. Plain text,
    not the raw XML: the markup is two-thirds of a JATS file and tells the model nothing.
    """
    root = _parse_xml(xml_text)
    if root is None:
        return ""
    for ref_list in _descendants(root, "ref-list"):
        ref_list.getparent().remove(ref_list)

    lines = []
    title = article_title(xml_text)
    if title:
        lines.append(f"# {title}")
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        parent = node.getparent()
        if _is_named(node, "title") and parent is not None:
            if _is_named(parent, _HEADING_PARENTS):
                text = _text_content(node)
                if text:
                    lines.append(f"\n## {text}")
            elif _is_named(parent, "caption"):
                label = _text_content(_direct_child(parent.getparent(), "label")) \
                    if parent.getparent() is not None else ""
                lines.append(f"\n[{label or 'Caption'}] {_text_content(node)}")
            continue
        if _is_named(node, {"p", "tr"}):
            if any(_is_named(a, {"p", "tr"}) for a in _ancestors(node)):
                continue
            text = _row_text(node) if _is_named(node, "tr") else _text_content(node)
            if text:
                lines.append(text)

    text = "\n".join(lines).strip()
    if len(text) > MAX_FULL_TEXT_CHARS:
        logger.warning("paper text is %d chars; truncated to %d", len(text), MAX_FULL_TEXT_CHARS)
        text = text[:MAX_FULL_TEXT_CHARS]
    return text


# --------------------------------------------------------------------------- grouping


def group_mentions(mentions: list[dict]) -> dict[str, dict]:
    """One entry per accession, carrying every mention of it as evidence.

    Each entry also records whether any mention sits in the paper's DA statement (`in_da`,
    `da_source`) and, if so, whether that statement itself marks it as someone else's data
    (`da_reuse_reason`) -- both are shown to the model.
    """
    entries: dict[str, dict] = {}
    for mention in mentions:
        entry = entries.setdefault(mention["accession"], {
            "accession": mention["accession"],
            "repository": mention["repository"],
            "url": accession_url(mention["accession"], mention["repository"]),
            "kind": kind_of(mention["repository"]),
            "found_by": "text",
            "in_da": False,
            "da_source": None,
            "da_reuse_reason": None,
            "evidence": [],
        })
        entry["evidence"].append({"section": mention["section"], "quote": mention["quote"],
                                  "context": mention["context"],
                                  "in_da": bool(mention.get("da_source"))})
        if mention.get("da_source"):
            entry["in_da"] = True
            # A titled section outranks an inline label when an ID sits in both.
            if entry["da_source"] != "section":
                entry["da_source"] = mention["da_source"]
            if entry["da_reuse_reason"] is None:
                cue = _REUSE_CUES.search(mention["quote"])
                if cue:
                    entry["da_reuse_reason"] = f"reuse wording '{cue.group(0)}' in the DA statement"
                elif mention.get("da_leadin"):
                    entry["da_reuse_reason"] = "listed after a 'previously published datasets' lead-in"
    return entries


def add_linked_datasets(entries: dict[str, dict], linked: list[tuple[str, str]]) -> list[str]:
    """Add datasets the repository links to this paper but the text never names.

    Returns the accessions added. They carry no evidence -- the repository link is the evidence
    -- and are not sent to the model, which has no sentence to read about them.
    """
    added = []
    for acc, repo in linked:
        if acc in entries:
            continue
        entries[acc] = {
            "accession": acc, "repository": repo, "url": accession_url(acc, repo),
            "kind": kind_of(repo), "found_by": "repository_link", "evidence": [],
            "in_da": False, "da_source": None, "da_reuse_reason": None,
        }
        added.append(acc)
    return added


# --------------------------------------------------------------------------- validation


def owner_of(validation: Optional[dict], pmid: str) -> Optional[str]:
    """`this_paper` / `other_paper` / `unlinked` from a validator result, or None if unknown."""
    if not validation or validation["status"] not in (VERIFIED, PRIVATE):
        return None
    pmids = validation.get("owner_pmids") or []
    if pmid in pmids:
        return THIS_PAPER
    return OTHER_PAPER if pmids else UNLINKED


def apply_validation(entries: dict[str, dict], validations: dict[str, dict], pmid: str) -> None:
    """Attach each validator result to its entry. Nothing is dropped here.

    Validation runs after the LLM, so this is a check on its answer: a NOT_FOUND on an ID the
    model kept becomes a REVIEW line; settle_drops() only drops a NOT_FOUND the model never
    answered for.
    """
    for acc, entry in entries.items():
        validation = validations.get(acc)
        if validation is None:
            continue
        entry["validation"] = validation
        entry["owner"] = owner_of(validation, pmid)
        entry["owner_pmids"] = validation["owner_pmids"]


def settle_drops(entries: dict[str, dict]) -> list[str]:
    """Remove what is not a real repository ID; return one DROPPED line per removal.

    The LLM decides when it answered (`is_accession: false` drops, even if a record with that ID
    happens to exist -- the line says so). Without an LLM answer, the repository decides: an ID
    it has no record of is dropped.
    """
    dropped = []
    for acc in list(entries):
        entry = entries[acc]
        validation = entry.get("validation") or {}
        llm = entry.get("llm")
        if llm is not None and llm["is_accession"] is False:
            note = (f"; note: {entry['repository']} does have a record with this ID"
                    if validation.get("status") == VERIFIED else "")
            dropped.append(f"{acc} ({entry['repository']}): model says not a repository ID "
                           f"({llm['reason']}){note}")
            del entries[acc]
        elif llm is None and validation.get("status") == NOT_FOUND:
            dropped.append(f"{acc} ({entry['repository']}): {validation['detail']}")
            del entries[acc]
    return dropped


# --------------------------------------------------------------------------- LLM


def llm_candidates(entries: dict[str, dict]) -> list[dict]:
    """Every ID the paper names in its text -- including DA-statement IDs and registrations.

    Only datasets found purely through the repository's link to this PMID are left out: there
    is no sentence about them for the model to read.
    """
    return [e for e in entries.values() if e["found_by"] == "text"]


def _candidate_block(entry: dict) -> str:
    da = {"section": "yes (Data Availability section)",
          "inline_label": "yes (labelled data availability statement)"}.get(entry.get("da_source"), "no")
    lines = [f"- ID: {entry['accession']} | pattern match: {entry['repository']}",
             f"  in the Data Availability statement: {da}"]
    if entry.get("da_reuse_reason"):
        lines.append(f"  note: {entry['da_reuse_reason']}")
    for i, ev in enumerate(entry["evidence"][:4], 1):
        lines.append(f"  mention {i} [{ev['section']}]")
        lines.append(f"    sentence: \"{ev['quote']}\"")
        if ev.get("context") and ev["context"] != ev["quote"]:
            lines.append(f"    context: \"{ev['context']}\"")
    return "\n".join(lines)


def build_prompt(paper_title: str, pmid: str, paper_text: str, candidates: list[dict]) -> str:
    """Render classify_data_availability.txt for one paper."""
    return (
        _load_prompt("classify_data_availability.txt")
        .replace("{paper_title}", paper_title or "(unknown title)")
        .replace("{pmid}", pmid or "(unknown)")
        .replace("{candidates}", "\n".join(_candidate_block(e) for e in candidates))
        .replace("{repositories}", ", ".join(ACCESSION_PATTERNS))
        .replace("{paper_text}", paper_text)
    )


def apply_llm_answer(entries: dict[str, dict], parsed: object, asked: set[str]) -> list[str]:
    """Validate a model answer and attach it to each entry as `entry["llm"]`.

    Returns warnings for everything refused. A refused or missing answer leaves that entry with
    no `llm`, so the free evidence decides it (combine's fallback).
    """
    if not isinstance(parsed, dict):
        raise DataAvailabilityError(
            f"model returned {type(parsed).__name__}, not an ID -> answer object")

    warnings = []
    for acc, answer in parsed.items():
        if acc not in asked:
            warnings.append(f"model answered for {acc}, which was not asked about; ignored")
            continue
        if not isinstance(answer, dict) or not isinstance(answer.get("is_accession"), bool):
            warnings.append(f"model's answer for {acc} has no true/false is_accession; ignored")
            continue
        role = answer.get("role")
        if answer["is_accession"] and role not in LLM_ROLES:
            warnings.append(f"model gave {acc} role {role!r}, not one of {LLM_ROLES}; ignored")
            continue
        repo = answer.get("repository")
        if repo is not None and repo not in ACCESSION_PATTERNS:
            warnings.append(f"model named {acc}'s repository {repo!r}, which is not one we know; "
                            "kept the pattern's guess")
            repo = None
        in_da = answer.get("in_da_statement")
        if answer["is_accession"] and not isinstance(in_da, bool):
            warnings.append(f"model's answer for {acc} has no true/false in_da_statement; "
                            "its role stands")
            in_da = None
        reason = answer.get("reason") if isinstance(answer.get("reason"), str) else ""
        entries[acc]["llm"] = {
            "is_accession": answer["is_accession"],
            "repository": repo or entries[acc]["repository"],
            "role": role if answer["is_accession"] else None,
            "in_da_statement": in_da if answer["is_accession"] else None,
            "reason": reason.strip(),
        }

    for acc in sorted(asked - set(parsed)):
        warnings.append(f"model did not answer for {acc}")
    return warnings


async def classify_candidates(
    paper_title: str,
    pmid: str,
    paper_text: str,
    entries: dict[str, dict],
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> list[str]:
    """One LLM call over every candidate; none when the paper names no ID."""
    candidates = llm_candidates(entries)
    if not candidates:
        return []

    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user",
                   "content": build_prompt(paper_title, pmid, paper_text, candidates)}],
        temperature=0,
    )
    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    if not raw:
        raise DataAvailabilityError("model returned an empty response")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataAvailabilityError(f"model returned unparseable JSON: {exc}") from exc

    warnings = apply_llm_answer(entries, parsed, {e["accession"] for e in candidates})
    for warning in warnings:
        logger.warning("data availability: %s", warning)
    return warnings


# --------------------------------------------------------------------------- combine

_LLM_ROLE_TO_ROLE = {"this_study": DEPOSITED, "public_data": REUSED, "reference": REFERENCED,
                     "registration": REGISTRATION}


def _owners(entry: dict) -> str:
    return ", ".join(entry.get("owner_pmids") or []) or "none"


def combine(entry: dict) -> tuple[str, str, str, Optional[str]]:
    """`(role, decided_by, reason, review)` for one entry.

    The LLM's answer is the role, and every disagreement with the DA statement or the
    repository record becomes the REVIEW text. An ID the model gave no answer for is `unclear`.
    """
    repo = entry["repository"]
    if entry["kind"] == "registration":
        # The pattern already says what it is; the LLM only confirms it is a real ID.
        return REGISTRATION, "regex", "clinical-trial registration, not a data deposit", None
    if entry["found_by"] == "repository_link":
        return DEPOSITED, "repository", f"{repo} links this dataset to this paper; the text never names it", None
    if entry.get("llm"):
        return _combine_llm(entry)
    return UNCLEAR, "none", "the model gave no answer for this ID", (
        f"{entry['accession']}: no model answer; needs a human look")


def _combine_llm(entry: dict) -> tuple[str, str, str, Optional[str]]:
    """The LLM's role, with one REVIEW clause per piece of evidence that disagrees."""
    acc, repo = entry["accession"], entry["repository"]
    llm = entry["llm"]
    role = _LLM_ROLE_TO_ROLE[llm["role"]]
    owner = entry.get("owner")
    validation = entry.get("validation") or {}
    detected = bool(entry.get("in_da"))
    model_da = llm.get("in_da_statement")

    issues = []
    if detected and role in (REUSED, REFERENCED) and not entry.get("da_reuse_reason"):
        issues.append(f"the DA statement names it, but the model says {llm['role']}")
    if model_da is not None and model_da != detected:
        issues.append("the model reads it as " + ("in" if model_da else "not in")
                      + " the DA statement; the pattern search found it "
                      + ("in" if detected else "outside") + " it")
    # Only when the repository answered and records no paper: an unchecked ID proves nothing.
    if role == DEPOSITED and not detected and not model_da and owner == UNLINKED:
        issues.append("the model says this_study, but no DA statement names it and no "
                      "repository links it to this paper")
    if owner == OTHER_PAPER and role == DEPOSITED:
        issues.append(f"{repo} links it to PMID {_owners(entry)} (often the same group's earlier "
                      "study), but the model says this_study")
    if owner == THIS_PAPER and role in (REUSED, REFERENCED):
        issues.append(f"{repo} links it to this paper, but the model says {llm['role']}")
    if validation.get("status") == NOT_FOUND:
        issues.append(f"{repo} has no record with this ID, but the model says it is one")
    if llm["repository"] != repo:
        issues.append(f"the model says the repository is {llm['repository']}, the pattern matched {repo}")

    review = f"{acc}: " + "; ".join(issues) if issues else None
    return role, "llm", llm["reason"], review


# --------------------------------------------------------------------------- output


def build_record(pmid: str, study: str, title: Optional[str], statement: Optional[str],
                 entries: dict[str, dict], *, warnings: list[str], dropped: list[str],
                 source_format: str = "xml", llm_model: Optional[str] = None,
                 statement_source: Optional[str] = None, validated: bool = True) -> dict:
    """The per-paper result: accessions split by final role, each with its evidence.

    `validated=False` is the record written before any repository lookup: the validation-only
    fields (`status`, `status_detail`, `owner`, `owner_pmids`) are left out.

    `llm_model` is the model that answered for this paper, or None when no LLM answer was used.
    `statement_source` is how the DA statement was found (`section` / `inline_label`), or None.
    """
    record = {
        "pmid": pmid,
        "study": study,
        "title": title,
        "source_format": source_format,
        "llm_called": llm_model is not None,
        "llm_model": llm_model,
        "da_accessions": [a for a, e in entries.items() if e.get("in_da")],
        "data_availability_statement": statement,
        "data_availability_source": statement_source,
        **{role: [] for role in ROLES},
        "reviews": [],
        "dropped": list(dropped),
        "warnings": list(warnings),
    }
    for entry in entries.values():
        role, decided_by, reason, review = combine(entry)
        if review:
            record["reviews"].append(review)
        item = {
            "accession": entry["accession"],
            "repository": entry["repository"],
            "url": entry["url"],
            "kind": entry["kind"],
            "llm": entry.get("llm"),
        }
        if validated:
            validation = entry.get("validation")
            item.update(owner=entry.get("owner"), owner_pmids=entry.get("owner_pmids", []),
                        status=validation["status"] if validation else None,
                        status_detail=validation["detail"] if validation else "not checked")
        item.update({
            "decided_by": decided_by,
            "reason": reason,
            "found_by": entry["found_by"],
            "in_da_section": bool(entry.get("in_da")),
            "da_source": entry.get("da_source"),
            "llm_in_da": (entry.get("llm") or {}).get("in_da_statement"),
            "evidence": entry["evidence"],
        })
        record[role].append(item)
    return record


def repository_record(record: dict) -> dict:
    """The final answer: which repositories hold this study's own data, with their links.

    Built from the validated, located record. A deposited dataset the repository confirmed
    (`verified` / `private`) goes in `data_repositories`; one it could not confirm goes in
    `unconfirmed` with the reason. Code, reused, referenced and registrations are left out.
    """
    reviews: dict[str, list[str]] = {}
    for line in record["reviews"]:
        acc, _, text = line.partition(": ")
        reviews.setdefault(acc, []).append(text)

    repositories, unconfirmed = [], []
    for item in record[DEPOSITED]:
        if item["kind"] != "data":
            continue
        if item.get("status") not in (VERIFIED, PRIVATE):
            unconfirmed.append({"accession": item["accession"], "repository": item["repository"],
                                "url": item["url"], "status": item.get("status"),
                                "detail": item.get("status_detail") or ""})
            continue
        location = item.get("location") or {}
        repositories.append({
            "accession": item["accession"],
            "repository": item["repository"],
            "landing_page": location.get("landing_page") or item["url"],
            "download": location.get("download"),
            "access": location.get("access"),
            "file_count": location.get("file_count"),
            "total_size_bytes": location.get("total_size_bytes"),
            "status": item["status"],
            "owner_pmids": item.get("owner_pmids", []),
            "found_by": item["found_by"],
            "review": "; ".join(reviews[item["accession"]]) if item["accession"] in reviews else None,
        })
    return {"pmid": record["pmid"], "study": record["study"], "title": record["title"],
            "data_repositories": repositories, "unconfirmed": unconfirmed}
