"""A study with several papers asks which one to run instead of paying for all of them."""

import pytest

from app.agent import orchestrator
from app.agent.orchestrator import _choose_sdy_paper

_ROWS = [
    {"pubmed_id": "23266342", "title": "Paper A", "year": 2013},
    {"pubmed_id": "23844129", "title": "Paper B", "year": 2013},
]


@pytest.fixture(autouse=True)
def no_local_files(monkeypatch):
    monkeypatch.setattr(orchestrator, "_load_disk_cache", lambda pmid, step: None)
    monkeypatch.setattr(orchestrator, "_find_local_pdf", lambda sdy, pmid: None)


def test_several_papers_returns_the_list():
    ids, choice = _choose_sdy_paper("SDY1364", _ROWS, "SDY1364")
    assert ids == []
    assert choice["type"] == "paper_choice"
    assert choice["study_accession"] == "SDY1364"
    assert [o["pubmed_id"] for o in choice["paper_options"]] == ["23266342", "23844129"]
    assert choice["paper_options"][0]["title"] == "Paper A"


def test_chosen_pmid_runs_only_that_paper():
    ids, choice = _choose_sdy_paper("SDY1364", _ROWS, "SDY1364 PMID:23844129")
    assert (ids, choice) == (["23844129"], None)


def test_pmid_not_in_the_study_is_refused():
    with pytest.raises(ValueError, match="23266342, 23844129"):
        _choose_sdy_paper("SDY1364", _ROWS, "SDY1364 PMID:99999999")


def test_single_paper_runs_without_asking():
    ids, choice = _choose_sdy_paper("SDY1", _ROWS[:1], "SDY1")
    assert (ids, choice) == (["23266342"], None)


def test_options_flag_cache_and_local_pdf(monkeypatch):
    monkeypatch.setattr(orchestrator, "_load_disk_cache",
                        lambda pmid, step: {"claim_1": {}} if pmid == "23266342" else None)
    monkeypatch.setattr(orchestrator, "_find_local_pdf",
                        lambda sdy, pmid: "x.pdf" if pmid == "23844129" else None)
    _, choice = _choose_sdy_paper("SDY1364", _ROWS, "SDY1364")
    a, b = choice["paper_options"]
    assert (a["cached"], a["local_pdf"]) == (True, False)
    assert (b["cached"], b["local_pdf"]) == (False, True)


def test_non_pubmed_row_is_listed_but_not_choosable():
    rows = _ROWS + [{"pubmed_id": "TBD", "title": None, "year": None}]
    _, choice = _choose_sdy_paper("SDY1364", rows, "SDY1364")
    tbd = choice["paper_options"][2]
    assert tbd["usable"] is False and tbd["unusable_reason"]
    assert tbd["cached"] is False and tbd["local_pdf"] is False
