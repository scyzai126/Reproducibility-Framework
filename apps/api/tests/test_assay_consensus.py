"""Round 1 by majority: entries and fields a majority of extractions agree on, nothing else."""

from app.agent.assay_consensus import consensus, consensus_with_support, same_entry
from app.agent.assay_extractor import ENTRY_FIELDS


def _entry(name, technique="ELISA", quote="Serum IgG was measured by ELISA.", ids=("S1",),
           sample="serum", readouts="IgG titers", aliases=(), claim=True):
    return {"name_in_paper": name, "standard_technique_name": technique, "aliases": list(aliases),
            "sample_type": sample, "readouts": readouts, "generate_claim": claim,
            "source": None,
            "evidence": {"section": "Methods", "sentence_ids": list(ids), "quote": quote}}


ELISA = _entry("ELISA")
FLOW = _entry("flow cytometry", "flow cytometry", "Cells were acquired on an LSRII.", ("S5",),
              sample="PBMCs", readouts="cell frequencies", aliases=["FACS"])
DC_PANEL = _entry("flow cytometry for DC activation", "flow cytometry",
                  "Cells were stained with CD80-FITC and CD86-APC.", ("S9",), sample="PBMCs",
                  readouts="CD80 and CD86 on DCs")


def test_one_registry_comes_back_untouched():
    registry = {"ELISA": ELISA, "flow cytometry": FLOW}

    assert consensus([registry]) == (registry, {})


def test_an_entry_in_two_of_three_runs_is_delivered_and_one_in_one_run_is_minority():
    """SDY1260: the DC-activation panel appeared in half the runs. With three runs there is a
    majority either way, and the losing side is reported rather than dropped."""
    runs = [{"ELISA": ELISA, "flow cytometry": FLOW},
            {"ELISA": ELISA, "flow cytometry": FLOW, "flow cytometry for DC activation": DC_PANEL},
            {"ELISA": ELISA, "flow cytometry": FLOW}]

    registry, minority = consensus(runs)

    assert list(registry) == ["ELISA", "flow cytometry"]
    assert list(minority) == ["flow cytometry for DC activation"]
    assert minority["flow cytometry for DC activation"]["runs"] == ["run2"]
    assert minority["flow cytometry for DC activation"]["of"] == 3
    assert minority["flow cytometry for DC activation"]["entry"] == DC_PANEL


def test_an_entry_in_two_of_three_runs_is_delivered():
    runs = [{"ELISA": ELISA, "flow cytometry for DC activation": DC_PANEL},
            {"ELISA": ELISA, "flow cytometry for DC activation": DC_PANEL},
            {"ELISA": ELISA}]

    registry, minority = consensus(runs)

    assert list(registry) == ["ELISA", "flow cytometry for DC activation"]
    assert minority == {}


def test_support_says_which_runs_held_each_delivered_entry():
    """A bare-majority entry is delivered like any other; `support` is the only place the
    margin survives, keyed by the delivered key, in the shape of a minority record."""
    runs = [{"ELISA": ELISA, "flow cytometry for DC activation": DC_PANEL},
            {"ELISA": ELISA, "flow cytometry for DC activation": DC_PANEL},
            {"ELISA": ELISA}]

    registry, minority, support = consensus_with_support(runs)

    assert (registry, minority) == consensus(runs)
    assert support == {"ELISA": {"runs": ["run1", "run2", "run3"], "of": 3},
                       "flow cytometry for DC activation": {"runs": ["run1", "run2"], "of": 3}}


def test_support_of_one_registry_is_one_of_one():
    registry = {"ELISA": ELISA}

    assert consensus_with_support([registry]) == (registry, {}, {"ELISA": {"runs": ["run1"], "of": 1}})


def test_fields_take_the_value_two_runs_agree_on_in_its_first_spelling():
    runs = [{"ELISA": _entry("ELISA", sample="Serum", readouts="IgG titers")},
            {"ELISA": _entry("ELISA", sample="serum samples", readouts="IgG titres")},
            {"ELISA": _entry("ELISA", sample="serum", readouts="IgG titers")}]

    registry, _ = consensus(runs)

    assert registry["ELISA"]["sample_type"] == "Serum"
    assert registry["ELISA"]["readouts"] == "IgG titers"


def test_when_every_run_differs_the_first_runs_value_stands():
    runs = [{"ELISA": _entry("ELISA", readouts="a")}, {"ELISA": _entry("ELISA", readouts="b")},
            {"ELISA": _entry("ELISA", readouts="c")}]

    assert consensus(runs)[0]["ELISA"]["readouts"] == "a"


def test_a_null_specimen_is_outvoted_by_two_stated_ones():
    """SDY1264's RT-PCR specimen came back null in one run and PBMC in the next."""
    runs = [{"RT-PCR": _entry("RT-PCR", sample=None)},
            {"RT-PCR": _entry("RT-PCR", sample="peripheral blood mononuclear cells")},
            {"RT-PCR": _entry("RT-PCR", sample="peripheral blood mononuclear cells")}]

    assert consensus(runs)[0]["RT-PCR"]["sample_type"] == "peripheral blood mononuclear cells"


def test_aliases_are_the_union_and_other_runs_names_become_aliases():
    """Round 2's string check removes an alias the paper lacks for free; a voted-away one is
    never recovered. A run that named the assay differently contributes that name."""
    runs = [{"flow cytometry": _entry("flow cytometry", aliases=["FACS"])},
            {"Flow cytometric analysis": _entry("Flow cytometric analysis", aliases=["flow cytometry"])},
            {"flow cytometry": _entry("flow cytometry", aliases=["fluorescence-activated cell sorting"])}]

    registry, _ = consensus(runs)

    assert list(registry) == ["flow cytometry"]
    # Order is the anchor order (by content), not run order; the set is what matters.
    assert set(registry["flow cytometry"]["aliases"]) == {
        "FACS", "Flow cytometric analysis", "fluorescence-activated cell sorting"}


def test_the_quote_is_voted_and_its_section_travels_with_it():
    runs = [{"SBA": _entry("SBA", quote="Titers were interpolated.", ids=("S3",))},
            {"SBA": _entry("SBA", quote="Serum samples were diluted 3-fold.", ids=("S2",))},
            {"SBA": {**_entry("SBA", quote="Serum samples were diluted 3-fold.", ids=("S2",)),
                     "evidence": {"section": "SBA methods", "sentence_ids": ["S2"],
                                  "quote": "Serum samples were diluted 3-fold."}}}]

    registry, _ = consensus(runs)

    assert registry["SBA"]["evidence"]["quote"] == "Serum samples were diluted 3-fold."
    # Derived later from the quote, not carried from any run.
    assert registry["SBA"]["evidence"]["sentence_ids"] == []
    assert registry["SBA"]["source"] is None


def test_generate_claim_is_a_boolean_or_none_never_a_string():
    runs = [{"ELISA": _entry("ELISA", claim=None)}, {"ELISA": _entry("ELISA", claim=False)},
            {"ELISA": _entry("ELISA", claim=False)}]

    assert consensus(runs)[0]["ELISA"]["generate_claim"] is False


def test_the_delivered_entry_has_exactly_the_contract_fields_in_order():
    registry, _ = consensus([{"ELISA": ELISA}, {"ELISA": ELISA}, {"ELISA": ELISA}])

    assert tuple(registry["ELISA"]) == ENTRY_FIELDS


def test_two_entries_every_run_kept_apart_are_never_voted_into_one():
    """SDY1260: `ELISA kits` is aliased "ELISA". A single-tier alias match would fold it onto
    the serum ELISA across runs; the vote must count what each run kept separate."""
    a = _entry("ELISA", quote="Serum IgG was measured by ELISA.", ids=("S1",))
    b = _entry("ELISA kits", quote="Supernatants were assessed by ELISA kits.", ids=("S9",),
               aliases=["ELISA"], sample="supernatant", readouts="IL-6")
    runs = [{"ELISA": a, "ELISA kits": b}] * 3

    registry, minority = consensus(runs)

    assert list(registry) == ["ELISA", "ELISA kits"]
    assert registry["ELISA kits"]["sample_type"] == "supernatant"
    assert minority == {}


def test_a_duplicate_key_one_run_produced_is_minority_not_merged():
    """v2's `ELISA (2)`, aliased "ELISA": it may not join the ELISA cluster, which already has an
    entry from its own run, so it is reported as a 1-of-3 minority."""
    a = _entry("ELISA")
    dup = _entry("ELISA (2)", quote="Supernatants were assessed by ELISA.", ids=("S9",),
                 aliases=["ELISA"])
    runs = [{"ELISA": a}, {"ELISA": a, "ELISA (2)": dup}, {"ELISA": a}]

    registry, minority = consensus(runs)

    assert list(registry) == ["ELISA"]
    assert list(minority) == ["ELISA (2)"]


def test_two_wordings_of_one_assay_are_recognised_as_the_same_entry():
    """`same_entry` is the second clustering tier `cluster_for_vote` falls back on when the
    normalized name does not match, so a run that wrote "FACS" still votes with one that
    wrote "flow cytometry" instead of being counted as a separate assay."""
    assert same_entry("flow cytometry", FLOW, "FACS", {**FLOW, "name_in_paper": "FACS"})


def test_a_dissenting_run_that_merged_two_assays_leaks_no_sibling_name_as_an_alias():
    """SDY1264: one of three extractions folded CPE and PRNT into one entry aliased with both
    names. The vote kept the split; the CPE entry must not come out aliased "PRNT"."""
    cpe = _entry("neutralizing antibodies by CPE", "neutralization assay",
                 "YFV neutralizing antibodies were measured by CPE or by PRNT.", ("S179",),
                 aliases=["CPE"])
    prnt = _entry("plaque reduction neutralization test", "neutralization assay",
                  "For the PRNT, dilutions of the sera were incubated overnight.", ("S183",),
                  aliases=["PRNT"])
    merged = _entry("Assay for YFV neutralizing antibodies", "neutralization assay",
                    "YFV neutralizing antibodies were measured by CPE or by PRNT.", ("S179",),
                    aliases=["CPE", "PRNT", "plaque reduction neutralization test"])
    runs = [{"neutralizing antibodies by CPE": cpe, "plaque reduction neutralization test": prnt},
            {"Assay for YFV neutralizing antibodies": merged},
            {"neutralizing antibodies by CPE": cpe, "plaque reduction neutralization test": prnt}]

    registry, minority = consensus(runs)

    assert list(registry) == ["neutralizing antibodies by CPE", "plaque reduction neutralization test"]
    assert registry["neutralizing antibodies by CPE"]["aliases"] == [
        "CPE", "Assay for YFV neutralizing antibodies"]
    assert registry["plaque reduction neutralization test"]["aliases"] == ["PRNT"]
    assert minority == {}


# ── free-text fields vote leniently; names, quotes and booleans do not ───────

def test_a_rewording_that_contains_the_other_agrees_and_the_shorter_is_delivered():
    """SDY1264's Multiplex analysis: "Plasma samples from CPTs" in one run, "plasma" in another.
    Run 1's verbose spelling used to stand because nothing matched it exactly."""
    runs = [{"ELISA": _entry("ELISA", sample="Plasma samples from CPTs")},
            {"ELISA": _entry("ELISA", sample="plasma")},
            {"ELISA": _entry("ELISA", sample="serum")}]

    assert consensus(runs)[0]["ELISA"]["sample_type"] == "plasma"


def test_rewordings_sharing_most_of_their_words_agree():
    long_a = "percentages of CD86+ antigen-presenting cells and CD38+ HLA-DR+ CD8+ T cells"
    long_b = "percentages of CD86+ antigen-presenting cells and percentage of CD38+ HLA-DR+ CD8+ CD3+ T cells"
    runs = [{"flow": _entry("flow", readouts="frequencies of monocytes and dendritic cells")},
            {"flow": _entry("flow", readouts=long_b)},
            {"flow": _entry("flow", readouts=long_a)}]

    assert consensus(runs)[0]["flow"]["readouts"] == long_a  # the shorter of the agreeing pair


def test_a_detail_two_runs_wrote_survives_the_lenient_vote():
    """SDY1289's gene array: all three readings agree leniently, and the shortest used to win,
    delivering "gene expression levels" although two runs both named whole-blood RNA on Illumina
    BeadChips. The value sharing the most words with the others carries what a majority wrote."""
    full_a = "gene expression levels from whole-blood RNA hybridized to Illumina BeadChips"
    full_b = "whole-blood gene expression levels measured by hybridization to Illumina BeadChips"
    runs = [{"array": _entry("array", readouts="gene expression levels")},
            {"array": _entry("array", readouts=full_b)},
            {"array": _entry("array", readouts=full_a)}]

    assert consensus(runs)[0]["array"]["readouts"] == full_a  # the shorter of the two fullest


def test_a_detail_only_one_run_wrote_still_does_not_survive():
    """SDY1289's IL-1β ELISA: "in culture supernatants" appears in one run only, so the shortest
    of the agreeing pair is still delivered."""
    runs = [{"ELISA": _entry("ELISA", readouts="IL-1β concentration in culture supernatants")},
            {"ELISA": _entry("ELISA", readouts="IL-1β concentration")},
            {"ELISA": _entry("ELISA", readouts="IL-1β secretion")}]

    assert consensus(runs)[0]["ELISA"]["readouts"] == "IL-1β concentration"


def test_an_exact_majority_still_beats_a_lenient_one():
    """Two runs wrote "24 cytokine concentrations"; the third's shorter wording is contained in
    it, but the words two runs actually wrote win over the core."""
    runs = [{"Luminex": _entry("Luminex", readouts="cytokine concentrations")},
            {"Luminex": _entry("Luminex", readouts="24 cytokine concentrations")},
            {"Luminex": _entry("Luminex", readouts="24 cytokine concentrations")}]

    assert consensus(runs)[0]["Luminex"]["readouts"] == "24 cytokine concentrations"


def test_a_null_never_agrees_with_a_stated_value():
    runs = [{"RT-PCR": _entry("RT-PCR", sample="PBMC")},
            {"RT-PCR": _entry("RT-PCR", sample=None)},
            {"RT-PCR": _entry("RT-PCR", sample="whole blood")}]

    assert consensus(runs)[0]["RT-PCR"]["sample_type"] == "PBMC"  # nothing agrees: run 1


def test_the_quote_is_never_voted_leniently():
    """A quote must be verbatim; the lenient rule could deliver a span only one run copied.
    Nothing agrees here, so the anchor's stands: all three are placed alike, so the longest."""
    runs = [{"ELISA": _entry("ELISA", quote="Serum IgG was measured by ELISA on day 28.")},
            {"ELISA": _entry("ELISA", quote="Serum IgG was measured by ELISA.")},
            {"ELISA": _entry("ELISA", quote="Titers were read at 450 nm.")}]

    assert consensus(runs)[0]["ELISA"]["evidence"]["quote"] == \
        "Serum IgG was measured by ELISA on day 28."


def test_the_technique_votes_leniently_too():
    runs = [{"FACS": _entry("FACS", technique="flow cytometry assay")},
            {"FACS": _entry("FACS", technique="flow cytometry")},
            {"FACS": _entry("FACS", technique="mass cytometry")}]

    assert consensus(runs)[0]["FACS"]["standard_technique_name"] == "flow cytometry"


def test_entries_quoting_the_same_sentence_align_on_sentence_ids_alone():
    """Different name, no shared alias, different technique string: only the ids link them."""
    a = _entry("ELISA", technique="enzyme-linked immunosorbent assay",
               quote="Serum IgG was measured", ids=("S1",))
    b = _entry("enzyme immunoassay", technique="immunoassay", quote="measured by ELISA",
               ids=("S1",))

    assert same_entry("ELISA", a, "enzyme immunoassay", b)
    assert not same_entry("ELISA", a, "enzyme immunoassay", {**b, "evidence": {**b["evidence"], "sentence_ids": ["S2"]}})


# ── order independence ────────────────────────────────────────────────────────

def _ics(name, aliases):
    return _entry(name, "flow cytometry", "PBMC were stained for intracellular IFN-g.", ("S10",),
                  sample="PBMCs", readouts="IFN-g production", aliases=aliases)


ICS_SHORT = {"ICS": _ics("ICS", ["intracellular cytokine staining"])}
ICS_LONG = {"intracellular cytokine staining": _ics("intracellular cytokine staining", ["ICS"])}


def _rotations(runs):
    return [runs[i:] + runs[:i] for i in range(len(runs))]


def test_the_vote_does_not_depend_on_which_reply_was_called_run1():
    """The three extraction calls run concurrently and are labelled by slot, so the same
    replies must vote the same way in any order. Tier 2 used to look only at clusters already
    passed, in run order, so the odd wording out joined its cluster only when it came last."""
    runs = [ICS_SHORT, ICS_LONG, ICS_LONG]

    outcomes = [consensus(order) for order in _rotations(runs)]

    for registry, minority in outcomes:
        assert list(registry) == ["intracellular cytokine staining"]
        assert minority == {}
        assert registry["intracellular cytokine staining"]["aliases"] == ["ICS"]


def test_a_lone_wording_in_the_first_run_joins_a_later_cluster_that_names_the_same_assay():
    """The case the old walk could never align: run1's wording with no earlier cluster to join."""
    registry, minority = consensus([ICS_SHORT, ICS_LONG, ICS_LONG])

    assert minority == {}
    assert list(registry) == ["intracellular cytokine staining"]


def test_a_lone_wording_prefers_the_host_more_runs_agree_on():
    """Two possible hosts, one backed by two runs and one by a single run: the majority wins,
    whatever order the runs came in."""
    other = {"flow cytometry": _entry("flow cytometry", "flow cytometry",
                                      "Cells were acquired on an LSRII.", ("S5",),
                                      sample="PBMCs", readouts="cell frequencies",
                                      aliases=["ICS"])}
    runs = [{**ICS_SHORT}, {**ICS_LONG}, {**ICS_LONG, **other}]

    for order in _rotations(runs):
        registry, minority = consensus(order)
        assert "intracellular cytokine staining" in registry
        assert registry["intracellular cytokine staining"]["aliases"] == ["ICS"]
        assert list(minority) == ["flow cytometry"]


def test_two_lone_wordings_from_different_runs_still_form_a_majority_in_any_order():
    """Neither wording has a two-run host; the two lone entries must find each other."""
    runs = [ICS_SHORT, ICS_LONG, {"ELISA": ELISA}]

    for order in _rotations(runs):
        registry, minority = consensus(order)
        (key, entry), = registry.items()
        assert {key, *entry["aliases"]} == {"ICS", "intracellular cytokine staining"}
        assert list(minority) == ["ELISA"]
        assert len(minority["ELISA"]["runs"]) == 1


def test_the_same_run_guard_still_holds_in_every_order():
    """`ELISA (2)` aliased "ELISA" from the run that also produced `ELISA` may never join it."""
    a = _entry("ELISA")
    dup = _entry("ELISA (2)", quote="Supernatants were assessed by ELISA.", ids=("S9",),
                 aliases=["ELISA"])
    runs = [{"ELISA": a}, {"ELISA": a, "ELISA (2)": dup}, {"ELISA": a}]

    for order in _rotations(runs):
        registry, minority = consensus(order)
        assert list(registry) == ["ELISA"]
        assert list(minority) == ["ELISA (2)"]


# ── the fallbacks read the anchor member, never slot run1 ─────────────────────

def test_fallback_fields_are_the_same_in_every_rotation():
    """Three different answers on every field: nothing agrees, and what stands must not depend on
    which reply was called run1. Measured on the stored v3 replies, 22 of 178 delivered clusters
    changed a field with run order before the anchor rule."""
    runs = [{"ELISA": _entry("ELISA", quote="Serum IgG was measured by ELISA on day 28.",
                             sample="serum", readouts="IgG titers", claim=True)},
            {"ELISA": _entry("ELISA", quote="Serum IgG was measured by ELISA.",
                             sample="plasma", readouts="antibody levels", claim=False)},
            {"ELISA": _entry("ELISA", quote="Titers were read at 450 nm.",
                             sample="whole blood", readouts="optical density", claim=None)}]

    results = [consensus(order)[0]["ELISA"] for order in _rotations(runs)]

    assert results[0] == results[1] == results[2]
    # One coherent write-up, not run1's name beside run2's quote.
    anchor = runs[0]["ELISA"]  # placed alike, so the longest quote
    assert results[0]["sample_type"] == anchor["sample_type"]
    assert results[0]["generate_claim"] == anchor["generate_claim"]
    assert results[0]["evidence"]["quote"] == anchor["evidence"]["quote"]


def test_an_attached_dissenter_never_anchors_the_entry():
    """SDY212: run1's lone "Tetramer staining" quoted a Figure caption about viral titer; run2 and
    run3 agreed on the name and each quoted a different Methods sentence. No quote has a majority,
    and the one delivered must be a Methods sentence whatever order the replies came back in."""
    caption = _entry("Tetramer staining", "flow cytometry",
                     "Seven days after infection, IAV-specific T cells were enumerated by tetramer.",
                     ("S40",), aliases=["tetramer"])
    caption["source"] = "results"
    long_name = "Tetramer and Phenotypic Staining of CD8 T Cells"
    a = _entry(long_name, "flow cytometry", "Class I monomers were synthesized and tetramerized.",
               ("S12",), aliases=["tetramer"])
    b = _entry(long_name, "flow cytometry", "Staining was done as described previously.",
               ("S13",), aliases=["tetramer"])
    a["source"] = b["source"] = "methods"

    for order in _rotations([{"Tetramer staining": caption}, {long_name: a}, {long_name: b}]):
        registry, minority = consensus(order)
        assert minority == {}
        (entry,) = registry.values()
        assert entry["name_in_paper"] == long_name
        assert entry["evidence"]["quote"] in (a["evidence"]["quote"], b["evidence"]["quote"])


def test_a_quote_the_paper_places_in_methods_anchors_over_one_placed_elsewhere():
    methods = _entry("ELISA", quote="Serum IgG was measured by ELISA using a commercial kit.",
                     ids=("S3",))
    methods["source"] = "methods"
    results = _entry("ELISA", quote="IgG rose.", ids=("S9",))
    results["source"] = "results"
    unplaced = _entry("ELISA", quote="IgG was quantified.", ids=())

    for order in _rotations([{"ELISA": results}, {"ELISA": unplaced}, {"ELISA": methods}]):
        assert consensus(order)[0]["ELISA"]["evidence"]["quote"] == methods["evidence"]["quote"]
