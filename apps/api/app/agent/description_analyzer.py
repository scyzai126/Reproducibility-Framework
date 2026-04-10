import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "description_analyzer.txt"
_openai_client: AsyncOpenAI | None = None


def _get_system_prompt() -> str:
    """Read prompt from disk each time so edits take effect without restart."""
    return _PROMPT_FILE.read_text(encoding="utf-8").strip()


def _get_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


async def analyze_descriptions(descriptions_text: str) -> tuple[list[dict], str]:
    """Use OpenAI to extract structured metadata from paper descriptions.

    Args:
        descriptions_text: Formatted descriptions string from format_descriptions_for_llm().

    Returns:
        Tuple of (parsed groups list, raw LLM response string).
    """
    if not descriptions_text:
        return [], ""

    system_prompt = _get_system_prompt()
    client = _get_client()

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": descriptions_text},
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    raw_for_log = raw  # preserve original before stripping fences
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]

    result = json.loads(raw)
    logger.info("Description analysis completed: %d groups", len(result))

    return result, raw_for_log


async def analyze_claims_batch(batch_text: str) -> tuple[dict[str, list[dict]], str]:
    """Analyze all claims in a single LLM call.

    Args:
        batch_text: All claims formatted by format_claims_batch_for_llm().

    Returns:
        Tuple of (mapping of claim_id str → groups list, raw LLM response string).
    """
    if not batch_text:
        return {}, ""

    system_prompt = _get_system_prompt()
    client = _get_client()

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": batch_text},
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    raw_for_log = raw
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]

    result = json.loads(raw)
    total_groups = sum(len(v) for v in result.values() if isinstance(v, list))
    logger.info("Batch analysis completed: %d claims, %d total groups", len(result), total_groups)

    return result, raw_for_log
