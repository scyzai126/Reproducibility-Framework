"""End-to-end run of the v9 chain with a fake client: extract once, verify, drop, correct, filter."""

import json
from unittest.mock import MagicMock

import pytest

from app.agent.claim_pipeline import OUTPUT_FIELDS, project, run_claim_pipeline

JATS = """<article>
  <front><article-meta><title-group><article-title>A vaccine trial</article-title></title-group>
    <abstract><p>We measured antibody responses in two arms.</p></abstract>
  </article-meta></front>
  <body>
    <sec><title>Results</title>
      <p>IgG rose by day 30 compared with baseline (<xref rid="F1" ref-type="fig">Fig. 1</xref>).</p>
      <p>IgG was higher at week 4 than at week 2 in the intradermal group.</p>
    </sec>
    <sec><title>Methods</title><p>IgG was measured by ELISA in serum.</p></sec>
    <fig id="F1"><label>Figure 1</label><caption><p>Antibody responses.</p></caption></fig>
  </body>
</article>"""


def _claim(sentence: str, claim_type: str, quote: str) -> dict:
    return {"claim": sentence, "claim_type": claim_type, "polarity": "affirm", "assay": "ELISA",
            "sample_type": "serum",
            "sources": [{"type": "text", "section": "Results", "quote": quote}]}


CLAIMS = [
    _claim("ELISA analysis of serum showed IgG rose by day 30 compared to baseline.",
           "induction_vs_reference", "IgG rose by day 30 compared with baseline"),
    _claim("ELISA analysis of serum showed IgG was higher at week 4 than week 2.",
           "group_difference", "IgG was higher at week 4 than at week 2 in the intradermal group."),
    _claim("ELISA analysis of serum showed baseline IgG was higher in one arm.",
           "group_difference", "IgG rose by day 30 compared with baseline"),
]


def _verification(key: str, claim: dict, identity="SUPPORTED", **flags) -> dict:
    from app.agent.claim_verifier import proposed_fields
    return {
        "claim_id": key,
        "claim_identity_verdict": identity,
        "not_a_claim_reason": "not-stated-in-words" if identity == "CONTRADICTED" else None,
        "field_verifications": [{"field_name": f, "proposed_value": v,
                                 "verdict": flags.get(f, "SUPPORTED"), "reason": "r"}
                                for f, v in proposed_fields(claim)],
    }


def _answer(messages: list[dict]) -> dict:
    """Route each call by which prompt it carries — passes 4 and 5 run concurrently."""
    text = " ".join(m["content"] for m in messages if isinstance(m["content"], str))
    if "You are in PASS 1" in text or "You are in PASS 2" in text:
        return {"claims": CLAIMS, "not_a_claim": [], "n_claims": len(CLAIMS)}
    if "You audit PROVENANCE" in text:
        return {"verdicts": [], "n_flagged": 0}
    if "COVERAGE AUDIT" in text:
        return {"abstract_findings": [], "n_uncovered": 0, "coverage": 1.0}
    if "reconcile a paper's full claim set" in text:
        return {"merges": [], "left_alone": [], "naming": [], "n_merges": 0}
    if "independent biomedical evidence verifier" in text:
        candidate = json.loads(text.split("THE CLAIM TO VERIFY:", 1)[1])
        key = next(k for k in candidate if k.startswith("claim_"))
        claim = candidate[key]
        if "baseline IgG" in claim["claim"]:
            return _verification(key, claim, identity="CONTRADICTED")
        if "week 4" in claim["claim"]:
            return _verification(key, claim, claim_type="CONTRADICTED")
        return _verification(key, claim)
    if "one specific fact" in text:
        return {"value": "induction_vs_reference", "sentence_ids": ["S2"], "reason": "r"}
    raise AssertionError(f"unrouted call: {text[:80]}")


class _Completions:
    def __init__(self):
        self.calls = 0

    async def create(self, model, messages, temperature):
        self.calls += 1
        message = MagicMock()
        message.content = json.dumps(_answer(messages))
        resp = MagicMock()
        resp.choices = [MagicMock(message=message)]
        resp.usage = None
        return resp


@pytest.mark.asyncio
async def test_pipeline_extracts_once_verifies_drops_corrects_and_filters(tmp_path):
    xml = tmp_path / "SDY1_1.xml"
    xml.write_text(JATS, encoding="utf-8")
    client = MagicMock()
    client.chat.completions = _Completions()

    out = await run_claim_pipeline(xml, client, "test-model")

    # 5 extraction + 3 verify + 1 correction (only claim_2's claim_type was flagged).
    assert client.chat.completions.calls == 9

    assert out["verification"]["summary"]["reject"] == 1
    assert "claim_3" not in out["claims"]
    assert any(e.get("claim_id") == "claim_3" for e in out["not_a_claim"])

    assert out["claims"]["claim_2"]["claim_type"] == "induction_vs_reference"
    assert out["precorrection"]["claim_2"]["claim_type"] == "group_difference"
    assert set(out["claim_filtered"]) == {"claim_1", "claim_2"}

    written = project(out["claims"])["claim_1"]
    assert tuple(written) == OUTPUT_FIELDS
    assert written["polarity"] == "affirm"
    assert written["assay_method_in_paper"] == "ELISA"
