"""Independently verify an already-extracted assay registry against its paper.

Reads <registry_dir>/assays.json and writes <registry_dir>/assays_verification.json. The
registry itself is never touched -- this pass reports verdicts, it does not repair anything.

Each assay gets one call carrying the whole sentence-numbered paper. The whole paper, rather
than the Methods section alone, because the verifier's own assay-identity rule requires it:
an assay "mentioned only in the Introduction" or "cited from another study" cannot be
recognised as such by a reader who was only shown Methods.

The paper's XML is located by convention from the registry directory name -- note the two
conventions run in opposite orders, `<pmid>_<SDY>` for the registry and `<SDY>_<pmid>` for
the XML. Pass --xml to override.

--check-quotes runs only the deterministic evidence-quote check and makes no API call at
all, which is the free way to survey a registry before paying to verify it.

Use --limit to smoke-test on a couple of assays before paying for a whole paper.

Usage:
    python scripts/run_assay_verify.py <registry_dir> [--xml PATH] [--limit N] [--check-quotes]

Example:
    python scripts/run_assay_verify.py data/claims/assay_registries/36988326_SDY2618 --limit 2
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.assay_verifier import (
    build_report,
    check_quote_verbatim,
    check_source_section,
    verify_registry,
)
from app.agent.claim_parser import _get_client
from app.agent.jats_parser import (
    article_title as _article_title,
    number_sentences,
    parse_jats_xml,
    sentence_sections,
)

_XML_ROOT = _REPO_ROOT / "data" / "JAT_XML"


def locate_xml(registry_dir: Path) -> Path | None:
    """Find the paper XML for a registry directory by naming convention.

    `assay_registries/23878721_SDY1276` -> `data/JAT_XML/SDY1276_23878721.xml`. The halves
    are swapped rather than matched in order, because the two directory schemes were named
    independently and disagree.
    """
    stem = registry_dir.resolve().name
    candidates = [stem]
    if "_" in stem:
        left, _, right = stem.partition("_")
        candidates.append(f"{right}_{left}")
    for candidate in candidates:
        path = _XML_ROOT / f"{candidate}.xml"
        if path.exists():
            return path
    return None


def article_title(xml_path: Path) -> str:
    """The paper's title, falling back to the filename stem. Parsing lives in jats_parser."""
    return _article_title(xml_path.read_bytes()) or xml_path.stem


def paper_text(xml_path: Path) -> tuple[str, str]:
    """Parse the paper to sentence-numbered text, returning (title, text).

    This is the same parse the extraction read from -- parse_jats_xml plus the skill's
    number_sentences -- so a cited `[S<n>]` id means the same sentence on both sides. Any
    other source of text would make the ids uncheckable.
    """
    parsed = parse_jats_xml(xml_path.read_text(encoding="utf-8"))
    if not parsed or not parsed.strip():
        raise SystemExit(f"{xml_path} yielded no text; verify against the PDF is not supported")

    return article_title(xml_path), number_sentences(parsed)


def report_quotes(assays: dict, source_text: str) -> None:
    """Print the deterministic checks for every entry. No API call.

    Two of them: the quote is copied from the sentences it cites, and `source` agrees with the
    section those sentences sit in. The second is what makes the extraction's Methods/Results
    classification auditable rather than self-asserted.
    """
    sections = sentence_sections(source_text)
    missing = mismatched = 0
    for key, entry in assays.items():
        check = check_quote_verbatim(entry, source_text)
        flag = {"found": "ok     ", "missing": "MISSING", "no_quote": "no quote"}[check["status"]]
        if check["status"] != "found":
            missing += 1
        print(f"  {flag}  {key}: {check['detail']}")

        src = check_source_section(entry, sections)
        if src["status"] == "mismatch":
            mismatched += 1
            print(f"  SOURCE?  {key}: {src['detail']}")

    print(f"\n{len(assays) - missing}/{len(assays)} quotes verified verbatim")
    if mismatched:
        print(f"{mismatched}/{len(assays)} entries claim a section their evidence does not support")


async def main(registry_dir: Path, limit: int | None, xml_path: Path | None, quotes_only: bool) -> None:
    registry_path = registry_dir / "assays.json"
    if not registry_path.exists():
        print(f"No assays.json in {registry_dir}")
        sys.exit(1)

    assays = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(assays, dict) or not assays:
        print(f"{registry_path} holds no assay entries")
        sys.exit(1)

    if xml_path is None:
        xml_path = locate_xml(registry_dir)
    if xml_path is None or not xml_path.exists():
        print(
            f"No paper XML found for {registry_dir.name}"
            + (f" at {xml_path}" if xml_path is not None else f" under {_XML_ROOT}")
            + ".\nPass --xml PATH. Verification needs the same parse the extraction read from."
        )
        sys.exit(1)

    title, source_text = paper_text(xml_path)

    if quotes_only:
        print(f"{len(assays)} assay(s) in {registry_path.name}, checked against {xml_path.name}:")
        report_quotes(assays, source_text)
        return

    keys = list(assays)[:limit] if limit is not None else list(assays)
    scope = f"the first {len(keys)}" if limit is not None else "all"
    print(
        f"{len(assays)} assay(s) in {registry_path.name}; verifying {scope} against "
        f"{xml_path.name} ({len(source_text):,} chars) — costs {len(keys)} call(s)."
    )

    results = await verify_registry(assays, source_text, title, _get_client(), limit=limit)
    report = build_report(results)

    out_path = registry_dir / "assays_verification.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = report["summary"]
    print(
        f"\n{summary['accept']}/{summary['total']} accepted, "
        f"{summary['review']} to review, {summary['reject']} rejected, "
        f"{summary['errors']} errors"
    )
    if summary["quotes_missing"]:
        print(f"  {summary['quotes_missing']} evidence quote(s) do not appear in the paper")
    if summary["field_issues"]:
        print(f"  field issues: {json.dumps(summary['field_issues'])}")
    print(f"  saved {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry_dir", type=Path, help="directory containing assays.json")
    parser.add_argument("--limit", type=int, default=None, help="verify only the first N assays")
    parser.add_argument(
        "--xml", type=Path, default=None, help="paper JATS XML (default: located by directory name)"
    )
    parser.add_argument(
        "--check-quotes",
        action="store_true",
        help="run only the deterministic evidence-quote check; makes no API call",
    )
    args = parser.parse_args()
    asyncio.run(main(args.registry_dir, args.limit, args.xml, args.check_quotes))
