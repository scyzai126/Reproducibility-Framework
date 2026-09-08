"""Answer "what assays did this paper use?" in one command: extract, verify, correct, promote.

The three rounds the separate scripts run one at a time, chained:

  1. prompts/extract_assays.txt      builds the registry              1 call
  2. prompts/verify_assays.txt       judges every entry               1 call per assay
  3. prompts/correct_assay_field.txt repairs what round 2 refused     1 call per flagged FIELD

Chaining is the whole point: an unverified registry cannot be told apart from a verified one by
reading it, because a `platform` inferred from what a technique usually runs on looks exactly
like one copied out of Methods.

Round 3 promotes, so `assays.json` ends up holding the corrected registry with the extracted
one kept beside it as `assays_precorrection.json`. The run then projects that onto
`assays_benchmark.json` -- name, aliases, source, evidence -- **which is the file to read**. All
seven fields stay in `assays.json` because every pass in the chain works from them.

The chain itself is app.agent.assay_service.assay_report, which is also what POST /agent/assays
runs. This script is the CLI in front of it, so a registry built here and one built through the
endpoint are the same files, and run_assay_verify.py / run_assay_correct.py still read them.

**Nothing is reused between runs.** Every invocation pays for all three rounds, so re-running
a finished paper costs what the first run cost. Reuse was removed because it could not be kept
for round 1 alone -- a fresh registry invalidates the stored verdicts, which invalidates the
corrections derived from them -- and because an edit to extract_assays.txt had no effect on a
paper that had already been run.

**--dry-run makes no API call** and reports the projected bill. Run it first: a 10-assay paper
is upwards of 20 calls. Round 1 is one call; round 2 is exact once a registry exists on disk
to count entries in, and round 3 once a verification does.

Usage:
    python3 scripts/run_assay_pipeline.py <registry_dir> [--dry-run]
    python3 scripts/run_assay_pipeline.py --pmid 34252919 --sdy SDY2189 [--dry-run]

Example:
    python3 scripts/run_assay_pipeline.py data/claims/assay_registries/34252919_SDY2189 --dry-run
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.assay_extractor import contract_warnings
from app.agent.assay_service import (
    PaperNotFoundError,
    assay_report,
    corrections_available,
    locate_paper_xml,
    paper_source_text,
    registry_dir,
)
from app.agent.claim_parser import _get_client


def split_registry_dir(path: Path) -> tuple[str, str]:
    """`assay_registries/34252919_SDY2189` -> ("34252919", "SDY2189").

    The registry scheme is `<pmid>_<SDY>` while the XML scheme is `<SDY>_<pmid>`; the halves
    are identified by which one starts with "SDY" rather than by position, so a directory
    named the other way round still resolves instead of silently producing a paper we cannot
    find.
    """
    stem = path.resolve().name
    left, _, right = stem.partition("_")
    if not right:
        raise SystemExit(
            f"{stem!r} is not a <pmid>_<SDY> registry directory; pass --pmid/--sdy instead"
        )
    if left.upper().startswith("SDY"):
        return right, left
    return left, right


def _print_fields(assays: dict) -> None:
    """The three fields the registry is asked to carry, per entry.

    Name, evidence source, aliases. Printed rather than summarised because "10 entries" tells
    you nothing about whether any of them can be traced back to a sentence.
    """
    print("\nname / source / aliases:")
    for key, entry in assays.items():
        evidence = entry.get("evidence") or {}
        ids = evidence.get("sentence_ids") or []
        where = entry.get("source") or "?"
        cite = f"{where} {evidence.get('section') or '?'} [{', '.join(ids) or 'no ids'}]"
        aliases = entry.get("aliases")
        shown = ", ".join(aliases) if isinstance(aliases, list) and aliases else (
            "(none)" if isinstance(aliases, list) else f"NOT A LIST: {aliases!r}")
        print(f"  {key}\n      source: {cite}\n      aliases: {shown}")


def _dry_run(pmid: str, sdy: str) -> None:
    """What the chain would cost, without calling anything.

    Every round runs, so the only question is how many calls each will make. A stored registry
    and verification are read for their *shape* -- how many assays, how many flagged fields --
    which makes the estimate exact even though neither will be reused. Where they are absent
    the round can only be bounded, and is reported that way rather than guessed at.
    """
    xml_path = locate_paper_xml(pmid, sdy)
    if xml_path is None:
        raise SystemExit(f"No JATS XML for pubmed_id={pmid!r} study_accession={sdy!r}")

    out_dir = registry_dir(pmid, sdy)
    title, source_text = paper_source_text(xml_path)
    print(f"{xml_path.name}: {len(source_text):,} chars, title {title!r}")
    print(f"registry: {out_dir}")

    registry_path = out_dir / "assays.json"
    verification_path = out_dir / "assays_verification.json"

    assays = (json.loads(registry_path.read_text(encoding="utf-8"))
              if registry_path.exists() else None)
    verification = (json.loads(verification_path.read_text(encoding="utf-8"))
                    if verification_path.exists() else None)

    print("  round 1 extract: will run                            1 call")

    if assays is not None:
        print(f"  round 2 verify:  will run                            ~{len(assays)} calls"
              "   (the last run found that many)")
    else:
        print("  round 2 verify:  will run, 1 call per assay found    ? calls")

    if verification is not None:
        pending = corrections_available(assays or {}, verification)
        print(f"  round 3 correct: will run                            ~{pending['calls']} calls"
              f"   ({pending['rejected']} assay(s) set aside last run)")
    else:
        print("  round 3 correct: will run, 1 call per flagged field  ? calls")

    if assays is not None:
        print("\n  ~ because rounds 2 and 3 are sized from the previous run's output, which "
              "this run\n    re-extracts rather than reuses. The shape rarely moves; it is not "
              "guaranteed.")
    print("\n--dry-run: nothing called.")


async def main(pmid: str, sdy: str) -> None:
    try:
        result = await assay_report(pmid, sdy, _get_client(), verify=True, correct=True)
    except PaperNotFoundError as exc:
        raise SystemExit(str(exc))

    print(f"{result['paper_source']}: {result['paper_title']!r}")
    for name in ("extract", "verify", "correct"):
        row = result["rounds"].get(name, {})
        extra = {k: v for k, v in row.items() if k not in ("source", "calls")}
        print(f"  {name:8} {row.get('source', '?'):10} {row.get('calls', 0)} call(s)"
              + (f"  {json.dumps(extra)}" if extra else ""))

    assays = result["assays"]
    check = result["quote_check"]
    print(f"\n{len(assays)} assay(s); {check['verified']}/{check['total']} quotes verbatim, "
          f"{check['source_aligned']}/{check['total']} source-aligned")

    # Both of these are the reasons not to trust an entry, so neither is summarised away.
    for warning in contract_warnings(assays):
        print(f"  WARNING  {warning}")
    for record in (result.get("verification") or {}).get("results", []):
        verdict = record.get("record_verdict")
        if verdict not in ("REVIEW", "REJECT"):
            continue
        print(f"  {verdict}  {record.get('assay_id')} "
              f"(identity {record.get('assay_identity_verdict')})")
        # The record itself carries no reason -- it is derived from the field verdicts, so the
        # unsupported fields are where the "why" actually lives.
        for field in record.get("field_verifications") or []:
            if field.get("verdict") not in (None, "SUPPORTED"):
                print(f"           {field.get('field_name')}: {field.get('verdict')}"
                      f" — {field.get('reason') or 'no reason given'}")
    for key, record in (result.get("dropped") or {}).items():
        print(f"  DROPPED  {key}: {record.get('reason') or 'rejected'}")

    _print_fields(assays)
    meta = result["meta"]
    print(f"\n{meta['llm_calls']} call(s) spent."
          f"\n  {meta['benchmark_path']}  <- the deliverable: name, aliases, source, evidence"
          f"\n  {meta['registry_path']}  full seven-field registry the pipeline works from")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry_dir", type=Path, nargs="?", default=None,
                        help="registry directory named <pmid>_<SDY>")
    parser.add_argument("--pmid", default="", help="PubMed id (instead of registry_dir)")
    parser.add_argument("--sdy", default="", help="study accession (instead of registry_dir)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the projected call count; makes no API call")
    args = parser.parse_args()

    if args.registry_dir is not None:
        pubmed_id, study = split_registry_dir(args.registry_dir)
    elif args.pmid.strip() or args.sdy.strip():
        pubmed_id, study = args.pmid.strip(), args.sdy.strip()
    else:
        parser.error("give a registry directory, or --pmid/--sdy")

    if args.dry_run:
        _dry_run(pubmed_id, study)
    else:
        asyncio.run(main(pubmed_id, study))
