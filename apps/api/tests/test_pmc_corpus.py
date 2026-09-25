"""The PMC topic-corpus downloader: what it keeps, what it rejects, and what it files it under.

No test here touches the network. What this script decides -- which articles survive the split,
which are rejected and why, what each file is named, what goes in the manifest -- does not depend
on what NCBI actually returns, so every test hands it a hand-built <pmc-articleset>.

The fixture articleset is deliberately awkward: it carries the three rejection cases (no body, no
PubMed ID, requested but not returned) alongside a good article, and the good article's
bibliography holds a *different* paper's PMID and title -- which is what a front-matter lookup
that forgot to scope itself to <article-meta> would return.
"""

import importlib.util
import json
from pathlib import Path

import pytest
from lxml import etree

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    """Import scripts/download_pmc_corpus.py, which is not an importable package."""
    path = _REPO_ROOT / "scripts" / "download_pmc_corpus.py"
    spec = importlib.util.spec_from_file_location("download_pmc_corpus", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


def _article(pmcid, *, pmid="36091148", body=True, title="A vaccine immunogenicity study"):
    """One <article>, with the knobs each rejection case turns."""
    pmid_tag = f'<article-id pub-id-type="pmid">{pmid}</article-id>' if pmid else ""
    body_xml = (
        '<body><sec><title>Methods</title><p>Sera were assayed by '
        '<ext-link xlink:href="http://example.org/kit">ELISA</ext-link>.</p></sec></body>'
        if body
        else ""
    )
    return f"""<article xml:lang="en" article-type="research-article">
  <front>
    <journal-meta>
      <journal-id journal-id-type="nlm-ta">Front Immunol</journal-id>
      <journal-title>Frontiers in Immunology</journal-title>
    </journal-meta>
    <article-meta>
      <article-id pub-id-type="pmcid">{pmcid}</article-id>
      <article-id pub-id-type="doi">10.3389/fimmu.2022.905036</article-id>
      {pmid_tag}
      <title-group><article-title>{title}</article-title></title-group>
      <pub-date pub-type="epub"><year>2022</year></pub-date>
      <permissions>
        <license><ali:license_ref xmlns:ali="http://www.niso.org/schemas/ali/1.0/"
          >https://creativecommons.org/licenses/by/4.0/</ali:license_ref></license>
      </permissions>
    </article-meta>
  </front>
  {body_xml}
  <back><ref-list><ref id="B1"><element-citation>
    <article-title>A completely unrelated cited paper</article-title>
    <pub-id pub-id-type="pmid">11111111</pub-id>
    <article-id pub-id-type="pmid">11111111</article-id>
  </element-citation></ref></ref-list></back>
</article>"""


def _articleset(*articles):
    return (
        '<?xml version="1.0"?><pmc-articleset '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'xmlns:mml="http://www.w3.org/1998/Math/MathML">'
        + "".join(articles)
        + "</pmc-articleset>"
    )


# --- splitting ------------------------------------------------------------------------------


def test_split_yields_one_standalone_document_per_article(script):
    parts = script.split_articleset(_articleset(_article("PMC1"), _article("PMC2")))
    assert len(parts) == 2
    for part in parts:
        root = etree.fromstring(part.encode("utf-8"))
        assert root.tag == "article"


def test_split_carries_namespace_declarations_onto_each_article(script):
    """xlink is declared on the articleset root; without it each article is unparseable."""
    part = script.split_articleset(_articleset(_article("PMC1")))[0]
    root = etree.fromstring(part.encode("utf-8"))
    assert root.find(".//ext-link").get("{http://www.w3.org/1999/xlink}href") == (
        "http://example.org/kit"
    )


def test_split_handles_a_bare_article_root(script):
    """Some responses are a single <article> with no articleset wrapper."""
    assert len(script.split_articleset(_article("PMC1"))) == 1


def test_split_of_an_empty_articleset_is_empty(script):
    assert script.split_articleset(_articleset()) == []


# --- metadata -------------------------------------------------------------------------------


def test_record_reads_front_matter_not_the_bibliography(script):
    """<article-id> and <article-title> occur again in every <ref>; a document-wide find would
    return the cited paper's identifiers for this one."""
    part = script.split_articleset(_articleset(_article("PMC9459166", pmid="36091148")))[0]
    record = script.article_record(part)
    assert record["pmcid"] == "PMC9459166"
    assert record["pmid"] == "36091148"  # not 11111111, the cited paper's
    assert record["title"] == "A vaccine immunogenicity study"
    assert record["journal"] == "Frontiers in Immunology"
    assert record["year"] == "2022"
    assert record["doi"] == "10.3389/fimmu.2022.905036"
    assert record["license"] == "https://creativecommons.org/licenses/by/4.0/"


def test_record_reports_a_missing_pubmed_id_as_none(script):
    part = script.split_articleset(_articleset(_article("PMC1", pmid=None)))[0]
    assert script.article_record(part)["pmid"] is None


# --- naming ---------------------------------------------------------------------------------


def test_output_name_holds_both_identifiers_pmcid_first(script):
    assert script.output_name("PMC9459166", "36091148") == "PMC9459166_36091148.xml"


def test_existing_pmcids_reads_what_is_already_downloaded(script, tmp_path):
    (tmp_path / "PMC9459166_36091148.xml").write_text("x")
    (tmp_path / "PMC8815383_35122211.xml").write_text("x")
    (tmp_path / "manifest.jsonl").write_text("")
    (tmp_path / "SDY2189_34252919.xml").write_text("x")  # the other corpus's scheme
    assert script.existing_pmcids(tmp_path) == {"PMC9459166", "PMC8815383"}


# --- the download loop ----------------------------------------------------------------------


@pytest.fixture
def run(script, monkeypatch, tmp_path):
    """Run main() over a fixed candidate list and a fixed articleset, and report what it did."""

    def _run(candidates, articleset, argv=(), out_dir=None):
        calls = []
        monkeypatch.setattr(script, "candidates", lambda session, query: iter(candidates))

        def _fetch(session, pmcids):
            calls.append(list(pmcids))
            return articleset

        monkeypatch.setattr(script, "fetch_batch", _fetch)
        out = out_dir or tmp_path
        monkeypatch.setattr(
            "sys.argv",
            ["download_pmc_corpus.py", "--out-dir", str(out), *argv],
        )
        assert script.main() == 0
        manifest = out / script.MANIFEST_NAME
        return {
            "files": sorted(p.name for p in out.glob("*.xml")),
            "manifest": [json.loads(line) for line in manifest.read_text().splitlines()],
            "fetched": calls,
        }

    return _run


def test_only_usable_full_text_is_written(script, run):
    """One good article, and the three ways a candidate fails."""
    articleset = _articleset(
        _article("PMC100", pmid="36091148"),
        _article("PMC200", body=False),  # abstract-only
        _article("PMC300", pmid=None),  # no PubMed ID
    )
    result = run(["PMC100", "PMC200", "PMC300", "PMC400"], articleset, ["--limit", "4"])
    assert result["files"] == ["PMC100_36091148.xml"]  # PMC400 was never returned at all
    assert len(result["manifest"]) == 1
    assert result["manifest"][0]["filename"] == "PMC100_36091148.xml"
    assert result["manifest"][0]["bytes"] > 0


def test_rejections_are_reported_with_their_reasons(script, run, capsys):
    articleset = _articleset(_article("PMC200", body=False), _article("PMC300", pmid=None))
    run(["PMC200", "PMC300", "PMC400"], articleset, ["--limit", "3"])
    out = capsys.readouterr().out
    assert "PubMed Central has only the abstract, not the full text" in out
    assert "no PubMed ID on record" in out
    assert "PubMed Central returned no article for it" in out
    assert "Downloaded 0" in out


def test_a_paper_already_on_disk_is_skipped_and_not_refetched(script, run, tmp_path):
    (tmp_path / "PMC100_36091148.xml").write_text("previously downloaded", encoding="utf-8")
    articleset = _articleset(_article("PMC100", pmid="36091148"))
    result = run(["PMC100"], articleset, ["--limit", "1"])
    assert result["fetched"] == []  # no request was made at all
    assert (tmp_path / "PMC100_36091148.xml").read_text() == "previously downloaded"


def test_force_refetches_and_rewrites_the_manifest(script, run, tmp_path):
    (tmp_path / "PMC100_36091148.xml").write_text("stale", encoding="utf-8")
    (tmp_path / "manifest.jsonl").write_text('{"filename": "stale.xml"}\n', encoding="utf-8")
    articleset = _articleset(_article("PMC100", pmid="36091148"))
    result = run(["PMC100"], articleset, ["--limit", "1", "--force"])
    assert result["fetched"] == [["PMC100"]]
    assert "stale" not in (tmp_path / "PMC100_36091148.xml").read_text()
    assert [r["filename"] for r in result["manifest"]] == ["PMC100_36091148.xml"]


def test_the_manifest_is_appended_to_on_a_resumed_run(script, run, tmp_path):
    (tmp_path / "PMC999_11111111.xml").write_text("earlier run", encoding="utf-8")
    (tmp_path / "manifest.jsonl").write_text('{"filename": "PMC999_11111111.xml"}\n')
    articleset = _articleset(_article("PMC100", pmid="36091148"))
    result = run(["PMC999", "PMC100"], articleset, ["--limit", "2"])
    assert [r["filename"] for r in result["manifest"]] == [
        "PMC999_11111111.xml",
        "PMC100_36091148.xml",
    ]


def test_the_limit_stops_the_run_mid_batch(script, run):
    articleset = _articleset(
        _article("PMC100", pmid="1"), _article("PMC200", pmid="2"), _article("PMC300", pmid="3")
    )
    result = run(["PMC100", "PMC200", "PMC300"], articleset, ["--limit", "2"])
    assert result["files"] == ["PMC100_1.xml", "PMC200_2.xml"]


def test_dry_run_writes_nothing(script, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(script, "search_count", lambda session, query: 36336)
    monkeypatch.setattr(
        "sys.argv",
        ["download_pmc_corpus.py", "--out-dir", str(tmp_path / "unmade"), "--dry-run"],
    )
    assert script.main() == 0
    assert "36,336 papers match" in capsys.readouterr().out
    assert not (tmp_path / "unmade").exists()


def test_exhausted_search_says_how_far_it_got(script, run, capsys):
    articleset = _articleset(_article("PMC100", pmid="1"))
    run(["PMC100"], articleset, ["--limit", "50"])
    assert "ran out of candidates at 1 of 50" in capsys.readouterr().out
