import json
import logging
import re
from pathlib import Path

import openpyxl
import requests
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from app.config import settings

_XLSX_PATH = Path(__file__).resolve().parent.parent.parent / "studyid_pmcid.xlsx"
_CLAIMS_DIR = Path(__file__).resolve().parent.parent.parent / "claims"


def _extract_pmcid(url: str) -> str:
    """Extract PMC ID from a PubMed Central URL, e.g. PMC4049462."""
    match = re.search(r"(PMC\d+)", url, re.IGNORECASE)
    return match.group(1).upper() if match else "UNKNOWN"


logger = logging.getLogger(__name__)


def _load_xlsx_row(study_accession: str) -> dict:
    """Return the row dict for a study accession from studyid_pmcid.xlsx."""
    wb = openpyxl.load_workbook(str(_XLSX_PATH), read_only=True, data_only=True)
    ws = wb.active
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if str(row[0]).strip() == study_accession.strip():
            return dict(zip(headers, row))
    raise ValueError(f"Study accession '{study_accession}' not found in {_XLSX_PATH.name}")


def get_paper_url(study_accession: str) -> str:
    """Look up the paper URL for a study accession from studyid_pmcid.xlsx."""
    return _load_xlsx_row(study_accession)["PMCID"]


def get_assay_methods(study_accession: str) -> list[str]:
    """Return assay methods for a study from the ASSAY METHODS column in studyid_pmcid.xlsx."""
    raw = _load_xlsx_row(study_accession).get("ASSAY METHODS") or ""
    return [a.strip() for a in raw.split(",") if a.strip()]

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_openai_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def _fetch_paper_text(url: str) -> str:
    """Fetch full article text from PMC via NCBI E-utilities API."""
    pmcid = _extract_pmcid(url)
    api_url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pmc&id={pmcid}&rettype=full&retmode=xml"
    )
    resp = requests.get(api_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    text = soup.get_text(separator=" ", strip=True)
    return text[:120000]


def _strip_fences(raw: str) -> str:
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]
    return raw


async def parse_paper_claims(paper_url: str, study_accession: str, assay_methods: list[str]) -> tuple[dict, dict]:
    """Run two-step LLM pipeline to extract and structure claims from a paper.

    Step 1: LLM identifies assay methods in the paper, then extracts claims.
    Step 2: LLM converts raw claims into structured groups + comparisons.

    Outputs are written to claims/{study_accession}_{PMCID}/.

    Args:
        paper_url: URL of the paper to parse.
        study_accession: ImmPort study accession (e.g. SDY2189).

    Returns:
        Tuple of (step1_json, step2_json).
    """
    client = _get_client()
    pmcid = _extract_pmcid(paper_url)
    out_dir = _CLAIMS_DIR / f"{study_accession}_{pmcid}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: identify assays + extract claims ──────────────────────────────
    logger.info("Fetching paper text from NCBI for %s", paper_url)
    paper_text = _fetch_paper_text(paper_url)
    logger.info("Fetched %d chars", len(paper_text))

    assay_list = ", ".join(assay_methods) if assay_methods else "CITE-seq, Bulk RNA-seq, CyTOF, Flow Cytometry, Olink, Q-PCR, ELISA"
    step1_system = (
        _load_prompt("claim_prompt_step1.txt")
        .replace("{paper_url}", paper_url)
        .replace("{assay_methods}", assay_list)
    )

    logger.info("Step 1: identifying assays and extracting claims from %s", paper_url)
    resp1 = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": step1_system},
            {"role": "user", "content": paper_text},
        ],
        temperature=0,
    )
    raw1 = _strip_fences(resp1.choices[0].message.content.strip())
    step1_json: dict = json.loads(raw1)
    n_claims = len([k for k in step1_json if k.startswith("claim_")])
    logger.info("Step 1 complete: assays=%s, claims=%d", assay_methods, n_claims)

    (out_dir / "step1.json").write_text(json.dumps(step1_json, indent=2), encoding="utf-8")
    logger.info("Step 1 output written to %s", out_dir / "step1.json")

    # ── Step 2: structure claims ──────────────────────────────────────────────
    step2_prompt = _load_prompt("claim_prompt_step2.txt").replace(
        "{claims}", json.dumps(step1_json, indent=2)
    )

    logger.info("Step 2: structuring %d claims", n_claims)
    resp2 = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": step2_prompt}],
        temperature=0,
    )
    raw2 = _strip_fences(resp2.choices[0].message.content.strip())
    step2_json: dict = json.loads(raw2)
    logger.info("Step 2 complete: %d structured claims", len(step2_json))

    # Ensure claim + sources from step1 are always present in step2 output,
    # and sort sources so Results-section entries come first.
    def _sort_sources(sources: list) -> list:
        def _rank(s):
            if s.get("type") == "text" and s.get("section", "").lower() == "results":
                return 0
            if s.get("type") == "text":
                return 1
            return 2  # figure / table
        return sorted(sources, key=_rank)

    for key, val in step2_json.items():
        step1_entry = step1_json.get(key, {})
        if "claim" not in val and "claim" in step1_entry:
            val["claim"] = step1_entry["claim"]
        if "sources" not in val and "sources" in step1_entry:
            val["sources"] = step1_entry["sources"]
        if "sources" in val:
            val["sources"] = _sort_sources(val["sources"])
        # Remove legacy result_quotes field if present
        val.pop("result_quotes", None)

    (out_dir / f"claims_LLM_{study_accession}.json").write_text(json.dumps(step2_json, indent=2), encoding="utf-8")
    logger.info("Step 2 output written to %s", out_dir / f"claims_LLM_{study_accession}.json")

    return step1_json, step2_json
