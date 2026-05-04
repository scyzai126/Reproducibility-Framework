"""Fetch paper content from PMC and prepare structured paper context."""

from __future__ import annotations

import asyncio
import re

import requests
from bs4 import BeautifulSoup

from app.agent.paper_context import render_paper_context_for_llm
from app.agent.paper_jats import MAX_PAPER_CHARS, clean_text, parse_jats_xml_to_json


def extract_pmcid(url: str) -> str:
    """Extract PMC ID from a PubMed Central URL, e.g. PMC4049462."""
    match = re.search(r"(PMC\d+)", url, re.IGNORECASE)
    return match.group(1).upper() if match else "UNKNOWN"


def fetch_paper_content_bundle(url: str) -> dict:
    """Fetch a PMC article and return both structured JSON and rendered text."""
    pmcid = extract_pmcid(url)
    api_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pmc&id={pmcid}&rettype=full&retmode=xml"
    )
    resp = requests.get(api_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "xml")

    pubmed_id: str | None = None
    tag = soup.find("article-id", {"pub-id-type": "pmid"})
    if tag:
        pubmed_id = tag.get_text(strip=True)

    paper_json = parse_jats_xml_to_json(resp.text)
    paper_text = render_paper_context_for_llm(paper_json)
    if not paper_text:
        paper_text = clean_text(soup.get_text(separator=" ", strip=True))[:MAX_PAPER_CHARS]
        paper_json["parse_mode"] = "fallback"
        paper_json["raw_text"] = paper_text

    return {
        "paper_text": paper_text,
        "pubmed_id": pubmed_id,
        "paper_json": paper_json,
        "xml_text": resp.text,
    }


async def fetch_paper_content_bundle_async(url: str) -> dict:
    """Async wrapper for fetching a paper bundle from PMC."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_paper_content_bundle, url)
