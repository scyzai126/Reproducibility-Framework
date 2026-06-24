import asyncio
import json
import logging
import re
from pathlib import Path

import openpyxl
import requests
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from app.config import settings
from app.agent.jats_parser import MAX_PAPER_CHARS, _clean_text, parse_jats_xml


class PaperNotAvailableError(Exception):
    """Raised when a paper is not available as open-access XML from NCBI."""
    pass


def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return Path(__file__).resolve().parent.parent.parent


_REPO_ROOT = _find_repo_root()
_XLSX_PATH = _REPO_ROOT / "data" / "studyid_pmcid.xlsx"


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
    Raises PaperNotAvailableError if the paper is not available as open-access XML.
    """
    pmcid = _extract_pmcid(url)
    api_url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pmc&id={pmcid}&rettype=full&retmode=xml"
    )
    try:
        resp = requests.get(api_url, timeout=30)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise PaperNotAvailableError(
            f"Paper {pmcid} is not available as open-access XML "
            f"(HTTP {exc.response.status_code if exc.response is not None else 'error'}). "
            "Please upload the PDF to continue."
        ) from exc

    soup = BeautifulSoup(resp.text, "xml")

    # NCBI returns HTTP 200 with an <ERROR> element for papers not in PMC open access
    error_tag = soup.find("ERROR")
    if error_tag:
        raise PaperNotAvailableError(
            f"Paper {pmcid} is not available in PubMed Central open access: "
            f"{error_tag.get_text(strip=True)}. Please upload the PDF to continue."
        )

    # Some publishers allow PMC hosting but restrict bulk XML downloads.
    # NCBI returns HTTP 200 with a comment and abstract-only XML in that case.
    if "does not allow downloading" in resp.text or "does not allow bulk downloading" in resp.text:
        raise PaperNotAvailableError(
            f"Paper {pmcid} is available on the PMC website but the publisher restricts "
            "bulk XML downloads. Please upload the PDF to continue."
        )

    # Detect abstract-only XML: article has no <body> element.
    article = soup.find("article")
    if article and not article.find("body"):
        raise PaperNotAvailableError(
            f"Paper {pmcid} returned abstract-only XML (no full text available via API). "
            "Please upload the PDF to continue."
        )

    # Extract PubMed ID from XML metadata
    pubmed_id: str | None = None
    tag = soup.find("article-id", {"pub-id-type": "pmid"})
    if tag:
        pubmed_id = tag.get_text(strip=True)

    structured_text = parse_jats_xml(resp.text)
    if not structured_text:
        # Fallback for malformed or non-standard XML.
        structured_text = _clean_text(soup.get_text(separator=" ", strip=True))[:MAX_PAPER_CHARS]

    # Detect abstract-only content: body tag exists but no results/methods sections
    # were parsed — the publisher provides metadata XML only.
    section_headers = [
        line[3:].strip().lower()
        for line in structured_text.splitlines()
        if line.startswith("## ")
    ]
    has_body_content = any(
        any(kw in h for kw in ("result", "finding", "method", "material", "procedure"))
        for h in section_headers
    )
    if section_headers and not has_body_content:
        raise PaperNotAvailableError(
            f"Paper {pmcid} returned abstract-only content (no results or methods sections found). "
            "Please upload the PDF to continue."
        )

    return structured_text, pubmed_id


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
    step1_override: dict | None = None,
) -> tuple[dict, dict]:
    """Core two-step LLM pipeline given already-fetched paper text.

    Step 1: extract assay-specific claims from paper text.
    Step 2: structure claims into groups + comparisons.

    Returns:
        Tuple of (step1_json, step2_json).
    """
    client = _get_client()

    assay_list = ", ".join(assay_methods) if assay_methods else "CITE-seq, Bulk RNA-seq, CyTOF, Flow Cytometry, Olink, Q-PCR, ELISA"
    step1_system = (
        _load_prompt("extract_claims.txt")
        .replace("{assay_methods}", assay_list)
    )

    if step1_override is not None:
        step1_json = step1_override
        logger.info("Step 1 skipped (using override): %d claims", len(step1_json))
    else:
        logger.info("Step 1: extracting claims for study %s", study_accession)
        resp1 = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": step1_system},
                {"role": "user", "content": paper_text},
            ],
            temperature=0,
        )
        raw1 = _strip_fences((resp1.choices[0].message.content or "").strip())
        step1_json: dict = json.loads(raw1)
        logger.info("Step 1 complete: assays=%s, claims=%d", assay_methods, len(step1_json))

    n_claims = len([k for k in step1_json if k.startswith("claim_")])

    # ── Step 2: structure each claim in parallel ──────────────────────────────
    step2_prompt_template = _load_prompt("classify_groups.txt")
    claim_keys = [k for k in step1_json if k.startswith("claim_")]

    def _sort_sources(sources: list) -> list:
        def _rank(s):
            if s.get("type") == "text" and s.get("section", "").lower() == "results":
                return 0
            if s.get("type") == "text":
                return 1
            return 2
        return sorted(sources, key=_rank)

    async def _structure_one_claim(key: str) -> tuple[str, dict]:
        single_claim = {key: step1_json[key]}
        prompt = step2_prompt_template.replace("{claims}", json.dumps(single_claim, indent=2))
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        result: dict = json.loads(raw)
        # Merge step1 fields into step2 output
        val = result.get(key, {})
        step1_entry = step1_json[key]
        if "claim" not in val and "claim" in step1_entry:
            val["claim"] = step1_entry["claim"]
        if "sources" not in val and "sources" in step1_entry:
            val["sources"] = step1_entry["sources"]
        if "sources" in val:
            val["sources"] = _sort_sources(val["sources"])
        val.pop("result_quotes", None)
        return key, val

    logger.info("Step 2: structuring %d claims in parallel", n_claims)
    pairs = await asyncio.gather(*[_structure_one_claim(k) for k in claim_keys])
    step2_json: dict = {k: v for k, v in pairs}
    logger.info("Step 2 complete: %d structured claims", len(step2_json))

    return step1_json, step2_json


async def parse_paper_claims(paper_url: str, study_accession: str, assay_methods: list[str]) -> tuple[dict, dict]:
    """Fetch paper text from PMC URL then run the two-step LLM pipeline.

    Returns:
        Tuple of (step1_json, step2_json).
    """
    logger.info("Fetching paper text from NCBI for %s", paper_url)
    paper_text = _fetch_paper_text(paper_url)
    logger.info("Fetched %d chars", len(paper_text))

    return await _run_two_step_pipeline(paper_text, study_accession, assay_methods)


async def parse_paper_claims_step1_only(
    paper_text: str,
    study_accession: str,
    assay_methods: list[str],
) -> dict:
    """Run only step 1 of the pipeline: extract claim sentences from the paper.

    Returns step1_json: {"claim_1": {"claim": "...", "sources": [...]}, ...}
    """
    client = _get_client()
    assay_list = ", ".join(assay_methods) if assay_methods else "CITE-seq, Bulk RNA-seq, CyTOF, Flow Cytometry, Olink, Q-PCR, ELISA"
    step1_system = (
        _load_prompt("extract_claims.txt")
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
    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    step1_json: dict = json.loads(raw)
    logger.info("Step 1 complete: %d claims", len([k for k in step1_json if k.startswith("claim_")]))
    return step1_json


async def parse_paper_claims_noimmport(paper_text: str, paper_url: str) -> list[dict]:
    """Extract claim sentences from a paper not linked to any ImmPort study.

    Uses a prompt that infers assay types directly from the paper — no assay list needed.
    Returns a list of {"claim_id": str, "claim_text": str, "sources": [...]} dicts.
    """
    client = _get_client()
    prompt = _load_prompt("claim_prompt_noimmport.txt").replace("{paper_url}", paper_url)
    logger.info("No-ImmPort path: extracting claims from paper %s", paper_url)
    resp = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": paper_text},
        ],
        temperature=0,
    )
    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    step1_json: dict = json.loads(raw)
    logger.info("No-ImmPort step 1 complete: %d claims", len([k for k in step1_json if k.startswith("claim_")]))
    return [
        {"claim_id": key, "claim_text": val.get("claim", ""), "sources": val.get("sources", [])}
        for key, val in step1_json.items()
        if key.startswith("claim_")
    ]


async def parse_paper_claims_from_text(
    paper_text: str,
    study_accession: str,
    assay_methods: list[str],
    cached_step1: dict | None = None,
) -> tuple[dict, dict]:
    """Run the two-step LLM pipeline on already-extracted paper text.

    If cached_step1 is provided, step 1 is skipped and only step 2 runs.
    Returns:
        Tuple of (step1_json, step2_json).
    """
    if cached_step1 is not None:
        logger.info("Skipping step 1 (using cached result), running step 2 only for %s", study_accession)
        _, step2_json = await _run_two_step_pipeline(
            "", study_accession, [], step1_override=cached_step1
        )
        return cached_step1, step2_json

    return await _run_two_step_pipeline(paper_text, study_accession, assay_methods)
