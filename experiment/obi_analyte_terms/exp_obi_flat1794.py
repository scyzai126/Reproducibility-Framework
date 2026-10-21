#!/usr/bin/env python3
"""Arm 1 of the analyte-level OBI term experiment: map a registry against the *unpruned* 1794-term
OBI assay branch with today's mapper, unchanged.

The live mapper searches 701 terms: the assay branch minus 545 compositional labels ("ELISPOT
assay measuring epitope specific IFN-gamma production by T cells") and 548 out-of-scope domain
terms (data/OBI/README.md). This arm puts all 1794 back and lets the picker choose among them,
to see whether the failure the prune was introduced for -- the family term buried under its
analyte-specific children -- still happens now that the picker sees definitions, neighbours and
the record's readouts.

Nothing in the production code or under data/ is touched. The mapper filters compositional terms
at load time whatever terms file it is given, and reads its vectors from a module constant, so
this script patches both *in-process* (the way the test suite does) for the duration of a run and
restores them after. Every output lands under experiment/obi_analyte_terms/.

    build-index                  data/OBI/obi_assay_full_index.json  (1794 rows, free)
    build-embeddings [--dry-run] data/OBI/obi_assay_full_embeddings.json (one embedding call per
                                 row not already in the live file: ~1093 rows, well under a cent)
    map <registry_dir> [--dry-run]
                                 results/flat1794/<registry_name>/{assays_OBI.json, raw.json}
                                 2-3 calls per entry the 1794 vocabulary does not match verbatim
                                 on a childless term; --dry-run prints the count and calls nothing

Usage, from the repo root:
    ./.venv/bin/python experiment/obi_analyte_terms/exp_obi_flat1794.py build-index
    ./.venv/bin/python experiment/obi_analyte_terms/exp_obi_flat1794.py build-embeddings --dry-run
    ./.venv/bin/python experiment/obi_analyte_terms/exp_obi_flat1794.py map data/31paper_assays/stability/34252919_SDY2189 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

#: Both live in data/OBI beside the pruned (701) files, not under experiment/: that folder is the
#: one place OBI vocabularies live, and these two are the same shape as the pruned pair.
OBI_DIR = REPO_ROOT / "data" / "OBI"
INDEX_PATH = OBI_DIR / "obi_assay_full_index.json"
EMBEDDINGS_PATH = OBI_DIR / "obi_assay_full_embeddings.json"
RESULTS_DIR = HERE / "results" / "flat1794"

#: Marks a term the live prune would have removed, so the output says which picks only this
#: arm could make. Same regex as assay_obi_mapper._COMPOSITIONAL_LABEL_RE.
_COMPOSITIONAL_RE = re.compile(r"\b(measuring|detecting)\b", re.IGNORECASE)


# ── vocabulary ────────────────────────────────────────────────────────────────

def build_index(obo_path: Path | None = None) -> list[dict]:
    """The full assay branch of obi.obo, annotated like the live index.

    Same shape as data/OBI/obi_assay_pruned_index.json (id, label, synonyms, definition,
    n_descendants, parents), same obo order, no prune at all: 1794 rows for the 2026-05-08 release.
    """
    import prune_obi_domain as prune

    obo = obo_path or prune.OBO_PATH
    source = prune.assay_branch(obo)
    _, children, definitions = prune.parse_obo(obo)
    return prune.annotate(source, definitions, children, parents=prune.parent_map(obo))


def write_index(path: Path = INDEX_PATH) -> list[dict]:
    terms = build_index()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(terms, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return terms


def rows_to_embed(index_path: Path = INDEX_PATH, output_path: Path = EMBEDDINGS_PATH) -> int:
    """How many rows build-embeddings would send to the API: those whose `embed_input` is not
    already in `output_path`. Mirrors scripts/build_obi_embeddings.py's reuse rule."""
    import build_obi_embeddings as builder

    terms = json.loads(index_path.read_text(encoding="utf-8"))
    cached = set()
    if output_path.exists():
        for row in json.loads(output_path.read_text(encoding="utf-8")):
            if "embed_input" in row:
                cached.add((row["id"], row["embed_input"]))
    return sum(1 for t in terms if (t["id"], builder.build_embed_input(t)) not in cached)


def build_embeddings(dry_run: bool) -> None:
    """Embed the experiment index into its own vectors file, reusing the live file's rows.

    The live embeddings are copied in first as the seed, so the 701 rows already embedded are
    reused and only the rows the prune removed are paid for. The live file itself is only read.
    """
    import build_obi_embeddings as builder
    from app.agent import assay_obi_mapper as mapper

    if not INDEX_PATH.exists():
        sys.exit(f"{INDEX_PATH} missing: run build-index first")
    if not EMBEDDINGS_PATH.exists() and mapper._EMBEDDINGS_PATH.exists():
        shutil.copyfile(mapper._EMBEDDINGS_PATH, EMBEDDINGS_PATH)
        print(f"seeded {EMBEDDINGS_PATH.name} from the live {mapper._EMBEDDINGS_PATH.name}")
    pending = rows_to_embed()
    print(f"{pending} row(s) to embed via {builder.EMBED_MODEL}")
    if dry_run:
        print("--dry-run: nothing called")
        return
    # build_obi_embeddings reads its paths from module globals and its key from the environment.
    from app.config import settings

    os.environ.setdefault("OPENAI_API_KEY", settings.OPENAI_API_KEY)
    builder.OBI_TERMS_PATH = INDEX_PATH
    builder.OUTPUT_PATH = EMBEDDINGS_PATH
    builder.main()


# ── the in-process patch ──────────────────────────────────────────────────────

class Unpruned:
    """Run the mapper over an unfiltered vocabulary for the duration of a `with` block.

    Patches `_is_generic_assay_term` to accept every term and `_EMBEDDINGS_PATH` to the
    experiment vectors, clearing every lru_cache that memoised the live vocabulary, and puts
    both back (clearing the caches again) on exit. The production module is never edited.
    """

    _CACHED = ("_load_embeddings", "_build_lookup", "_term_ids", "_index_children",
               "_index_parents", "_index_entries", "_term_details")

    def __init__(self, embeddings_path: Path = EMBEDDINGS_PATH) -> None:
        self.embeddings_path = embeddings_path

    @staticmethod
    def _clear_caches() -> None:
        from app.agent import assay_obi_mapper as mapper

        for name in Unpruned._CACHED:
            getattr(mapper, name).cache_clear()

    def __enter__(self) -> "Unpruned":
        from app.agent import assay_obi_mapper as mapper

        self._saved = (mapper._is_generic_assay_term, mapper._EMBEDDINGS_PATH)
        mapper._is_generic_assay_term = lambda obi_id, label: True
        mapper._EMBEDDINGS_PATH = self.embeddings_path
        self._clear_caches()
        return self

    def __exit__(self, *exc: object) -> None:
        from app.agent import assay_obi_mapper as mapper

        mapper._is_generic_assay_term, mapper._EMBEDDINGS_PATH = self._saved
        self._clear_caches()


# ── mapping ───────────────────────────────────────────────────────────────────

def plan_calls(assays: dict, index_path: Path = INDEX_PATH) -> list[tuple[str, int]]:
    """(registry key, calls) for every entry the paid step would see. No API call.

    Mirrors assay_service.obi_misses, which is fixed to the live vocabulary: an exact hit on a
    childless term is free; anything else costs obi_query_calls. Call inside `Unpruned`.
    """
    from app.agent.assay_obi_mapper import _build_lookup, _index_children
    from app.agent.assay_service import _obi_query, obi_query_calls

    lookup = _build_lookup(index_path)
    children = _index_children(index_path)
    planned = []
    for key, entry in assays.items():
        original, _ = _obi_query(key, entry)
        hit = lookup.get(original.lower()) if original else None
        if hit and not children.get(hit["obi_id"]):
            continue
        planned.append((key, obi_query_calls(key, entry)))
    return planned


def map_registry(registry_dir: Path, dry_run: bool, results_dir: Path = RESULTS_DIR,
                 index_path: Path = INDEX_PATH,
                 embeddings_path: Path = EMBEDDINGS_PATH) -> dict | None:
    """Round 4 over the 1794-term vocabulary, written beside this script, never into the registry."""
    from app.agent import assay_trace
    from app.agent.assay_obi_mapper import enrich_assays_with_obi

    assays = json.loads((registry_dir / "assays.json").read_text(encoding="utf-8"))
    if not index_path.exists():
        sys.exit(f"{index_path} missing: run build-index first")
    with Unpruned(embeddings_path):
        planned = plan_calls(assays, index_path)
        print(f"{registry_dir.name}: {len(assays)} entries, {len(planned)} reach the paid step,"
              f" ~{sum(c for _, c in planned)} calls")
        for key, calls in planned:
            print(f"  {calls} calls  {key}")
        if dry_run:
            print("--dry-run: nothing called")
            return None
        if not embeddings_path.exists():
            sys.exit(f"{embeddings_path} missing: run build-embeddings first")
        trace = assay_trace.start()
        try:
            obi = enrich_assays_with_obi(assays, terms_path=index_path)
        finally:
            assay_trace.stop()

    out_dir = results_dir / registry_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assays_OBI.json").write_text(
        json.dumps(obi, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    trace.write(out_dir / "raw.json")
    print(f"\nwrote {out_dir / 'assays_OBI.json'} and raw.json\n")
    for key, entry in obi.items():
        label = entry.get("obi_label") or "(unmapped)"
        mark = "  COMPOSITIONAL" if _COMPOSITIONAL_RE.search(label) else ""
        print(f"- {key}\n    -> {entry.get('obi_id')} {label} [{entry.get('obi_granularity')}]"
              f" via {entry.get('resource')}{mark}")
    return obi


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build-index", help="write the 1794-term index (free)")
    emb = sub.add_parser("build-embeddings", help="embed the index into its own vectors file")
    emb.add_argument("--dry-run", action="store_true")
    run = sub.add_parser("map", help="map a registry's assays.json against the 1794 terms")
    run.add_argument("registry_dir", type=Path)
    run.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.command == "build-index":
        terms = write_index()
        print(f"wrote {INDEX_PATH} ({len(terms)} terms)")
    elif args.command == "build-embeddings":
        build_embeddings(args.dry_run)
    else:
        map_registry(args.registry_dir, args.dry_run)


if __name__ == "__main__":
    main()
