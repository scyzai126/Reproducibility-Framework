"""scripts/build_obi_assay_terms.py: the unpruned assay branch, in the index's format."""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
INDEX_PATH = REPO_ROOT / "data" / "OBI" / "obi_assay_noncompositional_index.json"


@pytest.fixture(scope="module")
def mod():
    script = REPO_ROOT / "scripts" / "build_obi_assay_terms.py"
    spec = importlib.util.spec_from_file_location("build_obi_assay_terms", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SMALL_OBO = """format-version: 1.2

[Term]
id: OBI:0000070
name: assay
def: "A planned process." []

[Term]
id: OBI:0000001
name: family assay
def: "Has children." [PMID:1]
synonym: "family" EXACT []
is_a: OBI:0000070 ! assay

[Term]
id: OBI:0000002
name: child one
is_a: OBI:0000001 ! family assay

[Term]
id: OBI:0000003
name: child two, also under another branch
is_a: OBI:0000001 ! family assay
is_a: OBI:9999999 ! outside the assay branch

[Term]
id: OBI:0000004
name: retired assay
is_obsolete: true

[Term]
id: OBI:9999999
name: outside the assay branch
is_a: OBI:0000000 ! root of something else
"""


@pytest.fixture
def small(mod, tmp_path):
    path = tmp_path / "small.obo"
    path.write_text(SMALL_OBO, encoding="utf-8")
    return {t["id"]: t for t in mod.build_terms(path)}


def test_branch_holds_only_assay_descendants(small):
    # root, obsolete and the foreign term are out; the three descendants are in, nothing else.
    assert set(small) == {"OBI:0000001", "OBI:0000002", "OBI:0000003"}


def test_entry_has_the_index_fields_with_parsed_values(small):
    assert small["OBI:0000001"] == {
        "id": "OBI:0000001",
        "label": "family assay",
        "synonyms": ["family"],
        "is_a": ["OBI:0000070"],
        "definition": "Has children.",
        "n_descendants": 2,
    }
    leaf = small["OBI:0000002"]
    assert leaf["synonyms"] == [] and leaf["definition"] == "" and leaf["n_descendants"] == 0


def test_is_a_keeps_every_parent_including_one_outside_the_branch(small):
    assert small["OBI:0000003"]["is_a"] == ["OBI:0000001", "OBI:9999999"]


def _skip_unless_built(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path.name} is gitignored; build it with scripts/build_obi_assay_terms.py")


def test_committed_file_is_reproducible_from_obi_obo(mod):
    """The list on disk must be exactly what re-running the script produces."""
    _skip_unless_built(mod.OUTPUT_PATH)
    committed = json.loads(mod.OUTPUT_PATH.read_text(encoding="utf-8"))
    assert committed == mod.build_terms(mod.OBO_PATH)
    assert len(committed) == 1794


def test_committed_file_has_the_same_shape_as_the_index_and_contains_it(mod):
    """Same keys in the same order, and every index entry appears unchanged in the full list."""
    _skip_unless_built(mod.OUTPUT_PATH)
    full = json.loads(mod.OUTPUT_PATH.read_text(encoding="utf-8"))
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    assert {tuple(t) for t in full} == {tuple(index[0])}
    by_id = {t["id"]: t for t in full}
    assert all(by_id[t["id"]] == t for t in index)
