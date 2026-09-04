"""Extract a paper's assay registry with one LLM call.

The programmatic form of the extract-assay-methods skill: same rules
(apps/api/app/prompts/extract_assays.txt), run as a single call over the sentence-numbered
paper instead of read interactively.

Writes data/claims/assay_registries/<pmid>_<SDY>/assays.json -- the canonical location the
rest of the chain reads. Re-running overwrites it in place.

The paper text is the same parse the verifier reads (parse_jats_xml + number_sentences), so
the `[S<n>]` ids the extraction cites mean the same sentences downstream. Any other source of
text would make them uncheckable.

Cost is one call. Follow it with the free quote check, which is how you find out whether the
model copied its evidence quotes or reconstructed them:

    python scripts/run_assay_verify.py <registry_dir> --check-quotes

Usage:
    python scripts/run_assay_extract.py <paper.xml> <registry_dir> [--dry-run]

Example:
    python scripts/run_assay_extract.py data/JAT_XML/SDY1119_26682988.xml \\
        data/claims/assay_registries/26682988_SDY1119
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(_REPO_ROOT / ".claude" / "skills" / "extract-assay-methods" / "scripts"))

from app.agent.assay_extractor import AssayExtractionError, contract_warnings, extract_assays
from app.agent.claim_parser import _get_client
from run_assay_verify import paper_text


async def main(xml_path: Path, out_dir: Path, dry_run: bool) -> None:
    if not xml_path.exists():
        print(f"No such paper: {xml_path}")
        sys.exit(1)

    title, source_text = paper_text(xml_path)
    out_path = out_dir / "assays.json"

    print(f"{xml_path.name}: {len(source_text):,} chars, title {title!r}")
    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"  {out_path} exists with {len(existing)} entr(ies) -- it will be overwritten")
    if dry_run:
        print("--dry-run: nothing called.")
        return

    print("Extracting (1 call)...")
    try:
        registry = await extract_assays(source_text, title, _get_client())
    except AssayExtractionError as exc:
        print(f"Extraction failed: {exc}")
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    print(f"\n{len(registry)} assay(s):")
    for key, entry in registry.items():
        ids = ",".join(entry["evidence"]["sentence_ids"]) or "-"
        print(f"  {entry['source']:8s} {key}  [{ids}]  platform={entry['platform']!r}")

    for warning in contract_warnings(registry):
        print(f"  WARNING  {warning}")

    print(f"\n  saved {out_path}")
    print(f"\nNext, free: python scripts/run_assay_verify.py {out_dir} --check-quotes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml_path", type=Path, help="paper JATS XML")
    parser.add_argument("out_dir", type=Path, help="registry directory to write assays.json into")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be sent; makes no API call")
    args = parser.parse_args()
    asyncio.run(main(args.xml_path, args.out_dir, args.dry_run))
