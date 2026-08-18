"""Run the five-pass panel claim abstraction over a paper's JATS XML.

Three prompt documents share the architecture and can be selected with --prompt:
    claim_abstraction_prompt_v6.md  (default) extract_claims_pdf.txt's content in v5's
                                    five-pass form: sources[], the mandatory claim head,
                                    and polarity instead of a null_result claim type
    claim_abstraction_prompt_v7.md  v6 with INDIVIDUATION rebuilt on the one-claim-one-
                                    verdict test: an over-splitting guard, the data-object
                                    split, and the reproduction-procedure diagnostic
    claim_abstraction_prompt_v5.md  the original design doc, single `quote` per claim

Usage:
    python scripts/run_claim_v5.py <raw.xml> <out_dir> [--runs 5] [--no-methods]
                                   [--panels F1,F2] [--prompt <file.md>] [--dry-run]

Example:
    python scripts/run_claim_v5.py data/claims/SDY1260_24336226_jats_figures/raw.xml \
        data/claims/new_26_studies/24336226_SDY1260_v6 --runs 5

Output files:
    claims.json           claim_1..N, one entry per surviving claim, carrying only
                          claim, claim_type, assay and sources (CLAIMS_OUTPUT_FIELDS)
    claims_v5_audit.json  demotions, provenance verdicts, abstract coverage, proposed
                          merges, the per-panel sampling record, and token usage
    token_usage.json      per-pass and total token counts for the run

--dry-run splits the panels and prints their sizes without making any LLM call.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_abstraction_v5 import (
    PROMPT_FILE,
    abstract_claims_from_jats,
    load_v5_prompts,
    project_claims,
    split_panels,
    system_prompts,
)
from app.agent.claim_parser import _get_client
from app.config import settings


def _dry_run(
    xml_text: str,
    runs: int,
    include_methods: bool,
    panel_ids: list[str] | None,
    prompt_file: str,
) -> None:
    prompts = system_prompts(load_v5_prompts(prompt_file))
    paper = split_panels(xml_text)
    print(f"prompt blocks: {', '.join(f'{k} {len(v):,} chars' for k, v in prompts.items())}")
    print(f"abstract: {len(paper.abstract):,} chars   methods: {len(paper.methods):,} chars")

    with_prose = [p for p in paper.panels if p.prose_paragraphs]
    if panel_ids:
        with_prose = [p for p in with_prose if p.panel_id in panel_ids or p.label in panel_ids]
    for p in paper.panels:
        mark = "  " if p.prose_paragraphs else "! "
        print(
            f"{mark}{p.panel_id:<4} {p.label:<12} legend {len(p.legend):>6,} chars   "
            f"prose {len(p.prose):>7,} chars ({len(p.prose_paragraphs)} para)"
        )
    methods_chars = len(paper.methods) if include_methods else 0
    per_panel = [len(prompts["pass1"]) + len(p.prose) + methods_chars for p in with_prose]
    calls = len(with_prose) * (2 * runs + 1) + 2
    print(
        f"\n{len(with_prose)} panels x (2x{runs} sampled + 1 audit) + 2 paper passes = {calls} LLM calls"
    )
    print(f"pass-1 input ~{sum(per_panel) * runs // 4:,} tokens across all samples (rough, chars/4)")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xml_path", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--runs", type=int, default=5, help="samples per panel for passes 1-2")
    ap.add_argument("--no-methods", action="store_true", help="withhold Methods from pass 1")
    ap.add_argument("--panels", default="", help="comma-separated panel ids/labels to limit to")
    ap.add_argument("--model", default=settings.OPENAI_MODEL)
    ap.add_argument("--prompt", default=PROMPT_FILE, help="prompt document in app/prompts/")
    ap.add_argument("--dry-run", action="store_true", help="split panels only, no LLM calls")
    args = ap.parse_args()

    xml_text = args.xml_path.read_text(encoding="utf-8")
    panel_ids = [s.strip() for s in args.panels.split(",") if s.strip()] or None

    if args.dry_run:
        _dry_run(xml_text, args.runs, not args.no_methods, panel_ids, args.prompt)
        return

    print(
        f"Running 5-pass abstraction with {args.model}, {args.runs} sample(s) per panel pass, "
        f"prompt {args.prompt}..."
    )
    claims, audit = await abstract_claims_from_jats(
        xml_text,
        _get_client(),
        args.model,
        runs=args.runs,
        include_methods=not args.no_methods,
        panel_ids=panel_ids,
        prompt_file=args.prompt,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    # Written slim; `claims` keeps its full shape for the summary below.
    (args.out_dir / "claims.json").write_text(
        json.dumps(project_claims(claims), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (args.out_dir / "claims_v5_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    usage = audit["token_usage"]
    (args.out_dir / "token_usage.json").write_text(
        json.dumps(usage, indent=2), encoding="utf-8"
    )

    for record in audit["panels"]:
        # A near-tie decided this panel's claim count; the mode is still used, but flag it.
        decisive = record.get("pass1_decisive", True) and record.get("pass2_decisive", True)
        split = "" if decisive else "  << not decisive"
        print(
            f"  {record['panel']:<12} draft {record['draft_claims']:>3} -> final "
            f"{record['final_claims']:>3} (demoted {record['demoted_by_audit']}), "
            f"pass1 counts {record['pass1_claim_counts']}, pass2 {record['pass2_claim_counts']}"
            f"{split}"
        )
    coverage = audit["abstract_coverage"].get("coverage")
    polarity = Counter(c.get("polarity") for c in claims.values())
    print(f"\n{len(claims)} claims, {len(audit['not_a_claim'])} not_a_claim, abstract coverage {coverage}")
    print(f"polarity: {dict(sorted(polarity.items(), key=lambda kv: str(kv[0])))}")
    naming = audit["cross_panel_dedup"].get("naming") or []
    for group in naming:
        print(f"  naming: {group.get('field')} {group.get('variants')} -> {group.get('normalise_to')}")

    print("\nTOKEN USAGE")
    print(f"  {'pass':<8}{'calls':>7}{'prompt':>12}{'cached':>12}{'completion':>13}{'total':>12}")
    for name, b in usage["by_pass"].items():
        print(
            f"  {name:<8}{b['calls']:>7}{b['prompt']:>12,}{b['cached']:>12,}"
            f"{b['completion']:>13,}{b['total']:>12,}"
        )
    t = usage["total"]
    print(
        f"  {'TOTAL':<8}{t['calls']:>7}{t['prompt']:>12,}{t['cached']:>12,}"
        f"{t['completion']:>13,}{t['total']:>12,}"
    )
    if t["prompt"]:
        print(f"  prefix-cache hit rate: {t['cached'] / t['prompt']:.1%} of prompt tokens")

    print(f"\nWritten to {args.out_dir}/ — claims.json, claims_v5_audit.json, token_usage.json")


if __name__ == "__main__":
    asyncio.run(main())
