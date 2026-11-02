#!/usr/bin/env python3
"""NCBO BioPortal Annotator baseline: a published concept-recognition service, on OBI.

The Annotator (https://data.bioontology.org/documentation#nav_annotator) finds ontology classes
in free text by dictionary lookup over the labels and synonyms of the ontologies BioPortal hosts,
OBI among them. It is the standard "annotate this text with an ontology" tool, so it is the
external arm a reviewer expects beside a home-made dictionary. No model is involved on either
side; the only cost is one HTTP request per paper and scope, and every reply is cached under
`runs/raw/` so a rerun is free.

Settings sent: `ontologies=OBI`, `longest_only=true` (one class per span), synonyms on, whole
words on. The reply's classes are kept only when they are in the assay vocabulary -- the 1794
descendants of `assay` (`--vocab full`) or the agent's 701 pruned terms (`--vocab pruned`); an
OBI class outside the assay subtree (a device, a role, a specimen) is not an assay and is dropped
before scoring, which is the same restriction the dictionary arm's vocabulary imposes. The two
scopes are the dictionary arm's: the whole paper, or its Methods sentences.

A BioPortal API key (free, https://bioportal.bioontology.org/accounts/new) goes in `.env` as
`BIOPORTAL_API_KEY`.

**This is an experiment arm, not a way to run a paper.** Nothing here writes under data/.

    fetch   [--scope paper|methods|both] [--only SDY] [--force]
            runs/raw/<scope>/<registry>.json  -- the submitted text's length and the reply
    build   [--vocab pruned|full|both] [--scope ...]
            runs/<vocab>_<scope>/<registry>/{assays_benchmark.json, assays_OBI.json}
    score   comparison/<variant>{,_strict}.{json,html}
    report  comparison/summary.md

Usage, from the repo root:
    ./.venv/bin/python experiment/ncbo_annotator/run_ncbo.py fetch
    ./.venv/bin/python experiment/ncbo_annotator/run_ncbo.py build
    ./.venv/bin/python experiment/ncbo_annotator/run_ncbo.py score
    ./.venv/bin/python experiment/ncbo_annotator/run_ncbo.py report
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from arms import (  # noqa: E402
    OBI_INDEX, REPO_ROOT, mode_tables, paper_input, read, registries, run_names, score_runs,
    sentences, term_registry, write)

RUNS_DIR = HERE / "runs"
RAW_DIR = RUNS_DIR / "raw"
COMPARISON_DIR = HERE / "comparison"
VOCABS = ("pruned", "full")
SCOPES = ("paper", "methods")
ANNOTATOR_URL = "https://data.bioontology.org/annotator"
PARAMS = {"ontologies": "OBI", "longest_only": "true", "exclude_synonyms": "false",
          "whole_word_only": "true", "expand_mappings": "false", "exclude_numbers": "true"}
PAUSE_SECONDS = 1.0


# ── the text sent ────────────────────────────────────────────────────────────

def scoped_text(paper: dict, scope: str) -> tuple[str, list[dict], str]:
    """(text to annotate, its sentences with offsets, the scope actually applied).

    The text is the sentences joined by a newline, so a reply offset maps back to one sentence.
    A PDF has no headings, so `methods` falls back to the whole text, as the dictionary arm does.
    """
    sents = sentences(paper)
    has_sections = any(s["section"] for s in sents)
    applied = scope
    if scope == "methods":
        if has_sections:
            sents = [s for s in sents if s["section"] == "methods"]
        else:
            applied = "paper (no headings)"
    offset = 0
    laid = []
    for s in sents:
        laid.append({**s, "start": offset, "end": offset + len(s["text"])})
        offset += len(s["text"]) + 1
    return "\n".join(s["text"] for s in sents), laid, applied


def api_key() -> str:
    key = os.environ.get("BIOPORTAL_API_KEY")
    if not key:
        env = REPO_ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("BIOPORTAL_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("BIOPORTAL_API_KEY is not set: add it to .env (free key at "
                 "https://bioportal.bioontology.org/accounts/new)")
    return key


def annotate(text: str, key: str) -> list[dict]:
    """One POST to the Annotator; the parsed JSON list of annotated classes."""
    data = urllib.parse.urlencode({**PARAMS, "apikey": key, "text": text}).encode()
    req = urllib.request.Request(ANNOTATOR_URL, data=data, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ssl_context() -> ssl.SSLContext:
    """certifi's CA bundle when installed: the framework Python this repo runs on ships none."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch(scopes: list[str], only: str | None = None, force: bool = False, raw_dir: Path = RAW_DIR) -> None:
    key = api_key()
    for d in registries(only=only):
        paper = paper_input(d)
        for scope in scopes:
            out = raw_dir / scope / f"{d.name}.json"
            if out.exists() and not force:
                continue
            text, laid, applied = scoped_text(paper, scope)
            # a paper whose headings carry no Methods section (SDY1669) has nothing to send;
            # the Annotator rejects an empty text, and the dictionary arm writes 0 entries there
            reply = annotate(text, key) if text.strip() else []
            write(out, {"registry": d.name, "kind": paper["kind"], "scope": scope, "scope_applied": applied,
                        "chars": len(text), "sentences": laid, "params": PARAMS, "reply": reply})
            print(f"   {scope:7} {d.name:28} {len(text):6} chars -> {len(reply)} classes")
            time.sleep(PAUSE_SECONDS)


# ── the reply as a registry ──────────────────────────────────────────────────

def class_id(annotated: dict) -> str | None:
    """`http://purl.obolibrary.org/obo/OBI_0000916` -> `OBI:0000916`."""
    iri = (annotated.get("annotatedClass") or {}).get("@id") or ""
    tail = iri.rsplit("/", 1)[-1]
    if "_" in tail:
        prefix, num = tail.split("_", 1)
        if num.isdigit():
            return f"{prefix}:{num}"
    return None


def sentence_at(laid: list[dict], pos: int) -> dict | None:
    """The sentence holding a 1-based reply offset."""
    pos -= 1
    for s in laid:
        if s["start"] <= pos < s["end"] + 1:
            return s
    return None


def entries_from_reply(raw: dict, vocab: dict[str, str]) -> list[dict]:
    """One entry per class in the assay vocabulary, with every wording the Annotator matched and
    the first sentence it appeared in. Classes outside the vocabulary are dropped."""
    text_sents = raw["sentences"]
    by_term: dict[str, dict] = {}
    for annotated in raw["reply"]:
        term = class_id(annotated)
        if not term or term not in vocab:
            continue
        for a in sorted(annotated.get("annotations") or [], key=lambda a: a.get("from", 0)):
            s = sentence_at(text_sents, int(a.get("from", 1)))
            entry = by_term.setdefault(term, {
                "obi_id": term, "obi_label": vocab[term], "names": [],
                "quote": s["text"] if s else "", "section": s["section"] if s else None,
                "sentence_ids": [s["id"]] if s and s["id"] else [], "hits": 0, "match_types": []})
            wording = str(a.get("text") or "")
            if wording and wording not in entry["names"]:
                entry["names"].append(wording)
            entry["match_types"].append(a.get("matchType"))
            entry["hits"] += 1
    return list(by_term.values())


def build(vocabs: list[str], scopes: list[str], only: str | None = None,
          runs_dir: Path = RUNS_DIR, raw_dir: Path = RAW_DIR) -> None:
    for vocab_name in vocabs:
        index = read(OBI_INDEX[vocab_name])
        vocab = {t["id"]: t["label"] for t in index}
        for scope in scopes:
            variant = f"{vocab_name}_{scope}"
            total = dropped = 0
            for d in registries(only=only):
                raw_path = raw_dir / scope / f"{d.name}.json"
                if not raw_path.exists():
                    print(f"   WARNING {variant}: no reply on disk for {d.name}; run `fetch` first")
                    continue
                raw = read(raw_path)
                entries = entries_from_reply(raw, vocab)
                dropped += sum(1 for a in raw["reply"] if class_id(a) not in vocab)
                bench, obi = term_registry(
                    [{k: v for k, v in e.items() if k not in ("hits", "match_types")} for e in entries],
                    resource=f"ncbo_annotator:{variant}")
                write(runs_dir / variant / d.name / "assays_benchmark.json", bench)
                write(runs_dir / variant / d.name / "assays_OBI.json", obi)
                write(runs_dir / variant / d.name / "matches.json",
                      {"scope_applied": raw["scope_applied"], "classes_in_reply": len(raw["reply"]),
                       "entries": entries})
                total += len(bench)
            print(f"   {variant:16} {total} entries; {dropped} annotated classes outside the vocabulary dropped")


# ── report ───────────────────────────────────────────────────────────────────

def extra_terms(report: dict, top: int = 15) -> list[tuple[str, int]]:
    counts: Counter = Counter()
    for paper in report["papers"]:
        for row in paper["rows"]:
            if row["status"] == "EXTRA":
                for o in row["ours"]:
                    counts[o.get("obi_label") or o["key"]] += 1
    return counts.most_common(top)


def run_report(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR) -> str:
    runs = [r for r in run_names(runs_dir) if r != "raw"]
    lines = ["# NCBO BioPortal Annotator (OBI) vs the assay agent, against benchmark v5", "",
             "Agent: `data/31paper_assays/assay_result_v3`. Annotator variants: `<vocab>_<scope>`.", "",
             mode_tables(comparison_dir, runs_dir, run_calls={r: 0 for r in runs})]
    for run in runs:
        path = comparison_dir / f"{run}.json"
        if path.exists():
            lines += [f"## Most frequent EXTRA terms: {run} (default mode)", "", "| OBI label | papers |", "|---|---|"]
            lines += [f"| {label} | {n} |" for label, n in extra_terms(read(path))]
            lines.append("")
    text = "\n".join(lines) + "\n"
    (comparison_dir / "summary.md").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--scope", choices=[*SCOPES, "both"], default="both")
    f.add_argument("--only")
    f.add_argument("--force", action="store_true")
    b = sub.add_parser("build")
    b.add_argument("--vocab", choices=[*VOCABS, "both"], default="both")
    b.add_argument("--scope", choices=[*SCOPES, "both"], default="both")
    b.add_argument("--only")
    sub.add_parser("score")
    sub.add_parser("report")
    args = parser.parse_args()
    scopes = list(SCOPES) if getattr(args, "scope", "both") == "both" else [args.scope]
    if args.cmd == "fetch":
        fetch(scopes, args.only, args.force)
    elif args.cmd == "build":
        build(list(VOCABS) if args.vocab == "both" else [args.vocab], scopes, args.only)
    elif args.cmd == "score":
        score_runs(RUNS_DIR, COMPARISON_DIR)
    else:
        print(run_report())


if __name__ == "__main__":
    main()
