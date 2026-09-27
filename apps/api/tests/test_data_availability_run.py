"""data_availability_service for one paper: what the Extract tab's run depends on.

The estimate it prices a run with (one call when the paper names an accession, none otherwise),
the stored record it reads back for free, and a clear refusal when there is no paper to read.
No test here makes a network or model call.
"""

import asyncio
import json

import pytest

from app.agent import assay_service, data_availability_service as das

_WITH_ACCESSION = """<article><front><article-meta><article-title>A Paper</article-title>
<article-id pub-id-type="pmid">111</article-id></article-meta></front><body>
<sec><title>Data availability</title><p>Microarray data are deposited in GEO under accession
GSE12345.</p></sec></body></article>"""

_WITHOUT = """<article><front><article-meta><article-title>A Paper</article-title>
<article-id pub-id-type="pmid">222</article-id></article-meta></front><body>
<sec><title>Methods</title><p>Cells were analyzed by flow cytometry.</p></sec></body></article>"""


@pytest.fixture
def papers(tmp_path, monkeypatch):
    xml_root = tmp_path / "JAT_XML"
    xml_root.mkdir()
    (xml_root / "SDY1_111.xml").write_text(_WITH_ACCESSION, encoding="utf-8")
    (xml_root / "SDY2_222.xml").write_text(_WITHOUT, encoding="utf-8")
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    monkeypatch.setattr(assay_service, "PDF_ROOT", tmp_path / "no_pdfs")
    monkeypatch.setattr(das, "OUT_DIR", tmp_path / "data_availability")
    # 111 is a benchmark paper (its folder exists), so its files go to OUT_DIR; any other
    # paper would keep them beside its registry in the cache.
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", tmp_path / "registries")
    (tmp_path / "registries" / "111_SDY1").mkdir(parents=True)
    return tmp_path


def test_files_are_named_sdy_then_pmid():
    assert das.stem_for("111", "SDY1") == "SDY1_111"


def test_a_paper_naming_an_accession_costs_one_call(papers):
    round_ = das.estimate("111", "SDY1")

    assert (round_["name"], round_["calls"], round_["exact"]) == ("data_availability", 1, True)
    assert round_["entries"] >= 1


def test_a_paper_naming_no_accession_costs_nothing(papers):
    assert das.estimate("222", "SDY2")["calls"] == 0


def test_a_paper_with_no_file_is_priced_at_zero_rather_than_failing_the_estimate(papers):
    """The assay estimate already reports a missing paper; the data step must not add a 500."""
    assert das.estimate("999", "SDY9")["calls"] == 0


def test_the_stored_record_is_read_back_or_none(papers):
    das.OUT_DIR.mkdir()
    (das.OUT_DIR / "SDY1_111.json").write_text(
        json.dumps({"data_repositories": [{"accession": "GSE1"}]}), encoding="utf-8")

    assert das.stored("111", "SDY1") == {"data_repositories": [{"accession": "GSE1"}]}
    assert das.stored("222", "SDY2") is None


def test_an_unreadable_stored_record_reads_as_none(papers):
    das.OUT_DIR.mkdir()
    (das.OUT_DIR / "SDY1_111.json").write_text("{not json", encoding="utf-8")

    assert das.stored("111", "SDY1") is None


def test_running_a_paper_that_is_not_on_disk_is_refused(papers):
    with pytest.raises(assay_service.PaperNotFoundError):
        asyncio.run(das.run_for_paper("999", "SDY9", client=None))


def test_an_old_single_file_record_reads_as_never_run(papers):
    """Written before the two-file split: it has roles but no `data_repositories`."""
    das.OUT_DIR.mkdir()
    (das.OUT_DIR / "SDY1_111.json").write_text(json.dumps({"pmid": "111", "deposited": []}),
                                               encoding="utf-8")

    assert das.stored("111", "SDY1") is None
