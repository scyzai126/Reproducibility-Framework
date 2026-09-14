#!/usr/bin/env python3
"""Derive the live OBI assay vocabulary from the full assay branch.

Builds `obi_generic_index.json` from `obi_assay_terms_full.json` in two stages:

    1794  --[ measuring/detecting compositional filter ]-->  1248  --[ tier A-I subtrees ]-->  700

**Stage 1** drops the IEDB-style compositional labels (*"… assay measuring epitope specific X
production by Y cells"*). It reuses `_is_generic_assay_label` from the mapper so the rule has one
definition, and the mapper re-applies it at load time for callers pointing `--terms` at the
unfiltered list.

**Stage 2** drops whole domains that never appear in an immunology or biomedical paper — hospital
analyzer panels, insecticide resistance, electrophysiology, crystallography. Both stages exist for
the same reason: these terms are semantic near-neighbours of the ones we want, and there is no
score threshold in the mapper to stop a decoy that wins the top-10 from reaching the LLM. Stage 2
is expressed as `is_a` subtree roots rather than label keywords, so it survives an OBI release
bump.

Removed terms are **not** persisted. The root list below plus `data/OBI/README.md` record what
goes and why; `--show-dropped` reprints the terms themselves on demand. Because the whole index is
derived from `obi_assay_terms_full.json` + `obi.obo`, it is reproducible and verified as such by
`apps/api/tests/test_assay_obi_mapper.py::test_index_is_reproducible_from_the_full_source`.

Idempotent — rebuilding from source always lands on the same 700 terms in the same order.

    ./.venv/bin/python scripts/prune_obi_domain.py [--dry-run] [--show-dropped]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OBI_DIR = REPO_ROOT / "data" / "OBI"
OBO_PATH = OBI_DIR / "obi.obo"
SOURCE_PATH = OBI_DIR / "obi_assay_terms_full.json"
INDEX_PATH = OBI_DIR / "obi_generic_index.json"

sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
from app.agent.assay_obi_mapper import _is_generic_assay_label  # noqa: E402

# Out-of-scope subtree roots. Every term at or under one of these leaves the vocabulary.
OUT_OF_SCOPE_ROOTS = {
    "OBI:0002695",  # B — insecticide resistance assay (entomology)
    "OBI:0002441",  # C — physical examination of an organism (clinical exam, not an assay)
    "OBI:0002176",  # D — electrophysiology assay (neuro/cardiac)
    "OBI:0000870",  # E — single-nucleotide-resolution nucleic acid structure mapping
    "OBI:0002036",  # E — array based nucleic acid structure mapping
    "OBI:0002162",  # E — footprinting assay
    "OBI:0002438",  # E — nuclear ligation assay
    "OBI:0600045",  # F — 3D structure determination (crystallography/cryo-EM)
    "OBI:0002732",  # G — blood meal assay (vector biology)
    "OBI:0003290",  # G — mosquito membrane feeding assay
    "OBI:0003816",  # H — distance measurement assay
    "OBI:0003817",  # H — length measurement assay
    "OBI:0003825",  # H — acidity quality assay
    "OBI:0003826",  # H — specific gravity assay
    "OBI:0003827",  # H — speed measurement assay
    "OBI:0003828",  # H — velocity measurement assay
    "OBI:0003804",  # H — color detection assay
    "OBI:0003805",  # H — opacity determination assay
    "OBI:0002140",  # H — temperature measurement assay
    "OBI:0002141",  # H — volume measurement assay
    "OBI:0000944",  # I — handedness assay
    "OBI:0003725",  # I — survey administration assay
    "OBI:0003734",  # I — clinical history collection assay
    "OBI:0000117",  # I — Bernoulli trial
}

# Tier A. The OBI:21xxxxx band is a separate clinical-chemistry namespace, and it mixes two kinds
# of term: plain analyte readouts a paper does cite ("C-reactive protein assay", "lymphocyte count
# assay") and hospital analyzer/panel constructs it never does ("GEM4000 ANLCOOX arterial blood
# glucose assay"). Only the latter go, so the band is filtered by label and never dropped
# wholesale — OBI:2100402 "pooled clone sequencing assay" lives in it and is a real assay.
CLINICAL_BAND_PREFIX = "OBI:21"
CLINICAL_PANEL_QUALIFIERS = re.compile(
    r"\b(?:venous blood|arterial blood|capillary blood|whole blood|GEM|POC|CBC|SPEP|panel"
    r"|profile|inpatient|neonatal|ANLCOOX|premier|automated|manual differential|corrected"
    r"|total|tube \d|24 hour|random electrolytes|electrolytes|creatinine clearance"
    r"|bodily fluid|count bodily)\b",
    re.IGNORECASE,
)

# Terms held back from the prune because their family would otherwise have nothing left to fall
# back on. Subtracted from the whole dropped set, so it rescues from any tier.
KEEP_WHITELIST = {
    # Immunoglobulin quantitation — the one part of the OBI:21xxxxx band with no plain sibling;
    # there is no bare "IgG assay" term. The specimen qualifier is incidental here. Without these,
    # "Anti-Diphtheria IgG" loses OBI:2100177, the only committed mapping this prune would change.
    "OBI:2100177",  # quantitative venous blood IgG assay
    "OBI:2100178",  # quantitative venous blood IgM assay
    "OBI:2100179",  # quantitative venous blood IgA assay
    "OBI:2100234",  # total venous blood IgE assay
    # Tier F takes all four X-ray crystallography terms, leaving the index with nothing
    # crystallography-shaped at all — surfaced by comparing against ImmPort's assay vocabulary,
    # which lists "X-Ray Crystallography". Cryo-EM and NMR keep parents outside tier F; this
    # family does not, so pin the generic term.
    "OBI:0000912",  # X-ray crystallography 3D molecular structure determination assay
}


def parse_obo(path: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Return ({id: name}, {parent_id: [child_id, ...]}) for every [Term] stanza."""
    names: dict[str, str] = {}
    children: dict[str, list[str]] = defaultdict(list)
    for stanza in path.read_text(encoding="utf-8").split("\n[")[1:]:
        if not stanza.startswith("Term]"):
            continue
        term_id = name = None
        parents = []
        for line in stanza.split("\n"):
            if line.startswith("id: "):
                term_id = line[4:].strip()
            elif line.startswith("name: "):
                name = line[6:].strip()
            elif line.startswith("is_a: "):
                parents.append(line[6:].split("!")[0].strip())
        if not term_id:
            continue
        names[term_id] = name or ""
        for parent in parents:
            children[parent].append(term_id)
    return names, children


def subtree(root: str, children: dict[str, list[str]]) -> set[str]:
    """Every id at or below `root`, following is_a edges downward."""
    seen: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(children.get(node, ()))
    return seen


def out_of_scope_ids(terms: list[dict], children: dict[str, list[str]]) -> set[str]:
    """The ids to remove from `terms`, by subtree membership plus the tier-A label rule."""
    dropped: set[str] = set()
    for root in OUT_OF_SCOPE_ROOTS:
        dropped |= subtree(root, children)
    for term in terms:
        if term["id"].startswith(CLINICAL_BAND_PREFIX) and CLINICAL_PANEL_QUALIFIERS.search(
            term["label"]
        ):
            dropped.add(term["id"])
    present = {t["id"] for t in terms}
    return (dropped & present) - KEEP_WHITELIST


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="report the counts without writing any file"
    )
    parser.add_argument(
        "--show-dropped",
        action="store_true",
        help="print the removed terms; they are not written to a file",
    )
    args = parser.parse_args()

    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))

    # Stage 1 — compositional labels
    generic = [t for t in source if _is_generic_assay_label(t["label"])]

    # Stage 2 — out-of-scope domains
    _, children = parse_obo(OBO_PATH)
    dropped_ids = out_of_scope_ids(generic, children)

    # Entries are copied through untouched and in their source order: _build_lookup indexes
    # synonyms with setdefault, so index order decides synonym-collision ties.
    kept = [t for t in generic if t["id"] not in dropped_ids]
    removed = [t for t in generic if t["id"] in dropped_ids]

    if args.show_dropped:
        for term in removed:
            print(f"  {term['id']}  {term['label']}")

    print(
        f"{len(source)} in source"
        f" → {len(generic)} after compositional filter (-{len(source) - len(generic)})"
        f" → {len(kept)} after domain prune (-{len(removed)})"
    )
    if args.dry_run:
        print("--dry-run: nothing written")
        return

    INDEX_PATH.write_text(
        json.dumps(kept, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {INDEX_PATH.relative_to(REPO_ROOT)} ({len(kept)} terms)")


if __name__ == "__main__":
    main()
