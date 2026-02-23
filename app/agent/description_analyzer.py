import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "description_analyzer.txt"
SYSTEM_PROMPT = _PROMPT_FILE.read_text(encoding="utf-8").strip()


async def analyze_descriptions(descriptions_text: str) -> list[dict]:
    """Use OpenAI to extract structured metadata from paper descriptions.

    Args:
        descriptions_text: Formatted descriptions string from format_descriptions_for_llm().

    Returns:
        List of dicts with structured metadata per participant group.
    """
    if not descriptions_text:
        return []

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": descriptions_text},
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]

    result = json.loads(raw)
    logger.info("Description analysis completed: %d groups", len(result))

    return result
