"""Tests for the deterministic half of the five-pass abstraction: prompt assembly,
JATS panel splitting, modal-sample selection, verdict application, token accounting."""

from pathlib import Path

import pytest

from app.agent.claim_abstraction_v5 import (
    UsageTracker,
    apply_verdicts,
    build_pass1_user_message,
    load_v5_prompts,
    pick_modal,
    split_panels,
    system_prompts,
)
from app.agent.claim_filter import DOWNSTREAM_CLAIM_TYPES
from app.agent.claim_parser import CLAIM_TYPES_PLACEHOLDER

_REPO_ROOT = Path(__file__).resolve().parents[3]

JATS = """<article>
  <front><article-meta>
    <abstract><p>We measured antibody responses to two vaccines.</p></abstract>
  </article-meta></front>
  <body>
    <sec><title>Results</title>
      <sec><title>Antibody responses</title>
        <p>IgG rose by day 7 (<xref rid="F1" ref-type="fig">Fig. 1a</xref>).</p>
        <p>Titers differed between arms (<xref rid="F1" ref-type="fig">Fig. 1b</xref>,
           <xref rid="T1" ref-type="table">Table 1</xref>).</p>
      </sec>
      <sec><title>Modules</title>
        <p>Module M75 was enriched (<xref rid="F2" ref-type="fig">Fig. 2</xref>).</p>
      </sec>
    </sec>
    <sec><title>On-line Methods</title>
      <p>IgG was measured by ELISA in serum.</p>
    </sec>
    <fig id="F1"><label>Figure 1</label><caption><p>Antibody responses. n=13 per arm.</p></caption></fig>
    <fig id="F2"><label>Figure 2</label><caption><p>Module activity.</p></caption></fig>
    <fig id="F3"><label>Figure 3</label><caption><p>Never cited in the results.</p></caption></fig>
    <table-wrap id="T1"><label>Table 1</label><caption><p>Subject demographics.</p></caption>
      <table-wrap-foot><p>SBA, serum bactericidal assay.</p></table-wrap-foot>
    </table-wrap>
  </body>
</article>"""


# ── prompt assembly ───────────────────────────────────────────────────────────


V5_PROMPT = "claim_abstraction_prompt_v5.md"


@pytest.mark.parametrize("prompt_file", [None, V5_PROMPT])
def test_load_prompts_returns_every_block(prompt_file):
    """Both documents carry the same five-pass skeleton and must parse identically."""
    blocks = load_v5_prompts() if prompt_file is None else load_v5_prompts(prompt_file)
    assert set(blocks) == {"preamble", "pass1", "pass2", "pass3", "pass4", "pass5"}
    assert all(v.strip() for v in blocks.values())


def test_load_v5_prompts_rejects_a_document_missing_a_pass(tmp_path, monkeypatch):
    from app.agent import claim_abstraction_v5 as mod

    monkeypatch.setattr(mod, "_load_prompt", lambda _f: "## SHARED PREAMBLE\n```\nhi\n```")
    with pytest.raises(ValueError, match="pass1"):
        mod.load_v5_prompts("stub.md")


def test_document_prose_outside_fences_is_not_sent():
    """The header above PASS 1 is build instructions for the implementer, not prompt text."""
    prompts = system_prompts(load_v5_prompts())
    for text in prompts.values():
        assert "SYS_PASS1" not in text
        assert "prompt_borrow_decisions" not in text


def test_only_passes_1_and_2_carry_the_preamble():
    blocks = load_v5_prompts()
    prompts = system_prompts(blocks)
    first_line = blocks["preamble"].splitlines()[0]
    assert prompts["pass1"].startswith(first_line)
    assert prompts["pass2"].startswith(first_line)
    for audit in ("pass3", "pass4", "pass5"):
        assert prompts[audit] == blocks[audit]


def test_v6_substitutes_the_shared_claim_type_vocabulary():
    """The extractor and the accuracy judge must read one vocabulary file — an
    unsubstituted placeholder is still a valid prompt and would run without it."""
    prompts = system_prompts(load_v5_prompts())
    assert CLAIM_TYPES_PLACEHOLDER not in prompts["pass1"]
    assert "precedence ladder" in prompts["pass1"]
    for claim_type in DOWNSTREAM_CLAIM_TYPES:
        assert claim_type in prompts["pass1"]


def test_vocabulary_substitution_survives_its_own_code_fence():
    """claim_types.txt fences its precedence ladder in ```. Substituting it before the
    blocks are split closes the preamble at that fence and silently drops everything after
    it — the head, polarity, and the sources rules all live below the vocabulary."""
    vocabulary = (_REPO_ROOT / "apps/api/app/prompts/claim_types.txt").read_text(encoding="utf-8")
    assert "```" in vocabulary, "this test is meaningless if the fragment stops fencing"

    preamble = load_v5_prompts()["preamble"]
    assert "precedence ladder" in preamble
    # Everything below the vocabulary in the document — proof the block was not truncated.
    assert "SOURCES." in preamble
    assert "FILLING THE PROVENANCE FIELDS" in preamble


def test_v6_keeps_sources_and_drops_the_bare_quote_field():
    """validate_claims.txt treats `sources` as its only ground truth, so v6 carries the
    original's array rather than v5's single quote string."""
    prompts = system_prompts(load_v5_prompts())
    assert '"sources"' in prompts["pass1"]
    assert '"quote": "<VERBATIM' not in prompts["pass1"]
    assert "Figure N caption" in prompts["pass1"]


def test_v6_requires_the_mandatory_head():
    """claim_validator._head() splits on "showed" and the metadata pass batches by head."""
    prompts = system_prompts(load_v5_prompts())
    assert "THE HEAD IS MANDATORY IN BOTH FORMS" in prompts["pass1"]
    assert "showed" in prompts["pass1"]


def test_v6_carries_polarity_and_not_the_retired_null_result_type():
    prompts = system_prompts(load_v5_prompts())
    assert "POLARITY is separate from type" in prompts["pass1"]
    assert '"polarity": "affirm" | "null"' in prompts["pass1"]
    assert "null_result" not in prompts["pass1"]


def test_v6_names_a_closed_not_a_claim_reason_vocabulary():
    """The SDY1260 run invented `panel-not-this-figure` and `figure-not-supported` for
    assertions belonging to a neighbouring panel; `other-panel` gives them a real home."""
    prompts = system_prompts(load_v5_prompts())
    assert "other-panel" in prompts["pass1"]
    assert "Use exactly these six reason strings" in prompts["pass1"]
    assert "NARROWING IS A REWRITE, NOT A DEMOTION" in prompts["pass2"]


def test_v6_pass5_normalizes_names_across_panels():
    """sample_type drifted across panels on SDY1260 ("PBMC" x13 vs "PBMCs" x2)."""
    prompts = system_prompts(load_v5_prompts())
    assert "NAMING" in prompts["pass5"]
    assert "sample_type" in prompts["pass5"]
    assert "serum and plasma are not the same sample" in prompts["pass5"]


# ── panel splitting ───────────────────────────────────────────────────────────


def test_split_panels_attaches_prose_by_cross_reference():
    paper = split_panels(JATS)
    by_id = {p.panel_id: p for p in paper.panels}

    assert set(by_id) == {"F1", "F2", "F3", "T1"}
    assert len(by_id["F1"].prose_paragraphs) == 2
    assert by_id["F2"].prose_paragraphs == ["Module M75 was enriched (Fig. 2)."]
    assert by_id["F3"].prose_paragraphs == []


def test_a_paragraph_citing_two_panels_feeds_both():
    by_id = {p.panel_id: p for p in split_panels(JATS).panels}
    shared = "Titers differed between arms (Fig. 1b, Table 1)."
    assert shared in by_id["F1"].prose
    assert shared in by_id["T1"].prose


def test_legend_carries_label_caption_and_table_footer():
    by_id = {p.panel_id: p for p in split_panels(JATS).panels}
    assert by_id["F1"].legend == "Figure 1 Antibody responses. n=13 per arm."
    assert "SBA, serum bactericidal assay." in by_id["T1"].legend


def test_abstract_and_methods_are_separated_from_panel_prose():
    paper = split_panels(JATS)
    assert paper.abstract == "We measured antibody responses to two vaccines."
    assert paper.methods.startswith("On-line Methods")
    assert "ELISA" in paper.methods
    assert all("ELISA" not in p.prose for p in paper.panels)


def test_methods_precedes_prose_so_the_shared_prefix_caches():
    panel = next(p for p in split_panels(JATS).panels if p.panel_id == "F2")
    message = build_pass1_user_message(panel, "IgG was measured by ELISA.")
    assert message.index("METHODS") < message.index("RESULTS TEXT")
    assert message.endswith(panel.prose)


def test_pass1_message_omits_the_methods_block_when_there_is_none():
    panel = next(p for p in split_panels(JATS).panels if p.panel_id == "F2")
    assert build_pass1_user_message(panel, "") == f"RESULTS TEXT:\n{panel.prose}"


# ── modal sampling ────────────────────────────────────────────────────────────


def test_pick_modal_returns_the_most_common_claim_count():
    samples = [
        {"claims": [1, 2, 3, 4, 5, 6, 7]},
        {"claims": [1, 2, 3, 4, 5, 6], "tag": "modal"},
        {"claims": [1, 2, 3, 4, 5, 6]},
        {"claims": [1, 2, 3, 4, 5, 6, 7, 8]},
        {"claims": [1, 2, 3, 4, 5, 6]},
    ]
    chosen, tally, decisive = pick_modal(samples)
    assert chosen["tag"] == "modal"
    assert tally == {6: 3, 7: 1, 8: 1}
    assert decisive


def test_pick_modal_breaks_ties_toward_the_first_seen_count():
    chosen, tally, decisive = pick_modal([{"claims": [1, 2]}, {"claims": [1]}])
    assert len(chosen["claims"]) == 2
    assert tally == {1: 1, 2: 1}
    assert not decisive


def test_a_three_two_split_is_used_but_flagged_as_indecisive():
    """SDY1260 Figure 2 returned {2: 3, 10: 2} — a strict majority that still let one sample
    decide between 2 claims and 10. The mode wins; the run record says it was not settled."""
    samples = [{"claims": [1, 2]}] * 3 + [{"claims": list(range(10))}] * 2
    chosen, tally, decisive = pick_modal(samples)
    assert len(chosen["claims"]) == 2
    assert tally == {2: 3, 10: 2}
    assert not decisive


def test_a_unanimous_run_is_decisive():
    _, tally, decisive = pick_modal([{"claims": [1, 2, 3, 4, 5]}] * 5)
    assert tally == {5: 5}
    assert decisive


def test_pick_modal_rejects_an_empty_sample_set():
    with pytest.raises(ValueError):
        pick_modal([])


# ── provenance verdicts ───────────────────────────────────────────────────────


def test_apply_verdicts_demotes_only_the_flagged_claim():
    claims = [
        {"claim": "M75 activity correlates with titer", "targets": ["M75"]},
        {"claim": "the network edges come from Li et al.", "targets": ["edges"]},
    ]
    verdicts = [
        {"claim": "M75 activity correlates with titer", "action": "keep", "audited": True},
        {
            "claim": "the network edges come from Li et al.",
            "action": "demote_to_not_a_claim",
            "audited": True,
        },
    ]
    kept, demoted = apply_verdicts(claims, verdicts)

    assert [c["claim"] for c in kept] == ["M75 activity correlates with titer"]
    assert kept[0]["provenance_audit"]["action"] == "keep"
    assert demoted[0]["identifiers"] == ["edges"]
    assert demoted[0]["reason"] == "external-import"


def test_narrow_verdict_keeps_the_claim_and_flags_it():
    """The audit pass may not rewrite claims, so narrowing is left for a human."""
    claims = [{"claim": "colors show correlation with age", "targets": []}]
    verdicts = [{"claim": "colors show correlation with age", "action": "narrow_to_data_derived_part"}]
    kept, demoted = apply_verdicts(claims, verdicts)

    assert len(kept) == 1 and not demoted
    assert kept[0]["provenance_audit"]["action"] == "narrow_to_data_derived_part"


def test_a_claim_the_audit_never_reported_on_survives_unflagged():
    kept, demoted = apply_verdicts([{"claim": "unaudited", "targets": []}], [])
    assert len(kept) == 1 and not demoted
    assert "provenance_audit" not in kept[0]


# ── token accounting ──────────────────────────────────────────────────────────


class _Usage:
    def __init__(self, prompt, completion, cached=0):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion
        self.prompt_tokens_details = type("D", (), {"cached_tokens": cached})()


def test_usage_tracker_totals_by_pass():
    tracker = UsageTracker()
    tracker.record("pass1", _Usage(1000, 200, cached=800))
    tracker.record("pass1", _Usage(1000, 300, cached=900))
    tracker.record("pass2", _Usage(2000, 400))

    summary = tracker.summary()
    assert summary["by_pass"]["pass1"] == {
        "calls": 2, "prompt": 2000, "cached": 1700, "completion": 500, "total": 2500,
    }
    assert summary["total"] == {
        "calls": 3, "prompt": 4000, "cached": 1700, "completion": 900, "total": 4900,
    }


def test_a_response_without_usage_still_counts_as_a_call():
    """An unbilled-looking response must not silently vanish from the call count."""
    tracker = UsageTracker()
    tracker.record("pass3", None)
    assert tracker.summary()["total"]["calls"] == 1
    assert tracker.summary()["total"]["total"] == 0
