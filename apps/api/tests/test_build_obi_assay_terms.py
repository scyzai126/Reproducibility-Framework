"""scripts/build_obi_assay_terms.py: the unpruned assay branch with its `is_a` edges."""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


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
def: "Has children." []
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


def test_is_a_is_kept_verbatim_including_a_parent_outside_the_branch(small):
    assert small["OBI:0000001"]["is_a"] == [{"id": "OBI:0000070", "label": "assay"}]
    assert small["OBI:0000003"]["is_a"] == [
        {"id": "OBI:0000001", "label": "family assay"},
        {"id": "OBI:9999999", "label": "outside the assay branch"},
    ]


def test_children_and_counts_say_whether_a_term_is_a_leaf(small):
    family = small["OBI:0000001"]
    assert family["children"] == [
        {"id": "OBI:0000002", "label": "child one"},
        {"id": "OBI:0000003", "label": "child two, also under another branch"},
    ]
    assert family["n_children"] == 2 and family["n_descendants"] == 2
    leaf = small["OBI:0000002"]
    assert leaf["children"] == [] and leaf["n_children"] == 0 and leaf["n_descendants"] == 0


def test_core_fields_match_the_pruned_index_shape(small):
    family = small["OBI:0000001"]
    assert family["label"] == "family assay"
    assert family["synonyms"] == ["family"]
    assert family["definition"] == "Has children."
    assert small["OBI:0000002"]["definition"] == ""  # no def: line


def test_committed_file_is_reproducible_from_obi_obo(mod):
    """The committed list must be exactly what re-running the script produces."""
    committed = json.loads(mod.OUTPUT_PATH.read_text(encoding="utf-8"))
    assert committed == mod.build_terms(mod.OBO_PATH)
    assert len(committed) == 1794


def test_committed_file_is_a_superset_of_the_pruned_index(mod):
    full = {t["id"] for t in json.loads(mod.OUTPUT_PATH.read_text(encoding="utf-8"))}
    pruned = json.loads((REPO_ROOT / "data" / "OBI" / "obi_generic_index.json").read_text(encoding="utf-8"))
    assert {t["id"] for t in pruned} <= full
