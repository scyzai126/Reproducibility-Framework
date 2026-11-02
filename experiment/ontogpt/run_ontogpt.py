#!/usr/bin/env python3
"""OntoGPT (SPIRES) baseline: the published LLM-plus-ontology extraction tool, on OBI.

OntoGPT (Monarch Initiative; Caufield et al. 2024) is the closest published system to this
agent: a schema tells the model what to list, the model answers in free text, and each answer is
grounded to an ontology term by lexical lookup (OAK's annotator over OBI's labels and synonyms).
It is run here as it ships, with the same model the agent uses (`settings.OPENAI_MODEL`), on the
same paper text the agent's round 1 reads, and the template `assay_paper.yaml`: one multivalued
`assays` slot of `Assay` entities grounded by `sqlite:obo:obi`. One call per paper; no
vocabulary in the prompt, no retrieval, no vote, no verification.

The tool lives in its own virtualenv (`experiment/ontogpt/.venv`, gitignored; README has the
exact install) because its dependency set does not fit the project's. This script shells out to
that venv's `ontogpt` binary with `OPENAI_API_KEY` from `.env`.

Scoring reads `named_entities` from the JSON OntoGPT writes (`-O json`): an entity grounded to a term of the
assay vocabulary (`--vocab full`: the 1794 descendants of `assay`; `pruned`: the agent's 701)
is a mapped entry; one grounded to another OBI class (a device, a role) is `outside_vocabulary`
and one left `AUTO:` is `none`, both scored as unmapped and keyed by the model's wording.

**This is an experiment arm, not a way to run a paper.** Nothing here writes under data/.

    run     --runs 1 [--dry-run] [--only SDY] [--force]
            runs/r<k>/<registry>/{input.txt, output.json, ontogpt.log}
    build   [--vocab pruned|full|both]   runs/r<k>/<registry>/{assays_benchmark.json, assays_OBI.json}
            (both vocabularies are written beside each other as assays_*.json / assays_*_pruned.json;
            `score` scores the full-vocabulary reading, `score --vocab pruned` the other)
    score   comparison/r<k>{,_strict}.{json,html}
    report  comparison/summary.md

Usage, from the repo root:
    ./.venv/bin/python experiment/ontogpt/run_ontogpt.py run --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from arms import (  # noqa: E402
    AGENT, MODES, OBI_INDEX, REPO_ROOT, SOURCE_DIR, arm_column, paper_input, read, registries,
    run_names, score_runs, sentences, summary_table, unique_key, write)

TEMPLATE = HERE / "assay_paper.yaml"
ONTOGPT = HERE / ".venv" / "bin" / "ontogpt"
RUNS_DIR = HERE / "runs"
COMPARISON_DIR = HERE / "comparison"
ID_STATUSES = ("valid", "outside_vocabulary", "none")
_USAGE = re.compile(r'"usage":\s*(\{.*?\})\}?\s*$', re.M)


# ── the call ─────────────────────────────────────────────────────────────────

def input_text(paper: dict) -> str:
    """The marker-free text for an XML paper; a PDF's plain text."""
    return paper["text"] if paper["text"] is not None else (paper["haystack"] or "")


def extract(text_path: Path, out_path: Path, log_path: Path, model: str) -> None:
    env = {**os.environ}
    if not env.get("OPENAI_API_KEY"):
        sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
        from app.config import settings
        env["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    cmd = [str(ONTOGPT), "-vv", "extract", "-t", str(TEMPLATE), "-i", str(text_path), "-m", model,
           "-O", "json", "-o", str(out_path), "--cut-input-text"]
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run(cmd, check=True, env=env, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT)


def usage_from_log(log_path: Path) -> dict | None:
    """The `usage` block of the model reply OntoGPT logs at -vv, summed over the calls it made."""
    if not log_path.exists():
        return None
    tot: Counter = Counter()
    seen = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if '"usage"' not in line or '"id": "' not in line:
            continue
        try:
            reply = json.loads(line)
        except json.JSONDecodeError:
            continue
        if reply.get("id") in seen:
            continue
        seen.add(reply.get("id"))
        u = reply.get("usage") or {}
        tot["prompt_tokens"] += u.get("prompt_tokens", 0)
        tot["completion_tokens"] += u.get("completion_tokens", 0)
        tot["cached_tokens"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        tot["calls"] += 1
    return dict(tot) if tot else None


def run_calls(runs: int, dry_run: bool, only: str | None = None, force: bool = False,
              runs_dir: Path = RUNS_DIR) -> None:
    dirs = registries(only=only)
    todo = [(k, d) for k in range(1, runs + 1) for d in dirs
            if force or not (runs_dir / f"r{k}" / d.name / "output.json").exists()]
    if dry_run:
        chars = sum(len(input_text(paper_input(d))) for d in dirs)
        print(f"{len(dirs)} papers x {runs} runs; {len(todo)} OntoGPT extractions to make (the rest on disk). "
              f"One model call each, no chunking: ~{chars // 4:,} input tokens per run plus the prompt frame.")
        if not ONTOGPT.exists():
            print(f"WARNING: {ONTOGPT} is missing; see README for the install")
        return
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
    from app.config import settings

    for k, d in todo:
        out = runs_dir / f"r{k}" / d.name
        out.mkdir(parents=True, exist_ok=True)
        paper = paper_input(d)
        (out / "input.txt").write_text(input_text(paper), encoding="utf-8")
        try:
            extract(out / "input.txt", out / "output.json", out / "ontogpt.log", settings.OPENAI_MODEL)
        except subprocess.CalledProcessError as exc:
            print(f"   FAILED r{k} {d.name}: ontogpt exit {exc.returncode}; see {out / 'ontogpt.log'}")
            continue
        ents = (read(out / "output.json") or {}).get("named_entities") or []
        grounded = sum(1 for e in ents if not str(e.get("id", "")).startswith("AUTO:"))
        u = usage_from_log(out / "ontogpt.log") or {}
        print(f"   r{k} {d.name}: {len(ents)} entities, {grounded} grounded "
              f"[{u.get('calls', '?')} calls, {u.get('prompt_tokens', '?')} prompt tokens]")


# ── the output as a registry ─────────────────────────────────────────────────

def sentence_offsets(paper: dict, text: str) -> list[dict]:
    """The paper's sentences with their offsets in the text OntoGPT read."""
    out = []
    pos = 0
    for s in sentences(paper):
        at = text.find(s["text"], pos)
        if at < 0:
            continue
        out.append({**s, "start": at, "end": at + len(s["text"])})
        pos = at + len(s["text"])
    return out


def first_span(entity: dict) -> int | None:
    spans = entity.get("original_spans") or []
    if not spans:
        return None
    m = re.match(r"(\d+):(\d+)", str(spans[0]))
    return int(m.group(1)) if m else None


def entries_from_output(output: dict, text: str, laid: list[dict], vocab: dict[str, str]) -> list[dict]:
    """One entry per named entity: term, wording, the sentence of its first span, and status."""
    entries = []
    for ent in output.get("named_entities") or []:
        ent_id, label = str(ent.get("id") or ""), str(ent.get("label") or "").strip()
        start = first_span(ent)
        sent = next((s for s in laid if start is not None and s["start"] <= start < s["end"]), None)
        if not sent and label:
            sent = next((s for s in laid if label.lower() in s["text"].lower()), None)
        if ent_id.startswith("AUTO:") or not ent_id:
            status, term = "none", None
        elif ent_id in vocab:
            status, term = "valid", ent_id
        else:
            status, term = "outside_vocabulary", None
        entries.append({"obi_id": term, "obi_label": vocab.get(term) if term else None,
                        "grounded_id": None if ent_id.startswith("AUTO:") else ent_id,
                        "id_status": status, "names": [label] if label else [],
                        "quote": sent["text"] if sent else "", "section": sent["section"] if sent else None,
                        "sentence_ids": [sent["id"]] if sent and sent["id"] else []})
    return entries


def registry_files(entries: list[dict]) -> tuple[dict, dict]:
    bench: dict = {}
    obi: dict = {}
    for e in entries:
        key = unique_key(e["obi_label"] or (e["names"][0] if e["names"] else "unnamed assay"), bench)
        section = e.get("section")
        bench[key] = {"name_in_paper": list(e["names"]), "aliases": [], "generate_claim": None,
                      "source": section if section in ("methods", "results") else None,
                      "evidence": {"section": section or "", "quote": e["quote"],
                                   "sentence_ids": [f"S{n}" for n in e["sentence_ids"]]}}
        obi[key] = {"obi_id": e["obi_id"], "obi_label": e["obi_label"], "resource": "ontogpt",
                    "id_status": e["id_status"], "grounded_id": e["grounded_id"],
                    "name_in_paper": bench[key]["name_in_paper"]}
    return bench, obi


def build(vocab_name: str, only: str | None = None, runs_dir: Path = RUNS_DIR) -> None:
    vocab = {t["id"]: t["label"] for t in read(OBI_INDEX[vocab_name])}
    suffix = "" if vocab_name == "full" else f"_{vocab_name}"
    for run in run_names(runs_dir):
        counts: Counter = Counter()
        for d in registries(only=only):
            out = runs_dir / run / d.name
            if not (out / "output.json").exists():
                continue
            paper = paper_input(d)
            text = (out / "input.txt").read_text(encoding="utf-8")
            output = read(out / "output.json") or {}
            entries = entries_from_output(output, text, sentence_offsets(paper, text), vocab)
            bench, obi = registry_files(entries)
            write(out / f"assays_benchmark{suffix}.json", bench)
            write(out / f"assays_OBI{suffix}.json", obi)
            counts.update(e["id_status"] for e in entries)
        print(f"   {run} vocab={vocab_name}: {sum(counts.values())} entries {dict(counts)}")


def stage(vocab_name: str, runs_dir: Path = RUNS_DIR) -> Path:
    """`score` reads assays_benchmark.json; for the pruned reading the `_pruned` files are
    staged into a sibling runs folder."""
    if vocab_name == "full":
        return runs_dir
    staged = runs_dir.parent / f"runs_{vocab_name}"
    for run in run_names(runs_dir):
        for d in (runs_dir / run).iterdir():
            src = d / f"assays_benchmark_{vocab_name}.json"
            if src.exists():
                dst = staged / run / d.name
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst / "assays_benchmark.json")
                shutil.copyfile(d / f"assays_OBI_{vocab_name}.json", dst / "assays_OBI.json")
    return staged


# ── report ───────────────────────────────────────────────────────────────────

def id_counts(run_dir: Path) -> Counter:
    counts: Counter = Counter()
    for path in run_dir.glob("*/assays_OBI.json"):
        counts.update(e.get("id_status", "none") for e in read(path).values())
    return counts


def run_report(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR, vocab_name: str = "full") -> str:
    lines = [f"# OntoGPT (SPIRES, grounded to OBI by OAK) vs the assay agent, benchmark v5 — {vocab_name} vocabulary", ""]
    for mode in MODES:
        agent_path = comparison_dir / f"{AGENT}{mode}.json"
        if not agent_path.exists():
            continue
        cols = {AGENT: arm_column(read(agent_path), SOURCE_DIR, agent=True)}
        for run in run_names(runs_dir):
            path = comparison_dir / f"{run}{mode}.json"
            if not path.exists():
                continue
            usage = Counter()
            for log in (RUNS_DIR / run).glob("*/ontogpt.log"):
                usage.update(usage_from_log(log) or {})
            col = arm_column(read(path), runs_dir / run, calls=usage.get("calls", 0), id_statuses=False)
            ids = id_counts(runs_dir / run)
            col.update({f"ids: {k}": ids.get(k, 0) for k in ID_STATUSES})
            col.update({f"tokens: {k}": v for k, v in usage.items() if k != "calls"})
            cols[run] = col
        lines += [f"## Scorer mode: {'strict' if mode else 'default'}", "", summary_table(cols, mean_of=[]), ""]
    text = "\n".join(lines) + "\n"
    (comparison_dir / "summary.md").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--runs", type=int, default=1)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--only")
    r.add_argument("--force", action="store_true")
    b = sub.add_parser("build")
    b.add_argument("--vocab", choices=["pruned", "full", "both"], default="both")
    b.add_argument("--only")
    for name in ("score", "report"):
        sub.add_parser(name).add_argument("--vocab", choices=["pruned", "full"], default="full")
    args = parser.parse_args()
    if args.cmd == "run":
        run_calls(args.runs, args.dry_run, args.only, args.force)
    elif args.cmd == "build":
        for v in (["pruned", "full"] if args.vocab == "both" else [args.vocab]):
            build(v, args.only)
    elif args.cmd == "score":
        cdir = COMPARISON_DIR if args.vocab == "full" else COMPARISON_DIR / args.vocab
        score_runs(stage(args.vocab), cdir)
    else:
        cdir = COMPARISON_DIR if args.vocab == "full" else COMPARISON_DIR / args.vocab
        print(run_report(stage(args.vocab), cdir, args.vocab))


if __name__ == "__main__":
    main()
