#!/usr/bin/env python3
"""Pruned (701) vs full (1794) OBI vocabulary as the mapper's candidate pool, on assay_result_v3.

Round 4 as it runs today -- exact match on the paper's own name, else embedding top-20 and one
LLM pick -- with only the vocabulary swapped between arms:

    pruned            data/OBI/obi_assay_pruned_{index,embeddings}.json             701, the live pool
    full              data/OBI/obi_assay_full_{index,embeddings}.json              1794, the assay branch
    noncompositional  data/OBI/obi_assay_noncompositional_{index,embeddings}.json  1249, defined, not run by default

Every arm maps the same input, the canonical `assays.json` of each registry under
data/31paper_assays/assay_result_v3 (31 papers, 177 entries), so keys stay those of
`assays_benchmark.json` and the v2 comparator can score each arm as it scores the corpus. No
BROAD re-pick and no round-5 fold: the difference between arms is the candidate pool and nothing
else. The stored v3 mapping (same pruned vocabulary, run on 2026-10-2x) is the free reference
column; the gap between it and the fresh pruned arm is the picker's own run-to-run variance.

The mapper has no vocabulary switch, so an arm is applied in-process by `Vocabulary`: it patches
the two module path constants (and, for the full arm, the load-time compositional filter, which
would otherwise cut 1794 back to 1249), clears the memoised vocabulary, and puts everything back
on exit. Production code is never edited and nothing under data/ is written.

    map     --arm pruned|full|noncompositional|both [--dry-run] [--only SDY] [--force]
            runs/<arm>/<registry>/{assays.json, assays_benchmark.json, assays_OBI.json, raw.json}
            resumable: a registry whose assays_OBI.json exists is skipped unless --force
    score   comparison/<arm>.{json,html} via scripts/compare_assay_benchmark_v2.py (free)
    report  comparison/{diff.json, summary.md} (free)

Usage, from the repo root:
    ./.venv/bin/python experiment/obi_vocab_v3/run_vocab_comparison.py map --arm both --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (REPO_ROOT / "apps" / "api", REPO_ROOT / "scripts"):
    sys.path.insert(0, str(p))

SOURCE_DIR = REPO_ROOT / "data" / "31paper_assays" / "assay_result_v3"
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_assay" / "benchmark_assay_v5"
REFERENCE_REPORT = SOURCE_DIR / "comparison" / "benchmark_v5_vs_agent.json"
OBI_DIR = REPO_ROOT / "data" / "OBI"
RUNS_DIR = HERE / "runs"
COMPARISON_DIR = HERE / "comparison"
COMPARATOR = REPO_ROOT / "scripts" / "compare_assay_benchmark_v2.py"

ARMS = {
    "pruned": {"index": OBI_DIR / "obi_assay_pruned_index.json",
               "embeddings": OBI_DIR / "obi_assay_pruned_embeddings.json", "unfiltered": False},
    "full": {"index": OBI_DIR / "obi_assay_full_index.json",
             "embeddings": OBI_DIR / "obi_assay_full_embeddings.json", "unfiltered": True},
    "noncompositional": {"index": OBI_DIR / "obi_assay_noncompositional_index.json",
                         "embeddings": OBI_DIR / "obi_assay_noncompositional_embeddings.json",
                         "unfiltered": False},
}
REFERENCE = "v3_reference"

_COMPOSITIONAL_RE = re.compile(r"\b(measuring|detecting)\b", re.IGNORECASE)
_MATCHED = {"MATCH", "MATCH_GRANULARITY", "MATCH_OBI_CONFLICT", "MATCH_OBI_UNMAPPED"}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def registries(source: Path = SOURCE_DIR, only: str | None = None) -> list[Path]:
    dirs = sorted(d for d in source.iterdir() if d.is_dir() and (d / "assays.json").exists())
    if only:
        dirs = [d for d in dirs if re.search(rf"_{re.escape(only)}(_pdf)?$", d.name, re.IGNORECASE)]
    return dirs


# ── the in-process vocabulary switch ──────────────────────────────────────────

class Vocabulary:
    """Point the mapper at one arm's index and vectors for the duration of a `with` block.

    `_OBI_TERMS_PATH` and `_EMBEDDINGS_PATH` are module constants the mapper reads at call time;
    `_is_generic_assay_term` is the load-time filter that drops compositional labels from any
    file it loads. An `unfiltered` arm replaces it with a function that accepts everything, so
    the full 1794 reach the pool. Every lru_cache that memoised the previous vocabulary is
    cleared on entry and again on exit, and the three attributes are restored.
    """

    _CACHED = ("_load_embeddings", "_term_details", "_build_lookup", "_term_ids",
               "_index_children", "_index_entries")

    def __init__(self, arm: str) -> None:
        self.arm = ARMS[arm]

    @staticmethod
    def _clear_caches() -> None:
        from app.agent import assay_obi_mapper as mapper

        for name in Vocabulary._CACHED:
            fn = getattr(mapper, name, None)
            if fn is not None and hasattr(fn, "cache_clear"):
                fn.cache_clear()

    def __enter__(self) -> "Vocabulary":
        from app.agent import assay_obi_mapper as mapper

        self._saved = (mapper._OBI_TERMS_PATH, mapper._EMBEDDINGS_PATH, mapper._is_generic_assay_term)
        mapper._OBI_TERMS_PATH = self.arm["index"]
        mapper._EMBEDDINGS_PATH = self.arm["embeddings"]
        if self.arm["unfiltered"]:
            mapper._is_generic_assay_term = lambda obi_id, label: True
        self._clear_caches()
        return self

    def __exit__(self, *exc: object) -> None:
        from app.agent import assay_obi_mapper as mapper

        mapper._OBI_TERMS_PATH, mapper._EMBEDDINGS_PATH, mapper._is_generic_assay_term = self._saved
        self._clear_caches()


# ── map ───────────────────────────────────────────────────────────────────────

def plan(arm: str, assays: dict) -> list[tuple[str, int]]:
    """(key, calls) per entry the paid step would see under this arm's vocabulary. No call.

    Mirrors map_assay_to_obi step 1: an exact hit on the paper's first wording is free only when
    the term has no child in the index; anything else pays obi_query_calls (2, or 3 with a
    differing standard_technique_name).
    """
    from app.agent import assay_obi_mapper as mapper
    from app.agent.assay_service import _obi_query, obi_query_calls

    with Vocabulary(arm):
        lookup = mapper._build_lookup(ARMS[arm]["index"])
        children = mapper._index_children(ARMS[arm]["index"])
        planned = []
        for key, entry in assays.items():
            original, _ = _obi_query(key, entry)
            hit = lookup.get(original.lower()) if original else None
            if hit and not children.get(hit["obi_id"]):
                continue
            planned.append((key, obi_query_calls(key, entry)))
    return planned


def map_one(arm: str, registry: Path, runs_dir: Path = RUNS_DIR) -> dict:
    """Round 4 over this arm's vocabulary for one registry; writes under runs/<arm>/<name>/."""
    from app.agent import assay_trace
    from app.agent.assay_obi_mapper import enrich_assays_with_obi

    out_dir = runs_dir / arm / registry.name
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("assays.json", "assays_benchmark.json"):
        if (registry / name).exists():
            shutil.copyfile(registry / name, out_dir / name)
    assays = _read(registry / "assays.json")
    trace = assay_trace.start()
    try:
        with Vocabulary(arm):
            obi = enrich_assays_with_obi(assays, terms_path=ARMS[arm]["index"])
    finally:
        assay_trace.stop()
    _write(out_dir / "assays_OBI.json", obi)
    trace.write(out_dir / "raw.json")
    return obi


def run_map(arms: list[str], dry_run: bool, only: str | None = None, force: bool = False,
            source: Path = SOURCE_DIR, runs_dir: Path = RUNS_DIR) -> None:
    from app.agent.assay_service import obi_calls, obi_summary

    for arm in arms:
        dirs = registries(source, only)
        print(f"== arm {arm}: {len(dirs)} registries, index {ARMS[arm]['index'].name}")
        if dry_run:
            entries = paid = calls = 0
            for registry in dirs:
                assays = _read(registry / "assays.json")
                planned = plan(arm, assays)
                entries += len(assays)
                paid += len(planned)
                calls += sum(c for _, c in planned)
            print(f"   {entries} entries, {paid} reach the paid step, ~{calls} calls "
                  f"({paid} chat picks + {calls - paid} query embeddings, shared across arms)")
            continue
        spent = 0
        for registry in dirs:
            done = runs_dir / arm / registry.name / "assays_OBI.json"
            if done.exists() and not force:
                print(f"   skip {registry.name}: already mapped (--force to redo)")
                continue
            obi = map_one(arm, registry, runs_dir)
            summary = obi_summary(obi)
            spent += obi_calls(obi)
            print(f"   {registry.name}: {summary['mapped']}/{summary['total']} mapped, "
                  f"{obi_calls(obi)} calls, resources {summary['resources']}", flush=True)
            for key in summary["unresolved"]:
                if key in summary["errors"]:
                    print(f"      OBI ERROR  {key}: {summary['errors'][key]}")
                else:
                    print(f"      UNMAPPED   {key}")
        print(f"   arm {arm} spent ~{spent} calls this run")
    if dry_run:
        print("--dry-run: nothing called")


# ── score ─────────────────────────────────────────────────────────────────────

def score_arm(arm: str, runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR,
              benchmark_dir: Path = BENCHMARK_DIR) -> dict:
    """The v2 comparator over runs/<arm>, its report copied to comparison/<arm>.{json,html}."""
    registry_dir = runs_dir / arm
    subprocess.run([sys.executable, str(COMPARATOR), "--registry-dir", str(registry_dir),
                    "--benchmark-dir", str(benchmark_dir), "--out-stem", arm],
                   check=True, cwd=REPO_ROOT)
    comparison_dir.mkdir(parents=True, exist_ok=True)
    for suffix in (".json", ".html"):
        shutil.copyfile(registry_dir / "comparison" / f"{arm}{suffix}", comparison_dir / f"{arm}{suffix}")
    return _read(comparison_dir / f"{arm}.json")


def run_score(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR,
              reference_report: Path | None = REFERENCE_REPORT) -> dict[str, dict]:
    reports = {}
    for arm in ARMS:
        if (runs_dir / arm).exists():
            reports[arm] = score_arm(arm, runs_dir, comparison_dir)
    if reference_report is not None and reference_report.exists():
        shutil.copyfile(reference_report, comparison_dir / f"{REFERENCE}.json")
        reports[REFERENCE] = _read(reference_report)
    for name, report in reports.items():
        t = report["totals"]
        print(f"{name:18} papers {t['papers']:>2}  matched {t['matched']:>3}  exact {t['exact']:>3}  "
              f"obi_exact_rate {t['obi_exact_rate']:.1%}  obi_recall {t['obi_recall']:.1%}  "
              f"{t['status_counts']}")
        for s in t["skipped"]:
            print(f"   SKIPPED {s}")
    return reports


# ── report ────────────────────────────────────────────────────────────────────

def curator_terms(report: dict) -> dict[tuple[str, str], dict]:
    """{(registry name, our key): {obi_id, obi_label}} for every agent entry the scorer paired."""
    out = {}
    for paper in report["papers"]:
        reg = Path(paper["registry_dir"]).name
        for row in paper["rows"]:
            if row["status"] in _MATCHED and row.get("benchmark") and row.get("ours"):
                for ours in row["ours"]:
                    out[(reg, ours["key"])] = {"obi_id": row["benchmark"].get("obi_id"),
                                               "obi_label": row["benchmark"].get("obi_label")}
    return out


def row_statuses(report: dict) -> dict[tuple[str, str], str]:
    """{(registry name, our key): scorer status} for every agent entry in a report."""
    out = {}
    for paper in report["papers"]:
        reg = Path(paper["registry_dir"]).name
        for row in paper["rows"]:
            for ours in row.get("ours") or []:
                out[(reg, ours["key"])] = row["status"]
    return out


def diff_arms(a: str, b: str, runs: dict[str, Path], curated: dict, pruned_ids: set[str],
              noncomp_ids: set[str] | None = None,
              statuses: dict[str, dict[tuple[str, str], str]] | None = None) -> list[dict]:
    """One row per entry where arm `a` and arm `b` chose different terms."""
    rows = []
    for registry in sorted(d for d in runs[a].iterdir() if d.is_dir()):
        other = runs[b] / registry.name
        if not (registry / "assays_OBI.json").exists() or not (other / "assays_OBI.json").exists():
            continue
        obi_a, obi_b = _read(registry / "assays_OBI.json"), _read(other / "assays_OBI.json")
        for key in obi_a:
            ea, eb = obi_a.get(key) or {}, obi_b.get(key) or {}
            if ea.get("obi_id") == eb.get("obi_id"):
                continue
            cur = curated.get((registry.name, key)) or {}
            cur_id = cur.get("obi_id")
            agrees = ("both" if cur_id and ea.get("obi_id") == cur_id == eb.get("obi_id") else
                      a if cur_id and ea.get("obi_id") == cur_id else
                      b if cur_id and eb.get("obi_id") == cur_id else
                      "neither" if cur_id else "no curated term")
            label_b = eb.get("obi_label") or ""
            row = {
                "registry": registry.name, "key": key,
                a: {"obi_id": ea.get("obi_id"), "obi_label": ea.get("obi_label"), "resource": ea.get("resource"),
                    "granularity": ea.get("obi_granularity")},
                b: {"obi_id": eb.get("obi_id"), "obi_label": label_b or None, "resource": eb.get("resource"),
                    "granularity": eb.get("obi_granularity")},
                "curator": cur or None,
                "agrees_with_curator": agrees,
                f"{b}_term_is_compositional": bool(_COMPOSITIONAL_RE.search(label_b)),
                f"{b}_term_outside_pruned_index": bool(eb.get("obi_id")) and eb.get("obi_id") not in pruned_ids,
            }
            if noncomp_ids is not None:
                row[f"{b}_term_outside_noncompositional_index"] = (
                    bool(eb.get("obi_id")) and eb.get("obi_id") not in noncomp_ids)
            if statuses:
                row["status"] = {arm: statuses.get(arm, {}).get((registry.name, key)) for arm in (a, b)}
            rows.append(row)
    return rows


def run_report(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR,
               source: Path = SOURCE_DIR) -> dict:
    from app.agent.assay_service import obi_calls

    reports = {name: _read(comparison_dir / f"{name}.json")
               for name in (*ARMS, REFERENCE) if (comparison_dir / f"{name}.json").exists()}
    pruned_ids = {t["id"] for t in _read(ARMS["pruned"]["index"])}
    noncomp_path = ARMS["noncompositional"]["index"]
    noncomp_ids = {t["id"] for t in _read(noncomp_path)} if noncomp_path.exists() else None
    runs = {arm: runs_dir / arm for arm in ARMS if (runs_dir / arm).exists()}
    if REFERENCE in reports:
        runs[REFERENCE] = source
    curated = curator_terms(reports["pruned"]) if "pruned" in reports else {}
    statuses = {name: row_statuses(r) for name, r in reports.items()}

    def spent(path: Path) -> tuple[int, int, int]:
        calls = unresolved = errors = 0
        for d in sorted(p for p in path.iterdir() if p.is_dir()):
            f = d / "assays_OBI.json"
            if f.exists():
                obi = _read(f)
                calls += obi_calls(obi)
                unresolved += sum(1 for e in obi.values() if not e.get("obi_id"))
                errors += sum(1 for e in obi.values() if e.get("resource") == "error")
        return calls, unresolved, errors

    totals = {}
    for name, report in reports.items():
        t = report["totals"]
        calls, unresolved, errors = spent(runs[name])
        totals[name] = {k: t[k] for k in ("papers", "benchmark_total", "ours_total", "matched", "exact",
                                           "obi_ok", "missed", "extra", "obi_exact_rate", "obi_recall")}
        totals[name].update({"status_counts": t["status_counts"], "unresolved": unresolved,
                             "errors": errors, "calls": calls})

    diffs = {}
    for other in ("full", "noncompositional", REFERENCE):
        if "pruned" in runs and other in runs:
            diffs[f"pruned_vs_{other}"] = diff_arms("pruned", other, runs, curated, pruned_ids,
                                                    noncomp_ids, statuses)

    summary = {"totals": totals, "diffs": diffs, "diff_counts": {
        name: dict(Counter(r["agrees_with_curator"] for r in rows)) for name, rows in diffs.items()}}
    for name, rows in diffs.items():
        other = name.split("_vs_")[1]
        summary["diff_counts"][name].update({
            "changed": len(rows),
            f"{other}_term_compositional": sum(r[f"{other}_term_is_compositional"] for r in rows),
            f"{other}_term_outside_pruned_index": sum(r[f"{other}_term_outside_pruned_index"] for r in rows),
        })
    _write(comparison_dir / "diff.json", summary)
    (comparison_dir / "summary.md").write_text(render_summary(summary), encoding="utf-8")
    print(render_summary(summary))
    return summary


def render_summary(summary: dict) -> str:
    names = list(summary["totals"])
    lines = ["# Pruned (701) vs full (1794) vocabulary, assay_result_v3 against benchmark v5", "",
             "| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    keys = [("papers scored", "papers"), ("curated rows", "benchmark_total"), ("agent entries", "ours_total"),
            ("matched", "matched"), ("exact (same OBI term as curator)", "exact"),
            ("OBI ok (same or parent/child)", "obi_ok"),
            ("obi_exact_rate", "obi_exact_rate"), ("obi_recall", "obi_recall"),
            ("unresolved (no term)", "unresolved"), ("lookup errors", "errors"), ("calls spent", "calls")]
    for label, key in keys:
        vals = []
        for n in names:
            v = summary["totals"][n][key]
            vals.append(f"{v:.1%}" if isinstance(v, float) else str(v))
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    for status in ("MATCH", "MATCH_GRANULARITY", "MATCH_OBI_CONFLICT", "MATCH_OBI_UNMAPPED", "MISSED", "EXTRA"):
        lines.append(f"| {status} | " + " | ".join(
            str(summary["totals"][n]["status_counts"].get(status, 0)) for n in names) + " |")
    for name, rows in summary["diffs"].items():
        a, b = name.split("_vs_")
        lines += ["", f"## {a} vs {b}: entries that chose different terms ({len(rows)})", "",
                  f"counts: {summary['diff_counts'][name]}", "",
                  f"| registry | entry | {a} | {b} | curator | agrees |", "|---|---|---|---|---|---|"]
        for r in rows:
            cur = r["curator"] or {}
            flag = " (compositional)" if r.get(f"{b}_term_is_compositional") else (
                " (outside 701)" if r.get(f"{b}_term_outside_pruned_index") else "")
            lines.append(f"| {r['registry']} | {r['key']} | {r[a]['obi_id']} {r[a]['obi_label']} | "
                         f"{r[b]['obi_id']} {r[b]['obi_label']}{flag} | "
                         f"{cur.get('obi_id') or '—'} {cur.get('obi_label') or ''} | {r['agrees_with_curator']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("map")
    m.add_argument("--arm", choices=[*ARMS, "both"], default="both")
    m.add_argument("--dry-run", action="store_true")
    m.add_argument("--only", help="one study accession, e.g. SDY2189")
    m.add_argument("--force", action="store_true", help="re-map registries already mapped")
    sub.add_parser("score")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "map":
        arms = ["pruned", "full"] if args.arm == "both" else [args.arm]
        run_map(arms, args.dry_run, args.only, args.force)
    elif args.command == "score":
        run_score()
    else:
        run_report()


if __name__ == "__main__":
    main()
