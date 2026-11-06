"""The ImmPort paper list: one row per PubMed ID, every study kept, nothing silently dropped.

No database here. What is under test is the folding -- a paper cited by five studies is one
paper -- and the bookkeeping that keeps the 28 non-paper rows visible instead of missing.
"""

import csv

import pytest

from app.agent import immport_corpus
from app.agent.immport_corpus import (
    PAPER_COLUMNS,
    benchmark_xml,
    existing_xml,
    group_papers,
    is_permanent,
    paper_rows,
    parse_idconv,
    primary_sdy,
    read_papers,
    sdy_key,
    summary,
    write_csv,
    xml_name,
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


# ── step 2: reading the list back, naming files, finding what is on disk ─────

def test_read_papers_splits_the_studies(tmp_path):
    path = tmp_path / "papers_all.csv"
    write_csv(path, paper_rows({"111": ["SDY1119", "SDY80"]}), PAPER_COLUMNS)
    rows = read_papers(path)
    assert rows[0]["studies"] == ["SDY80", "SDY1119"]
    assert rows[0]["primary_sdy"] == "SDY80"
    assert read_papers(tmp_path / "absent.csv") == []


def test_xml_name_is_sdy_first_and_validated():
    assert xml_name("SDY80", "111") == "SDY80_111.xml"
    with pytest.raises(ValueError):
        xml_name("ABC", "111")
    with pytest.raises(ValueError):
        xml_name("SDY80", "PMC111")


def test_existing_xml_reads_both_stem_orders_and_ignores_appledouble(tmp_path):
    (tmp_path / "SDY80_111.xml").write_text("x")
    (tmp_path / "222_SDY2.xml").write_text("x")
    (tmp_path / "._SDY80_111.xml").write_text("x")  # ExFAT metadata twin
    (tmp_path / "notes.xml").write_text("x")  # no second half
    found = existing_xml(tmp_path)
    assert set(found) == {"111", "222"}
    assert found["111"].name == "SDY80_111.xml"
    assert existing_xml(tmp_path / "missing") == {}


def test_parse_idconv_handles_int_pmids_and_error_records():
    payload = {"records": [
        {"pmid": 111, "pmcid": "PMC1"},
        {"pmid": "222", "status": "error", "errmsg": "invalid article id"},
        {"pmid": "333"},  # in PubMed, no PMC record
        {"pmcid": "PMC9"},  # no pmid at all: nothing to key it by
    ]}
    assert parse_idconv(payload) == {"111": "PMC1", "222": None, "333": None}
    assert parse_idconv({}) == {}


def test_benchmark_xml_tries_every_study_and_both_orders(tmp_path):
    (tmp_path / "SDY1119_111.xml").write_text("x")
    (tmp_path / "222_SDY5.xml").write_text("x")
    assert benchmark_xml("111", ["SDY80", "SDY1119"], tmp_path).name == "SDY1119_111.xml"
    assert benchmark_xml("222", ["SDY5"], tmp_path).name == "222_SDY5.xml"
    assert benchmark_xml("333", ["SDY80"], tmp_path) is None


# ── step 3: the assay run's bookkeeping ──────────────────────────────────────

def test_benchmark_registry_tries_every_study_and_needs_the_marker(tmp_path):
    (tmp_path / "111_SDY1119").mkdir()
    (tmp_path / "111_SDY1119" / "assays_benchmark.json").write_text("{}")
    (tmp_path / "222_SDY2_pdf").mkdir()  # a PDF registry: never reused for an XML corpus
    (tmp_path / "222_SDY2_pdf" / "assays_benchmark.json").write_text("{}")
    (tmp_path / "333_SDY3").mkdir()  # unfinished: no marker
    assert immport_corpus.benchmark_registry("111", ["SDY80", "SDY1119"], tmp_path).name \
        == "111_SDY1119"
    assert immport_corpus.benchmark_registry("222", ["SDY2"], tmp_path) is None
    assert immport_corpus.benchmark_registry("333", ["SDY3"], tmp_path) is None


def test_done_marker_is_the_benchmark_file(tmp_path):
    assert immport_corpus.done_marker(tmp_path, "111", "SDY1") \
        == tmp_path / "111_SDY1" / "assays_benchmark.json"


def test_count_report_lines_uses_the_longest_prefix():
    text = "\n".join([
        "SDY1_111.xml [xml]: 'T'",
        "  WARNING  extraction 2 failed: boom",
        "  DROPPED ALIAS  ELISA: 'EIA' does not appear",
        "  REVIEW  not folded: flow cytometry (2)",
        "    JUDGED  DIFFERENT: readouts differ",
        "  OBI FAILED  ELISpot: timeout",
        "  VOTE  2 of 3: qPCR",
        "  MERGED  ELISA <- EIA",
        "  UNMAPPED  PRNT",
        "  nothing here",
    ])
    assert immport_corpus.count_report_lines(text) == {
        "WARNING": 1, "DROPPED": 1, "REVIEW": 1, "JUDGED": 1, "OBI FAILED": 1, "VOTE": 1,
        "MERGED": 1, "UNMAPPED": 1,
    }
    assert immport_corpus.format_flags({"VOTE": 1, "WARNING": 2}) == "WARNING=2;VOTE=1"
    assert immport_corpus.format_flags({}) == ""


def test_cost_per_paper_prefers_corpus_rows_then_any_then_default(tmp_path):
    corpus = tmp_path / "result"
    rows = [{"usd": 0.30, "registry_dir": str(corpus / "1_SDY1")},
            {"usd": 0.50, "registry_dir": str(corpus / "2_SDY2")},
            {"usd": 0.40, "registry_dir": str(corpus / "3_SDY3")},
            {"usd": 9.00, "registry_dir": "data/31paper_assays/x"},
            {"usd": None, "registry_dir": str(corpus / "4_SDY4")}]
    assert immport_corpus.cost_per_paper(rows, under=corpus) == {"median": 0.40, "max": 0.50, "n": 3}
    assert immport_corpus.cost_per_paper(rows[3:], under=corpus) == {"median": 9.0, "max": 9.0, "n": 1}
    assert immport_corpus.cost_per_paper([], under=corpus) == {"median": 0.40, "max": 0.40, "n": 0}


def test_seconds_and_summary_over_run_rows():
    rows = [{"status": "done", "seconds": "100", "flags": "REVIEW=2;VOTE=1"},
            {"status": "done", "seconds": "300", "flags": ""},
            {"status": "failed", "seconds": "5", "flags": ""},
            {"status": "reused", "seconds": "", "flags": "VOTE=1"}]
    assert immport_corpus.seconds_per_paper(rows) == 200
    assert immport_corpus.seconds_per_paper([]) == immport_corpus.DEFAULT_SECONDS_PER_PAPER
    assert immport_corpus.summarize_runs(rows) == {
        "by_status": {"done": 2, "failed": 1, "reused": 1},
        "flags": {"REVIEW": 2, "VOTE": 2},
    }


def test_permanent_reasons_are_not_transport_failures():
    assert is_permanent(immport_corpus.NO_PMC_REASON)
    assert is_permanent("PubMed Central has only the abstract, not the full text")
    assert not is_permanent("request failed: connection reset")
    assert not is_permanent("not attempted")
