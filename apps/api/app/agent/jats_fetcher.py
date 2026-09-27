"""Get one paper's JATS XML onto disk, or say precisely why it cannot be.

The assay pipeline reads papers from exactly one place: `data/JAT_XML/<SDY>_<pmid>.xml`. Until
now the only thing that wrote there was scripts/download_jats_xml.py, which is batch-only -- it
reads a spreadsheet or a directory of PDFs, and its fetch loop is inline in `main()`, so there
was no way to add a single paper by id from anywhere else. This module is that way.

**No model calls.** Two HTTP requests to NCBI: the ID converter to turn a PubMed ID into a PMC
id, then E-utilities efetch for the full text. It belongs on the free side of any UI.

A PDF is deliberately not an input here. Every assay round reads the output of
`parse_jats_xml` -> `number_sentences`, and `jats_parser.sentence_sections` keys off the
`## Heading [methods]` markers only `parse_jats_xml` emits. Raw PDF text has none, so the
verifier's section check would go blind and the `[S<n>]` ids every piece of evidence cites would
be numbering page headers and running feet -- producing a registry that reads exactly like a
verified one and is not.
"""

import asyncio
import logging
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.agent import assay_service
from app.agent.claim_parser import _extract_pmcid
from app.agent.ncbi_utils import pmid_to_pmc_url

logger = logging.getLogger(__name__)

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

#: NCBI allows three requests a second without an API key, and one fetch is two of them. The lock
#: serialises concurrent callers and the delay spaces them -- a button a user can hold down should
#: not be what discovers that limit.
REQUEST_DELAY_S = 0.4
_fetch_lock = asyncio.Lock()

#: A study accession must start with "SDY" and a PubMed ID must be digits, or the file cannot be
#: filed under its own name. See validate_identifiers.
#:
#: Public, because app.agent.paper_resolver classifies typed input with the same two patterns. A
#: second copy is how the resolver and the validator quietly stop agreeing -- and a disagreement
#: there means offering a paper that fetch_jats then refuses.
PMID_RE = re.compile(r"\d+")
SDY_RE = re.compile(r"SDY\d+", re.IGNORECASE)

_PMID_RE, _SDY_RE = PMID_RE, SDY_RE  # the names this module used before they were shared


class PaperUnavailableError(LookupError):
    """The paper is not something PMC will serve as usable full text.

    Distinct from a transport failure: retrying will not help, and the message says which of the
    several different reasons it was -- "no PMC record" and "abstract-only" send a reader to
    different next steps.
    """


class PaperNotInPMCError(PaperUnavailableError):
    """There is no open-access PubMed Central record for this paper at all.

    A subclass rather than a message a caller greps for: the route maps this to 404 and every
    other unavailability to 422, and deciding that by substring meant one reworded sentence
    silently turned a 404 into a 422.
    """


class PaperFetchError(RuntimeError):
    """NCBI could not be reached. Unlike PaperUnavailableError, retrying may well work."""


def validate_identifiers(pubmed_id: str, study_accession: str) -> tuple[str, str]:
    """Check the pair can be filed under its own name, before anything is fetched.

    The registry directory is `<pmid>_<SDY>` and the XML is `<SDY>_<pmid>`; the two schemes were
    named independently, and `assay_service.split_stem` reconciles them by asking which half
    starts with "SDY". So an accession that does not silently *inverts* the pair -- a file named
    `ABC123_34252919.xml` parses back as pubmed_id "ABC123", study "34252919", and the paper is
    unfindable under the identifiers it was added with.

    That makes the shape of these two strings a correctness constraint rather than tidiness,
    and it is checked here, before a network call, rather than discovered later by a lookup that
    quietly returns nothing.
    """
    pmid, sdy = (pubmed_id or "").strip(), (study_accession or "").strip().upper()
    if not _PMID_RE.fullmatch(pmid):
        raise ValueError(
            f"{pubmed_id!r} is not a PubMed ID: expected digits only. A PMC id (PMC1234567) "
            "will not do -- the pipeline files papers by PubMed ID."
        )
    if not _SDY_RE.fullmatch(sdy):
        raise ValueError(
            f"{study_accession!r} is not a study accession: expected SDY followed by digits, "
            "e.g. SDY2189. The XML is filed as <SDY>_<pmid>.xml and the two halves are told "
            "apart by the SDY prefix, so an accession without it cannot be read back."
        )
    return pmid, sdy


def unavailable_reason(xml: str, soup: BeautifulSoup) -> str | None:
    """Why this XML is not usable full text, or None if it is fine.

    Mirrors the checks in claim_parser._fetch_paper_content so this module's notion of
    "unavailable" matches the pipeline's. One definition, shared with
    scripts/download_jats_xml.py, because a second copy is how one of these four checks quietly
    stops applying to papers added through one route but not the other.

    Each reason is a plain lower-case clause rather than a diagnostic, because it is read by a
    person: it is what the UI shows after "Cannot fetch this paper's content online:" and what
    the batch script prints beside a FAIL. "abstract-only XML (no <body>)" told a maintainer
    what happened and told everyone else nothing.
    """
    error_tag = soup.find("ERROR")
    if error_tag:
        return ("PubMed Central does not carry it as open access "
                f"({error_tag.get_text(strip=True)})")
    if "does not allow downloading" in xml or "does not allow bulk downloading" in xml:
        return "the publisher does not allow its full text to be downloaded"
    article = soup.find("article")
    if article is None:
        return "PubMed Central returned no article for it"
    if not article.find("body"):
        return "PubMed Central has only the abstract, not the full text"
    return None


def _destination(pmid: str, sdy: str, out_dir: Path | None) -> Path:
    """Where this paper's XML goes.

    `assay_service.XML_ROOT` is read here rather than captured at import, so a test or a
    deployment that moves the data directory reaches this module too -- the same reason every
    other function that writes into that root resolves it late.
    """
    root = out_dir if out_dir is not None else assay_service.XML_ROOT
    return root / f"{sdy}_{pmid}.xml"


async def download_jats(pubmed_id: str) -> tuple[str, str]:
    """Fetch one paper's full-text JATS XML from PMC without writing it anywhere.

    Returns `(xml, pmcid)`. Raises PaperNotInPMCError / PaperUnavailableError when PMC will not
    serve usable full text and PaperFetchError when NCBI could not be reached. fetch_jats files
    the result under `<SDY>_<pmid>.xml`; a paper with no ImmPort study has no such name, so
    claims-only extraction calls this directly.
    """
    pmid = (pubmed_id or "").strip()
    async with _fetch_lock:
        pmc_url = await pmid_to_pmc_url(pmid)
        if not pmc_url:
            raise PaperNotInPMCError(
                f"Cannot fetch this paper's content online: PubMed ID {pmid} has no "
                "open-access PubMed Central record, so there is no full text to download. "
                "A paper behind a publisher's paywall cannot go through this pipeline."
            )
        pmcid = _extract_pmcid(pmc_url)

        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    EFETCH_URL,
                    params={"db": "pmc", "id": pmcid, "rettype": "full", "retmode": "xml"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PaperFetchError(f"could not reach NCBI for {pmcid}: {exc}") from exc
        finally:
            # Inside the lock, so the spacing applies between callers and not merely within one.
            await asyncio.sleep(REQUEST_DELAY_S)

    xml = response.text
    reason = unavailable_reason(xml, BeautifulSoup(xml, "xml"))
    if reason:
        # Led by the plain statement, because this is shown to whoever typed the identifier and
        # "PMC4049462: abstract-only XML (no <body>)" does not tell them the thing they need to
        # know, which is that the paper cannot be fetched at all.
        raise PaperUnavailableError(
            f"Cannot fetch this paper's content online: {reason} ({pmcid})."
        )

    return xml, pmcid


async def fetch_jats(
    pubmed_id: str,
    study_accession: str,
    *,
    force: bool = False,
    out_dir: Path | None = None,
) -> dict:
    """Download one paper's JATS XML into the corpus the assay pipeline reads.

    Costs two NCBI requests and no model calls. Returns
    `{pubmed_id, study_accession, path, filename, created, bytes, pmcid}`.

    **An XML already on disk is left alone** and reported with `created: False`, without a
    request. Re-fetching is `force=True` and is deliberately a choice: the sentence numbering is
    derived from the file, so a re-fetched paper can renumber every `[S<n>]` a stored registry
    cites and make its quotes stop matching. That is exactly what `assay_service.stored_registry`
    recomputes the quote check for, but it should happen because someone asked, not as a side
    effect of adding a paper twice.

    Raises ValueError for an unusable identifier pair, PaperUnavailableError when PMC will not
    serve the paper, and PaperFetchError when NCBI could not be reached. Nothing is written on
    any of those paths.
    """
    pmid, sdy = validate_identifiers(pubmed_id, study_accession)
    destination = _destination(pmid, sdy, out_dir)

    if destination.exists() and not force:
        return {
            "pubmed_id": pmid,
            "study_accession": sdy,
            "path": str(destination),
            "filename": destination.name,
            "created": False,
            "bytes": destination.stat().st_size,
            "pmcid": None,
        }

    xml, pmcid = await download_jats(pmid)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(xml, encoding="utf-8")
    logger.info("fetched %s for PMID %s into %s", pmcid, pmid, destination.name)

    return {
        "pubmed_id": pmid,
        "study_accession": sdy,
        "path": str(destination),
        "filename": destination.name,
        "created": True,
        "bytes": len(xml),
        "pmcid": pmcid,
    }
