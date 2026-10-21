#!/usr/bin/env python3
"""Recall of the OBI mapper's candidate list against the curated benchmark. Free: no API call.

Every pick the mapper makes keeps its numbered candidate lines in the paper's assays_raw.json
(`["obi"][<extractor key>]["candidates"]`), and a benchmark comparison
(scripts/compare_assay_benchmark_v2.py) pairs each curated row with the agent entry it matched.
Joining the two says, per matched row, whether the curator's term was among the candidates the
picker was shown -- the retrieval ceiling -- and, for the rows where it was not, whether a
candidate-list change would have added it. Two are simulated from the index and obi.obo alone:

  neighbours  the direct is_a parents and children of the first --top retrieved candidates,
              children only when the term has at most --max-children in the index -- what
              assay_obi_mapper._with_neighbours adds since 2026-10-19;
  --lexical   a BM25 pool (top --lexical-k) over `label | synonyms`, queried with the entry's
              name, aliases and technique -- measured 2026-10-19 and NOT adopted: it added the
              curator's term in 0 of the 5 misses. Kept so the number can be re-checked.

A row whose candidate list was recorded before neighbours existed shows what the expansion
would have added; one recorded after shows them already present (recall "in list" rises, the
"neighbours add" column falls to 0). Rows whose agent entry resolved by exact match have no
list; they count as a hit on their own term.

Usage:
    python3 scripts/eval_obi_retrieval.py [--comparison PATH] [--top 3] [--max-children 8]
                                          [--lexical] [--lexical-k 5] [--show-misses]

Reads  : the comparison JSON (default data/benchmark_assay/comparison/benchmark_vs_stability.json)
         and each paper's assays_raw.json, assays_merges.json, assays_corrected.json
Writes : nothing
"""

import argparse
import collections
import json
import math
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.assay_obi_mapper import (  # noqa: E402
    _OBI_TERMS_PATH,
    MAX_NEIGHBOUR_CHILDREN,
    NEIGHBOUR_TOP,
    _index_children,
    _index_parents,
)

DEFAULT_COMPARISON = _REPO_ROOT / "data" / "benchmark_assay" / "comparison" / "benchmark_vs_stability.json"
_CANDIDATE_ID = re.compile(r"^\d+\.\s+(OBI:\d+|[A-Z]+:\d+)")
#: Marks that say a line was pinned rather than retrieved; such lines are not anchors.
_PINNED_MARKS = ("exact name match", "child of candidate", "parent of candidate")


def _tokens(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) >= 2]


class _BM25:
    """Okapi BM25 over the index's `label | synonyms`; the measurement's lexical pool."""

    def __init__(self, terms: list[dict], k1: float = 1.5, b: float = 0.75):
        self.docs = {t["id"]: _tokens(" ".join([t["label"], *(t.get("synonyms") or [])]))
                     for t in terms}
        self.k1, self.b = k1, b
        self.n = len(self.docs)
        self.avgdl = sum(map(len, self.docs.values())) / max(1, self.n)
        self.df = collections.Counter(w for d in self.docs.values() for w in set(d))

    def top(self, query: str, k: int) -> list[str]:
        q = _tokens(query)
        scores: dict[str, float] = {}
        for obi_id, doc in self.docs.items():
            tf = collections.Counter(doc)
            score = 0.0
            for w in q:
                if w in tf:
                    idf = math.log((self.n - self.df[w] + 0.5) / (self.df[w] + 0.5) + 1)
                    denom = tf[w] + self.k1 * (1 - self.b + self.b * len(doc) / self.avgdl)
                    score += idf * tf[w] * (self.k1 + 1) / denom
            if score > 0:
                scores[obi_id] = score
        return [i for i, _ in sorted(scores.items(), key=lambda x: -x[1])[:k]]


def _candidate_ids(lines: list[str]) -> list[str]:
    return [m.group(1) for m in (_CANDIDATE_ID.match(line) for line in lines) if m]


def _anchor_ids(lines: list[str], top: int) -> list[str]:
    retrieved = [line for line in lines if not any(mark in line for mark in _PINNED_MARKS)]
    return _candidate_ids(retrieved)[:top]


def _neighbours(anchors: list[str], children: dict, parents: dict, max_children: int) -> set[str]:
    out: set[str] = set()
    for anchor in anchors:
        out.update(parents.get(anchor, ()))
        kids = children.get(anchor, ())
        if len(kids) <= max_children:
            out.update(kids)
    return out


def _query(entry: dict, key: str) -> str:
    names = entry.get("name_in_paper")
    names = names if isinstance(names, list) else [names or key]
    return " | ".join([*names, *(entry.get("aliases") or []),
                       entry.get("standard_technique_name") or ""])


def evaluate(comparison: dict, top: int, max_children: int, lexical_k: int | None) -> dict:
    terms = json.loads(_OBI_TERMS_PATH.read_text(encoding="utf-8"))
    labels = {t["id"]: t["label"] for t in terms}
    children, parents = _index_children(), _index_parents()
    bm25 = _BM25(terms) if lexical_k else None
    counts: collections.Counter = collections.Counter()
    misses: list[dict] = []
    for paper in comparison["papers"]:
        registry_dir = _REPO_ROOT / paper["registry_dir"]
        raw = json.loads((registry_dir / "assays_raw.json").read_text(encoding="utf-8")).get("obi", {})
        key_map = json.loads((registry_dir / "assays_merges.json").read_text(encoding="utf-8")).get("key_map", {})
        corrected = json.loads((registry_dir / "assays_corrected.json").read_text(encoding="utf-8"))
        by_canonical: dict[str, list[str]] = collections.defaultdict(list)
        for pre, canonical in key_map.items():
            by_canonical[canonical].append(pre)
        for row in paper["rows"]:
            if not row["status"].startswith("MATCH"):
                continue
            curated = row["benchmark"].get("obi_id")
            if not curated:
                counts["curator left the term blank"] += 1
                continue
            ours = row["ours"][0]
            pres = by_canonical.get(ours["key"]) or [ours["key"]]
            lines = [line for pre in pres for line in (raw.get(pre) or {}).get("candidates", [])]
            candidates = _candidate_ids(lines) or [ours.get("obi_id")]
            counts["rows"] += 1
            if curated in candidates:
                counts["in list"] += 1
                continue
            counts["absent"] += 1
            neighbours = _neighbours(_anchor_ids(lines, top), children, parents, max_children)
            lexical = set(bm25.top(_query(corrected.get(pres[0], {}), pres[0]), lexical_k)) if bm25 else set()
            if curated in neighbours:
                counts["absent, neighbours add it"] += 1
            if bm25 and curated in lexical:
                counts["absent, lexical adds it"] += 1
            misses.append({"study": paper["study"], "entry": pres[0], "ours": ours.get("obi_id"),
                           "curated": curated, "curated_label": labels.get(curated, "?"),
                           "neighbours": curated in neighbours,
                           "lexical": (curated in lexical) if bm25 else None})
    return {"counts": dict(counts), "misses": misses}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--comparison", type=Path, default=DEFAULT_COMPARISON)
    parser.add_argument("--top", type=int, default=NEIGHBOUR_TOP,
                        help="retrieved candidates whose neighbours are simulated")
    parser.add_argument("--max-children", type=int, default=MAX_NEIGHBOUR_CHILDREN)
    parser.add_argument("--lexical", action="store_true", help="also simulate the BM25 pool")
    parser.add_argument("--lexical-k", type=int, default=5)
    parser.add_argument("--show-misses", action="store_true")
    args = parser.parse_args()

    comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
    result = evaluate(comparison, args.top, args.max_children,
                      args.lexical_k if args.lexical else None)
    c = result["counts"]
    rows = c.get("rows", 0)
    print(f"{args.comparison.relative_to(_REPO_ROOT)}: {rows} matched rows with a curated term")
    print(f"  curator's term among the candidates shown : {c.get('in list', 0)} / {rows}")
    print(f"  absent                                     : {c.get('absent', 0)}")
    print(f"    neighbours (top {args.top}, <= {args.max_children} children) would add it : "
          f"{c.get('absent, neighbours add it', 0)}")
    if args.lexical:
        print(f"    lexical BM25 top {args.lexical_k} would add it : {c.get('absent, lexical adds it', 0)}")
    print(f"  curator left the term blank (not scored)   : {c.get('curator left the term blank', 0)}")
    if args.show_misses:
        for m in result["misses"]:
            flags = ("N" if m["neighbours"] else "-") + ("L" if m["lexical"] else "-")
            print(f"    {flags} {m['study']:8} {m['entry'][:48]:48} ours={m['ours']} "
                  f"curated={m['curated']} {m['curated_label']}")


if __name__ == "__main__":
    main()
