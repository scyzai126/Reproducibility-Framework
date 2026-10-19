"""The claim -> assay registry join and its gap triage. Deterministic: nothing is called."""

import json

from app.agent.claim_assay_linker import finding_sentences, link_claims, load_registry


def _entry(names, aliases=(), generate_claim=True, **extra) -> dict:
    return {"name_in_paper": list(names), "aliases": list(aliases),
            "generate_claim": generate_claim, "sample_type": "", **extra}


def _claim(assay, text="...", quote="") -> dict:
    return {"claim": text, "assay_method_in_paper": assay,
            "sources": [{"type": "text", "quote": quote}] if quote else []}


# A registry in its round-5 shape: keyed by OBI label, the paper's wordings kept as names.
REGISTRY = {
    "enzyme-linked immunosorbent assay": _entry(
        ["IgG ELISA"], aliases=["ELISA"], obi_id="OBI:0000661",
        obi_label="enzyme-linked immunosorbent assay", sample_type="serum"),
    "cytometric bead array assay": _entry(
        ["Multiplex analysis"], aliases=["24-plex Luminex assay"], standard_technique_name="Luminex"),
    "flow cytometry assay": _entry(["flow cytometry"]),
    "viral plaque assay": _entry(["plaque assay"], generate_claim=False),
}


def test_a_claim_naming_the_obi_label_links_exact():
    links = link_claims({"claim_1": _claim("Enzyme-linked immunosorbent assays")}, REGISTRY)

    record = links["claims"]["claim_1"]
    assert record["link"] == "exact"
    assert record["assay_key"] == "enzyme-linked immunosorbent assay"
    assert record["obi_id"] == "OBI:0000661"
    assert record["registry_sample_type"] == "serum"


def test_a_claim_naming_a_paper_wording_links_through_the_alias():
    links = link_claims({"claim_1": _claim("ELISA"), "claim_2": _claim("Luminex")}, REGISTRY)

    assert links["claims"]["claim_1"]["link"] == "alias"
    assert links["claims"]["claim_1"]["assay_key"] == "enzyme-linked immunosorbent assay"
    # `standard_technique_name` is a wording too, though merge_verified does not index it.
    assert links["claims"]["claim_2"]["assay_key"] == "cytometric bead array assay"


def test_an_unmatched_claim_is_unlinked_with_the_entries_its_text_mentions():
    claims = {"claim_1": _claim("DNA microarray", text="Flow cytometry of PBMCs showed ...")}

    record = link_claims(claims, REGISTRY)["claims"]["claim_1"]

    assert record["link"] == "unlinked"
    assert record["assay_key"] is None
    assert record["candidates"] == ["flow cytometry assay"]


def test_a_mention_must_be_a_whole_word():
    claims = {"claim_1": _claim("x", text="the ELISAs-free cohort", quote="preflow cytometryx")}

    assert link_claims(claims, REGISTRY)["claims"]["claim_1"]["candidates"] == []


def test_a_linked_assay_the_registry_says_generates_no_claim_is_a_mismatch():
    links = link_claims({"claim_1": _claim("plaque assay")}, REGISTRY)

    assert links["assays"]["viral plaque assay"]["status"] == "generate_claim_mismatch"
    assert links["assays"]["viral plaque assay"]["claims"] == ["claim_1"]


def test_an_uncovered_assay_mentioned_by_an_unlinked_claim_is_a_possible_wording_mismatch():
    claims = {"claim_1": _claim("ELISA"),
              "claim_2": _claim("cytokine panel", quote="measured by 24-plex Luminex assay")}

    links = link_claims(claims, REGISTRY)

    gap = links["assays"]["cytometric bead array assay"]
    assert gap["status"] == "possible_wording_mismatch"
    assert gap["candidate_claims"] == ["claim_2"]
    assert "cytometric bead array assay" in links["unclaimed_assays"]
    assert links["unlinked_claims"] == ["claim_2"]


def test_an_uncovered_assay_nothing_in_results_mentions_has_a_doubtful_generate_claim():
    finding_text = {"S10": "Luminex showed higher IL-6.", "S11": "Nothing relevant here."}

    links = link_claims({"claim_1": _claim("ELISA")}, REGISTRY, finding_text)

    assert links["assays"]["flow cytometry assay"]["status"] == "generate_claim_doubtful"
    luminex = links["assays"]["cytometric bead array assay"]
    assert luminex["status"] == "unexplained"
    assert luminex["finding_sentence_ids"] == ["S10"]


def test_without_paper_text_an_uncovered_assay_is_unexplained_and_says_so():
    links = link_claims({}, REGISTRY)

    gap = links["assays"]["flow cytometry assay"]
    assert gap == {**gap, "status": "unexplained", "text_checked": False}
    assert links["assays"]["viral plaque assay"]["status"] == "no_claim_expected"


def test_a_pre_flag_registry_entry_without_a_claim_is_not_counted_as_a_gap():
    registry = {"flow cytometry assay": _entry(["flow cytometry"], generate_claim=None)}

    links = link_claims({}, registry)

    assert links["assays"]["flow cytometry assay"]["status"] == "no_claim_unlabelled"
    assert links["unclaimed_assays"] == []


def test_summary_counts_links_and_statuses():
    links = link_claims({"claim_1": _claim("ELISA"), "claim_2": _claim("RNA-seq")}, REGISTRY)

    assert links["summary"]["claims"] == 2
    assert links["summary"]["claim_links"] == {"alias": 1, "unlinked": 1}
    assert links["summary"]["assays"] == 4


def test_load_registry_copies_the_obi_term_in_by_key(tmp_path):
    (tmp_path / "assays.json").write_text(json.dumps(
        {"flow cytometry assay": _entry(["flow cytometry"])}))
    (tmp_path / "assays_OBI.json").write_text(json.dumps(
        {"flow cytometry assay": {"obi_id": "OBI:0000916", "obi_label": "flow cytometry assay"}}))

    registry = load_registry(tmp_path)

    assert registry["flow cytometry assay"]["obi_id"] == "OBI:0000916"


def test_load_registry_works_without_an_obi_file(tmp_path):
    (tmp_path / "assays.json").write_text(json.dumps(
        {"flow cytometry assay": _entry(["flow cytometry"])}))

    assert "obi_id" not in load_registry(tmp_path)["flow cytometry assay"]


def test_finding_sentences_keeps_results_and_captions_only():
    numbered = (
        "## Methods [methods]\n[S1] Cells were stained for flow cytometry.\n"
        "## Results [results]\n[S2] Flow cytometry showed more B cells.\n"
        "--- Figures ---\n[S3] Figure 1. Flow cytometry of PBMCs.\n"
    )

    assert set(finding_sentences(numbered)) == {"S2", "S3"}
