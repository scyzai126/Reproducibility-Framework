#!/usr/bin/env python3
"""Write the full OBI assay branch, with its `is_a` edges, to `obi_assay_terms_full.json`.

    obi.obo  5218  --[ assay branch ]-->  1794

This is stage 0 of `scripts/prune_obi_domain.py` and nothing more: every `is_a` descendant of
`OBI:0000070 assay` (root excluded), in `obi.obo` order, with **no** compositional or domain
prune. It exists so an experiment can run the mapper over the unpruned vocabulary and tell a
leaf from a family term, which the pruned index cannot say (its `n_descendants` counts children
the prune removed).

Each entry carries the same core fields as `obi_generic_index.json` (`id`, `label`, `synonyms`,
`definition`, `n_descendants`), so either file can be handed to `run_obi_map.py --terms`, plus:

    is_a         every `is_a:` line of the stanza, in OBO order, as {id, label}; a parent outside
                 the branch is kept as written, and `assay` itself appears here but never as an entry
    children     direct `is_a` children in the full ontology, file order, as {id, label}
    n_children   len(children); 0 means leaf

`n_children` and `n_descendants` both count over the full `obi.obo`, the same definition
`prune_obi_domain.annotate` uses. Obsolete terms carry no `is_a` and so never enter the branch.

Run under the repo-root `.venv` (the prune module imports the mapper, which needs numpy):

    ./.venv/bin/python scripts/build_obi_assay_terms.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from prune_obi_domain import ASSAY_ROOT, OBO_PATH, read_terms, subtree  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "data" / "OBI" / "obi_assay_terms_full.json"


def build_terms(obo_path: Path = OBO_PATH) -> list[dict]:
    """The assay branch of `obo_path` with parents, children and counts, in file order."""
    terms = read_terms(obo_path)
    names = {t["id"]: t["name"] for t in terms}
    children: dict[str, list[str]] = defaultdict(list)
    for term in terms:
        for parent in term["parents"]:
            children[parent].append(term["id"])
    branch = subtree(ASSAY_ROOT, children) - {ASSAY_ROOT}

    def ref(term_id: str) -> dict:
        return {"id": term_id, "label": names.get(term_id, "")}

    out = []
    for term in terms:
        if term["id"] not in branch:
            continue
        kids = children.get(term["id"], [])
        out.append({
            "id": term["id"],
            "label": term["name"],
            "synonyms": term["synonyms"],
            "definition": term["definition"],
            "is_a": [ref(p) for p in term["parents"]],
            "children": [ref(c) for c in kids],
            "n_children": len(kids),
            "n_descendants": len(subtree(term["id"], children)) - 1,
        })
    return out


def summary(terms: list[dict]) -> str:
    leaves = sum(t["n_children"] == 0 for t in terms)
    multi = sum(len(t["is_a"]) > 1 for t in terms)
    return (f"{len(terms)} assay terms: {leaves} leaves, {len(terms) - leaves} with children, "
            f"{multi} with more than one parent")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--obo", type=Path, default=OBO_PATH)
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--dry-run", action="store_true", help="print the counts; write nothing")
    args = parser.parse_args()

    terms = build_terms(args.obo)
    print(summary(terms))
    if args.dry_run:
        print(f"dry run: would write {args.out}")
        return
    args.out.write_text(json.dumps(terms, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
