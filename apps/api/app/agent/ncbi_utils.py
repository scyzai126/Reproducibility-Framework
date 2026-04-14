import logging

import httpx

logger = logging.getLogger(__name__)

_pmc_url_cache: dict[str, str | None] = {}
_pmcid_to_pmid_cache: dict[str, str | None] = {}


async def pmid_to_pmc_url(pmid: str) -> str | None:
    """Convert a PubMed ID to its PMC article URL via the NCBI ID converter API.

    Returns the PMC URL (e.g. https://pmc.ncbi.nlm.nih.gov/articles/PMC7665312/)
    or None if no open-access PMC record exists for the given PMID.
    Results are cached in-process to avoid redundant API calls.
    """
    if pmid in _pmc_url_cache:
        return _pmc_url_cache[pmid]

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
                params={"ids": pmid, "format": "json"},
            )
            data = resp.json()
        records = data.get("records", [])
        if records and "pmcid" in records[0]:
            pmcid = records[0]["pmcid"]  # e.g. "PMC7665312"
            url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
            _pmc_url_cache[pmid] = url
            return url
    except Exception as exc:
        logger.warning("NCBI ID conversion failed for PMID %s: %s", pmid, exc)

    _pmc_url_cache[pmid] = None
    return None


async def pmc_to_pmid(pmc_id: str) -> str | None:
    """Convert a PMC numeric ID (e.g. "7665312") to a PubMed ID (e.g. "32788292").

    Uses the NCBI ID converter API — lightweight, returns only metadata.
    Results are cached in-process.
    """
    key = f"PMC{pmc_id.lstrip('PMCpmc')}"
    if key in _pmcid_to_pmid_cache:
        return _pmcid_to_pmid_cache[key]

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
                params={"ids": key, "format": "json"},
            )
            data = resp.json()
        records = data.get("records", [])
        if records and "pmid" in records[0]:
            pmid = records[0]["pmid"]
            _pmcid_to_pmid_cache[key] = pmid
            return pmid
    except Exception as exc:
        logger.warning("NCBI ID conversion failed for %s: %s", key, exc)

    _pmcid_to_pmid_cache[key] = None
    return None
