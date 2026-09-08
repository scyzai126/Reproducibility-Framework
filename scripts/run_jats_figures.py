"""Extract claims using JATS XML text (clean, structured, boilerplate-stripped) combined
with rendered PDF pages for each figure (so the model can read plot/chart content that
figure captions alone don't capture).

Usage:
  python scripts/run_jats_figures.py --pdf data/pdf/SDY1669.pdf --study SDY1669
  python scripts/run_jats_figures.py --pdf data/pdf/SDY1669.pdf --study SDY1669 --pmid 33637673
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import (
    PaperNotAvailableError,
    _get_client,
    _load_prompt,
    _strip_fences,
    fetch_paper_content_async,
    get_paper_url,
)
from app.agent.pdf_vision import (
    extract_claims_from_jats_and_figures,
    extract_figure_labels,
    extract_table_labels,
    find_label_pages,
)
from app.config import settings

REPO_ROOT = Path(__file__).parent
IMMPORT_XLSX = REPO_ROOT / "data" / "ImmuneSigResource_1_studies.xlsx"
PMCID_XLSX = REPO_ROOT / "data" / "studyid_pmcid.xlsx"
OUT_DIR = REPO_ROOT / "data" / "claims"


def _pmcid_to_pmid(pmcid: str) -> str:
    """Convert a numeric PMC ID to a PubMed ID via NCBI elink."""
    import requests
    url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
        f"?dbfrom=pmc&db=pubmed&id={pmcid}&retmode=json"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    try:
        links = data["linksets"][0]["linksetdbs"]
        for db in links:
            if db["dbto"] == "pubmed" and db["linkname"] == "pmc_pubmed":
                return str(db["links"][0])
    except (KeyError, IndexError):
        pass
    raise ValueError(f"No PubMed ID found for PMCID {pmcid}")


def _lookup_pmid(study_id: str) -> str | None:
    """Try to find a PubMed ID for a study from either XLSX, resolving PMC IDs if needed."""
    for xlsx_path in (IMMPORT_XLSX, PMCID_XLSX):
        if not xlsx_path.exists():
            continue
        wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
        ws = wb.active
        headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        for row in ws.iter_rows(min_row=2, values_only=True):
            row_dict = dict(zip(headers, row))
            sid = str(row_dict.get("Study ID") or row_dict.get(headers[0]) or "").strip()
            if sid != study_id:
                continue
            pmid = str(row_dict.get("PubMed ID") or "").strip()
            if pmid and pmid != "None":
                return pmid.split(";")[0].strip()
            pmcid_url = str(row_dict.get("PMCID") or "").strip()
            m = re.search(r"PMC(\d+)", pmcid_url, re.IGNORECASE)
            if m:
                try:
                    return _pmcid_to_pmid(m.group(1))
                except Exception:
                    return f"PMC{m.group(1)}"
    return None


async def _run_step2(client, claims: dict) -> dict:
    """Classify groups for each claim (Step 2)."""
    template = _load_prompt("classify_groups.txt")
    groups: dict = {}
    claim_keys = [k for k in claims if k.startswith("claim_")]
    for i, key in enumerate(claim_keys, 1):
        single = {key: {"claim": claims[key]["claim"], "sources": claims[key]["sources"]}}
        prompt = template.replace("{claims}", json.dumps(single, indent=2))
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        result: dict = json.loads(raw)
        val = result.get(key, {})
        val.setdefault("claim", claims[key]["claim"])
        val.setdefault("sources", claims[key]["sources"])
        groups[key] = val
        print(f"    [{i}/{len(claim_keys)}] {key} done")
        if i < len(claim_keys):
            await asyncio.sleep(3)
    return groups


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="Path to the PDF file")
    parser.add_argument("--study", required=True, help="Study ID (e.g. SDY1669)")
    parser.add_argument("--pmid", help="PubMed/PMC ID (auto-looked up if omitted)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        sys.exit(1)

    pmid = args.pmid or _lookup_pmid(args.study)
    if not pmid:
        print(f"WARNING: Could not find PMID for {args.study} — using 'unknown'")
        pmid = "unknown"

    out_dir = OUT_DIR / f"{args.study}_{pmid}_jats_figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{args.study}] PDF: {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")
    print(f"[{args.study}] Output: {out_dir}")

    paper_url = get_paper_url(args.study)
    print(f"[{args.study}] Fetching JATS XML from PMC ({paper_url})…")
    try:
        paper_text, _ = await fetch_paper_content_async(paper_url)
    except PaperNotAvailableError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    print(f"[{args.study}] Parsed {len(paper_text)} chars of structured text")

    pdf_bytes = pdf_path.read_bytes()
    fig_labels = extract_figure_labels(paper_text)
    table_labels = extract_table_labels(paper_text)
    evidence_pages = find_label_pages(pdf_bytes, fig_labels + table_labels)
    n_pages = len({idx for pages in evidence_pages.values() for idx in pages})
    print(
        f"[{args.study}] Matched {len(evidence_pages)}/{len(fig_labels) + len(table_labels)} "
        f"figure/table labels to {n_pages} PDF page(s)"
    )
    for label in fig_labels + table_labels:
        pages = evidence_pages.get(label)
        if pages:
            print(f"    {label}: page(s) {[p + 1 for p in pages]}")
    unmatched = [l for l in fig_labels + table_labels if l not in evidence_pages]
    if unmatched:
        print(f"    unmatched: {unmatched}")

    client = _get_client()

    print(f"[{args.study}] Extracting claims with {settings.OPENAI_MODEL}…")
    assays, claims = await extract_claims_from_jats_and_figures(paper_text, pdf_bytes, client)
    print(f"[{args.study}] {len(assays)} assays, {len(claims)} claims")

    (out_dir / "assays.json").write_text(json.dumps(assays, indent=2, ensure_ascii=False))
    (out_dir / "claims.json").write_text(json.dumps(claims, indent=2, ensure_ascii=False))
    print(f"[{args.study}] saved assays.json, claims.json")

    print(f"[{args.study}] Step 2: structuring {len(claims)} claims into groups…")
    groups = await _run_step2(client, claims)
    (out_dir / "claims_groups.json").write_text(json.dumps(groups, indent=2, ensure_ascii=False))
    print(f"[{args.study}] saved claims_groups.json")
    print(f"[{args.study}] Done.")


asyncio.run(main())
