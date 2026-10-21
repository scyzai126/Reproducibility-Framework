#!/usr/bin/env python3
"""Pruned (701) vs full (1794) OBI vocabulary as the mapper's candidate pool, over the 31-paper corpus.

The workflow is today's round 4, unchanged: exact match on the paper's own name, else embedding
top-20 (+ neighbours) and an LLM pick. Only the vocabulary differs between the two arms:

    pruned   data/OBI/obi_assay_pruned_{index,embeddings}.json   701 terms, what the pipeline uses
    full     data/OBI/obi_assay_full_{index,embeddings}.json     1794 terms, the whole assay branch

Both arms map the same input: every `assays.json` under data/31paper_assays/stability (157 entries
over 31 papers, already canonicalized). The stored stability mapping of 2026-10-19 is scored as a
third, free column -- it is the pruned vocabulary run on another day, so the difference between it
and the fresh pruned arm is the mapper's own run-to-run variance, the yardstick any arm-to-arm
difference has to clear.

    map    --arm pruned|full|both [--dry-run] [--only SDY] [--force]
           runs/<arm>/<registry>/{assays.json, assays_benchmark.json, assays_OBI.json, raw.json}
           2-3 calls per entry the vocabulary does not match verbatim on a childless term.
           Resumable: a registry with assays_OBI.json already written is skipped unless --force.
    score  comparison/{pruned,full,stability_reference}.{json,html}  (free; the v2 comparator)
    report comparison/{diff.json, summary.md}                        (free)

Nothing under data/ or in the production code is written. The full arm patches the mapper
in-process the way experiment/obi_analyte_terms/exp_obi_flat1794.py does (`Unpruned`).

Usage, from the repo root:
    ./.venv/bin/python experiment/obi_vocab_31papers/run_vocab_comparison.py map --arm both --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (REPO_ROOT / "apps" / "api", REPO_ROOT / "scripts", REPO_ROOT / "experiment" / "obi_analyte_terms"):
    sys.path.insert(0, str(p))

STABILITY_DIR = REPO_ROOT / "data" / "31paper_assays" / "stability"
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_assay" / "benchmark_assay_v4"
OBI_DIR = REPO_ROOT / "data" / "OBI"
RUNS_DIR = HERE / "runs"
COMPARISON_DIR = HERE / "comparison"

ARMS = {
    "pruned": {"index": OBI_DIR / "obi_assay_pruned_index.json",
               "embeddings": OBI_DIR / "obi_assay_pruned_embeddings.json"},
    "full": {"index": OBI_DIR / "obi_assay_full_index.json",
             "embeddings": OBI_DIR / "obi_assay_full_embeddings.json"},
}
REFERENCE = "stability_reference"

_COMPOSITIONAL_RE = re.compile(r"\b(measuring|detecting)\b", re.IGNORECASE)
_MATCHED = {"MATCH", "MATCH_GRANULARITY", "MATCH_OBI_CONFLICT", "MATCH_OBI_UNMAPPED"}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def registries(source: Path = STABILITY_DIR, only: str | None = None) -> list[Path]:
    dirs = sorted(d for d in source.iterdir() if d.is_dir() and (d / "assays.json").exists())
    if only:
        dirs = [d for d in dirs if d.name.upper().endswith(f"_{only.upper()}")]
    return dirs


# ── map ───────────────────────────────────────────────────────────────────────

def plan(arm: str, assays: dict) -> list[tuple[str, int]]:
    """(key, calls) per entry the paid step would see under this arm's vocabulary. No call."""
    from exp_obi_flat1794 import Unpruned, plan_calls

    if arm == "full":
        with Unpruned(ARMS["full"]["embeddings"]):
            return plan_calls(assays, ARMS["full"]["index"])
    return plan_calls(assays, ARMS["pruned"]["index"])


def map_one(arm: str, registry: Path, runs_dir: Path = RUNS_DIR) -> dict:
    """Round 4 over this arm's vocabulary for one registry; writes under runs/<arm>/<name>/."""
    from app.agent import assay_trace
    from app.agent.assay_obi_mapper import enrich_assays_with_obi
    from exp_obi_flat1794 import Unpruned

    out_dir = runs_dir / arm / registry.name
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("assays.json", "assays_benchmark.json"):
        if (registry / name).exists():
            shutil.copyfile(registry / name, out_dir / name)
    assays = _read(registry / "assays.json")
    trace = assay_trace.start()
    try:
        if arm == "full":
            with Unpruned(ARMS["full"]["embeddings"]):
                obi = enrich_assays_with_obi(assays, terms_path=ARMS["full"]["index"])
        else:
            obi = enrich_assays_with_obi(assays, terms_path=ARMS["pruned"]["index"])
    finally:
        assay_trace.stop()
    _write(out_dir / "assays_OBI.json", obi)
    trace.write(out_dir / "raw.json")
    return obi


def run_map(arms: list[str], dry_run: bool, only: str | None = None, force: bool = False,
            source: Path = STABILITY_DIR, runs_dir: Path = RUNS_DIR) -> None:
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
            print(f"   {entries} entries, {paid} reach the paid step, ~{calls} calls")
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
                  f"{obi_calls(obi)} calls, resources {summary['resources']}")
            for key in summary["unresolved"]:
                if key in summary["errors"]:
                    print(f"      OBI ERROR  {key}: {summary['errors'][key]}")
                else:
                    print(f"      UNMAPPED   {key}")
        print(f"   arm {arm} spent ~{spent} calls this run")
    if dry_run:
        print("--dry-run: nothing called")


# ── score ─────────────────────────────────────────────────────────────────────

def score_dir(registry_dir: Path, out_stem: Path, benchmark_dir: Path = BENCHMARK_DIR) -> dict:
    """The v2 comparator's main loop over `registry_dir`, written to `out_stem`.{json,html}."""
    import compare_assay_benchmark_v2 as v2

    obi = v2.ObiGraph()
    pairs, skipped = v2.discover_pairs(None, benchmark_dir, registry_dir)
    papers = []
    for pair in pairs:
        raw, repair, error = v2.load_lenient(pair["benchmark"])
        if raw is None:
            skipped.append(f"{pair['benchmark'].name}: unparseable JSON ({error})")
            continue
        result = v2.compare_paper(v2.prepare_benchmark(raw, obi), pair["registry"], obi)
        papers.append({"study": pair["study"], "pmid": pair["pmid"],
                       "benchmark_file": str(pair["benchmark"]), "registry_dir": str(pair["registry"]),
                       "repair": repair, **result})
    scored = {Path(p["registry_dir"]).name for p in papers}
    totals = {"papers": len(papers), "skipped": skipped,
              "registries_without_benchmark": sorted(d.name for d in registry_dir.iterdir()
                                                     if d.is_dir() and d.name not in scored),
              **v2.overall_totals(papers)}
    report = {"benchmark_dir": str(benchmark_dir), "registry_dir": str(registry_dir),
              "totals": totals, "papers": papers}
    _write(out_stem.with_suffix(".json"), report)
    out_stem.with_suffix(".html").write_text(v2.render_html(report), encoding="utf-8")
    return report


def run_score(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR,
              reference_dir: Path | None = STABILITY_DIR) -> dict[str, dict]:
    reports = {}
    for arm in ARMS:
        if (runs_dir / arm).exists():
            reports[arm] = score_dir(runs_dir / arm, comparison_dir / arm)
    if reference_dir is not None and reference_dir.exists():
        reports[REFERENCE] = score_dir(reference_dir, comparison_dir / REFERENCE)
    for name, report in reports.items():
        t = report["totals"]
        print(f"{name:20} papers {t['papers']:>2}  matched {t['matched']:>3}  exact {t['exact']:>3}  "
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
                out[(reg, row["ours"][0]["key"])] = {"obi_id": row["benchmark"].get("obi_id"),
                                                      "obi_label": row["benchmark"].get("obi_label")}
    return out


def diff_arms(a: str, b: str, runs: dict[str, Path], curated: dict, pruned_ids: set[str]) -> list[dict]:
    """One row per entry where arm `a` and arm `b` chose different terms."""
    rows = []
    for registry in sorted(d for d in runs[a].iterdir() if d.is_dir()):
        other = runs[b] / registry.name
        if not (other / "assays_OBI.json").exists():
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
            rows.append({
                "registry": registry.name, "key": key,
                a: {"obi_id": ea.get("obi_id"), "obi_label": ea.get("obi_label"), "resource": ea.get("resource")},
                b: {"obi_id": eb.get("obi_id"), "obi_label": label_b or None, "resource": eb.get("resource")},
                "curator": cur or None,
                "agrees_with_curator": agrees,
                f"{b}_term_is_compositional": bool(_COMPOSITIONAL_RE.search(label_b)),
                f"{b}_term_outside_pruned_index": bool(eb.get("obi_id")) and eb.get("obi_id") not in pruned_ids,
            })
    return rows


def run_report(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR,
               reference_dir: Path | None = STABILITY_DIR,
               pruned_index: Path = ARMS["pruned"]["index"]) -> dict:
    from app.agent.assay_service import obi_calls

    reports = {name: _read(comparison_dir / f"{name}.json")
               for name in (*ARMS, REFERENCE) if (comparison_dir / f"{name}.json").exists()}
    pruned_ids = {t["id"] for t in _read(pruned_index)}
    runs = {arm: runs_dir / arm for arm in ARMS if (runs_dir / arm).exists()}
    if reference_dir is not None and reference_dir.exists():
        runs[REFERENCE] = reference_dir
    curated = curator_terms(reports["pruned"]) if "pruned" in reports else {}

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
                                           "missed", "extra", "obi_exact_rate", "obi_recall")}
        totals[name].update({"status_counts": t["status_counts"], "unresolved": unresolved,
                             "errors": errors, "calls": calls})

    diffs = {}
    if "pruned" in runs and "full" in runs:
        diffs["pruned_vs_full"] = diff_arms("pruned", "full", runs, curated, pruned_ids)
    if "pruned" in runs and REFERENCE in runs:
        diffs["pruned_vs_stability_reference"] = diff_arms("pruned", REFERENCE, runs, curated, pruned_ids)

    summary = {"totals": totals, "diffs": diffs, "diff_counts": {
        name: dict(Counter(r["agrees_with_curator"] for r in rows)) for name, rows in diffs.items()}}
    if "pruned_vs_full" in diffs:
        rows = diffs["pruned_vs_full"]
        summary["diff_counts"]["pruned_vs_full"].update({
            "changed": len(rows),
            "full_term_compositional": sum(r["full_term_is_compositional"] for r in rows),
            "full_term_outside_pruned_index": sum(r["full_term_outside_pruned_index"] for r in rows),
        })
    _write(comparison_dir / "diff.json", summary)
    (comparison_dir / "summary.md").write_text(render_summary(summary), encoding="utf-8")
    print(render_summary(summary))
    return summary


def render_summary(summary: dict) -> str:
    names = list(summary["totals"])
    lines = ["# Pruned (701) vs full (1794) vocabulary, 31 papers", "",
             "| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    keys = [("papers scored", "papers"), ("curated rows", "benchmark_total"), ("agent entries", "ours_total"),
            ("matched", "matched"), ("exact (same OBI term as curator)", "exact"),
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
    m.add_argument("--arm", choices=["pruned", "full", "both"], default="both")
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
