import json

import pytest

import exp_obi_hierarchical as hier


@pytest.fixture(scope="module")
def families():
    return hier.compositional_children()


def test_elispot_has_its_43_compositional_children(families):
    kids = families["OBI:0600031"]
    assert len(kids) == 43
    assert all("measuring" in k["label"] for k in kids)
    assert all(k["definition"] for k in kids)


def test_a_term_with_no_compositional_descendant_is_absent(families):
    assert "OBI:0003112" not in families  # Olink assay
    assert "OBI:0003090" not in families  # bulk RNA-seq assay


def test_the_umbrellas_are_too_big_to_judge(families):
    assert len(families["OBI:0003128"]) > hier.MAX_CHILDREN  # T cell epitope assay
    assert len(families["OBI:0000661"]) <= hier.MAX_CHILDREN  # ELISA: 53


def test_the_gates(families):
    entry = {"readouts": "IFN-gamma spots", "sample_type": "PBMC"}
    assert hier.gate(None, [], entry) == hier.GATE_NO_FAMILY
    assert hier.gate("OBI:0003112", [], entry) == hier.GATE_NO_CHILDREN
    assert hier.gate("OBI:0003128", families["OBI:0003128"], entry) == hier.GATE_TOO_MANY
    assert hier.gate("OBI:0600031", families["OBI:0600031"], {"readouts": "", "sample_type": None}) == hier.GATE_NO_EVIDENCE
    assert hier.gate("OBI:0600031", families["OBI:0600031"], entry) == hier.GATE_JUDGED


@pytest.mark.parametrize("reply, expected", [
    ("3 | the readout is IFN-gamma", (2, "the readout is IFN-gamma")),
    ("keep | three cytokines", (None, "three cytokines")),
    ("KEEP | x", (None, "x")),
    ("  7  ", (6, "")),
    ("#2 | fine", (1, "fine")),
])
def test_reply_parsing(reply, expected):
    assert hier.parse_reply(reply, 10) == expected


@pytest.mark.parametrize("reply", ["", "maybe 3", "3 or 4 | unsure", "0 | none", "11 | out of range"])
def test_unreadable_replies_raise(reply):
    with pytest.raises(hier.ReplyError):
        hier.parse_reply(reply, 10)


def test_the_prompt_shows_the_record_and_every_child(families):
    entry = {"name_in_paper": ["IFN-γ ELISPOT"], "aliases": ["ELISpot"], "sample_type": "PBMC",
             "readouts": "IFN-γ spot-forming cells", "standard_technique_name": "enzyme-linked immunospot",
             "evidence": {"quote": "Spots were counted."}}
    family = {"id": "OBI:0600031", "label": "enzyme-linked immunospot assay", "definition": "A cytometry assay ..."}
    prompt = hier.build_prompt("k", entry, family, families["OBI:0600031"])
    assert '"IFN-γ ELISPOT"' in prompt and "ELISpot" in prompt and "Spots were counted." in prompt
    assert "43. OBI:" in prompt and "{children}" not in prompt and "{readouts}" not in prompt


def _registry(tmp_path, obi_id, label, readouts="IFN-γ spot-forming cells after peptide stimulation"):
    registry = tmp_path / "1_SDY1"
    registry.mkdir()
    (registry / "assays.json").write_text(json.dumps({"k": {
        "name_in_paper": ["IFN-γ ELISPOT"], "sample_type": "PBMC", "readouts": readouts,
        "evidence": {"quote": "q"}}}))
    (registry / "assays_OBI.json").write_text(json.dumps({"k": {
        "obi_id": obi_id, "obi_label": label, "obi_granularity": "EXACT", "resource": "embedding_llm"}}))
    return registry


def test_dry_run_judges_nothing_and_writes_nothing(tmp_path, families):
    registry = _registry(tmp_path, "OBI:0600031", "enzyme-linked immunospot assay")
    rows = hier.run(registry, dry_run=True, results_dir=tmp_path / "results",
                    judge_fn=lambda p: pytest.fail("the dry run called the judge"), families=families)
    assert rows[0]["gate"] == hier.GATE_JUDGED and rows[0]["reply"] is None
    assert not (tmp_path / "results").exists()


def test_a_child_pick_is_recorded_with_its_reason(tmp_path, families):
    registry = _registry(tmp_path, "OBI:0600031", "enzyme-linked immunospot assay")
    kids = families["OBI:0600031"]
    target = next(i for i, k in enumerate(kids, 1) if "interferon-gamma" in k["label"])
    rows = hier.run(registry, dry_run=False, results_dir=tmp_path / "results",
                    judge_fn=lambda p: f"{target} | IFN-gamma after peptide stimulation", families=families)
    assert rows[0]["specific"]["id"] == kids[target - 1]["id"]
    assert rows[0]["reason"] == "IFN-gamma after peptide stimulation"
    out = json.loads((tmp_path / "results" / "1_SDY1" / "hierarchical.json").read_text())
    assert out[0]["specific"]["id"] == kids[target - 1]["id"]
    raw = json.loads((tmp_path / "results" / "1_SDY1" / "raw.json").read_text())
    assert raw["k"]["reply"].startswith(str(target)) and "prompt" in raw["k"]
    assert sorted(p.name for p in registry.iterdir()) == ["assays.json", "assays_OBI.json"]


def test_keep_and_a_failed_reply_are_told_apart(tmp_path, families):
    registry = _registry(tmp_path, "OBI:0600031", "enzyme-linked immunospot assay")
    rows = hier.run(registry, dry_run=False, results_dir=tmp_path / "r1",
                    judge_fn=lambda p: "keep | lists three cytokines", families=families)
    assert rows[0]["specific"] is None and rows[0]["gate"] == hier.GATE_JUDGED
    rows = hier.run(registry, dry_run=False, results_dir=tmp_path / "r2",
                    judge_fn=lambda p: "I think candidate 3 or 5", families=families)
    assert rows[0]["gate"] == "JUDGE FAILED" and rows[0]["specific"] is None


def test_an_unmapped_or_childless_entry_never_reaches_the_judge(tmp_path, families):
    registry = _registry(tmp_path, None, None)
    rows = hier.run(registry, dry_run=False, results_dir=tmp_path / "results",
                    judge_fn=lambda p: pytest.fail("called"), families=families)
    assert rows[0]["gate"] == hier.GATE_NO_FAMILY
