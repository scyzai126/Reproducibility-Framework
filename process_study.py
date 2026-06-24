"""Process one or all ImmuneSigResource studies: generate claims + groups JSON.

Usage:
  python process_study.py --study SDY1260          # single study
  python process_study.py --all                    # all 26 studies

Output filenames include the PubMed ID so multi-paper studies get one file pair each:
  claims_LLM_{STUDY}_{PMID}.json
  groups_LLM_{STUDY}_{PMID}.json
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import openpyxl
import requests

sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))

from app.agent.claim_parser import (
    PaperNotAvailableError,
    _fetch_paper_text,
    _get_client,
    _load_prompt,
    _strip_fences,
)
from app.agent.paper_reader import extract_pdf_text

REPO_ROOT = Path(__file__).parent
IMMPORT_XLSX = REPO_ROOT / "data" / "ImmuneSigResource_1_studies.xlsx"
PMCID_XLSX = REPO_ROOT / "data" / "studyid_pmcid.xlsx"
PDF_DIR = REPO_ROOT / "data" / "papers_pdf"
OUT_DIR = REPO_ROOT / "data" / "claims"
MODEL = "gpt-4o"


# ── XLSX helpers ──────────────────────────────────────────────────────────────

def _load_study_rows() -> dict[str, dict]:
    """Return {study_accession: row_dict} from ImmuneSigResource_1_studies.xlsx (Sheet1)."""
    wb = openpyxl.load_workbook(str(IMMPORT_XLSX), read_only=True, data_only=True)
    ws = wb.active
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    studies: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        sid = str(row[0]).strip()
        if sid and sid != "None" and sid not in studies:
            studies[sid] = dict(zip(headers, row))
    return studies


def _all_study_ids() -> list[str]:
    wb = openpyxl.load_workbook(str(IMMPORT_XLSX), read_only=True, data_only=True)
    ws = wb["unique studies"]
    ids = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        sid = str(row[0]).strip()
        if sid and sid != "None":
            ids.append(sid)
    return ids


def _get_assay_methods(row: dict) -> list[str]:
    raw = row.get("Assay") or ""
    return [a.strip() for a in raw.split(";") if a.strip()]


def _get_pmids(row: dict) -> list[str]:
    """Return list of PMIDs from the PubMed ID field (may be semicolon-separated)."""
    raw = str(row.get("PubMed ID") or "").strip()
    if not raw or raw == "None":
        return []
    return [p.strip() for p in raw.split(";") if p.strip()]


def _load_pmcid_rows() -> dict[str, dict]:
    """Return {study_accession: row_dict} from studyid_pmcid.xlsx."""
    wb = openpyxl.load_workbook(str(PMCID_XLSX), read_only=True, data_only=True)
    ws = wb.active
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    studies: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        sid = str(row[0]).strip()
        if sid and sid != "None" and sid not in studies:
            studies[sid] = dict(zip(headers, row))
    return studies


# ── PMID → PMCID lookup ───────────────────────────────────────────────────────

def _pmid_to_pmcid(pmid: str) -> str:
    """Convert a PubMed ID to a PMC ID string (e.g. '3946932') via NCBI elink."""
    url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
        f"?dbfrom=pubmed&db=pmc&id={pmid}&retmode=json"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    try:
        links = data["linksets"][0]["linksetdbs"]
        for db in links:
            if db["dbto"] == "pmc" and db["linkname"] == "pubmed_pmc":
                return db["links"][0]
    except (KeyError, IndexError):
        pass
    raise ValueError(f"No PMC article found for PMID {pmid}")


def _pmcid_to_pmid(pmcid: str) -> str:
    """Convert a PMC ID (numeric string) to a PubMed ID via NCBI elink."""
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


def _pmc_url(pmcid: str) -> str:
    return f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmcid}/"


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def _run_step2(client, claims: dict) -> dict:
    """Classify groups for each claim sequentially (rate-limit friendly)."""
    template = _load_prompt("classify_groups.txt")
    claim_keys = [k for k in claims if k.startswith("claim_")]
    groups: dict = {}

    for i, key in enumerate(claim_keys, 1):
        single = {key: {"claim": claims[key]["claim"], "sources": claims[key]["sources"]}}
        prompt = template.replace("{claims}", json.dumps(single, indent=2))
        resp = await client.chat.completions.create(
            model=MODEL,
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
            await asyncio.sleep(3)  # stay under TPM limit

    return groups


async def _process_paper(study_id: str, pmid: str, debug: bool = False, direct_url: str | None = None, step1_only: bool = False) -> None:
    """Run the full pipeline for one paper (identified by PMID) of a study."""
    tag = f"{study_id}/{pmid}"
    paper_dir = OUT_DIR / f"{study_id}_{pmid}_xml"

    # Always delete existing claims file before re-running
    if (paper_dir / "claims.json").exists():
        (paper_dir / "claims.json").unlink()
        print(f"[{tag}] Deleted existing claims.json")

    # Resolve PMC URL (skip if already provided directly)
    if direct_url:
        paper_url = direct_url
        print(f"[{tag}] PMC URL: {paper_url}")
    else:
        print(f"[{tag}] Resolving PMCID…")
        try:
            pmcid = _pmid_to_pmcid(pmid)
        except Exception as exc:
            print(f"[{tag}] Could not resolve PMCID: {exc} — skipping")
            return
        paper_url = _pmc_url(pmcid)
        print(f"[{tag}] PMC URL: {paper_url}")

    # Fetch paper — fall back to local PDF if PMC full text is unavailable
    print(f"[{tag}] Fetching paper text…")
    try:
        paper_text = _fetch_paper_text(paper_url)
        print(f"[{tag}] {len(paper_text):,} chars fetched from PMC")
    except PaperNotAvailableError as exc:
        pdf_path = PDF_DIR / f"{study_id}_{pmid}.pdf"
        if pdf_path.exists():
            print(f"[{tag}] PMC unavailable — using local PDF: {pdf_path.name}")
            paper_text = extract_pdf_text(pdf_path.read_bytes())
            print(f"[{tag}] {len(paper_text):,} chars extracted from PDF")
        else:
            print(f"\n{'='*60}")
            print(f"ALERT [{tag}]: Full text not available from PMC.")
            print(f"  Reason : {exc}")
            print(f"  Action : Upload the PDF as:")
            print(f"           {pdf_path}")
            print(f"  Then re-run: .venv/bin/python process_study.py --study {study_id}")
            print(f"{'='*60}\n")
            return
    except Exception as exc:
        print(f"[{tag}] Could not fetch paper: {exc} — skipping")
        return

    # Create output subfolder and save parsed paper text
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "paper.txt").write_text(paper_text, encoding="utf-8")
    print(f"[{tag}] paper.txt saved ({len(paper_text):,} chars)")

    if debug:
        sections = [line[3:].strip() for line in paper_text.splitlines() if line.startswith("## ")]
        print(f"[{tag}] DEBUG: {len(sections)} sections found:")
        for s in sections:
            print(f"         • {s}")

    client = _get_client()

    # Step 1 — extract claims (LLM discovers assays itself from Methods/figures)
    print(f"[{tag}] Step 1: extracting claims…")
    step1_system = _load_prompt("extract_claims.txt")
    resp1 = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": step1_system},
            {"role": "user", "content": paper_text},
        ],
        temperature=0,
    )
    raw1 = _strip_fences((resp1.choices[0].message.content or "").strip())
    step1 = json.loads(raw1)
    assays = step1.pop("assays", {})
    claims = {k: v for k, v in step1.items() if k.startswith("claim_")}
    (paper_dir / "assays.json").write_text(json.dumps(assays, indent=2, ensure_ascii=False))
    (paper_dir / "claims.json").write_text(json.dumps(claims, indent=2, ensure_ascii=False))
    print(f"[{tag}] Step 1: {len(assays)} assays → {paper_dir.name}/assays.json")
    print(f"[{tag}] Step 1: {len(claims)} claims → {paper_dir.name}/claims.json")

    print(f"[{tag}] Done.\n")


async def process_study(study_id: str, row: dict, debug: bool = False, step1_only: bool = False) -> None:
    # studyid_pmcid.xlsx rows have a pre-resolved PMC URL stored as a synthetic PMID
    direct_url = row.get("_pmc_url")
    if direct_url:
        pmid = str(row.get("PubMed ID") or "unknown").strip()
        print(f"[{study_id}] 1 paper(s): [{pmid}] (direct PMC URL)")
        await _process_paper(study_id, pmid, debug=debug, direct_url=direct_url, step1_only=step1_only)
        return

    pmids = _get_pmids(row)
    if not pmids:
        print(f"[{study_id}] No PubMed ID found — skipping")
        return

    print(f"[{study_id}] {len(pmids)} paper(s): {pmids}")
    for pmid in pmids:
        await _process_paper(study_id, pmid, debug=debug, step1_only=step1_only)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate claims + groups JSON for ImmuneSigResource studies.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--study", metavar="SDYXXX", help="Process a single study")
    group.add_argument("--all", action="store_true", help="Process all 26 studies")
    parser.add_argument("--debug", action="store_true", help="Save parsed paper text and print sections")
    parser.add_argument("--step1-only", action="store_true", help="Run Step 1 (claims) only, skip Step 2 (groups)")
    args = parser.parse_args()

    immport_rows = _load_study_rows()
    pmcid_rows = _load_pmcid_rows()

    if args.study:
        study_ids = [args.study]
    else:
        study_ids = _all_study_ids()

    print(f"Studies to process: {study_ids}\n")

    for study_id in study_ids:
        row = immport_rows.get(study_id)
        source = IMMPORT_XLSX.name

        if row is None:
            # Fall back to studyid_pmcid.xlsx — synthesise a compatible row from the PMC URL
            pmcid_row = pmcid_rows.get(study_id)
            if pmcid_row is None:
                print(f"[{study_id}] Not found in either XLSX — skipping")
                continue
            pmc_url = str(pmcid_row.get("PMCID") or "").strip()
            pmcid = re.search(r"PMC(\d+)", pmc_url, re.IGNORECASE)
            if not pmcid:
                print(f"[{study_id}] No valid PMC URL in {PMCID_XLSX.name} — skipping")
                continue
            # Resolve PMC ID → PubMed ID; fall back to PMC ID string if lookup fails
            pmcid_str = pmcid.group(1)
            try:
                resolved_pmid = _pmcid_to_pmid(pmcid_str)
            except Exception:
                resolved_pmid = f"PMC{pmcid_str}"
            row = {"PubMed ID": resolved_pmid, "_pmc_url": pmc_url, "Assay": ""}
            source = PMCID_XLSX.name

        print(f"[{study_id}] Source: {source}")
        try:
            await process_study(study_id, row, debug=args.debug, step1_only=args.step1_only)
        except Exception as exc:
            print(f"[{study_id}] Unexpected error: {exc}")


asyncio.run(main())
