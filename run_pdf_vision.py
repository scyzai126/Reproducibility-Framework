"""Extract claims from a local PDF using GPT-4o vision (no PMC parsing).

Usage:
  python run_pdf_vision.py --pdf data/papers_pdf/SDY1669.pdf --study SDY1669
  python run_pdf_vision.py --pdf data/papers_pdf/SDY1669.pdf --study SDY1669 --pmid 33637673
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))

from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.agent.pdf_vision import extract_claims_from_pdf_images
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
            # ImmuneSigResource: PubMed ID column (already numeric)
            pmid = str(row_dict.get("PubMed ID") or "").strip()
            if pmid and pmid != "None":
                return pmid.split(";")[0].strip()
            # studyid_pmcid: PMCID column — resolve PMC ID → PubMed ID
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

    out_dir = OUT_DIR / f"{args.study}_{pmid}_pdf"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{args.study}] PDF: {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")
    print(f"[{args.study}] Output: {out_dir}")

    pdf_bytes = pdf_path.read_bytes()
    client = _get_client()

    print(f"[{args.study}] Sending to vision model ({settings.OPENAI_MODEL})…")
    assays, claims = await extract_claims_from_pdf_images(pdf_bytes, client)

    (out_dir / "assays.json").write_text(json.dumps(assays, indent=2, ensure_ascii=False))
    print(f"[{args.study}] {len(assays)} assays → {out_dir.name}/assays.json")

    (out_dir / "claims.json").write_text(json.dumps(claims, indent=2, ensure_ascii=False))
    print(f"[{args.study}] {len(claims)} claims → {out_dir.name}/claims.json")
    print(f"[{args.study}] Done.")


asyncio.run(main())
