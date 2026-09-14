"""Round 5: the OBI term is the assay's identity, and the registry is keyed by it.

Extraction keys by the paper's wording, so one assay described under two Methods subheadings lands
two entries. This round groups by the term round 4 resolved, keys each group by the term's label,
and folds the group into one entry. Deterministic and free -- no model is involved, so the tests
are about the shaping rules and nothing else.

The rule is deliberately coarser than the paper's language: one OBI term covers every ELISA a
paper runs. What keeps that from costing a measurement is that each folded write-up's specimen,
platform, readouts and quote move to `additional_evidence`, so most of what follows is about
nothing being dropped on the way.
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
    "platform": "ELx808 plate reader",
    "sample_type": "serum samples",
    "readouts": "polysaccharide-specific IgG",
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
    """A fold is not a re-extraction: nothing picks field-by-field between two records."""
    merged = merge_entries(ELISA, [ELISA_KITS])

    for field in ("platform", "sample_type", "readouts", "source", "evidence"):
        assert merged[field] == ELISA[field]


def test_each_folded_entrys_whole_record_survives_as_additional_evidence():
    merged = merge_entries(ELISA, [ELISA_KITS])

    assert merged[MERGED_FIELD] == [{
        "name_in_paper": "ELISA kits",
        "platform": "BD Biosciences",
        "sample_type": "Cell supernatants",
        "readouts": "IL-6, TNF and IL-12p40 levels",
        "source": "methods",
        "evidence": ELISA_KITS["evidence"],
    }]


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
