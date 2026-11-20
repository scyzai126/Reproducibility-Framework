"""The Claude adapter: request translation, reply/usage translation, and the stop reasons."""
import asyncio
from types import SimpleNamespace

import pytest

from app.agent import anthropic_chat, assay_trace
from app.agent.anthropic_chat import (
    AnthropicChat,
    AnthropicReplyError,
    AsyncAnthropicChat,
    build_request,
    is_claude,
    to_chat_completion,
)


def _message(text="ok", stop_reason="end_turn", **usage):
    usage = {"input_tokens": 10, "output_tokens": 5, **usage}
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(**usage),
    )


class _FakeMessages:
    def __init__(self, message):
        self.message, self.calls = message, []

    def create(self, **kw):
        self.calls.append(kw)
        return self.message


class _FakeAsyncMessages(_FakeMessages):
    async def create(self, **kw):
        return super().create(**kw)


def test_is_claude():
    assert is_claude("claude-opus-5-5")
    assert not is_claude("gpt-5.4")


def test_build_request_drops_openai_only_arguments():
    req = build_request(model="claude-opus-5-5", temperature=0, seed=7, prompt_cache_key="k",
                        messages=[{"role": "user", "content": "hi"}])
    assert req["model"] == "claude-opus-5-5"
    assert req["messages"] == [{"role": "user", "content": "hi"}]
    assert req["max_tokens"] == anthropic_chat.MAX_TOKENS
    assert req["output_config"] == {"effort": anthropic_chat.EFFORT}
    assert not {"temperature", "seed", "prompt_cache_key", "system"} & set(req)


def test_build_request_moves_system_message_to_top_level():
    req = build_request(model="claude-opus-5-5", messages=[
        {"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}])
    assert req["system"] == "rules"
    assert req["messages"] == [{"role": "user", "content": "hi"}]


def test_build_request_rejects_an_untranslated_argument():
    with pytest.raises(TypeError):
        build_request(model="claude-opus-5-5", messages=[], response_format={"type": "json"})


def test_build_request_rejects_a_pdf_file_part():
    with pytest.raises(NotImplementedError):
        build_request(model="claude-opus-5-5", messages=[{"role": "user", "content": [
            {"type": "file", "file": {"filename": "p.pdf", "file_data": "data:..."}}]}])


def test_reply_text_skips_thinking_blocks():
    resp = to_chat_completion(_message("the reply"))
    assert resp.choices[0].message.content == "the reply"


def test_usage_is_reported_in_the_shape_assay_trace_reads():
    resp = to_chat_completion(_message(
        input_tokens=100, cache_read_input_tokens=900, cache_creation_input_tokens=50,
        output_tokens=40))
    assert assay_trace.usage_fields(resp) == {
        "prompt": 1050, "cached": 900, "completion": 40, "reasoning": 0}


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_an_incomplete_reply_raises(stop_reason):
    with pytest.raises(AnthropicReplyError):
        to_chat_completion(_message(stop_reason=stop_reason))


def test_sync_client_calls_messages_create():
    fake = SimpleNamespace(messages=_FakeMessages(_message("pick 3")))
    resp = AnthropicChat(fake).chat.completions.create(
        model="claude-opus-5-5", messages=[{"role": "user", "content": "q"}], temperature=0)
    assert resp.choices[0].message.content == "pick 3"
    assert "temperature" not in fake.messages.calls[0]


def test_async_client_calls_messages_create():
    fake = SimpleNamespace(messages=_FakeAsyncMessages(_message("[]")))
    resp = asyncio.run(AsyncAnthropicChat(fake).chat.completions.create(
        model="claude-opus-5-5", messages=[{"role": "user", "content": "q"}], seed=7))
    assert resp.choices[0].message.content == "[]"
    assert "seed" not in fake.messages.calls[0]
