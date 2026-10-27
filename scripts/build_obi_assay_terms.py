#!/usr/bin/env python3
"""Write the full OBI assay branch, in the index's format, to `obi_assay_full_index.json`.

    obi.obo  5218  --[ assay branch ]-->  1794

This is stage 0 of `scripts/prune_obi_domain.py` and nothing more: every `is_a` descendant of
`OBI:0000070 assay` (root excluded), in `obi.obo` order, with **no** compositional or domain
prune. It exists so an experiment can run the mapper over the unpruned vocabulary.

The entries have exactly the fields of `obi_assay_pruned_index.json`, built by the same two helpers
(`assay_branch` and `annotate`), so either file can be handed to `run_obi_map.py --terms`:

    id, label, synonyms, is_a, definition, n_descendants

`is_a` is the parent ids from the full ontology in OBO order (the root `assay` appears as a
parent, never as an entry); `n_descendants` counts distinct `is_a` descendants in the full
ontology, self excluded, so 0 means leaf. Obsolete terms carry no `is_a` and never enter the
branch.

Run under the repo-root `.venv` (the prune module imports the mapper, which needs numpy):

    ./.venv/bin/python scripts/build_obi_assay_terms.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from prune_obi_domain import OBO_PATH, annotate, assay_branch, parse_obo  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "data" / "OBI" / "obi_assay_full_index.json"


def build_terms(obo_path: Path = OBO_PATH) -> list[dict]:
    """The assay branch of `obo_path`, annotated like the index, in file order."""
    _, children, definitions = parse_obo(obo_path)
    return annotate(assay_branch(obo_path), definitions, children)


def summary(terms: list[dict]) -> str:
    leaves = sum(t["n_descendants"] == 0 for t in terms)
    multi = sum(len(t["is_a"]) > 1 for t in terms)
    return (f"{len(terms)} assay terms: {leaves} leaves, {len(terms) - leaves} with descendants, "
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
