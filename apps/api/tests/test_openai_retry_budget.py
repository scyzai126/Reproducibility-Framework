"""Every OpenAI client the assay chain builds carries settings.OPENAI_MAX_RETRIES.

The SDK's default is 2 retries. The chain turns a call that fails after its retries into a
soft loss -- a skipped OBI round, an ERROR record, a pair kept apart -- never a crash, so over
a corpus a short budget is paid for in quietly poorer registries. The budget is one setting so
it is set in one place, and these tests pin that each constructor reads it.
"""

import json

from app.agent import assay_fold_judge, assay_obi_mapper, claim_parser
from app.config import settings


class _Recorder:
    """Stands in for OpenAI / AsyncOpenAI and keeps the kwargs it was built with."""
    built: list[dict] = []

    def __init__(self, **kwargs):
        _Recorder.built.append(kwargs)
        self.chat = type("c", (), {"completions": self})()
        self.embeddings = self

    def create(self, **_):
        message = type("m", (), {"content": "DIFFERENT: readouts differ"})()
        choice = type("c", (), {"message": message})()
        datum = type("d", (), {"embedding": [1.0, 0.0]})()
        return type("r", (), {"choices": [choice], "data": [datum], "usage": None})()


def test_the_default_budget_is_above_the_sdk_default():
    assert settings.OPENAI_MAX_RETRIES > 2


def test_the_claim_parser_client_carries_the_budget(monkeypatch):
    monkeypatch.setattr(claim_parser, "AsyncOpenAI", _Recorder)
    monkeypatch.setattr(claim_parser, "_openai_client", None)
    _Recorder.built.clear()

    claim_parser._get_client()

    assert _Recorder.built[0]["max_retries"] == settings.OPENAI_MAX_RETRIES


def test_the_fold_judge_client_carries_the_budget(monkeypatch):
    monkeypatch.setattr(assay_fold_judge, "OpenAI", _Recorder)
    _Recorder.built.clear()

    assay_fold_judge.judge_fold("a", {}, "b", {}, "ELISA", model="m")

    assert _Recorder.built[0]["max_retries"] == settings.OPENAI_MAX_RETRIES


def test_the_obi_mapper_embedding_client_carries_the_budget(monkeypatch):
    monkeypatch.setattr(assay_obi_mapper, "OpenAI", _Recorder)
    _Recorder.built.clear()

    # A string no other test embeds: _embed_query is cached per process.
    assay_obi_mapper._embed_query("retry budget probe " + json.dumps(settings.OPENAI_MAX_RETRIES))

    assert _Recorder.built[0]["max_retries"] == settings.OPENAI_MAX_RETRIES
