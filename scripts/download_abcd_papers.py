#!/usr/bin/env python3
"""Download every paper on the ABCD datasheet's "Gisela&Gur list" into one folder.

Input is docs/ABCD_master_datasheet.xlsx. Output, under --papers-dir (the external drive by
default):

    papers_all.csv         every PMID on the sheet, once: pmid, study_accessions, primary_sdy,
                           n_studies, title
    xml/<pmid>_<label>.xml the full text PubMed Central served
    papers_xml.csv         the papers WITH xml -- the list scripts/run_immport_assays.py reads
    pdf/<label>_<pmid>.pdf an open-access PDF, for a paper PubMed Central does not carry
    papers_pdf.csv         the papers with a PDF and no XML: pmid, primary_sdy, title, file, url
    papers_no_xml.csv      the papers WITHOUT xml, with the reason; a paper that got a PDF is
                           listed here too, its reason saying so

**The label stands where the ImmPort corpus has an SDY accession.** These papers are not
ImmPort studies; the sheet's "Study Name" (D1, D2, ...) is used, and `ABCD` for a row that has
none. The XML is filed `<pmid>_<label>.xml` -- pmid FIRST, unlike the ImmPort corpus's
`<SDY>_<pmid>.xml` -- because assay_service.split_stem tells the two halves apart by the SDY
prefix, and a stem with no SDY half reads back as (left, right). `D1_37367734` would come back
as PubMed ID "D1".

**Free.** NCBI's ID converter and efetch for the XML, OpenAlex for the open-access PDF
location, then the PDF itself. No model calls.

**Resumable.** A paper whose file is already in xml/ or pdf/ is skipped. Everything else is
asked about again on every run -- the list is 39 papers, so there is nothing to save by
remembering a refusal. --force refetches everything.

A downloaded PDF is kept only if it is a PDF (`%PDF` magic) whose text layer carries the
paper's title words: a publisher that answers a scripted request with a landing page, or with
a different article, must not be filed under this paper's id.

Usage:
    python3 scripts/download_abcd_papers.py [--sheet docs/ABCD_master_datasheet.xlsx]
                                            [--papers-dir "/Volumes/Extreme SSD/ABCD papers"]
                                            [--sheet-name NAME] [--skip PMID ...]
                                            [--dry-run] [--force] [--no-pdf]

--dry-run reads the sheet and the folder and prints what a run would fetch; it writes and calls
nothing. Prints one OK / SKIP / FAIL line per paper and the three closing lists.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agent import assay_service, immport_corpus  # noqa: E402
from app.agent.jats_fetcher import unavailable_reason  # noqa: E402
from app.agent.paper_reader import extract_pdf_text  # noqa: E402
from download_immport_xml import _chunks, idconv, write_xml  # noqa: E402
from download_pmc_corpus import (  # noqa: E402
    FETCH_BATCH,
    article_record,
    fetch_batch,
    split_articleset,
)

DEFAULT_SHEET = _REPO_ROOT / "docs" / "ABCD_master_datasheet.xlsx"
SHEET_NAME = "Gisela&Gur list"
PAPERS_DIR = Path("/Volumes/Extreme SSD/ABCD papers")
RESULT_DIR = Path("/Volumes/Extreme SSD/ABCD result")
PDF_DIR_NAME = "pdf"
PAPERS_PDF_NAME = "papers_pdf.csv"

#: What a row with no "Study Name" is filed under.
FALLBACK_LABEL = "ABCD"

ALL_COLUMNS = immport_corpus.PAPER_COLUMNS + ("title",)
PDF_COLUMNS = ("pmid", "primary_sdy", "title", "file", "url")

OPENALEX_URL = "https://api.openalex.org/works/pmid:{pmid}"
#: A generic client name: nothing about the user or the project goes to an outside service.
USER_AGENT = "Mozilla/5.0 (compatible; paper-downloader/1.0)"

_PMID_RE = re.compile(r"\d{6,9}")
_LABEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_WORD_RE = re.compile(r"[a-z0-9]{5,}")
#: Share of the title's long words the PDF's text must carry to be taken as this paper.
TITLE_MATCH_MIN = 0.6
#: How much of the PDF's text layer the title is looked for in: it is on the first page.
TITLE_SEARCH_CHARS = 30000


# ── the sheet ────────────────────────────────────────────────────────────────

def cell_pmids(value) -> list[str]:
    """Every PubMed ID in one cell: `37367734`, `'37367734'`, or `'[32747814, 34772824]'`."""
    if value is None:
        return []
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return _PMID_RE.findall(str(value))


def cell_label(value) -> str:
    """The row's Study Name as a file label, or FALLBACK_LABEL.

    Refused if it starts with SDY (split_stem would then read the stem the other way round) or
    carries anything a filename or the `<pmid>_<label>` split cannot: the fallback is used.
    """
    label = str(value or "").strip()
    if not _LABEL_RE.fullmatch(label) or label.upper().startswith("SDY"):
        return FALLBACK_LABEL
    return label


def papers_from_rows(rows: list[tuple]) -> list[dict]:
    """Sheet rows (header first) -> one record per PMID, in sheet order.

    A PMID on several rows is one paper: its first row's label files it and every label is kept
    in `study_accessions`. A title is taken from the first row that has one and names a single
    PMID -- the two-PMID row's title, if it had one, would belong to neither.
    """
    if not rows:
        return []
    # "Study_name" on one sheet and "Study Name" on another are the same column.
    header = [str(h or "").strip().rstrip("*").strip().lower().replace("_", " ")
              for h in rows[0]]

    def column(name: str) -> int:
        if name not in header:
            raise ValueError(f"the sheet has no {name!r} column; found {header}")
        return header.index(name)

    pmid_col, title_col, study_col = column("pmid"), column("paper title"), column("study name")

    def at(row: tuple, index: int):
        return row[index] if index < len(row) else None

    papers: dict[str, dict] = {}
    for row in rows[1:]:
        pmids = cell_pmids(at(row, pmid_col))
        label = cell_label(at(row, study_col))
        title = str(at(row, title_col) or "").strip() if len(pmids) == 1 else ""
        for pmid in pmids:
            paper = papers.setdefault(pmid, {"pmid": pmid, "labels": [], "title": ""})
            if label not in paper["labels"]:
                paper["labels"].append(label)
            if title and not paper["title"]:
                paper["title"] = title
    out = []
    for paper in papers.values():
        # A real Study Name beats the fallback whichever row came first.
        named = [label for label in paper["labels"] if label != FALLBACK_LABEL]
        labels = named or paper["labels"]
        out.append({
            "pmid": paper["pmid"],
            "study_accessions": immport_corpus.STUDY_SEP.join(labels),
            "primary_sdy": labels[0],
            "n_studies": len(labels),
            "title": paper["title"],
            "studies": labels,
        })
    return out


def read_sheet(path: Path, sheet: str = SHEET_NAME) -> list[dict]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet not in workbook.sheetnames:
            raise ValueError(f"{path.name} has no sheet {sheet!r}; found {workbook.sheetnames}")
        rows = [tuple(row) for row in workbook[sheet].iter_rows(values_only=True)]
    finally:
        workbook.close()
    return papers_from_rows(rows)


# ── names ────────────────────────────────────────────────────────────────────

def xml_name(pmid: str, label: str) -> str:
    """`<pmid>_<label>.xml`: pmid first, so split_stem reads it back the right way round."""
    return f"{pmid}_{label}.xml"


def pdf_name(pmid: str, label: str) -> str:
    """`<label>_<pmid>.pdf`, the one name assay_service.locate_paper_pdf matches."""
    return f"{label}_{pmid}.pdf"


def existing_pdf(pdf_dir: Path) -> dict[str, Path]:
    """`{pmid: path}` for every PDF already in the folder (AppleDouble twins skipped)."""
    found: dict[str, Path] = {}
    if not pdf_dir.is_dir():
        return found
    for path in sorted(pdf_dir.glob("*.pdf")):
        if path.name.startswith("._"):
            continue
        _, _, pmid = path.stem.rpartition("_")
        if _PMID_RE.fullmatch(pmid):
            found[pmid] = path
    return found


# ── open-access PDF ──────────────────────────────────────────────────────────

def openalex_pdf_urls(work: dict) -> list[str]:
    """The open-access PDF links of one OpenAlex work, best location first, no repeats."""
    locations = [work.get("best_oa_location") or {}]
    locations += [loc for loc in (work.get("locations") or []) if (loc or {}).get("is_oa")]
    urls: list[str] = []
    for location in locations:
        url = (location or {}).get("pdf_url")
        if url and url not in urls:
            urls.append(url)
    return urls


def title_words(title: str) -> list[str]:
    return sorted(set(_WORD_RE.findall((title or "").lower())))


def pdf_problem(data: bytes, title: str) -> str | None:
    """Why these bytes are not this paper's PDF, or None if they are.

    A title with no long words to look for cannot be checked, and is refused rather than waved
    through: the check is the only thing standing between a wrong article and this paper's id.
    """
    if not data.startswith(b"%PDF"):
        return "the reply is not a PDF"
    words = title_words(title)
    if not words:
        return "no title to check the PDF against"
    try:
        text = extract_pdf_text(data, max_chars=TITLE_SEARCH_CHARS).lower()
    except Exception as exc:  # noqa: BLE001 - a corrupt download is an outcome, not a crash
        return f"the PDF could not be read ({type(exc).__name__})"
    if not text.strip():
        return "the PDF has no text layer"
    found = sum(1 for word in words if word in text)
    if found / len(words) < TITLE_MATCH_MIN:
        return f"the PDF does not carry this paper's title ({found}/{len(words)} title words)"
    return None


def fetch_open_pdf(session: requests.Session, pmid: str, title: str) -> tuple[bytes, str] | str:
    """`(pdf bytes, url)` for the first open-access link that yields this paper, else the reason."""
    try:
        response = session.get(OPENALEX_URL.format(pmid=pmid), timeout=60)
        if response.status_code == 404:
            return "no open-access PDF: OpenAlex has no record"
        response.raise_for_status()
        work = response.json()
    except (requests.RequestException, ValueError) as exc:
        return f"request failed: OpenAlex: {exc}"
    urls = openalex_pdf_urls(work)
    if not urls:
        return "no open-access PDF: OpenAlex lists none"
    title = title or str(work.get("title") or "")
    problems = []
    for url in urls:
        try:
            reply = session.get(url, timeout=120, allow_redirects=True)
            reply.raise_for_status()
        except requests.RequestException as exc:
            problems.append(f"{url}: {type(exc).__name__}"
                            + (f" {exc.response.status_code}"
                               if getattr(exc, "response", None) is not None else ""))
            continue
        problem = pdf_problem(reply.content, title)
        if problem is None:
            return reply.content, url
        problems.append(f"{url}: {problem}")
        time.sleep(0.5)
    return "no open-access PDF could be downloaded: " + "; ".join(problems)


def write_bytes(path: Path, data: bytes) -> int:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path.stat().st_size


# ── the run ──────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    parser.add_argument("--sheet-name", default=SHEET_NAME,
                        help=f"worksheet to read (default: {SHEET_NAME!r})")
    parser.add_argument("--skip", nargs="+", default=[], metavar="PMID",
                        help="leave these PMIDs out, e.g. papers another sheet's run already "
                             "holds a registry for")
    parser.add_argument("--papers-dir", type=Path, default=PAPERS_DIR)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be fetched; write and call nothing")
    parser.add_argument("--force", action="store_true", help="refetch papers already on disk")
    parser.add_argument("--no-pdf", action="store_true",
                        help="do not look for an open-access PDF for papers without XML")
    args = parser.parse_args(argv)

    papers_dir: Path = args.papers_dir
    if not papers_dir.parent.is_dir():
        print(f"{papers_dir.parent} does not exist. Mount the drive and run again.",
              file=sys.stderr)
        return 1
    papers = read_sheet(args.sheet, args.sheet_name)
    skipped = [p for p in papers if p["pmid"] in args.skip]
    papers = [p for p in papers if p["pmid"] not in args.skip]
    for paper in skipped:
        print(f"SKIP  {paper['pmid']} ({paper['primary_sdy']})  left out by --skip")
    xml_dir, pdf_dir = papers_dir / immport_corpus.XML_DIR_NAME, papers_dir / PDF_DIR_NAME

    have_xml = {} if args.force else immport_corpus.existing_xml(xml_dir)
    have_pdf = {} if args.force else existing_pdf(pdf_dir)
    to_fetch = [p for p in papers if p["pmid"] not in have_xml]
    print(f"{len(papers)} papers on {args.sheet.name} [{args.sheet_name}]; "
          f"{len(papers) - len(to_fetch)} already have XML in {xml_dir}.\n")
    if args.dry_run:
        print(f"  ask the ID converter : {len(to_fetch)}")
        print(f"  fetch from PMC       : up to {len(to_fetch)}")
        print(f"  open-access PDF      : for those PMC does not carry"
              + (" (off: --no-pdf)" if args.no_pdf else "")
              + f"; {len([p for p in to_fetch if p['pmid'] in have_pdf])} already in {pdf_dir}")
        print("\n--dry-run: nothing written, nothing called.")
        return 0

    xml_dir.mkdir(parents=True, exist_ok=True)
    immport_corpus.write_csv(papers_dir / immport_corpus.PAPERS_ALL_NAME, papers, ALL_COLUMNS)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    #: pmid -> {"pmcid", "file", "bytes"} / {"pmcid", "reason"}
    have: dict[str, dict] = {pmid: {"pmcid": "", "file": path.name,
                                    "bytes": path.stat().st_size}
                             for pmid, path in have_xml.items()}
    lack: dict[str, dict] = {}
    for pmid in have:
        print(f"SKIP  {pmid}  already in xml/")

    # 1. PubMed ID -> PMC id.
    pmcid_of: dict[str, str | None] = {}
    for chunk in _chunks([p["pmid"] for p in to_fetch], immport_corpus.IDCONV_BATCH):
        try:
            pmcid_of.update(idconv(session, chunk))
        except (requests.RequestException, ValueError) as exc:
            for pmid in chunk:
                lack[pmid] = {"pmcid": "", "reason": f"request failed: id converter: {exc}"}
    for paper in to_fetch:
        if paper["pmid"] not in lack and not pmcid_of.get(paper["pmid"]):
            lack[paper["pmid"]] = {"pmcid": "", "reason": immport_corpus.NO_PMC_REASON}

    # 2. Full text.
    fetchable = [p for p in to_fetch if pmcid_of.get(p["pmid"])]
    for batch in _chunks(fetchable, FETCH_BATCH):
        try:
            articleset = fetch_batch(session, [pmcid_of[p["pmid"]] for p in batch])
        except requests.RequestException as exc:
            for paper in batch:
                lack[paper["pmid"]] = {"pmcid": pmcid_of[paper["pmid"]],
                                       "reason": f"request failed: {exc}"}
            continue
        by_pmcid = {}
        for article_xml in split_articleset(articleset):
            record = article_record(article_xml)
            if record.get("pmcid"):
                by_pmcid[record["pmcid"]] = (article_xml, record)
        for paper in batch:
            pmid, pmcid = paper["pmid"], pmcid_of[paper["pmid"]]
            if pmcid not in by_pmcid:
                reason = "PubMed Central returned no article for it"
            else:
                article_xml, record = by_pmcid[pmcid]
                reason = unavailable_reason(article_xml, BeautifulSoup(article_xml, "xml"))
                if reason is None and record.get("pmid") and record["pmid"] != pmid:
                    reason = (f"request failed: idconv/efetch pmid mismatch "
                              f"({pmcid} carries PubMed ID {record['pmid']})")
            if reason:
                lack[pmid] = {"pmcid": pmcid, "reason": reason}
                continue
            target = xml_dir / xml_name(pmid, paper["primary_sdy"])
            size = write_xml(target, article_xml)
            have[pmid] = {"pmcid": pmcid, "file": target.name, "bytes": size}
            print(f"OK    {pmid}  -> xml/{target.name}  ({size:,} bytes)")

    # 3. An open-access PDF for the papers with no XML.
    pdf_rows: list[dict] = []
    for paper in papers:
        pmid = paper["pmid"]
        if pmid in have:
            continue
        outcome = lack.setdefault(pmid, {"pmcid": "", "reason": "not attempted"})
        if pmid in have_pdf:
            path = have_pdf[pmid]
            pdf_rows.append({**paper, "file": path.name, "url": ""})
            outcome["reason"] += f"; PDF on disk: pdf/{path.name}"
            print(f"SKIP  {pmid}  no XML ({outcome['reason']})")
            continue
        if args.no_pdf:
            print(f"FAIL  {pmid}  {outcome['reason']}")
            continue
        got = fetch_open_pdf(session, pmid, paper["title"])
        if isinstance(got, str):
            outcome["reason"] += f"; {got}"
            print(f"FAIL  {pmid}  {outcome['reason']}")
            continue
        data, url = got
        pdf_dir.mkdir(parents=True, exist_ok=True)
        target = pdf_dir / pdf_name(pmid, paper["primary_sdy"])
        size = write_bytes(target, data)
        pdf_rows.append({**paper, "file": target.name, "url": url})
        outcome["reason"] += f"; PDF on disk: pdf/{target.name}"
        print(f"OK    {pmid}  -> pdf/{target.name}  ({size:,} bytes)  <- {url}")

    xml_rows = [{**p, **have[p["pmid"]]} for p in papers if p["pmid"] in have]
    no_xml_rows = [{**p, **lack[p["pmid"]]} for p in papers if p["pmid"] not in have]
    immport_corpus.write_csv(papers_dir / immport_corpus.PAPERS_XML_NAME, xml_rows,
                             immport_corpus.XML_COLUMNS)
    immport_corpus.write_csv(papers_dir / immport_corpus.PAPERS_NO_XML_NAME, no_xml_rows,
                             immport_corpus.NO_XML_COLUMNS)
    immport_corpus.write_csv(papers_dir / PAPERS_PDF_NAME, pdf_rows, PDF_COLUMNS)

    with_pdf = {row["pmid"] for row in pdf_rows}
    neither = [row for row in no_xml_rows if row["pmid"] not in with_pdf]
    print(f"\n{len(papers)} papers: {len(xml_rows)} with XML, {len(pdf_rows)} with a PDF only, "
          f"{len(neither)} with neither.")
    for row in neither:
        print(f"  NEITHER  {row['pmid']} ({row['primary_sdy']}): {row['reason']}")
    print(f"\n  {xml_dir}")
    print(f"  {pdf_dir}")
    print(f"  {papers_dir / immport_corpus.PAPERS_XML_NAME}")
    print(f"  {papers_dir / PAPERS_PDF_NAME}")
    print(f"  {papers_dir / immport_corpus.PAPERS_NO_XML_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
