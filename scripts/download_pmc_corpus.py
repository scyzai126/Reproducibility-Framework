"""Download a topic corpus of JATS XML straight from PubMed Central.

Unlike scripts/download_jats_xml.py, which fetches a known list of papers named in
data/studyid_pmcid.xlsx, this script *discovers* its papers: it runs an E-utilities search over
db=pmc and downloads the top N hits that PMC will actually serve as full text. The built-in
query is vaccination immunology, 2015 onwards, open-access only.

Papers land in data/JAT_XML_vaccine1000/PMC<pmcid>_<pmid>.xml alongside a manifest.jsonl -- a
separate directory from data/JAT_XML/, deliberately. The curated corpus is named
``<StudyID>_<pmid>.xml`` and assay_service.split_stem tells the two halves apart by an "SDY"
prefix, so a PMC-named file dropped in there would read back with its identifiers inverted, and
run_assay_batch.py would sweep all of these on its next run.

**Two things a search corpus has to get right, and both cost extra requests:**

  * Being inside PMC's open-access filter does not mean the full text is downloadable. A share
    of hits come back abstract-only or publisher-blocked, so asking for exactly N PMCIDs yields
    noticeably fewer than N files. This pages through the ranked hit list and keeps going until
    N usable papers are on disk.
  * Very recent articles and preprints deposited in PMC often carry no PubMed ID at all. Those
    are skipped rather than filed under a placeholder, so every filename holds two real ids.

No model calls. E-utilities only, which is free.

Usage:
    python scripts/download_pmc_corpus.py [--limit N] [--out-dir DIR] [--query Q]
                                          [--force] [--dry-run]

--dry-run runs only the search and prints how many papers match, writing nothing.
--force refetches papers already present in the output directory and rewrites the manifest.

Set NCBI_API_KEY in the environment to raise NCBI's rate cap from 3 to 10 requests a second;
it is not required. Set NCBI_EMAIL to give NCBI a contact address, as they ask of bulk users.

Prints an OK / SKIP / FAIL line per paper and a closing summary of why papers were rejected.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.agent.jats_fetcher import unavailable_reason as _unavailable_reason  # noqa: E402

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

OUT_DIR = ROOT / "data" / "JAT_XML_vaccine1000"
MANIFEST_NAME = "manifest.jsonl"

#: Vaccination immunology: a vaccine term AND an immune-readout term, so that policy, coverage
#: and hesitancy papers -- which match "vaccination" just as well -- stay out of the corpus.
DEFAULT_QUERY = (
    "(vaccine[Title/Abstract] OR vaccination[Title/Abstract] OR immunization[Title/Abstract])"
    ' AND (immunogenicity[Title/Abstract] OR antibody[Title/Abstract]'
    ' OR "immune response"[Title/Abstract])'
    ' AND "open access"[filter]'
    " AND 2015:2026[pdat]"
)

DEFAULT_LIMIT = 1000
SEARCH_PAGE = 200  # PMCIDs per esearch page
FETCH_BATCH = 50  # PMCIDs per efetch; ~25 requests for 1000 papers instead of 1000

#: NCBI allows three requests a second without an API key and ten with one.
REQUEST_DELAY_S = 0.4
REQUEST_DELAY_WITH_KEY_S = 0.11

TOOL = "claim_reproduce_agent"

#: Output filenames, and the source of truth for which papers are already on disk.
_OUTPUT_RE = re.compile(r"(PMC\d+)_(\d+)")

#: recover=True because one malformed article in a 50-article batch should cost that article and
#: not the batch; no_network/resolve_entities because the response carries a DTD reference we have
#: no reason to follow.
_PARSER = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True)


def api_key() -> str | None:
    return os.environ.get("NCBI_API_KEY", "").strip() or None


def request_delay() -> float:
    return REQUEST_DELAY_WITH_KEY_S if api_key() else REQUEST_DELAY_S


def _params(extra: dict) -> dict:
    """E-utilities parameters, with the identification NCBI asks of bulk callers."""
    params = {"tool": TOOL, **extra}
    email = os.environ.get("NCBI_EMAIL", "").strip()
    if email:
        params["email"] = email
    key = api_key()
    if key:
        params["api_key"] = key
    return params


def search_count(session: requests.Session, query: str) -> int:
    """How many papers match the query. One request, writes nothing -- what --dry-run reports."""
    response = session.get(
        ESEARCH_URL, params=_params({"db": "pmc", "term": query, "retmax": 0}), timeout=30
    )
    response.raise_for_status()
    time.sleep(request_delay())
    soup = BeautifulSoup(response.text, "xml")
    count = soup.find("Count")
    return int(count.get_text(strip=True)) if count else 0


def search_page(session: requests.Session, query: str, retstart: int) -> tuple[list[str], int]:
    """One page of PMCIDs in relevance order, plus the total hit count."""
    response = session.get(
        ESEARCH_URL,
        params=_params(
            {
                "db": "pmc",
                "term": query,
                "sort": "relevance",
                "retstart": retstart,
                "retmax": SEARCH_PAGE,
            }
        ),
        timeout=30,
    )
    response.raise_for_status()
    time.sleep(request_delay())
    soup = BeautifulSoup(response.text, "xml")
    ids = [f"PMC{tag.get_text(strip=True)}" for tag in soup.find_all("Id")]
    count_tag = soup.find("Count")
    return ids, int(count_tag.get_text(strip=True)) if count_tag else 0


def candidates(session: requests.Session, query: str):
    """Yield PMCIDs in relevance order, paging lazily.

    A generator rather than a list because how many candidates it takes to reach N usable papers
    is not knowable up front -- the caller stops pulling when it has enough, and no page is
    requested that nothing needed.
    """
    retstart = 0
    while True:
        ids, total = search_page(session, query, retstart)
        if not ids:
            return
        yield from ids
        retstart += len(ids)
        if retstart >= total:
            return


def fetch_batch(session: requests.Session, pmcids: list[str]) -> str:
    """Full text for up to FETCH_BATCH papers as one <pmc-articleset>.

    POST because a 50-id list is too long to want in a URL.
    """
    response = session.post(
        EFETCH_URL,
        data=_params({"db": "pmc", "id": ",".join(pmcids), "rettype": "full", "retmode": "xml"}),
        timeout=120,
    )
    response.raise_for_status()
    time.sleep(request_delay())
    return response.text


def split_articleset(xml: str) -> list[str]:
    """Split a <pmc-articleset> into standalone per-article XML documents.

    lxml carries the namespace declarations that were in scope on the articleset root (xlink,
    mml) down onto each article element as it serializes it, so each string parses on its own --
    which is what jats_parser and every downstream pass will get handed.
    """
    root = etree.fromstring(xml.encode("utf-8"), _PARSER)
    if root is None:
        return []
    articles = [root] if etree.QName(root).localname == "article" else root.findall("article")
    out = []
    for article in articles:
        # Whitespace between articles becomes trailing text after the new root, which is not
        # well-formed.
        article.tail = None
        out.append(etree.tostring(article, xml_declaration=True, encoding="utf-8").decode("utf-8"))
    return out


def article_record(xml: str) -> dict:
    """The manifest fields for one article: ids and front-matter metadata.

    Everything is read out of <front>, never the whole document: <article-id> and
    <article-title> both occur again inside every <ref> in the bibliography, and a document-wide
    find would return a cited paper's identifiers for this one.
    """
    soup = BeautifulSoup(xml, "xml")
    article = soup.find("article")
    meta = article.find("article-meta") if article else None
    journal_meta = article.find("journal-meta") if article else None
    if meta is None:
        return {"pmcid": None, "pmid": None}

    ids = {
        tag.get("pub-id-type"): tag.get_text(strip=True) for tag in meta.find_all("article-id")
    }
    title_group = meta.find("title-group")
    title_tag = title_group.find("article-title") if title_group else None

    journal = None
    if journal_meta:
        tag = journal_meta.find("journal-title") or journal_meta.find(
            "journal-id", {"journal-id-type": "nlm-ta"}
        )
        journal = tag.get_text(" ", strip=True) if tag else None

    year = None
    for pub_date in meta.find_all("pub-date"):
        year_tag = pub_date.find("year")
        if year_tag:
            year = year_tag.get_text(strip=True)
            break

    license_tag = meta.find("license")
    license_ref = meta.find("license_ref")
    if license_ref:
        license_value = license_ref.get_text(strip=True)
    elif license_tag and license_tag.get("license-type"):
        license_value = license_tag.get("license-type")
    else:
        link = license_tag.find("ext-link") if license_tag else None
        license_value = link.get_text(strip=True) if link else None

    return {
        "pmcid": ids.get("pmcid") or (f"PMC{ids['pmcaid']}" if ids.get("pmcaid") else None),
        "pmid": ids.get("pmid"),
        "doi": ids.get("doi"),
        "title": title_tag.get_text(" ", strip=True) if title_tag else None,
        "journal": journal,
        "year": year,
        "license": license_value,
    }


def output_name(pmcid: str, pmid: str) -> str:
    """`PMC9459166_36091148.xml` -- both identifiers, PMCID first."""
    return f"{pmcid}_{pmid}.xml"


def existing_pmcids(out_dir: Path) -> set[str]:
    """PMCIDs already downloaded, so a resumed run neither refetches nor recounts them."""
    found = set()
    for path in out_dir.glob("PMC*_*.xml"):
        match = _OUTPUT_RE.fullmatch(path.stem)
        if match:
            found.add(match.group(1))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help=f"papers to download (default {DEFAULT_LIMIT})"
    )
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR, help=f"default: {OUT_DIR}")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="E-utilities query (default: vaccination immunology, 2015+, open access)")
    parser.add_argument("--force", action="store_true", help="refetch papers already on disk")
    parser.add_argument(
        "--dry-run", action="store_true", help="print how many papers match and exit"
    )
    args = parser.parse_args()

    session = requests.Session()

    print(f"Query: {args.query}\n")
    if args.dry_run:
        print(f"{search_count(session, args.query):,} papers match. Nothing downloaded.")
        return 0

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    already = set() if args.force else existing_pmcids(out_dir)
    if already:
        print(f"{len(already)} papers already in {out_dir}; resuming.\n")

    manifest = (out_dir / MANIFEST_NAME).open("w" if args.force else "a", encoding="utf-8")

    written = skipped = 0
    rejected: list[tuple[str, str]] = []
    batch: list[str] = []

    def have() -> int:
        return written + skipped

    def flush(batch: list[str]) -> None:
        nonlocal written
        try:
            articleset = fetch_batch(session, batch)
        except requests.RequestException as exc:
            for pmcid in batch:
                print(f"FAIL  {pmcid}  request failed: {exc}")
                rejected.append((pmcid, f"request failed: {exc}"))
            return

        by_pmcid = {}
        for article_xml in split_articleset(articleset):
            record = article_record(article_xml)
            if record["pmcid"]:
                by_pmcid[record["pmcid"]] = (article_xml, record)

        for pmcid in batch:
            if have() >= args.limit:
                return
            if pmcid not in by_pmcid:
                # An articleset-level <error> is a sibling of the articles and does not survive
                # the split, so a missing article is how this loop learns the fetch failed.
                print(f"FAIL  {pmcid}  PubMed Central returned no article for it")
                rejected.append((pmcid, "PubMed Central returned no article for it"))
                continue

            article_xml, record = by_pmcid[pmcid]
            reason = _unavailable_reason(article_xml, BeautifulSoup(article_xml, "xml"))
            if reason:
                print(f"FAIL  {pmcid}  {reason}")
                rejected.append((pmcid, reason))
                continue
            if not record["pmid"]:
                reason = "no PubMed ID on record (too recent to be indexed, or a preprint)"
                print(f"FAIL  {pmcid}  {reason}")
                rejected.append((pmcid, reason))
                continue

            path = out_dir / output_name(pmcid, record["pmid"])
            path.write_text(article_xml, encoding="utf-8")
            manifest.write(
                json.dumps(
                    {**record, "bytes": len(article_xml), "filename": path.name},
                    ensure_ascii=False,
                )
                + "\n"
            )
            manifest.flush()
            written += 1
            print(f"OK    {pmcid}  -> {path.name}  ({len(article_xml):,} chars)  [{have()}/{args.limit}]")

    exhausted = True
    for pmcid in candidates(session, args.query):
        if have() >= args.limit:
            exhausted = False
            break
        if pmcid in already:
            skipped += 1
            continue
        batch.append(pmcid)
        if len(batch) >= FETCH_BATCH:
            flush(batch)
            batch = []
    if batch and have() < args.limit:
        flush(batch)

    manifest.close()

    print(f"\nDownloaded {written}, skipped {skipped} already present, rejected {len(rejected)}.")
    if rejected:
        reasons: dict[str, int] = {}
        for _, reason in rejected:
            key = reason.split(" (")[0]
            reasons[key] = reasons.get(key, 0) + 1
        print("\nRejected, by reason:")
        for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}  {reason}")
    if exhausted and have() < args.limit:
        print(
            f"\nThe search ran out of candidates at {have()} of {args.limit}. "
            "Broaden --query or widen the date range to go further."
        )
    print(f"\n{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
