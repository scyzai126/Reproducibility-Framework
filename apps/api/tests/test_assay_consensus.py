"""Round 1 by majority: entries and fields a majority of extractions agree on, nothing else."""

from app.agent.assay_consensus import consensus, same_entry
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
    assert registry["flow cytometry"]["aliases"] == [
        "FACS", "Flow cytometric analysis", "fluorescence-activated cell sorting"]


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
    """The parser keys a run's second "Luminex" as `Luminex (2)` but leaves its `name_in_paper`
    as "Luminex". It may not join the Luminex cluster, which already has an entry from its own
    run, so it is reported as a 1-of-3 minority rather than silently merged into the first."""
    a = _entry("Luminex", "Luminex", sample="serum")
    dup = _entry("Luminex", "Luminex", quote="Cytokines were measured by Luminex.", ids=("S9",),
                 sample="supernatant", readouts="cytokine concentrations")
    runs = [{"Luminex": a}, {"Luminex": a, "Luminex (2)": dup}, {"Luminex": a}]

    registry, minority = consensus(runs)

    assert list(registry) == ["Luminex"]
    assert registry["Luminex"]["sample_type"] == "serum"
    assert list(minority) == ["Luminex (2)"]
    assert minority["Luminex (2)"]["runs"] == ["run2"]
    assert minority["Luminex (2)"]["entry"] == dup


def test_a_second_same_name_entry_two_runs_produced_is_delivered_on_its_own():
    """Two of three runs split Luminex into a serum and a supernatant assay. The majority's
    judgement that there are two is kept: the second is delivered under the parser's key."""
    a = _entry("Luminex", "Luminex", sample="serum")
    dup = _entry("Luminex", "Luminex", quote="Cytokines were measured by Luminex.", ids=("S9",),
                 sample="supernatant", readouts="cytokine concentrations")
    runs = [{"Luminex": a}, {"Luminex": a, "Luminex (2)": dup}, {"Luminex": a, "Luminex (2)": dup}]

    registry, minority = consensus(runs)

    assert list(registry) == ["Luminex", "Luminex (2)"]
    assert registry["Luminex"]["sample_type"] == "serum"
    assert registry["Luminex (2)"]["sample_type"] == "supernatant"
    assert registry["Luminex (2)"]["evidence"]["quote"] == "Cytokines were measured by Luminex."
    assert minority == {}


def test_a_run_with_two_same_name_entries_does_not_outvote_the_others():
    """A vote counts runs. One run's two same-name entries agreeing with each other is one
    run's opinion, not a majority over the other two."""
    runs = [{"Luminex": _entry("Luminex", "Luminex", readouts="antibody titers")},
            {"Luminex": _entry("Luminex", "Luminex", readouts="multiplex panel"),
             "Luminex (2)": _entry("Luminex", "Luminex", readouts="multiplex panel",
                                   quote="Cytokines were measured by Luminex.", ids=("S9",))},
            {"Luminex": _entry("Luminex", "Luminex", readouts="antibody titres")}]

    registry, _ = consensus(runs)

    assert registry["Luminex"]["readouts"] == "antibody titers"


def test_a_lone_entry_joins_its_twin_even_when_the_twin_cluster_comes_later():
    """Run 1 wrote "flow cytometry"; runs 2 and 3 wrote "FACS". Clusters are built in run order,
    so the lone run-1 entry is seen before the FACS cluster exists -- it must still find it,
    be outvoted on the name, and contribute its wording as an alias instead of going to minority."""
    facs = {**FLOW, "name_in_paper": "FACS", "aliases": []}
    runs = [{"flow cytometry": FLOW, "ELISA": ELISA},
            {"ELISA": ELISA, "FACS": facs},
            {"ELISA": ELISA, "FACS": facs}]

    registry, minority = consensus(runs)

    assert list(registry) == ["ELISA", "FACS"]
    assert registry["FACS"]["aliases"] == ["flow cytometry"]
    assert minority == {}


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
