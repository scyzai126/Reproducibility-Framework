"""Map the flat assay table to OBI ontology terms.

Uses the repo's existing three-step chain in app.agent.assay_obi_mapper:
  1. exact match on the paper's name   -> resource: exact_original,  confidence "high"
  2. exact match on the normalized name -> resource: exact_normalized, confidence "high"
  3. embedding top-10 + LLM pick        -> resource: embedding_llm,  confidence = similarity

The existing CLIs (run_obi_map.py, map_assays_obi.py, the skill's obi_enrich_file.py) all
take a per-study registry dict keyed by assay name; this one takes the flat corpus-wide
table checked in at data/claims/all_assays_full.json.

Each distinct (assay, normalized_name) pair is mapped once and the result fanned back out
to every row sharing it — fewer calls, and the same assay name is guaranteed the same OBI
id in every paper. A pair can appear with different sample types across papers; the first
row's sample_type/readouts are the ones passed through. That only affects step 3, where
resolver_obi_assay.txt treats them as secondary disambiguating context by design; steps 1-2
ignore them entirely.

The OBI confidence is written as `obi_confidence`, not `confidence`: registries carry an
extraction confidence under the latter, and enrich_assays_with_obi overwrites it.

Usage:
    python scripts/map_assays_to_obi.py [--in FILE] [--out FILE] [--terms PATH]
                                        [--force] [--dry-run]

--dry-run reports the exact-match split without making a single API call. Results are
cached in data/claims/obi_cache.json, so a re-run costs nothing unless --force is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.agent.assay_obi_mapper import (  # noqa: E402
    _OBI_TERMS_PATH,
    _build_lookup,
    map_assay_to_obi,
)

IN_PATH = ROOT / "data" / "claims" / "all_assays_full.json"
OUT_PATH = ROOT / "data" / "claims" / "all_assays_full_OBI.json"
CACHE_PATH = ROOT / "data" / "claims" / "obi_cache.json"

UNRESOLVED = {"obi_id": None, "obi_label": None, "resource": "unresolved", "confidence": None}


def _pairs_with_context(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Distinct (assay, normalized_name) pairs -> the first row's disambiguating context."""
    pairs: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row.get("assay", ""), row.get("normalized_name", ""))
        pairs.setdefault(
            key,
            {
                "sample_type": str(row.get("sample_type") or ""),
                "readouts": str(row.get("readouts") or ""),
            },
        )
    return pairs


def _resolves_locally(assay: str, normalized: str, terms_path: Path) -> str | None:
    """Which exact-match step would catch this pair, if any. No API call."""
    lookup = _build_lookup(terms_path)
    if lookup.get(assay.strip().lower()):
        return "exact_original"
    if normalized.strip() and lookup.get(normalized.strip().lower()):
        return "exact_normalized"
    return None


def _cache_key(assay: str, normalized: str) -> str:
    return f"{assay}\x1f{normalized}"


def _decision_key(assay: str, normalized: str, terms_path: Path) -> str:
    """The input that actually decides this pair's OBI term.

    Steps 1-2 key on the pair, because they test the paper's name and then the
    normalized name as literal strings. Step 3 keys on its *query* — which is the
    normalized name, falling back to the paper's — because that, plus the candidate
    list it retrieves, is the whole input to the LLM's pick.

    Grouping by this rather than by the pair is what stops two assay names sharing a
    normalized name from getting different OBI terms out of an identical query. That
    happened: "ImmunoChip array" and "Whole-genome genotyping" both normalize to
    "Genome-wide SNP genotyping", and the model answered differently for each.
    """
    if _resolves_locally(assay, normalized, terms_path):
        return f"exact\x1f{_cache_key(assay, normalized)}"
    return f"query\x1f{normalized.strip() or assay.strip()}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_path", type=Path, default=IN_PATH)
    parser.add_argument("--out", dest="out_path", type=Path, default=OUT_PATH)
    parser.add_argument("--terms", type=Path, default=_OBI_TERMS_PATH)
    parser.add_argument("--force", action="store_true", help="ignore the cache and remap")
    parser.add_argument("--dry-run", action="store_true", help="report only, no API calls")
    args = parser.parse_args()

    rows = json.loads(args.in_path.read_text(encoding="utf-8"))
    pairs = _pairs_with_context(rows)
    print(f"{len(rows)} rows, {len(pairs)} distinct (assay, normalized_name) pairs")
    print(f"Vocabulary: {args.terms.name}\n")

    if args.dry_run:
        steps = Counter(
            _resolves_locally(assay, normalized, args.terms) or "embedding_llm"
            for assay, normalized in pairs
        )
        for step, count in steps.most_common():
            print(f"  {step:18s} {count}")
        fallback = steps["embedding_llm"]
        print(f"\n{fallback} pairs would need an embedding + LLM call. No API calls made.")
        return 0

    cache: dict[str, dict | None] = {}
    if CACHE_PATH.exists() and not args.force:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    # Pairs that share a decision key must share an answer, so map once per key.
    groups: dict[str, list[tuple[str, str]]] = {}
    for pair in sorted(pairs):
        groups.setdefault(_decision_key(*pair, args.terms), []).append(pair)

    # Carry forward results cached under the old per-pair keys, so tightening the key
    # does not re-decide the whole corpus. A group whose members disagree is exactly
    # the inconsistency this key change exists to fix — drop it and let it recompute.
    for key, members in groups.items():
        if key in cache:
            continue
        previous = [cache[_cache_key(*p)] for p in members if _cache_key(*p) in cache]
        if len(previous) == len(members) and all(p == previous[0] for p in previous):
            cache[key] = previous[0]
    for pair in pairs:
        cache.pop(_cache_key(*pair), None)

    mapped: dict[tuple[str, str], dict] = {}
    for key, members in groups.items():
        if key in cache:
            result = cache[key]
        else:
            assay, normalized = members[0]
            result = map_assay_to_obi(
                assay,
                normalized,
                terms_path=args.terms,
                sample_type=pairs[members[0]]["sample_type"],
                readouts=pairs[members[0]]["readouts"],
            )
            cache[key] = result
        entry = result or UNRESOLVED
        for pair in members:
            mapped[pair] = entry
        shared = f"  (shared by {len(members)} names)" if len(members) > 1 else ""
        print(f"  {members[0][0][:52]:54s} -> {entry['obi_id'] or '—'} | "
              f"{entry['obi_label'] or '—'} ({entry['resource']}){shared}")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")

    enriched = []
    for row in rows:
        entry = mapped[(row.get("assay", ""), row.get("normalized_name", ""))]
        enriched.append(
            {
                **row,
                "obi_id": entry["obi_id"],
                "obi_label": entry["obi_label"],
                "resource": entry["resource"],
                "obi_confidence": entry["confidence"],
            }
        )

    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    args.out_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")

    by_resource = Counter(r["resource"] for r in enriched)
    unresolved = sorted({a for (a, _), e in mapped.items() if e["resource"] == "unresolved"})
    display = args.out_path
    if display.is_relative_to(ROOT):
        display = display.relative_to(ROOT)
    print(f"\nWrote {display}")
    print(f"  {len(enriched)} rows, {len(by_resource)} resources")
    for resource, count in by_resource.most_common():
        print(f"    {resource:18s} {count} rows")
    if unresolved:
        print(f"\n  {len(unresolved)} assay names left unresolved (no OBI term invented):")
        for name in unresolved:
            print(f"    - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
