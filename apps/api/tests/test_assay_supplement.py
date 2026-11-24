"""The supplement workflow: one document of main text + supplement, and a chain that reads it.

No network and no model. What is under test is what the workflow decides for itself -- how the
two texts are joined and numbered, which supplement text rides along, what counts as a Methods
section, which evidence is marked as the supplement's -- and that asking for it changes nothing
about the main-text workflow: same prompt, same document, same folder when the switch is off.
"""

import json

import pytest

from app.agent import assay_extractor, assay_service, assay_supplement as sup, paper_supplements
from app.agent.assay_service import PaperNotFoundError, assay_report, estimate_run
from app.agent.assay_verifier import derive_evidence_fields, sentence_index
from app.agent.jats_parser import number_sentences, sentence_sections

_PROSE = ("Peripheral blood was drawn into heparinized tubes and processed within four hours of "
          "collection. Mononuclear cells were isolated by density gradient centrifugation, washed "
          "twice in buffered saline, counted, and cryopreserved in freezing medium until the day "
          "of staining. On the day of analysis the cells were thawed, rested for one hour, and "
          "stained with the antibody panel before acquisition.")

_XML = f"""<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p>
<p>{_PROSE}</p></sec>
<sec><title>Results</title><p>Frequencies rose after vaccination.</p></sec></body></article>"""

_XML_NO_METHODS = """<article><front><article-meta><article-title>A Paper</article-title>
</article-meta></front><body><sec><title>Results</title>
<p>Frequencies rose after vaccination.</p></sec></body></article>"""

_SUPP_METHODS = ("Serum antibody was measured by ELISA on coated plates. " + _PROSE)
_SUPPLEMENT = number_sentences(
    "## s1.pdf: Supplementary Methods  [methods]\n" + _SUPP_METHODS + "\n\n"
    "## s1.pdf  [other]\nFigure S1. Gating strategy for the panel. Second legend sentence here."
)


def _main(xml: str = _XML) -> str:
    from app.agent.jats_parser import parse_jats_xml
    return number_sentences(parse_jats_xml(xml, include_extended_data=True))


# ── the combined document ─────────────────────────────────────────────────────

def test_main_text_keeps_its_sentence_ids_and_the_supplement_continues_them():
    main = _main()
    combined, first = sup.combine(main, _SUPPLEMENT)
    before, after = sentence_index(main), sentence_index(combined)
    # A sentence's span runs to the next marker (assay_verifier.sentence_index), so the last
    # main-text sentence now also holds the banner and the first supplement heading: same id,
    # same sentence, a longer tail.
    assert all(after[sid].startswith(text) for sid, text in before.items())
    assert combined.startswith(main.rstrip("\n"))
    assert first == len(before) + 1
    assert after[f"S{first}"] == "Serum antibody was measured by ELISA on coated plates."
    assert sup.main_text(combined) == main.rstrip("\n")


def test_supplement_sections_are_read_back_with_their_buckets():
    combined, first = sup.combine(_main(), _SUPPLEMENT)
    sections = sentence_sections(combined)
    assert sections[f"S{first}"] == "methods"
    legend = next(sid for sid, text in sentence_index(combined).items()
                  if text.startswith("Figure S1."))
    assert sections[legend] == "other"
    entry = {"x": {"evidence": {"quote": "Serum antibody was measured by ELISA on coated plates."}}}
    derive_evidence_fields(entry, combined)
    assert entry["x"]["source"] == "methods"
    assert entry["x"]["evidence"]["sentence_ids"] == [f"S{first}"]


def test_an_empty_supplement_adds_nothing():
    main = _main()
    assert sup.combine(main, "") == (main, None)
    assert sup.combine(main, "## s1.pdf  [other]\n") == (main, None)


def test_methods_blocks_are_never_cut_and_other_text_fills_the_budget():
    rendered = number_sentences(
        "## a.pdf: Methods  [methods]\n" + "M sentence one. " * 30 + "\n\n"
        "## a.pdf  [other]\n" + "Legend sentence. " * 30 + "\n\n"
        "## b.pdf  [other]\nNever reached.")
    methods_len = len("M sentence one. " * 30)
    picked = sup.select_blocks(rendered, max_chars=methods_len + 150)
    assert picked.count("M sentence one.") == 30
    assert 0 < picked.count("Legend sentence.") < 30
    assert picked.rstrip().endswith("Legend sentence.")
    assert "Never reached" not in picked
    # A budget smaller than the methods still delivers the methods, and only them.
    tight = sup.select_blocks(rendered, max_chars=10)
    assert tight.count("M sentence one.") == 30 and "Legend" not in tight


# ── the prompt ────────────────────────────────────────────────────────────────

def test_supplementary_methods_count_as_the_papers_methods():
    main = _main(_XML_NO_METHODS)
    assert not assay_extractor.has_methods_section(main)
    combined, _ = sup.combine(main, _SUPPLEMENT)
    assert sup.has_methods_section(combined)
    prompt = sup.build_prompt(combined, "A Paper")
    assert "STRUCTURE 3 APPLIES" not in prompt.split("PAPER TEXT:")[1]
    assert "--- Supplement ---" in prompt.split("PAPER TEXT:")[1]


def test_structure_3_is_stated_when_neither_side_has_methods():
    legends_only = number_sentences("## s1.pdf  [other]\nFigure S1. Gating strategy shown.")
    combined, first = sup.combine(_main(_XML_NO_METHODS), legends_only)
    assert first is not None and not sup.has_methods_section(combined)
    assert sup.NO_METHODS_NOTE in sup.build_prompt(combined, "A Paper")


def test_the_supplement_prompt_is_its_own_file_with_the_same_output_contract():
    main_prompt = assay_extractor._load_prompt("extract_assays.txt")
    supplement_prompt = assay_extractor._load_prompt(sup.PROMPT_FILE)
    assert "--- Supplement ---" in supplement_prompt
    assert "--- Supplement ---" not in main_prompt
    # Everything from the entry rules to the paper slot is shared wording: the two workflows
    # must agree on what an entry is and what fields it carries, or their results cannot be
    # compared. Only the passages about the supplement differ.
    for field in ("name_in_paper", "standard_technique_name", "aliases", "sample_type",
                  "readouts", "generate_claim", "evidence"):
        assert f"`{field}`" in supplement_prompt and f"`{field}`" in main_prompt
    assert supplement_prompt.count("{source_text}") == 1
    assert supplement_prompt.count("{paper_title}") == 1


def test_the_supplement_prompt_anchors_a_shared_technique_in_the_main_text():
    """SDY1373, 2026-11-20: told to quote "the one that says more", the model moved ELISA's
    evidence from a main-text sentence to a figure fragment in the supplement."""
    prompt = assay_extractor._load_prompt(sup.PROMPT_FILE)
    assert "Main text first." in prompt
    assert "the quote MUST\n    come from the main text" in prompt
    assert "Never quote a fragment." in prompt
    assert "quote the one that says" not in prompt


# ── marking the evidence ──────────────────────────────────────────────────────

def test_in_supplement_is_decided_by_the_sentence_ids():
    assert sup.in_supplement(["S3"], 10) is False
    assert sup.in_supplement(["S10", "S11"], 10) is True
    assert sup.in_supplement(["S9", "S10"], 10) is False
    assert sup.in_supplement([], 10) is None
    assert sup.in_supplement(["S50"], None) is False


def test_mark_and_list_supplement_entries():
    combined, first = sup.combine(_main(), _SUPPLEMENT)
    assays = {
        "flow": {"name_in_paper": ["LSRII"], "aliases": [],
                 "evidence": {"sentence_ids": ["S1"], "quote": "q"}},
        "elisa": {"name_in_paper": ["ELISA"], "aliases": [],
                  "evidence": {"sentence_ids": [f"S{first}"], "quote": "q"}},
        "both": {"name_in_paper": ["antibody panel"], "aliases": [],
                 "evidence": {"sentence_ids": [f"S{first + 1}"], "quote": "q"},
                 "additional_evidence": [{"evidence": {"sentence_ids": ["S2"], "quote": "q"}}]},
        "described better": {"name_in_paper": ["density gradient centrifugation"], "aliases": [],
                             "evidence": {"sentence_ids": [f"S{first + 2}"], "quote": "q"}},
    }
    sup.mark_supplement_evidence(assays, first)
    assert assays["flow"]["evidence"]["in_supplement"] is False
    assert assays["elisa"]["evidence"]["in_supplement"] is True
    assert assays["both"]["additional_evidence"][0]["evidence"]["in_supplement"] is False
    assert sup.supplement_entries(assays, combined) == [
        {"key": "elisa", "named_in_main_text": False},
        {"key": "described better", "named_in_main_text": True},
    ]


# ── the chain ─────────────────────────────────────────────────────────────────

_FLOW = {"name_in_paper": "flow cytometry", "standard_technique_name": "flow cytometry",
         "aliases": [], "sample_type": "cells", "readouts": "cell frequencies",
         "evidence": {"section": "Methods", "quote": "Cells were analyzed on an LSRII."}}
_ELISA = {"name_in_paper": "ELISA", "standard_technique_name": "ELISA", "aliases": [],
          "sample_type": "serum", "readouts": "antibody",
          "evidence": {"section": "s1.pdf: Supplementary Methods",
                       "quote": "Serum antibody was measured by ELISA on coated plates."}}
_OBI = {"flow cytometry": ("OBI:0000916", "flow cytometry assay"),
        "ELISA": ("OBI:0000661", "enzyme-linked immunosorbent assay")}


class _Client:
    """Answers round 1 with `extraction`, and round 2 by reading which assay it was asked about."""

    def __init__(self, extraction: dict):
        self.extraction, self.prompts = extraction, []
        self.chat = type("c", (), {"completions": self})()

    async def create(self, messages, **_):
        content = messages[-1]["content"]
        self.prompts.append(content)
        if len(self.prompts) <= assay_service.EXTRACTIONS:
            body = json.dumps(self.extraction)
        else:
            assay_id = "ELISA" if '"ELISA"' in content[-2500:] else "flow cytometry"
            fields = ["name_in_paper", "readouts", "sample_type", "evidence.quote"]
            body = json.dumps({
                "assay_id": assay_id, "assay_identity_verdict": "SUPPORTED",
                "field_verifications": [{"field_name": f, "verdict": "SUPPORTED",
                                         "reason": "ok"} for f in fields],
                "conflict_detected": False, "record_verdict": "ACCEPT"})
        message = type("m", (), {"content": body})()
        return type("r", (), {"choices": [type("c", (), {"message": message})()]})()


@pytest.fixture
def paper(tmp_path, monkeypatch):
    """One paper with an XML and a rendered supplement, every root redirected into tmp_path."""
    roots = {name: tmp_path / name for name in
             ("JAT_XML", "pdf", "registries", "cache", "supplement_registries", "supplements")}
    for root in roots.values():
        root.mkdir()
    (roots["JAT_XML"] / "SDY1_111.xml").write_text(_XML, encoding="utf-8")
    (roots["supplements"] / "SDY1_111").mkdir()
    (roots["supplements"] / "SDY1_111" / "supplement.txt").write_text(_SUPPLEMENT, "utf-8")
    monkeypatch.setattr(assay_service, "XML_ROOT", roots["JAT_XML"])
    monkeypatch.setattr(assay_service, "PDF_ROOT", roots["pdf"])
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", roots["registries"])
    monkeypatch.setattr(assay_service, "CACHE_ROOT", roots["cache"])
    monkeypatch.setattr(assay_service, "SUPPLEMENT_REGISTRY_ROOT", roots["supplement_registries"])
    monkeypatch.setattr(paper_supplements, "SUPPLEMENT_ROOT", roots["supplements"])

    def _fake_obi(assays, *_args, **_kwargs):
        mapped = {}
        for key, entry in assays.items():
            name = entry["name_in_paper"]
            obi_id, label = _OBI[name[0] if isinstance(name, list) else name]
            mapped[key] = {**entry, "obi_id": obi_id, "obi_label": label,
                           "resource": "exact_original", "obi_confidence": "high"}
        return mapped

    monkeypatch.setattr(assay_service, "enrich_assays_with_obi", _fake_obi)
    return roots


@pytest.mark.asyncio
async def test_the_supplement_workflow_reads_both_and_writes_to_its_own_folder(paper):
    client = _Client({"flow cytometry": _FLOW, "ELISA": _ELISA})
    result = await assay_report("111", "SDY1", client, supplement=True)

    out_dir = paper["supplement_registries"] / "111_SDY1"
    assert (out_dir / "assays_benchmark.json").is_file()
    assert not any(paper["registries"].iterdir()) and not any(paper["cache"].iterdir())

    first_prompt = client.prompts[0]
    assert first_prompt == sup.build_prompt(
        sup.combine(_main(), _SUPPLEMENT)[0], "A Paper")
    assert "Serum antibody was measured by ELISA" in first_prompt

    delivered = json.loads((out_dir / "assays_benchmark.json").read_text())
    flow = delivered["flow cytometry assay"]
    elisa = delivered["enzyme-linked immunosorbent assay"]
    assert flow["evidence"]["in_supplement"] is False
    assert elisa["evidence"]["in_supplement"] is True
    assert elisa["source"] == "methods"
    assert result["paper_source_kind"] == sup.SOURCE_KIND
    assert result["supplement"]["entries"] == [
        {"key": "enzyme-linked immunosorbent assay", "named_in_main_text": False}]
    assert result["quote_check"]["missing"] == 0
    assert "no_methods" not in result["rounds"]["extract"]
    assert not result["contract_warnings"]


@pytest.mark.asyncio
async def test_without_the_switch_the_main_text_workflow_is_what_it_was(paper):
    client = _Client({"flow cytometry": _FLOW})
    result = await assay_report("111", "SDY1", client)

    assert client.prompts[0] == assay_extractor.build_prompt(_main(), "A Paper")
    assert "--- Supplement ---" not in client.prompts[0]
    assert (paper["cache"] / "111_SDY1" / "assays_benchmark.json").is_file()
    assert not any(paper["supplement_registries"].iterdir())
    assert result["supplement"] is None and result["paper_source_kind"] == "xml"
    evidence = result["assays"]["flow cytometry assay"]["evidence"]
    assert "in_supplement" not in evidence


@pytest.mark.asyncio
async def test_the_supplement_workflow_names_what_is_missing(paper):
    (paper["supplements"] / "SDY1_111" / "supplement.txt").unlink()
    with pytest.raises(PaperNotFoundError, match="No supplement text"):
        await assay_report("111", "SDY1", _Client({}), supplement=True)
    (paper["JAT_XML"] / "SDY1_111.xml").unlink()
    (paper["pdf"] / "SDY1_111.pdf").write_bytes(b"%PDF")
    with pytest.raises(PaperNotFoundError, match="needs the paper's JATS XML"):
        await assay_report("111", "SDY1", _Client({}), supplement=True)


def test_the_estimate_reports_the_combined_document_and_what_it_was_sized_from(paper):
    plain = estimate_run("111", "SDY1")
    estimate = estimate_run("111", "SDY1", supplement=True)
    assert plain["paper_source_kind"] == "xml" and plain["supplement_chars"] is None
    assert estimate["paper_source_kind"] == sup.SOURCE_KIND
    assert estimate["source_chars"] == plain["source_chars"] + estimate["supplement_chars"]
    assert estimate["supplement_chars"] > 0
    assert estimate["registry_dir"] == str(paper["supplement_registries"] / "111_SDY1")
    assert estimate["sized_from"] is not None
    assert plain["sized_from"] is None


# ── the command line ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cli():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "scripts" / "run_assay_pipeline.py"
    spec = importlib.util.spec_from_file_location("run_assay_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_the_cli_prints_a_supplement_line_per_entry(paper, cli, capsys):
    result = await assay_report(
        "111", "SDY1", _Client({"flow cytometry": _FLOW, "ELISA": _ELISA}), supplement=True)
    cli.report_result(result)
    out = capsys.readouterr().out
    assert ("SUPPLEMENT  enzyme-linked immunosorbent assay: evidence is in the supplement; "
            "not named in the main text") in out
    assert "SUPPLEMENT  flow cytometry assay" not in out
    assert "WARNING" not in out


def test_the_dry_run_says_which_workflow_and_what_it_was_sized_from(paper, cli, capsys):
    cli._dry_run("111", "SDY1", supplement=True)
    out = capsys.readouterr().out
    assert "[xml+supplement]" in out and "extract_assays_supplement.txt" in out
    assert "sized from the main-text registry" in out
    cli._dry_run("111", "SDY1")
    plain = capsys.readouterr().out
    assert "[xml]" in plain and "supplement" not in plain
