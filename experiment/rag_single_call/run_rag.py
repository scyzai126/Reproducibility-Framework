#!/usr/bin/env python3
"""RAG single call: the bare LLM baseline with the OBI assay vocabulary in its context.

`experiment/llm_baseline/` showed one plain gpt-5.4 call finds the assays and cannot name their
OBI terms (14 exact strict, 75 when its labels are read for it, against the agent's 140). The
obvious repair is to hand the model the vocabulary. This arm does exactly that and nothing else:
one call per paper, the 701 pruned terms first -- rendered as the agent's picker renders a
candidate (id | label | synonyms | definition | descendants), so the prefix is cacheable -- then
the bare prompt's instructions, which now ask for an id from the list or null. No retrieval, no
vote, no verify/correct, no fold. Same input as the agent's round 1 (`arms.paper_input`), same
model, default temperature, three runs so the variance a user would see is measured.

The model's id is kept only when it is a term of the vocabulary (`id_status: valid`); an id of
another live OBI term is `outside_vocabulary`, a made-up one `nonexistent`, and both score as
unmapped. The model's label is not read for it: with the list in view, the id is the answer.

**This is an experiment arm, not a way to run a paper.** Nothing here writes under data/.

    run     --runs 3 [--dry-run] [--only SDY] [--force]
            runs/r<k>/<registry>/{raw.json, assays_benchmark.json, assays_OBI.json}
            resumable: a registry whose assays_OBI.json exists is skipped unless --force
    score   comparison/r<k>{,_strict}.{json,html} + agent{,_strict}.json (free)
    report  comparison/summary.md (free)

Usage, from the repo root:
    ./.venv/bin/python experiment/rag_single_call/run_rag.py run --runs 3 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for _p in (REPO_ROOT / "experiment" / "common", REPO_ROOT / "experiment" / "llm_baseline",
           REPO_ROOT / "experiment" / "obi_llm_fulllist"):
    sys.path.insert(0, str(_p))
from arms import (  # noqa: E402
    AGENT, MODES, OBI_INDEX, SOURCE_DIR, ObiIds, arm_column, bench_rows, paper_input, read,
    registries, run_names, score_runs, summary_table, unique_key, write)
from run_fulllist import candidate_lines, vocabulary  # noqa: E402
from run_llm_baseline import parse_reply  # noqa: E402

PROMPT_PATH = HERE / "prompt.txt"
RUNS_DIR = HERE / "runs"
COMPARISON_DIR = HERE / "comparison"
CONCURRENCY = 4
ID_STATUSES = ("valid", "outside_vocabulary", "obsolete", "nonexistent", "none")
_OK = {"MATCH", "MATCH_GRANULARITY"}


# ── the prompt ───────────────────────────────────────────────────────────────

def vocab_ids(index_path: Path = OBI_INDEX["pruned"]) -> dict[str, str]:
    return {t["id"]: t["label"] for t in read(index_path)}


def build_prompt(title: str, index_path: Path = OBI_INDEX["pruned"]) -> str:
    """The vocabulary first, verbatim across papers, so the prefix caches; the title last."""
    terms = vocabulary(index_path)
    return (PROMPT_PATH.read_text(encoding="utf-8")
            .replace("{n_terms}", str(len(terms)))
            .replace("{vocabulary}", "\n".join(candidate_lines(terms)))
            .replace("{paper_title}", title))


def build_messages(paper: dict, index_path: Path = OBI_INDEX["pruned"]) -> list[dict]:
    from app.agent.pdf_direct import _pdf_file_content

    prompt = build_prompt(paper["title"], index_path)
    if paper["kind"] == "pdf":
        return [{"role": "user", "content": [
            _pdf_file_content(paper["path"].read_bytes(), paper["path"].name),
            {"type": "text", "text": prompt}]}]
    return [{"role": "user", "content": prompt + "\n\n" + paper["text"]}]


# ── the reply as a registry ──────────────────────────────────────────────────

def to_registry(assays: list[dict], ids: ObiIds, vocab: dict[str, str]) -> tuple[dict, dict]:
    """(assays_benchmark.json, assays_OBI.json): the id is kept only when it is in the list."""
    bench: dict = {}
    obi: dict = {}
    for a in assays:
        name = str(a.get("name_in_paper") or "").strip()
        claimed_id, claimed_label = a.get("obi_id"), str(a.get("obi_label") or "").strip() or None
        obi_id = ids.canonical(claimed_id)
        status = ids.status(obi_id, None)
        if status == "valid" and obi_id not in vocab:
            status = "outside_vocabulary"
        kept = obi_id if status == "valid" else None
        key = unique_key(vocab[kept] if kept else (claimed_label or name or "unnamed assay"), bench)
        bench[key] = {"name_in_paper": [name] if name else [], "aliases": [], "generate_claim": None,
                      "evidence": {"section": "", "quote": str(a.get("quote") or "").strip()}}
        obi[key] = {"obi_id": kept, "obi_label": vocab[kept] if kept else None, "id_status": status,
                    "claimed_id": claimed_id, "claimed_label": claimed_label,
                    "name_in_paper": bench[key]["name_in_paper"]}
    return bench, obi


# ── the call ─────────────────────────────────────────────────────────────────

async def call_one(client, model: str, registry: Path, out_dir: Path, ids: ObiIds, vocab: dict[str, str]) -> dict:
    from app.agent.assay_verifier import derive_evidence_fields

    paper = paper_input(registry)
    resp = await client.chat.completions.create(model=model, messages=build_messages(paper))
    raw = resp.choices[0].message.content or ""
    u = resp.usage
    details = getattr(u, "prompt_tokens_details", None) if u else None
    usage = ({"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
              "cached_tokens": getattr(details, "cached_tokens", 0) or 0} if u else None)
    assays = parse_reply(raw)
    write(out_dir / "raw.json", {"model": model, "kind": paper["kind"], "usage": usage,
                                 "parsed": assays is not None, "reply": raw})
    bench, obi = to_registry(assays or [], ids, vocab)
    derive_evidence_fields(bench, paper["haystack"])
    write(out_dir / "assays_benchmark.json", bench)
    write(out_dir / "assays_OBI.json", obi)
    return {"registry": registry.name, "entries": len(bench), "parsed": assays is not None,
            "usage": usage, "id_status": dict(Counter(e["id_status"] for e in obi.values()))}


def run_calls(runs: int, dry_run: bool, only: str | None = None, force: bool = False,
              runs_dir: Path = RUNS_DIR) -> None:
    dirs = registries(only=only)
    todo = [(k, d) for k in range(1, runs + 1) for d in dirs
            if force or not (runs_dir / f"r{k}" / d.name / "assays_OBI.json").exists()]
    if dry_run:
        prefix = len(build_prompt("title"))
        chars = 0
        for d in dirs:
            paper = paper_input(d)
            chars += len(paper["text"] or "")
            print(f"   {d.name:28} {paper['kind']:3}  "
                  f"{'%d chars' % len(paper['text']) if paper['text'] else '%d KB pdf' % (paper['path'].stat().st_size // 1024)}")
        print(f"\n{len(dirs)} papers x {runs} runs; {len(todo)} calls to make (the rest already on disk).\n"
              f"Vocabulary prefix ~{prefix // 4:,} tokens per call (cacheable after the first); "
              f"paper text ~{chars // 4:,} tokens per run, plus "
              f"{sum(1 for d in dirs if d.name.endswith('_pdf'))} PDFs attached.")
        return

    from openai import AsyncOpenAI

    from app.config import settings

    ids, vocab = ObiIds(), vocab_ids()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(k: int, d: Path) -> None:
        async with sem:
            try:
                s = await call_one(client, settings.OPENAI_MODEL, d, runs_dir / f"r{k}" / d.name, ids, vocab)
            except Exception as exc:  # one failed paper must not sink the run; it is re-run next time
                print(f"   FAILED r{k} {d.name}: {exc!r}")
                return
            flag = "" if s["parsed"] else "   UNPARSED reply, scored as empty"
            u = s["usage"] or {}
            print(f"   r{k} {d.name}: {s['entries']} entries {s['id_status']} "
                  f"[{u.get('prompt_tokens', '?')} prompt, {u.get('cached_tokens', '?')} cached]{flag}")

    async def main() -> None:
        await asyncio.gather(*(one(k, d) for k, d in todo))

    asyncio.run(main())


# ── report ───────────────────────────────────────────────────────────────────

def id_counts(run_dir: Path) -> Counter:
    counts: Counter = Counter()
    for path in run_dir.glob("*/assays_OBI.json"):
        counts.update(e.get("id_status", "none") for e in read(path).values())
    return counts


def tokens_spent(run_dir: Path) -> dict[str, int]:
    tot: Counter = Counter()
    for path in run_dir.glob("*/raw.json"):
        tot.update(read(path).get("usage") or {})
    return dict(tot)


def status_stability(reports: dict[str, dict]) -> tuple[int, int]:
    """(curated rows with one status across every run, curated rows)."""
    runs = [n for n in reports if n != AGENT]
    rows = {n: bench_rows(reports[n]) for n in runs}
    keys = bench_rows(reports[AGENT]).keys()
    same = sum(len({rows[n][k]["status"] if k in rows[n] else "MISSED" for n in runs}) == 1 for k in keys)
    return same, len(keys)


def run_report(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR) -> str:
    lines = ["# RAG single call (bare prompt + 701-term vocabulary) vs the assay agent, benchmark v5", ""]
    for mode in MODES:
        reports = {AGENT: read(comparison_dir / f"{AGENT}{mode}.json")}
        reports.update({n: read(comparison_dir / f"{n}{mode}.json") for n in run_names(runs_dir)
                        if (comparison_dir / f"{n}{mode}.json").exists()})
        cols = {AGENT: arm_column(reports[AGENT], SOURCE_DIR, agent=True)}
        for n in reports:
            if n == AGENT:
                continue
            col = arm_column(reports[n], runs_dir / n, calls=sum(1 for _ in (runs_dir / n).glob("*/raw.json")),
                             id_statuses=False)
            ids = id_counts(runs_dir / n)
            col.update({f"ids: {k}": ids.get(k, 0) for k in ID_STATUSES})
            col.update({f"tokens: {k}": v for k, v in tokens_spent(runs_dir / n).items()})
            cols[n] = col
        same, total = status_stability(reports)
        lines += [f"## Scorer mode: {'strict' if mode else 'default'}", "", summary_table(cols), "",
                  f"Curated rows with the same status in every run: {same} / {total}.", ""]
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
    sub.add_parser("score")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.cmd == "run":
        run_calls(args.runs, args.dry_run, args.only, args.force)
    elif args.cmd == "score":
        score_runs(RUNS_DIR, COMPARISON_DIR)
    else:
        print(run_report())


if __name__ == "__main__":
    main()
