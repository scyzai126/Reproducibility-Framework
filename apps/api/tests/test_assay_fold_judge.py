"""Adjudicating the folds round 5 refused: SAME folds through merge_entries, DIFFERENT stays
apart with the reason attached, a technique difference is never asked about."""

from app.agent.assay_fold_judge import (
    adjudicate,
    build_judge_prompt,
    judgeable,
    judged_pairs,
    parse_judge_reply,
)

ELISA_TERM = {"obi_id": "OBI:0000661", "obi_label": "enzyme-linked immunosorbent assay"}


def _entry(name, technique="ELISA", sample="serum", readouts="IgG titers",
           quote="Serum IgG was measured by ELISA."):
    return {"name_in_paper": [name], "standard_technique_name": technique, "aliases": [],
            "sample_type": sample, "readouts": readouts, "generate_claim": True,
            "source": "methods", "evidence": {"section": "Methods", "sentence_ids": ["S1"],
                                              "quote": quote}}


def _canonical():
    """SDY1328's shape after round 5: two ELISAs on one term, kept apart on readouts."""
    assays = {
        "enzyme-linked immunosorbent assay":
            _entry("GM1-ELISA", readouts="anti-CTB IgG titres by optical density"),
        "enzyme-linked immunosorbent assay (2)":
            _entry("commercial kit", readouts="anti-diphtheria IgG concentrations"),
    }
    obi = {k: {**ELISA_TERM, "name_in_paper": v["name_in_paper"]} for k, v in assays.items()}
    return assays, obi


def _judge(verdict, reason="because"):
    calls = []

    def judge(anchor_key, anchor, member_key, member, obi_label):
        calls.append((anchor_key, member_key, obi_label))
        return {"verdict": verdict, "reason": reason}
    judge.calls = calls
    return judge


def test_a_readouts_block_is_judged_and_a_same_verdict_folds_the_member():
    assays, obi = _canonical()
    judge = _judge("SAME", "one anti-toxin IgG ELISA described twice")

    merged, obi_out, folds, blocked = adjudicate(assays, obi, judge)

    assert judge.calls == [("enzyme-linked immunosorbent assay",
                            "enzyme-linked immunosorbent assay (2)",
                            "enzyme-linked immunosorbent assay")]
    assert list(merged) == ["enzyme-linked immunosorbent assay"]
    assert list(obi_out) == ["enzyme-linked immunosorbent assay"]
    survivor = merged["enzyme-linked immunosorbent assay"]
    assert survivor["name_in_paper"] == ["GM1-ELISA", "commercial kit"]
    assert survivor["additional_evidence"][0]["readouts"] == "anti-diphtheria IgG concentrations"
    assert obi_out["enzyme-linked immunosorbent assay"]["name_in_paper"] == \
        ["GM1-ELISA", "commercial kit"]
    assert folds == [{"key": "enzyme-linked immunosorbent assay", **ELISA_TERM,
                      "members": ["enzyme-linked immunosorbent assay",
                                  "enzyme-linked immunosorbent assay (2)"],
                      "folded": ["enzyme-linked immunosorbent assay (2)"],
                      "judged": {"verdict": "SAME",
                                 "reason": "one anti-toxin IgG ELISA described twice"}}]
    assert blocked == []


def test_a_different_verdict_keeps_the_pair_apart_with_the_reason_attached():
    assays, obi = _canonical()

    merged, obi_out, folds, blocked = adjudicate(assays, obi, _judge("DIFFERENT", "two antigens"))

    assert merged == assays and obi_out == obi and folds == []
    assert len(blocked) == 1
    assert blocked[0]["member"] == "enzyme-linked immunosorbent assay (2)"
    assert blocked[0]["reason"].startswith("readouts differs")
    assert blocked[0]["judged"] == {"verdict": "DIFFERENT", "reason": "two antigens"}


def test_a_technique_difference_is_never_sent_to_the_judge():
    assays, obi = _canonical()
    assays["enzyme-linked immunosorbent assay (2)"]["standard_technique_name"] = "multiplex bead assay"
    judge = _judge("SAME")

    merged, _, folds, blocked = adjudicate(assays, obi, judge)

    assert judge.calls == []
    assert merged == assays and folds == []
    assert len(blocked) == 1 and "judged" not in blocked[0]
    assert blocked[0]["reason"].startswith("standard_technique_name differs")
    assert not judgeable(blocked[0])
    assert judged_pairs(assays, obi) == []


def test_a_sample_type_block_is_judged_too():
    assays, obi = _canonical()
    assays["enzyme-linked immunosorbent assay (2)"]["readouts"] = "anti-CTB IgG titres by optical density"
    assays["enzyme-linked immunosorbent assay (2)"]["sample_type"] = "culture supernatants"

    pairs = judged_pairs(assays, obi)

    assert len(pairs) == 1 and pairs[0]["reason"].startswith("sample_type differs")


def test_a_reply_that_is_neither_verdict_never_folds():
    assert parse_judge_reply("SAME: one IgG ELISA") == ("SAME", "one IgG ELISA")
    assert parse_judge_reply("**Different** — the antigens differ") == \
        ("DIFFERENT", "the antigens differ")
    assert parse_judge_reply("different") == ("DIFFERENT", "")
    assert parse_judge_reply("I think these are probably the same") == \
        (None, "I think these are probably the same")
    # adjudicate folds only on the literal verdict, so an unparsed answer passed through as
    # judge_fold does (DIFFERENT, raw reply) keeps the pair apart.
    assays, obi = _canonical()
    _, _, folds, blocked = adjudicate(assays, obi, _judge("DIFFERENT", "reply not understood: ..."))
    assert folds == [] and len(blocked) == 1


def test_the_prompt_shows_both_records_and_the_shared_term():
    assays, obi = _canonical()
    anchor, member = assays.values()

    prompt = build_judge_prompt(anchor, member, "enzyme-linked immunosorbent assay")

    assert '"enzyme-linked immunosorbent assay"' in prompt
    assert "GM1-ELISA" in prompt and "commercial kit" in prompt
    assert "anti-CTB IgG titres by optical density" in prompt
    assert "anti-diphtheria IgG concentrations" in prompt
    assert "{" not in prompt  # every placeholder filled
