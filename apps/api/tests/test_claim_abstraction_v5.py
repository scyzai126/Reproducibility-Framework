"""Tests for the deterministic half of the five-pass abstraction: prompt assembly,
JATS panel splitting, modal-sample selection, verdict application, token accounting."""

from pathlib import Path

import pytest

from app.agent.claim_abstraction_v5 import (
    CLAIMS_OUTPUT_FIELDS,
    UsageTracker,
    apply_verdicts,
    build_pass1_user_message,
    load_v5_prompts,
    pick_modal,
    project_claims,
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
V7_PROMPT = "claim_abstraction_prompt_v7.md"


@pytest.mark.parametrize("prompt_file", [None, V5_PROMPT, V7_PROMPT])
def test_load_prompts_returns_every_block(prompt_file):
    """All three documents carry the same five-pass skeleton and must parse identically."""
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


# ── v7: the granularity guideline ─────────────────────────────────────────────


def test_v7_preserves_everything_downstream_parses():
    """v7 changes only the splitting rules. claim_validator._head() splits on "showed",
    validate_claims.txt reads `sources`, and claim_filter reads the shared vocabulary — a
    v7 that dropped any of them would still be a runnable prompt."""
    prompts = system_prompts(load_v5_prompts(V7_PROMPT))

    assert "THE HEAD IS MANDATORY IN BOTH FORMS" in prompts["pass1"]
    assert "showed" in prompts["pass1"]
    assert '"sources"' in prompts["pass1"]
    assert "Figure N caption" in prompts["pass1"]
    assert "POLARITY is separate from type" in prompts["pass1"]
    assert '"polarity": "affirm" | "null"' in prompts["pass1"]
    assert "null_result" not in prompts["pass1"]
    assert "Use exactly these six reason strings" in prompts["pass1"]

    assert CLAIM_TYPES_PLACEHOLDER not in prompts["pass1"]
    for claim_type in DOWNSTREAM_CLAIM_TYPES:
        assert claim_type in prompts["pass1"]


@pytest.mark.parametrize("prompt_file", [None, V7_PROMPT])
def test_response_difference_carries_both_of_its_references(prompt_file):
    """A difference-in-differences needs two references — the within-group baseline each arm
    is measured against, and the comparator arm. `contrast` has one `reference` slot, so
    without `within_reference` the baseline is overwritten by the comparator and the record
    no longer says whether to compare levels or changes. Both v6 (the module default) and v7
    must ship the field and the rule that fills it."""
    prompts = system_prompts(load_v5_prompts() if prompt_file is None
                             else load_v5_prompts(prompt_file))
    pass1 = prompts["pass1"]

    assert "response_difference" in pass1
    assert '"within_reference"' in pass1
    # The DiD must not be split into an induction plus a between-group comparison.
    assert "difference-in-differences is ONE claim" in pass1
    # And the level/change test that decides the type must survive the vocabulary injection.
    assert "Level or change?" in pass1


def test_v7_carries_the_one_claim_one_verdict_test():
    """The principle the five rules are derived from. v6 listed the rules without it."""
    prompts = system_prompts(load_v5_prompts(V7_PROMPT))
    assert "ONE CLAIM = ONE VERDICT" in prompts["pass1"]
    assert "CAN THIS COME BACK HALF-TRUE" in prompts["pass1"]


def test_v7_guards_over_splitting_not_only_under_splitting():
    """The gap v7 exists to close: every v6-era prompt pushes one direction only."""
    prompts = system_prompts(load_v5_prompts(V7_PROMPT))
    assert "OVER-SPLITTING" in prompts["pass1"]
    assert "THE TWO FAILURE MODES ARE NOT SYMMETRIC" in prompts["pass1"]
    # The asymmetry must survive: splitting stays the safer default.
    assert "Under-extraction is as much a defect as fabrication" in prompts["pass1"]
    assert "Splitting remains the safer default" in prompts["pass1"]


def test_v7_adds_the_data_object_split_and_the_merging_case():
    """Rule 5 and its counterweight — absent from every other prompt in the repo."""
    prompts = system_prompts(load_v5_prompts(V7_PROMPT))
    assert "RULE 5 — SPLIT WHEN THE DATA OBJECT DIFFERS" in prompts["pass1"]
    assert "THE ONE CASE THAT ARGUES FOR MERGING" in prompts["pass1"]
    assert "WRITE THE REPRODUCTION PROCEDURE BEFORE YOU SPLIT" in prompts["pass1"]
    assert "CALIBRATION" in prompts["pass1"]


def test_v7_keeps_the_cardinality_test_and_its_one_way_converse():
    """Splitting on claim_type is the mechanical under-split check; a SHARED type is
    never grounds to merge. The over-split guard must not have weakened either."""
    prompts = system_prompts(load_v5_prompts(V7_PROMPT))
    assert "CARDINALITY TEST" in prompts["pass1"]
    assert "THE CONVERSE DOES NOT HOLD" in prompts["pass1"]
    assert "conjunction" in prompts["pass1"]
    # The vocabulary-consistent shared-type example carries the converse on its own.
    assert "remained above baseline at day 750" in prompts["pass1"]


def test_v7_does_not_prescribe_group_difference_for_whole_course_comparisons():
    """v7 once told the extractor that the magnitude and duration halves of the SDY1260
    Fig. 1a sentence were BOTH `group_difference`. That contradicted claim_types.txt three
    ways -- group_difference requires a matched timepoint, the precedence ladder ranks
    trajectory_segment and magnitude_comparison above it, and "greater magnitude" is a
    listed magnitude_comparison cue -- and the SDY1260 run typed the same assertion two
    different ways across panels as a result."""
    prompts = system_prompts(load_v5_prompts(V7_PROMPT))
    assert "BOTH `group_difference`" not in prompts["pass1"]
    assert "A BETWEEN-ARM COMPARISON IS NOT AUTOMATICALLY `group_difference`" in prompts["pass1"]
    assert "magnitude -> `response_difference`" in prompts["pass1"]
    assert 'duration -> `trajectory_segment` ("how long it lasts")' in prompts["pass1"]


def test_v7_magnitude_duration_convention_matches_the_whole_pdf_extractor():
    """The five-pass and single-call extractors must not drift on this pair.
    extract_claims_pdf.txt's worked example is the origin of the convention."""
    whole_pdf = (
        _REPO_ROOT / "apps/api/app/prompts/extract_claims_pdf.txt"
    ).read_text(encoding="utf-8")
    assert "greater magnitude" in whole_pdf and "`claim_type: response_difference`" in whole_pdf
    assert "greater duration" in whole_pdf and "`claim_type: trajectory_segment`" in whole_pdf
    # The magnitude half compares two ARMS, so it is a response_difference; labelling it
    # magnitude_comparison would send it to the filter's discard pile.
    assert "showed greater magnitude of the polysaccharide-specific IgG response after MPSV4"\
           " compared to a single dose of MCV4.\" `claim_type: magnitude_comparison`" not in whole_pdf

    pass1 = system_prompts(load_v5_prompts(V7_PROMPT))["pass1"]
    assert "`response_difference`" in pass1
    assert '`trajectory_segment` ("how long it lasts")' in pass1


def test_v7_routes_the_merge_decision_to_pass1_only():
    """Pass 2 sees the draft and the legend, never the prose, so it cannot re-derive the
    reproduction procedure that decides a merge. Without this, v7's new recombine step
    would read as licence for pass 2 to merge — and pass 2 forbids exactly that."""
    prompts = system_prompts(load_v5_prompts(V7_PROMPT))
    assert "PASS 1 IS THE ONLY PLACE IT CAN HAPPEN" in prompts["pass1"]
    assert "Do not merge draft claims." in prompts["pass2"]
    assert "YOU CANNOT TELL AN OVER-SPLIT PARTITION" in prompts["pass2"]
    # Pass 5 still owns cross-panel redundancy, and still may not undo a legitimate split.
    assert "SHARING A SOURCE IS NORMAL" in prompts["pass5"]


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


def _paper(methods_xml: str) -> str:
    """A minimal article carrying one figure panel and the given Methods markup."""
    return f"""<article>
  <front><article-meta><abstract><p>An abstract.</p></abstract></article-meta></front>
  <body>
    <sec><title>Results</title>
      <p>IgG rose (<xref rid="F1" ref-type="fig">Fig. 1</xref>).</p>
    </sec>
    {methods_xml}
    <fig id="F1"><label>Figure 1</label><caption><p>Antibody responses.</p></caption></fig>
  </body>
</article>"""


def test_methods_is_found_under_a_cell_press_experimental_procedures_heading():
    """A prefix match on "methods" missed this on 4 of the 30 corpus papers."""
    paper = split_panels(_paper(
        "<sec><title>EXPERIMENTAL PROCEDURES</title><p>IgG was measured by ELISA.</p></sec>"
    ))

    assert "ELISA" in paper.methods


def test_methods_is_found_under_a_star_methods_heading():
    paper = split_panels(_paper(
        "<sec><title>STAR\u2605METHODS</title><p>IgG was measured by ELISA.</p></sec>"
    ))

    assert "ELISA" in paper.methods


def test_a_parent_methods_section_wins_over_its_own_subsections():
    """Otherwise the first nested child is picked and the rest of Methods is dropped."""
    paper = split_panels(_paper(
        "<sec><title>STAR METHODS</title>"
        "<sec><title>Method Details</title><p>IgG was measured by ELISA.</p></sec>"
        "<sec><title>Quantification</title><p>Titers were log-transformed.</p></sec>"
        "</sec>"
    ))

    assert "ELISA" in paper.methods
    assert "log-transformed" in paper.methods


def test_the_real_methods_wins_over_an_earlier_results_subsection_titled_study_design():
    """"Study design for ..." canonicalizes to methods too, and comes first in the document."""
    paper = split_panels("""<article>
  <front><article-meta><abstract><p>An abstract.</p></abstract></article-meta></front>
  <body>
    <sec><title>Results</title>
      <sec><title>Study design for integrative profiling</title><p>Subjects were enrolled.</p></sec>
      <p>IgG rose (<xref rid="F1" ref-type="fig">Fig. 1</xref>).</p>
    </sec>
    <sec><title>STAR METHODS</title>
      <p>IgG was measured by ELISA in serum, with titers reported as endpoint dilutions.</p>
    </sec>
    <fig id="F1"><label>Figure 1</label><caption><p>Antibody responses.</p></caption></fig>
  </body>
</article>""")

    assert "ELISA" in paper.methods
    assert "were enrolled" not in paper.methods


def test_a_paper_with_no_methods_section_still_reports_none():
    paper = split_panels(_paper(""))

    assert paper.methods == ""


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


# ── claims.json projection ────────────────────────────────────────────────────


def _full_claim(**overrides) -> dict:
    """A claim carrying every field the five passes attach to it."""
    claim = {
        "claim": "ELISA analysis of serum ... showed X.",
        "claim_type": "induction_vs_reference",
        "polarity": "affirm",
        "measured": "titer",
        "operation": None,
        "contrast": {"subject_groups": [{"label": "MCV4"}], "reference": "baseline"},
        "targets": ["IgG"],
        "timepoints": ["day 7"],
        "candidate_set": None,
        "parent_claims": [],
        "assay": "ELISA",
        "sample_type": "serum",
        "cohort_n": "n=17",
        "timeframe": "days 0-30",
        "method": "paired t-test",
        "sources": [{"type": "text", "section": "Results", "quote": "verbatim"}],
        "unspecified": ["threshold"],
        "data_derived_part": "the comparison",
        "imported_inputs": [],
        "scope_changes": ["measured: a -> b"],
        "figure_omissions": [],
        "method_added": ["paired t-test"],
        "provenance_audit": {"audited": True, "action": "keep"},
        "panel": "Figure 1",
    }
    claim.update(overrides)
    return claim


def test_project_claims_keeps_only_the_output_fields():
    """~53% of claims.json was scaffolding no downstream stage reads."""
    out = project_claims({"claim_1": _full_claim()})
    assert tuple(out["claim_1"]) == CLAIMS_OUTPUT_FIELDS
    for dropped in ("provenance_audit", "contrast", "scope_changes", "method_added",
                    "polarity", "panel", "sample_type", "unspecified", "assay"):
        assert dropped not in out["claim_1"]
    assert out["claim_1"]["sources"][0]["quote"] == "verbatim"


def test_project_claims_preserves_claim_order_and_emits_missing_fields_as_null():
    """Every entry keeps the same shape, so a reader can index without testing presence."""
    claims = {"claim_2": _full_claim(), "claim_1": {"claim": "bare"}}
    out = project_claims(claims)
    assert list(out) == ["claim_2", "claim_1"]
    assert tuple(out["claim_1"]) == CLAIMS_OUTPUT_FIELDS
    assert out["claim_1"]["claim_type"] is None
    assert out["claim_1"]["assay_method_in_paper"] is None
    assert out["claim_1"]["claim"] == "bare"


def test_assay_is_published_under_its_renamed_key():
    """The passes emit `assay`; claims.json publishes `assay_method_in_paper` to say the
    value is the method as the paper words it, not an OBI-mapped identifier. A plain tuple
    rename without the source-key mapping would write null for every claim, which is the
    failure this pins."""
    out = project_claims({"claim_1": _full_claim(assay="Hemagglutination inhibition")})

    assert out["claim_1"]["assay_method_in_paper"] == "Hemagglutination inhibition"
    assert "assay" not in out["claim_1"]


def test_projection_would_starve_pass5_if_applied_before_the_write():
    """run_dedup_audit reads polarity/panel/contrast/targets/timepoints off the in-memory
    claim set, and pass 3 attaches provenance_audit onto each claim. Slimming inside the
    pipeline instead of at the write site would silently break both."""
    pass5_needs = {"polarity", "sample_type", "targets", "timepoints", "contrast", "panel"}
    assert not pass5_needs & set(CLAIMS_OUTPUT_FIELDS)
