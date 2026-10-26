#!/usr/bin/env python3
"""Write the full OBI assay branch, raw stanza fields unchanged, to `obi_assay_terms_full.json`.

    obi.obo  5218  --[ assay branch ]-->  1794

This is stage 0 of `scripts/prune_obi_domain.py` and nothing more: every `is_a` descendant of
`OBI:0000070 assay` (root excluded), in `obi.obo` order, with **no** compositional or domain
prune and **no** reshaping. Each entry is the term's `[Term]` stanza as a JSON object: one key
per OBO tag, the value copied verbatim from the line after `tag: `. `id`, `name` and `def` are
strings; `synonym` and `is_a` are lists (a list even when the stanza has one line, empty when
it has none), so `is_a` reads `"OBI:0001977 ! cytometry assay"` exactly as the file has it.
Any other tag an OBI release adds is carried the same way, as a list.

Whether a term has children is not stored; invert `is_a` over the list to get it. Obsolete
terms carry no `is_a` and so never enter the branch.

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
from prune_obi_domain import ASSAY_ROOT, OBO_PATH, subtree  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "data" / "OBI" / "obi_assay_terms_full.json"

SCALAR_TAGS = ("id", "name", "def")
LIST_TAGS = ("synonym", "is_a")


def read_stanzas(obo_path: Path) -> list[dict]:
    """Every [Term] stanza in file order, tags verbatim: scalars as strings, the rest as lists."""
    stanzas: list[dict] = []
    for block in obo_path.read_text(encoding="utf-8").split("\n[")[1:]:
        if not block.startswith("Term]"):
            continue
        term: dict = {}
        for line in block.split("\n")[1:]:
            if ": " not in line:
                continue
            tag, value = line.split(": ", 1)
            if tag in SCALAR_TAGS:
                term[tag] = value
            else:
                term.setdefault(tag, []).append(value)
        for tag in LIST_TAGS:
            term.setdefault(tag, [])
        if term.get("id"):
            stanzas.append(term)
    return stanzas


def build_terms(obo_path: Path = OBO_PATH) -> list[dict]:
    """The assay branch of `obo_path`, raw stanzas, in file order."""
    stanzas = read_stanzas(obo_path)
    children: dict[str, list[str]] = defaultdict(list)
    for term in stanzas:
        for parent in term["is_a"]:
            children[parent.split("!")[0].strip()].append(term["id"])
    branch = subtree(ASSAY_ROOT, children) - {ASSAY_ROOT}
    return [t for t in stanzas if t["id"] in branch]


def summary(terms: list[dict]) -> str:
    parents = {p.split("!")[0].strip() for t in terms for p in t["is_a"]}
    with_children = sum(t["id"] in parents for t in terms)
    multi = sum(len(t["is_a"]) > 1 for t in terms)
    return (f"{len(terms)} assay terms: {len(terms) - with_children} leaves, {with_children} with "
            f"children, {multi} with more than one parent")


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
