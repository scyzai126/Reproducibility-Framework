"""The corpus table the /assays Corpus tab renders is one row per final assay, in the route's schema.

scripts/build_assay_table.py flattens every registry's assays_OBI.json. The rows must keep the
exact fields `GET /agent/assay-obi` serves and `AssayObiRow` renders, and `study` must stay the
`<pmid>_<SDY>` spelling assay_immport.study_accession_of parses -- a `_pdf` registry included.
Each row carries the curator's matching assay, paired by compare_assay_benchmark.py, and a curator
assay nothing of ours matches becomes a `benchmark_only` row.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The fields of AssayObiRow in apps/web/src/lib/types.ts.
_ROW_FIELDS = {"study", "assay", "normalized_name", "sample_type", "readouts",
               "obi_id", "obi_label", "resource", "obi_confidence",
               "benchmark_assay", "benchmark_obi_label", "benchmark_obi_id", "benchmark_items",
               "paper_url", "paper_source"}


@pytest.fixture
def builder(tmp_path, monkeypatch):
    """Import scripts/build_assay_table.py, which is not an importable package.

    XML_ROOT points at an empty tmp dir so paper links never depend on the real corpus."""
    from app.agent import assay_service

    monkeypatch.setattr(assay_service, "XML_ROOT", tmp_path / "JAT_XML")
    path = _REPO_ROOT / "scripts" / "build_assay_table.py"
    spec = importlib.util.spec_from_file_location("build_assay_table", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, stem: str, entries: dict) -> None:
    (root / stem).mkdir(parents=True)
    (root / stem / "assays_OBI.json").write_text(json.dumps(entries), encoding="utf-8")


@pytest.fixture
def registries(tmp_path):
    _write(tmp_path, "24336226_SDY1260", {
        "enzyme-linked immunosorbent assay": {
            "name_in_paper": ["ELISA", "ELISA kits"], "normalized_name": "ELISA",
            "sample_type": "serum", "readouts": "IgG titers",
            "obi_id": "OBI:0000661", "obi_label": "enzyme-linked immunosorbent assay",
            "resource": "exact_original", "obi_confidence": "high",
            "evidence": {"quote": "not carried into the table"},
        },
        "lateral flow assay": {
            "name_in_paper": ["lateral flow assay"], "normalized_name": "lateral flow",
            "sample_type": "whole blood", "readouts": "antibody presence",
            "obi_id": None, "obi_label": None, "obi_confidence": None,
        },
    })
    _write(tmp_path, "20078211_SDY1293_pdf", {
        "microarray assay": {
            "name_in_paper": "GeneChip analysis", "normalized_name": "microarray",
            "sample_type": "PBMCs", "readouts": "gene expression",
            "obi_id": "OBI:0001985", "obi_label": "microarray assay",
            "resource": "exact_normalized_llm", "obi_confidence": "high",
        },
    })
    (tmp_path / "all_assays_OBI.json").write_text("[]", encoding="utf-8")  # a prior table is not a registry
    return tmp_path


@pytest.fixture
def rows(builder, registries, tmp_path):
    """The table with no benchmark files at all."""
    return builder.table_rows(registries, tmp_path / "no_benchmarks")


def test_one_row_per_final_assay_in_the_route_schema(rows):
    assert len(rows) == 3
    assert all(set(row) == _ROW_FIELDS for row in rows)


def test_a_pdf_registry_is_listed_under_its_pmid_and_sdy(rows):
    assert [row["study"] for row in rows] == ["20078211_SDY1293", "24336226_SDY1260", "24336226_SDY1260"]


def test_every_wording_a_merged_entry_kept_is_shown(rows):
    elisa = next(r for r in rows if r["obi_id"] == "OBI:0000661")

    assert elisa["assay"] == "ELISA / ELISA kits"


def test_a_string_name_from_before_round_5_is_taken_as_is(rows):
    array = next(r for r in rows if r["obi_id"] == "OBI:0001985")

    assert array["assay"] == "GeneChip analysis"


def test_an_unmapped_assay_reads_as_unresolved(rows):
    lateral = next(r for r in rows if r["assay"] == "lateral flow assay")

    assert lateral["obi_id"] is None
    assert lateral["resource"] == "unresolved"


def test_without_a_benchmark_the_curator_fields_are_null(rows):
    assert all(row[f] is None for row in rows
               for f in ("benchmark_assay", "benchmark_obi_label", "benchmark_obi_id"))
    assert all(row["benchmark_items"] == [] for row in rows)


# ── the curator's columns ─────────────────────────────────────────────────────


def _curated(name, obi_id, label, quote=""):
    return {"name_in_paper": name, "aliases": [],
            "OBI ontology": {"obi_id": obi_id, "obi_label": label},
            "evidence_location": {"quote": quote}}


@pytest.fixture
def with_benchmark(builder, registries, tmp_path):
    """A curator file for SDY1260: two ELISAs (both pair with our one ELISA entry), and SIMOA,
    which nothing of ours matches. compare_assay_benchmark.py reads assays_benchmark.json."""
    registry = registries / "24336226_SDY1260"
    obi = json.loads((registry / "assays_OBI.json").read_text(encoding="utf-8"))
    (registry / "assays_benchmark.json").write_text(json.dumps(obi), encoding="utf-8")
    bench_dir = tmp_path / "benchmark_assay"
    bench_dir.mkdir()
    (bench_dir / "SDY1260_Assay_Test.json").write_text(json.dumps({
        "ELISA": _curated("ELISA", "OBI:0000661", "enzyme-linked immunosorbent assay"),
        "IgG ELISA": _curated("IgG ELISA", "OBI:0000661", "enzyme-linked immunosorbent assay"),
        "SIMOA": _curated("single-molecule array", None, None),
    }), encoding="utf-8")
    return builder.table_rows(registries, bench_dir)


def test_a_paired_row_carries_the_curator_name_label_and_id(with_benchmark):
    elisa = next(r for r in with_benchmark if r["obi_id"] == "OBI:0000661")

    assert elisa["benchmark_assay"] == "ELISA / IgG ELISA"
    assert elisa["benchmark_obi_label"] == ("enzyme-linked immunosorbent assay / "
                                            "enzyme-linked immunosorbent assay")
    assert elisa["benchmark_obi_id"] == "OBI:0000661 / OBI:0000661"


def test_an_assay_no_curator_lists_has_null_curator_fields(with_benchmark):
    lateral = next(r for r in with_benchmark if r["assay"] == "lateral flow assay")

    assert lateral["benchmark_assay"] is None


def test_a_curator_assay_we_missed_becomes_a_benchmark_only_row(with_benchmark):
    missed = [r for r in with_benchmark if r.get("benchmark_only")]

    assert len(missed) == 1
    assert missed[0]["study"] == "24336226_SDY1260"
    assert missed[0]["benchmark_assay"] == "single-molecule array"
    assert missed[0]["assay"] == "" and missed[0]["obi_id"] is None and missed[0]["resource"] is None
    assert [i["obi_match"] for i in missed[0]["benchmark_items"]] == ["missed"]


def test_each_curator_assay_says_how_our_obi_term_compares(with_benchmark):
    """The result cards count from `benchmark_items`: one per curator assay, keyed within the paper."""
    elisa = next(r for r in with_benchmark if r["obi_id"] == "OBI:0000661")

    assert [(i["key"], i["obi_match"]) for i in elisa["benchmark_items"]] == [
        ("ELISA", "same"), ("IgG ELISA", "same")]


@pytest.mark.parametrize("status, bench_id, ours_id, expected", [
    ("MATCH", "OBI:1", "OBI:1", "same"),
    ("MATCH_GRANULARITY", "OBI:1", "OBI:2", "related"),
    ("SPLIT", "OBI:1", "OBI:2", "related"),
    ("SPLIT", "OBI:1", "OBI:1", "same"),
    ("MATCH_OBI_CONFLICT", "OBI:1", "OBI:2", "differs"),
    ("MATCH_OBI_UNMAPPED", "OBI:1", None, "ours_unmapped"),
    ("MATCH_OBI_UNMAPPED", None, "OBI:2", "curator_unmapped"),
    ("MATCH_OBI_UNMAPPED", None, None, "ours_unmapped"),
    ("MISSED", "OBI:1", None, "missed"),
])
def test_obi_match_categories(builder, status, bench_id, ours_id, expected):
    assert builder._obi_match(status, bench_id, ours_id) == expected


# ── the paper link ────────────────────────────────────────────────────────────


def test_a_paper_with_jats_xml_links_to_its_own_pmc_page(builder, registries, tmp_path):
    """The reference list names cited papers' PMCIDs too; only <article-meta> is the paper's."""
    xml_root = tmp_path / "JAT_XML"
    xml_root.mkdir()
    (xml_root / "SDY1260_24336226.xml").write_text(
        '<article><front><article-meta><article-id pub-id-type="pmid">24336226</article-id>'
        '<article-id pub-id-type="pmc">PMC3946932</article-id></article-meta></front>'
        '<back><ref-list><ref><pub-id pub-id-type="pmcid">PMC1111111</pub-id>'
        '<article-id pub-id-type="pmc">PMC2222222</article-id></ref></ref-list></back></article>',
        encoding="utf-8")

    rows = builder.table_rows(registries, tmp_path / "no_benchmarks")
    sdy1260 = {(r["paper_url"], r["paper_source"]) for r in rows if r["study"] == "24336226_SDY1260"}

    assert sdy1260 == {("https://pmc.ncbi.nlm.nih.gov/articles/PMC3946932/", "PMC")}


def test_a_paper_without_jats_xml_links_to_pubmed(rows):
    pdf_only = {(r["paper_url"], r["paper_source"]) for r in rows if r["study"] == "20078211_SDY1293"}

    assert pdf_only == {("https://pubmed.ncbi.nlm.nih.gov/20078211/", "PubMed")}
