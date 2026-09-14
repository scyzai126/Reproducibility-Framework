"""Download the JATS XML for a set of papers from NCBI E-utilities.

Two sources of papers are supported:

  * data/studyid_pmcid.xlsx (default) — Study ID + PMC URL columns.
  * --pdf-dir DIR — every ``<StudyID>_<PMID>.pdf`` in DIR; the PMID is resolved
    to a PMCID via the NCBI ID converter.

The raw full-text XML is written to data/JAT_XML/<StudyID>_<pmid>.xml, matching
the naming of the files already in that directory.

Usage:
    python scripts/download_jats_xml.py [--pdf-dir DIR] [--force]

--force refetches papers whose output file already exists (default: skip them).

Prints an OK / SKIP / FAIL line per paper and a closing summary naming every
paper PMC will not serve as full-text XML.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path
from typing import NamedTuple

import openpyxl
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.agent.claim_parser import _extract_pmcid  # noqa: E402
from app.agent.jats_fetcher import unavailable_reason as _unavailable_reason  # noqa: E402
from app.agent.ncbi_utils import pmid_to_pmc_url  # noqa: E402

XLSX_PATH = ROOT / "data" / "studyid_pmcid.xlsx"
OUT_DIR = ROOT / "data" / "JAT_XML"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
REQUEST_DELAY_S = 0.4


class Paper(NamedTuple):
    study_id: str
    pmcid: str | None  # None when the PMID has no PMC record at all
    pmid: str | None  # known up front only for --pdf-dir
    note: str = ""  # non-empty when the paper could not even be resolved


def _load_from_xlsx() -> list[Paper]:
    """Return papers from the Study ID / PMCID columns of the workbook."""
    wb = openpyxl.load_workbook(str(XLSX_PATH), read_only=True, data_only=True)
    ws = wb.active
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    id_col = headers.index("Study ID")
    url_col = headers.index("PMCID")
    papers = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        study_id, url = row[id_col], row[url_col]
        if study_id and url:
            papers.append(Paper(str(study_id).strip(), _extract_pmcid(str(url)), None))
    return papers


def _load_from_pdf_dir(pdf_dir: Path) -> list[Paper]:
    """Return papers from ``<StudyID>_<PMID>.pdf`` filenames, resolving each PMID to a PMCID."""
    papers = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        match = re.fullmatch(r"(.+?)_(\d+)", pdf.stem)
        if not match:
            papers.append(Paper(pdf.stem, None, None, "filename is not <StudyID>_<PMID>.pdf"))
            continue
        study_id, pmid = match.group(1), match.group(2)
        pmc_url = asyncio.run(pmid_to_pmc_url(pmid))
        if not pmc_url:
            papers.append(Paper(study_id, None, pmid, "no PMC record for this PMID"))
            continue
        papers.append(Paper(study_id, _extract_pmcid(pmc_url), pmid))
        time.sleep(REQUEST_DELAY_S)
    return papers


def _existing_output(paper: Paper) -> Path | None:
    """Return the already-downloaded XML for this paper, if any."""
    if paper.pmid:
        path = OUT_DIR / f"{paper.study_id}_{paper.pmid}.xml"
        return path if path.exists() else None
    return next(iter(sorted(OUT_DIR.glob(f"{paper.study_id}_*.xml"))), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        help="directory of <StudyID>_<PMID>.pdf files to download XML for "
        "(default: read data/studyid_pmcid.xlsx)",
    )
    parser.add_argument(
        "--force", action="store_true", help="refetch papers already present in data/JAT_XML"
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.pdf_dir:
        print(f"Resolving PMIDs from {args.pdf_dir} ...")
        papers = _load_from_pdf_dir(args.pdf_dir)
        source = str(args.pdf_dir)
    else:
        papers = _load_from_xlsx()
        source = XLSX_PATH.name
    print(f"{len(papers)} papers from {source}\n")

    failures: list[tuple[str, str, str]] = []
    downloaded = skipped = 0

    for paper in papers:
        label = f"{paper.study_id}  {paper.pmcid or f'PMID {paper.pmid}'}"
        if paper.note:
            print(f"FAIL  {label}  {paper.note}")
            failures.append((paper.study_id, paper.pmcid or f"PMID {paper.pmid}", paper.note))
            continue

        existing = _existing_output(paper)
        if existing and not args.force:
            print(f"SKIP  {label}  -> {existing.name} already present")
            skipped += 1
            continue

        try:
            resp = requests.get(
                EFETCH_URL,
                params={"db": "pmc", "id": paper.pmcid, "rettype": "full", "retmode": "xml"},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"FAIL  {label}  request failed: {exc}")
            failures.append((paper.study_id, paper.pmcid, f"request failed: {exc}"))
            time.sleep(REQUEST_DELAY_S)
            continue

        soup = BeautifulSoup(resp.text, "xml")
        reason = _unavailable_reason(resp.text, soup)
        if reason:
            print(f"FAIL  {label}  {reason}")
            failures.append((paper.study_id, paper.pmcid, reason))
            time.sleep(REQUEST_DELAY_S)
            continue

        pmid = paper.pmid
        if not pmid:
            tag = soup.find("article-id", {"pub-id-type": "pmid"})
            pmid = tag.get_text(strip=True) if tag else paper.pmcid.removeprefix("PMC")
        out_path = OUT_DIR / f"{paper.study_id}_{pmid}.xml"
        out_path.write_text(resp.text, encoding="utf-8")
        print(f"OK    {label}  -> {out_path.name}  ({len(resp.text):,} chars)")
        downloaded += 1
        time.sleep(REQUEST_DELAY_S)

    print(f"\nDownloaded {downloaded}, skipped {skipped}, failed {len(failures)}.")
    if failures:
        print("\nNot available as full-text XML:")
        for study_id, ident, reason in failures:
            print(f"  - {study_id} ({ident}): {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
