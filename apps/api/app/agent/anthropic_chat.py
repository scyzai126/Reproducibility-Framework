"""A Claude client with the shape of the OpenAI one the assay chain already calls.

Every round of the chain does exactly three things with its client: call
`client.chat.completions.create(**kw)`, read `resp.choices[0].message.content`, and hand
`resp` to `assay_trace.usage_kw`. This module provides those three things over the Anthropic
Messages API, so a paper can be run on a Claude model without a second copy of any round.

What is translated, and why:

* `seed`, `prompt_cache_key` and `temperature` are dropped. The first two are OpenAI's; the
  current Claude models reject sampling parameters outright.
* `system` messages move to the top-level `system` field.
* `max_tokens` is required by the API and set here. A reply cut at that cap, or a refusal,
  raises `AnthropicReplyError` instead of returning partial text: every round already turns an
  exception into an ERROR record, and a truncated JSON registry must not look like a reply.
* Usage comes back under the OpenAI field names. Anthropic's `input_tokens` excludes cached
  tokens where OpenAI's `prompt_tokens` includes them, so `prompt_tokens` is the sum of the
  three input counts and `cached_tokens` is the cache read -- the subset relation
  `assay_trace.estimate_usd` assumes.

No server-side model fallback is requested: a run that silently finished on another model
could not be compared against anything. PDF file parts are not translated; the XML route is
the only one supported here.

Embeddings stay on OpenAI (`assay_obi_mapper._embed_query`): the OBI vectors on disk were
computed with its model and Anthropic has no embeddings endpoint.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic

from app.config import settings

#: Room for the longest reply in the chain (a round-1 registry) plus the model's thinking,
#: and still short enough for a non-streaming request.
MAX_TOKENS = 16000

#: Stated rather than left to the model's default, which differs between Claude models.
EFFORT = "medium"

#: chat.completions arguments with no Messages API counterpart.
_DROPPED = ("seed", "prompt_cache_key", "temperature")


class AnthropicReplyError(RuntimeError):
    """The model stopped without a complete reply (refusal, or cut at max_tokens)."""


def is_claude(model: str) -> bool:
    return model.startswith("claude")


def _text(content: Any) -> str:
    """The text of one chat message's content, which is a string or a list of parts."""
    if isinstance(content, str):
        return content
    texts = []
    for part in content:
        if part.get("type") != "text":
            raise NotImplementedError(
                f"content part {part.get('type')!r} is not translated for Claude; "
                "only the XML (text) route is supported")
        texts.append(part["text"])
    return "\n".join(texts)


def build_request(**kw: Any) -> dict[str, Any]:
    """chat.completions.create keyword arguments -> messages.create keyword arguments."""
    kw = {k: v for k, v in kw.items() if k not in _DROPPED}
    model = kw.pop("model")
    messages = kw.pop("messages")
    if kw:
        raise TypeError(f"arguments not translated for Claude: {sorted(kw)}")
    system = [_text(m["content"]) for m in messages if m["role"] == "system"]
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "output_config": {"effort": EFFORT},
        # Caches the whole request: the three round-1 calls of a paper are byte-identical.
        "cache_control": {"type": "ephemeral"},
        "messages": [{"role": m["role"], "content": _text(m["content"])}
                     for m in messages if m["role"] != "system"],
    }
    if system:
        request["system"] = "\n\n".join(system)
    return request


def to_chat_completion(message: Any) -> SimpleNamespace:
    """A Messages API response -> the three attributes the chain reads off a completion."""
    if message.stop_reason in ("refusal", "max_tokens"):
        raise AnthropicReplyError(f"stop_reason={message.stop_reason}")
    text = "".join(b.text for b in message.content if b.type == "text")
    u = message.usage
    cache_read = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    cache_write = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    usage = SimpleNamespace(
        prompt_tokens=int(u.input_tokens or 0) + cache_read + cache_write,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cache_read),
        completion_tokens=int(u.output_tokens or 0),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=usage)


class _Completions:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, **kw: Any) -> SimpleNamespace:
        return to_chat_completion(self._client.messages.create(**build_request(**kw)))


class _AsyncCompletions:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def create(self, **kw: Any) -> SimpleNamespace:
        return to_chat_completion(await self._client.messages.create(**build_request(**kw)))


class AnthropicChat:
    """Sync stand-in for `openai.OpenAI`, chat completions only."""

    def __init__(self, client: Any = None) -> None:
        client = client or anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY, max_retries=settings.OPENAI_MAX_RETRIES)
        self.chat = SimpleNamespace(completions=_Completions(client))


class AsyncAnthropicChat:
    """Async stand-in for `openai.AsyncOpenAI`, chat completions only."""

    def __init__(self, client: Any = None) -> None:
        client = client or anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY, max_retries=settings.OPENAI_MAX_RETRIES)
        self.chat = SimpleNamespace(completions=_AsyncCompletions(client))
