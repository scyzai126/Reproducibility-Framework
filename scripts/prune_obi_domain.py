#!/usr/bin/env python3
"""Derive the live OBI assay vocabulary from the full assay branch.

Builds `obi_assay_noncompositional_index.json` from `obi.obo` -- **the live vocabulary since
2026-11-10**, 1249 terms: compositional labels gone, every domain still in. Stage 2 then runs on
top of it and writes `obi_assay_pruned_index.json` (701), the vocabulary that served until that
date; it is gitignored now and kept for the vocabulary A/B and as the record of which OBI domains
act as retrieval decoys.

    5218  --[ assay branch ]-->  1794  --[ measuring/detecting compositional filter ]-->  1249  LIVE
          --[ tier A-I subtrees ]-->  701  retired

Why the live list is stage 1: the domain prune was measured out together with TOP_K 20 -> 30. The
two interact with opposite signs -- widening K costs 2 exact on the 701 and gains 2 on the 1249 --
and at K=30 the 1249 wins by 3, outside the noise band. Separately, over 892 corpus papers stage 2
was doing real damage: it cut four conformation-capture terms out from under Hi-C, leaving only
the 5C ones, so two papers reporting promoter capture Hi-C mapped to 5C-seq. Evidence:
`experiment/obi_topk_1249/FINDINGS.md`.

**Stage 0** keeps the `is_a` descendants of `OBI:0000070 assay`, each with its `is_a` parent ids.
Each kept term then gets its `definition` and `n_descendants` from `obi.obo` (see `annotate`).

**Stage 1** drops the IEDB-style compositional labels (*"… assay measuring epitope specific X
production by Y cells"*). It reuses `_is_generic_assay_term` from the mapper so the rule has one
definition, and the mapper re-applies it at load time for callers pointing `--terms` at the
unfiltered list. The mapper's `_COMPOSITIONAL_KEEP` pins the few compositional terms whose family
has no generic term left (today only OBI:1110179, the MHC tetramer/multimer assay).

**Stage 2** drops whole domains that never appear in an immunology or biomedical paper — hospital
analyzer panels, insecticide resistance, electrophysiology, crystallography. Both stages exist for
the same reason: these terms are semantic near-neighbours of the ones we want, and there is no
score threshold in the mapper to stop a decoy that wins the top-10 from reaching the LLM. Stage 2
is expressed as `is_a` subtree roots rather than label keywords, so it survives an OBI release
bump.

Removed terms are **not** persisted. The root list below plus `data/OBI/README.md` record what
goes and why; `--show-dropped` reprints the terms themselves on demand. Because the whole index is
derived from `obi.obo` and the roots below, it is reproducible and verified as such by
`apps/api/tests/test_assay_obi_mapper.py::test_index_is_reproducible_from_the_full_source`.

Idempotent — rebuilding from source always lands on the same 1249 (and 701) terms in the same order.

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
INDEX_PATH = OBI_DIR / "obi_assay_pruned_index.json"
NONCOMPOSITIONAL_PATH = OBI_DIR / "obi_assay_noncompositional_index.json"  # stage 1 only

sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
from app.agent.assay_obi_mapper import _is_generic_assay_term  # noqa: E402

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


# `def: "text" [xrefs]` / `synonym: "text" EXACT []` — the text may carry escaped quotes.
_OBO_QUOTED_RE = re.compile(r'^(def|synonym): "((?:[^"\\]|\\.)*)"')

#: OBI's `assay` class. Its is_a descendants are the assay branch every stage starts from.
ASSAY_ROOT = "OBI:0000070"


def read_terms(path: Path) -> list[dict]:
    """Every [Term] stanza in file order, as {id, name, synonyms, definition, parents}."""
    terms: list[dict] = []
    for stanza in path.read_text(encoding="utf-8").split("\n[")[1:]:
        if not stanza.startswith("Term]"):
            continue
        term = {"id": None, "name": "", "synonyms": [], "definition": "", "parents": []}
        for line in stanza.split("\n"):
            if line.startswith("id: "):
                term["id"] = line[4:].strip()
            elif line.startswith("name: "):
                term["name"] = line[6:].strip()
            elif line.startswith("is_a: "):
                term["parents"].append(line[6:].split("!")[0].strip())
            elif match := _OBO_QUOTED_RE.match(line):
                text = re.sub(r"\\(.)", r"\1", match.group(2))
                if match.group(1) == "def":
                    term["definition"] = text
                else:
                    term["synonyms"].append(text)
        if term["id"]:
            terms.append(term)
    return terms


def parse_obo(
    path: Path,
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, str]]:
    """Return ({id: name}, {parent_id: [child_id, ...]}, {id: definition}) for every [Term]."""
    names: dict[str, str] = {}
    children: dict[str, list[str]] = defaultdict(list)
    definitions: dict[str, str] = {}
    for term in read_terms(path):
        names[term["id"]] = term["name"]
        if term["definition"]:
            definitions[term["id"]] = term["definition"]
        for parent in term["parents"]:
            children[parent].append(term["id"])
    return names, children, definitions


def assay_branch(path: Path) -> list[dict]:
    """The full assay vocabulary: every descendant of `assay` (root excluded), in file order.

    Each entry is {id, label, synonyms, is_a}. This is the 1794-term list every prune starts
    from, and the vocabulary scripts/compare_assay_benchmark.py resolves curator keys against.

    `is_a` is the stanza's parent ids, in OBO order, from the **full** ontology: a parent may be
    `assay` itself or a term a later prune removes, so an edge in the index need not have both
    ends in it. It is kept so an index entry says where it hangs without a reader re-parsing
    `obi.obo`; the mapper's `_index_children` still derives the in-index edges from the OBO.
    """
    terms = read_terms(path)
    children: dict[str, list[str]] = defaultdict(list)
    for term in terms:
        for parent in term["parents"]:
            children[parent].append(term["id"])
    branch = subtree(ASSAY_ROOT, children) - {ASSAY_ROOT}
    return [
        {"id": t["id"], "label": t["name"], "synonyms": t["synonyms"], "is_a": t["parents"]}
        for t in terms
        if t["id"] in branch
    ]


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


def annotate(
    terms: list[dict], definitions: dict[str, str], children: dict[str, list[str]]
) -> list[dict]:
    """Add `definition` and `n_descendants` to each term, both read from obi.obo.

    `n_descendants` counts distinct `is_a` descendants in the full ontology (self excluded), not
    within the pruned index — the compositional children it counts are gone from the index, so a
    family term like ELISPOT can be broad in OBI and a leaf here. A term with no `def:` gets "".
    """
    return [
        {
            **term,
            "definition": definitions.get(term["id"], ""),
            "n_descendants": len(subtree(term["id"], children)) - 1,
        }
        for term in terms
    ]


def build_index(obo_path: Path = OBO_PATH) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Run every stage from obi.obo. Returns (assay branch, generic, kept, removed).

    `generic` and `kept` are annotated alike, so an entry reads the same in
    `obi_assay_noncompositional_index.json` and `obi_assay_pruned_index.json` (and in the full list
    scripts/build_obi_assay_terms.py writes with the same helpers).
    """
    source = assay_branch(obo_path)
    _, children, definitions = parse_obo(obo_path)

    # Stage 1 — compositional labels
    generic = annotate(
        [t for t in source if _is_generic_assay_term(t["id"], t["label"])], definitions, children
    )

    # Stage 2 — out-of-scope domains
    dropped_ids = out_of_scope_ids(generic, children)

    # Entries keep their fields and obi.obo order: _build_lookup indexes synonyms with
    # setdefault, so index order decides synonym-collision ties.
    kept = [t for t in generic if t["id"] not in dropped_ids]
    removed = [t for t in generic if t["id"] in dropped_ids]
    return source, generic, kept, removed


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

    source, generic, kept, removed = build_index()

    if args.show_dropped:
        for term in removed:
            print(f"  {term['id']}  {term['label']}")

    print(
        f"{len(source)} in assay branch"
        f" → {len(generic)} after compositional filter (-{len(source) - len(generic)})"
        f" → {len(kept)} after domain prune (-{len(removed)})"
    )
    if args.dry_run:
        print("--dry-run: nothing written")
        return

    for path, terms in ((NONCOMPOSITIONAL_PATH, generic), (INDEX_PATH, kept)):
        path.write_text(json.dumps(terms, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)} ({len(terms)} terms)")


if __name__ == "__main__":
    main()
