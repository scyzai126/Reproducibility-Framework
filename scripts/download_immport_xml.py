#!/usr/bin/env python3
"""Download the full-text XML of every ImmPort paper into one folder, and list who got one.

Input is papers_all.csv (scripts/build_immport_paper_list.py). Output, beside it:

    xml/<SDY>_<pmid>.xml   every full text PubMed Central served, one folder, named the way
                           the assay pipeline reads a paper
    papers_xml.csv         the papers WITH xml:    pmid, study_accessions, primary_sdy, pmcid, file, bytes
    papers_no_xml.csv      the papers WITHOUT one: pmid, study_accessions, primary_sdy, pmcid, reason

Every PMID in papers_all.csv ends up in exactly one of the two lists; papers_no_xml.csv is the
input to the PDF step.

**Free.** NCBI E-utilities only: the ID converter 200 PubMed IDs at a time, then efetch 50 PMC
ids at a time (~7 + ~25 requests for the corpus). No model calls. Set NCBI_API_KEY to raise
NCBI's rate cap from 3 to 10 requests a second and NCBI_EMAIL to give them a contact, as they
ask of bulk callers; neither is required.

**Resumable.** A paper whose file is already in xml/ is skipped, and a paper papers_no_xml.csv
already records as not in PMC, abstract-only or publisher-blocked is not asked about again --
those are facts about the paper. A transport failure is retried on every run. --retry-failed
re-asks the permanent ones too; --force refetches everything.

**The curated corpus is copied, not refetched.** A paper that already has an XML under
data/JAT_XML is copied from there, so the sentence numbering its existing assay registry cites
is the numbering this folder carries.

A paper whose efetch reply carries a different PubMed ID than the one asked for is marked
failed rather than filed: an XML under the wrong id is a correct, verified registry for the
wrong paper.

Usage:
    python3 scripts/download_immport_xml.py [--papers-dir "/Volumes/Extreme SSD/HIPC papers"]
                                            [--dry-run] [--limit N] [--force] [--retry-failed]

--dry-run reads the list and the folder, prints what a run would copy, convert and fetch, and
neither writes nor calls anything. --limit N fetches at most N papers this run.

Prints one OK / COPY / SKIP / FAIL line per paper and a closing summary of the papers without
XML, by reason.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agent import immport_corpus  # noqa: E402
from app.agent.jats_fetcher import unavailable_reason  # noqa: E402
from download_pmc_corpus import (  # noqa: E402
    FETCH_BATCH,
    _params,
    article_record,
    fetch_batch,
    request_delay,
    split_articleset,
)


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def idconv(session: requests.Session, pmids: list[str]) -> dict[str, str | None]:
    """`{pmid: pmcid or None}` for one chunk of PubMed IDs. One request."""
    response = session.get(
        immport_corpus.IDCONV_URL,
        params=_params({"ids": ",".join(pmids), "format": "json"}),
        timeout=60,
    )
    response.raise_for_status()
    time.sleep(request_delay())
    found = immport_corpus.parse_idconv(response.json())
    # An id the converter left out of its reply has no record either.
    return {pmid: found.get(pmid) for pmid in pmids}


def write_xml(path: Path, xml: str) -> int:
    """Write through a sibling temp file so an interrupted write never leaves a half paper
    that the resume logic would count as done."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(xml, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path.stat().st_size


class Run:
    """One pass over the corpus: what each paper's outcome is, and the two lists it implies."""

    def __init__(self, papers: list[dict], xml_dir: Path, previous_no_xml: list[dict]):
        self.papers = papers
        self.xml_dir = xml_dir
        self.by_pmid = {p["pmid"]: p for p in papers}
        #: pmid -> {"pmcid", "file", "bytes"} for papers with XML
        self.have: dict[str, dict] = {}
        #: pmid -> {"pmcid", "reason"} for papers without
        self.lack: dict[str, dict] = {}
        for pmid, file in immport_corpus.existing_xml(xml_dir).items():
            if pmid in self.by_pmid:
                self.have[pmid] = {"pmcid": "", "file": file.name, "bytes": file.stat().st_size}
        for row in previous_no_xml:
            pmid = row.get("pmid", "")
            if pmid in self.by_pmid and pmid not in self.have:
                self.lack[pmid] = {"pmcid": row.get("pmcid", ""), "reason": row.get("reason", "")}
        # pmcid is remembered from a previous papers_xml.csv when there is one.
        self.known_pmcid: dict[str, str] = {}

    def remember_pmcids(self, previous_xml: list[dict]) -> None:
        for row in previous_xml:
            if row.get("pmcid"):
                self.known_pmcid[row["pmid"]] = row["pmcid"]
                if row["pmid"] in self.have and not self.have[row["pmid"]]["pmcid"]:
                    self.have[row["pmid"]]["pmcid"] = row["pmcid"]

    def got(self, pmid: str, pmcid: str | None, file: Path) -> None:
        self.lack.pop(pmid, None)
        self.have[pmid] = {"pmcid": pmcid or self.known_pmcid.get(pmid, ""),
                           "file": file.name, "bytes": file.stat().st_size}

    def missed(self, pmid: str, pmcid: str | None, reason: str) -> None:
        self.have.pop(pmid, None)
        self.lack[pmid] = {"pmcid": pmcid or self.known_pmcid.get(pmid, ""), "reason": reason}

    def rows(self) -> tuple[list[dict], list[dict]]:
        xml_rows, no_xml_rows = [], []
        for paper in self.papers:
            pmid = paper["pmid"]
            base = {"pmid": pmid, "study_accessions": paper["study_accessions"],
                    "primary_sdy": paper["primary_sdy"]}
            if pmid in self.have:
                xml_rows.append({**base, **self.have[pmid]})
            else:
                outcome = self.lack.get(pmid, {"pmcid": "", "reason": "not attempted"})
                no_xml_rows.append({**base, **outcome})
        return xml_rows, no_xml_rows

    def write_lists(self, papers_dir: Path) -> None:
        xml_rows, no_xml_rows = self.rows()
        immport_corpus.write_csv(papers_dir / immport_corpus.PAPERS_XML_NAME, xml_rows,
                                 immport_corpus.XML_COLUMNS)
        immport_corpus.write_csv(papers_dir / immport_corpus.PAPERS_NO_XML_NAME, no_xml_rows,
                                 immport_corpus.NO_XML_COLUMNS)


def plan(run: Run, force: bool, retry_failed: bool) -> tuple[list[dict], list[dict]]:
    """`(to_copy, to_fetch)`: the papers this run touches, in list order."""
    to_copy, to_fetch = [], []
    for paper in run.papers:
        pmid = paper["pmid"]
        if pmid in run.have and not force:
            continue
        if pmid in run.lack and not force and not retry_failed \
                and immport_corpus.is_permanent(run.lack[pmid]["reason"]):
            continue
        if immport_corpus.benchmark_xml(pmid, paper["studies"]) is not None:
            to_copy.append(paper)
        else:
            to_fetch.append(paper)
    return to_copy, to_fetch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--papers-dir", type=Path, default=immport_corpus.PAPERS_DIR,
                        help=f"folder holding papers_all.csv (default: {immport_corpus.PAPERS_DIR})")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be copied and fetched; write and call nothing")
    parser.add_argument("--limit", type=int, default=0, metavar="N",
                        help="fetch at most N papers this run (0 = no limit)")
    parser.add_argument("--force", action="store_true",
                        help="refetch papers already in xml/ and re-ask about every failure")
    parser.add_argument("--retry-failed", action="store_true",
                        help="re-ask NCBI about papers papers_no_xml.csv already records as "
                             "not in PMC, abstract-only or blocked")
    args = parser.parse_args()

    papers_dir: Path = args.papers_dir
    all_path = papers_dir / immport_corpus.PAPERS_ALL_NAME
    if not papers_dir.is_dir() or not all_path.exists():
        print(f"No {immport_corpus.PAPERS_ALL_NAME} under {papers_dir}.\n"
              "Mount the drive and run scripts/build_immport_paper_list.py first.",
              file=sys.stderr)
        return 1

    papers = immport_corpus.read_papers(all_path)
    xml_dir = papers_dir / immport_corpus.XML_DIR_NAME
    run = Run(papers, xml_dir,
              immport_corpus.read_csv(papers_dir / immport_corpus.PAPERS_NO_XML_NAME))
    run.remember_pmcids(immport_corpus.read_csv(papers_dir / immport_corpus.PAPERS_XML_NAME))
    to_copy, to_fetch = plan(run, args.force, args.retry_failed)
    skipped = len(papers) - len(to_copy) - len(to_fetch)
    limited = 0
    if args.limit > 0:
        limited = max(0, len(to_fetch) - args.limit)
        to_fetch = to_fetch[:args.limit]

    print(f"{len(papers)} papers in {_display(all_path)}; {len(run.have)} already have XML, "
          f"{len(run.lack)} recorded without.\n")
    if args.dry_run:
        need_idconv = [p for p in to_fetch if p["pmid"] not in run.known_pmcid]
        print(f"  copy from data/JAT_XML : {len(to_copy)}")
        print(f"  skip (done or settled) : {skipped}")
        print(f"  ask the ID converter   : {len(need_idconv)} "
              f"(~{math.ceil(len(need_idconv) / immport_corpus.IDCONV_BATCH)} requests)")
        print(f"  fetch from PMC         : up to {len(to_fetch)} "
              f"(~{math.ceil(len(to_fetch) / FETCH_BATCH)} requests)")
        print("\n--dry-run: nothing written, nothing called.")
        return 0

    xml_dir.mkdir(parents=True, exist_ok=True)
    copied = fetched = 0
    reasons: dict[str, int] = {}

    def note(reason: str) -> None:
        key = reason.split(" (")[0]
        reasons[key] = reasons.get(key, 0) + 1

    # 1. Curated corpus: copy.
    for paper in to_copy:
        pmid = paper["pmid"]
        source = immport_corpus.benchmark_xml(pmid, paper["studies"])
        target = xml_dir / immport_corpus.xml_name(paper["primary_sdy"], pmid)
        shutil.copyfile(source, target)
        run.got(pmid, None, target)
        copied += 1
        print(f"COPY  {pmid}  <- {_display(source)}")
    if to_copy:
        run.write_lists(papers_dir)

    session = requests.Session()

    # 2. PubMed ID -> PMC id, 200 at a time.
    pmcid_of: dict[str, str | None] = {p["pmid"]: run.known_pmcid[p["pmid"]]
                                       for p in to_fetch if p["pmid"] in run.known_pmcid}
    need = [p["pmid"] for p in to_fetch if p["pmid"] not in pmcid_of]
    for chunk in _chunks(need, immport_corpus.IDCONV_BATCH):
        try:
            pmcid_of.update(idconv(session, chunk))
        except (requests.RequestException, ValueError) as exc:
            for pmid in chunk:
                reason = f"request failed: id converter: {exc}"
                run.missed(pmid, None, reason)
                note(reason)
                print(f"FAIL  {pmid}  {reason}")
            run.write_lists(papers_dir)
            continue
        for pmid in chunk:
            if pmcid_of.get(pmid) is None:
                run.missed(pmid, None, immport_corpus.NO_PMC_REASON)
                note(immport_corpus.NO_PMC_REASON)
                print(f"FAIL  {pmid}  {immport_corpus.NO_PMC_REASON}")
        run.write_lists(papers_dir)

    # 3. Full text, 50 at a time.
    fetchable = [p for p in to_fetch if pmcid_of.get(p["pmid"])]
    for batch in _chunks(fetchable, FETCH_BATCH):
        pmcids = [pmcid_of[p["pmid"]] for p in batch]
        try:
            articleset = fetch_batch(session, pmcids)
        except requests.RequestException as exc:
            for paper in batch:
                reason = f"request failed: {exc}"
                run.missed(paper["pmid"], pmcid_of[paper["pmid"]], reason)
                note(reason)
                print(f"FAIL  {paper['pmid']}  {reason}")
            run.write_lists(papers_dir)
            continue

        by_pmcid: dict[str, tuple[str, dict]] = {}
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
                run.missed(pmid, pmcid, reason)
                note(reason)
                print(f"FAIL  {pmid}  {reason}")
                continue
            target = xml_dir / immport_corpus.xml_name(paper["primary_sdy"], pmid)
            size = write_xml(target, article_xml)
            run.got(pmid, pmcid, target)
            fetched += 1
            print(f"OK    {pmid}  -> {target.name}  ({size:,} bytes)")
        run.write_lists(papers_dir)

    run.write_lists(papers_dir)
    xml_rows, no_xml_rows = run.rows()
    print(f"\nFetched {fetched}, copied {copied}, skipped {skipped} already settled"
          + (f", {limited} left for the next run by --limit" if limited else "")
          + f"; {len(xml_rows)} papers with XML, {len(no_xml_rows)} without.")
    if reasons:
        print("\nNo XML this run, by reason:")
        for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {n:5d}  {reason}")
    print(f"\n  {xml_dir}")
    print(f"  {papers_dir / immport_corpus.PAPERS_XML_NAME}")
    print(f"  {papers_dir / immport_corpus.PAPERS_NO_XML_NAME}   <- the PDF step's input")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
