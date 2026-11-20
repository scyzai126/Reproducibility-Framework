#!/usr/bin/env python3
"""Dictionary baseline: the OBI assay vocabulary string-matched against the paper. No model.

The simplest thing that could list a paper's assays with OBI terms: every label and synonym of the
assay vocabulary, matched as whole words in the paper text, longest match first. It is what a
reviewer means by "why not just grep for the ontology", and it is the arm the agent has to beat on
the mapping without a model. Everything it gets wrong is informative: the paper wordings no OBI
term carries (Luminex, PRNT, CBA), and the terms whose labels are everyday words (`cell
culture`, `imaging`) that a paper uses outside any assay.

Four variants, all free:

    --vocab pruned   the agent's 701-term vocabulary (data/OBI/obi_assay_pruned_index.json)
    --vocab full     every assay term, 1794 (obi_assay_full_index.json)
    --scope paper    the whole paper, the same input the agent's round 1 reads
    --scope methods  the sentences under a Methods heading only (a PDF paper has no headings
                     and is matched whole; the README says which)

Matching rules, so the arm is not a strawman and not a cheat:
  * forms: the label and each synonym, each also without a trailing "assay" ("flow cytometry"
    names `flow cytometry assay`, "ELISPOT" its synonym "ELISPOT assay"), as whole words,
    case-insensitive, a plain plural of the last word allowed ("ELISAs"); an adjective form
    ("flow cytometric") is not matched;
  * a form of 3 characters is an acronym and must match in its own case; a form shorter than
    that, or a single all-lowercase word of 4 letters or fewer, is dropped (README lists them);
  * overlapping matches: the longest span wins, so "real-time PCR" is one term, not two;
  * one entry per term found, carrying every distinct wording matched and the first sentence.

**This is an experiment arm, not a way to run a paper.** Nothing here writes under data/.

    run    [--vocab pruned|full|both] [--scope paper|methods|both] [--only SDY]
           runs/<vocab>_<scope>/<registry>/{assays_benchmark.json, assays_OBI.json, matches.json}
    score  comparison/<variant>{,_strict}.{json,html} via scripts/compare_assay_benchmark_v2.py
    report comparison/summary.md: the table in both scorer modes, and the EXTRA terms a
           dictionary floods the list with

Usage, from the repo root:
    ./.venv/bin/python experiment/dictionary_baseline/run_dictionary.py run
    ./.venv/bin/python experiment/dictionary_baseline/run_dictionary.py score
    ./.venv/bin/python experiment/dictionary_baseline/run_dictionary.py report
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from arms import (  # noqa: E402
    OBI_INDEX, mode_tables, paper_input, read, registries, run_names, score_runs, sentences,
    term_registry, write)

RUNS_DIR = HERE / "runs"
COMPARISON_DIR = HERE / "comparison"
VOCABS = ("pruned", "full")
SCOPES = ("paper", "methods")
#: The one term that is the vocabulary's root and names nothing in a paper.
ROOT_LABELS = {"assay"}
ACRONYM_LEN = 3
SHORT_WORD = 4


# ── the dictionary ───────────────────────────────────────────────────────────

def forms_of(term: dict) -> list[str]:
    """The strings that name one term: label and synonyms, each also without a trailing
    "assay" ("flow cytometry" names `flow cytometry assay`; "ELISPOT" its synonym "ELISPOT assay")."""
    forms = []
    for f in [term["label"], *(term.get("synonyms") or [])]:
        f = str(f).strip()
        bare = re.sub(r"\s+assay$", "", f, flags=re.I)
        forms += [f, bare] if bare != f else [f]
    return [f for f in dict.fromkeys(forms) if f]


def keep_form(form: str) -> bool:
    """Drop what would match everywhere: the root, anything under 3 characters, and a single
    all-lowercase word of 4 letters or fewer ("gel", "stain")."""
    if form.lower() in ROOT_LABELS or len(form) < ACRONYM_LEN:
        return False
    if " " not in form and len(form) <= SHORT_WORD and form.islower():
        return False
    return True


def build_dictionary(index: list[dict]) -> list[tuple[str, re.Pattern, str]]:
    """[(form, compiled whole-word pattern, term id)], longest form first."""
    out = []
    for term in index:
        for form in forms_of(term):
            if not keep_form(form):
                continue
            flags = 0 if len(form) == ACRONYM_LEN and form.isupper() else re.I
            # Whole words; a hyphen or a slash inside the form matches itself or a space; a
            # plain plural of the last word ("ELISAs", "assays") matches too.
            body = r"[\s\-/]+".join(re.escape(w) for w in re.split(r"[\s\-/]+", form))
            out.append((form, re.compile(rf"(?<![\w-]){body}(?:e?s)?(?![\w-])", flags), term["id"]))
    out.sort(key=lambda t: -len(t[0]))
    return out


def dropped_forms(index: list[dict]) -> list[str]:
    return sorted({f for t in index for f in forms_of(t) if not keep_form(f)}, key=str.lower)


# ── matching ─────────────────────────────────────────────────────────────────

def match_sentence(text: str, dictionary: list[tuple[str, re.Pattern, str]]) -> list[dict]:
    """Non-overlapping matches in one sentence, longest first: {term, form, text, start}."""
    taken: list[tuple[int, int]] = []
    found = []
    for form, pattern, term_id in dictionary:
        for m in pattern.finditer(text):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            taken.append((s, e))
            found.append({"term": term_id, "form": form, "text": m.group(0), "start": s})
    return sorted(found, key=lambda f: f["start"])


def match_paper(paper: dict, dictionary: list[tuple[str, re.Pattern, str]], scope: str,
                labels: dict[str, str]) -> tuple[list[dict], dict]:
    """Entries for `term_registry` plus a `matches.json` record of every hit."""
    sents = sentences(paper)
    has_sections = any(s["section"] for s in sents)
    if scope == "methods" and has_sections:
        sents = [s for s in sents if s["section"] == "methods"]
    by_term: dict[str, dict] = {}
    hits = []
    for s in sents:
        for f in match_sentence(s["text"], dictionary):
            hits.append({**f, "sentence_id": s["id"], "section": s["section"]})
            entry = by_term.setdefault(f["term"], {
                "obi_id": f["term"], "obi_label": labels[f["term"]], "names": [],
                "quote": s["text"], "section": s["section"], "sentence_ids": [s["id"]] if s["id"] else [],
                "hits": 0})
            if f["text"] not in entry["names"]:
                entry["names"].append(f["text"])
            entry["hits"] += 1
    record = {"kind": paper["kind"], "scope": scope,
              "scope_applied": scope if (scope == "paper" or has_sections) else "paper (no headings)",
              "sentences": len(sents), "hits": hits}
    return list(by_term.values()), record


def run(vocabs: list[str], scopes: list[str], only: str | None = None, runs_dir: Path = RUNS_DIR) -> None:
    dirs = registries(only=only)
    papers = {d.name: paper_input(d) for d in dirs}
    for vocab in vocabs:
        index = read(OBI_INDEX[vocab])
        dictionary = build_dictionary(index)
        labels = {t["id"]: t["label"] for t in index}
        for scope in scopes:
            variant = f"{vocab}_{scope}"
            total = 0
            for d in dirs:
                entries, record = match_paper(papers[d.name], dictionary, scope, labels)
                entries = [{k: v for k, v in e.items() if k != "hits"} for e in entries]
                bench, obi = term_registry(entries, resource=f"dictionary:{variant}")
                out = runs_dir / variant / d.name
                write(out / "assays_benchmark.json", bench)
                write(out / "assays_OBI.json", obi)
                write(out / "matches.json", record)
                total += len(bench)
            print(f"   {variant:16} {len(dirs)} papers, {total} entries, "
                  f"{len(dictionary)} forms from {len(index)} terms")


# ── report ───────────────────────────────────────────────────────────────────

def extra_terms(report: dict, top: int = 15) -> list[tuple[str, int]]:
    """The OBI labels most often delivered with no curated row, across the corpus."""
    counts: Counter = Counter()
    for paper in report["papers"]:
        for row in paper["rows"]:
            if row["status"] == "EXTRA":
                for o in row["ours"]:
                    counts[o.get("obi_label") or o["key"]] += 1
    return counts.most_common(top)


def run_report(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR) -> str:
    runs = run_names(runs_dir)
    lines = ["# Dictionary baseline vs the assay agent, against benchmark v5", "",
             "Agent: `data/benchmark_agent_assays/assay_result_v3`. Dictionary variants: `<vocab>_<scope>`.", "",
             mode_tables(comparison_dir, runs_dir, run_calls={r: 0 for r in runs})]
    for run in runs:
        path = comparison_dir / f"{run}.json"
        if not path.exists():
            continue
        lines += [f"## Most frequent EXTRA terms: {run} (default mode)", "",
                  "| OBI label | papers |", "|---|---|"]
        lines += [f"| {label} | {n} |" for label, n in extra_terms(read(path))]
        lines.append("")
    text = "\n".join(lines) + "\n"
    (comparison_dir / "summary.md").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--vocab", choices=[*VOCABS, "both"], default="both")
    r.add_argument("--scope", choices=[*SCOPES, "both"], default="both")
    r.add_argument("--only")
    sub.add_parser("score")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.cmd == "run":
        run(list(VOCABS) if args.vocab == "both" else [args.vocab],
            list(SCOPES) if args.scope == "both" else [args.scope], args.only)
    elif args.cmd == "score":
        score_runs(RUNS_DIR, COMPARISON_DIR)
    else:
        print(run_report())


if __name__ == "__main__":
    main()
