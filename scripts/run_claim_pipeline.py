"""Claim abstraction v9: the five v8 passes once each, then verify -> correct, like assays.

The chain is app.agent.claim_pipeline.run_claim_pipeline; this is its CLI. The existing
five-sample path (run_claim_doc.py) is untouched.

Usage:
    python3 scripts/run_claim_pipeline.py <raw.xml> <out_dir> [--dry-run] [--audit]

Example:
    python3 scripts/run_claim_pipeline.py data/JAT_XML/SDY1364_23266342.xml \
        data/experiments/sdy1364_sampling_vs_verify/arm_C_v9 --dry-run

Output files (a rerun overwrites them in place):
    claims_precorrection.json   every field pass 2 wrote, as extracted
    claims_verification.json    per-field verdicts and ACCEPT / REVIEW / REJECT per claim
    claims_corrections.json     REAFFIRMED / REPLACED / CLEARED per flagged field
    claims.json                 the corrected claims: claim, claim_type, assay_method_in_paper,
                                sources, polarity
    claim_filtered.json         the downstream-actionable subset, filtered on corrected types
    not_a_claim.json            pass 1-3 demotions, REJECTs, and findings a correction cleared
    --audit adds claims_v9_audit.json (coverage, pass-5 proposals, token usage)

--dry-run makes no API call. The claim count is not known until extraction has run, so the
estimate is 5 calls + 1 per claim + 1 per flagged field.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_abstraction_v5 import split_document  # noqa: E402
from app.agent.claim_parser import _get_client  # noqa: E402
from app.agent.claim_pipeline import EXTRACTION_CALLS, project, run_claim_pipeline  # noqa: E402
from app.config import settings  # noqa: E402


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _report(out: dict) -> None:
    verification = out["verification"]
    for r in verification["results"]:
        if r["record_verdict"] == "ACCEPT":
            continue
        issues = [f"{v['field_name']} {v['verdict']}" for v in r["field_verifications"]
                  if v["verdict"] != "SUPPORTED"]
        why = r.get("not_a_claim_reason") or "; ".join(issues) or r.get("error", "")
        print(f"  {r['record_verdict']:<7}{r['claim_id']}: {why}")

    for record in out["corrections"]["results"]:
        for change in record["corrections"]:
            if change["action"] in ("REPLACED", "CLEARED", "ERROR"):
                print(f"  {change['action']:<9}{record['claim_id']} / {change['field']}: "
                      f"{change.get('previous')!r} -> {change.get('blind_answer')!r}")
            if change.get("note"):
                print(f"  WARNING  {record['claim_id']} / {change['field']}: {change['note']}")
        for flag in record["reported_not_corrected"]:
            print(f"  REVIEW   {record['claim_id']} / {flag['field_name']}: {flag['reason']}")

    for entry in out["not_a_claim"]:
        if entry.get("from") in ("verification", "correction"):
            print(f"  DROPPED  {entry['claim_id']} ({entry['reason']}): {entry['text'][:110]}")

    s = verification["summary"]
    print(f"\nverified {s['total']}: {s['accept']} ACCEPT, {s['review']} REVIEW, "
          f"{s['reject']} REJECT, {s['errors']} ERROR")
    print(f"corrections: {out['corrections']['summary']['actions']}")
    print(f"{len(out['claims'])} claims kept, {len(out['claim_filtered'])} after the filter "
          f"(dropped types {out['filter_dropped']})")

    t = out["audit"]["token_usage"]["total"]
    print(f"\nTOKEN USAGE  {t['calls']} calls, {t['prompt']:,} prompt ({t['cached']:,} cached), "
          f"{t['completion']:,} completion, {t['total']:,} total")
    for name, b in out["audit"]["token_usage"]["by_pass"].items():
        print(f"  {name:<8}{b['calls']:>5} calls {b['total']:>10,} tokens")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_path", type=Path, help="the paper's JATS XML")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--model", default=settings.OPENAI_MODEL)
    ap.add_argument("--dry-run", action="store_true", help="estimate only, no LLM calls")
    ap.add_argument("--audit", action="store_true", help="also write claims_v9_audit.json")
    args = ap.parse_args()

    if args.paper_path.suffix.lower() != ".xml":
        raise SystemExit(f"{args.paper_path}: expected a .xml paper")
    # Split before any paid call, so a malformed paper fails for free.
    doc = split_document(args.paper_path.read_text(encoding="utf-8"))

    if args.dry_run:
        print(f"prose {len(doc.prose):,} chars, legends {len(doc.panels_block):,} chars")
        print(f"{EXTRACTION_CALLS} extraction calls (passes 1-5, one each)")
        print("+ 1 verify call per extracted claim + 1 correct call per flagged field group")
        print("  (a ~15-claim paper is roughly 5 + 15 + 5-10 = 25-30 calls)")
        return

    out = await run_claim_pipeline(args.paper_path, _get_client(), args.model)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write(args.out_dir / "claims_precorrection.json", out["precorrection"])
    _write(args.out_dir / "claims_verification.json", out["verification"])
    _write(args.out_dir / "claims_corrections.json", out["corrections"])
    _write(args.out_dir / "claims.json", project(out["claims"]))
    _write(args.out_dir / "claim_filtered.json", out["claim_filtered"])
    _write(args.out_dir / "not_a_claim.json", out["not_a_claim"])
    if args.audit:
        _write(args.out_dir / "claims_v9_audit.json", out["audit"])

    print()
    _report(out)
    print(f"\nWritten to {args.out_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
