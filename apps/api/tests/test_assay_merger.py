"""Round 5: the OBI term is the assay's identity, and the registry is keyed by it.

Extraction keys by the paper's wording, so one assay described under two Methods subheadings lands
two entries. This round groups by the term round 4 resolved, keys each group by the term's label,
and folds the group into one entry. Deterministic and free -- no model is involved, so the tests
are about the shaping rules and nothing else.

The rule is deliberately coarser than the paper's language: one OBI term covers every ELISA a
paper runs. What keeps that from costing a measurement is that each folded write-up's specimen,
readouts and quote move to `additional_evidence`, so most of what follows is about nothing being
dropped on the way.
"""

from app.agent.assay_extractor import MERGED_FIELD, paper_names, trim_registry
from app.agent.assay_merger import (
    blocked_folds,
    build_merge_report,
    canonical_groups,
    canonicalize_registry,
    merge_entries,
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

    assert report["summary"] == {"groups_merged": 1, "entries_folded": 1, "folds_blocked": 0}
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
    supported, and promoting the doubt made the deliverable say otherwise."""
    merged = merge_entries(ELISA, [{**ELISA_KITS, "identity_review": _REVIEW}])

    assert "identity_review" not in merged
    assert merged["additional_evidence"][0]["identity_review"] == _REVIEW


def test_the_survivors_own_review_wins_and_an_unreviewed_member_gains_no_slot():
    mine = {"verdict": "NOT_REPORTED", "reason": "verification failed"}
    merged = merge_entries({**ELISA, "identity_review": mine}, [ELISA_KITS])

    assert merged["identity_review"] == mine
    assert "identity_review" not in merged["additional_evidence"][0]


# ── the fold rules: same id, neither BROAD, same technique ───────────────────

def _broad(term: dict) -> dict:
    return {**term, "obi_granularity": "BROAD"}


def _exact(term: dict) -> dict:
    return {**term, "obi_granularity": "EXACT"}


def test_grouping_is_by_obi_id_not_by_label_spelling():
    assays = {"a": _tech("a", "flow cytometry"), "b": _tech("b", "flow cytometry")}
    obi = {"a": _FLOW_TERM, "b": {**_FLOW_TERM, "obi_label": "Flow Cytometry Assay"}}

    groups = canonical_groups(assays, obi)

    assert [g["members"] for g in groups] == [["a", "b"]]
    assert groups[0]["key"] == "flow cytometry assay"  # the anchor's spelling


def test_the_same_label_on_two_ids_stays_two_groups():
    assays = {"a": _tech("a", "flow cytometry"), "b": _tech("b", "flow cytometry")}
    obi = {"a": _FLOW_TERM, "b": {**_FLOW_TERM, "obi_id": "OBI:9999999"}}

    groups = canonical_groups(assays, obi)

    assert [g["members"] for g in groups] == [["a"], ["b"]]
    assert [g["key"] for g in groups] == ["flow cytometry assay", "flow cytometry assay (2)"]
    assert blocked_folds(groups) == []  # different terms: nothing was refused, nothing to report


def test_a_broad_mapping_is_kept_apart_and_reported():
    """SDY1640: immunophenotyping and intracellular cytokine staining both on `flow cytometry
    assay`, the ICS as BROAD because no candidate named the function. Folding absorbed the ICS
    into the phenotyping; the curator lists it on its own."""
    assays = {"phenotyping": _tech("phenotyping", "flow cytometry"),
              "ICS": _tech("ICS", "flow cytometry")}
    obi = {"phenotyping": _exact(_FLOW_TERM), "ICS": _broad(_FLOW_TERM)}

    groups = canonical_groups(assays, obi)

    assert [(g["key"], g["members"]) for g in groups] == [
        ("flow cytometry assay", ["phenotyping"]), ("flow cytometry assay (2)", ["ICS"])]
    assert blocked_folds(groups) == [{
        "member": "ICS", "kept_apart_from": "flow cytometry assay", "anchor": "phenotyping",
        "obi_id": "OBI:0000916", "obi_label": "flow cytometry assay", "reason": "mapping is BROAD"}]
    merged, obi_out, folds = canonicalize_registry(assays, obi)
    assert folds == []
    assert list(merged) == ["flow cytometry assay", "flow cytometry assay (2)"]
    assert merged["flow cytometry assay (2)"]["name_in_paper"] == ["ICS"]
    assert obi_out["flow cytometry assay (2)"]["obi_granularity"] == "BROAD"


def test_nothing_folds_onto_a_broad_anchor_either():
    assays = {"ICS": _tech("ICS", "flow cytometry"),
              "phenotyping": _tech("phenotyping", "flow cytometry")}
    obi = {"ICS": _broad(_FLOW_TERM), "phenotyping": _exact(_FLOW_TERM)}

    groups = canonical_groups(assays, obi)

    assert [g["members"] for g in groups] == [["ICS"], ["phenotyping"]]
    assert [b["member"] for b in blocked_folds(groups)] == ["phenotyping"]


def test_two_techniques_on_one_term_stay_two_entries():
    """SDY1264: a cytopathic-effect test and a plaque-reduction test both resolved to `serum
    neutralization of viral infectivity assay`."""
    term = {"obi_id": "OBI:0000872", "obi_label": "serum neutralization of viral infectivity assay"}
    assays = {"CPE": _tech("CPE", "cytopathic effect neutralization assay"),
              "PRNT": _tech("PRNT", "plaque reduction neutralization test")}

    groups = canonical_groups(assays, {"CPE": _exact(term), "PRNT": _exact(term)})

    assert [g["members"] for g in groups] == [["CPE"], ["PRNT"]]
    [blocked] = blocked_folds(groups)
    assert blocked["member"] == "PRNT"
    assert blocked["reason"] == ("standard_technique_name differs: "
                                 "'cytopathic effect neutralization assay' vs "
                                 "'plaque reduction neutralization test'")


def test_an_empty_technique_on_one_side_still_folds():
    assays = {"ELISA": _tech("ELISA", "enzyme-linked immunosorbent assay"),
              "ELISA kits": _tech("ELISA kits", None)}

    groups = canonical_groups(assays, {"ELISA": _exact(_ELISA_TERM), "ELISA kits": _exact(_ELISA_TERM)})

    assert [g["members"] for g in groups] == [["ELISA", "ELISA kits"]]
    assert blocked_folds(groups) == []


def test_the_same_technique_spelt_differently_still_folds():
    assays = {"a": _tech("a", "Flow Cytometry"), "b": _tech("b", "flow cytometry assay")}

    groups = canonical_groups(assays, {"a": _FLOW_TERM, "b": _FLOW_TERM})

    assert [g["members"] for g in groups] == [["a", "b"]]


def test_a_refused_entry_lands_on_its_own_key_in_the_key_map():
    from app.agent.assay_merger import key_map
    assays = {"phenotyping": _tech("phenotyping", "flow cytometry"),
              "ICS": _tech("ICS", "flow cytometry")}
    obi = {"phenotyping": _exact(_FLOW_TERM), "ICS": _broad(_FLOW_TERM)}

    assert key_map(assays, obi) == {"phenotyping": "flow cytometry assay",
                                    "ICS": "flow cytometry assay (2)"}


def test_the_report_carries_the_blocked_folds():
    blocked = [{"member": "ICS", "kept_apart_from": "flow cytometry assay", "anchor": "phenotyping",
                "obi_id": "OBI:0000916", "obi_label": "flow cytometry assay",
                "reason": "mapping is BROAD"}]

    report = build_merge_report([], blocked=blocked)

    assert report["summary"] == {"groups_merged": 0, "entries_folded": 0, "folds_blocked": 1}
    assert report["blocked"] == blocked
    assert build_merge_report([])["blocked"] == []
