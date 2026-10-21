"""Round 5: the OBI term is the assay's identity, and the registry is keyed by it.

Extraction keys by the paper's wording, so one assay described under two Methods subheadings lands
two entries. This round groups by the term round 4 resolved, keys each group by the term's label,
and folds what a judge confirms is one measurement. The judge itself is tested in
test_assay_fold_judge.py; here it is a partition handed in, so the tests are about the shaping
rules and nothing else -- deterministic given the partition.

A shared term makes entries candidates, not one assay: 12 of the 18 folds on the 31-paper run
merged different measurements. What keeps a confirmed fold from costing a measurement is that
each folded write-up's specimen, readouts and quote move to `additional_evidence`, so much of
what follows is about nothing being dropped on the way.
"""

from app.agent.assay_extractor import KEY_SEP, MERGED_FIELD, paper_names, trim_registry
from app.agent.assay_merger import (
    JUDGE_FAILED,
    KEPT_APART,
    build_merge_report,
    canonical_groups,
    canonicalize_registry,
    fold_candidates,
    judge_failed,
    kept_apart,
    key_map,
    merge_entries,
    review_unfolded,
)

ELISA = {
    "name_in_paper": "ELISA",
    "aliases": [],
    # An older registry's field: the extraction no longer produces it, and a fold must not choke
    # on one that is still on disk. It is simply not carried onto the survivor.
    "platform": "ELx808 plate reader",
    "sample_type": "serum samples",
    "readouts": "polysaccharide-specific IgG",
    "generate_claim": True,
    "source": "methods",
    "evidence": {"section": "Measurement of anti-Meningococcal antibodies by ELISA",
                 "sentence_ids": ["S1"], "quote": "Serum titers were measured by ELISA."},
}

ELISA_KITS = {
    "name_in_paper": "ELISA kits",
    "aliases": ["ELISA"],
    "platform": "BD Biosciences",
    "sample_type": "Cell supernatants",
    "readouts": "IL-6, TNF and IL-12p40 levels",
    "generate_claim": False,
    "source": "methods",
    "evidence": {"section": "In vitro DC activation", "sentence_ids": ["S2"],
                 "quote": "Supernatants were assessed for IL-6 using ELISA kits."},
}

FLOW = {
    "name_in_paper": "flow cytometry",
    "aliases": ["FACS"],
    "platform": "BD LSRFortessa",
    "sample_type": "PBMCs",
    "readouts": "cell frequencies",
    "source": "methods",
    "evidence": {"section": "Methods", "sentence_ids": ["S3"], "quote": "…"},
}

SBA = {
    "name_in_paper": "serum bactericidal titers (SBA)",
    "aliases": ["SBA"],
    "platform": None, "sample_type": "sera", "readouts": "bactericidal titer",
    "source": "methods",
    "evidence": {"section": "Measurement of SBA", "sentence_ids": ["S4"], "quote": "…"},
}

_ELISA_TERM = {"obi_id": "OBI:0000661", "obi_label": "enzyme-linked immunosorbent assay"}
_FLOW_TERM = {"obi_id": "OBI:0000916", "obi_label": "flow cytometry assay"}
_NO_TERM = {"obi_id": None, "obi_label": None, "resource": "unresolved"}


# ── grouping ─────────────────────────────────────────────────────────────────


def test_entries_on_one_term_form_one_group_in_registry_order():
    groups = canonical_groups(
        {"ELISA": ELISA, "flow cytometry": FLOW, "ELISA kits": ELISA_KITS},
        {"ELISA": _ELISA_TERM, "flow cytometry": _FLOW_TERM, "ELISA kits": _ELISA_TERM})

    assert [(g["key"], g["members"]) for g in groups] == [
        ("enzyme-linked immunosorbent assay", ["ELISA", "ELISA kits"]),
        ("flow cytometry assay", ["flow cytometry"]),
    ]


def test_an_unmapped_entry_is_its_own_group_under_its_paper_name():
    """Two assays OBI has no term for have nothing in common except that gap."""
    groups = canonical_groups(
        {"serum bactericidal titers (SBA)": SBA, "flow cytometry": FLOW},
        {"serum bactericidal titers (SBA)": _NO_TERM, "flow cytometry": _FLOW_TERM})

    assert [g["key"] for g in groups] == ["serum bactericidal titers (SBA)", "flow cytometry assay"]
    assert all(len(g["members"]) == 1 for g in groups)


def test_a_registry_with_no_mapping_at_all_keeps_every_paper_name():
    groups = canonical_groups({"ELISA": ELISA, "ELISA kits": ELISA_KITS}, obi=None)

    assert [g["key"] for g in groups] == ["ELISA", "ELISA kits"]


# ── merge shaping ────────────────────────────────────────────────────────────


def test_every_wording_becomes_a_name_winner_first():
    merged = merge_entries(ELISA, [ELISA_KITS])

    assert merged["name_in_paper"] == ["ELISA", "ELISA kits"]


def test_an_alias_that_repeats_a_name_is_dropped_from_aliases():
    """`ELISA kits` lists "ELISA" as an alias, which is now the entry's own first name."""
    merged = merge_entries(ELISA, [ELISA_KITS])

    assert merged["aliases"] == []


def test_aliases_that_are_not_names_are_kept_and_unioned():
    other = {**FLOW, "name_in_paper": "flow cytometric analysis", "aliases": ["FACS", "cytometry"]}
    merged = merge_entries(FLOW, [other])

    assert merged["name_in_paper"] == ["flow cytometry", "flow cytometric analysis"]
    assert merged["aliases"] == ["FACS", "cytometry"]


def test_the_first_entrys_own_fields_are_untouched():
    """A fold is not a re-extraction: nothing picks field-by-field between two records.

    `generate_claim` is the one exception, and is tested separately below: it describes the assay
    rather than the write-up, so it is the one field a fold has to decide.
    """
    merged = merge_entries(ELISA, [ELISA_KITS])

    for field in ("sample_type", "readouts", "source", "evidence"):
        assert merged[field] == ELISA[field]


def test_each_folded_entrys_whole_record_survives_as_additional_evidence():
    merged = merge_entries(ELISA, [ELISA_KITS])

    assert merged[MERGED_FIELD] == [{
        "name_in_paper": "ELISA kits",
        "sample_type": "Cell supernatants",
        "readouts": "IL-6, TNF and IL-12p40 levels",
        # Kept on the member because the survivor's value is the fold's: without this, a member's
        # own answer would be the one thing the fold destroyed rather than recorded.
        "generate_claim": False,
        "source": "methods",
        "evidence": ELISA_KITS["evidence"],
    }]


def test_a_fold_reports_a_finding_when_any_member_did():
    """Two wordings of one assay are one assay, so a finding drawn from either was drawn from it.

    The winner is the `False` one here on purpose: taking the survivor's value would lose the
    finding the other member recorded, and the survivor is chosen by registry order, not by what
    it says.
    """
    merged = merge_entries({**ELISA, "generate_claim": False},
                           [{**ELISA_KITS, "generate_claim": True}])

    assert merged["generate_claim"] is True


def test_a_fold_reports_no_finding_only_when_no_member_did():
    merged = merge_entries({**ELISA, "generate_claim": False},
                           [{**ELISA_KITS, "generate_claim": None}])

    assert merged["generate_claim"] is False


def test_a_fold_of_unanswered_entries_stays_unanswered():
    """An old registry on disk carries the field nowhere. Re-canonicalizing one must not turn
    "nobody said" into "the paper drew nothing from it"."""
    merged = merge_entries({k: v for k, v in ELISA.items() if k != "generate_claim"},
                           [{k: v for k, v in ELISA_KITS.items() if k != "generate_claim"}])

    assert merged["generate_claim"] is None


def test_three_entries_on_one_term_leave_two_evidence_blocks():
    third = {**ELISA, "name_in_paper": "ELISA assays",
             "evidence": {"section": "Serology", "sentence_ids": ["S5"], "quote": "…"}}

    merged = merge_entries(ELISA, [ELISA_KITS, third])

    assert len(merged[MERGED_FIELD]) == 2
    # "ELISA assays" normalizes to "elisa", which is already a name -- the wording is not repeated.
    assert merged["name_in_paper"] == ["ELISA", "ELISA kits"]


def test_canonicalizing_twice_keeps_the_blocks_the_first_pass_wrote():
    once, _, _ = canonicalize_registry({"ELISA": ELISA, "ELISA kits": ELISA_KITS},
                                       {"ELISA": _ELISA_TERM, "ELISA kits": _ELISA_TERM})
    obi = {"enzyme-linked immunosorbent assay": _ELISA_TERM}

    twice, _, folds = canonicalize_registry(once, obi)

    assert twice == once
    assert folds == []


# ── whole-registry canonicalization ──────────────────────────────────────────


def test_the_registry_is_rekeyed_by_obi_label_and_the_duplicate_is_gone():
    assays = {"ELISA": ELISA, "ELISA kits": ELISA_KITS, "flow cytometry": FLOW}
    obi = {"ELISA": _ELISA_TERM, "ELISA kits": _ELISA_TERM, "flow cytometry": _FLOW_TERM}

    merged, obi_out, folds = canonicalize_registry(assays, obi)

    assert list(merged) == ["enzyme-linked immunosorbent assay", "flow cytometry assay"]
    # The mapping is re-keyed identically: the three files are looked up across each other.
    assert list(obi_out) == list(merged)
    assert folds[0]["folded"] == ["ELISA kits"]
    assert folds[0]["obi_id"] == "OBI:0000661"
    # The inputs are not mutated.
    assert list(assays) == ["ELISA", "ELISA kits", "flow cytometry"]


def test_name_in_paper_is_a_list_even_when_nothing_folded():
    """A field whose type depends on whether a fold happened is one every reader must branch on."""
    merged, _, folds = canonicalize_registry({"flow cytometry": FLOW}, {"flow cytometry": _FLOW_TERM})

    assert folds == []
    assert merged["flow cytometry assay"]["name_in_paper"] == ["flow cytometry"]
    assert paper_names(merged["flow cytometry assay"]) == ["flow cytometry"]


def test_an_unmapped_entry_keeps_its_paper_name_as_its_key():
    merged, obi_out, _ = canonicalize_registry(
        {"serum bactericidal titers (SBA)": SBA}, {"serum bactericidal titers (SBA)": _NO_TERM})

    assert list(merged) == ["serum bactericidal titers (SBA)"]
    assert list(obi_out) == ["serum bactericidal titers (SBA)"]


def test_the_mapping_carries_the_merged_names_not_just_the_one_it_looked_up():
    _, obi_out, _ = canonicalize_registry({"ELISA": ELISA, "ELISA kits": ELISA_KITS},
                                          {"ELISA": _ELISA_TERM, "ELISA kits": _ELISA_TERM})

    entry = obi_out["enzyme-linked immunosorbent assay"]
    assert entry["name_in_paper"] == ["ELISA", "ELISA kits"]
    assert entry["obi_id"] == "OBI:0000661"


def test_without_a_mapping_nothing_is_rekeyed_and_nothing_folds():
    """The honest degradation when round 4 failed: there is nothing to key on."""
    merged, obi_out, folds = canonicalize_registry({"ELISA": ELISA, "ELISA kits": ELISA_KITS}, None)

    assert list(merged) == ["ELISA", "ELISA kits"]
    assert obi_out is None
    assert folds == []


def test_the_deliverable_shows_one_entry_with_both_wordings_and_both_quotes():
    merged, _, _ = canonicalize_registry({"ELISA": ELISA, "ELISA kits": ELISA_KITS},
                                         {"ELISA": _ELISA_TERM, "ELISA kits": _ELISA_TERM})

    trimmed = trim_registry(merged)["enzyme-linked immunosorbent assay"]

    assert trimmed["name_in_paper"] == ["ELISA", "ELISA kits"]
    assert trimmed["evidence"]["section"] == "Measurement of anti-Meningococcal antibodies by ELISA"
    assert trimmed[MERGED_FIELD][0]["evidence"]["section"] == "In vitro DC activation"


def test_the_report_counts_groups_and_entries():
    _, _, folds = canonicalize_registry({"ELISA": ELISA, "ELISA kits": ELISA_KITS, "flow": FLOW},
                                        {"ELISA": _ELISA_TERM, "ELISA kits": _ELISA_TERM,
                                         "flow": _FLOW_TERM})

    report = build_merge_report(folds)

    assert report["summary"] == {"groups_merged": 1, "entries_folded": 1,
                                 "review_unfolded": [], "kept_apart": [], "judge_failed": []}
    assert report["results"][0]["key"] == "enzyme-linked immunosorbent assay"

# ── a shared technique never links ───────────────────────────────────────────

_RNASEQ_TERM = {"obi_id": "OBI:0001271", "obi_label": "RNA-seq assay"}
_BULK_TERM = {"obi_id": "OBI:0003090", "obi_label": "bulk RNA-seq assay"}
_AIM_TERM = {"obi_id": "OBI:0003230", "obi_label": "T cell activation induced marker assay"}


def _tech(name: str, technique: str | None) -> dict:
    return {**FLOW, "name_in_paper": name, "aliases": [], "standard_technique_name": technique}


def test_same_technique_on_different_terms_stays_two_assays():
    assays = {"RNA-seq": _tech("RNA-seq", "RNA sequencing"),
              "bulk RNA-seq": _tech("bulk RNA-seq", "RNA sequencing")}
    groups = canonical_groups(assays, {"RNA-seq": _RNASEQ_TERM, "bulk RNA-seq": _BULK_TERM})

    assert [g["key"] for g in groups] == ["RNA-seq assay", "bulk RNA-seq assay"]
    assert [g["members"] for g in groups] == [["RNA-seq"], ["bulk RNA-seq"]]


def test_a_shared_instrument_never_joins_two_different_terms():
    """SDY1640: three flow-cytometry experiments, one of them an AIM assay with its own term.
    The shared instrument used to fold the AIM assay into the immunophenotyping."""
    assays = {"phenotyping": _tech("phenotyping", "flow cytometry"),
              "AIM assay": _tech("AIM assay", "flow cytometry"),
              "ICS": _tech("ICS", "flow cytometry")}
    obi = {"phenotyping": _FLOW_TERM, "AIM assay": _AIM_TERM, "ICS": _FLOW_TERM}

    groups = canonical_groups(assays, obi)

    assert [(g["key"], g["members"]) for g in groups] == [
        ("flow cytometry assay", ["phenotyping", "ICS"]),
        ("T cell activation induced marker assay", ["AIM assay"]),
    ]


def test_an_unmapped_entry_is_never_folded_onto_a_sibling_sharing_its_technique():
    """SDY1328: `multiplex ELISA` had no term and shared "ELISA" as its technique with the
    paper's plate ELISA, so it was folded into OBI:0000661 -- the one case the resolver's own
    rule says is a different assay (a bead-based multiplex). An unmapped entry stays its own
    entry, under its own wording, where UNMAPPED can be reported for it."""
    assays = {"ELISA": _tech("ELISA", "ELISA"),
              "multiplex ELISA": _tech("multiplex ELISA", "ELISA")}
    obi = {"ELISA": _ELISA_TERM, "multiplex ELISA": _NO_TERM}

    merged, obi_out, folds = canonicalize_registry(assays, obi)

    assert list(merged) == ["enzyme-linked immunosorbent assay", "multiplex ELISA"]
    assert merged["multiplex ELISA"]["name_in_paper"] == ["multiplex ELISA"]
    assert obi_out["multiplex ELISA"]["obi_id"] is None
    assert folds == []


def test_an_unmapped_entry_between_two_terms_stays_alone():
    assays = {"flow": _tech("flow", "flow cytometry"), "U": _tech("U", "flow cytometry"),
              "AIM": _tech("AIM", "flow cytometry")}
    obi = {"flow": _FLOW_TERM, "U": _NO_TERM, "AIM": _AIM_TERM}

    assert [g["members"] for g in canonical_groups(assays, obi)] == [["flow"], ["U"], ["AIM"]]


def test_two_unmapped_entries_on_one_technique_stay_two_assays():
    """A CFSE assay and an ICS panel OBI happened to miss are not one assay for sharing a
    cytometer."""
    assays = {"CFSE": _tech("CFSE", "flow cytometry"), "ICS": _tech("ICS", "flow cytometry")}

    groups = canonical_groups(assays, {k: _NO_TERM for k in assays})

    assert [(g["key"], g["members"]) for g in groups] == [("CFSE", ["CFSE"]), ("ICS", ["ICS"])]


def test_a_technique_on_the_obi_record_does_not_link_either():
    assays = {"A": _tech("A", None), "B": _tech("B", None)}
    obi = {"A": {**_NO_TERM, "standard_technique_name": "ELISA"},
           "B": {**_NO_TERM, "standard_technique_name": "elisa"}}

    assert [g["members"] for g in canonical_groups(assays, obi)] == [["A"], ["B"]]


def test_the_report_lists_each_members_own_label():
    assays = {"ELISA": _tech("ELISA", "ELISA"), "ELISA kits": _tech("ELISA kits", "ELISA")}

    _, _, folds = canonicalize_registry(assays, {"ELISA": _ELISA_TERM, "ELISA kits": _ELISA_TERM})

    assert folds[0]["member_labels"] == {"ELISA": "enzyme-linked immunosorbent assay",
                                         "ELISA kits": "enzyme-linked immunosorbent assay"}


# ── the identity review travels with the fold ────────────────────────────────

_REVIEW = {"verdict": "NOT_SUPPORTED", "reason": "a section heading"}


def test_a_folded_members_review_stays_in_its_block_and_is_not_promoted():
    """SDY1260: the judge doubted "ELISA kits" as a name; the ELISA it folded into was
    supported, and promoting the doubt made the deliverable say otherwise. The pipeline no
    longer folds a marked entry at all (canonical_groups); this is merge_entries' own contract,
    which a registry folded before that rule still relies on."""
    merged = merge_entries(ELISA, [{**ELISA_KITS, "identity_review": _REVIEW}])

    assert "identity_review" not in merged
    assert merged["additional_evidence"][0]["identity_review"] == _REVIEW


def test_the_survivors_own_review_wins_and_an_unreviewed_member_gains_no_slot():
    mine = {"verdict": "NOT_REPORTED", "reason": "verification failed"}
    merged = merge_entries({**ELISA, "identity_review": mine}, [ELISA_KITS])

    assert merged["identity_review"] == mine
    assert "identity_review" not in merged["additional_evidence"][0]


# ── granularity plays no part in a fold ──────────────────────────────────────

def test_a_broad_mapping_folds_like_an_exact_one():
    """A rule keeping BROAD mappings apart was tried and withdrawn: the picker's BROAD/EXACT
    label is not stable (SDY2189's two FRNT write-ups came back EXACT in one run and BROAD in
    the next, splitting one assay in two). Same term, one assay, whatever the granularity."""
    for granularity in ("BROAD", "EXACT", None):
        assays = {"flow cytometry": FLOW, "ICS": _tech("ICS", "flow cytometry")}
        obi = {"flow cytometry": _FLOW_TERM, "ICS": {**_FLOW_TERM, "obi_granularity": granularity}}

        merged, _, folds = canonicalize_registry(assays, obi)

        assert list(merged) == ["flow cytometry assay"], granularity
        assert len(folds) == 1


# ── a reviewed identity is never folded ──────────────────────────────────────

def test_a_reviewed_entry_is_never_folded_onto_a_sibling():
    """SDY1260: the judge doubted "ELISA kits" as a name. Folded onto the supported ELISA, its
    wording became that entry's second name and its mark sank into additional_evidence."""
    assays = {"ELISA": ELISA, "ELISA kits": {**ELISA_KITS, "identity_review": _REVIEW}}
    obi = {"ELISA": _ELISA_TERM, "ELISA kits": _ELISA_TERM}

    merged, obi_out, folds = canonicalize_registry(assays, obi)

    assert list(merged) == ["enzyme-linked immunosorbent assay", "ELISA kits"]
    assert merged["enzyme-linked immunosorbent assay"]["name_in_paper"] == ["ELISA"]
    assert "additional_evidence" not in merged["enzyme-linked immunosorbent assay"]
    assert merged["ELISA kits"]["identity_review"] == _REVIEW
    assert obi_out["ELISA kits"]["obi_id"] == "OBI:0000661"
    assert folds == []


def test_a_reviewed_first_entry_does_not_absorb_its_siblings():
    assays = {"ELISA": {**ELISA, "identity_review": _REVIEW}, "ELISA kits": ELISA_KITS}
    obi = {"ELISA": _ELISA_TERM, "ELISA kits": _ELISA_TERM}

    merged, _, folds = canonicalize_registry(assays, obi)

    assert list(merged) == ["ELISA", "enzyme-linked immunosorbent assay"]
    assert merged["enzyme-linked immunosorbent assay"]["name_in_paper"] == ["ELISA kits"]
    assert folds == []


def test_the_report_lists_reviewed_entries_left_unfolded():
    assays = {"ELISA": ELISA, "ELISA kits": {**ELISA_KITS, "identity_review": _REVIEW}}
    obi = {"ELISA": _ELISA_TERM, "ELISA kits": _ELISA_TERM}

    assert review_unfolded(assays, obi) == ["ELISA kits"]
    report = build_merge_report([], key_map(assays, obi), review_unfolded(assays, obi))
    assert report["summary"]["review_unfolded"] == ["ELISA kits"]


# ── the judge's partition decides what folds ─────────────────────────────────
#
# SDY1630's three flow entries, all mapped to one term. The stimulation assay has its own
# stimulation step and measures IFN-γ, not surface markers; the rule folded it anyway.

_PHENO = {**FLOW, "name_in_paper": "Flow cytometry analysis and cell sorting", "aliases": [],
          "sample_type": None, "readouts": "cell surface marker expression on NK cells"}
_HIGHDIM = {**FLOW, "name_in_paper": "High-dimensional parameter flow cytometric analysis of NK "
                                     "cell subsets",
            "aliases": [], "sample_type": None, "readouts": "high-parameter NK cell marker profiles"}
_STIM = {**FLOW, "name_in_paper": "In vitro cytokine stimulation and functional assays of NK cells",
         "aliases": [], "sample_type": "PBMCs",
         "readouts": "intracellular IFN-γ production after cytokine stimulation",
         "evidence": {"section": "In vitro cytokine stimulation", "sentence_ids": ["S52"],
                      "quote": "PBMCs were stimulated with IL-12 and IL-18."}}
_SDY1630 = {"pheno": _PHENO, "highdim": _HIGHDIM, "stim": _STIM}
_SDY1630_OBI = {key: _FLOW_TERM for key in _SDY1630}
_SPLIT = {"flow cytometry assay": [["pheno", "highdim"], ["stim"]]}
_STIM_KEY = ("flow cytometry assay" + KEY_SEP
             + "In vitro cytokine stimulation and functional assays of NK cells")


def test_a_judged_split_keeps_the_stimulation_assay_out_of_the_phenotyping():
    merged, obi_out, folds = canonicalize_registry(_SDY1630, _SDY1630_OBI, _SPLIT)

    assert list(merged) == ["flow cytometry assay", _STIM_KEY]
    assert merged["flow cytometry assay"]["name_in_paper"] == [_PHENO["name_in_paper"],
                                                               _HIGHDIM["name_in_paper"]]
    assert merged[_STIM_KEY]["name_in_paper"] == [_STIM["name_in_paper"]]
    assert "additional_evidence" not in merged[_STIM_KEY]
    # The one confirmed fold is the report's; the kept-apart entry is not a fold.
    assert [(f["key"], f["folded"]) for f in folds] == [("flow cytometry assay", ["highdim"])]


def test_a_split_off_entry_keeps_the_term_and_says_why_it_stands_alone():
    """Kept apart is not unmapped: the entry is still a flow cytometry assay, under the same
    OBI id, and the mapping says so under the composite key."""
    groups = canonical_groups(_SDY1630, _SDY1630_OBI, _SPLIT)
    _, obi_out, _ = canonicalize_registry(_SDY1630, _SDY1630_OBI, _SPLIT)

    assert [(g["key"], g["members"], g["alone"]) for g in groups] == [
        ("flow cytometry assay", ["pheno", "highdim"], None),
        (_STIM_KEY, ["stim"], KEPT_APART)]
    assert KEPT_APART == "kept_apart"
    assert list(obi_out) == ["flow cytometry assay", _STIM_KEY]
    assert obi_out[_STIM_KEY]["obi_id"] == obi_out["flow cytometry assay"]["obi_id"] == "OBI:0000916"
    assert obi_out[_STIM_KEY]["obi_label"] == "flow cytometry assay"


def test_no_partition_is_todays_fold_byte_for_byte():
    """`None` and `{}` both mean "nobody judged": the term alone folds, exactly as before the
    judge existed. This is the path every caller that asks no judge is on."""
    before = canonicalize_registry(_SDY1630, _SDY1630_OBI)

    assert canonicalize_registry(_SDY1630, _SDY1630_OBI, None) == before
    assert canonicalize_registry(_SDY1630, _SDY1630_OBI, {}) == before
    assert list(before[0]) == ["flow cytometry assay"]
    assert canonical_groups(_SDY1630, _SDY1630_OBI, {}) == canonical_groups(_SDY1630, _SDY1630_OBI)


def test_a_failed_judgement_keeps_every_member_apart_and_folds_nothing():
    """A fold is irreversible and a split is not, so a group the judge could not rule on stays
    as the extractor left it: singletons, the first still under the bare label."""
    merged, obi_out, folds = canonicalize_registry(_SDY1630, _SDY1630_OBI,
                                                   {"flow cytometry assay": None})

    assert list(merged) == ["flow cytometry assay",
                            "flow cytometry assay" + KEY_SEP + _HIGHDIM["name_in_paper"],
                            _STIM_KEY]
    assert folds == []
    assert all(g["alone"] == JUDGE_FAILED == "judge_failed"
               for g in canonical_groups(_SDY1630, _SDY1630_OBI, {"flow cytometry assay": None}))
    assert all(v["obi_id"] == "OBI:0000916" for v in obi_out.values())


def test_the_report_always_carries_both_lists():
    report = build_merge_report([])

    assert report["summary"]["kept_apart"] == []
    assert report["summary"]["judge_failed"] == []
    assert "judge" not in report


def test_kept_apart_and_judge_failed_read_the_partition():
    assert kept_apart(_SDY1630, _SDY1630_OBI, _SPLIT) == [_STIM_KEY]
    assert judge_failed(_SDY1630, _SDY1630_OBI, _SPLIT) == []
    assert kept_apart(_SDY1630, _SDY1630_OBI, {"flow cytometry assay": None}) == []
    # Deduped: three singletons, one label.
    assert judge_failed(_SDY1630, _SDY1630_OBI, {"flow cytometry assay": None}) == [
        "flow cytometry assay"]
    assert kept_apart(_SDY1630, _SDY1630_OBI) == judge_failed(_SDY1630, _SDY1630_OBI) == []


def test_the_report_carries_the_judges_reason_when_given():
    records = [{"label": "flow cytometry assay", "members": list(_SDY1630),
                "groups": _SPLIT["flow cytometry assay"], "reason": "its own stimulation step",
                "error": None}]

    report = build_merge_report([], key_map(_SDY1630, _SDY1630_OBI, _SPLIT),
                                review_unfolded(_SDY1630, _SDY1630_OBI, _SPLIT),
                                kept_apart(_SDY1630, _SDY1630_OBI, _SPLIT),
                                judge_failed(_SDY1630, _SDY1630_OBI, _SPLIT), records)

    assert report["summary"]["kept_apart"] == [_STIM_KEY]
    assert report["judge"] == records


def test_the_key_map_sends_the_stimulation_member_to_the_composite_key():
    assert key_map(_SDY1630, _SDY1630_OBI, _SPLIT) == {
        "pheno": "flow cytometry assay", "highdim": "flow cytometry assay", "stim": _STIM_KEY}


def test_colliding_first_wordings_are_suffixed_not_overwritten():
    """Two kept-apart sets whose first members share a wording would land on one composite key;
    the second is suffixed, as a stand-alone entry colliding with a label already was."""
    assays = {"a": {**FLOW, "name_in_paper": "ICS"}, "b": {**FLOW, "name_in_paper": "ICS"},
              "c": {**FLOW, "name_in_paper": "ICS"}}
    obi = {k: _FLOW_TERM for k in assays}

    merged, _, _ = canonicalize_registry(assays, obi,
                                         {"flow cytometry assay": [["a"], ["b"], ["c"]]})

    assert list(merged) == ["flow cytometry assay", "flow cytometry assay" + KEY_SEP + "ICS",
                            "flow cytometry assay" + KEY_SEP + "ICS (2)"]


def test_fold_candidates_are_the_multi_member_label_groups_only():
    """Singletons have nothing to judge; a reviewed entry and an unmapped one stand alone before
    any judge is asked, so neither is a candidate."""
    assays = {**_SDY1630, "kits": {**ELISA_KITS, "identity_review": _REVIEW}, "sba": SBA,
              "elisa": ELISA}
    obi = {**_SDY1630_OBI, "kits": _ELISA_TERM, "sba": _NO_TERM, "elisa": _ELISA_TERM}

    candidates = fold_candidates(assays, obi)

    assert [(g["obi_label"], g["members"]) for g in candidates] == [
        ("flow cytometry assay", ["pheno", "highdim", "stim"])]
    assert fold_candidates({"pheno": _PHENO}, {"pheno": _FLOW_TERM}) == []
