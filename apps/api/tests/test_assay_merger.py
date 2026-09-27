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

    assert report["summary"] == {"groups_merged": 1, "entries_folded": 1}
    assert report["results"][0]["key"] == "enzyme-linked immunosorbent assay"

# ── linking on normalized_name ───────────────────────────────────────────────

_RNASEQ_TERM = {"obi_id": "OBI:0001271", "obi_label": "RNA-seq assay"}
_BULK_TERM = {"obi_id": "OBI:0003090", "obi_label": "bulk RNA-seq assay"}


def _tech(name: str, technique: str | None) -> dict:
    return {**FLOW, "name_in_paper": name, "aliases": [], "normalized_name": technique}


def test_same_technique_on_different_terms_folds_under_the_first_mapped_label():
    assays = {"RNA-seq": _tech("RNA-seq", "RNA sequencing"),
              "bulk RNA-seq": _tech("bulk RNA-seq", "RNA sequencing")}
    groups = canonical_groups(assays, {"RNA-seq": _RNASEQ_TERM, "bulk RNA-seq": _BULK_TERM})

    assert len(groups) == 1
    assert groups[0]["key"] == "RNA-seq assay"
    assert groups[0]["members"] == ["RNA-seq", "bulk RNA-seq"]


def test_an_unmapped_entry_joins_the_mapped_one_that_shares_its_technique():
    """The case the link exists for: a protocol-section name OBI could not resolve."""
    assays = {"Whole transcriptome profiling of NK cell subsets":
                  _tech("Whole transcriptome profiling of NK cell subsets", "RNA sequencing"),
              "RNA-seq": _tech("RNA-seq", "RNA sequencing")}
    obi = {"Whole transcriptome profiling of NK cell subsets": _NO_TERM, "RNA-seq": _RNASEQ_TERM}

    merged, obi_out, folds = canonicalize_registry(assays, obi)

    assert list(merged) == ["RNA-seq assay"]
    # The unmapped entry came first, so its fields survive; the term comes from the mapped one.
    assert merged["RNA-seq assay"]["name_in_paper"][0] == \
        "Whole transcriptome profiling of NK cell subsets"
    assert obi_out["RNA-seq assay"]["obi_id"] == "OBI:0001271"
    assert folds[0]["obi_label"] == "RNA-seq assay"


def test_links_chain_across_term_and_technique():
    """A~B on the term, B~C on the technique: one assay, not two."""
    assays = {"A": _tech("A", None), "B": _tech("B", "RNA sequencing"),
              "C": _tech("C", "RNA sequencing")}
    obi = {"A": _RNASEQ_TERM, "B": _RNASEQ_TERM, "C": _NO_TERM}

    groups = canonical_groups(assays, obi)

    assert [g["members"] for g in groups] == [["A", "B", "C"]]


def test_a_missing_or_blank_technique_never_links():
    assays = {"A": _tech("A", None), "B": _tech("B", None), "C": _tech("C", "  ")}

    groups = canonical_groups(assays, {k: _NO_TERM for k in assays})

    assert [g["members"] for g in groups] == [["A"], ["B"], ["C"]]


def test_technique_matching_ignores_case_and_spacing():
    assays = {"A": _tech("A", "Flow  Cytometry"), "B": _tech("B", "flow cytometry")}

    groups = canonical_groups(assays, None)

    assert [g["members"] for g in groups] == [["A", "B"]]
    assert groups[0]["key"] == "A"


def test_the_report_lists_each_members_own_label():
    assays = {"RNA-seq": _tech("RNA-seq", "RNA sequencing"),
              "bulk RNA-seq": _tech("bulk RNA-seq", "RNA sequencing")}

    _, _, folds = canonicalize_registry(
        assays, {"RNA-seq": _RNASEQ_TERM, "bulk RNA-seq": _BULK_TERM})

    assert folds[0]["member_labels"] == {"RNA-seq": "RNA-seq assay",
                                         "bulk RNA-seq": "bulk RNA-seq assay"}


def test_the_technique_can_come_from_the_obi_record():
    """The mapper carries normalized_name on its own output; either source links."""
    assays = {"A": _tech("A", None), "B": _tech("B", None)}
    obi = {"A": {**_NO_TERM, "normalized_name": "ELISA"},
           "B": {**_NO_TERM, "normalized_name": "elisa"}}

    assert [g["members"] for g in canonical_groups(assays, obi)] == [["A", "B"]]
