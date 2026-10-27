#!/usr/bin/env python3
"""Bare LLM baseline vs the assay agent: one plain call per paper, extract + map to OBI from memory.

The question is how much the agent adds over just asking the model. The baseline is one call per
paper with `prompt.txt` -- list the assays, give a quote and the OBI id and label for each -- and
nothing else: no candidate vocabulary, no retrieval, no vote, no verify/correct, no fold. Same
model (`settings.OPENAI_MODEL`), same papers, same input the agent reads:

    XML paper   the JATS parse round 1 reads (assay_service.paper_source_text), [S<n>] markers removed
    _pdf paper  the PDF itself attached, as round 1 does

Default temperature and no seed, so the --runs repeats measure the variance a user would see.

**This is an experiment arm, not a way to run a paper.** CLAUDE.md allows assays to be delivered
only through scripts/run_assay_pipeline.py; nothing here writes under data/ and no answer about a
paper is ever to be taken from these files.

Every reply is converted to the two files the v2 comparator reads, so both sides are scored by
the same code against benchmark v5:

    assays_benchmark.json  keyed by the model's OBI label (else its paper name), ` (2)` on a repeat;
                           evidence.sentence_ids and source derived from the quote by code
    assays_OBI.json        the model's id checked against data/OBI/obi.obo: `id_status` is valid,
                           label_mismatch, obsolete, nonexistent or none. An obsolete or nonexistent
                           id is scored as unmapped; a label mismatch keeps the id (the id is what a
                           user would store) and the OBO label replaces the model's.

    run     --runs 3 [--dry-run] [--only SDY] [--force]
            runs/r<k>/<registry>/{raw.json, assays_benchmark.json, assays_OBI.json}
            resumable: a registry whose assays_OBI.json exists is skipped unless --force
    score   comparison/r<k>.{json,html} via scripts/compare_assay_benchmark_v2.py (free)
    report  comparison/{summary.md, diff.json}, with the delivered v3 registry as the agent column (free)
    relabel runs_label/r<k>/: the same replies with each term found by the model's label (free);
            `score --label` / `report --label` then write comparison/label/

Usage, from the repo root:
    ./.venv/bin/python experiment/llm_baseline/run_llm_baseline.py run --runs 3 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
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

from compare_assay_benchmark import normalize  # noqa: E402
from prune_obi_domain import read_terms  # noqa: E402

SOURCE_DIR = REPO_ROOT / "data" / "31paper_assays" / "assay_result_v3"
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_assay" / "benchmark_assay_v5"
AGENT_REPORT = SOURCE_DIR / "comparison" / "benchmark_v5_vs_agent.json"
OBO_PATH = REPO_ROOT / "data" / "OBI" / "obi.obo"
PROMPT_PATH = HERE / "prompt.txt"
RUNS_DIR = HERE / "runs"
COMPARISON_DIR = HERE / "comparison"
#: The label-resolved reading: same replies, the term found by the model's label rather than its id.
LABEL_RUNS_DIR = HERE / "runs_label"
LABEL_COMPARISON_DIR = COMPARISON_DIR / "label"
COMPARATOR = REPO_ROOT / "scripts" / "compare_assay_benchmark_v2.py"

AGENT = "agent"
CONCURRENCY = 4
ID_STATUSES = ("valid", "label_mismatch", "obsolete", "nonexistent", "none")
#: Statuses whose OBI term the ontology accepts -- the comparator's OBI_OK_STATUSES.
_OK = {"MATCH", "MATCH_GRANULARITY"}
_ID = re.compile(r"^\s*([A-Za-z]+)[:_](\d+)\s*$")
_SENTENCE_MARKER = re.compile(r"\[S\d+\]\s?")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def registries(source: Path = SOURCE_DIR, only: str | None = None) -> list[Path]:
    dirs = sorted(d for d in source.iterdir() if d.is_dir() and (d / "assays_benchmark.json").exists())
    if only:
        dirs = [d for d in dirs if re.search(rf"_{re.escape(only)}(_pdf)?$", d.name, re.IGNORECASE)]
    return dirs


# ── checking the model's ids ──────────────────────────────────────────────────

def _loose(label: str) -> str:
    """normalize(), minus a trailing "assay": "flow cytometry" names `flow cytometry assay`."""
    return re.sub(r"\s+assay$", "", normalize(label))


class ObiIds:
    """Every [Term] in obi.obo: its name, synonyms and whether it is obsolete."""

    def __init__(self, obo_path: Path = OBO_PATH):
        self.name: dict[str, str] = {}
        self.forms: dict[str, set[str]] = {}
        for term in read_terms(obo_path):
            self.name[term["id"]] = term["name"]
            self.forms[term["id"]] = {_loose(term["name"])} | {_loose(s) for s in term["synonyms"]}
        # read_terms does not keep `is_obsolete`, so the stanzas are scanned for it here.
        self.obsolete: set[str] = set()
        for stanza in obo_path.read_text(encoding="utf-8").split("\n[")[1:]:
            if "\nis_obsolete: true" in stanza and (m := re.search(r"^id: (\S+)", stanza, re.M)):
                self.obsolete.add(m.group(1))
        # Label -> id over live terms, names before synonyms so a synonym never shadows a name.
        self.by_label: dict[str, str] = {}
        live = [t for t in self.name if t not in self.obsolete and not self.name[t].startswith("obsolete")]
        for t in live:
            self.by_label.setdefault(_loose(self.name[t]), t)
        for t in live:
            for form in self.forms[t]:
                self.by_label.setdefault(form, t)

    @staticmethod
    def canonical(obi_id: object) -> str | None:
        """`OBI_0000661` / ` obi:0000661 ` -> `OBI:0000661`; None for anything that is not an id."""
        m = _ID.match(str(obi_id or ""))
        return f"{m.group(1).upper()}:{m.group(2)}" if m else None

    def status(self, obi_id: str | None, label: str | None) -> str:
        if not obi_id:
            return "none"
        if obi_id not in self.name:
            return "nonexistent"
        if obi_id in self.obsolete or self.name[obi_id].startswith("obsolete"):
            return "obsolete"
        if label and _loose(label) not in self.forms[obi_id]:
            return "label_mismatch"
        return "valid"


# ── the call ─────────────────────────────────────────────────────────────────

def paper_input(registry: Path) -> dict:
    """What round 1 reads for this registry: the XML parse, or the PDF for a `_pdf` registry."""
    from app.agent.assay_service import (
        locate_paper_pdf, locate_paper_xml, paper_source, paper_source_text, split_stem)

    pmid, sdy = split_stem(registry.name)
    if registry.name.endswith("_pdf"):
        path = locate_paper_pdf(pmid, sdy)
        title, haystack = paper_source("pdf", path)
        return {"kind": "pdf", "path": path, "title": title, "text": None, "haystack": haystack}
    path = locate_paper_xml(pmid, sdy)
    title, numbered = paper_source_text(path)
    return {"kind": "xml", "path": path, "title": title,
            "text": _SENTENCE_MARKER.sub("", numbered), "haystack": numbered}


def build_messages(paper: dict) -> list[dict]:
    from app.agent.pdf_direct import _pdf_file_content

    prompt = PROMPT_PATH.read_text(encoding="utf-8").replace("{paper_title}", paper["title"])
    if paper["kind"] == "pdf":
        return [{"role": "user", "content": [
            _pdf_file_content(paper["path"].read_bytes(), paper["path"].name),
            {"type": "text", "text": prompt}]}]
    return [{"role": "user", "content": prompt + "\n\n" + paper["text"]}]


def parse_reply(raw: str) -> list[dict] | None:
    """The `assays` list of a reply, or None when the reply is not that JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        parsed = parsed.get("assays")
    if not isinstance(parsed, list):
        return None
    return [a for a in parsed if isinstance(a, dict)]


def to_registry(assays: list[dict], ids: ObiIds) -> tuple[dict, dict]:
    """(assays_benchmark.json, assays_OBI.json) for one parsed reply."""
    bench: dict = {}
    obi: dict = {}
    for a in assays:
        name = str(a.get("name_in_paper") or "").strip()
        claimed_id = a.get("obi_id")
        claimed_label = str(a.get("obi_label") or "").strip() or None
        obi_id = ids.canonical(claimed_id)
        status = ids.status(obi_id, claimed_label)
        kept_id = obi_id if status in ("valid", "label_mismatch") else None
        base = (ids.name[kept_id] if kept_id else None) or claimed_label or name or "unnamed assay"
        key, n = base, 1
        while key in bench:
            n += 1
            key = f"{base} ({n})"
        bench[key] = {
            "name_in_paper": [name] if name else [],
            "aliases": [],
            "generate_claim": None,
            "evidence": {"section": "", "quote": str(a.get("quote") or "").strip()},
        }
        obi[key] = {
            "obi_id": kept_id,
            "obi_label": ids.name[kept_id] if kept_id else None,
            "id_status": status,
            "claimed_id": claimed_id,
            "claimed_label": claimed_label,
            "name_in_paper": bench[key]["name_in_paper"],
        }
    return bench, obi


def relabel(obi: dict, ids: ObiIds) -> dict:
    """assays_OBI.json read by the model's label: the term whose name or synonym it is, else the
    model's own id when that is a live term. The most generous reading of a reply -- the model
    often names the term right with a wrong id, and sometimes the reverse (`OBI:0000893` called
    "quantitative PCR assay"), so neither the id nor the label alone is the baseline's best."""
    out = {}
    for key, e in obi.items():
        by_label = ids.by_label.get(_loose(e.get("claimed_label") or ""))
        term = by_label or e.get("obi_id")
        out[key] = {**e, "obi_id": term, "obi_label": ids.name[term] if term else None,
                    "resolved_by": "label" if by_label else ("id" if term else None)}
    return out


def run_relabel(runs_dir: Path = RUNS_DIR, label_dir: Path = LABEL_RUNS_DIR) -> None:
    ids = ObiIds()
    for run in run_names(runs_dir):
        for reg in sorted(d for d in (runs_dir / run).iterdir() if (d / "assays_OBI.json").is_file()):
            out = label_dir / run / reg.name
            out.mkdir(parents=True, exist_ok=True)
            for name in ("raw.json", "assays_benchmark.json"):
                shutil.copyfile(reg / name, out / name)
            _write(out / "assays_OBI.json", relabel(_read(reg / "assays_OBI.json"), ids))


async def call_one(client, model: str, registry: Path, out_dir: Path, ids: ObiIds) -> dict:
    from app.agent.assay_verifier import derive_evidence_fields

    paper = paper_input(registry)
    resp = await client.chat.completions.create(model=model, messages=build_messages(paper))
    raw = resp.choices[0].message.content or ""
    usage = resp.usage.model_dump() if resp.usage else None
    assays = parse_reply(raw)
    _write(out_dir / "raw.json", {"model": model, "kind": paper["kind"], "usage": usage,
                                  "parsed": assays is not None, "reply": raw})
    if assays is None:
        assays = []
    bench, obi = to_registry(assays, ids)
    derive_evidence_fields(bench, paper["haystack"])
    _write(out_dir / "assays_benchmark.json", bench)
    _write(out_dir / "assays_OBI.json", obi)
    return {"registry": registry.name, "entries": len(bench), "parsed": assays is not None,
            "id_status": dict(Counter(e["id_status"] for e in obi.values()))}


def run_calls(runs: int, dry_run: bool, only: str | None = None, force: bool = False,
              runs_dir: Path = RUNS_DIR) -> None:
    dirs = registries(only=only)
    todo = [(k, d) for k in range(1, runs + 1) for d in dirs
            if force or not (runs_dir / f"r{k}" / d.name / "assays_OBI.json").exists()]
    if dry_run:
        chars = 0
        for d in dirs:
            paper = paper_input(d)
            size = len(paper["text"]) if paper["text"] else paper["path"].stat().st_size
            chars += len(paper["text"] or "")
            print(f"   {d.name:28} {paper['kind']:3}  "
                  f"{'%d chars' % size if paper['text'] else '%d KB pdf' % (size // 1024)}")
        print(f"\n{len(dirs)} papers x {runs} runs; {len(todo)} calls to make "
              f"(the rest already on disk). XML text ~{chars // 4:,} input tokens per run, "
              f"plus {sum(1 for d in dirs if d.name.endswith('_pdf'))} PDFs.")
        return

    from openai import AsyncOpenAI

    from app.config import settings

    ids = ObiIds()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(k: int, d: Path) -> None:
        async with sem:
            try:
                s = await call_one(client, settings.OPENAI_MODEL, d, runs_dir / f"r{k}" / d.name, ids)
            except Exception as exc:  # one failed paper must not sink the run; it is re-run next time
                print(f"   FAILED r{k} {d.name}: {exc!r}")
                return
            flag = "" if s["parsed"] else "   UNPARSED reply, scored as empty"
            print(f"   r{k} {d.name}: {s['entries']} entries {s['id_status']}{flag}")

    async def main() -> None:
        await asyncio.gather(*(one(k, d) for k, d in todo))

    asyncio.run(main())


# ── scoring ──────────────────────────────────────────────────────────────────

def run_names(runs_dir: Path = RUNS_DIR) -> list[str]:
    return sorted((d.name for d in runs_dir.iterdir() if d.is_dir() and re.fullmatch(r"r\d+", d.name)),
                  key=lambda n: int(n[1:])) if runs_dir.exists() else []


def run_score(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR) -> None:
    comparison_dir.mkdir(parents=True, exist_ok=True)
    for run in run_names(runs_dir):
        subprocess.run([sys.executable, str(COMPARATOR), "--registry-dir", str(runs_dir / run),
                        "--benchmark-dir", str(BENCHMARK_DIR), "--out-stem", run],
                       check=True, cwd=REPO_ROOT)
        for suffix in (".json", ".html"):
            shutil.copyfile(runs_dir / run / "comparison" / f"{run}{suffix}",
                            comparison_dir / f"{run}{suffix}")
    shutil.copyfile(AGENT_REPORT, comparison_dir / f"{AGENT}.json")


# ── report ───────────────────────────────────────────────────────────────────

def bench_rows(report: dict) -> dict[tuple[str, str], dict]:
    """{(registry name, curator key): row} for every curated row. Not the study: SDY1364 and
    SDY1276 each have two papers."""
    return {(Path(paper["registry_dir"]).name, row["benchmark"]["key"]): row
            for paper in report["papers"] for row in paper["rows"] if row.get("benchmark")}


def id_counts(run_dir: Path) -> Counter:
    counts: Counter = Counter()
    for path in run_dir.glob("*/assays_OBI.json"):
        counts.update(e.get("id_status", "none") for e in _read(path).values())
    return counts


def calls_spent(run_dir: Path, agent: bool) -> int:
    """One per raw.json for a baseline run; every reply in assays_raw.json for the agent."""
    if not agent:
        return sum(1 for _ in run_dir.glob("*/raw.json"))
    return sum(len(v) for p in run_dir.glob("*/assays_raw.json")
               for v in _read(p).values() if isinstance(v, dict))


def arm_column(report: dict, run_dir: Path, agent: bool) -> dict:
    t = report["totals"]
    s = t["status_counts"]
    col = {
        "curated rows": t["benchmark_total"], "entries": t["ours_total"], "matched": t["matched"],
        "MISSED": t["missed"], "EXTRA": t["extra"],
        "exact (same OBI term as curator)": t["exact"],
        "OBI ok (same or parent/child)": t["obi_ok"],
        "obi_exact_rate": t["obi_exact_rate"], "obi_recall": t["obi_recall"],
        "wrong term (CONFLICT)": s.get("MATCH_OBI_CONFLICT", 0),
        "no usable term (UNMAPPED)": s.get("MATCH_OBI_UNMAPPED", 0),
        "calls": calls_spent(run_dir, agent),
    }
    if not agent:
        ids = id_counts(run_dir)
        col.update({f"ids: {k}": ids.get(k, 0) for k in ID_STATUSES})
    return col


def _fmt(v) -> str:
    return f"{v:.1%}" if isinstance(v, float) else str(v)


def summary_table(cols: dict[str, dict]) -> str:
    runs = [n for n in cols if n != AGENT]
    metrics = list(dict.fromkeys(m for c in cols.values() for m in c))
    head = ["metric", *cols, "baseline mean (min-max)"] if runs else ["metric", *cols]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for m in metrics:
        cells = [_fmt(cols[n][m]) if m in cols[n] else "—" for n in cols]
        vals = [cols[n][m] for n in runs if m in cols[n]]
        if runs:
            if vals:
                mean = sum(vals) / len(vals)
                pct = isinstance(vals[0], float)
                cells.append(f"{mean:.1%} ({min(vals):.1%}-{max(vals):.1%})" if pct
                             else f"{mean:.1f} ({min(vals)}-{max(vals)})")
            else:
                cells.append("—")
        lines.append(f"| {m} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def majority(statuses: list[str]) -> str:
    """The most common status; a tie goes to the first run's."""
    counts = Counter(statuses)
    best = max(counts.values())
    return next(s for s in statuses if counts[s] == best)


def reason(agent_status: str, base_status: str, base_id_statuses: list[str]) -> str | None:
    agent_ok, base_ok = agent_status in _OK, base_status in _OK
    if agent_ok == base_ok:
        return None
    if base_ok:
        return "agent_worse"
    if base_status == "MISSED":
        return "baseline_missed"
    if any(s in ("nonexistent", "obsolete") for s in base_id_statuses):
        return "baseline_fake_id"
    return "baseline_wrong_term"


def compare(reports: dict[str, dict], runs_dir: Path = RUNS_DIR) -> dict:
    """Per curated row: agent status, each run's status, the majority, and why they differ."""
    runs = [n for n in reports if n != AGENT]
    agent_rows = bench_rows(reports[AGENT])
    run_rows = {n: bench_rows(reports[n]) for n in runs}

    rows, stable = [], 0
    for key, arow in sorted(agent_rows.items()):
        statuses, id_stats, terms = [], [], []
        for n in runs:
            row = run_rows[n].get(key)
            statuses.append(row["status"] if row else "MISSED")
            ours = (row or {}).get("ours") or []
            terms.append(", ".join(f"{o.get('obi_id')} {o.get('obi_label')}" for o in ours) or "—")
            obi_path = runs_dir / n / key[0] / "assays_OBI.json"
            obi = _read(obi_path) if obi_path.is_file() else {}
            id_stats += [obi.get(o["key"], {}).get("id_status", "none") for o in ours]
        stable += len(set(statuses)) == 1
        base = majority(statuses) if statuses else "MISSED"
        rows.append({
            "registry": key[0], "curated": key[1],
            "curator_term": f"{arow['benchmark'].get('obi_id')} {arow['benchmark'].get('obi_label')}",
            "agent": arow["status"],
            "agent_term": ", ".join(f"{o.get('obi_id')} {o.get('obi_label')}"
                                    for o in arow.get("ours") or []) or "—",
            "baseline": dict(zip(runs, statuses)), "baseline_majority": base,
            "baseline_terms": dict(zip(runs, terms)),
            "reason": reason(arow["status"], base, id_stats),
        })
    return {"rows": rows, "curated_rows": len(rows), "same_status_all_runs": stable,
            "reasons": dict(Counter(r["reason"] for r in rows if r["reason"]))}


def term_stability(runs_dir: Path = RUNS_DIR) -> dict:
    """Per paper, the distinct valid OBI ids each run used: share present in every run."""
    runs = run_names(runs_dir)
    union = every = 0
    for reg in sorted({d.name for n in runs for d in (runs_dir / n).iterdir() if d.is_dir()} - {"comparison"}):
        sets = []
        for n in runs:
            path = runs_dir / n / reg / "assays_OBI.json"
            sets.append({e["obi_id"] for e in _read(path).values() if e.get("obi_id")} if path.is_file() else set())
        union += len(set().union(*sets))
        every += len(set.intersection(*sets)) if sets else 0
    return {"distinct_terms": union, "in_every_run": every}


def run_report(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR) -> str:
    reports = {AGENT: _read(comparison_dir / f"{AGENT}.json")}
    reports.update({n: _read(comparison_dir / f"{n}.json") for n in run_names(runs_dir)
                    if (comparison_dir / f"{n}.json").exists()})
    cols = {AGENT: arm_column(reports[AGENT], SOURCE_DIR, agent=True)}
    cols.update({n: arm_column(reports[n], runs_dir / n, agent=False) for n in reports if n != AGENT})
    diff = compare(reports, runs_dir)
    stab = term_stability(runs_dir)
    diff["term_stability"] = stab
    _write(comparison_dir / "diff.json", diff)

    lines = ["# Bare LLM baseline vs the assay agent, against benchmark v5", "",
             summary_table(cols), "",
             f"Curated rows with the same baseline status in every run: "
             f"{diff['same_status_all_runs']} / {diff['curated_rows']}.  "
             f"Valid OBI terms per paper present in every run: "
             f"{stab['in_every_run']} / {stab['distinct_terms']}.", "",
             f"## Rows where the agent and the baseline majority disagree ({sum(diff['reasons'].values())})",
             "", f"counts: {diff['reasons']}", "",
             "| registry | curated | curator | agent | baseline (per run) | baseline terms (r1) | reason |",
             "|---|---|---|---|---|---|---|"]
    for r in diff["rows"]:
        if r["reason"]:
            first = next(iter(r["baseline_terms"].values()), "—")
            lines.append(f"| {r['registry']} | {r['curated']} | {r['curator_term']} | {r['agent']} "
                         f"| {' / '.join(r['baseline'].values())} | {first} | {r['reason']} |")
    text = "\n".join(lines) + "\n"
    (comparison_dir / "summary.md").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--runs", type=int, default=3)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--only")
    r.add_argument("--force", action="store_true")
    sub.add_parser("relabel")
    for name in ("score", "report"):
        sub.add_parser(name).add_argument("--label", action="store_true",
                                          help="the label-resolved runs (runs_label/, comparison/label/)")
    args = parser.parse_args()
    dirs = (LABEL_RUNS_DIR, LABEL_COMPARISON_DIR) if getattr(args, "label", False) else (RUNS_DIR, COMPARISON_DIR)
    if args.cmd == "run":
        run_calls(args.runs, args.dry_run, args.only, args.force)
    elif args.cmd == "relabel":
        run_relabel()
    elif args.cmd == "score":
        run_score(*dirs)
    else:
        print(run_report(*dirs))


if __name__ == "__main__":
    main()
