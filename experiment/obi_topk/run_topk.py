#!/usr/bin/env python3
"""Would a longer candidate list (TOP_K 20 -> 30 / 40) help the OBI picker? On assay_result_v3.

Stage 1 answers the retrieval half without a single picker call: for every entry of the v3
registries, embed the mapper's two retrieval queries once (cached), then replay the mapper's own
retrieval and merge code offline at several K and record where the curator's term lands.

    embed-queries [--dry-run]   query_embeddings.json  (one embedding per new query string; no chat)
    recall                      recall/recall_at_k.{json,md}  (no network at all)

Stage 2 is the picker half, paid and gated: round 4 over the v3 registries with the list widened
to K, scored with the v2 comparator and diffed against the K=20 arm of the vocabulary A/B
(experiment/obi_vocab_v3/runs/pruned, 141 exact).

    pick --k 30 [--dry-run] [--force]   picks/k<K>/<registry>/...
    pick-score                          picks/comparison/*, picks/summary.md (free)

`TOP_K` and `PRIMARY_SLOTS` are bound as defaults inside the mapper, so assigning the module
constants changes nothing; `WidenedList` wraps `_top_k_candidates` and `_merge_candidates` for
the duration of the run instead, and restores them. The full-list fallback (picker says "none")
is switched off for the run: the K=20 arm predates it, and leaving it on would credit K with
whatever the fallback rescues. Nothing in production code or under data/ is written.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (REPO_ROOT / "apps" / "api", REPO_ROOT / "scripts", REPO_ROOT / "experiment" / "obi_vocab_v3"):
    sys.path.insert(0, str(p))

SOURCE_DIR = REPO_ROOT / "data" / "31paper_assays" / "assay_result_v3"
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_assay" / "benchmark_assay_v5"
INDEX = REPO_ROOT / "data" / "OBI" / "obi_assay_pruned_index.json"
CACHE_PATH = HERE / "query_embeddings.json"
RECALL_DIR = HERE / "recall"
PICKS_DIR = HERE / "picks"
K20_RUN = REPO_ROOT / "experiment" / "obi_vocab_v3" / "runs" / "pruned"
PAIRING_REPORT = REPO_ROOT / "experiment" / "obi_vocab_v3" / "comparison" / "pruned.json"
COMPARATOR = REPO_ROOT / "scripts" / "compare_assay_benchmark_v2.py"

KS = (10, 20, 30, 40, 60)
POOL = 100  # per-query pool depth before the merge; larger than any K


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def registries(source: Path = SOURCE_DIR) -> list[Path]:
    return sorted(d for d in source.iterdir() if d.is_dir() and (d / "assays.json").exists())


def primary_slots(k: int) -> int:
    """The paper-wording reserve, scaled with K: 14 of 20 -> 21 of 30 -> 28 of 40."""
    from app.agent import assay_obi_mapper as m

    return round(k * m.PRIMARY_SLOTS / m.TOP_K)


# ── the entries and their queries ─────────────────────────────────────────────

def entries(source: Path = SOURCE_DIR) -> list[dict]:
    """One record per registry entry with the exact strings the mapper retrieves on."""
    from app.agent.assay_extractor import paper_names
    from app.agent.assay_obi_mapper import _paper_query

    out = []
    for registry in registries(source):
        for key, entry in _read(registry / "assays.json").items():
            entry = dict(entry) if isinstance(entry, dict) else {"description": entry}
            names = paper_names(entry)
            original = (names[0] if names else key).strip()
            raw_aliases = entry.get("aliases")
            aliases = names[1:] + [a for a in (raw_aliases if isinstance(raw_aliases, list) else []) if isinstance(a, str)]
            normalized = str(entry.get("standard_technique_name") or "").strip()
            out.append({
                "registry": registry.name, "key": key, "name": original, "aliases": aliases,
                "paper_query": _paper_query(original, aliases),
                "technique_query": normalized if normalized and normalized.lower() != original.lower() else "",
            })
    return out


def query_strings(records: list[dict]) -> list[str]:
    seen, out = set(), []
    for r in records:
        for q in (r["paper_query"], r["technique_query"]):
            if q and q not in seen:
                seen.add(q)
                out.append(q)
    return out


def embed_queries(dry_run: bool, cache_path: Path = CACHE_PATH, source: Path = SOURCE_DIR) -> dict:
    from app.agent.assay_obi_mapper import _embed_query

    cache = _read(cache_path) if cache_path.exists() else {}
    todo = [q for q in query_strings(entries(source)) if q not in cache]
    print(f"{len(cache)} cached, {len(todo)} query string(s) to embed")
    if dry_run:
        print("--dry-run: nothing called")
        return cache
    for i, q in enumerate(todo, 1):
        cache[q] = [float(x) for x in _embed_query(q)]
        if i % 50 == 0 or i == len(todo):
            _write(cache_path, cache)
            print(f"  {i}/{len(todo)} embedded")
    _write(cache_path, cache)
    return cache


class CachedQueries:
    """Serve `_embed_query` from the cache for a `with` block; a miss is an error, never a call."""

    def __init__(self, cache: dict):
        self.cache = cache

    def __enter__(self):
        from app.agent import assay_obi_mapper as m

        self._saved = m._embed_query

        def cached(text: str) -> np.ndarray:
            if text not in self.cache:
                raise KeyError(f"query not in the embedding cache: {text[:80]!r}")
            vec = np.array(self.cache[text], dtype=np.float64)
            norm = np.linalg.norm(vec)
            return vec / norm if norm > 0 else vec

        m._embed_query = cached
        return self

    def __exit__(self, *exc):
        from app.agent import assay_obi_mapper as m

        m._embed_query = self._saved


# ── stage 1: recall@K, offline ────────────────────────────────────────────────

def candidate_list(record: dict, k: int, primary: int, terms_path: Path = INDEX) -> tuple[list[dict], dict | None]:
    """The list the picker would see at this K, built with the mapper's own functions.

    Returns (list, leaf_hit): when the paper's name exact-matches a childless term the mapper
    answers without a list, and `leaf_hit` carries that term instead.
    """
    from app.agent import assay_obi_mapper as m

    hit = m._build_lookup(terms_path).get(record["name"].lower())
    pinned = None
    if hit:
        if not m._index_children(terms_path).get(hit["obi_id"]):
            return [], hit
        pinned = m._pinned_candidates(hit["obi_id"], terms_path)
    allowed = m._term_ids(terms_path)
    pools = [m._top_k_candidates(record["paper_query"], k=POOL, allowed_ids=allowed)]
    if record["technique_query"]:
        pools.append(m._top_k_candidates(record["technique_query"], k=POOL, allowed_ids=allowed))
    cands = m._merge_candidates(*pools, k=k, primary_slots=primary)
    if pinned:
        cands = m._with_pinned(cands, pinned)
    return cands, None


def recall(cache: dict, curated: dict, records: list[dict], ks=KS, terms_path: Path = INDEX) -> dict:
    """Per K: how often the curated term is on the list the picker sees, and at what rank."""
    scored = [r for r in records if curated.get((r["registry"], r["key"]))]
    result = {"scored_entries": len(scored), "ks": list(ks), "per_k": {}}
    with CachedQueries(cache):
        for k in ks:
            primary = primary_slots(k)
            hits, lengths, rows = 0, [], []
            for r in scored:
                cur = curated[(r["registry"], r["key"])]
                cands, leaf = candidate_list(r, k, primary, terms_path)
                if leaf:
                    hit, rank, length = leaf["obi_id"] == cur, 1 if leaf["obi_id"] == cur else None, 1
                else:
                    ids = [c["id"] for c in cands]
                    hit = cur in ids
                    rank = ids.index(cur) + 1 if hit else None
                    length = len(cands)
                hits += hit
                lengths.append(length)
                rows.append({"registry": r["registry"], "key": r["key"], "curated": cur,
                             "hit": hit, "rank": rank, "list_len": length})
            result["per_k"][str(k)] = {"primary_slots": primary, "hits": hits, "recall": hits / len(scored),
                                       "mean_list_len": sum(lengths) / len(lengths), "rows": rows}
    return result


def render_recall(result: dict) -> str:
    ks = result["ks"]
    per_k = result["per_k"]
    lines = [f"# Retrieval recall@K on assay_result_v3, {result['scored_entries']} entries with a curated OBI term", "",
             "| K | paper-wording slots | curated term on the list | recall | mean list length |",
             "|---|---|---|---|---|"]
    for k in ks:
        s = per_k[str(k)]
        lines.append(f"| {k} | {s['primary_slots']} | {s['hits']} | {s['recall']:.1%} | {s['mean_list_len']:.1f} |")
    base_k = 20 if 20 in ks else ks[0]
    wider = [k for k in ks if k > base_k]
    lines += ["", f"## Curated terms NOT on the K={base_k} list, and their rank at wider K", "",
              "| registry | entry | curated | " + " | ".join(f"rank at K={k}" for k in wider) + " |",
              "|---|---|---|" + "---|" * len(wider)]
    for row in per_k[str(base_k)]["rows"]:
        if row["hit"]:
            continue
        key = (row["registry"], row["key"])
        ranks = [next((x["rank"] for x in per_k[str(k)]["rows"] if (x["registry"], x["key"]) == key), None)
                 for k in wider]
        lines.append(f"| {row['registry']} | {row['key']} | {row['curated']} | "
                     + " | ".join(str(x) if x else "—" for x in ranks) + " |")
    return "\n".join(lines) + "\n"


def run_recall(cache_path: Path = CACHE_PATH, out_dir: Path = RECALL_DIR, source: Path = SOURCE_DIR,
               pairing: Path = PAIRING_REPORT) -> dict:
    from run_vocab_comparison import curator_terms

    curated = {k: v["obi_id"] for k, v in curator_terms(_read(pairing)).items() if v.get("obi_id")}
    result = recall(_read(cache_path), curated, entries(source))
    _write(out_dir / "recall_at_k.json", result)
    md = render_recall(result)
    (out_dir / "recall_at_k.md").write_text(md, encoding="utf-8")
    print(md)
    return result


# ── stage 2: the picker at K ──────────────────────────────────────────────────

class WidenedList:
    """Run the mapper with TOP_K=K, a proportionally wider paper-wording reserve, and no
    full-list fallback (the K=20 arm it is compared with predates the fallback)."""

    def __init__(self, k: int):
        self.k = k

    def __enter__(self):
        from app.agent import assay_obi_mapper as m

        self.primary = primary_slots(self.k)
        self._saved = (m._top_k_candidates, m._merge_candidates, m._fulllist_pick)
        top, merge, k, primary = m._top_k_candidates, m._merge_candidates, self.k, self.primary
        m._top_k_candidates = lambda query, k=k, **kw: top(query, k=k, **kw)
        m._merge_candidates = lambda first, *others, **kw: merge(first, *others, k=k, primary_slots=primary)
        m._fulllist_pick = lambda *a, **kw: None
        return self

    def __exit__(self, *exc):
        from app.agent import assay_obi_mapper as m

        m._top_k_candidates, m._merge_candidates, m._fulllist_pick = self._saved


def run_pick(k: int, dry_run: bool, cache_path: Path = CACHE_PATH, source: Path = SOURCE_DIR,
             picks_dir: Path = PICKS_DIR, force: bool = False) -> None:
    from app.agent import assay_trace
    from app.agent.assay_obi_mapper import enrich_assays_with_obi
    from app.agent.assay_service import obi_summary
    from run_vocab_comparison import plan

    dirs = registries(source)
    out_root = picks_dir / f"k{k}"
    if dry_run:
        chat = sum(len(plan("pruned", _read(d / "assays.json"))) for d in dirs)
        print(f"K={k}: {len(dirs)} registries, ~{chat} chat picks (query embeddings served from cache)")
        print("--dry-run: nothing called")
        return
    cache = _read(cache_path)
    picks = 0
    with CachedQueries(cache), WidenedList(k):
        for d in dirs:
            out_dir = out_root / d.name
            if (out_dir / "assays_OBI.json").exists() and not force:
                print(f"   skip {d.name}: already mapped")
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            for name in ("assays.json", "assays_benchmark.json"):
                shutil.copyfile(d / name, out_dir / name)
            trace = assay_trace.start()
            try:
                obi = enrich_assays_with_obi(_read(d / "assays.json"), terms_path=INDEX)
            finally:
                assay_trace.stop()
            _write(out_dir / "assays_OBI.json", obi)
            trace.write(out_dir / "raw.json")
            s = obi_summary(obi)
            picks += sum(1 for e in obi.values() if e.get("resource") != "exact_original")
            print(f"   {d.name}: {s['mapped']}/{s['total']} mapped {s['resources']}", flush=True)
            for key in s["unresolved"]:
                print(f"      {'OBI ERROR' if key in s['errors'] else 'UNMAPPED '}  {key}")
    print(f"K={k}: ~{picks} chat picks this run (embeddings were cached)")


def run_pick_score(picks_dir: Path = PICKS_DIR, k20_run: Path = K20_RUN, pairing: Path = PAIRING_REPORT) -> None:
    import subprocess

    from run_vocab_comparison import curator_terms, diff_arms

    curated = curator_terms(_read(pairing))
    pruned_ids = {t["id"] for t in _read(INDEX)}
    base = _read(pairing)["totals"]
    lines = ["# Picker at wider K vs K=20, assay_result_v3 against benchmark v5", "",
             "| run | matched | exact | OBI ok | CONFLICT | UNMAPPED | obi_exact_rate | obi_recall |",
             "|---|---|---|---|---|---|---|---|"]

    def row(name: str, t: dict) -> str:
        sc = t["status_counts"]
        return (f"| {name} | {t['matched']} | {t['exact']} | {t['obi_ok']} | {sc['MATCH_OBI_CONFLICT']} | "
                f"{sc['MATCH_OBI_UNMAPPED']} | {t['obi_exact_rate']:.1%} | {t['obi_recall']:.1%} |")

    lines.append(row("k20 (obi_vocab_v3 pruned)", base))
    runs = sorted(p for p in picks_dir.iterdir() if p.is_dir() and p.name.startswith("k"))
    for d in runs:
        subprocess.run([sys.executable, str(COMPARATOR), "--registry-dir", str(d),
                        "--benchmark-dir", str(BENCHMARK_DIR), "--out-stem", d.name],
                       check=True, cwd=REPO_ROOT)
        out = picks_dir / "comparison"
        out.mkdir(parents=True, exist_ok=True)
        for suffix in (".json", ".html"):
            shutil.copyfile(d / "comparison" / f"{d.name}{suffix}", out / f"{d.name}{suffix}")
        lines.append(row(d.name, _read(out / f"{d.name}.json")["totals"]))
    for d in runs:
        diff = diff_arms("k20", d.name, {"k20": k20_run, d.name: d}, curated, pruned_ids)
        counts = Counter(r["agrees_with_curator"] for r in diff)
        lines += ["", f"## K=20 vs {d.name}: {len(diff)} entries changed — {dict(counts)}", "",
                  f"| registry | entry | K=20 | {d.name} | curator | agrees |", "|---|---|---|---|---|---|"]
        for r in diff:
            cur = r["curator"] or {}
            lines.append(f"| {r['registry']} | {r['key']} | {r['k20']['obi_id']} {r['k20']['obi_label']} | "
                         f"{r[d.name]['obi_id']} {r[d.name]['obi_label']} | "
                         f"{cur.get('obi_id') or '—'} {cur.get('obi_label') or ''} | {r['agrees_with_curator']} |")
    md = "\n".join(lines) + "\n"
    (picks_dir / "summary.md").write_text(md, encoding="utf-8")
    print(md)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("embed-queries")
    e.add_argument("--dry-run", action="store_true")
    sub.add_parser("recall")
    p = sub.add_parser("pick")
    p.add_argument("--k", type=int, required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    sub.add_parser("pick-score")
    args = parser.parse_args()
    if args.command == "embed-queries":
        embed_queries(args.dry_run)
    elif args.command == "recall":
        run_recall()
    elif args.command == "pick":
        run_pick(args.k, args.dry_run, force=args.force)
    else:
        run_pick_score()


if __name__ == "__main__":
    main()
