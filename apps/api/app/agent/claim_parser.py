import json
import logging
import re
from pathlib import Path

import openpyxl
import requests
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from app.config import settings


def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return Path(__file__).resolve().parent.parent.parent


_REPO_ROOT = _find_repo_root()
_XLSX_PATH = _REPO_ROOT / "data" / "studyid_pmcid.xlsx"
_CLAIMS_DIR = _REPO_ROOT / "data" / "claims"


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


def _fetch_paper_content(url: str) -> tuple[str, str | None]:
    """Fetch full article text and PubMed ID from PMC via NCBI E-utilities API.

    Returns (paper_text, pubmed_id).
    pubmed_id is parsed from <article-id pub-id-type="pmid"> in the XML response.
    """
    pmcid = _extract_pmcid(url)
    api_url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pmc&id={pmcid}&rettype=full&retmode=xml"
    )
    resp = requests.get(api_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Extract PubMed ID from XML metadata
    pubmed_id: str | None = None
    tag = soup.find("article-id", {"pub-id-type": "pmid"})
    if tag:
        pubmed_id = tag.get_text(strip=True)

    text = soup.get_text(separator=" ", strip=True)
    return text[:120000], pubmed_id


def _fetch_paper_text(url: str) -> str:
    """Fetch full article text only (legacy helper)."""
    text, _ = _fetch_paper_content(url)
    return text


async def fetch_paper_content_async(url: str) -> tuple[str, str | None]:
    """Async wrapper — returns (paper_text, pubmed_id)."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_paper_content, url)


async def fetch_paper_text_async(url: str) -> str:
    """Async wrapper — returns paper text only (legacy)."""
    text, _ = await fetch_paper_content_async(url)
    return text


def _strip_fences(raw: str) -> str:
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]
    return raw


async def _run_two_step_pipeline(
    paper_text: str,
    study_accession: str,
    assay_methods: list[str],
    out_dir,
) -> tuple[dict, dict]:
    """Core two-step LLM pipeline given already-fetched paper text.

    Step 1: extract assay-specific claims from paper text.
    Step 2: structure claims into groups + comparisons.

    Outputs are written to out_dir.

    Returns:
        Tuple of (step1_json, step2_json).
    """
    client = _get_client()

    assay_list = ", ".join(assay_methods) if assay_methods else "CITE-seq, Bulk RNA-seq, CyTOF, Flow Cytometry, Olink, Q-PCR, ELISA"
    step1_system = (
        _load_prompt("claim_prompt_step1.txt")
        .replace("{paper_url}", study_accession)
        .replace("{assay_methods}", assay_list)
    )

    logger.info("Step 1: extracting claims for study %s", study_accession)
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


async def parse_paper_claims(paper_url: str, study_accession: str, assay_methods: list[str]) -> tuple[dict, dict]:
    """Fetch paper text from PMC URL then run the two-step LLM pipeline.

    Outputs are written to claims/{study_accession}_{PMCID}/.
    Returns:
        Tuple of (step1_json, step2_json).
    """
    pmcid = _extract_pmcid(paper_url)
    out_dir = _CLAIMS_DIR / f"{study_accession}_{pmcid}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Fetching paper text from NCBI for %s", paper_url)
    paper_text = _fetch_paper_text(paper_url)
    logger.info("Fetched %d chars", len(paper_text))

    return await _run_two_step_pipeline(paper_text, study_accession, assay_methods, out_dir)


async def parse_paper_claims_step1_only(
    paper_text: str,
    study_accession: str,
    assay_methods: list[str],
    pmcid: str = "PDF",
) -> dict:
    """Run only step 1 of the pipeline: extract claim sentences from the paper.

    Returns step1_json: {"claim_1": {"claim": "...", "sources": [...]}, ...}
    """
    client = _get_client()
    assay_list = ", ".join(assay_methods) if assay_methods else "CITE-seq, Bulk RNA-seq, CyTOF, Flow Cytometry, Olink, Q-PCR, ELISA"
    step1_system = (
        _load_prompt("claim_prompt_step1.txt")
        .replace("{paper_url}", study_accession)
        .replace("{assay_methods}", assay_list)
    )
    logger.info("Step 1 only: extracting claims for study %s", study_accession)
    resp = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": step1_system},
            {"role": "user", "content": paper_text},
        ],
        temperature=0,
    )
    raw = _strip_fences(resp.choices[0].message.content.strip())
    step1_json: dict = json.loads(raw)
    out_dir = _CLAIMS_DIR / f"{study_accession}_{pmcid}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "step1.json").write_text(json.dumps(step1_json, indent=2), encoding="utf-8")
    logger.info("Step 1 complete: %d claims", len([k for k in step1_json if k.startswith("claim_")]))
    return step1_json


async def parse_paper_claims_from_text(
    paper_text: str,
    study_accession: str,
    assay_methods: list[str],
    pmcid: str = "PDF",
) -> tuple[dict, dict]:
    """Run the two-step LLM pipeline on already-extracted paper text (e.g. from PDF).

    Outputs are written to claims/{study_accession}_{pmcid}/.
    Returns:
        Tuple of (step1_json, step2_json).
    """
    out_dir = _CLAIMS_DIR / f"{study_accession}_{pmcid}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return await _run_two_step_pipeline(paper_text, study_accession, assay_methods, out_dir)
