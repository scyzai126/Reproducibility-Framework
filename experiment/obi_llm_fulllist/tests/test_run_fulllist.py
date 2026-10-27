"""Offline tests for experiment/obi_llm_fulllist/run_fulllist.py. No API call."""

import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def mod():
    script = HERE.parent / "run_fulllist.py"
    spec = importlib.util.spec_from_file_location("run_fulllist", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _paper(registry, statuses):
    return {"registry_dir": f"x/{registry}", "rows": [{"status": s} for s in statuses]}


def test_select_ranks_by_non_exact_then_reference(mod, tmp_path):
    report = {"papers": [_paper("1_SDYA", ["MATCH", "MATCH"]),
                         _paper("2_SDYB", ["MATCH_OBI_CONFLICT", "MISSED"]),
                         _paper("3_SDYC", ["MATCH_GRANULARITY"]),
                         _paper("4_SDYD", ["MATCH_OBI_UNMAPPED", "MATCH_GRANULARITY"])]}
    reference = {"papers": [_paper("2_SDYB", []), _paper("3_SDYC", ["MATCH_OBI_CONFLICT"])]}
    picked = mod.select_papers(report, reference, source=tmp_path, n=3)
    assert [p["registry"] for p in picked] == ["4_SDYD", "3_SDYC", "2_SDYB"]
    assert picked[0]["non_exact_embedding"] == 2


def test_prompt_lists_whole_vocabulary_before_the_record(mod):
    vocab = mod.vocabulary()
    assert len(vocab) == 701
    prompt = mod.build_prompt("ELISA", vocab, readouts="IgG titers")
    lines = mod.candidate_lines(vocab)
    assert all(line in prompt for line in (lines[0], lines[-1]))
    assert prompt.index(lines[-1]) < prompt.index('Assay name from paper: "ELISA"')
    assert "similarity" not in "\n".join(lines)
    assert not any(line.endswith("()") for line in lines)
    assert "{" not in prompt.split("## Assay record")[1]


def test_pins_mark_in_place(mod):
    vocab = mod.vocabulary()
    pinned = [{"id": vocab[5]["id"], "label": vocab[5]["label"], "pin": "exact"},
              {"id": vocab[9]["id"], "label": vocab[9]["label"], "pin": "child"}]
    marked = mod.with_pins(vocab, pinned)
    assert [c["id"] for c in marked] == [c["id"] for c in vocab]
    lines = mod.candidate_lines(marked)
    assert lines[5].endswith("(exact name match)")
    assert lines[9].endswith("(child of exact name match)")


def test_pick_and_exact_floor(mod):
    vocab = mod.vocabulary()
    usage = {"prompt_tokens": 1, "completion_tokens": 1, "cached_tokens": 0}
    got = mod.fulllist_match("ELISA", complete=lambda p, m: ("3 exact", usage))
    assert got["obi_id"] == vocab[2]["id"] and got["resource"] == "fulllist_llm"
    assert got["granularity"] == "EXACT"
    assert mod.fulllist_match("blah", complete=lambda p, m: ("none", usage)) is None
    pinned = [{"id": vocab[5]["id"], "label": vocab[5]["label"], "pin": "exact"}]
    floor = mod.fulllist_match("x", pinned=pinned, complete=lambda p, m: ("none", usage))
    assert floor["obi_id"] == vocab[5]["id"] and floor["resource"] == "exact_original_llm"


def test_patch_restored(mod):
    from app.agent import assay_obi_mapper as mapper

    original = mapper._embedding_llm_match
    with mod.FullList():
        assert mapper._embedding_llm_match is mod.fulllist_match
    assert mapper._embedding_llm_match is original
