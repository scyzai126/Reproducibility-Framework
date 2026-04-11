"""Extract text and PubMed ID from an uploaded PDF file."""

import re

import fitz  # pymupdf


def extract_pdf_text(pdf_bytes: bytes, max_chars: int = 120000) -> str:
    """Return plain text from a PDF byte string, capped at max_chars."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [page.get_text() for page in doc]
    return "\n".join(pages)[:max_chars]


def extract_pubmed_id_from_filename(filename: str) -> str | None:
    """Parse a PubMed ID from a PDF filename.

    Accepts e.g. "PMID32788292.pdf" or "32788292.pdf" → "32788292".
    PMC IDs are not accepted here since they cannot be directly mapped
    to ImmPort study accessions.
    Returns None if no digits found.
    """
    match = re.search(r"(\d+)", filename)
    if match:
        return match.group(1)
    return None
