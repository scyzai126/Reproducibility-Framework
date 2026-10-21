#!/usr/bin/env python3
"""Would a longer candidate list (TOP_K 20 -> 30 / 40 / 60) help the OBI picker?

Stage 1 answers the retrieval half without a single picker call: for every entry of the 31-paper
corpus, embed the mapper's two retrieval queries once (cached), then replay the mapper's own
retrieval and merge code offline at several K and record where the curator's term lands.

    embed-queries [--dry-run]   query_embeddings.json  (<= 314 embedding calls, once; no chat)
    recall                      recall/recall_at_k.{json,md}  (no network at all)

Stage 2 is the picker half, paid and gated: one full mapping of the corpus with TOP_K patched to K,
scored like experiment/obi_vocab_31papers and diffed against its K=20 run.

    pick --vocab pruned|full --k 30 [--dry-run]   picks/<vocab>_k<K>/...  (~150 chat calls)
    pick-score                                    picks/comparison/*, picks/summary.md (free)

`TOP_K` and `PRIMARY_SLOTS` are bound as defaults inside the mapper, so they are not changed by
assigning the module constants; `pick` wraps `_top_k_candidates` and `_merge_candidates` for the
duration of the run instead, and restores them. Nothing in production code or under data/ is
written.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (REPO_ROOT / "apps" / "api", REPO_ROOT / "scripts",
          REPO_ROOT / "experiment" / "obi_analyte_terms", REPO_ROOT / "experiment" / "obi_vocab_31papers"):
    sys.path.insert(0, str(p))

STABILITY_DIR = REPO_ROOT / "data" / "31paper_assays" / "stability"
OBI_DIR = REPO_ROOT / "data" / "OBI"
VOCABS = {
    "pruned": {"index": OBI_DIR / "obi_assay_pruned_index.json", "embeddings": OBI_DIR / "obi_assay_pruned_embeddings.json"},
    "full": {"index": OBI_DIR / "obi_assay_full_index.json", "embeddings": OBI_DIR / "obi_assay_full_embeddings.json"},
}
CACHE_PATH = HERE / "query_embeddings.json"
RECALL_DIR = HERE / "recall"
PICKS_DIR = HERE / "picks"
K20_RUNS = REPO_ROOT / "experiment" / "obi_vocab_31papers" / "runs"
PAIRING_REPORT = REPO_ROOT / "experiment" / "obi_vocab_31papers" / "comparison" / "pruned.json"

KS = (10, 20, 30, 40, 60)
POOL = 100  # per-query pool depth before the merge; larger than any K
_COMPOSITIONAL_RE = re.compile(r"\b(measuring|detecting)\b", re.IGNORECASE)


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ── the entries and their queries ─────────────────────────────────────────────

def entries(source: Path = STABILITY_DIR) -> list[dict]:
    """One record per registry entry with the exact strings the mapper retrieves on."""
    from app.agent.assay_extractor import paper_names
    from app.agent.assay_obi_mapper import _paper_query

    out = []
    for registry in sorted(d for d in source.iterdir() if d.is_dir() and (d / "assays.json").exists()):
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


def embed_queries(dry_run: bool, cache_path: Path = CACHE_PATH, source: Path = STABILITY_DIR) -> dict:
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

def candidate_list(record: dict, k: int, primary_slots: int, terms_path: Path) -> tuple[list[dict], dict | None]:
    """The list the picker would see at this K, built with the mapper's own functions.

    Returns (list, leaf_hit): when the paper's name exact-matches a childless term the mapper
    answers without a list, and `leaf_hit` carries that term instead.
    """
    from app.agent import assay_obi_mapper as m

    lookup = m._build_lookup(terms_path)
    hit = lookup.get(record["name"].lower())
    pinned = None
    if hit:
        if not m._index_children(terms_path).get(hit["obi_id"]):
            return [], hit
        pinned = m._pinned_candidates(hit["obi_id"], terms_path)
    allowed = m._term_ids(terms_path)
    pools = [m._top_k_candidates(record["paper_query"], k=POOL, allowed_ids=allowed, terms_path=terms_path)]
    if record["technique_query"]:
        pools.append(m._top_k_candidates(record["technique_query"], k=POOL, allowed_ids=allowed, terms_path=terms_path))
    cands = m._merge_candidates(*pools, k=k, primary_slots=primary_slots)
    if pinned:
        cands = m._with_pinned(cands, pinned)
    cands = m._with_neighbours(cands, terms_path)
    return cands, None


def recall(cache: dict, curated: dict, records: list[dict], ks=KS, vocabs=VOCABS,
           pruned_index: Path = VOCABS["pruned"]["index"], scale_primary: bool = True) -> dict:
    """Per vocabulary and K: how often the curated term is on the list, and the decoy load."""
    from app.agent import assay_obi_mapper as m
    from exp_obi_flat1794 import Unpruned

    pruned_ids = {t["id"] for t in _read(pruned_index)}
    scored = [r for r in records if curated.get((r["registry"], r["key"]))]
    result = {"scored_entries": len(scored), "ks": list(ks), "vocabs": {}}
    with CachedQueries(cache):
        for vocab, paths in vocabs.items():
            per_k = {}
            ctx = Unpruned(paths["embeddings"]) if vocab == "full" else None
            if ctx:
                ctx.__enter__()
            try:
                m._load_embeddings.cache_clear()
                for k in ks:
                    primary = round(k * m.PRIMARY_SLOTS / m.TOP_K) if scale_primary else m.PRIMARY_SLOTS
                    hits, ranks, lengths, decoys, outside, rows = 0, [], [], [], [], []
                    for r in scored:
                        cur = curated[(r["registry"], r["key"])]
                        cands, leaf = candidate_list(r, k, primary, paths["index"])
                        if leaf:
                            hit = leaf["obi_id"] == cur
                            rank = 1 if hit else None
                            length, n_dec, n_out = 1, 0, 0
                        else:
                            ids = [c["id"] for c in cands]
                            hit = cur in ids
                            rank = ids.index(cur) + 1 if hit else None
                            length = len(cands)
                            n_dec = sum(1 for c in cands if _COMPOSITIONAL_RE.search(c["label"]))
                            n_out = sum(1 for c in cands if c["id"] not in pruned_ids)
                        hits += hit
                        lengths.append(length); decoys.append(n_dec); outside.append(n_out)
                        rows.append({"registry": r["registry"], "key": r["key"], "curated": cur,
                                     "hit": hit, "rank": rank, "list_len": length,
                                     "compositional": n_dec, "outside_pruned": n_out})
                    per_k[str(k)] = {
                        "primary_slots": primary, "hits": hits, "recall": hits / len(scored),
                        "mean_list_len": sum(lengths) / len(lengths),
                        "mean_compositional": sum(decoys) / len(decoys),
                        "mean_outside_pruned": sum(outside) / len(outside),
                        "rows": rows,
                    }
            finally:
                if ctx:
                    ctx.__exit__(None, None, None)
                m._load_embeddings.cache_clear()
            result["vocabs"][vocab] = per_k
    return result


def render_recall(result: dict) -> str:
    ks = result["ks"]
    lines = [f"# Retrieval recall@K, {result['scored_entries']} entries with a curated OBI term", ""]
    for vocab, per_k in result["vocabs"].items():
        lines += [f"## {vocab}", "", "| K | paper-wording slots | curated term on the list | recall | mean list length | mean compositional on list | mean outside-701 on list |",
                  "|---|---|---|---|---|---|---|"]
        for k in ks:
            s = per_k[str(k)]
            lines.append(f"| {k} | {s['primary_slots']} | {s['hits']} | {s['recall']:.1%} | {s['mean_list_len']:.1f} | "
                         f"{s['mean_compositional']:.1f} | {s['mean_outside_pruned']:.1f} |")
        base_k = 20 if 20 in ks else ks[0]
        wider = [k for k in ks if k > base_k]
        base = {(r["registry"], r["key"]): r for r in per_k[str(base_k)]["rows"]}
        lines += ["", f"### {vocab}: curated terms NOT on the K={base_k} list, and their rank at wider K", "",
                  "| registry | entry | curated | " + " | ".join(f"rank at K={k}" for k in wider) + " |",
                  "|---|---|---|" + "---|" * len(wider)]
        for key, row in base.items():
            if row["hit"]:
                continue
            ranks = [next((x["rank"] for x in per_k[str(k)]["rows"] if (x["registry"], x["key"]) == key), None)
                     for k in wider]
            lines.append(f"| {row['registry']} | {row['key']} | {row['curated']} | " + " | ".join(str(x) if x else "—" for x in ranks) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"


def run_recall(cache_path: Path = CACHE_PATH, out_dir: Path = RECALL_DIR, source: Path = STABILITY_DIR,
               pairing: Path = PAIRING_REPORT) -> dict:
    from run_vocab_comparison import curator_terms

    cache = _read(cache_path)
    curated = {k: v["obi_id"] for k, v in curator_terms(_read(pairing)).items() if v.get("obi_id")}
    result = recall(cache, curated, entries(source))
    _write(out_dir / "recall_at_k.json", result)
    md = render_recall(result)
    (out_dir / "recall_at_k.md").write_text(md, encoding="utf-8")
    print(md)
    return result


# ── stage 2: the picker at K ──────────────────────────────────────────────────

class WidenedList:
    """Run the mapper with TOP_K=K (and a proportionally wider paper-wording reserve)."""

    def __init__(self, k: int):
        self.k = k

    def __enter__(self):
        from app.agent import assay_obi_mapper as m

        self.primary = round(self.k * m.PRIMARY_SLOTS / m.TOP_K)
        self._saved = (m._top_k_candidates, m._merge_candidates)
        top, merge, k, primary = m._top_k_candidates, m._merge_candidates, self.k, self.primary
        m._top_k_candidates = lambda query, k_=k, **kw: top(query, k=k_, **kw)
        m._merge_candidates = lambda primary_, *others, **kw: merge(primary_, *others, k=k, primary_slots=primary)
        return self

    def __exit__(self, *exc):
        from app.agent import assay_obi_mapper as m

        m._top_k_candidates, m._merge_candidates = self._saved


def run_pick(vocab: str, k: int, dry_run: bool, cache_path: Path = CACHE_PATH, source: Path = STABILITY_DIR,
             picks_dir: Path = PICKS_DIR, force: bool = False) -> None:
    import shutil

    from app.agent import assay_trace
    from app.agent.assay_obi_mapper import enrich_assays_with_obi
    from app.agent.assay_service import obi_calls, obi_summary
    from exp_obi_flat1794 import Unpruned, plan_calls

    paths = VOCABS[vocab]
    dirs = sorted(d for d in source.iterdir() if d.is_dir() and (d / "assays.json").exists())
    out_root = picks_dir / f"{vocab}_k{k}"
    if dry_run:
        chat = 0
        ctx = Unpruned(paths["embeddings"]) if vocab == "full" else None
        if ctx:
            ctx.__enter__()
        try:
            for d in dirs:
                chat += len(plan_calls(_read(d / "assays.json"), paths["index"]))
        finally:
            if ctx:
                ctx.__exit__(None, None, None)
        print(f"{vocab} K={k}: {len(dirs)} registries, ~{chat} chat calls (query embeddings served from cache)")
        print("--dry-run: nothing called")
        return
    cache = _read(cache_path)
    spent = 0
    with CachedQueries(cache), WidenedList(k):
        ctx = Unpruned(paths["embeddings"]) if vocab == "full" else None
        if ctx:
            ctx.__enter__()
        try:
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
                    obi = enrich_assays_with_obi(_read(d / "assays.json"), terms_path=paths["index"])
                finally:
                    assay_trace.stop()
                _write(out_dir / "assays_OBI.json", obi)
                trace.write(out_dir / "raw.json")
                s = obi_summary(obi)
                spent += obi_calls(obi)
                print(f"   {d.name}: {s['mapped']}/{s['total']} mapped {s['resources']}")
                for key in s["unresolved"]:
                    print(f"      {'OBI ERROR' if key in s['errors'] else 'UNMAPPED '}  {key}")
        finally:
            if ctx:
                ctx.__exit__(None, None, None)
    print(f"{vocab} K={k}: ~{spent} calls billed by resource (embeddings were cached)")


def run_pick_score(picks_dir: Path = PICKS_DIR, k20_runs: Path = K20_RUNS, pairing: Path = PAIRING_REPORT) -> None:
    from run_vocab_comparison import curator_terms, diff_arms, score_dir

    curated = curator_terms(_read(pairing))
    pruned_ids = {t["id"] for t in _read(VOCABS["pruned"]["index"])}
    lines = ["# Picker at wider K vs the K=20 run", "", "| run | matched | exact | obi_exact_rate | obi_recall | unresolved |", "|---|---|---|---|---|---|"]
    runs = {}
    for d in sorted(p for p in picks_dir.iterdir() if p.is_dir() and p.name != "comparison"):
        report = score_dir(d, picks_dir / "comparison" / d.name)
        t = report["totals"]
        unresolved = sum(1 for r in d.iterdir() if r.is_dir() for e in _read(r / "assays_OBI.json").values() if not e.get("obi_id"))
        lines.append(f"| {d.name} | {t['matched']} | {t['exact']} | {t['obi_exact_rate']:.1%} | {t['obi_recall']:.1%} | {unresolved} |")
        runs[d.name] = d
    for name, d in runs.items():
        vocab = name.split("_k")[0]
        base = k20_runs / vocab
        if not base.exists():
            continue
        rows = diff_arms("k20", name, {"k20": base, name: d}, curated, pruned_ids)
        counts = Counter(r["agrees_with_curator"] for r in rows)
        lines += ["", f"## {vocab} K=20 vs {name}: {len(rows)} entries changed — {dict(counts)}", "",
                  "| registry | entry | K=20 | " + name + " | curator | agrees |", "|---|---|---|---|---|---|"]
        for r in rows:
            cur = r["curator"] or {}
            lines.append(f"| {r['registry']} | {r['key']} | {r['k20']['obi_id']} {r['k20']['obi_label']} | "
                         f"{r[name]['obi_id']} {r[name]['obi_label']} | {cur.get('obi_id') or '—'} {cur.get('obi_label') or ''} | {r['agrees_with_curator']} |")
    md = "\n".join(lines) + "\n"
    (picks_dir / "summary.md").write_text(md, encoding="utf-8")
    print(md)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("embed-queries"); e.add_argument("--dry-run", action="store_true")
    sub.add_parser("recall")
    p = sub.add_parser("pick")
    p.add_argument("--vocab", choices=list(VOCABS), required=True)
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
        run_pick(args.vocab, args.k, args.dry_run, force=args.force)
    else:
        run_pick_score()


if __name__ == "__main__":
    main()
