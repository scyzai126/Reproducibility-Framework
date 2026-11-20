"""paper_supplements: listing a paper's supplementary files, unpacking them, rendering text."""

import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

from app.agent import paper_supplements as ps
from app.agent.assay_extractor import has_methods_section
from app.agent.jats_parser import sentence_sections

XLINK = 'xmlns:xlink="http://www.w3.org/1999/xlink"'


def _article(body: str, pmc: str = "5583508") -> bytes:
    return (f'<article {XLINK}><front><article-meta>'
            f'<article-id pub-id-type="pmid">1</article-id>'
            f'<article-id pub-id-type="pmc">{pmc}</article-id>'
            f'</article-meta></front><body>{body}</body></article>').encode()


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


def test_pmcid_from_xml_reads_the_pmc_article_id():
    assert ps.pmcid_from_xml(_article("")) == "PMC5583508"
    assert ps.pmcid_from_xml(_article("", pmc="PMC42")) == "PMC42"
    assert ps.pmcid_from_xml(b"<article><front/></article>") is None


def test_listed_supplements_reads_wrapped_media():
    raw = _article(
        '<supplementary-material id="mmc1"><caption><p>Document S1. Supplemental '
        'Experimental Procedures</p></caption><media xlink:href="mmc1.pdf"/>'
        '</supplementary-material>')
    assert ps.listed_supplements(raw) == [
        {"href": "mmc1.pdf", "caption": "Document S1. Supplemental Experimental Procedures"}]


def test_listed_supplements_reads_bare_media_and_does_not_double_count():
    raw = _article(
        '<sec><title>Additional files</title>'
        '<media xlink:href="13073_MOESM1_ESM.pdf"><caption><p>Additional file 1</p></caption>'
        '</media></sec>'
        '<supplementary-material><media xlink:href="a.xlsx"/></supplementary-material>')
    assert [item["href"] for item in ps.listed_supplements(raw)] == [
        "13073_MOESM1_ESM.pdf", "a.xlsx"]


def test_listed_supplements_keeps_a_supplement_with_no_file():
    raw = _article('<supplementary-material><p>science.sciencemag.org/content/369/6508/1210/'
                   'suppl/DC1 Materials and Methods Figs. S1 to S21</p></supplementary-material>')
    listed = ps.listed_supplements(raw)
    assert len(listed) == 1
    assert listed[0]["href"] is None
    assert "Materials and Methods" in listed[0]["caption"]


def test_is_article_copy():
    assert ps.is_article_copy("Document S2. Article plus Supplemental Information")
    assert not ps.is_article_copy("Document S1. Supplemental Experimental Procedures")


def test_safe_extract_flattens_paths_and_skips_what_it_should(tmp_path):
    archive = _zip({
        "../../escape.pdf": b"x",
        "/abs/also.pdf": b"y",
        "folder/": b"",
        "folder/inner.docx": b"z",
        ".hidden": b"h",
        "also.pdf": b"second copy",
    })
    dest = tmp_path / "files"
    written = ps.safe_extract(archive, dest)
    assert sorted(path.name for path in written) == ["also.pdf", "escape.pdf", "inner.docx"]
    assert all(path.parent == dest for path in written)
    assert (dest / "also.pdf").read_bytes() == b"y"
    assert not (tmp_path / "escape.pdf").exists()


def test_safe_extract_skips_oversized_members(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "MAX_MEMBER_BYTES", 3)
    written = ps.safe_extract(_zip({"big.pdf": b"12345", "ok.pdf": b"12"}), tmp_path)
    assert [path.name for path in written] == ["ok.pdf"]


def test_safe_extract_does_not_write_an_empty_member(tmp_path):
    written = ps.safe_extract(_zip({"placeholder.gif": b"", "real.pdf": b"12"}), tmp_path)
    assert [path.name for path in written] == ["real.pdf"]
    assert not (tmp_path / "placeholder.gif").exists()


def test_safe_extract_replaces_an_empty_file_left_by_an_earlier_run(tmp_path):
    (tmp_path / "s1.pdf").write_bytes(b"")
    (tmp_path / "kept.pdf").write_bytes(b"first")
    written = ps.safe_extract(_zip({"s1.pdf": b"real", "kept.pdf": b"second"}), tmp_path)
    assert [path.name for path in written] == ["s1.pdf"]
    assert (tmp_path / "s1.pdf").read_bytes() == b"real"
    assert (tmp_path / "kept.pdf").read_bytes() == b"first"


class _Reply:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content, self.status_code = content, status_code


class _Session:
    def __init__(self, reply):
        self.reply = reply

    def get(self, url, **kwargs):
        return self.reply


@pytest.fixture(scope="module")
def script():
    path = Path(__file__).resolve().parents[3] / "scripts" / "download_paper_supplements.py"
    spec = importlib.util.spec_from_file_location("download_paper_supplements", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REQUEST_DELAY_S = 0
    return module


def test_download_of_an_archive_of_empty_files_is_a_failure(script, tmp_path):
    dest = tmp_path / "files"
    session = _Session(_Reply(_zip({"nihms540680f4.gif": b""})))
    status, _ = script.download(session, "PMC3946932", dest)
    assert status == "failed: empty archive"
    assert script.files_on_disk(dest) == []


def test_download_with_a_real_file_is_ok(script, tmp_path):
    session = _Session(_Reply(_zip({"mmc1.pdf": b"%PDF", "stub.gif": b""})))
    status, _ = script.download(session, "PMC5583508", tmp_path / "files")
    assert status == "ok"
    assert [p.name for p in script.files_on_disk(tmp_path / "files")] == ["mmc1.pdf"]


def test_an_empty_file_on_disk_does_not_count_as_downloaded(script, tmp_path):
    (tmp_path / "stub.gif").write_bytes(b"")
    (tmp_path / "s1.docx").write_bytes(b"x")
    assert [p.name for p in script.files_on_disk(tmp_path)] == ["s1.docx"]
    assert script.files_on_disk(tmp_path / "absent") == []


def test_docx_text_reads_paragraphs():
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = (f'<w:document xmlns:w="{ns}"><w:body>'
                f'<w:p><w:r><w:t>Supplementary Methods</w:t></w:r></w:p>'
                f'<w:p><w:r><w:t>PBMCs were </w:t></w:r><w:r><w:t>stained.</w:t></w:r></w:p>'
                f'</w:body></w:document>').encode()
    data = _zip({"word/document.xml": document})
    assert ps.docx_text(data) == "Supplementary Methods\nPBMCs were stained."
    assert ps.docx_text(b"not a zip") == ""


def test_methods_headings():
    for line in ("Supplementary Methods", "Supplemental Experimental Procedures",
                 "SUPPLEMENTARY MATERIALS AND METHODS", "Materials and Methods:",
                 "1. Methods", "Supplementary Note 1", "SI Materials and Methods"):
        assert ps.is_methods_heading(line), line
    for line in ("as described in Supplementary Methods.",
                 "Document S1. Supplemental Experimental Procedures, Figures S1-S6",
                 "Notes", "Text", "artifactual (see Methods) for each sample.",
                 "Supplementary Figure 1"):
        assert not ps.is_methods_heading(line), line


def test_split_blocks_separates_methods_from_legends():
    text = "\n".join([
        "Supplemental Information",
        "Some cover text.",
        "Supplemental Experimental Procedures",
        "Flow cytometry",
        "12",
        "PBMCs were stained with anti-",
        "bodies and acquired.",
        "Figure S1. Gating strategy.",
        "More legend.",
    ])
    blocks = ps.split_blocks(text)
    assert [block["bucket"] for block in blocks] == ["other", "methods", "other"]
    assert blocks[1]["heading"] == "Supplemental Experimental Procedures"
    assert blocks[1]["body"] == "Flow cytometry PBMCs were stained with antibodies and acquired."
    assert blocks[2]["body"].startswith("Figure S1. Gating strategy.")
    assert ps.methods_chars(blocks) == len(blocks[1]["body"])


def test_render_is_the_format_the_chain_reads_back():
    methods = "PBMCs were stained and acquired on a flow cytometer. " * 10
    files = [
        ("legends.pdf", "Figure S1. Gating strategy for NK cells."),
        ("mmc1.pdf", "Supplementary Methods\n" + methods + "\nFigure S2. Luminex panel."),
    ]
    rendered = ps.render(files)
    headings = [line for line in rendered.splitlines() if line.startswith("## ")]
    assert headings[0] == "## mmc1.pdf: Supplementary Methods  [methods]"
    assert all(line.endswith("[other]") for line in headings[1:])
    assert has_methods_section(rendered)
    buckets = set(sentence_sections(rendered).values())
    assert buckets == {"methods", "other"}


def test_render_cuts_other_blocks_before_methods():
    methods = "Serum IgG was measured by ELISA. " * 20
    files = [("a.pdf", "Figure S1. " + "x" * 5000),
             ("b.pdf", "Supplementary Methods\n" + methods)]
    rendered = ps.render(files, max_chars=len(methods) + 80)
    assert "[methods]" in rendered
    assert "ELISA" in rendered
    assert len(rendered.split("## ")) <= 3


def test_render_of_nothing_is_empty():
    assert ps.render([]) == ""
    assert ps.render([("a.pdf", "   \n  ")]) == ""
