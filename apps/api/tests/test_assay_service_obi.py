"""Round 4: mapping the assay registry onto OBI terms, after correction rather than before.

The placement is the point of most of these. Rounds 2 and 3 change what round 4 reads -- they
drop assays outright and re-extract the sample_type/readouts the OBI resolver uses as
disambiguating context -- so a mapping built from the extracted registry would resolve some
assays against values the verifier had already refused to support, and would pay to map assays
that no longer exist. Nothing in the output distinguishes the two, which is why it is pinned
here instead of left to a comment.

The mapper itself is stubbed throughout: what it decides is test_assay_obi_mapper.py's subject,
and these tests would otherwise call a real embedding endpoint.
"""

import json

import pytest

from app.agent import assay_service
from app.agent.assay_extractor import ENTRY_FIELDS, TRIMMED_FIELDS
from app.agent.assay_service import assay_report, obi_calls, obi_summary

_XML = """<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p></sec></body></article>"""


def _entry(name: str = "flow cytometry") -> dict:
    return {
        "name_in_paper": name, "aliases": [], "platform": "LSRII",
        "sample_type": None, "readouts": "cell frequencies", "source": "methods",
        "evidence": {"section": "Methods", "sentence_ids": ["S1"],
                     "quote": "Cells were analyzed on an LSRII."},
    }


@pytest.fixture
def paper(tmp_path, monkeypatch):
    xml_root, registry_root = tmp_path / "JAT_XML", tmp_path / "assay_registries"
    xml_root.mkdir()
    (xml_root / "SDY1_111.xml").write_text(_XML, encoding="utf-8")
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    # PDF_ROOT is redirected at an empty directory so the listing cannot pick up the
    # repo's real PDFs: available_papers offers PDF-only papers too.
    _pdf_root = tmp_path / "pdf"
    _pdf_root.mkdir(exist_ok=True)
    monkeypatch.setattr(assay_service, "PDF_ROOT", _pdf_root)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)
    # Not a benchmark paper (no folder under REGISTRY_ROOT), so its run lands in the cache.
    return assay_service.CACHE_ROOT / "111_SDY1"


@pytest.fixture
def seen(monkeypatch):
    """Record what round 4 was handed, and answer without calling anything."""
    calls: list[dict] = []

    def _fake(assays, *_args, **_kwargs):
        calls.append(dict(assays))
        return {key: {**entry, "normalized_name": key, "obi_id": "OBI:0000916",
                      "obi_label": "flow cytometry assay", "resource": "exact_original",
                      "obi_confidence": "high"}
                for key, entry in assays.items()}

    monkeypatch.setattr(assay_service, "enrich_assays_with_obi", _fake)
    return calls


class _Client:
    """Answers by reading the prompt, not by counting calls.

    Round 2 verifies up to 8 assays concurrently, so with more than one assay the order the
    calls arrive in is not fixed and a positional fixture answers the wrong question roughly
    half the time. Each prompt opens with the role its own file declares, and the verifier's
    carries the assay it is judging, which is enough to route on.
    """

    def __init__(self, extraction: str, verdicts: dict | None = None, correction: str = "{}"):
        self.extraction, self.verdicts = extraction, dict(verdicts or {})
        self.correction, self.calls = correction, 0
        self.chat = type("c", (), {"completions": self})()

    def _route(self, prompt: str) -> str:
        if prompt.startswith("You are an independent biomedical evidence verifier"):
            for name, body in self.verdicts.items():
                # The candidate block, not a bare name: verify_assays.txt uses "flow cytometry"
                # and "ELISA" in its own worked examples, so a substring test on the name alone
                # matches every prompt and answers whichever assay happens to be listed first.
                # assay_verifier interpolates json.dumps({key: entry}, indent=2).
                if f'  "{name}": {{' in prompt:
                    return body
            raise AssertionError(f"no canned verdict for this prompt: {prompt[:200]!r}")
        if prompt.startswith("You are a biomedical information extractor"):
            return self.correction
        return self.extraction

    async def create(self, **kwargs):
        self.calls += 1
        body = self._route(kwargs["messages"][0]["content"])
        message = type("m", (), {"content": body})()
        return type("r", (), {"choices": [type("c", (), {"message": message})()]})()


#: What extract_assays.txt asks for, and therefore what a judge is expected to answer about.
#: A field left out of a verdict comes back NOT_REPORTED and is queued for re-extraction, so a
#: fixture that answers for fewer fields silently bills round 3 for the rest.
_PROPOSED = ("name_in_paper", "platform", "readouts", "source",
             "evidence.quote", "evidence.sentence_ids")


def _verdict(assay_id: str, identity: str = "SUPPORTED", **overrides: str) -> dict:
    """A verdict answering for every proposed field, SUPPORTED unless overridden.

    `record_verdict` is set but not load-bearing: assay_verifier.derive_record_verdict
    re-derives it from the identity and field verdicts rather than trusting the model, so a
    fixture asking for a REJECT has to say CONTRADICTED on the identity, which is the only
    thing that reaches REJECT.
    """
    fields = [{"field_name": f, "verdict": overrides.get(f.replace(".", "_"), "SUPPORTED"),
               "reason": "ok"} for f in _PROPOSED]
    return {
        "assay_id": assay_id, "assay_identity_verdict": identity,
        "field_verifications": fields, "conflict_detected": False,
        "record_verdict": "REJECT" if identity == "CONTRADICTED" else "ACCEPT",
    }


# ── where the round sits ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_mapping_reads_the_corrected_registry_not_the_extracted_one(paper, seen):
    """Round 3 replaced `readouts`; the mapper must see the repaired value.

    `readouts` and `sample_type` are what prompts/resolver_obi_assay.txt uses to choose
    between candidates that already match the name, so handing it the extracted value is
    how an assay ends up resolved against something the verifier refused to support.
    """
    client = _Client(
        json.dumps({"flow cytometry": _entry()}),
        {"flow cytometry": json.dumps(_verdict("flow cytometry", readouts="NOT_SUPPORTED"))},
        # assay_corrector.correct_field reads parsed["value"], whatever field it asked about.
        correction=json.dumps({"value": "phosphorylation levels"}),
    )

    result = await assay_report("111", "SDY1", client)

    # Round 5 re-keys the finished registry by its OBI term; round 4 still saw the paper's
    # wording, which is what `seen` records.
    assert result["assays"]["flow cytometry assay"]["readouts"] == "phosphorylation levels"
    assert seen, "round 4 never ran"
    assert seen[0]["flow cytometry"]["readouts"] == "phosphorylation levels", (
        "round 4 was handed the pre-correction registry"
    )


@pytest.mark.asyncio
async def test_an_assay_the_judge_rejected_is_never_mapped(paper, seen):
    """drop_rejected removes it in round 3, so round 4 must not pay to map it."""
    client = _Client(
        json.dumps({"flow cytometry": _entry(), "ELISA": _entry("ELISA")}),
        {"flow cytometry": json.dumps(_verdict("flow cytometry")),
         "ELISA": json.dumps(_verdict("ELISA", identity="CONTRADICTED"))},
    )

    result = await assay_report("111", "SDY1", client)

    assert "ELISA" in result["dropped"]
    assert "flow cytometry" in seen[0]
    assert "ELISA" not in seen[0], "a rejected assay was still sent to the mapper"


# ── what it writes, and what it must not touch ────────────────────────────────

@pytest.mark.asyncio
async def test_the_mapping_lands_in_its_own_file(paper, seen):
    client = _Client(json.dumps({"flow cytometry": _entry()}),
                     {"flow cytometry": json.dumps(_verdict("flow cytometry"))})

    result = await assay_report("111", "SDY1", client)

    written = json.loads((paper / "assays_OBI.json").read_text(encoding="utf-8"))
    assert written["flow cytometry assay"]["obi_id"] == "OBI:0000916"
    assert result["obi"] == written
    assert result["meta"]["obi_path"].endswith("assays_OBI.json")


@pytest.mark.asyncio
async def test_enrichment_does_not_leak_into_the_registry_or_the_deliverable(paper, seen):
    """The OBI keys are not in ENTRY_FIELDS, so a merged registry would fail its own contract.

    assays.json stays at seven fields and assays_benchmark.json at four; the ontology lives
    beside them, not inside them.
    """
    client = _Client(json.dumps({"flow cytometry": _entry()}),
                     {"flow cytometry": json.dumps(_verdict("flow cytometry"))})

    await assay_report("111", "SDY1", client)

    registry = json.loads((paper / "assays.json").read_text(encoding="utf-8"))
    benchmark = json.loads((paper / "assays_benchmark.json").read_text(encoding="utf-8"))
    assert set(registry["flow cytometry assay"]) == set(ENTRY_FIELDS)
    assert set(benchmark["flow cytometry assay"]) == set(TRIMMED_FIELDS)


# ── failing soft ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_mapping_failure_does_not_throw_away_a_paid_run(paper, monkeypatch):
    """Rounds 1-3 are already on disk and already billed when round 4 starts.

    Raising here would lose 1+N+F calls to an ontology lookup, and every input round 4 needs
    is persisted -- so scripts/run_assay_merge.py --map can finish the job without re-paying.
    """
    def _boom(*_args, **_kwargs):
        raise RuntimeError("no embeddings")

    monkeypatch.setattr(assay_service, "enrich_assays_with_obi", _boom)
    client = _Client(json.dumps({"flow cytometry": _entry()}),
                     {"flow cytometry": json.dumps(_verdict("flow cytometry"))})

    result = await assay_report("111", "SDY1", client)

    assert result["rounds"]["obi"] == {"source": "failed", "calls": 0}
    assert result["obi"] is None
    assert result["meta"]["obi_path"] is None
    assert not (paper / "assays_OBI.json").exists()
    for name in ("assays.json", "assays_verification.json", "assays_benchmark.json"):
        assert (paper / name).exists(), f"{name} was lost to an OBI failure"


@pytest.mark.asyncio
async def test_a_failed_mapping_does_not_leave_the_previous_runs_mapping_behind(paper, monkeypatch):
    """A stale assays_OBI.json beside a new registry was served as this run's mapping, keyed by
    labels the new registry does not have."""
    paper.mkdir(parents=True)
    (paper / "assays_OBI.json").write_text('{"old assay": {"obi_id": "OBI:9"}}')
    (paper / "assays_merges.json").write_text('{"summary": {}, "results": []}')

    def _boom(*_args, **_kwargs):
        raise RuntimeError("no embeddings")

    monkeypatch.setattr(assay_service, "enrich_assays_with_obi", _boom)
    client = _Client(json.dumps({"flow cytometry": _entry()}),
                     {"flow cytometry": json.dumps(_verdict("flow cytometry"))})

    await assay_report("111", "SDY1", client)

    assert not (paper / "assays_OBI.json").exists()
    assert not (paper / "assays_merges.json").exists()


@pytest.mark.asyncio
async def test_a_run_that_dies_after_extraction_leaves_no_registry_that_looks_verified(
        paper, monkeypatch):
    """assays.json is written last. Written at round 1, a crash in round 2 left an unverified
    registry that nothing on disk told apart from a verified one."""
    paper.mkdir(parents=True)
    (paper / "assays.json").write_text('{"old assay": {}}')
    (paper / "assays_benchmark.json").write_text('{"old assay": {}}')

    async def _dies(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(assay_service, "verify_registry", _dies)
    client = _Client(json.dumps({"flow cytometry": _entry()}), {})

    with pytest.raises(KeyboardInterrupt):
        await assay_report("111", "SDY1", client)

    assert not (paper / "assays.json").exists()
    assert not (paper / "assays_benchmark.json").exists()
    assert "flow cytometry" in json.loads((paper / "assays_precorrection.json").read_text())


def test_an_errored_lookup_is_reported_apart_from_a_vocabulary_gap():
    summary = obi_summary({"a": {"obi_id": None, "resource": "unresolved"},
                           "b": {"obi_id": None, "resource": "error", "obi_error": "Timeout"}})

    assert summary["unresolved"] == ["a", "b"]
    assert summary["errors"] == {"b": "Timeout"}


@pytest.mark.asyncio
async def test_an_empty_registry_skips_the_round(paper, seen):
    client = _Client("{}")

    result = await assay_report("111", "SDY1", client)

    assert result["rounds"]["obi"] == {"source": "skipped", "calls": 0}
    assert not seen, "the mapper was called with nothing to map"


# ── accounting ────────────────────────────────────────────────────────────────

def test_only_the_names_the_vocabulary_missed_are_billed():
    """The exact match is a dict lookup; the embedding round costs an embedding plus a chat call.

    "exact_normalized" is billed rather than exempted: the lexical round that produced it was
    removed, so a registry still carrying that value was mapped by older code and re-running it
    now pays. Treating it as free here would under-report the bill.
    """
    assert obi_calls({
        "a": {"resource": "exact_original"},
        "b": {"resource": "exact_normalized"},
        "c": {"resource": "embedding_llm"},
    }) == 4


def test_an_assay_the_llm_declined_is_billed_like_one_it_matched():
    """"unresolved" means the model was asked and said none -- the two calls were spent."""
    assert obi_calls({"a": {"resource": "unresolved"}}) == 2


def test_the_summary_names_the_assays_that_did_not_resolve():
    """A total tells you coverage; the name tells you whether it is a vocabulary gap."""
    summary = obi_summary({
        "flow cytometry": {"obi_id": "OBI:0000916", "resource": "exact_original"},
        "bespoke readout": {"obi_id": None, "resource": "unresolved"},
    })

    assert summary["mapped"] == 1
    assert summary["total"] == 2
    assert summary["unresolved"] == ["bespoke readout"]
    assert summary["resources"] == {"exact_original": 1, "unresolved": 1}


def test_a_normalized_exact_match_is_billed_as_free():
    """Step 1b is a dict lookup, not a call.

    The first real run of the eighth field billed a 4-assay paper 8 calls for an OBI round
    that made none: every entry resolved via `exact_normalized_llm`, which obi_calls did not
    yet know was a free tier. Any future free resource has to be added to
    _OBI_FREE_RESOURCES as well, or it is silently billed at the paid rate.
    """
    from app.agent.assay_service import obi_calls

    assert obi_calls({"a": {"resource": "exact_normalized_llm"}}) == 0
    assert obi_calls({"a": {"resource": "exact_original"}}) == 0
    assert obi_calls({"a": {"resource": "embedding_llm"}}) == 2
    assert obi_calls({"a": {"resource": "embedding_llm_normalized"}}) == 2
    assert obi_calls({"a": {"resource": "unresolved"}}) == 2
