#!/usr/bin/env python3
"""Download the benchmark papers' supplementary files and find their supplementary methods.

Free: no model is called. For each paper under data/benchmark_agent_assays/<result version>/ this

  1. reads the PMCID and the supplementary files the JATS XML lists (a PDF-only paper has no
     XML, so its PMCID is asked of NCBI's ID converter and nothing is listed),
  2. downloads the paper's supplement archive from Europe PMC into
     data/supplements/<SDY>_<pmid>/files/ -- skipped when that folder already holds files, so
     a run resumes, and a file put there by hand is picked up the same way,
  3. reads every PDF and .docx in it and writes data/supplements/<SDY>_<pmid>/supplement.txt
     in the chain's own source format, methods blocks first,
  4. writes data/supplements/manifest.csv (one row per file) and summary.csv (one per paper).

Usage:
    python3 scripts/download_paper_supplements.py                 # all papers
    python3 scripts/download_paper_supplements.py --only SDY1373  # some
    python3 scripts/download_paper_supplements.py --no-download   # re-read what is on disk
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.agent import assay_service, paper_supplements as ps  # noqa: E402
from app.agent.assay_extractor import MIN_METHODS_CHARS  # noqa: E402

RESULT_VERSION = "assay_result_v3"
USER_AGENT = "paper-supplement-downloader/1.0"
IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
REQUEST_DELAY_S = 1.0

MANIFEST_FIELDS = ["study_accession", "pubmed_id", "pmcid", "file", "kind", "bytes",
                   "listed_in_xml", "source_url", "status"]
SUMMARY_FIELDS = ["study_accession", "pubmed_id", "pmcid", "paper_source", "listed_in_xml",
                  "download", "files", "readable_files", "text_chars", "methods_chars",
                  "has_supplementary_methods", "methods_headings", "note"]


def benchmark_papers(version: str) -> list[tuple[str, str]]:
    """(pmid, SDY) for every registry folder of the result version, in folder order."""
    root = assay_service.CORPUS_ROOT / version
    papers = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        stem = folder.name.removesuffix(assay_service.PDF_DIR_SUFFIX)
        ids = assay_service.split_stem(stem)
        if ids:
            papers.append(ids)
    return papers


def lookup_pmcid(session: requests.Session, pmid: str) -> str | None:
    response = session.get(IDCONV_URL, params={"ids": pmid, "format": "json"}, timeout=30)
    time.sleep(REQUEST_DELAY_S)
    if response.status_code != 200:
        return None
    records = response.json().get("records", [])
    return records[0].get("pmcid") if records else None


def files_on_disk(files_dir: Path) -> list[Path]:
    """The supplement files a paper has. An empty file is a placeholder, not a file."""
    if not files_dir.is_dir():
        return []
    return sorted(p for p in files_dir.glob("*") if p.is_file() and p.stat().st_size > 0)


def download(session: requests.Session, pmcid: str, dest: Path) -> tuple[str, str]:
    """Fetch and unpack one paper's archive. Returns (status, source url)."""
    url = ps.EPMC_SUPPLEMENT_URL.format(pmcid=pmcid)
    try:
        response = session.get(url, timeout=300)
    except requests.RequestException as exc:
        return f"failed: {type(exc).__name__}", url
    finally:
        time.sleep(REQUEST_DELAY_S)
    if response.status_code == 404:
        return "none_at_europepmc", url
    if response.status_code != 200:
        return f"failed: HTTP {response.status_code}", url
    if b"not open access" in response.content[:600]:
        # Europe PMC serves supplements for open-access articles only. An NIH author
        # manuscript is in PMC but not open access, and PMC's own file URLs sit behind a
        # proof-of-work page meant to stop scripted downloads -- so these are fetched by hand.
        return "not_open_access", url
    try:
        written = ps.safe_extract(response.content, dest)
        # MDPI ships the whole supplement as one zip inside the archive: open that one level.
        for path in written:
            if path.suffix.lower() == ".zip":
                try:
                    ps.safe_extract(path.read_bytes(), dest)
                except Exception:  # noqa: BLE001 - a data zip we cannot open stays as it is
                    pass
    except Exception as exc:  # noqa: BLE001 - not a zip, or a broken one
        return f"failed: {type(exc).__name__}", url
    if not files_on_disk(dest):
        # A 200 with a well-formed zip of nothing but zero-byte members: what Europe PMC sends
        # for some author manuscripts in place of the "not open access" reply.
        return "failed: empty archive", url
    return "ok", url


def manual_url(pmcid: str, href: str) -> str:
    """Where a browser finds one supplementary file on PMC."""
    return f"https://pmc.ncbi.nlm.nih.gov/articles/instance/{pmcid.removeprefix('PMC')}/bin/{href}"


def process(session, pmid: str, sdy: str, do_download: bool) -> tuple[dict, list[dict]]:
    xml_path = assay_service.locate_paper_xml(pmid, sdy)
    raw = xml_path.read_bytes() if xml_path else None
    pmcid = ps.pmcid_from_xml(raw) if raw else lookup_pmcid(session, pmid)
    listed = ps.listed_supplements(raw) if raw else []
    listed_names = {Path(item["href"]).name for item in listed if item["href"]}

    paper_dir = ps.SUPPLEMENT_ROOT / f"{sdy}_{pmid}"
    files_dir = paper_dir / "files"
    on_disk = files_on_disk(files_dir)

    url = ps.EPMC_SUPPLEMENT_URL.format(pmcid=pmcid) if pmcid else ""
    if on_disk:
        status = "on_disk"
    elif not pmcid:
        status = "no_pmcid"
    elif not do_download:
        status = "not_downloaded"
    else:
        status, url = download(session, pmcid, files_dir)
        on_disk = files_on_disk(files_dir)

    rows = [{
        "study_accession": sdy, "pubmed_id": pmid, "pmcid": pmcid or "", "file": path.name,
        "kind": ps.file_kind(path.name), "bytes": path.stat().st_size,
        "listed_in_xml": path.name in listed_names, "source_url": url, "status": "ok",
    } for path in on_disk]
    have = {path.name for path in on_disk}
    for item in listed:
        name = Path(item["href"]).name if item["href"] else ""
        if name in have:
            continue
        rows.append({
            "study_accession": sdy, "pubmed_id": pmid, "pmcid": pmcid or "",
            "file": name or f"(no file; {item['caption'][:120]})",
            "kind": ps.file_kind(name) if name else "", "bytes": "", "listed_in_xml": True,
            "source_url": manual_url(pmcid, item["href"]) if pmcid and name else "",
            "status": "manual",
        })

    copies = {Path(item["href"]).name for item in listed
              if item["href"] and ps.is_article_copy(item["caption"])}
    texts = [(path.name, ps.file_text(path)) for path in on_disk
             if ps.is_readable(path.name) and path.name not in copies]
    texts = [(name, text) for name, text in texts if text.strip()]
    blocks = [block for _, text in texts for block in ps.split_blocks(text)]
    methods = ps.methods_chars(blocks)
    rendered = ps.render(texts)
    target = paper_dir / "supplement.txt"
    if rendered:
        paper_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    elif target.exists():
        target.unlink()

    notes = []
    if any(not item["href"] for item in listed):
        notes.append("XML points at a supplement PMC does not hold")
    if copies:
        notes.append("article-plus-supplement copy not read: " + ", ".join(sorted(copies)))
    unread = [p.name for p in on_disk if ps.file_kind(p.name) == "doc"]
    if unread:
        notes.append("legacy .doc not read: " + ", ".join(unread))
    summary = {
        "study_accession": sdy, "pubmed_id": pmid, "pmcid": pmcid or "",
        "paper_source": "xml" if raw else "pdf", "listed_in_xml": len(listed),
        "download": status, "files": len(on_disk), "readable_files": len(texts),
        "text_chars": sum(len(text) for _, text in texts), "methods_chars": methods,
        "has_supplementary_methods": methods >= MIN_METHODS_CHARS,
        "methods_headings": " | ".join(dict.fromkeys(
            b["heading"] for b in blocks if b["bucket"] == "methods")),
        "note": "; ".join(notes),
    }
    return summary, rows


def _merge(path: Path, fields: list[str], new_rows: list[dict], touched: set) -> None:
    """Rewrite a CSV keeping the rows of papers this run did not touch."""
    kept = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            kept = [row for row in csv.DictReader(handle)
                    if (row["study_accession"], row["pubmed_id"]) not in touched]
    rows = sorted(kept + new_rows, key=lambda r: (r["study_accession"], r["pubmed_id"]))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_manual_list() -> None:
    """manual_downloads.csv: what a person has to fetch in a browser, and where to put it.

    Read back from the two CSVs, so it covers every paper and not only this run's. One row per
    listed file that is not on disk, and one per paper whose XML is not in the repo (a
    PDF-only paper lists nothing, so only its article page can be given).
    """
    root = ps.SUPPLEMENT_ROOT
    with (root / "manifest.csv").open(newline="", encoding="utf-8") as handle:
        missing = [row for row in csv.DictReader(handle) if row["status"] == "manual"]
    with (root / "summary.csv").open(newline="", encoding="utf-8") as handle:
        papers = list(csv.DictReader(handle))
    rows = []
    for row in missing:
        folder = f"data/supplements/{row['study_accession']}_{row['pubmed_id']}/files/"
        rows.append({"study_accession": row["study_accession"], "pubmed_id": row["pubmed_id"],
                     "file": row["file"], "kind": row["kind"], "url": row["source_url"],
                     "article_page": _article_page(row["pmcid"], row["pubmed_id"]),
                     "save_into": folder})
    for paper in papers:
        if paper["paper_source"] == "pdf" and paper["files"] == "0":
            folder = f"data/supplements/{paper['study_accession']}_{paper['pubmed_id']}/files/"
            rows.append({"study_accession": paper["study_accession"],
                         "pubmed_id": paper["pubmed_id"],
                         "file": "(no XML in the repo: see the article page)", "kind": "",
                         "url": "", "save_into": folder,
                         "article_page": _article_page(paper["pmcid"], paper["pubmed_id"])})
    rows.sort(key=lambda r: (r["study_accession"], r["pubmed_id"], r["file"]))
    with (root / "manual_downloads.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["study_accession", "pubmed_id", "file",
                                                    "kind", "url", "article_page", "save_into"])
        writer.writeheader()
        writer.writerows(rows)


def _article_page(pmcid: str, pmid: str) -> str:
    if pmcid:
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", nargs="+", metavar="SDY", help="study accessions to process")
    parser.add_argument("--no-download", action="store_true",
                        help="make no supplement download; re-read the files already on disk")
    parser.add_argument("--result-version", default=RESULT_VERSION)
    args = parser.parse_args()

    papers = benchmark_papers(args.result_version)
    if args.only:
        papers = [(pmid, sdy) for pmid, sdy in papers if sdy in set(args.only)]
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    summaries, manifest = [], []
    for pmid, sdy in papers:
        summary, rows = process(session, pmid, sdy, not args.no_download)
        summaries.append(summary)
        manifest.extend(rows)
        print(f"{sdy:8} {pmid:9} {summary['pmcid'] or '-':11} listed={summary['listed_in_xml']:<3}"
              f" {summary['download']:20} files={summary['files']:<3}"
              f" readable={summary['readable_files']:<2} text={summary['text_chars']:<8}"
              f" methods={summary['methods_chars']:<7}"
              f" {'SUPP-METHODS' if summary['has_supplementary_methods'] else ''}"
              f" {summary['note']}")

    ps.SUPPLEMENT_ROOT.mkdir(parents=True, exist_ok=True)
    touched = {(sdy, pmid) for pmid, sdy in papers}
    _merge(ps.SUPPLEMENT_ROOT / "manifest.csv", MANIFEST_FIELDS, manifest, touched)
    _merge(ps.SUPPLEMENT_ROOT / "summary.csv", SUMMARY_FIELDS, summaries, touched)
    write_manual_list()
    with_methods = [s for s in summaries if s["has_supplementary_methods"]]
    print(f"\n{len(summaries)} papers, {sum(1 for s in summaries if s['files'])} with files on "
          f"disk, {sum(1 for s in summaries if s['readable_files'])} with readable text, "
          f"{len(with_methods)} with supplementary methods")
    return 0


if __name__ == "__main__":
    sys.exit(main())
