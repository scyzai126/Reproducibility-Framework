#!/usr/bin/env python3
"""Link a paper's claims to its verified assay registry. **Calls nothing.**

The join is app.agent.claim_assay_linker.link_claims; this is its CLI. Neither input file is
changed: the links go to their own file, which the grouping step reads.

Usage:
    python3 scripts/run_claim_assay_link.py <assay_dir> <claims.json> <out_dir> [--xml <paper.xml>]

Example:
    python3 scripts/run_claim_assay_link.py data/31paper_assays/19047440_SDY1289 \
        data/claims/new_26_studies/19047440_SDY1289_filtered/claims.json \
        data/claims/new_26_studies/19047440_SDY1289_filtered

Reads  : <assay_dir>/{assays.json,assays_OBI.json}, <claims.json>, the paper XML
         (--xml, else found under data/JAT_XML/ from <assay_dir>'s name; without one the
         generate_claim_doubtful check is skipped and an uncovered assay reads `unexplained`)
Writes : <out_dir>/claim_assay_links.json (a rerun overwrites it in place)
"""

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS.parent / "apps" / "api"))
sys.path.insert(0, str(_SCRIPTS))

from app.agent.claim_assay_linker import finding_sentences, link_claims, load_registry  # noqa: E402
from run_assay_verify import locate_xml, paper_text  # noqa: E402


def _report(links: dict) -> None:
    for cid in links["unlinked_claims"]:
        r = links["claims"][cid]
        print(f"  UNLINKED  {cid}: {r['assay_method_in_paper']!r} "
              f"(mentions: {', '.join(r['candidates']) or 'none'})")
    for name, r in links["assays"].items():
        if r["status"] == "generate_claim_mismatch":
            print(f"  MISMATCH  {name}: generate_claim false, but linked by {', '.join(r['claims'])}")
        elif r["status"] == "possible_wording_mismatch":
            print(f"  NO_CLAIM  {name}: possible wording mismatch with "
                  f"{', '.join(r['candidate_claims'])}")
        elif r["status"] == "generate_claim_doubtful":
            print(f"  NO_CLAIM  {name}: generate_claim doubtful -- no Results/caption sentence "
                  f"mentions it")
        elif r["status"] == "unexplained":
            where = (f"mentioned in {', '.join(r['finding_sentence_ids'])}"
                     if r.get("text_checked") else "paper text not checked")
            print(f"  NO_CLAIM  {name}: unexplained ({where})")

    s = links["summary"]
    print(f"\n{s['claims']} claims: {s['claim_links']}")
    print(f"{s['assays']} assays: {s['assay_status']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("assay_dir", type=Path)
    parser.add_argument("claims", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--xml", type=Path, help="paper XML (default: found by assay_dir name)")
    args = parser.parse_args()

    registry = load_registry(args.assay_dir)
    claims = json.loads(args.claims.read_text(encoding="utf-8"))

    xml_path = args.xml or locate_xml(args.assay_dir)
    finding_text = None
    if xml_path and xml_path.exists():
        finding_text = finding_sentences(paper_text(xml_path)[1])
    else:
        print(f"WARNING  no paper XML for {args.assay_dir.name}; "
              f"generate_claim_doubtful is not checked")

    links = link_claims(claims, registry, finding_text)
    _report(links)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / "claim_assay_links.json"
    out.write_text(json.dumps(links, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
