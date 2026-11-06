"""The ImmPort paper list: one row per PubMed ID, every study kept, nothing silently dropped.

No database here. What is under test is the folding -- a paper cited by five studies is one
paper -- and the bookkeeping that keeps the 28 non-paper rows visible instead of missing.
"""

import csv

import pytest

from app.agent import immport_corpus
from app.agent.immport_corpus import (
    PAPER_COLUMNS,
    group_papers,
    paper_rows,
    primary_sdy,
    sdy_key,
    summary,
    write_csv,
)


# ── grouping ─────────────────────────────────────────────────────────────────

def test_one_entry_per_pmid_with_every_study():
    rows = [("SDY1119", "26682988"), ("SDY1260", "26682988"), ("SDY80", "26682988"),
            ("SDY212", "23591775")]
    grouped, unusable = group_papers(rows)
    assert grouped == {"26682988": ["SDY80", "SDY1119", "SDY1260"], "23591775": ["SDY212"]}
    assert unusable == []


def test_duplicate_row_counts_once():
    grouped, _ = group_papers([("SDY1", "111"), ("SDY1", "111")])
    assert grouped == {"111": ["SDY1"]}


def test_unusable_rows_are_kept_with_a_reason():
    rows = [("SDY1", "TBD"), ("SDY2", "Not Applicable"), ("SDY3", "PMC1234567"),
            ("SDY4", "PMID: 123"), ("SDY5", None)]
    grouped, unusable = group_papers(rows)
    assert grouped == {"123": ["SDY4"]}  # the label is stripped, the row is usable
    assert [u["study_accession"] for u in unusable] == ["SDY1", "SDY2", "SDY3", "SDY5"]
    assert [u["raw_value"] for u in unusable] == ["TBD", "Not Applicable", "PMC1234567", ""]
    assert all(u["reason"] for u in unusable)
    assert "PMC id" in unusable[2]["reason"]


# ── naming ───────────────────────────────────────────────────────────────────

def test_primary_sdy_is_numeric_not_lexical():
    assert primary_sdy(["SDY1119", "SDY80"]) == "SDY80"
    assert sorted(["SDY1119", "SDY80", "SDY212"], key=sdy_key) == ["SDY80", "SDY212", "SDY1119"]


def test_primary_sdy_needs_a_study():
    with pytest.raises(ValueError):
        primary_sdy([])


# ── rows ─────────────────────────────────────────────────────────────────────

def test_paper_rows_sorted_by_numeric_pmid_with_joined_studies():
    rows = paper_rows({"9999999": ["SDY2"], "26682988": ["SDY1119", "SDY80"]})
    assert [r["pmid"] for r in rows] == ["9999999", "26682988"]
    assert rows[1] == {"pmid": "26682988", "study_accessions": "SDY80;SDY1119",
                       "primary_sdy": "SDY80", "n_studies": 2}


def test_summary_counts():
    rows = [("SDY1", "111"), ("SDY2", "111"), ("SDY3", "222"), ("SDY4", "TBD")]
    grouped, unusable = group_papers(rows)
    assert summary(rows, grouped, unusable) == {
        "rows": 4, "usable_pmids": 2, "shared_pmids": 1, "max_studies_per_pmid": 2,
        "studies": 3, "unusable_rows": 1,
    }


# ── writing ──────────────────────────────────────────────────────────────────

def test_write_csv_round_trip_leaves_no_temp_file(tmp_path):
    path = tmp_path / "papers_all.csv"
    write_csv(path, paper_rows({"111": ["SDY1", "SDY2"]}), PAPER_COLUMNS)

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [{"pmid": "111", "study_accessions": "SDY1;SDY2", "primary_sdy": "SDY1",
                     "n_studies": "2"}]
    assert not (tmp_path / "papers_all.csv.tmp").exists()


def test_write_csv_keeps_the_old_file_when_writing_fails(tmp_path, monkeypatch):
    path = tmp_path / "papers_all.csv"
    path.write_text("old\n", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(csv.DictWriter, "writerow", _boom)
    with pytest.raises(OSError):
        write_csv(path, [{"pmid": "1"}], PAPER_COLUMNS)

    assert path.read_text(encoding="utf-8") == "old\n"
    assert not (tmp_path / "papers_all.csv.tmp").exists()


def test_default_lists_live_on_the_external_drive():
    assert immport_corpus.PAPERS_DIR == immport_corpus.Path("/Volumes/Extreme SSD/HIPC papers")
