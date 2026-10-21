"""Round 5 on its own, over a registry on disk: free by default, judged on request.

The plain path is what backfills a registry built before round 5 existed, and it must stay free
-- it reads the term off disk and folds, constructing no client. `--judge` is the opt-in that
makes the pipeline's one call per candidate group, and what it must prove is that the judge's
split reaches the files: a registry canonicalized by this script and one canonicalized by the
pipeline are the same files.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from app.agent import claim_parser
from app.agent.assay_extractor import KEY_SEP

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PHENO = {
    "name_in_paper": "Flow cytometry analysis and cell sorting", "standard_technique_name":
    "flow cytometry", "aliases": [], "sample_type": None,
    "readouts": "cell surface marker expression", "generate_claim": True, "source": "methods",
    "evidence": {"section": "Flow cytometry", "sentence_ids": ["S1"], "quote": "Cells were stained."},
}
_STIM = {
    **_PHENO, "name_in_paper": "In vitro cytokine stimulation and functional assays of NK cells",
    "sample_type": "PBMCs", "readouts": "intracellular IFN-γ after stimulation",
    "evidence": {"section": "Stimulation", "sentence_ids": ["S2"], "quote": "PBMCs were stimulated."},
}
_TERM = {"obi_id": "OBI:0000916", "obi_label": "flow cytometry assay", "resource": "exact_original"}
_STIM_KEY = "flow cytometry assay" + KEY_SEP + _STIM["name_in_paper"]


@pytest.fixture(scope="module")
def script():
    path = _REPO_ROOT / "scripts" / "run_assay_merge.py"
    spec = importlib.util.spec_from_file_location("run_assay_merge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def registry(tmp_path):
    """A pre-canonical two-entry registry on disk, both entries on one term."""
    folder = tmp_path / "111_SDY1"
    folder.mkdir()
    (folder / "assays.json").write_text(json.dumps({"pheno": _PHENO, "stim": _STIM}),
                                        encoding="utf-8")
    (folder / "assays_OBI.json").write_text(json.dumps({"pheno": _TERM, "stim": _TERM}),
                                            encoding="utf-8")
    return folder


class _Client:
    def __init__(self, body: str):
        self.body, self.calls = body, 0
        self.chat = type("c", (), {"completions": self})()

    async def create(self, **_):
        self.calls += 1
        message = type("m", (), {"content": self.body})()
        return type("r", (), {"choices": [type("c", (), {"message": message})()]})()


@pytest.fixture
def no_client(monkeypatch):
    """A client factory that fails the test if anything reaches for it."""
    def _refuse():
        raise AssertionError("the plain path constructed a client")
    monkeypatch.setattr(claim_parser, "_get_client", _refuse)


def test_the_plain_path_folds_every_same_term_group_and_constructs_no_client(script, registry,
                                                                             no_client, capsys):
    script.canonicalize_one(registry)

    assays = json.loads((registry / "assays.json").read_text(encoding="utf-8"))
    assert list(assays) == ["flow cytometry assay"]
    assert assays["flow cytometry assay"]["name_in_paper"] == [_PHENO["name_in_paper"],
                                                               _STIM["name_in_paper"]]
    merges = json.loads((registry / "assays_merges.json").read_text(encoding="utf-8"))
    assert merges["summary"]["kept_apart"] == [] and "judge" not in merges
    assert "MERGED  stim → flow cytometry assay" in capsys.readouterr().out


def test_judge_keeps_the_split_the_judge_asked_for(script, registry, monkeypatch, capsys):
    client = _Client(json.dumps({"groups": [["pheno"], ["stim"]],
                                 "reason": "its own stimulation step"}))
    monkeypatch.setattr(claim_parser, "_get_client", lambda: client)

    script.canonicalize_one(registry, judge=True)

    assert client.calls == 1
    assays = json.loads((registry / "assays.json").read_text(encoding="utf-8"))
    assert list(assays) == ["flow cytometry assay", _STIM_KEY]
    obi = json.loads((registry / "assays_OBI.json").read_text(encoding="utf-8"))
    assert obi[_STIM_KEY]["obi_id"] == "OBI:0000916"
    benchmark = json.loads((registry / "assays_benchmark.json").read_text(encoding="utf-8"))
    assert benchmark[_STIM_KEY]["name_in_paper"] == [_STIM["name_in_paper"]]
    merges = json.loads((registry / "assays_merges.json").read_text(encoding="utf-8"))
    assert merges["summary"]["kept_apart"] == [_STIM_KEY]
    assert merges["key_map"]["stim"] == _STIM_KEY
    assert merges["judge"][0]["reason"] == "its own stimulation step"
    raw = json.loads((registry / "assays_raw.json").read_text(encoding="utf-8"))
    assert raw["canonicalize"]["flow cytometry assay"]["reply"] == client.body
    out = capsys.readouterr().out
    assert f"KEPT APART  {_STIM_KEY}: judged a different measurement from flow cytometry assay " \
           "— its own stimulation step" in out
    assert "MERGED" not in out


def test_judge_that_cannot_rule_folds_nothing_and_says_so(script, registry, monkeypatch, capsys):
    monkeypatch.setattr(claim_parser, "_get_client", lambda: _Client("{}"))

    script.canonicalize_one(registry, judge=True)

    assays = json.loads((registry / "assays.json").read_text(encoding="utf-8"))
    assert len(assays) == 2
    merges = json.loads((registry / "assays_merges.json").read_text(encoding="utf-8"))
    assert merges["summary"]["judge_failed"] == ["flow cytometry assay"]
    assert "FOLD JUDGE FAILED  flow cytometry assay:" in capsys.readouterr().out


def test_a_dry_run_with_judge_counts_the_calls_and_makes_none(script, registry, no_client, capsys):
    script.dry_run(registry, judge=True)

    out = capsys.readouterr().out
    assert "1 candidate group(s) to judge → 1 call(s)" in out
    assert "candidate group flow cytometry assay: pheno, stim" in out
    assert (registry / "assays_merges.json").exists() is False


# ── --map: finish a failed round without re-paying the entries it kept ─────────

_ERROR = {"obi_id": None, "obi_label": None, "resource": "error", "obi_error": "TimeoutError: x"}


def _mapper(seen: list) -> callable:
    def fake(assays, **_):
        seen.append(list(assays))
        return {key: {**_TERM, "resource": "embedding_llm"} for key in assays}
    return fake


def test_map_re_maps_only_the_entries_whose_lookup_failed(script, registry, monkeypatch):
    from app.agent import assay_obi_mapper
    (registry / "assays_OBI.json").write_text(json.dumps({"pheno": _TERM, "stim": _ERROR}),
                                              encoding="utf-8")
    seen: list = []
    monkeypatch.setattr(assay_obi_mapper, "enrich_assays_with_obi", _mapper(seen))

    script.canonicalize_one(registry, remap=True)

    assert seen == [["stim"]]
    # Both now share the term, so the plain path folded them; pheno's stored mapping survived.
    assays = json.loads((registry / "assays.json").read_text(encoding="utf-8"))
    assert list(assays) == ["flow cytometry assay"]
    obi = json.loads((registry / "assays_OBI.json").read_text(encoding="utf-8"))
    assert obi["flow cytometry assay"]["resource"] == "exact_original"


def test_map_with_nothing_failed_calls_nothing_and_says_so(script, registry, monkeypatch, capsys):
    from app.agent import assay_obi_mapper
    seen: list = []
    monkeypatch.setattr(assay_obi_mapper, "enrich_assays_with_obi", _mapper(seen))

    script.canonicalize_one(registry, remap=True)

    assert seen == []
    assert "nothing to re-map" in capsys.readouterr().out


def test_map_all_maps_every_entry_from_the_corrected_registry(script, registry, monkeypatch):
    from app.agent import assay_obi_mapper
    (registry / "assays_corrected.json").write_text(json.dumps({"pheno": _PHENO, "stim": _STIM}),
                                                    encoding="utf-8")
    seen: list = []
    monkeypatch.setattr(assay_obi_mapper, "enrich_assays_with_obi", _mapper(seen))

    script.canonicalize_one(registry, remap=True, remap_all=True)

    assert seen == [["pheno", "stim"]]


def test_map_with_no_mapping_on_disk_maps_every_entry(script, registry, monkeypatch):
    from app.agent import assay_obi_mapper
    (registry / "assays_OBI.json").unlink()
    seen: list = []
    monkeypatch.setattr(assay_obi_mapper, "enrich_assays_with_obi", _mapper(seen))

    script.canonicalize_one(registry, remap=True)

    assert seen == [["pheno", "stim"]]


def test_map_dry_run_counts_only_the_failed_entries(script, registry, no_client, capsys):
    (registry / "assays_OBI.json").write_text(json.dumps({"pheno": _TERM, "stim": _ERROR}),
                                              encoding="utf-8")

    script.dry_run(registry, remap=True)

    out = capsys.readouterr().out
    assert "for 1 of 2 entry(ies)" in out
    assert "needs embedding + LLM: stim" in out
    assert "pheno" not in out.split("entry(ies)")[1]
