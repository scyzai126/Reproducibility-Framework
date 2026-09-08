"""Run the five-pass claim abstraction over a paper, read whole.

The paper arrives as `jats_parser.parse_jats_xml` output -- Abstract, Results and Methods
as continuous text, with every figure and table legend held back until pass 2.

This replaced a path that split each paper into one <fig>/<table-wrap> panel and looped
the passes over them. Why it was dropped:
    COVERAGE. The splitter attached a Results paragraph to a panel only through an <xref>,
    which left 127 of the 30-paper corpus's 494 Results paragraphs (26%) attached to no
    panel and therefore read by no pass. parse_jats_xml keeps every paragraph, in document
    order, whatever it cites.
    CROSS-PANEL FINDINGS. "the difference in the magnitude of the SBA titers was not as
    pronounced as that of the ELISA binding titers" spans two panels. Read whole it is one
    claim; split into panels it survived in neither.
    COST. 13 LLM calls against the panel path's ~79 on the same paper, and ~190k prompt
    tokens against 1.67M. The measurement is in
    data/experiments/sdy1260_prompt_ab/comparison.md.

What is NOT given up: pass 1 still never sees a legend. The legends are withheld as one
block rather than per panel, so the two-pass reconciliation the panel architecture was
built around still runs -- see PaperDocument in app.agent.claim_abstraction_v5.

What IS given up: pass 2 must now match each claim to the right legend itself, where the
panel split did that structurally. claim_abstraction_prompt_v8.md gives it a step 0 for
exactly that, and tells it to leave a claim alone rather than guess a panel by topic.

Usage:
    python scripts/run_claim_doc.py <raw.xml> <out_dir> [--runs 5] [--prompt <file.md>]
                                    [--audit] [--dry-run]

Examples:
    python scripts/run_claim_doc.py data/JAT_XML/SDY1260_24336226.xml \
        data/claims/new_26_studies/24336226_SDY1260_filtered --runs 5

XML only. Five corpus papers PMC will not serve as full text (SDY1276/21357945,
SDY1291/23151505, SDY1293/20078211, SDY404/25367297, SDY2618/36988326) have no JATS to
parse and no path here -- a PDF route is still to be written.

Output file:
    claims.json           claim_1..N, carrying only claim, claim_type,
                          assay_method_in_paper and sources (CLAIMS_OUTPUT_FIELDS)

A full parse is this script followed by run_claim_filter.py and run_groups_noassay.py,
leaving three files in <out_dir>: claims.json, claim_filtered.json, claims_groups.json.
Nothing else is written.

--audit additionally writes two diagnostics, both otherwise only summarised on stdout:
    claims_v5_audit.json  demotions, provenance verdicts, abstract coverage, proposed
                          merges, and the sampling record
    token_usage.json      per-pass and total token counts for the run

--dry-run splits the document and prints the block sizes without making any LLM call.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_abstraction_v5 import (
    DOCUMENT_PROMPT_FILE,
    PaperDocument,
    abstract_claims_from_document,
    load_v5_prompts,
    project_claims,
    split_document,
    system_prompts,
)
from app.agent.claim_parser import _get_client
from app.config import settings


def _dry_run(doc: PaperDocument, runs: int, prompt_file: str) -> None:
    prompts = system_prompts(load_v5_prompts(prompt_file))
    print(f"prompt blocks: {', '.join(f'{k} {len(v):,} chars' for k, v in prompts.items())}")
    print(
        f"prose {len(doc.prose):,} chars   legends {len(doc.panels_block):,} chars   "
        f"abstract {len(doc.abstract):,} chars"
    )

    # The whole point of the two blocks is that pass 1 cannot see a caption. Say so here,
    # where it is free to check, rather than discovering it in the claims afterwards.
    leaked = "Caption:" in doc.prose
    print(f"legend text in the pass-1 block: {'YES — BLINDING BROKEN' if leaked else 'no'}")

    calls = 2 * runs + 3
    print(f"\n2x{runs} sampled + 1 provenance audit + 2 paper passes = {calls} LLM calls")
    pass1_in = (len(prompts["pass1"]) + len(doc.prose)) * runs
    pass2_in = (len(prompts["pass2"]) + len(doc.panels_block)) * runs
    print(f"pass-1/2 input ~{(pass1_in + pass2_in) // 4:,} tokens across all samples (rough, chars/4)")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_path", type=Path, help="the paper's JATS XML")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--runs", type=int, default=5, help="samples for passes 1-2")
    ap.add_argument("--model", default=settings.OPENAI_MODEL)
    ap.add_argument("--prompt", default=DOCUMENT_PROMPT_FILE, help="prompt document in app/prompts/")
    ap.add_argument("--dry-run", action="store_true", help="split the document only, no LLM calls")
    ap.add_argument(
        "--audit",
        action="store_true",
        help="also write claims_v5_audit.json and token_usage.json (off by default)",
    )
    args = ap.parse_args()

    if args.paper_path.suffix.lower() != ".xml":
        raise SystemExit(f"{args.paper_path}: expected a .xml paper — no PDF route yet")

    xml_text = args.paper_path.read_text(encoding="utf-8")
    # Split here as well as inside abstract_claims_from_document so a malformed paper fails
    # before the first paid call rather than after it.
    doc = split_document(xml_text)

    if args.dry_run:
        _dry_run(doc, args.runs, args.prompt)
        return

    print(
        f"Running 5-pass whole-document abstraction with {args.model}, "
        f"{args.runs} sample(s) per extraction pass, prompt {args.prompt}..."
    )
    claims, audit = await abstract_claims_from_document(
        xml_text,
        _get_client(),
        args.model,
        runs=args.runs,
        prompt_file=args.prompt,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    # Written slim; `claims` keeps its full shape for the summary below.
    (args.out_dir / "claims.json").write_text(
        json.dumps(project_claims(claims), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    usage = audit["token_usage"]
    if args.audit:
        (args.out_dir / "claims_v5_audit.json").write_text(
            json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (args.out_dir / "token_usage.json").write_text(
            json.dumps(usage, indent=2), encoding="utf-8"
        )

    record = audit["document"]
    # A near-tie decided the claim count. It matters more here than per panel: one near-tie
    # settles the whole paper rather than one figure's share of it.
    decisive = record.get("pass1_decisive", True) and record.get("pass2_decisive", True)
    print(
        f"  draft {record['draft_claims']} -> final {record['final_claims']} "
        f"(demoted {record['demoted_by_audit']}), pass1 counts {record['pass1_claim_counts']}, "
        f"pass2 {record['pass2_claim_counts']}{'' if decisive else '  << not decisive'}"
    )
    for err in record["sample_errors"]:
        print(f"  WARNING  sample failed: {err}")
    if record["audit_error"]:
        print(f"  WARNING  provenance audit failed, claims kept unaudited: {record['audit_error']}")

    coverage = audit["abstract_coverage"].get("coverage")
    polarity = Counter(c.get("polarity") for c in claims.values())
    print(f"\n{len(claims)} claims, {len(audit['not_a_claim'])} not_a_claim, abstract coverage {coverage}")
    print(f"polarity: {dict(sorted(polarity.items(), key=lambda kv: str(kv[0])))}")
    for finding in audit["abstract_coverage"].get("abstract_findings") or []:
        if finding.get("status") != "covered":
            print(f"  UNCOVERED ({finding.get('status')}): {finding.get('finding')}")
    naming = audit["claim_set_dedup"].get("naming") or []
    for group in naming:
        print(f"  naming: {group.get('field')} {group.get('variants')} -> {group.get('normalise_to')}")
    for merge in audit["claim_set_dedup"].get("merges") or []:
        print(f"  merge: keep {merge.get('keep')}, drop {merge.get('drop')} — {merge.get('reason')}")

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

    written = "claims.json"
    if args.audit:
        written += ", claims_v5_audit.json, token_usage.json"
    print(f"\nWritten to {args.out_dir}/ — {written}")


if __name__ == "__main__":
    asyncio.run(main())
