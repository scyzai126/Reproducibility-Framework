"""Experiment Arm B — JATS parser output, read panel-by-panel with the v6 pass structure.

Pass 1 drafts claims from the Results prose alone (legend withheld); pass 2 hands the model
its own draft plus the figure legend and asks it to reconcile. Panels run concurrently.

Usage:
    python scripts/exp_run_arm_b.py data/claims/SDY1260_24336226_jats_figures/raw.xml \
        data/experiments/sdy1260_prompt_ab/arm_B
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_abstraction_v5 import Panel, build_pass1_user_message, split_panels
from app.agent.claim_parser import _get_client, _strip_fences
from app.config import settings

PROMPTS = Path(__file__).resolve().parent.parent / "apps" / "api" / "app" / "prompts"


def build_prompts() -> tuple[str, str]:
    core = (PROMPTS / "exp_shared_core.txt").read_text(encoding="utf-8")
    p1 = (PROMPTS / "exp_arm_b_pass1.txt").read_text(encoding="utf-8").replace("{SHARED_CORE}", core)
    p2 = (PROMPTS / "exp_arm_b_pass2.txt").read_text(encoding="utf-8").replace("{SHARED_CORE}", core)
    return p1, p2


def _claims_of(raw: str) -> dict:
    return {k: v for k, v in json.loads(_strip_fences(raw.strip())).items() if k.startswith("claim_")}


async def run_panel(
    panel: Panel, methods: str, sys1: str, sys2: str, client, model: str
) -> tuple[str, dict, dict, dict]:
    """Pass 1 (prose only) then pass 2 (draft + legend) for one panel."""
    r1 = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": sys1},
            {"role": "user", "content": f"PANEL: {panel.label}\n\n{build_pass1_user_message(panel, methods)}"},
        ],
        temperature=0,
    )
    draft = _claims_of(r1.choices[0].message.content or "")

    r2 = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": sys2},
            {
                "role": "user",
                "content": (
                    f"PANEL: {panel.label}\n\n"
                    f"YOUR PASS 1 DRAFT CLAIMS:\n{json.dumps(draft, indent=2, ensure_ascii=False)}\n\n"
                    f"FIGURE LEGEND (withheld until now):\n{panel.legend}\n\n"
                    f"RESULTS TEXT (unchanged):\n{panel.prose}"
                ),
            },
        ],
        temperature=0,
    )
    final = _claims_of(r2.choices[0].message.content or "")

    usage = {
        "pass1_prompt": r1.usage.prompt_tokens,
        "pass1_completion": r1.usage.completion_tokens,
        "pass2_prompt": r2.usage.prompt_tokens,
        "pass2_completion": r2.usage.completion_tokens,
    }
    print(f"  {panel.label:<12} pass1 {len(draft):>3} -> pass2 {len(final):>3} claims")
    return panel.label, draft, final, usage


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xml_path", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--model", default=settings.OPENAI_MODEL)
    ap.add_argument("--panels", default="", help="comma-separated panel labels to limit to")
    args = ap.parse_args()

    sys1, sys2 = build_prompts()
    paper = split_panels(args.xml_path.read_text(encoding="utf-8"))
    panels = [p for p in paper.panels if p.prose_paragraphs]
    wanted = [s.strip() for s in args.panels.split(",") if s.strip()]
    if wanted:
        panels = [p for p in panels if p.panel_id in wanted or p.label in wanted]

    print(f"Arm B: {len(panels)} panels with prose, model {args.model}")
    print(f"pass1 prompt {len(sys1):,} chars, pass2 prompt {len(sys2):,} chars")

    client = _get_client()
    results = await asyncio.gather(
        *(run_panel(p, paper.methods, sys1, sys2, client, args.model) for p in panels)
    )

    claims: dict = {}
    per_panel: list[dict] = []
    totals = {"pass1_prompt": 0, "pass1_completion": 0, "pass2_prompt": 0, "pass2_completion": 0}
    n = 0
    for label, draft, final, usage in results:
        for value in final.values():
            n += 1
            claims[f"claim_{n}"] = {**value, "panel_source": label}
        per_panel.append({"panel": label, "pass1_claims": len(draft), "pass2_claims": len(final)})
        for k in totals:
            totals[k] += usage[k]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "claims.json").write_text(
        json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (args.out_dir / "panels.json").write_text(json.dumps(per_panel, indent=2), encoding="utf-8")
    (args.out_dir / "token_usage.json").write_text(json.dumps(totals, indent=2), encoding="utf-8")

    print(f"\n{len(claims)} claims -> {args.out_dir}/claims.json")
    print(
        f"tokens: pass1 {totals['pass1_prompt']:,}+{totals['pass1_completion']:,}  "
        f"pass2 {totals['pass2_prompt']:,}+{totals['pass2_completion']:,}"
    )


if __name__ == "__main__":
    asyncio.run(main())
