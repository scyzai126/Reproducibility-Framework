"""Extract text and PubMed ID from an uploaded PDF file."""

import re

import fitz  # pymupdf


def extract_pdf_text(pdf_bytes: bytes, max_chars: int = 120000) -> str:
    """Return plain text from a PDF byte string, capped at max_chars."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [page.get_text() for page in doc]
    return "\n".join(pages)[:max_chars]


def extract_pubmed_id_from_filename(filename: str) -> str | None:
    """Parse a PubMed or PMC numeric ID from a PDF filename.

    Tries PMC\\d+ first (e.g. "PMC9924941.pdf" → "9924941"),
    then falls back to any digit sequence (e.g. "36543218.pdf" → "36543218").
    Returns None if no digits found.
    """
    match = re.search(r"PMC(\d+)", filename, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"(\d+)", filename)
    if match:
        return match.group(1)
    return None
