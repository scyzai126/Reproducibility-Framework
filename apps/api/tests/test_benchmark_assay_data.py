"""The curated benchmark files have to be machine-readable, because nothing else checks them.

`scripts/compare_assay_benchmark.py` is the only consumer, it reads them with `json.loads`, and it
scores whichever files it can pair. A hand edit that leaves a trailing comma therefore does not
fail loudly -- before this test existed, three of the 31 files had been unparseable long enough
that the comparison report had never included them, and one was missing its closing brace.
"""

import json
from pathlib import Path

import pytest

BENCHMARK_DIR = Path(__file__).resolve().parents[3] / "data" / "benchmark_assay" / "benchmark_assay_v5"


def _benchmark_files() -> list[Path]:
    return sorted(BENCHMARK_DIR.glob("*.json"))


def test_the_benchmark_directory_is_where_it_is_expected():
    assert BENCHMARK_DIR.is_dir(), f"{BENCHMARK_DIR} is missing"
    assert _benchmark_files(), "no benchmark files found"


@pytest.mark.parametrize("path", _benchmark_files(), ids=lambda p: p.name)
def test_every_benchmark_file_parses_as_json(path: Path):
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        pytest.fail(f"{path.name} is not valid JSON: {exc}")
    assert isinstance(loaded, dict), f"{path.name} is a {type(loaded).__name__}, not an object"


@pytest.mark.parametrize("path", _benchmark_files(), ids=lambda p: p.name)
def test_every_benchmark_entry_names_the_assay_in_the_paper(path: Path):
    """`name_in_paper` is what the name and containment match tiers pair on, so an entry without
    one can only ever pair through its OBI id."""
    for key, entry in json.loads(path.read_text(encoding="utf-8")).items():
        assert isinstance(entry, dict), f"{path.name}: {key!r} is not an object"
        assert "name_in_paper" in entry, f"{path.name}: {key!r} has no name_in_paper"


@pytest.mark.parametrize("path", _benchmark_files(), ids=lambda p: p.name)
def test_every_benchmark_filename_starts_with_its_study_accession(path: Path):
    """discover_pairs reads the accession, and optionally a PMID, off the front of the name; the
    curator suffix that follows is free-form and is not read. A file it cannot parse a name from
    is skipped, which is how a paper silently leaves the report."""
    import importlib.util

    script = BENCHMARK_DIR.parents[2] / "scripts" / "compare_assay_benchmark.py"
    spec = importlib.util.spec_from_file_location("compare_assay_benchmark", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._BENCH_NAME.match(path.name), \
        f"{path.name} does not start with SDY<n>[_<pmid>]"


def test_the_comparison_can_be_pointed_at_another_result_version(tmp_path, monkeypatch):
    """--registry-dir scores a different result folder and writes its report beside it."""
    import importlib.util, json

    script = BENCHMARK_DIR.parents[2] / "scripts" / "compare_assay_benchmark.py"
    spec = importlib.util.spec_from_file_location("compare_assay_benchmark_v3", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    other = tmp_path / "assay_result_v3"
    (other / "32473127_SDY1640").mkdir(parents=True)
    (other / "32473127_SDY1640" / "assays_benchmark.json").write_text("{}", encoding="utf-8")

    module.use_registry_dir(other)
    pairs, skipped = module.discover_pairs("SDY1640")

    assert module.OUT_DIR == other.resolve() / "comparison"
    assert [p["registry"].name for p in pairs] == ["32473127_SDY1640"] if pairs and "registry" in pairs[0] \
        else len(pairs) == 1
    assert not any("SDY1640" in s for s in skipped)
