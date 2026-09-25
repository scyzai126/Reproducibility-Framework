"""Does ImmPort record this assay as an experiment for this study?

No test here reaches a database or a model: the session is a fake that answers from a canned
experiment table. What is under test is which search terms are tried, the rule that the sweep
never pays unless asked, and the distinction between the three different ways the answer can be
"no" -- because only one of them is worth spending a model call on.
"""

import pytest

from app.agent import assay_immport
from app.agent.assay_immport import (
    ABSENT,
    MATCHED,
    NO_EXPERIMENTS,
    UNKNOWN_STUDY,
    check_rows,
    search_terms,
    study_accession_of,
    summarize,
)


class _FakeSession:
    """Answers the count query and the LIKE query from a canned {study: [(acc, technique)]}."""

    def __init__(self, experiments=None):
        self.experiments = experiments or {}
        self.like_terms: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "COUNT(*)" in sql:
            rows = [(s, len(e)) for s, e in self.experiments.items()
                    if s in set(params.get("studies") or [])]
        elif "measurement_technique FROM experiment WHERE experiment_accession" in sql:
            # get_assay_method_for_experiment: one row, one column.
            wanted = params.get("acc", "")
            rows = [(tech,) for e in self.experiments.values()
                    for acc, tech in e if acc == wanted]
        elif "pattern" not in params:
            # The LLM fallback's candidate list: every experiment in the study.
            rows = list(self.experiments.get(params.get("study_accession", ""), []))
        else:
            study = params.get("study_accession", "")
            pattern = (params.get("pattern") or "").strip("%").lower()
            if pattern:
                self.like_terms.append(pattern)
            rows = [(acc, tech) for acc, tech in self.experiments.get(study, [])
                    if pattern and pattern in tech.lower()]
        return type("R", (), {
            "fetchall": lambda self: rows,
            "fetchone": lambda self: rows[0] if rows else None,
            "keys": lambda self: ["experiment_accession", "measurement_technique"],
        })()


@pytest.fixture(autouse=True)
def llm_cache(tmp_path, monkeypatch):
    """Every test gets an empty cache of its own; none touches the one under data/."""
    path = tmp_path / "immport_llm_cache.json"
    monkeypatch.setattr(assay_immport, "LLM_CACHE_PATH", path)
    return path


class _FakeModel:
    """Stands in for the OpenAI client; answers every call with `answer` and counts them."""

    def __init__(self, answer):
        self.answer, self.calls = answer, 0
        self.chat = type("c", (), {"completions": self})()

    async def create(self, **_):
        self.calls += 1
        message = type("m", (), {"content": self.answer})()
        return type("r", (), {"choices": [type("ch", (), {"message": message})()]})()


@pytest.fixture
def model(monkeypatch):
    def _install(answer):
        fake = _FakeModel(answer)
        monkeypatch.setattr("app.agent.query_builder._get_openai_client", lambda: fake)
        return fake
    return _install


def _row(**kw):
    base = {"study": "19029902_SDY1264", "assay": "", "normalized_name": "", "obi_label": ""}
    return {**base, **kw}


# ── which wordings get tried ──────────────────────────────────────────────────

def test_the_technique_is_tried_before_the_paper_s_own_wording():
    """ImmPort's column holds the technique ("Luminex xMAP"), not the paper's phrasing."""
    terms = search_terms(assay="24-plex Luminex assay", normalized_name="Luminex xMAP")

    assert terms[0] == "Luminex xMAP"


def test_an_obi_label_is_also_tried_without_its_trailing_assay():
    """`%flow cytometry assay%` does not match ImmPort's "Flow Cytometry"; stripping the suffix
    is free and is most of the difference between resolving and not."""
    terms = search_terms(assay="", obi_label="flow cytometry assay")

    assert "flow cytometry assay" in terms
    assert "flow cytometry" in terms


def test_aliases_are_tried_too():
    terms = search_terms(assay="Flow cytometric analysis", aliases=["FACS"])

    assert "FACS" in terms


def test_a_term_repeated_in_another_case_is_tried_once():
    """Each term costs a query."""
    terms = search_terms(assay="ELISA", normalized_name="elisa", obi_label="ELISA")

    assert len(terms) == 1


def test_a_term_too_short_to_discriminate_is_dropped():
    """`%PCR%` against a study's experiments is noise, not a resolution."""
    assert "PCR" not in search_terms(assay="PCR")


def test_the_study_half_is_taken_from_either_spelling():
    assert study_accession_of({"study": "19029902_SDY1264"}) == "SDY1264"
    assert study_accession_of({"study": "SDY1264"}) == "SDY1264"
    assert study_accession_of({"study": ""}) == ""


# ── the three different ways the answer is "no" ───────────────────────────────

@pytest.mark.asyncio
async def test_an_assay_immport_registered_is_matched_with_its_accession():
    session = _FakeSession({"SDY1264": [("EXP16737", "Virus Neutralization")]})

    report = await check_rows(session, [_row(normalized_name="Virus Neutralization")])

    row = report["rows"][0]
    assert row["status"] == MATCHED
    assert row["experiment_accession"] == "EXP16737"
    assert row["method"] == "SQL"
    # ImmPort's own name for the technique, which is what a "yes" is worth reading.
    assert row["measurement_technique"] == "Virus Neutralization"


@pytest.mark.asyncio
async def test_a_study_with_nothing_registered_is_answered_without_a_single_lookup():
    """The cheapest true answer the sweep can give, and it must never reach a model."""
    session = _FakeSession({"SDY1264": []})

    report = await check_rows(session, [_row(normalized_name="Virus Neutralization")])

    assert report["rows"][0]["status"] == NO_EXPERIMENTS
    assert session.like_terms == []


@pytest.mark.asyncio
async def test_an_assay_the_study_does_not_register_is_absent_not_missing():
    """ImmPort has experiments for this study; this is not recognisably one of them. That is the
    one status a model call could still change, which is why it is kept apart."""
    session = _FakeSession({"SDY1264": [("EXP16737", "Virus Neutralization")]})

    report = await check_rows(session, [_row(normalized_name="Mass spectrometry")])

    row = report["rows"][0]
    assert row["status"] == ABSENT
    assert row["study_experiments"] == 1
    # Nothing matched, so there is no technique to name.
    assert row["measurement_technique"] is None


@pytest.mark.asyncio
async def test_a_row_whose_study_cannot_be_read_says_so_rather_than_guessing():
    report = await check_rows(_FakeSession(), [_row(study="not-a-study-id")])

    assert report["rows"][0]["status"] == UNKNOWN_STUDY


# ── the sweep does not spend ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_sweep_never_reaches_the_model(monkeypatch):
    """171 rows must cost nothing. The resolver's LLM fallback is opt-in per call, and the
    sweep does not opt in."""
    def _explode(*_a, **_k):
        raise AssertionError("the free sweep asked for a model client")

    monkeypatch.setattr("app.agent.query_builder._get_openai_client", _explode)
    session = _FakeSession({"SDY1264": [("EXP1", "Flow Cytometry")]})

    report = await check_rows(session, [_row(normalized_name="Mass spectrometry")])

    assert report["rows"][0]["status"] == ABSENT


@pytest.mark.asyncio
async def test_every_wording_is_tried_before_a_row_is_called_absent():
    """A row is only unresolved once each of its names has missed."""
    session = _FakeSession({"SDY1264": [("EXP1", "Flow Cytometry")]})

    await check_rows(session, [_row(assay="Flow cytometric analysis",
                                    normalized_name="", obi_label="flow cytometry assay")])

    assert "flow cytometry" in session.like_terms


@pytest.mark.asyncio
async def test_a_later_wording_can_rescue_a_row_the_first_one_missed():
    """The suffix-stripped OBI label is what finds "Flow Cytometry"; without it this is absent."""
    session = _FakeSession({"SDY1264": [("EXP1", "Flow Cytometry")]})

    report = await check_rows(session, [_row(assay="High-parameter panel",
                                             obi_label="flow cytometry assay")])

    assert report["rows"][0]["status"] == MATCHED
    assert report["rows"][0]["experiment_accession"] == "EXP1"


# ── the LLM fallback, when asked for ──────────────────────────────────────────

_PRNT = {"normalized_name": "plaque reduction neutralization test",
         "assay": "plaque reduction neutralization test (PRNT)"}


@pytest.mark.asyncio
async def test_a_row_sql_misses_is_handed_to_the_model(model):
    """PRNT shares no whole phrase with "Virus Neutralization"; the model is what places it."""
    fake = model("EXP16737")
    session = _FakeSession({"SDY1264": [("EXP16737", "Virus Neutralization")]})

    report = await check_rows(session, [_row(**_PRNT)], use_llm=True)

    row = report["rows"][0]
    assert row["status"] == MATCHED
    assert row["experiment_accession"] == "EXP16737"
    assert row["method"] == "LLM"
    assert row["measurement_technique"] == "Virus Neutralization"
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_a_row_sql_resolves_never_reaches_the_model(model):
    fake = model("EXP16737")
    session = _FakeSession({"SDY1264": [("EXP16737", "Virus Neutralization")]})

    report = await check_rows(session, [_row(normalized_name="Virus Neutralization")],
                              use_llm=True)

    assert report["rows"][0]["method"] == "SQL"
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_a_second_look_is_answered_from_the_cache(model, llm_cache):
    fake = model("EXP16737")
    experiments = {"SDY1264": [("EXP16737", "Virus Neutralization")]}

    await check_rows(_FakeSession(experiments), [_row(**_PRNT)], use_llm=True)
    report = await check_rows(_FakeSession(experiments), [_row(**_PRNT)], use_llm=True)

    assert fake.calls == 1
    assert report["rows"][0]["method"] == "LLM"
    assert report["rows"][0]["experiment_accession"] == "EXP16737"
    assert llm_cache.exists()


@pytest.mark.asyncio
async def test_a_none_from_the_model_is_cached_as_absent(model):
    """"None of these" was paid for; asking again would buy the same answer."""
    fake = model("NONE")
    experiments = {"SDY1264": [("EXP1", "Flow Cytometry")]}

    first = await check_rows(_FakeSession(experiments), [_row(**_PRNT)], use_llm=True)
    second = await check_rows(_FakeSession(experiments), [_row(**_PRNT)], use_llm=True)

    assert first["rows"][0]["status"] == ABSENT
    assert second["rows"][0]["status"] == ABSENT
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_a_failed_call_leaves_the_row_absent_and_uncached(monkeypatch, llm_cache):
    """An error is not an answer, so the next load asks again rather than trusting it."""
    def _broken():
        raise RuntimeError("openai is down")

    monkeypatch.setattr("app.agent.query_builder._get_openai_client", _broken)
    session = _FakeSession({"SDY1264": [("EXP16737", "Virus Neutralization")]})

    report = await check_rows(session, [_row(**_PRNT)], use_llm=True)

    assert report["rows"][0]["status"] == ABSENT
    assert not llm_cache.exists()


# ── the arithmetic a caller pays against ──────────────────────────────────────

def test_only_the_absent_rows_are_worth_paying_to_resolve():
    """A study with nothing registered cannot be rescued by a model, so it is not billed for."""
    results = [
        {"status": MATCHED, "study_accession": "SDY1"},
        {"status": ABSENT, "study_accession": "SDY1"},
        {"status": ABSENT, "study_accession": "SDY1"},
        {"status": NO_EXPERIMENTS, "study_accession": "SDY2"},
        {"status": UNKNOWN_STUDY, "study_accession": ""},
    ]

    stats = summarize(results)

    assert (stats["total"], stats["matched"], stats["absent"]) == (5, 1, 2)
    assert stats["resolvable"] == 2
    assert stats["studies_without_experiments"] == ["SDY2"]


@pytest.mark.asyncio
async def test_the_report_is_keyed_the_way_the_response_model_reads_it():
    """AssayImmportResponse declares `rows`; a report keyed `results` is silently dropped by the
    response model rather than raising, and the table renders empty."""
    report = await check_rows(_FakeSession({"SDY1264": []}), [_row()])

    assert "rows" in report and "stats" in report
