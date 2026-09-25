"""Turning one typed identifier into every paper it could mean.

No test here reaches the network or a real database. What is under test is the part that decides
what a user meant, and the rule that matters most is the one about *not* deciding: the mapping
between PubMed IDs and study accessions is many-to-many, and a resolver that picked would be
wrong for roughly a tenth of identifiers while saying nothing about it.
"""

import json

import pytest
from sqlalchemy.exc import OperationalError

from app.agent import assay_jobs, assay_service, jats_fetcher, paper_resolver
from app.agent.paper_resolver import (
    UnrecognizedQueryError,
    _BY_PMID,
    _BY_SDY,
    classify,
    resolve,
)

_XML = """<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p></sec></body></article>"""


@pytest.fixture(autouse=True)
def clean_jobs():
    assay_jobs.reset()
    yield
    assay_jobs.reset()


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """An empty corpus, with both assay roots redirected into tmp_path."""
    xml_root, registry_root = tmp_path / "JAT_XML", tmp_path / "assay_registries"
    xml_root.mkdir()
    registry_root.mkdir()
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    # PDF_ROOT is redirected at an empty directory so the listing cannot pick up the
    # repo's real PDFs: available_papers offers PDF-only papers too.
    _pdf_root = tmp_path / "pdf"
    _pdf_root.mkdir(exist_ok=True)
    monkeypatch.setattr(assay_service, "PDF_ROOT", _pdf_root)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)
    return xml_root, registry_root


class _FakeSession:
    """Records the statement and the bound parameters, and answers with canned rows.

    `by_param` answers differently per bound value, which the PMC path needs: it asks once by
    the converted PubMed ID and, finding nothing, again by the PMC id itself.
    """

    def __init__(self, rows=None, raises=None, by_param=None):
        self.rows, self.raises, self.by_param = rows or [], raises, by_param
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        if self.raises is not None:
            raise self.raises
        if self.by_param is not None:
            value = next(iter((params or {}).values()), None)
            rows = self.by_param.get(value, [])
        else:
            rows = self.rows
        return type("R", (), {"mappings": lambda self: type("M", (), {"all": lambda self: rows})()})()


def _row(study_accession, pubmed_id, **extra):
    return {"study_accession": study_accession, "pubmed_id": pubmed_id,
            "title": extra.get("title", "A paper"), "journal": extra.get("journal", "J Immunol"),
            "year": extra.get("year", 2021), "authors": extra.get("authors", "A. Author"),
            "doi": extra.get("doi", "10.1000/x")}


# ── what a typed string is taken to mean ──────────────────────────────────────

@pytest.mark.parametrize("query,expected", [
    ("SDY2189", ("study_accession", "SDY2189")),
    ("sdy2189", ("study_accession", "SDY2189")),
    ("  SDY2189  ", ("study_accession", "SDY2189")),
    ("34252919", ("pubmed_id", "34252919")),
    ("PMID:34252919", ("pubmed_id", "34252919")),
    ("PMID 34252919", ("pubmed_id", "34252919")),
    ("PMC8761119", ("pmc_id", "PMC8761119")),
    ("https://pmc.ncbi.nlm.nih.gov/articles/PMC8761119/", ("pmc_id", "PMC8761119")),
    ("https://pubmed.ncbi.nlm.nih.gov/34252919", ("pubmed_id", "34252919")),
])
def test_each_identifier_shape_is_recognised(query, expected):
    assert classify(query) == expected


@pytest.mark.parametrize("query", ["", "   ", "SDY", "PMC", "flow cytometry", "SDY-2189"])
def test_a_string_that_is_not_an_identifier_is_refused(query):
    with pytest.raises(UnrecognizedQueryError):
        classify(query)


def test_the_refusal_names_all_three_accepted_shapes():
    """A 400 on a cost-bearing page should say what would have worked."""
    with pytest.raises(UnrecognizedQueryError) as exc:
        classify("flow cytometry")

    message = str(exc.value)
    assert "34252919" in message and "SDY2189" in message and "PMC8761119" in message


def test_the_resolver_and_the_fetcher_share_one_definition_of_each_identifier():
    """Two copies would drift, and a drift here means offering a pair that fetch_jats refuses."""
    assert paper_resolver.PMID_RE is jats_fetcher.PMID_RE
    assert paper_resolver.SDY_RE is jats_fetcher.SDY_RE


# ── the query itself ──────────────────────────────────────────────────────────

def test_neither_lookup_carries_a_limit():
    """orchestrator.py asks this question with LIMIT 1 in seven places and so silently answers
    one of the five studies PMID 26682988 belongs to. This module must not repeat it."""
    assert "LIMIT" not in str(_BY_PMID).upper()
    assert "LIMIT" not in str(_BY_SDY).upper()


@pytest.mark.asyncio
async def test_identifiers_are_bound_not_interpolated(corpus):
    session = _FakeSession()

    await resolve("SDY2189", session)

    statement, params = session.calls[0]
    assert params == {"study_accession": "SDY2189"}
    assert "SDY2189" not in statement


# ── the case the module exists for ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_study_with_several_papers_returns_all_of_them(corpus):
    """SDY212 really does have six. Returning one would be wrong five times out of six."""
    session = _FakeSession([
        _row("SDY212", "23591775", year=2013), _row("SDY212", "24337376", year=2014),
        _row("SDY212", "25834109", year=2015), _row("SDY212", "27746093", year=2016),
        _row("SDY212", "30842675", year=2019), _row("SDY212", "31636302", year=2019),
    ])

    resolution = await resolve("SDY212", session)

    assert resolution["total"] == 6
    assert [c["pubmed_id"] for c in resolution["candidates"]] == [
        "23591775", "24337376", "25834109", "27746093", "30842675", "31636302"]
    assert all(c["title"] and c["year"] for c in resolution["candidates"])


@pytest.mark.asyncio
async def test_a_paper_belonging_to_several_studies_returns_all_of_them(corpus):
    """The direction that misfiles rather than mis-extracts: the accession decides which study
    directory a verified registry is written under."""
    rows = [_row(sdy, "26682988")
            for sdy in ("SDY1119", "SDY269", "SDY270", "SDY56", "SDY61")]

    resolution = await resolve("26682988", _FakeSession(rows))

    assert {c["study_accession"] for c in resolution["candidates"]} == {
        "SDY1119", "SDY269", "SDY270", "SDY56", "SDY61"}


@pytest.mark.asyncio
async def test_the_candidate_order_does_not_shuffle_between_two_identical_resolves(corpus):
    """A list that reorders under the cursor is a list you misclick."""
    rows = [_row("SDY212", pmid) for pmid in ("23591775", "25834109", "31636302")]

    first = await resolve("SDY212", _FakeSession(rows))
    second = await resolve("SDY212", _FakeSession(rows))

    assert [c["pubmed_id"] for c in first["candidates"]] == \
           [c["pubmed_id"] for c in second["candidates"]]


# ── the database is not required ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unreachable_database_degrades_instead_of_failing(corpus):
    """The 30 local papers still work without it; only discovery of new ones is lost. A 500
    here would take the whole page down to lose that."""
    xml_root, _ = corpus
    (xml_root / "SDY2189_34252919.xml").write_text(_XML, encoding="utf-8")
    session = _FakeSession(raises=OperationalError("SELECT 1", {}, Exception("down")))

    resolution = await resolve("SDY2189", session)

    assert resolution["degraded"] is True
    assert resolution["source"] == "local"
    assert resolution["warning"]
    assert resolution["total"] == 1
    candidate = resolution["candidates"][0]
    assert candidate["in_db"] is False
    assert candidate["has_xml"] is True
    # Absence is reported, never invented: there is no title without the database.
    assert candidate["title"] is None
    assert candidate["paper_title"] == "A Paper"


@pytest.mark.asyncio
async def test_a_paper_on_disk_that_the_database_has_never_heard_of_is_still_offered(corpus):
    xml_root, _ = corpus
    (xml_root / "SDY9999_11112222.xml").write_text(_XML, encoding="utf-8")

    resolution = await resolve("SDY9999", _FakeSession([]))

    assert resolution["total"] == 1
    assert resolution["degraded"] is False
    assert resolution["source"] == "local"
    assert "study_pubmed" in resolution["warning"]


@pytest.mark.asyncio
async def test_a_registry_whose_xml_was_deleted_is_still_offered(corpus):
    """The extraction survives its source file, and re-fetching would restore it."""
    _, registry_root = corpus
    directory = registry_root / "11112222_SDY9999"
    directory.mkdir()
    (directory / "assays.json").write_text(json.dumps({"flow cytometry": {}}), encoding="utf-8")

    resolution = await resolve("SDY9999", _FakeSession([]))

    candidate = resolution["candidates"][0]
    assert (candidate["has_xml"], candidate["has_registry"]) == (False, True)


@pytest.mark.asyncio
async def test_a_pair_in_both_places_appears_once(corpus):
    xml_root, _ = corpus
    (xml_root / "SDY2189_34252919.xml").write_text(_XML, encoding="utf-8")

    resolution = await resolve("SDY2189", _FakeSession([_row("SDY2189", "34252919")]))

    assert resolution["total"] == 1
    assert resolution["candidates"][0]["in_db"] is True
    assert resolution["candidates"][0]["has_xml"] is True
    assert resolution["source"] == "db"


@pytest.mark.asyncio
async def test_a_database_row_with_no_file_is_where_a_run_would_have_to_fetch(corpus):
    resolution = await resolve("SDY2189", _FakeSession([_row("SDY2189", "34252919")]))

    candidate = resolution["candidates"][0]
    assert (candidate["has_xml"], candidate["has_registry"], candidate["assays"]) == \
           (False, False, None)


# ── ImmPort's pubmed_id column is not reliably a PubMed ID ────────────────────

@pytest.mark.asyncio
async def test_a_study_whose_paper_is_recorded_as_tbd_is_shown_but_not_runnable(corpus):
    """28 of study_pubmed's 1,562 rows hold "TBD", "Not Applicable" or a PMC id. `<SDY>_TBD.xml`
    is not a paper, so the row is reported as unusable here rather than refused later by
    validate_identifiers with a 400 that says nothing about why."""
    resolution = await resolve("SDY2540", _FakeSession([_row("SDY2540", "TBD")]))

    candidate = resolution["candidates"][0]
    assert candidate["usable"] is False
    assert "TBD" in candidate["unusable_reason"]
    assert resolution["warning"]


@pytest.mark.asyncio
async def test_a_row_holding_a_pmc_id_names_the_way_forward(corpus):
    """This page accepts a PMC id typed directly, so the reason says so."""
    resolution = await resolve("SDY3312", _FakeSession([_row("SDY3312", "PMC12543083")]))

    candidate = resolution["candidates"][0]
    assert candidate["usable"] is False
    assert "PMC12543083" in candidate["unusable_reason"]


@pytest.mark.asyncio
async def test_a_labelled_pubmed_id_is_recovered_rather_than_discarded(corpus):
    """One row really is spelled "PMID: 38019093"."""
    resolution = await resolve("SDY2951", _FakeSession([_row("SDY2951", "PMID: 38019093")]))

    candidate = resolution["candidates"][0]
    assert candidate["usable"] is True
    assert candidate["pubmed_id"] == "38019093"


@pytest.mark.asyncio
async def test_runnable_candidates_are_listed_before_unrunnable_ones(corpus):
    """A list whose first entry cannot be clicked reads as a broken page."""
    rows = [_row("SDY1", "TBD"), _row("SDY1", "34252919"), _row("SDY1", "Not Applicable")]

    resolution = await resolve("SDY1", _FakeSession(rows))

    assert [c["usable"] for c in resolution["candidates"]] == [True, False, False]


@pytest.mark.asyncio
async def test_a_pair_from_a_filename_is_usable_by_construction(corpus):
    """split_stem already parsed it, so it cannot be "TBD"."""
    xml_root, _ = corpus
    (xml_root / "SDY2189_34252919.xml").write_text(_XML, encoding="utf-8")

    resolution = await resolve("SDY2189", _FakeSession([]))

    assert resolution["candidates"][0]["usable"] is True


# ── the PMC branch ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_pmc_id_is_converted_before_the_database_is_asked(corpus, monkeypatch):
    async def _convert(_pmc):
        return "34252919"

    monkeypatch.setattr(paper_resolver, "pmc_to_pmid", _convert)
    session = _FakeSession([_row("SDY2189", "34252919")])

    resolution = await resolve("PMC8761119", session)

    assert session.calls[0][1] == {"pubmed_id": "34252919"}
    assert resolution["pmc_id"] == "PMC8761119"
    assert resolution["resolved_via"] == "pmc"
    assert resolution["pubmed_id"] == "34252919"


@pytest.mark.asyncio
async def test_a_pmc_id_converted_to_a_number_is_still_a_string(corpus, monkeypatch):
    """NCBI's id converter returns the pmid as a JSON number for some records and a string for
    others; every identifier downstream of here is a string."""
    async def _convert(_pmc):
        return 34252919

    monkeypatch.setattr(paper_resolver, "pmc_to_pmid", _convert)
    session = _FakeSession([_row("SDY2189", "34252919")])

    resolution = await resolve("PMC8761119", session)

    assert resolution["pubmed_id"] == "34252919"
    assert session.calls[0][1] == {"pubmed_id": "34252919"}


@pytest.mark.asyncio
async def test_a_study_recorded_only_by_its_pmc_id_is_still_found_by_that_pmc_id(corpus,
                                                                                 monkeypatch):
    """The 28 rows that store a PMC id are invisible to a lookup by the converted PubMed ID --
    which is precisely the study the "type the PMC id" hint sends people to. Without the second
    lookup the hint is a dead end."""
    async def _convert(_pmc):
        return "40991727"

    monkeypatch.setattr(paper_resolver, "pmc_to_pmid", _convert)
    session = _FakeSession(by_param={
        "40991727": [],
        "PMC12543083": [_row("SDY3311", "PMC12543083"), _row("SDY3312", "PMC12543083")],
    })

    resolution = await resolve("PMC12543083", session)

    assert resolution["total"] == 2
    # Carried back runnable: the PMC string could not name a file, the converted id can.
    assert all(c["usable"] for c in resolution["candidates"])
    assert {c["pubmed_id"] for c in resolution["candidates"]} == {"40991727"}
    assert {c["study_accession"] for c in resolution["candidates"]} == {"SDY3311", "SDY3312"}
    assert "PMC12543083" in resolution["warning"]


@pytest.mark.asyncio
async def test_the_second_lookup_is_skipped_when_the_first_one_answered(corpus, monkeypatch):
    """One query, not two, for the overwhelming majority of PMC ids."""
    async def _convert(_pmc):
        return "34252919"

    monkeypatch.setattr(paper_resolver, "pmc_to_pmid", _convert)
    session = _FakeSession(by_param={"34252919": [_row("SDY2189", "34252919")]})

    await resolve("PMC8761119", session)

    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_a_pmc_id_that_converts_to_nothing_says_it_cannot_tell_why(corpus, monkeypatch):
    """pmc_to_pmid swallows its own errors and returns None either way, so the reason must not
    claim the paper does not exist."""
    async def _convert(_pmc):
        return None

    monkeypatch.setattr(paper_resolver, "pmc_to_pmid", _convert)

    resolution = await resolve("PMC9999999", _FakeSession())

    assert resolution["candidates"] == []
    assert "unreachable" in resolution["reason"]


@pytest.mark.asyncio
async def test_a_plain_identifier_never_touches_ncbi(corpus, monkeypatch):
    """Resolve runs on every submission; it is a database read, not a network call."""
    calls = []

    async def _convert(pmc):
        calls.append(pmc)
        return None

    monkeypatch.setattr(paper_resolver, "pmc_to_pmid", _convert)

    await resolve("34252919", _FakeSession([_row("SDY2189", "34252919")]))
    await resolve("SDY2189", _FakeSession([_row("SDY2189", "34252919")]))

    assert calls == []


# ── nothing matched ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_identifier_that_matches_nothing_is_an_answer_not_an_error(corpus):
    resolution = await resolve("SDY9999", _FakeSession([]))

    assert resolution["candidates"] == []
    assert resolution["reason"]
    assert resolution["source"] == "none"


@pytest.mark.asyncio
async def test_a_bare_number_that_found_nothing_suggests_the_pmc_spelling(corpus):
    """Bare digits are read as a PubMed ID, and 8761119 is also a plausible PMC number."""
    resolution = await resolve("8761119", _FakeSession([]))

    assert "PMC8761119" in resolution["reason"]


# ── adopting a run already under way ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_candidate_carries_the_id_of_a_run_already_going(corpus):
    """So a caller adopts it rather than discovering the 409 by paying for a POST."""
    job = assay_jobs.create("34252919", "SDY2189")
    job.state = "running"

    resolution = await resolve("SDY2189", _FakeSession([_row("SDY2189", "34252919")]))

    assert resolution["candidates"][0]["active_job_id"] == job.id


@pytest.mark.asyncio
async def test_a_finished_run_is_not_offered_for_adoption(corpus):
    job = assay_jobs.create("34252919", "SDY2189")
    assay_jobs.finish(job.id, {"meta": {"llm_calls": 3}})

    resolution = await resolve("SDY2189", _FakeSession([_row("SDY2189", "34252919")]))

    assert resolution["candidates"][0]["active_job_id"] is None


@pytest.mark.asyncio
async def test_a_year_stored_as_text_comes_back_as_a_number(corpus):
    resolution = await resolve("SDY2189", _FakeSession([_row("SDY2189", "34252919", year="2021")]))

    assert resolution["candidates"][0]["year"] == 2021


@pytest.mark.asyncio
async def test_an_unparseable_year_is_dropped_rather_than_guessed(corpus):
    resolution = await resolve("SDY2189", _FakeSession([_row("SDY2189", "34252919", year="n/a")]))

    assert resolution["candidates"][0]["year"] is None
