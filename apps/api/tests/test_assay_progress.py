"""What a run reports about itself while it is running.

The progress callback is a listener bolted onto a chain that spends money, so the tests care
less about the events being pretty than about two properties: that the calls a round reports
mid-run are the calls it reports at the end, and that nothing a listener does can cost the run
its remaining rounds.
"""

import json

import pytest

from app.agent import assay_service
from app.agent.assay_service import assay_report
from app.agent.assay_verifier import verify_registry

_XML = """<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p></sec></body></article>"""

_ENTRY = {
    "name_in_paper": "flow cytometry", "aliases": [], "platform": "LSRII",
    "sample_type": None, "readouts": "cell frequencies", "source": "methods",
    "evidence": {"section": "Methods", "sentence_ids": ["S1"],
                 "quote": "Cells were analyzed on an LSRII."},
}


@pytest.fixture(autouse=True)
def stub_obi(monkeypatch):
    """Round 4 answers from here, not from data/OBI -- see test_assay_service.py."""
    monkeypatch.setattr(assay_service, "enrich_assays_with_obi", lambda assays, *a, **k: {
        key: {**entry, "obi_id": "OBI:0000916", "obi_label": "flow cytometry assay",
              "resource": "exact_original", "obi_confidence": "high"}
        for key, entry in assays.items()})


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
    return registry_root / "111_SDY1"


class _Client:
    def __init__(self, *bodies):
        self.bodies, self.calls = list(bodies), 0
        self.chat = type("c", (), {"completions": self})()

    async def create(self, **_):
        body = self.bodies[min(self.calls, len(self.bodies) - 1)]
        self.calls += 1
        message = type("m", (), {"content": body})()
        return type("r", (), {"choices": [type("c", (), {"message": message})()]})()


def _two_assays_body() -> str:
    return json.dumps({"flow cytometry": _ENTRY, "ELISA": {**_ENTRY, "name_in_paper": "ELISA"}})


def _verification_body() -> str:
    fields = ["name_in_paper", "platform", "readouts", "source",
              "evidence.quote", "evidence.sentence_ids"]
    return json.dumps({
        "assay_id": "flow cytometry", "assay_identity_verdict": "SUPPORTED",
        "field_verifications": [{"field_name": f, "verdict": "SUPPORTED", "reason": "ok"}
                                for f in fields],
        "conflict_detected": False, "record_verdict": "ACCEPT",
    })


# ── the shape of a run, as it happens ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_round_announces_itself_before_it_spends_and_again_when_it_is_done(paper):
    """Five rounds, each opening and closing, in the order the chain runs them. A caller can
    lay out the whole run before the first call returns."""
    events = []

    await assay_report("111", "SDY1", _Client(_two_assays_body(), _verification_body()),
                       on_progress=events.append)

    opened, seen = [], set()
    for event in events:
        if event["round"] not in seen:
            seen.add(event["round"])
            opened.append((event["round"], event["state"]))
    closed = [e["round"] for e in events if e["state"] == "done"]
    assert opened == [(name, "running") for name in
                      ("extract", "verify", "correct", "obi", "canonicalize")] + [
        # Round 6 has nothing to ask about when round 5 refused no fold, and says so.
        ("judge", "skipped")]
    assert closed == ["extract", "verify", "correct", "obi", "canonicalize"]


@pytest.mark.asyncio
async def test_verifying_reports_once_per_assay_with_the_name_not_just_the_counter(paper):
    """The calls run concurrently, so the counter does not identify the assay -- which is why
    the event carries it."""
    events = []

    await assay_report("111", "SDY1", _Client(_two_assays_body(), _verification_body()),
                       on_progress=events.append)

    ticks = [e for e in events if e["round"] == "verify" and "done" in e and e["done"]]
    assert [e["done"] for e in ticks] == [1, 2]
    assert all(e["total"] == 2 for e in ticks)
    assert all(e["item"] and e["verdict"] for e in ticks)


@pytest.mark.asyncio
async def test_each_round_reports_the_same_call_count_it_ends_up_in_the_report(paper):
    """A live total and a final total that disagree are two different bills for one run."""
    events = []

    result = await assay_report("111", "SDY1",
                                _Client(_two_assays_body(), _verification_body()),
                                on_progress=events.append)

    reported = {e["round"]: e["calls"] for e in events
                if e["state"] in ("done", "skipped", "failed")}
    assert reported == {name: row["calls"] for name, row in result["rounds"].items()}
    assert sum(reported.values()) == result["meta"]["llm_calls"]


@pytest.mark.asyncio
async def test_the_rounds_that_cannot_be_watched_announce_a_total_and_no_position(paper):
    """correct_registry gathers its field calls and the OBI mapper runs in a worker thread, so
    neither can report progress. A total with no position is honest; an invented position is
    a progress bar that means nothing."""
    events = []

    await assay_report("111", "SDY1", _Client(_two_assays_body(), _verification_body()),
                       on_progress=events.append)

    for name in ("correct", "obi"):
        opening = [e for e in events if e["round"] == name and e["state"] == "running"][0]
        assert "total" in opening
        assert "done" not in opening


@pytest.mark.asyncio
async def test_a_skipped_round_says_so_rather_than_staying_silent(paper):
    """Silence reads as "still running" to anything watching."""
    events = []

    await assay_report("111", "SDY1", _Client(_two_assays_body()),
                       verify=False, correct=False, on_progress=events.append)

    skipped = {e["round"] for e in events if e["state"] == "skipped"}
    assert {"verify", "correct"} <= skipped


# ── a listener is never allowed to cost a run ─────────────────────────────────

@pytest.mark.asyncio
async def test_a_listener_that_raises_does_not_take_the_run_down_with_it(paper):
    """By the time round 3 reports, the run has already paid for rounds 1 and 2. Losing the
    rest of it to a bug in a progress display would throw that money away."""
    def _broken(_event):
        raise RuntimeError("the listener is broken")

    result = await assay_report("111", "SDY1",
                                _Client(_two_assays_body(), _verification_body()),
                                on_progress=_broken)

    assert list(result["assays"]) == ["flow cytometry assay"]
    assert result["rounds"]["canonicalize"]["source"] == "canonical"


@pytest.mark.asyncio
async def test_no_listener_is_the_behaviour_the_cli_has_always_had(paper):
    """on_progress defaults to None, and the chain must not notice."""
    client = _Client(_two_assays_body(), _verification_body())

    result = await assay_report("111", "SDY1", client)

    assert result["meta"]["llm_calls"] == client.calls == 3


# ── the verifier's own hook ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_verifier_calls_back_beside_the_line_it_prints(capsys):
    """Additive: the print stays, so the CLI is unchanged."""
    seen = []

    await verify_registry({"flow cytometry": _ENTRY, "ELISA": _ENTRY},
                          "[S1] Cells were analyzed on an LSRII.", "A Paper",
                          _Client(_verification_body()),
                          on_item=lambda done, total, result: seen.append((done, total)))

    assert seen == [(1, 2), (2, 2)]
    assert "[1/2]" in capsys.readouterr().out
