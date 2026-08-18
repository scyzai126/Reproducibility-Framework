"""Experiment Arm A — whole-PDF, prose + panel + legend read together in one pass.

Sends the complete PDF to the model with exp_arm_a_wholepdf.txt and writes claims.json.

Usage:
    python scripts/exp_run_arm_a.py data/pdf/26papers/SDY1260_24336226.pdf \
        data/experiments/sdy1260_prompt_ab/arm_A
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.agent.pdf_direct import _pdf_file_content
from app.config import settings

PROMPTS = Path(__file__).resolve().parent.parent / "apps" / "api" / "app" / "prompts"


def build_prompt() -> str:
    core = (PROMPTS / "exp_shared_core.txt").read_text(encoding="utf-8")
    return (PROMPTS / "exp_arm_a_wholepdf.txt").read_text(encoding="utf-8").replace(
        "{SHARED_CORE}", core
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_path", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--model", default=settings.OPENAI_MODEL)
    args = ap.parse_args()

    system_prompt = build_prompt()
    pdf_bytes = args.pdf_path.read_bytes()
    print(f"Arm A: {args.pdf_path.name} ({len(pdf_bytes):,} bytes), model {args.model}")
    print(f"system prompt {len(system_prompt):,} chars")

    client = _get_client()
    resp = await client.chat.completions.create(
        model=args.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    _pdf_file_content(pdf_bytes, args.pdf_path.name),
                    {
                        "type": "text",
                        "text": (
                            "Extract every claim this paper makes, as instructed. Read the Results "
                            "prose, the figure/table panels and their legends together before drafting."
                        ),
                    },
                ],
            },
        ],
        temperature=0,
    )

    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    claims = {k: v for k, v in json.loads(raw).items() if k.startswith("claim_")}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "claims.json").write_text(
        json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    u = resp.usage
    usage = {"prompt": u.prompt_tokens, "completion": u.completion_tokens, "total": u.total_tokens}
    (args.out_dir / "token_usage.json").write_text(json.dumps(usage, indent=2), encoding="utf-8")

    print(f"\n{len(claims)} claims -> {args.out_dir}/claims.json")
    print(f"tokens: prompt {usage['prompt']:,}  completion {usage['completion']:,}")


if __name__ == "__main__":
    asyncio.run(main())
