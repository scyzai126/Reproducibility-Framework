"""Round 5's judge: whether entries that share an OBI term are one measurement.

A shared term makes two entries candidates, not one assay -- 12 of the 18 folds on the 31-paper
run merged different measurements. The judge sees the records and nothing else, so the tests are
about what it is shown, how its answer is checked against the members it was asked about, and
that a failed call is a recorded failure rather than a raise or a fold.
"""

import json

import pytest

from app.agent import assay_trace
from app.agent.assay_fold_judge import (
    build_prompt,
    candidate,
    judge_fold,
    judge_fold_groups,
    parse_partition,
)

_LABEL = "flow cytometry assay"

_PHENO = {
    "name_in_paper": "Flow cytometry analysis and cell sorting",
    "standard_technique_name": "flow cytometry", "aliases": ["FACS"],
    "sample_type": None, "readouts": "cell surface marker expression on NK cells",
    "source": "methods",
    "evidence": {"section": "Flow cytometry analysis and cell sorting", "sentence_ids": ["S40"],
                 "quote": "Cells were stained and acquired on an LSRFortessa."},
}
_STIM = {
    "name_in_paper": "In vitro cytokine stimulation and functional assays of NK cells",
    "standard_technique_name": "flow cytometry", "aliases": [],
    "sample_type": "PBMCs", "readouts": "intracellular IFN-γ production after stimulation",
    "source": "methods",
    "evidence": {"section": "In vitro cytokine stimulation", "sentence_ids": ["S52"],
                 "quote": "PBMCs were stimulated with IL-12 and IL-18 and stained for IFN-γ."},
}
_ASSAYS = {"pheno": _PHENO, "stim": _STIM}
_MEMBERS = ["pheno", "stim"]


class _Client:
    def __init__(self, *bodies):
        self.bodies, self.calls, self.prompts = list(bodies), 0, []
        self.chat = type("c", (), {"completions": self})()

    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        body = self.bodies[min(self.calls, len(self.bodies) - 1)]
        self.calls += 1
        if isinstance(body, Exception):
            raise body
        message = type("m", (), {"content": body})()
        return type("r", (), {"choices": [type("c", (), {"message": message})()]})()


def _reply(groups, reason="judged") -> str:
    return json.dumps({"groups": groups, "reason": reason})


# ── what the judge is shown ───────────────────────────────────────────────────

def test_the_prompt_carries_every_member_field_and_the_label_and_no_paper_text():
    prompt = build_prompt(_LABEL, _MEMBERS, _ASSAYS)

    assert _LABEL in prompt
    for entry in (_PHENO, _STIM):
        assert entry["name_in_paper"] in prompt
        assert entry["readouts"] in prompt
        assert entry["evidence"]["section"] in prompt
        assert entry["evidence"]["quote"] in prompt
    assert "PBMCs" in prompt and "FACS" in prompt
    # The judge rules on the records alone: no placeholder for the paper is left, and none is
    # filled -- there is no `{source_text}` in this prompt to fill.
    assert "{candidates}" not in prompt and "{obi_label}" not in prompt
    assert "{source_text}" not in prompt and "ORIGINAL SOURCE TEXT" not in prompt


def test_the_prompt_says_a_null_specimen_is_not_a_disagreement():
    assert "null" in build_prompt(_LABEL, _MEMBERS, _ASSAYS)
    assert "not a disagreement" in build_prompt(_LABEL, _MEMBERS, _ASSAYS)


def test_a_candidate_is_the_eight_fields_and_reads_an_old_schema_evidence_location():
    old = {**_PHENO, "evidence_location": {"section": "Old", "quote": "old quote"}}
    del old["evidence"]

    record = candidate("pheno", old)

    assert tuple(record) == ("key", "name_in_paper", "standard_technique_name", "aliases",
                             "sample_type", "readouts", "section", "quote")
    assert (record["key"], record["section"], record["quote"]) == ("pheno", "Old", "old quote")


# ── the answer is checked against the members ────────────────────────────────

def test_a_valid_partition_is_normalised_to_registry_order():
    """Sets sorted by their first member's index and members within a set likewise, so the first
    set always holds the anchor and the same answer always yields the same keys."""
    sets, error = parse_partition([["c", "a"], ["b"]], ["a", "b", "c"])

    assert error is None
    assert sets == [["a", "c"], ["b"]]


@pytest.mark.parametrize("raw", [
    [["pheno"]],                      # a member is missing
    [["pheno", "stim"], ["stim"]],    # a member is repeated
    [["pheno", "stim", "other"]],     # a member the judge invented
    [["pheno"], []],                  # an empty set
    [["pheno", "stim"], "stim"],      # not a list of lists
    "pheno, stim",
    None,
])
def test_an_answer_that_is_not_a_partition_of_the_members_is_an_error(raw):
    sets, error = parse_partition(raw, _MEMBERS)

    assert sets is None
    assert error


@pytest.mark.asyncio
async def test_the_record_carries_the_groups_and_the_reason():
    record = await judge_fold(_LABEL, _MEMBERS, _ASSAYS,
                              _Client(_reply([["pheno"], ["stim"]], "its own stimulation step")),
                              "m")

    assert record == {"label": _LABEL, "members": _MEMBERS, "groups": [["pheno"], ["stim"]],
                      "reason": "its own stimulation step", "error": None}


@pytest.mark.asyncio
async def test_a_missing_member_in_the_reply_leaves_groups_none_with_the_error():
    record = await judge_fold(_LABEL, _MEMBERS, _ASSAYS, _Client(_reply([["pheno"]])), "m")

    assert record["groups"] is None
    assert "stim" in record["error"]


# ── a failed call is recorded, never raised, never folded ────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["", "[]", "\"yes\"", "{not json"])
async def test_an_empty_or_non_object_reply_is_a_failure(body):
    record = await judge_fold(_LABEL, _MEMBERS, _ASSAYS, _Client(body), "m")

    assert record["groups"] is None
    assert record["error"]


@pytest.mark.asyncio
async def test_an_api_error_is_recorded_and_not_raised():
    record = await judge_fold(_LABEL, _MEMBERS, _ASSAYS, _Client(TimeoutError("slow")), "m")

    assert record["groups"] is None
    assert record["error"] == "TimeoutError: slow"


@pytest.mark.asyncio
async def test_replies_and_errors_are_traced_under_the_round():
    trace = assay_trace.start()
    try:
        await judge_fold(_LABEL, ["pheno", "stim"], _ASSAYS, _Client(_reply([["pheno", "stim"]])),
                         "m")
        await judge_fold("other", ["pheno", "stim"], _ASSAYS, _Client(TimeoutError("slow")), "m")
    finally:
        assay_trace.stop()

    traced = trace.as_json()["canonicalize"]
    assert traced[_LABEL]["reply"] == _reply([["pheno", "stim"]])
    assert traced["other"]["error"] == "TimeoutError: slow"


# ── a registry's candidate groups, judged together ───────────────────────────

@pytest.mark.asyncio
async def test_records_come_back_in_group_order_and_the_partition_is_keyed_by_label():
    """Two candidate groups answered by one client in call order; `gather` keeps group order
    however the calls interleave, and a failed group is `None` rather than absent."""
    assays = {**_ASSAYS, "elisa": {**_PHENO, "name_in_paper": "ELISA"},
              "kits": {**_PHENO, "name_in_paper": "ELISA kits"}}
    groups = [{"obi_label": _LABEL, "members": ["pheno", "stim"]},
              {"obi_label": "ELISA", "members": ["elisa", "kits"]}]
    client = _Client(_reply([["pheno"], ["stim"]]), "")

    partition, records = await judge_fold_groups(groups, assays, client, "m", max_concurrency=1)

    assert [r["label"] for r in records] == [_LABEL, "ELISA"]
    assert partition == {_LABEL: [["pheno"], ["stim"]], "ELISA": None}
    assert records[1]["error"]


@pytest.mark.asyncio
async def test_no_candidate_groups_means_no_call():
    client = _Client(_reply([]))

    partition, records = await judge_fold_groups([], _ASSAYS, client, "m")

    assert (partition, records, client.calls) == ({}, [], 0)
