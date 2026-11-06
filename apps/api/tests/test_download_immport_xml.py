"""The ImmPort XML downloader: one folder, two lists that partition the corpus, nothing refetched.

No network. The idconv reply and the efetch articleset are hand-built, so what is under test is
what the script decides: which papers to copy rather than fetch, what each outcome is called,
that every PMID lands in exactly one list, and that a resumed run leaves finished papers alone.
"""

import importlib.util
from pathlib import Path

import pytest
import requests

from app.agent import assay_service, immport_corpus

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    path = _REPO_ROOT / "scripts" / "download_immport_xml.py"
    spec = importlib.util.spec_from_file_location("download_immport_xml", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


def _article(pmcid, *, pmid="111", body=True):
    pmid_tag = f'<article-id pub-id-type="pmid">{pmid}</article-id>' if pmid else ""
    body_xml = ('<body><sec><title>Methods</title><p>Sera were assayed by ELISA.</p></sec></body>'
                if body else "")
    return f"""<article xml:lang="en"><front><journal-meta>
      <journal-title>J</journal-title></journal-meta><article-meta>
      <article-id pub-id-type="pmcid">{pmcid}</article-id>{pmid_tag}
      <title-group><article-title>T {pmcid}</article-title></title-group>
      <pub-date><year>2020</year></pub-date></article-meta></front>{body_xml}</article>"""


def _articleset(*articles):
    return ('<?xml version="1.0"?><pmc-articleset xmlns:xlink="http://www.w3.org/1999/xlink">'
            + "".join(articles) + "</pmc-articleset>")


def _papers_all(papers_dir: Path, grouped: dict[str, list[str]]) -> None:
    immport_corpus.write_csv(papers_dir / immport_corpus.PAPERS_ALL_NAME,
                             immport_corpus.paper_rows(grouped), immport_corpus.PAPER_COLUMNS)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """A papers_all.csv of four papers and an empty curated corpus."""
    papers_dir = tmp_path / "HIPC papers"
    papers_dir.mkdir()
    _papers_all(papers_dir, {"111": ["SDY1"], "222": ["SDY2"], "333": ["SDY3"],
                             "444": ["SDY4", "SDY40"]})
    curated = tmp_path / "JAT_XML"
    curated.mkdir()
    monkeypatch.setattr(assay_service, "XML_ROOT", curated)
    return papers_dir, curated


@pytest.fixture
def run(script, monkeypatch):
    """Run main() against a canned idconv reply and articleset; report calls and outcomes."""

    def _run(papers_dir, *, idconv=None, articleset="", argv=(), idconv_error=None,
             fetch_error=None):
        calls = {"idconv": [], "fetch": []}

        class _Reply:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        class _Session:
            def get(self, url, params=None, timeout=None):
                ids = params["ids"].split(",")
                calls["idconv"].append(ids)
                if idconv_error:
                    raise idconv_error
                return _Reply({"records": [
                    {"pmid": pmid, **({"pmcid": idconv[pmid]} if idconv.get(pmid) else
                                      {"status": "error"})}
                    for pmid in ids]})

        monkeypatch.setattr(script.requests, "Session", _Session)

        def _fetch(session, pmcids):
            calls["fetch"].append(list(pmcids))
            if fetch_error:
                raise fetch_error
            return articleset

        monkeypatch.setattr(script, "fetch_batch", _fetch)
        monkeypatch.setattr(script, "request_delay", lambda: 0)
        monkeypatch.setattr("sys.argv",
                            ["download_immport_xml.py", "--papers-dir", str(papers_dir), *argv])
        assert script.main() == 0
        xml_dir = papers_dir / immport_corpus.XML_DIR_NAME
        return {
            "files": sorted(p.name for p in xml_dir.glob("*.xml")) if xml_dir.exists() else [],
            "xml": {r["pmid"]: r for r in
                    immport_corpus.read_csv(papers_dir / immport_corpus.PAPERS_XML_NAME)},
            "no_xml": {r["pmid"]: r for r in
                       immport_corpus.read_csv(papers_dir / immport_corpus.PAPERS_NO_XML_NAME)},
            "calls": calls,
        }

    return _run


# ── the deliverable ───────────────────────────────────────────────────────────

def test_every_paper_lands_in_exactly_one_list_with_its_reason(corpus, run):
    papers_dir, _ = corpus
    result = run(papers_dir,
                 idconv={"111": "PMC1", "222": "PMC2", "333": None, "444": "PMC4"},
                 articleset=_articleset(_article("PMC1", pmid="111"),
                                        _article("PMC2", pmid="222", body=False)))
    assert result["files"] == ["SDY1_111.xml"]
    assert set(result["xml"]) == {"111"}
    assert result["xml"]["111"]["pmcid"] == "PMC1"
    assert result["xml"]["111"]["file"] == "SDY1_111.xml"
    assert int(result["xml"]["111"]["bytes"]) > 0
    assert set(result["no_xml"]) == {"222", "333", "444"}
    assert "only the abstract" in result["no_xml"]["222"]["reason"]
    assert result["no_xml"]["333"]["reason"] == immport_corpus.NO_PMC_REASON
    assert result["no_xml"]["444"]["reason"] == "PubMed Central returned no article for it"
    assert result["no_xml"]["444"]["study_accessions"] == "SDY4;SDY40"
    # 333 has no PMC id, so it was never part of an efetch batch
    assert result["calls"]["fetch"] == [["PMC1", "PMC2", "PMC4"]]


def test_a_mismatched_pmid_is_never_filed(corpus, run):
    papers_dir, _ = corpus
    result = run(papers_dir, idconv={"111": "PMC1", "222": None, "333": None, "444": None},
                 articleset=_articleset(_article("PMC1", pmid="999")))
    assert result["files"] == []
    assert "mismatch" in result["no_xml"]["111"]["reason"]


# ── the curated corpus ────────────────────────────────────────────────────────

def test_a_benchmark_paper_is_copied_not_fetched(corpus, run, capsys):
    papers_dir, curated = corpus
    (curated / "SDY40_444.xml").write_text("<article>curated</article>")  # filed under SDY40
    result = run(papers_dir, idconv={"111": None, "222": None, "333": None},
                 articleset=_articleset())
    assert "SDY4_444.xml" in result["files"]  # named after the primary study
    assert (papers_dir / "xml" / "SDY4_444.xml").read_text() == "<article>curated</article>"
    assert all("444" not in chunk for chunk in result["calls"]["idconv"])
    assert "COPY  444" in capsys.readouterr().out


# ── resuming ──────────────────────────────────────────────────────────────────

def test_a_paper_already_in_the_folder_is_skipped(corpus, run):
    papers_dir, _ = corpus
    xml_dir = papers_dir / "xml"
    xml_dir.mkdir()
    (xml_dir / "SDY1_111.xml").write_text("<article/>")
    result = run(papers_dir, idconv={"222": None, "333": None, "444": None},
                 articleset=_articleset())
    assert all("111" not in chunk for chunk in result["calls"]["idconv"])
    assert "111" in result["xml"]
    assert "111" not in result["no_xml"]


def test_a_settled_failure_is_not_asked_again_unless_told(corpus, run):
    papers_dir, _ = corpus
    immport_corpus.write_csv(
        papers_dir / immport_corpus.PAPERS_NO_XML_NAME,
        [{"pmid": "333", "study_accessions": "SDY3", "primary_sdy": "SDY3", "pmcid": "",
          "reason": immport_corpus.NO_PMC_REASON},
         {"pmid": "444", "study_accessions": "SDY4;SDY40", "primary_sdy": "SDY4", "pmcid": "",
          "reason": "request failed: connection reset"}],
        immport_corpus.NO_XML_COLUMNS)
    result = run(papers_dir, idconv={"111": None, "222": None, "444": None},
                 articleset=_articleset())
    asked = {pmid for chunk in result["calls"]["idconv"] for pmid in chunk}
    assert asked == {"111", "222", "444"}  # 333 settled; 444's transport failure retried
    assert result["no_xml"]["333"]["reason"] == immport_corpus.NO_PMC_REASON

    result = run(papers_dir, idconv={"111": None, "222": None, "333": None, "444": None},
                 articleset=_articleset(), argv=["--retry-failed"])
    asked = {pmid for chunk in result["calls"]["idconv"] for pmid in chunk}
    assert "333" in asked


def test_limit_fetches_only_the_first_papers(corpus, run):
    papers_dir, _ = corpus
    result = run(papers_dir, idconv={"111": "PMC1", "222": "PMC2", "333": "PMC3", "444": "PMC4"},
                 articleset=_articleset(_article("PMC1", pmid="111")), argv=["--limit", "1"])
    assert result["calls"]["idconv"] == [["111"]]
    assert result["files"] == ["SDY1_111.xml"]
    assert result["no_xml"]["222"]["reason"] == "not attempted"


# ── failure handling ──────────────────────────────────────────────────────────

def test_a_failed_batch_is_recorded_and_the_run_finishes(corpus, run):
    papers_dir, _ = corpus
    result = run(papers_dir, idconv={"111": "PMC1", "222": "PMC2", "333": None, "444": None},
                 fetch_error=requests.ConnectionError("reset"))
    assert result["files"] == []
    assert result["no_xml"]["111"]["reason"].startswith("request failed")
    assert result["no_xml"]["111"]["pmcid"] == "PMC1"
    assert result["no_xml"]["333"]["reason"] == immport_corpus.NO_PMC_REASON


def test_an_idconv_failure_is_recorded_as_transport(corpus, run):
    papers_dir, _ = corpus
    result = run(papers_dir, idconv={}, idconv_error=requests.ConnectionError("down"))
    assert result["calls"]["fetch"] == []
    assert all(r["reason"].startswith("request failed") for r in result["no_xml"].values())


# ── dry run ───────────────────────────────────────────────────────────────────

def test_dry_run_writes_nothing_and_calls_nothing(corpus, run, capsys):
    papers_dir, curated = corpus
    (curated / "SDY1_111.xml").write_text("<article/>")
    result = run(papers_dir, idconv={}, argv=["--dry-run"])
    assert result["files"] == []
    assert result["calls"] == {"idconv": [], "fetch": []}
    assert not (papers_dir / immport_corpus.PAPERS_XML_NAME).exists()
    out = capsys.readouterr().out
    assert "copy from data/JAT_XML : 1" in out
    assert "fetch from PMC         : up to 3" in out
    assert "nothing called" in out


def test_missing_list_is_a_clear_exit(script, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["download_immport_xml.py", "--papers-dir", str(tmp_path)])
    assert script.main() == 1
    assert "build_immport_paper_list.py" in capsys.readouterr().err
