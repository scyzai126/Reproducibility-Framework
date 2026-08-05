"""Judge the accuracy of every claim in an already-extracted study directory.

Reads <study_dir>/claim_filtered.json and writes <study_dir>/claims_validation.json. No
extraction is re-run — the claims themselves are left untouched.

Two passes:
  * closed-book, one call per claim, judging the biological finding against the quotes
    already recorded in that claim's `sources`, and the claim_type label against the
    vocabulary the extraction step assigned it from;
  * metadata, a handful of calls carrying the PDF, auditing each claim's contextual
    metadata (assay, tissue, sample size, age, cohort, day schedule) against the paper —
    Methods included, since that is where those fields come from and why the closed-book
    pass cannot see them.

The PDF is located by convention from the study directory name; pass --pdf to override, or
--no-metadata to skip that pass and emit the closed-book checks alone.

Use --limit to smoke-test the prompts on a few claims before paying for a whole paper.

Usage:
    python scripts/run_claim_validate.py <study_dir> [--pdf PATH] [--no-metadata] [--limit N]

Example:
    python scripts/run_claim_validate.py data/claims/SDY1669_PMC7665312_pdf --limit 3
"""

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import _get_client
from app.agent.claim_validator import (
    _METADATA_BATCH_SIZE,
    build_report,
    metadata_entries,
    validate_claims_file,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PDF_ROOT = _REPO_ROOT / "data" / "pdf"
_DIR_SUFFIXES = ("_pdf", "_xml", "_jats_xml", "_jats_figures")


def _locate_pdf(study_dir: Path) -> Path | None:
    """Find the paper for a study directory by naming convention.

    `data/claims/SDY1119_26682988_pdf` -> `data/pdf/**/SDY1119_26682988.pdf`.
    """
    stem = study_dir.resolve().name
    for suffix in _DIR_SUFFIXES:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    matches = sorted(_PDF_ROOT.glob(f"**/{stem}.pdf"))
    return matches[0] if matches else None


async def main(study_dir: Path, limit: int | None, pdf_path: Path | None, use_metadata: bool) -> None:
    claims_path = study_dir / "claim_filtered.json"
    if not claims_path.exists():
        print(
            f"No claim_filtered.json in {study_dir}\n"
            "Directories extracted before the claim filter existed can be backfilled for "
            f"free: python scripts/run_claim_filter.py {study_dir}"
        )
        sys.exit(1)

    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claim_keys = [k for k in claims if k.startswith("claim_")]
    if limit is not None:
        claim_keys = claim_keys[:limit]

    pdf_bytes = None
    if use_metadata:
        if pdf_path is None:
            pdf_path = _locate_pdf(study_dir)
        if pdf_path is None or not pdf_path.exists():
            print(
                f"No PDF found for {study_dir.name}"
                + (f" at {pdf_path}" if pdf_path is not None else f" under {_PDF_ROOT}")
                + ".\nThe metadata pass needs the paper: pass --pdf PATH, or --no-metadata "
                "to run the closed-book checks alone."
            )
            sys.exit(1)
        pdf_bytes = pdf_path.read_bytes()

    total = len([k for k in claims if k.startswith("claim_")])
    scope = f"the first {len(claim_keys)}" if limit is not None else "all"
    cost = f"{len(claim_keys)} closed-book calls"
    if pdf_bytes is not None:
        heads = len(metadata_entries(claims, claim_keys))
        batches = math.ceil(heads / _METADATA_BATCH_SIZE)
        cost += f" + {batches} metadata call(s) carrying {pdf_path.name} ({heads} distinct heads)"
    print(f"{total} claims in {claims_path.name}; validating {scope} — costs {cost}.")

    results = await validate_claims_file(
        claims,
        _get_client(),
        limit=limit,
        pdf_bytes=pdf_bytes,
        filename=pdf_path.name if pdf_path else "paper.pdf",
    )
    report = build_report(results)

    out_path = study_dir / "claims_validation.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = report["summary"]
    print(
        f"\n{summary['accurate']}/{summary['total']} accurate, "
        f"{summary['needs_revision']} need revision, "
        f"{summary['inconclusive']} inconclusive, {summary['errors']} errors"
    )
    if not summary["metadata_checked"]:
        print("  metadata pass did not run — contextual metadata is unaudited in this report")
    print(f"  fail counts: {summary['fail_counts']}")
    print(f"  saved {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study_dir", type=Path, help="directory containing claim_filtered.json")
    parser.add_argument("--limit", type=int, default=None, help="validate only the first N claims")
    parser.add_argument(
        "--pdf", type=Path, default=None, help="paper PDF (default: located by directory name)"
    )
    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="skip the open-book metadata pass; run the closed-book checks alone",
    )
    args = parser.parse_args()
    asyncio.run(main(args.study_dir, args.limit, args.pdf, not args.no_metadata))
