#!/usr/bin/env python3
"""Full-list LLM vs embedding retrieval for round 4 (map to OBI), on the 10 worst papers.

Round 4 today retrieves 20 candidates from the pruned 701-term vocabulary by embedding and asks
one LLM call to pick among them. This arm drops retrieval: every assay that reaches the paid
step gets one call that sees all 701 terms, rendered as the picker renders a candidate
(label | <=4 synonyms | definition <=300 chars | descendants). Everything else is held fixed --
the input (`assays.json` of each assay_result_v3 registry), the free exact-name step, the exact
hit pinned with its children and kept as the floor on "none", the selection rules, the model,
the scorer. No BROAD re-pick and no round-5 fold, as in experiment/obi_vocab_v3.

The baseline is free: the same 10 registries mapped by embedding in experiment/obi_vocab_v3
(arm `pruned`, same input, same vocabulary, same day) and, as a second embedding column that
shows run-to-run variance, the stored v3 mapping.

    select  papers.json: the 10 registries with most non-exact matched rows in obi_vocab_v3's
            pruned report (ties: same count in the v3 reference, then entry count). Free.
    map     [--dry-run] [--only SDY] [--force]
            runs/fulllist/<registry>/{assays.json, assays_benchmark.json, assays_OBI.json,
            raw.json, usage.json}; resumable, a mapped registry is skipped unless --force
    score   comparison/{fulllist,embedding,v3_reference}.{json,html} via
            scripts/compare_assay_benchmark_v2.py (free)
    report  comparison/{diff.json, summary.md} (free)

The mapper has no switch for this, so the arm is applied in-process by `FullList`, which swaps
`assay_obi_mapper._embedding_llm_match` for `fulllist_match` and puts it back on exit.
Production code is never edited and nothing under data/ is written.

Usage, from the repo root:
    ./.venv/bin/python experiment/obi_llm_fulllist/run_fulllist.py map --dry-run
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
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (REPO_ROOT / "apps" / "api", REPO_ROOT / "scripts"):
    sys.path.insert(0, str(p))

SOURCE_DIR = REPO_ROOT / "data" / "31paper_assays" / "assay_result_v3"
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_assay" / "benchmark_assay_v5"
INDEX_PATH = REPO_ROOT / "data" / "OBI" / "obi_assay_pruned_index.json"
VOCAB_V3 = REPO_ROOT / "experiment" / "obi_vocab_v3"
EMBEDDING_RUNS = VOCAB_V3 / "runs" / "pruned"
EMBEDDING_REPORT = VOCAB_V3 / "comparison" / "pruned.json"
REFERENCE_REPORT = VOCAB_V3 / "comparison" / "v3_reference.json"
PROMPT_PATH = HERE / "prompt.txt"
PAPERS_PATH = HERE / "papers.json"
RUNS_DIR = HERE / "runs"
COMPARISON_DIR = HERE / "comparison"
COMPARATOR = REPO_ROOT / "scripts" / "compare_assay_benchmark_v2.py"

ARM = "fulllist"
EMBEDDING = "embedding"
REFERENCE = "v3_reference"
N_PAPERS = 10
_NON_EXACT = ("MATCH_GRANULARITY", "MATCH_OBI_CONFLICT", "MATCH_OBI_UNMAPPED")
_MATCHED = {"MATCH", *_NON_EXACT}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ── select ────────────────────────────────────────────────────────────────────

def _non_exact_by_registry(report: dict) -> dict[str, int]:
    return {Path(p["registry_dir"]).name: sum(1 for r in p["rows"] if r["status"] in _NON_EXACT)
            for p in report["papers"]}


def select_papers(report: dict, reference: dict | None = None, source: Path = SOURCE_DIR,
                  n: int = N_PAPERS) -> list[dict]:
    """The `n` registries the embedding arm got most wrong, worst first."""
    ours = _non_exact_by_registry(report)
    ref = _non_exact_by_registry(reference) if reference else {}

    def entries(name: str) -> int:
        f = source / name / "assays.json"
        return len(_read(f)) if f.exists() else 0

    ranked = sorted(ours, key=lambda name: (-ours[name], -ref.get(name, 0), -entries(name), name))
    return [{"registry": name, "non_exact_embedding": ours[name], "non_exact_v3_reference": ref.get(name),
             "entries": entries(name)} for name in ranked[:n]]


def run_select() -> list[dict]:
    reference = _read(REFERENCE_REPORT) if REFERENCE_REPORT.exists() else None
    papers = select_papers(_read(EMBEDDING_REPORT), reference)
    _write(PAPERS_PATH, papers)
    for p in papers:
        print(f"   {p['registry']:24} non-exact embedding {p['non_exact_embedding']}  "
              f"v3 reference {p['non_exact_v3_reference']}  entries {p['entries']}")
    print(f"wrote {PAPERS_PATH.relative_to(REPO_ROOT)}")
    return papers


def selected_registries(source: Path = SOURCE_DIR, only: str | None = None) -> list[Path]:
    if not PAPERS_PATH.exists():
        sys.exit("papers.json missing: run `select` first")
    dirs = [source / p["registry"] for p in _read(PAPERS_PATH)]
    if only:
        dirs = [d for d in dirs if re.search(rf"_{re.escape(only)}(_pdf)?$", d.name, re.IGNORECASE)]
    return dirs


# ── the full-list picker ──────────────────────────────────────────────────────

def vocabulary(index_path: Path = INDEX_PATH) -> list[dict]:
    """Every term of the index as a candidate the picker can render, in index order."""
    return [{"id": t["id"], "label": t["label"],
             "text": " | ".join([t["label"], *(str(s) for s in t.get("synonyms") or [])]),
             "definition": t.get("definition") or "", "n_descendants": t.get("n_descendants"),
             "similarity": None}
            for t in _read(index_path)]


def candidate_lines(candidates: list[dict]) -> list[str]:
    """The picker's own line format; an unmarked term drops the empty "()" it would carry."""
    from app.agent.assay_obi_mapper import _candidate_line

    return [_candidate_line(i + 1, c).removesuffix(" ()") for i, c in enumerate(candidates)]


def with_pins(candidates: list[dict], pinned: list[dict] | None) -> list[dict]:
    """The full list with the exact hit and its children marked in place, order unchanged."""
    pins = {p["id"]: p["pin"] for p in pinned or []}
    return [{**c, "pin": pins[c["id"]]} if c["id"] in pins else c for c in candidates]


def build_prompt(assay_name: str, candidates: list[dict], sample_type: str = "", readouts: str = "",
                 aliases: list[str] | None = None, standard_technique_name: str = "") -> str:
    """prompt.txt filled like build_pick_prompt fills resolver_obi_assay.txt. The 701 lines come
    before the assay record, so every call shares one long prefix the provider can cache."""
    named = [a.strip() for a in (aliases or []) if isinstance(a, str) and a.strip()]
    return (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{candidates}", "\n".join(candidate_lines(candidates)))
        .replace("{assay_name}", assay_name)
        .replace("{aliases}", ", ".join(named) if named else "none given")
        .replace("{standard_technique_name}", standard_technique_name.strip() or "not given")
        .replace("{sample_type}", sample_type.strip() or "not specified")
        .replace("{readouts}", readouts.strip() or "not specified")
    )


def _complete(prompt: str, model: str) -> tuple[str, dict]:
    from openai import OpenAI

    from app.config import settings

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}],
                                          temperature=0)
    u = resp.usage
    details = getattr(u, "prompt_tokens_details", None)
    usage = {"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
             "cached_tokens": getattr(details, "cached_tokens", 0) or 0}
    return (resp.choices[0].message.content or "").strip().lower(), usage


#: Filled per call by fulllist_match, drained per registry by map_one.
USAGE: list[dict] = []


def fulllist_match(query: str, allowed_ids=None, sample_type: str = "", readouts: str = "",
                   display_name: str = "", model: str | None = None, aliases: list[str] | None = None,
                   standard_technique_query: str = "", pinned: list[dict] | None = None,
                   registry_key: str = "", complete=_complete) -> dict | None:
    """Drop-in for assay_obi_mapper._embedding_llm_match: same arguments, same result shape,
    the whole vocabulary in place of the retrieved top 20."""
    from app.agent import assay_trace
    from app.agent.assay_obi_mapper import parse_pick_reply
    from app.config import settings

    exact_hit = next((p for p in pinned or [] if p.get("pin") == "exact"), None)
    candidates = with_pins(vocabulary(), pinned)
    name = display_name or query
    normalized = standard_technique_query.strip()
    prompt = build_prompt(name, candidates, sample_type, readouts, aliases,
                          normalized if normalized.lower() != name.strip().lower() else "")
    reply, usage = complete(prompt, model or settings.OPENAI_MODEL)
    USAGE.append({"key": registry_key or name, **usage})
    assay_trace.record("obi", registry_key or name, reply=reply, n_candidates=len(candidates))
    idx, granularity = parse_pick_reply(reply, len(candidates))
    if idx is None:
        if exact_hit:
            return {"obi_id": exact_hit["id"], "obi_label": exact_hit["label"],
                    "resource": "exact_original_llm", "confidence": "high"}
        return None
    chosen = candidates[idx]
    return {"obi_id": chosen["id"], "obi_label": chosen["label"],
            "resource": "exact_original_llm" if exact_hit else "fulllist_llm",
            "confidence": "high" if exact_hit else None, "granularity": granularity}


class FullList:
    """Swap the mapper's retrieval-and-pick step for fulllist_match inside a `with` block."""

    def __enter__(self) -> "FullList":
        from app.agent import assay_obi_mapper as mapper

        self._saved = mapper._embedding_llm_match
        mapper._embedding_llm_match = fulllist_match
        return self

    def __exit__(self, *exc: object) -> None:
        from app.agent import assay_obi_mapper as mapper

        mapper._embedding_llm_match = self._saved


# ── map ───────────────────────────────────────────────────────────────────────

def plan(assays: dict) -> list[str]:
    """Keys that reach the paid step: everything but an exact hit on a childless term."""
    from app.agent import assay_obi_mapper as mapper
    from app.agent.assay_service import _obi_query

    lookup = mapper._build_lookup(INDEX_PATH)
    children = mapper._index_children(INDEX_PATH)
    paid = []
    for key, entry in assays.items():
        original, _ = _obi_query(key, entry)
        hit = lookup.get(original.lower()) if original else None
        if hit and not children.get(hit["obi_id"]):
            continue
        paid.append(key)
    return paid


def map_one(registry: Path, runs_dir: Path = RUNS_DIR) -> dict:
    from app.agent import assay_trace
    from app.agent.assay_obi_mapper import enrich_assays_with_obi

    out_dir = runs_dir / ARM / registry.name
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("assays.json", "assays_benchmark.json"):
        if (registry / name).exists():
            shutil.copyfile(registry / name, out_dir / name)
    assays = _read(registry / "assays.json")
    USAGE.clear()
    trace = assay_trace.start()
    try:
        with FullList():
            obi = enrich_assays_with_obi(assays, terms_path=INDEX_PATH)
    finally:
        assay_trace.stop()
    _write(out_dir / "assays_OBI.json", obi)
    trace.write(out_dir / "raw.json")
    _write(out_dir / "usage.json", list(USAGE))
    return obi


def run_map(dry_run: bool, only: str | None = None, force: bool = False,
            source: Path = SOURCE_DIR, runs_dir: Path = RUNS_DIR) -> None:
    from app.agent.assay_service import obi_summary

    dirs = selected_registries(source, only)
    print(f"== arm {ARM}: {len(dirs)} registries, index {INDEX_PATH.name}")
    if dry_run:
        sample = build_prompt("x", vocabulary())
        approx = len(sample) // 4
        entries = paid = 0
        for registry in dirs:
            assays = _read(registry / "assays.json")
            keys = plan(assays)
            entries += len(assays)
            paid += len(keys)
            print(f"   {registry.name:24} {len(assays)} entries, {len(keys)} paid")
        print(f"   {entries} entries, {paid} reach the paid step = {paid} chat calls, no embeddings")
        print(f"   prompt ~{len(sample):,} chars ~{approx:,} tokens (chars/4) per call, "
              f"~{paid * approx:,} input tokens total, most of it a shared cacheable prefix")
        print("--dry-run: nothing called")
        return
    totals = Counter()
    for registry in dirs:
        done = runs_dir / ARM / registry.name / "assays_OBI.json"
        if done.exists() and not force:
            print(f"   skip {registry.name}: already mapped (--force to redo)")
            continue
        obi = map_one(registry, runs_dir)
        summary = obi_summary(obi)
        usage = _read(runs_dir / ARM / registry.name / "usage.json")
        for u in usage:
            totals.update({"calls": 1, **{k: u[k] for k in ("prompt_tokens", "cached_tokens",
                                                              "completion_tokens")}})
        print(f"   {registry.name}: {summary['mapped']}/{summary['total']} mapped, {len(usage)} calls, "
              f"resources {summary['resources']}", flush=True)
        for key in summary["unresolved"]:
            if key in summary["errors"]:
                print(f"      OBI ERROR  {key}: {summary['errors'][key]}")
            else:
                print(f"      UNMAPPED   {key}")
    print(f"   spent this run: {dict(totals)}")


# ── score ─────────────────────────────────────────────────────────────────────

def stage_baselines(runs_dir: Path = RUNS_DIR, source: Path = SOURCE_DIR,
                    embedding_runs: Path = EMBEDDING_RUNS) -> None:
    """runs/embedding and runs/v3_reference: the selected registries' already-paid mappings,
    copied so the comparator scores exactly the same 10 papers in every column."""
    for registry in selected_registries(source):
        for arm, src in ((EMBEDDING, embedding_runs / registry.name), (REFERENCE, registry)):
            out = runs_dir / arm / registry.name
            out.mkdir(parents=True, exist_ok=True)
            for name in ("assays.json", "assays_benchmark.json", "assays_OBI.json"):
                if (src / name).exists():
                    shutil.copyfile(src / name, out / name)


def score_arm(arm: str, runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR,
              benchmark_dir: Path = BENCHMARK_DIR) -> dict:
    registry_dir = runs_dir / arm
    subprocess.run([sys.executable, str(COMPARATOR), "--registry-dir", str(registry_dir),
                    "--benchmark-dir", str(benchmark_dir), "--out-stem", arm],
                   check=True, cwd=REPO_ROOT)
    comparison_dir.mkdir(parents=True, exist_ok=True)
    for suffix in (".json", ".html"):
        shutil.copyfile(registry_dir / "comparison" / f"{arm}{suffix}", comparison_dir / f"{arm}{suffix}")
    return _read(comparison_dir / f"{arm}.json")


def run_score() -> dict[str, dict]:
    stage_baselines()
    reports = {arm: score_arm(arm) for arm in (ARM, EMBEDDING, REFERENCE) if (RUNS_DIR / arm).exists()}
    for name, report in reports.items():
        t = report["totals"]
        print(f"{name:14} papers {t['papers']:>2}  matched {t['matched']:>3}  exact {t['exact']:>3}  "
              f"obi_exact_rate {t['obi_exact_rate']:.1%}  obi_recall {t['obi_recall']:.1%}  "
              f"{t['status_counts']}")
        for s in t["skipped"]:
            print(f"   SKIPPED {s}")
    return reports


# ── report ────────────────────────────────────────────────────────────────────

def row_index(report: dict) -> dict[tuple[str, str], dict]:
    """{(registry, our key): {status, curator}} for every agent entry the scorer saw."""
    out = {}
    for paper in report["papers"]:
        reg = Path(paper["registry_dir"]).name
        for row in paper["rows"]:
            bench = row.get("benchmark") or {}
            curator = ({"obi_id": bench.get("obi_id"), "obi_label": bench.get("obi_label")}
                       if row["status"] in _MATCHED and bench else None)
            for ours in row.get("ours") or []:
                out[(reg, ours["key"])] = {"status": row["status"], "curator": curator}
    return out


def entry_rows(runs_dir: Path, reports: dict[str, dict]) -> list[dict]:
    """One row per entry: each arm's term and status, and who of embedding / fulllist won."""
    index = {arm: row_index(r) for arm, r in reports.items()}
    rows = []
    for registry in sorted(d for d in (runs_dir / ARM).iterdir() if (d / "assays_OBI.json").exists()):
        obi = {arm: _read(runs_dir / arm / registry.name / "assays_OBI.json")
               for arm in reports if (runs_dir / arm / registry.name / "assays_OBI.json").exists()}
        for key in obi[ARM]:
            seen = {arm: index[arm].get((registry.name, key), {}) for arm in reports}
            curator = next((s["curator"] for s in seen.values() if s.get("curator")), None)
            row = {"registry": registry.name, "key": key, "curator": curator}
            for arm in reports:
                e = obi.get(arm, {}).get(key) or {}
                row[arm] = {"obi_id": e.get("obi_id"), "obi_label": e.get("obi_label"),
                            "granularity": e.get("obi_granularity"), "resource": e.get("resource"),
                            "status": seen[arm].get("status")}
            emb, full = row.get(EMBEDDING, {}).get("status"), row[ARM]["status"]
            row["verdict"] = ("won" if full == "MATCH" and emb != "MATCH" else
                              "lost" if emb == "MATCH" and full != "MATCH" else
                              "same" if row.get(EMBEDDING, {}).get("obi_id") == row[ARM]["obi_id"] else
                              "changed")
            rows.append(row)
    return rows


def run_report(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR) -> dict:
    reports = {arm: _read(comparison_dir / f"{arm}.json")
               for arm in (ARM, EMBEDDING, REFERENCE) if (comparison_dir / f"{arm}.json").exists()}
    totals = {}
    for arm, report in reports.items():
        t = report["totals"]
        totals[arm] = {k: t[k] for k in ("papers", "benchmark_total", "ours_total", "matched", "exact",
                                          "obi_ok", "obi_exact_rate", "obi_recall")}
        totals[arm]["status_counts"] = t["status_counts"]
    spent = Counter()
    for f in sorted((runs_dir / ARM).glob("*/usage.json")):
        for u in _read(f):
            spent.update({"calls": 1, **{k: u[k] for k in ("prompt_tokens", "cached_tokens",
                                                            "completion_tokens")}})
    rows = entry_rows(runs_dir, reports)
    summary = {"papers": [p["registry"] for p in _read(PAPERS_PATH)], "totals": totals,
               "spent": dict(spent), "verdicts": dict(Counter(r["verdict"] for r in rows)), "rows": rows}
    _write(comparison_dir / "diff.json", summary)
    (comparison_dir / "summary.md").write_text(render_summary(summary), encoding="utf-8")
    print(render_summary(summary))
    return summary


def render_summary(summary: dict) -> str:
    names = list(summary["totals"])
    lines = ["# Full-list LLM (701 terms) vs embedding top-20, 10 worst papers of assay_result_v3", "",
             "Papers: " + ", ".join(summary["papers"]), "",
             "| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    keys = [("papers scored", "papers"), ("curated rows", "benchmark_total"), ("agent entries", "ours_total"),
            ("matched", "matched"), ("exact (same OBI term as curator)", "exact"),
            ("OBI ok (same or parent/child)", "obi_ok"),
            ("obi_exact_rate", "obi_exact_rate"), ("obi_recall", "obi_recall")]
    for label, key in keys:
        vals = [f"{v:.1%}" if isinstance(v, float) else str(v)
                for v in (summary["totals"][n][key] for n in names)]
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    for status in ("MATCH", *_NON_EXACT, "SPLIT", "MISSED", "EXTRA"):
        lines.append(f"| {status} | " + " | ".join(
            str(summary["totals"][n]["status_counts"].get(status, 0)) for n in names) + " |")
    lines += ["", f"Full-list spend: {summary['spent']}", "",
              f"## Per entry, embedding vs fulllist ({summary['verdicts']})", "",
              "| registry | entry | curator | " + " | ".join(names) + " | verdict |",
              "|---|---|---|" + "---|" * len(names) + "---|"]
    order = {"won": 0, "lost": 1, "changed": 2, "same": 3}
    for r in sorted(summary["rows"], key=lambda r: (order[r["verdict"]], r["registry"], r["key"])):
        cur = r["curator"] or {}
        cells = [f"{(r.get(n) or {}).get('obi_label') or '—'} ({(r.get(n) or {}).get('status') or '—'})"
                 for n in names]
        lines.append(f"| {r['registry']} | {r['key']} | {cur.get('obi_label') or '—'} | "
                     + " | ".join(cells) + f" | {r['verdict']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("select")
    m = sub.add_parser("map")
    m.add_argument("--dry-run", action="store_true")
    m.add_argument("--only", help="one study accession, e.g. SDY2189")
    m.add_argument("--force", action="store_true", help="re-map registries already mapped")
    sub.add_parser("score")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "select":
        run_select()
    elif args.command == "map":
        run_map(args.dry_run, args.only, args.force)
    elif args.command == "score":
        run_score()
    else:
        run_report()


if __name__ == "__main__":
    main()
