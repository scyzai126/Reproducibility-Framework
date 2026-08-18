"""The assay batch run must land in all_assays.json's exact table shape.

Four things can silently corrupt that table, and none of them involve the model:
the study key is reversed relative to the filename (<SDY>_<pmid>.xml keys as
<pmid>_<SDY>), a paper supplied as both XML and PDF must be extracted once rather
than twice, the flattener has to pick five fields out of a seven-field registry, and
normalization must leave a name alone when no vocabulary term fits rather than
snapping it onto a nearby technique. These cover that logic without any network.
"""

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_runner():
    """Import scripts/extract_assays.py, which is not an importable package."""
    path = _REPO_ROOT / "scripts" / "extract_assays.py"
    spec = importlib.util.spec_from_file_location("extract_assays", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def test_study_key_reverses_the_filename(runner, tmp_path):
    for name in ("SDY212_25834109.xml", "SDY1364_23844129.xml"):
        (tmp_path / name).write_text("<article/>", encoding="utf-8")

    papers = runner._load_papers(tmp_path, [])

    assert [p.study for p in papers] == ["23844129_SDY1364", "25834109_SDY212"]
    assert {p.source for p in papers} == {"xml"}


def test_load_papers_skips_filenames_without_a_pmid(runner, tmp_path):
    (tmp_path / "SDY212_25834109.xml").write_text("<article/>", encoding="utf-8")
    (tmp_path / "orphan.xml").write_text("<article/>", encoding="utf-8")

    assert [p.study for p in runner._load_papers(tmp_path, [])] == ["25834109_SDY212"]


def test_pdfs_fill_the_gap_and_defer_to_xml_for_the_same_study(runner, tmp_path):
    """A study with both formats must be extracted once — from its XML — not twice."""
    xml_dir = tmp_path / "xml"
    pdf_dir = tmp_path / "pdf"
    xml_dir.mkdir()
    pdf_dir.mkdir()
    (xml_dir / "SDY212_25834109.xml").write_text("<article/>", encoding="utf-8")
    (pdf_dir / "SDY212_25834109.pdf").write_bytes(b"%PDF-")
    (pdf_dir / "SDY404_25367297.pdf").write_bytes(b"%PDF-")

    papers = runner._load_papers(xml_dir, [pdf_dir])

    assert [(p.study, p.source) for p in papers] == [
        ("25367297_SDY404", "pdf"),
        ("25834109_SDY212", "xml"),
    ]


def test_pdf_source_accepts_bare_files_and_ignores_other_suffixes(runner, tmp_path):
    pdf = tmp_path / "SDY404_25367297.pdf"
    pdf.write_bytes(b"%PDF-")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    papers = runner._load_papers(None, [pdf, tmp_path / "notes.txt"])

    assert [(p.study, p.source) for p in papers] == [("25367297_SDY404", "pdf")]


def test_flatten_keeps_exactly_the_all_assays_fields(runner):
    registries = {
        "25834109_SDY212": {
            "flow cytometry": {
                "name_in_paper": "flow cytometry",
                "aliases": ["FACS"],
                "sample_type": "PBMCs",
                "readouts": "cell frequencies",
                "evidence_location": {"type": "figure", "ref": "Figure 1"},
                "confidence": 0.95,
                "claim_role": "primary",
            }
        }
    }

    rows = runner._flatten(registries, {"flow cytometry": "Flow Cytometry"})

    assert rows == [
        {
            "study": "25834109_SDY212",
            "assay": "flow cytometry",
            "normalized_name": "Flow Cytometry",
            "sample_type": "PBMCs",
            "readouts": "cell frequencies",
        }
    ]


def test_flatten_sorts_by_study_then_assay(runner):
    registries = {
        "25834109_SDY212": {"qPCR": {"name_in_paper": "qPCR"}},
        "23844129_SDY1364": {
            "western blot": {"name_in_paper": "western blot"},
            "ELISA": {"name_in_paper": "ELISA"},
        },
    }

    rows = runner._flatten(registries, {})

    assert [(r["study"], r["assay"]) for r in rows] == [
        ("23844129_SDY1364", "ELISA"),
        ("23844129_SDY1364", "western blot"),
        ("25834109_SDY212", "qPCR"),
    ]


def test_flatten_falls_back_to_the_registry_key_and_empty_fields(runner):
    rows = runner._flatten({"25834109_SDY212": {"ELISpot": {}}}, {})

    assert rows == [
        {
            "study": "25834109_SDY212",
            "assay": "ELISpot",
            "normalized_name": "ELISpot",
            "sample_type": "",
            "readouts": "",
        }
    ]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Flow Cytometry", "Flow Cytometry"),
        ("flow cytometry", "Flow Cytometry"),
        ("  FLOW CYTOMETRY  ", "Flow Cytometry"),
        ("mass cytometry", None),
    ],
)
def test_match_vocabulary_resolves_only_exact_and_case_variants(runner, name, expected):
    assert runner._match_vocabulary(name, ["Flow Cytometry", "ELISA"]) == expected


@pytest.mark.asyncio
async def test_normalize_skips_the_model_when_every_name_matches_locally(runner):
    class ExplodingClient:
        def __getattr__(self, _):
            raise AssertionError("no LLM call should be made when all names match")

    mapping = await runner._normalize_names(
        ["ELISA", "flow cytometry"], ["ELISA", "Flow Cytometry"], ExplodingClient()
    )

    assert mapping == {"ELISA": "ELISA", "flow cytometry": "Flow Cytometry"}


def test_case_variants_of_an_unmapped_name_collapse_to_the_common_spelling(runner):
    mapping = runner._collapse_case_variants(
        {
            "a": "Multiplex Cytokine Analysis",
            "b": "multiplex cytokine analysis",
            "c": "Multiplex Cytokine Analysis",
            "d": "Flow Cytometry",
        }
    )

    assert mapping == {
        "a": "Multiplex Cytokine Analysis",
        "b": "Multiplex Cytokine Analysis",
        "c": "Multiplex Cytokine Analysis",
        "d": "Flow Cytometry",
    }


def test_collapse_is_stable_when_no_spelling_is_more_common(runner):
    mapping = runner._collapse_case_variants({"a": "western blot", "b": "Western Blot"})

    assert set(mapping.values()) == {"Western Blot"}
