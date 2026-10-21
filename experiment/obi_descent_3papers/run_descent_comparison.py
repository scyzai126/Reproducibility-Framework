#!/usr/bin/env python3
"""Round 4 by OBI tree descent vs the stored embedding mapping, on the three papers whose
embedding mapping disagreed most with the curator.

Three arms, same input (each paper's canonical `assays.json` under
data/31paper_assays/assay_result_v1):

    embedding   the mapping already on disk there (resource embedding_llm / exact_*): copied,
                free -- this is "what the pipeline produced" and the yardstick
    descend     round 4 re-run with settings.OBI_MAPPING_STRATEGY = "descend", in-process only:
                one chat call per level of the OBI assay tree (apps/api/app/agent/assay_obi_mapper._descend)
    hybrid      the stored embedding pick, then one descent from it when the picked term has
                children in the index (assay_obi_mapper._descend_from_pick) -- the second step of
                OBI_MAPPING_STRATEGY=hybrid applied to the pick already on disk, so only the
                descent is paid for and the picker's run-to-run variance stays out of the comparison

The three papers, by rows where *our* term disagreed with the curator in
data/benchmark_assay/comparison/benchmark_vs_agent.json (a curator row with no OBI id is not
our disagreement): SDY1264 (2), SDY1373 (2), and SDY1260 (1, chosen among the six tied at one
because its error is a parent chosen over the curator's child -- the case the descent is for).

    map    [--arm descend|hybrid|both] [--dry-run] [--only SDY] [--force]
           runs/embedding/<registry>/{assays.json, assays_benchmark.json, assays_OBI.json}   (copied)
           runs/<arm>/<registry>/{assays.json, assays_benchmark.json, assays_OBI.json, raw.json}
           Resumable: a registry whose arm assays_OBI.json exists is skipped unless --force.
    score  comparison/{embedding,descend,hybrid}.{json,html}   (free; scripts/compare_assay_benchmark_v2.py)
    report comparison/{diff.json, summary.md}                   (free)

Nothing under data/, apps/ or .env is written; the strategy is switched on the settings object
for the duration of one registry's mapping and put back.

Usage, from the repo root:
    ./.venv/bin/python experiment/obi_descent_3papers/run_descent_comparison.py map --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (REPO_ROOT / "apps" / "api", REPO_ROOT / "scripts",
          REPO_ROOT / "experiment" / "obi_analyte_terms", REPO_ROOT / "experiment" / "obi_vocab_31papers"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import run_vocab_comparison as vocab  # noqa: E402  (score_dir, curator_terms, diff_arms, _read, _write)

SOURCE_DIR = REPO_ROOT / "data" / "31paper_assays" / "assay_result_v1"
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_assay" / "benchmark_assay_v4"
RUNS_DIR = HERE / "runs"
COMPARISON_DIR = HERE / "comparison"
PAPERS = ("SDY1264", "SDY1373", "SDY1260")
ARMS = ("embedding", "descend", "hybrid")
PAID_ARMS = ("descend", "hybrid")

_read, _write = vocab._read, vocab._write


def registries(source: Path = SOURCE_DIR, only: str | None = None,
               papers: tuple[str, ...] = PAPERS) -> list[Path]:
    """The chosen papers' registry dirs, in PAPERS order; `only` narrows to one study."""
    wanted = [only.upper()] if only else list(papers)
    out = []
    for study in wanted:
        hits = [d for d in source.iterdir()
                if d.is_dir() and d.name.upper().endswith(f"_{study}") and (d / "assays.json").exists()]
        out.extend(sorted(hits))
    return out


# ── map ───────────────────────────────────────────────────────────────────────

def plan(arm: str, assays: dict, stored_obi: dict | None = None) -> list[tuple[str, int]]:
    """(key, chat calls) per entry the arm would pay for. No call.

    descend: the service's estimate (1 from an exact hit, else the typical depth). hybrid: exactly
    one per stored pick whose term has children in the index -- known in advance here, since the
    pick is on disk.
    """
    from app.agent.assay_obi_mapper import _index_children
    from app.agent.assay_service import obi_misses, obi_query_calls

    if arm == "hybrid":
        children = _index_children()
        return [(key, 1) for key, entry in (stored_obi or {}).items()
                if entry.get("obi_id") and children.get(entry["obi_id"])]
    return [(key, obi_query_calls(key, assays[key], strategy="descend")) for key in obi_misses(assays)]


def copy_embedding_arm(registry: Path, runs_dir: Path = RUNS_DIR) -> dict:
    """The stored mapping, as it is, under runs/embedding/<name>/. Free."""
    out_dir = runs_dir / "embedding" / registry.name
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("assays.json", "assays_benchmark.json", "assays_OBI.json"):
        shutil.copyfile(registry / name, out_dir / name)
    return _read(out_dir / "assays_OBI.json")


def map_descend_one(registry: Path, runs_dir: Path = RUNS_DIR) -> dict:
    """Round 4 under the descent for one registry; writes under runs/descend/<name>/.

    The strategy is set on the settings object and restored in `finally`, so a failure
    half-way leaves the process (and any later arm) on the configured default.
    """
    from app.agent import assay_trace
    from app.agent.assay_obi_mapper import enrich_assays_with_obi
    from app.config import settings

    out_dir = runs_dir / "descend" / registry.name
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("assays.json", "assays_benchmark.json"):
        shutil.copyfile(registry / name, out_dir / name)
    assays = _read(registry / "assays.json")
    previous = settings.OBI_MAPPING_STRATEGY
    settings.OBI_MAPPING_STRATEGY = "descend"
    trace = assay_trace.start()
    try:
        obi = enrich_assays_with_obi(assays)
    finally:
        assay_trace.stop()
        settings.OBI_MAPPING_STRATEGY = previous
    _write(out_dir / "assays_OBI.json", obi)
    trace.write(out_dir / "raw.json")
    return obi


def map_hybrid_one(registry: Path, runs_dir: Path = RUNS_DIR) -> dict:
    """The hybrid strategy's second step from the stored embedding pick, for one registry.

    Each stored entry is handed to assay_obi_mapper._descend_from_pick exactly as
    map_assay_to_obi would hand its own pick: the walk runs only when the picked term has
    children in the index, is recorded under the "obi_descend" trace round, and keeps the pick
    when it stops where it started or cannot be read. `obi_calls` counts only the descent here
    (the pick's calls were spent by the original run), so the arm's bill is what this run cost.
    Writes under runs/hybrid/<name>/.
    """
    from app.agent import assay_trace
    from app.agent.assay_obi_mapper import _descend_from_pick
    from app.agent.assay_extractor import paper_names

    out_dir = runs_dir / "hybrid" / registry.name
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("assays.json", "assays_benchmark.json"):
        shutil.copyfile(registry / name, out_dir / name)
    stored = _read(registry / "assays_OBI.json")
    obi: dict = {}
    trace = assay_trace.start()
    try:
        for key, entry in stored.items():
            entry = dict(entry)
            if not entry.get("obi_id"):
                obi[key] = entry
                continue
            names = paper_names(entry)
            raw_aliases = entry.get("aliases")
            aliases = names[1:] + [a for a in (raw_aliases if isinstance(raw_aliases, list) else [])
                                   if isinstance(a, str)]
            technique = str(entry.get("standard_technique_name") or "")
            display = names[0] if names else key
            picked = {"obi_id": entry["obi_id"], "obi_label": entry.get("obi_label"),
                      "resource": entry.get("resource"), "confidence": entry.get("obi_confidence"),
                      "granularity": entry.get("obi_granularity")}
            try:
                walked = _descend_from_pick(
                    picked, display, sample_type=str(entry.get("sample_type") or ""),
                    readouts=str(entry.get("readouts") or ""), aliases=aliases or None,
                    standard_technique_name=technique if technique.lower() != display.lower() else "",
                    registry_key=key, prior_calls=0)
            except Exception as exc:  # noqa: BLE001 - one failed walk must not cost the others
                entry.update({"obi_error": f"{type(exc).__name__}: {exc}", "obi_calls": 1})
                obi[key] = entry
                continue
            entry.update({"obi_id": walked["obi_id"], "obi_label": walked["obi_label"],
                          "resource": walked["resource"], "obi_confidence": walked.get("confidence"),
                          "obi_granularity": walked.get("granularity"), "obi_path": walked["path"],
                          "obi_calls": walked["calls"], "obi_backoff": walked["backoff"]})
            if walked.get("descend_error"):
                entry["obi_error"] = walked["descend_error"]
            obi[key] = entry
    finally:
        assay_trace.stop()
    _write(out_dir / "assays_OBI.json", obi)
    trace.write(out_dir / "raw.json")
    return obi


_MAPPERS = {"descend": map_descend_one, "hybrid": map_hybrid_one}


def run_map(dry_run: bool, only: str | None = None, force: bool = False,
            source: Path = SOURCE_DIR, runs_dir: Path = RUNS_DIR,
            arms: tuple[str, ...] = PAID_ARMS) -> None:
    from app.agent.assay_service import obi_summary

    dirs = registries(source, only)
    print(f"== {len(dirs)} registries from {source.relative_to(REPO_ROOT) if source.is_relative_to(REPO_ROOT) else source}")
    for arm in arms:
        print(f"== arm {arm}")
        if dry_run:
            total = 0
            for registry in dirs:
                assays = _read(registry / "assays.json")
                stored = _read(registry / "assays_OBI.json")
                planned = plan(arm, assays, stored)
                calls = sum(c for _, c in planned)
                total += calls
                note = "1-5 each by depth" if arm == "descend" else "one per stored pick with children"
                print(f"   {registry.name}: {len(assays)} entries, {len(planned)} reach the paid step, "
                      f"~{calls} calls ({note})")
                for key, c in planned:
                    print(f"      {c}  {key}")
            print(f"   ~{total} chat calls for the {arm} arm; the embedding arm is the stored mapping and costs nothing")
            continue
        spent = 0
        for registry in dirs:
            copy_embedding_arm(registry, runs_dir)
            done = runs_dir / arm / registry.name / "assays_OBI.json"
            if done.exists() and not force:
                print(f"   skip {registry.name}: already mapped by {arm} (--force to redo)")
                continue
            obi = _MAPPERS[arm](registry, runs_dir)
            summary = obi_summary(obi)
            calls = sum(e.get("obi_calls") or 0 for e in obi.values())
            spent += calls
            print(f"   {registry.name}: {summary['mapped']}/{summary['total']} mapped, "
                  f"{calls} calls, resources {summary['resources']}")
            for key, entry in obi.items():
                if entry.get("obi_backoff"):
                    print(f"      BACKOFF    {key}: ended on {entry.get('obi_id')} {entry.get('obi_label')} "
                          f"after {entry.get('obi_calls')} call(s), path {entry.get('obi_path')}")
                if entry.get("obi_error") and entry.get("obi_id"):
                    print(f"      WALK ERROR {key}: {entry['obi_error']} (the stored pick stands)")
            for key in summary["unresolved"]:
                if key in summary["errors"]:
                    print(f"      OBI ERROR  {key}: {summary['errors'][key]}")
                else:
                    print(f"      UNMAPPED   {key}")
        print(f"   {arm} arm spent ~{spent} calls this run")
    if dry_run:
        print("--dry-run: nothing called")


# ── score ─────────────────────────────────────────────────────────────────────

def run_score(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR,
              benchmark_dir: Path = BENCHMARK_DIR) -> dict[str, dict]:
    reports = {}
    for arm in ARMS:
        if (runs_dir / arm).exists():
            reports[arm] = vocab.score_dir(runs_dir / arm, comparison_dir / arm, benchmark_dir)
    for name, report in reports.items():
        t = report["totals"]
        print(f"{name:10} papers {t['papers']:>2}  matched {t['matched']:>3}  exact {t['exact']:>3}  "
              f"obi_exact_rate {t['obi_exact_rate']:.1%}  obi_recall {t['obi_recall']:.1%}  "
              f"{t['status_counts']}")
        for s in t["skipped"]:
            print(f"   SKIPPED {s}")
    return reports


# ── report ────────────────────────────────────────────────────────────────────

def _walk_levels(raw: dict, key: str, round_: str = "obi") -> list[dict]:
    """The walk's per-level record for one entry, from raw.json: [{node, reply, n_candidates}].
    The root walk records under "obi"; the hybrid's descent under "obi_descend"."""
    record = (raw.get(round_) or {}).get(key) or {}
    return [{"node": lvl.get("node"), "reply": lvl.get("reply"),
             "n_candidates": len(lvl.get("candidates") or [])} for lvl in record.get("levels") or []]


def _row_status(report: dict, registry: str, key: str) -> str | None:
    """The scorer's status for our entry `key` in `registry`, or None if it paired nothing."""
    for paper in report.get("papers", []):
        if Path(paper["registry_dir"]).name != registry:
            continue
        for row in paper["rows"]:
            if any(o.get("key") == key for o in row.get("ours") or []):
                return row["status"]
    return None


def run_report(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR,
               pruned_index: Path = REPO_ROOT / "data" / "OBI" / "obi_assay_pruned_index.json") -> dict:
    from app.agent.assay_service import obi_calls

    reports = {arm: _read(comparison_dir / f"{arm}.json")
               for arm in ARMS if (comparison_dir / f"{arm}.json").exists()}
    runs = {arm: runs_dir / arm for arm in ARMS if (runs_dir / arm).exists()}
    pruned_ids = {t["id"] for t in _read(pruned_index)}
    curated = vocab.curator_terms(reports["embedding"]) if "embedding" in reports else {}

    totals = {}
    for arm, report in reports.items():
        t = report["totals"]
        calls = unresolved = errors = backoffs = 0
        for d in sorted(p for p in runs[arm].iterdir() if p.is_dir()):
            obi = _read(d / "assays_OBI.json")
            calls += obi_calls(obi)
            unresolved += sum(1 for e in obi.values() if not e.get("obi_id"))
            errors += sum(1 for e in obi.values() if e.get("resource") == "error")
            backoffs += sum(1 for e in obi.values() if e.get("obi_backoff"))
        totals[arm] = {k: t[k] for k in ("papers", "benchmark_total", "ours_total", "matched", "exact",
                                          "missed", "extra", "obi_exact_rate", "obi_recall")}
        totals[arm].update({"status_counts": t["status_counts"], "unresolved": unresolved,
                            "errors": errors, "backoffs": backoffs, "calls": calls})

    changed: dict[str, list[dict]] = {}
    for arm in PAID_ARMS:
        if "embedding" not in runs or arm not in runs:
            continue
        rows = []
        for row in vocab.diff_arms("embedding", arm, runs, curated, pruned_ids):
            reg, key = row["registry"], row["key"]
            entry = _read(runs[arm] / reg / "assays_OBI.json").get(key) or {}
            raw_path = runs[arm] / reg / "raw.json"
            raw = _read(raw_path) if raw_path.exists() else {}
            row[arm].update({"obi_path": entry.get("obi_path"), "obi_calls": entry.get("obi_calls"),
                             "obi_backoff": entry.get("obi_backoff"),
                             "obi_granularity": entry.get("obi_granularity"),
                             "levels": _walk_levels(raw, key, "obi" if arm == "descend" else "obi_descend")})
            row["status"] = {a: _row_status(reports.get(a, {}), reg, key) for a in ARMS}
            rows.append(row)
        changed[arm] = rows

    # Every entry's status under each arm, so the rows that were wrong before can be found
    # whether or not a walk changed them.
    per_entry = []
    if "embedding" in runs:
        for reg in sorted(d.name for d in runs["embedding"].iterdir() if d.is_dir()):
            obi_e = _read(runs["embedding"] / reg / "assays_OBI.json")
            others = {arm: (_read(runs[arm] / reg / "assays_OBI.json")
                            if arm in runs and (runs[arm] / reg / "assays_OBI.json").exists() else {})
                      for arm in PAID_ARMS}
            for key in obi_e:
                cur = curated.get((reg, key)) or {}
                row = {"registry": reg, "key": key, "curator": cur or None,
                       "embedding": {"obi_id": obi_e[key].get("obi_id"),
                                     "status": _row_status(reports.get("embedding", {}), reg, key)}}
                for arm in PAID_ARMS:
                    e = others[arm].get(key) or {}
                    row[arm] = {"obi_id": e.get("obi_id"), "status": _row_status(reports.get(arm, {}), reg, key),
                                "obi_calls": e.get("obi_calls")}
                per_entry.append(row)

    summary = {"totals": totals, "changed": changed, "per_entry": per_entry,
               "changed_counts": {arm: dict(Counter(r["agrees_with_curator"] for r in rows))
                                  for arm, rows in changed.items()}}
    _write(comparison_dir / "diff.json", summary)
    (comparison_dir / "summary.md").write_text(render_summary(summary), encoding="utf-8")
    print(render_summary(summary))
    return summary


def render_summary(summary: dict) -> str:
    names = list(summary["totals"])
    lines = ["# OBI tree descent vs stored embedding mapping, three papers", "",
             "| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    keys = [("papers scored", "papers"), ("curated rows", "benchmark_total"), ("agent entries", "ours_total"),
            ("matched", "matched"), ("exact (same OBI term as curator)", "exact"),
            ("obi_exact_rate", "obi_exact_rate"), ("obi_recall", "obi_recall"),
            ("unresolved (no term)", "unresolved"), ("lookup errors", "errors"),
            ("walks that backed off", "backoffs"), ("calls spent", "calls")]
    for label, key in keys:
        vals = []
        for n in names:
            v = summary["totals"][n].get(key)
            vals.append(f"{v:.1%}" if isinstance(v, float) else str(v))
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    for status in ("MATCH", "MATCH_GRANULARITY", "MATCH_OBI_CONFLICT", "MATCH_OBI_UNMAPPED", "MISSED", "EXTRA"):
        lines.append(f"| {status} | " + " | ".join(
            str(summary["totals"][n]["status_counts"].get(status, 0)) for n in names) + " |")

    for arm, rows in summary["changed"].items():
        lines += ["", f"## embedding vs {arm}: entries that chose different terms ({len(rows)})", "",
                  f"counts: {summary['changed_counts'][arm]}", "",
                  f"| registry | entry | embedding | {arm} | curator | agrees | path (calls) | replies |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            cur = r["curator"] or {}
            d = r[arm]
            path = " → ".join(d.get("obi_path") or []) or "—"
            replies = "; ".join(f"{lvl['node']}:{lvl['reply']}" for lvl in d.get("levels") or [])
            backoff = " BACKOFF" if d.get("obi_backoff") else ""
            lines.append(f"| {r['registry']} | {r['key']} | {r['embedding']['obi_id']} {r['embedding']['obi_label']} | "
                         f"{d['obi_id']} {d['obi_label']}{backoff} | {cur.get('obi_id') or '—'} {cur.get('obi_label') or ''} | "
                         f"{r['agrees_with_curator']} | {path} ({d.get('obi_calls')}) | {replies} |")

    arms = [a for a in PAID_ARMS if any(a in r for r in summary["per_entry"])]
    rows = [r for r in summary["per_entry"] if r["embedding"]["status"] not in (None, "MATCH")]
    lines += ["", f"## Rows the embedding mapping got wrong, under each arm ({len(rows)})", "",
              "| registry | entry | curator | embedding | " + " | ".join(arms) + " |",
              "|---|---|---|---|" + "---|" * len(arms)]
    for r in rows:
        cur = r["curator"] or {}
        cells = [f"{r[a]['obi_id']} ({r[a]['status']}, {r[a]['obi_calls']} calls)" for a in arms]
        lines.append(f"| {r['registry']} | {r['key']} | {cur.get('obi_id') or '—'} | "
                     f"{r['embedding']['obi_id']} ({r['embedding']['status']}) | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("map")
    m.add_argument("--arm", choices=[*PAID_ARMS, "both"], default="both")
    m.add_argument("--dry-run", action="store_true")
    m.add_argument("--only", help="one study accession, e.g. SDY1264")
    m.add_argument("--force", action="store_true", help="re-map a registry the descent already mapped")
    sub.add_parser("score")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "map":
        run_map(args.dry_run, args.only, args.force,
                arms=PAID_ARMS if args.arm == "both" else (args.arm,))
    elif args.command == "score":
        run_score()
    else:
        run_report()


if __name__ == "__main__":
    main()
