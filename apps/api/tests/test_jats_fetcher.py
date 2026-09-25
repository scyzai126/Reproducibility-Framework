"""Adding one paper to the corpus the assay pipeline reads.

No test here touches the network: NCBI's two endpoints are stubbed throughout. What is under
test is the part that is ours -- which identifier pairs can be filed under their own name, which
PMC responses count as usable full text, and the rule that nothing is written unless both
questions were answered yes.
"""

import asyncio
from pathlib import Path

import httpx
import pytest

from app.agent import assay_service, jats_fetcher
from app.agent.assay_service import available_papers, locate_paper_xml, split_stem
from app.agent.jats_fetcher import (
    PaperFetchError,
    PaperNotInPMCError,
    PaperUnavailableError,
    fetch_jats,
    unavailable_reason,
    validate_identifiers,
)

_FULL_TEXT = """<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p></sec></body></article>"""

_ABSTRACT_ONLY = """<article><front><article-meta><article-title>A Paper</article-title>
<abstract><p>Only an abstract.</p></abstract></article-meta></front></article>"""

_NOT_OPEN_ACCESS = """<pmc-articleset><ERROR>The publisher of this article does not allow
downloading of the full text in XML form.</ERROR></pmc-articleset>"""


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """An empty JATS corpus, with both assay roots redirected into tmp_path."""
    xml_root, registry_root = tmp_path / "JAT_XML", tmp_path / "assay_registries"
    xml_root.mkdir()
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    # PDF_ROOT is redirected at an empty directory so the listing cannot pick up the
    # repo's real PDFs: available_papers offers PDF-only papers too.
    _pdf_root = tmp_path / "pdf"
    _pdf_root.mkdir(exist_ok=True)
    monkeypatch.setattr(assay_service, "PDF_ROOT", _pdf_root)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)
    return xml_root


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    """The inter-request spacing is real behaviour but nothing to sit through in a test."""
    monkeypatch.setattr(jats_fetcher, "REQUEST_DELAY_S", 0)


class _Calls:
    """Counts the HTTP requests a test caused, so "made no call" can be asserted."""

    def __init__(self):
        self.count = 0


@pytest.fixture
def ncbi(monkeypatch):
    """Stub both NCBI endpoints. Returns a handle for varying the efetch response."""
    calls = _Calls()
    state = {"pmc_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC999/", "body": _FULL_TEXT,
             "raises": None}

    async def _fake_pmid_to_pmc_url(_pmid):
        calls.count += 1
        return state["pmc_url"]

    class _FakeClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, _url, params=None):
            calls.count += 1
            if state["raises"] is not None:
                raise state["raises"]
            return httpx.Response(200, text=state["body"],
                                  request=httpx.Request("GET", "https://example.test"))

    monkeypatch.setattr(jats_fetcher, "pmid_to_pmc_url", _fake_pmid_to_pmc_url)
    monkeypatch.setattr(jats_fetcher.httpx, "AsyncClient", _FakeClient)
    state["calls"] = calls
    return state


# ── the identifier pair has to survive being written to a filename ────────────

def test_a_valid_pair_is_normalised_rather_than_merely_accepted():
    assert validate_identifiers(" 34252919 ", " sdy2189 ") == ("34252919", "SDY2189")


def test_the_filename_a_valid_pair_produces_reads_back_as_the_same_pair():
    """The load-bearing property. The registry dir is <pmid>_<SDY> and the XML <SDY>_<pmid>, and
    split_stem tells the halves apart by the SDY prefix -- so a pair that does not round-trip is
    a paper filed under a name it can never be found by."""
    pmid, sdy = validate_identifiers("34252919", "SDY2189")

    assert split_stem(f"{sdy}_{pmid}") == (pmid, sdy)


def test_an_accession_without_the_sdy_prefix_is_refused():
    """`ABC123_34252919` would parse back as pubmed_id "ABC123", study "34252919"."""
    with pytest.raises(ValueError, match="SDY"):
        validate_identifiers("34252919", "ABC123")


def test_a_pmc_id_is_not_a_pubmed_id():
    with pytest.raises(ValueError, match="PubMed ID"):
        validate_identifiers("PMC7665312", "SDY2189")


def test_an_empty_identifier_is_refused_before_anything_is_fetched():
    with pytest.raises(ValueError):
        validate_identifiers("", "SDY1")
    with pytest.raises(ValueError):
        validate_identifiers("111", "")


# ── what counts as usable full text ───────────────────────────────────────────

def _reason(xml: str) -> str | None:
    from bs4 import BeautifulSoup
    return unavailable_reason(xml, BeautifulSoup(xml, "xml"))


def test_a_paper_with_a_body_is_usable():
    assert _reason(_FULL_TEXT) is None


def test_an_abstract_only_record_is_not_full_text():
    assert _reason(_ABSTRACT_ONLY) == "PubMed Central has only the abstract, not the full text"


def test_a_publisher_block_is_reported_as_such():
    assert "does not carry it as open access" in _reason(_NOT_OPEN_ACCESS)


def test_a_response_with_no_article_is_not_a_paper():
    assert (_reason("<pmc-articleset></pmc-articleset>")
            == "PubMed Central returned no article for it")


# ── fetching ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_fetched_paper_lands_where_the_pipeline_looks_for_it(corpus, ncbi):
    """The round trip is the point, not the write: the pipeline has to find it afterwards."""
    result = await fetch_jats("34252919", "SDY2189")

    assert result["created"] is True
    assert result["filename"] == "SDY2189_34252919.xml"
    assert (corpus / "SDY2189_34252919.xml").read_text() == _FULL_TEXT
    assert locate_paper_xml("34252919", "SDY2189").name == "SDY2189_34252919.xml"


@pytest.mark.asyncio
async def test_a_fetched_paper_is_offered_by_the_picker_with_no_registry_yet(corpus, ncbi):
    await fetch_jats("34252919", "SDY2189")

    papers = available_papers()

    assert len(papers) == 1
    assert (papers[0]["pubmed_id"], papers[0]["study_accession"]) == ("34252919", "SDY2189")
    assert papers[0]["paper_title"] == "A Paper"
    assert papers[0]["has_registry"] is False


@pytest.mark.asyncio
async def test_a_paper_already_on_disk_is_left_alone_and_costs_no_request(corpus, ncbi):
    """Asking twice is idempotent. Re-fetching renumbers the sentences a stored registry cites,
    so it must never happen as a side effect of adding a paper again."""
    (corpus / "SDY2189_34252919.xml").write_text("<article>the one already here</article>")

    result = await fetch_jats("34252919", "SDY2189")

    assert result["created"] is False
    assert ncbi["calls"].count == 0
    assert "already here" in (corpus / "SDY2189_34252919.xml").read_text()


@pytest.mark.asyncio
async def test_forcing_refetches_and_overwrites(corpus, ncbi):
    (corpus / "SDY2189_34252919.xml").write_text("<article>stale</article>")

    result = await fetch_jats("34252919", "SDY2189", force=True)

    assert result["created"] is True
    assert (corpus / "SDY2189_34252919.xml").read_text() == _FULL_TEXT


@pytest.mark.asyncio
async def test_an_out_dir_overrides_the_corpus_root(tmp_path, corpus, ncbi):
    elsewhere = tmp_path / "elsewhere"

    await fetch_jats("34252919", "SDY2189", out_dir=elsewhere)

    assert (elsewhere / "SDY2189_34252919.xml").exists()
    assert not (corpus / "SDY2189_34252919.xml").exists()


# ── every failure leaves the corpus untouched ─────────────────────────────────

@pytest.mark.asyncio
async def test_a_pmid_with_no_pmc_record_cannot_be_fetched(corpus, ncbi):
    ncbi["pmc_url"] = None

    with pytest.raises(PaperNotInPMCError, match="no open-access PubMed Central"):
        await fetch_jats("34252919", "SDY2189")

    assert list(corpus.iterdir()) == []


@pytest.mark.asyncio
async def test_an_abstract_only_paper_is_refused_with_that_reason(corpus, ncbi):
    """A large minority of papers land here, so the reason has to be specific enough to act on."""
    ncbi["body"] = _ABSTRACT_ONLY

    with pytest.raises(PaperUnavailableError, match="only the abstract"):
        await fetch_jats("34252919", "SDY2189")

    assert list(corpus.iterdir()) == []


@pytest.mark.asyncio
async def test_a_publisher_restricted_paper_is_refused_with_that_reason(corpus, ncbi):
    ncbi["body"] = _NOT_OPEN_ACCESS

    with pytest.raises(PaperUnavailableError, match="does not carry it as open access"):
        await fetch_jats("34252919", "SDY2189")

    assert list(corpus.iterdir()) == []


@pytest.mark.parametrize("body", [_ABSTRACT_ONLY, _NOT_OPEN_ACCESS,
                                  "<pmc-articleset></pmc-articleset>"])
@pytest.mark.asyncio
async def test_every_unavailable_paper_says_it_cannot_be_fetched_online(corpus, ncbi, body):
    """Whoever typed the identifier needs one fact before any diagnosis: this paper's content
    cannot be got. Each reason then says which of the several different ways it failed, because
    an abstract-only record and a paywalled one call for different next steps."""
    ncbi["body"] = body

    with pytest.raises(PaperUnavailableError) as exc:
        await fetch_jats("34252919", "SDY2189")

    assert str(exc.value).startswith("Cannot fetch this paper's content online:")
    assert list(corpus.iterdir()) == []


@pytest.mark.asyncio
async def test_a_paper_with_no_pmc_record_at_all_says_the_same_thing(corpus, ncbi):
    """The other way a paper's content cannot be reached, and it must not read differently."""
    ncbi["pmc_url"] = None

    with pytest.raises(PaperUnavailableError) as exc:
        await fetch_jats("34252919", "SDY2189")

    assert str(exc.value).startswith("Cannot fetch this paper's content online:")


@pytest.mark.asyncio
async def test_ncbi_being_unreachable_is_a_different_failure_from_an_unusable_paper(corpus, ncbi):
    """Retrying helps with one and never with the other, so they are not the same exception."""
    ncbi["raises"] = httpx.ConnectError("no route to host")

    with pytest.raises(PaperFetchError, match="could not reach NCBI"):
        await fetch_jats("34252919", "SDY2189")

    assert list(corpus.iterdir()) == []


@pytest.mark.asyncio
async def test_an_invalid_pair_is_refused_without_a_single_request(corpus, ncbi):
    with pytest.raises(ValueError):
        await fetch_jats("34252919", "ABC123")

    assert ncbi["calls"].count == 0
    assert list(corpus.iterdir()) == []


@pytest.mark.asyncio
async def test_concurrent_fetches_do_not_overlap(corpus, ncbi, monkeypatch):
    """NCBI allows three requests a second without a key and one fetch is two of them, so the
    requests are serialised rather than left to whatever the caller does."""
    overlapping, active = False, 0
    original = jats_fetcher.pmid_to_pmc_url

    async def _tracking(pmid):
        nonlocal overlapping, active
        active += 1
        overlapping = overlapping or active > 1
        await asyncio.sleep(0)
        active -= 1
        return await original(pmid)

    monkeypatch.setattr(jats_fetcher, "pmid_to_pmc_url", _tracking)

    await asyncio.gather(
        fetch_jats("111", "SDY1"),
        fetch_jats("222", "SDY2"),
    )

    assert overlapping is False
    assert {p.name for p in corpus.iterdir()} == {"SDY1_111.xml", "SDY2_222.xml"}
