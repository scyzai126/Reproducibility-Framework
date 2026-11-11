"""scripts/download_abcd_papers.py: the sheet -> paper list, the file names, the PDF check."""

import importlib.util
import sys
from pathlib import Path

import fitz
import pytest

from app.agent import assay_service

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def mod():
    scripts = REPO_ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "download_abcd_papers", scripts / "download_abcd_papers.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts))
    return module


HEADER = ("From Lab Member*", "PMID*", "Paper Title*", "Data Type", "Study Name")


def test_cell_pmids_reads_every_shape(mod):
    assert mod.cell_pmids("37367734") == ["37367734"]
    assert mod.cell_pmids(37367734) == ["37367734"]
    assert mod.cell_pmids(37367734.0) == ["37367734"]
    assert mod.cell_pmids("[32747814, 34772824]") == ["32747814", "34772824"]
    assert mod.cell_pmids(None) == []
    assert mod.cell_pmids("see comment") == []


def test_cell_label_falls_back(mod):
    assert mod.cell_label("D12") == "D12"
    assert mod.cell_label(None) == "ABCD"
    assert mod.cell_label("  ") == "ABCD"
    assert mod.cell_label("D 1/2") == "ABCD"
    # An SDY-prefixed label would make split_stem read the stem the other way round.
    assert mod.cell_label("SDY12") == "ABCD"


def test_papers_from_rows_dedupes_and_keeps_sheet_order(mod):
    rows = [
        HEADER,
        ("Hailong", "37367734", "A flu paper", "scBCR", "D1"),
        (None, None, None, None, None),
        ("Gisela", "41928519", "No study name", "scBCR", None),
        ("Pramod", "34772824", "The SLE paper", "scBCR", "D28"),
        ("Pramod (secondary)", "[32747814, 34772824]", "Not either paper's", "scBCR", "D18"),
    ]
    papers = mod.papers_from_rows(rows)
    assert [p["pmid"] for p in papers] == ["37367734", "41928519", "34772824", "32747814"]
    by = {p["pmid"]: p for p in papers}
    assert by["37367734"]["primary_sdy"] == "D1"
    assert by["41928519"]["primary_sdy"] == "ABCD"
    assert by["34772824"]["primary_sdy"] == "D28"
    assert by["34772824"]["study_accessions"] == "D28;D18"
    assert by["34772824"]["n_studies"] == 2
    assert by["34772824"]["title"] == "The SLE paper"
    assert by["32747814"]["primary_sdy"] == "D18"
    assert by["32747814"]["title"] == ""


def test_a_real_study_name_beats_the_fallback(mod):
    rows = [HEADER, ("a", "37367734", "T", "x", None), ("b", "37367734", "T", "x", "D7")]
    (paper,) = mod.papers_from_rows(rows)
    assert paper["primary_sdy"] == "D7"
    assert paper["study_accessions"] == "D7"


def test_missing_column_is_an_error(mod):
    with pytest.raises(ValueError, match="study name"):
        mod.papers_from_rows([("PMID*", "Paper Title*")])


def test_names_are_found_by_the_pipeline(mod, tmp_path, monkeypatch):
    xml_dir, pdf_dir = tmp_path / "xml", tmp_path / "pdf"
    xml_dir.mkdir()
    pdf_dir.mkdir()
    (xml_dir / mod.xml_name("37367734", "D1")).write_text("<article/>")
    (pdf_dir / mod.pdf_name("35302862", "D2")).write_bytes(b"%PDF-1.4")
    (pdf_dir / "._D2_35302862.pdf").write_bytes(b"x")
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_dir)
    monkeypatch.setattr(assay_service, "PDF_ROOT", pdf_dir)

    assert assay_service.split_stem(Path(mod.xml_name("37367734", "D1")).stem) == ("37367734", "D1")
    assert assay_service.locate_paper_xml("37367734", "D1") == xml_dir / "37367734_D1.xml"
    assert assay_service.locate_paper_pdf("35302862", "D2") == pdf_dir / "D2_35302862.pdf"
    assert assay_service.locate_paper_source("35302862", "D2")[0] == "pdf"
    assert mod.existing_pdf(pdf_dir) == {"35302862": pdf_dir / "D2_35302862.pdf"}


def test_openalex_pdf_urls_best_first_without_repeats(mod):
    work = {
        "best_oa_location": {"pdf_url": "https://a/x.pdf", "is_oa": True},
        "locations": [
            {"pdf_url": "https://a/x.pdf", "is_oa": True},
            {"pdf_url": "https://closed/y.pdf", "is_oa": False},
            {"pdf_url": None, "is_oa": True},
            {"pdf_url": "https://b/z.pdf", "is_oa": True},
        ],
    }
    assert mod.openalex_pdf_urls(work) == ["https://a/x.pdf", "https://b/z.pdf"]
    assert mod.openalex_pdf_urls({"best_oa_location": None, "locations": None}) == []


def _pdf(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def test_pdf_problem(mod):
    title = "Clonal associations between lymphocyte subsets in rheumatoid arthritis"
    assert mod.pdf_problem(_pdf(title + "\nAbstract ..."), title) is None
    assert mod.pdf_problem(b"<html>Access denied</html>", title) == "the reply is not a PDF"
    assert "does not carry this paper's title" in mod.pdf_problem(
        _pdf("A completely unrelated article about soil"), title)
    assert mod.pdf_problem(_pdf(title), "") == "no title to check the PDF against"


def test_underscore_header_is_the_same_column(mod):
    rows = [("Study_name", "Project name", "PMID*", "Paper Title*"),
            ("D100 ", "oconnor_musk", "32573488", "A paper"),
            ("D109", "unpublished", None, None)]
    (paper,) = mod.papers_from_rows(rows)
    assert (paper["pmid"], paper["primary_sdy"]) == ("32573488", "D100")
