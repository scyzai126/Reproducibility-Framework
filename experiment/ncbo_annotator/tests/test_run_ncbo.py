"""Offline tests for experiment/ncbo_annotator/run_ncbo.py: a stored reply shape, no network."""

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def mod():
    sys.path.insert(0, str(HERE.parents[1] / "common"))
    spec = importlib.util.spec_from_file_location("run_ncbo", HERE.parent / "run_ncbo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HAY = ("## Abstract  [abstract]\n[S1] FACS showed activation.\n## Methods  [methods]\n"
       "[S2] Cells were analysed by flow cytometry.\n[S3] Plates were read on a Luminex instrument.\n")
VOCAB = {"OBI:0000916": "flow cytometry assay", "OBI:0000661": "enzyme-linked immunosorbent assay"}


def _annotated(iri, *spans):
    return {"annotatedClass": {"@id": iri},
            "annotations": [{"from": f, "to": t, "matchType": m, "text": txt} for f, t, m, txt in spans]}


def test_scoped_text_lays_sentences_out_with_offsets(mod):
    text, laid, applied = mod.scoped_text({"kind": "xml", "haystack": HAY}, "paper")
    assert text.splitlines() == ["FACS showed activation.", "Cells were analysed by flow cytometry.",
                                 "Plates were read on a Luminex instrument."]
    assert [(s["id"], s["start"], s["section"]) for s in laid] == [(1, 0, "abstract"), (2, 24, "methods"), (3, 63, "methods")]
    assert applied == "paper"


def test_methods_scope_keeps_methods_sentences_and_a_pdf_falls_back(mod):
    text, laid, applied = mod.scoped_text({"kind": "xml", "haystack": HAY}, "methods")
    assert [s["id"] for s in laid] == [2, 3] and applied == "methods"
    _, laid, applied = mod.scoped_text({"kind": "pdf", "haystack": "FACS was used. Then ELISA."}, "methods")
    assert len(laid) == 2 and applied == "paper (no headings)"


def test_class_id_reads_the_purl(mod):
    assert mod.class_id({"annotatedClass": {"@id": "http://purl.obolibrary.org/obo/OBI_0000916"}}) == "OBI:0000916"
    assert mod.class_id({"annotatedClass": {"@id": "http://purl.obolibrary.org/obo/CHMO_0000087"}}) == "CHMO:0000087"
    assert mod.class_id({"annotatedClass": {"@id": "http://example.org/not-an-obo-class"}}) is None


def test_entries_keep_vocabulary_classes_with_every_wording_and_first_sentence(mod):
    text, laid, _ = mod.scoped_text({"kind": "xml", "haystack": HAY}, "paper")
    flow_pos = text.index("flow cytometry") + 1  # the Annotator's offsets are 1-based
    raw = {"sentences": laid, "reply": [
        _annotated("http://purl.obolibrary.org/obo/OBI_0000916", (1, 4, "SYN", "FACS"),
                   (flow_pos, flow_pos + 13, "PREF", "FLOW CYTOMETRY")),
        _annotated("http://purl.obolibrary.org/obo/OBI_0000968", (10, 15, "PREF", "DEVICE")),  # not in the vocabulary
    ]}
    entries = mod.entries_from_reply(raw, VOCAB)
    assert len(entries) == 1
    e = entries[0]
    assert e["obi_id"] == "OBI:0000916" and e["names"] == ["FACS", "FLOW CYTOMETRY"]
    assert e["quote"] == "FACS showed activation." and e["section"] == "abstract"
    assert e["sentence_ids"] == [1] and e["hits"] == 2 and e["match_types"] == ["SYN", "PREF"]


def test_fetch_sends_nothing_for_an_empty_scope_and_caches_an_empty_reply(mod, tmp_path, monkeypatch):
    """SDY1669's headings carry no Methods section: the Annotator rejects an empty text (400),
    so the fetch writes an empty reply instead of asking, as the dictionary arm writes 0 entries."""
    paper = {"kind": "xml", "haystack": "## Abstract  [abstract]\n[S1] FACS showed activation.\n"}
    sent = []
    monkeypatch.setattr(mod, "api_key", lambda: "k")
    monkeypatch.setattr(mod, "registries", lambda only=None: [tmp_path / "1_SDY1669"])
    monkeypatch.setattr(mod, "paper_input", lambda d: paper)
    monkeypatch.setattr(mod, "annotate", lambda text, key: sent.append(text) or [{"annotatedClass": {"@id": "x"}}])
    monkeypatch.setattr(mod, "PAUSE_SECONDS", 0)
    mod.fetch(["methods", "paper"], raw_dir=tmp_path / "raw")
    assert len(sent) == 1 and "FACS" in sent[0]  # only the whole-paper scope was sent
    methods = mod.read(tmp_path / "raw" / "methods" / "1_SDY1669.json")
    assert methods["reply"] == [] and methods["chars"] == 0
    assert mod.read(tmp_path / "raw" / "paper" / "1_SDY1669.json")["reply"] != []


def test_run_names_skips_the_raw_reply_folder(mod, tmp_path):
    for name in ("raw", "pruned_paper", "r2", "r1"):
        (tmp_path / name).mkdir()
    assert mod.run_names(tmp_path) == ["r1", "r2", "pruned_paper"]


def test_ssl_context_is_a_default_context(mod):
    import ssl
    assert isinstance(mod._ssl_context(), ssl.SSLContext)
