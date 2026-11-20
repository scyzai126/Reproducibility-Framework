"""What every comparison arm shares: the papers, the registry files the scorer reads, scoring in
both comparator modes, and the summary table.

An *arm* is one way of listing a paper's assays and naming their OBI terms -- the agent, a bare
LLM call, a dictionary, an annotator. Each arm writes, per paper, the two files
`scripts/compare_assay_benchmark_v2.py` reads (`assays_benchmark.json` keyed by OBI label,
`assays_OBI.json` with the term), so every arm is scored by the same code against benchmark v5,
in both the default and the `--strict` mode (`docs/assay_scorer_strict_mode.md`).

Nothing here calls a model or writes under `data/`. No file under `experiment/` is a way to run a
paper (CLAUDE.md); the agent's own registries are read from `data/benchmark_agent_assays/assay_result_v3/`.

Layout an arm keeps, so the helpers find its files:

    experiment/<arm>/runs/<run>/<registry>/{assays_benchmark.json, assays_OBI.json, ...}
    experiment/<arm>/comparison/<run>.{json,html}, <run>_strict.{json,html}, agent{,_strict}.json
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / "apps" / "api", REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_assay_benchmark import normalize  # noqa: E402
from prune_obi_domain import read_terms  # noqa: E402

SOURCE_DIR = REPO_ROOT / "data" / "benchmark_agent_assays" / "assay_result_v3"
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_curator_assay" / "benchmark_assay_v5"
#: The agent's own scoring, both modes, as `compare_assay_benchmark_v2.py --registry-dir` wrote it.
AGENT_REPORTS = {"": SOURCE_DIR / "comparison" / "benchmark_vs_agent.json",
                 "_strict": SOURCE_DIR / "comparison" / "benchmark_vs_agent_strict.json"}
OBO_PATH = REPO_ROOT / "data" / "OBI" / "obi.obo"
OBI_INDEX = {"pruned": REPO_ROOT / "data" / "OBI" / "obi_assay_pruned_index.json",
             "full": REPO_ROOT / "data" / "OBI" / "obi_assay_full_index.json"}
COMPARATOR = REPO_ROOT / "scripts" / "compare_assay_benchmark_v2.py"

AGENT = "agent"
MODES = ("", "_strict")
ID_STATUSES = ("valid", "label_mismatch", "obsolete", "nonexistent", "none")
_ID = re.compile(r"^\s*([A-Za-z]+)[:_](\d+)\s*$")
SENTENCE_MARKER = re.compile(r"\[S\d+\]\s?")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ── the papers ───────────────────────────────────────────────────────────────

def registries(source: Path = SOURCE_DIR, only: str | None = None) -> list[Path]:
    """The agent's registry folders, one per paper; `only` keeps one study (SDY1289)."""
    dirs = sorted(d for d in source.iterdir() if d.is_dir() and (d / "assays_benchmark.json").exists())
    if only:
        dirs = [d for d in dirs if re.search(rf"_{re.escape(only)}(_pdf)?$", d.name, re.IGNORECASE)]
    return dirs


def paper_input(registry: Path) -> dict:
    """What round 1 reads for this registry: the XML parse, or the PDF for a `_pdf` registry.

    `haystack` carries the `[S<n>]` sentence markers (the PDF's is its plain text); `text` is the
    same with the markers removed, None for a PDF.
    """
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
            "text": SENTENCE_MARKER.sub("", numbered), "haystack": numbered}


_HEADING = re.compile(r"^## .*?\[(\w+)\]\s*$", re.M)


def sentences(paper: dict) -> list[dict]:
    """The paper as sentences: `{id, text, section}`.

    For an XML paper the `[S<n>]` markers are the boundaries and the `## heading  [section]` lines
    the sections, so `section` is `abstract`, `methods`, `results` ... as the parser tagged them.
    A PDF has neither: it is split on sentence punctuation and every sentence's section is None.
    """
    hay = paper["haystack"] or ""
    if paper["kind"] != "xml":
        return [{"id": None, "text": s.strip(), "section": None}
                for s in re.split(r"(?<=[.!?])\s+", hay) if s.strip()]
    parts = re.split(r"\[S(\d+)\]\s?", hay)
    out: list[dict] = []
    section = None
    for m in _HEADING.finditer(parts[0]):
        section = m.group(1)
    for i in range(1, len(parts) - 1, 2):
        sid, chunk = int(parts[i]), parts[i + 1]
        text, _, tail = chunk.partition("\n")
        text = text.strip()
        if text:
            out.append({"id": sid, "text": text, "section": section})
        for m in _HEADING.finditer(tail):
            section = m.group(1)
    return out


# ── OBI ids and the registry files ───────────────────────────────────────────

def loose(label: str) -> str:
    """normalize(), minus a trailing "assay": "flow cytometry" names `flow cytometry assay`."""
    return re.sub(r"\s+assay$", "", normalize(label))


class ObiIds:
    """Every [Term] in obi.obo: its name, synonyms and whether it is obsolete."""

    def __init__(self, obo_path: Path = OBO_PATH):
        self.name: dict[str, str] = {}
        self.forms: dict[str, set[str]] = {}
        for term in read_terms(obo_path):
            self.name[term["id"]] = term["name"]
            self.forms[term["id"]] = {loose(term["name"])} | {loose(s) for s in term["synonyms"]}
        # read_terms does not keep `is_obsolete`, so the stanzas are scanned for it here.
        self.obsolete: set[str] = set()
        for stanza in obo_path.read_text(encoding="utf-8").split("\n[")[1:]:
            if "\nis_obsolete: true" in stanza and (m := re.search(r"^id: (\S+)", stanza, re.M)):
                self.obsolete.add(m.group(1))
        # Label -> id over live terms, names before synonyms so a synonym never shadows a name.
        self.by_label: dict[str, str] = {}
        live = [t for t in self.name if t not in self.obsolete and not self.name[t].startswith("obsolete")]
        for t in live:
            self.by_label.setdefault(loose(self.name[t]), t)
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
        if label and loose(label) not in self.forms[obi_id]:
            return "label_mismatch"
        return "valid"


def to_registry(assays: list[dict], ids: ObiIds) -> tuple[dict, dict]:
    """(assays_benchmark.json, assays_OBI.json) for a model's reply: `name_in_paper`, `quote`,
    and the `obi_id` + `obi_label` it claimed, checked against obi.obo.

    An obsolete or nonexistent id is scored as unmapped; a label mismatch keeps the id (the id
    is what a user would store) and the OBO label replaces the model's.
    """
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
        key = unique_key(base, bench)
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


def unique_key(base: str, taken: dict) -> str:
    """`base`, or `base (2)`, `base (3)` ... -- how the agent keys a repeat on one label."""
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base} ({n})"
    return key


def term_registry(entries: list[dict], resource: str) -> tuple[dict, dict]:
    """(assays_benchmark.json, assays_OBI.json) for an arm that found terms directly -- a
    dictionary or an annotator -- so every id is a live term and there is nothing to check.

    Each entry: `obi_id`, `obi_label`, `names` (the wordings found), `quote`, `section`
    (`methods` / `results` / ... or None) and optionally `sentence_ids`.
    """
    bench: dict = {}
    obi: dict = {}
    for e in entries:
        key = unique_key(e.get("obi_label") or (e["names"][0] if e["names"] else "unnamed assay"), bench)
        section = e.get("section")
        bench[key] = {
            "name_in_paper": list(e["names"]),
            "aliases": [],
            "generate_claim": None,
            "source": section if section in ("methods", "results") else None,
            # Sentence ids are written as the agent writes them, `S165`, so one viewer reads both.
            "evidence": {"section": section or "", "quote": e.get("quote") or "",
                         "sentence_ids": [f"S{n}" for n in e.get("sentence_ids") or []]},
        }
        obi[key] = {
            "obi_id": e.get("obi_id"),
            "obi_label": e.get("obi_label"),
            "resource": resource,
            "id_status": "valid" if e.get("obi_id") else "none",
            "name_in_paper": bench[key]["name_in_paper"],
        }
    return bench, obi


# ── scoring ──────────────────────────────────────────────────────────────────

def run_names(runs_dir: Path) -> list[str]:
    """Every run folder under `runs/`: `r1`, `r2` ... numerically, then any named variant."""
    if not runs_dir.exists():
        return []
    names = [d.name for d in runs_dir.iterdir() if d.is_dir() and d.name != "raw"]  # raw replies, not a run
    numbered = sorted((n for n in names if re.fullmatch(r"r\d+", n)), key=lambda n: int(n[1:]))
    return numbered + sorted(n for n in names if not re.fullmatch(r"r\d+", n))


def score_run(run_dir: Path, comparison_dir: Path, stem: str) -> None:
    """Score one run folder in both modes; the reports land in `comparison_dir` as
    `<stem>.{json,html}` and `<stem>_strict.{json,html}`."""
    comparison_dir.mkdir(parents=True, exist_ok=True)
    for mode in MODES:
        cmd = [sys.executable, str(COMPARATOR), "--registry-dir", str(run_dir),
               "--benchmark-dir", str(BENCHMARK_DIR), "--out-stem", f"{stem}{mode}"]
        if mode:
            cmd.append("--strict")
        subprocess.run(cmd, check=True, cwd=REPO_ROOT, stdout=subprocess.DEVNULL)
        for suffix in (".json", ".html"):
            shutil.copyfile(run_dir / "comparison" / f"{stem}{mode}{suffix}",
                            comparison_dir / f"{stem}{mode}{suffix}")


def copy_agent_reports(comparison_dir: Path) -> None:
    """The agent's column, both modes, beside the arm's: `agent.json`, `agent_strict.json`."""
    comparison_dir.mkdir(parents=True, exist_ok=True)
    for mode, path in AGENT_REPORTS.items():
        shutil.copyfile(path, comparison_dir / f"{AGENT}{mode}.json")


def score_runs(runs_dir: Path, comparison_dir: Path) -> None:
    """Every run of an arm, both modes, plus the agent's reports."""
    for run in run_names(runs_dir):
        score_run(runs_dir / run, comparison_dir, run)
    copy_agent_reports(comparison_dir)


# ── the table ────────────────────────────────────────────────────────────────

def bench_rows(report: dict) -> dict[tuple[str, str], dict]:
    """{(registry name, curator key): row} for every curated row. Not the study: SDY1364 and
    SDY1276 each have two papers."""
    return {(Path(paper["registry_dir"]).name, row["benchmark"]["key"]): row
            for paper in report["papers"] for row in paper["rows"] if row.get("benchmark")}


def id_counts(run_dir: Path) -> Counter:
    counts: Counter = Counter()
    for path in run_dir.glob("*/assays_OBI.json"):
        counts.update(e.get("id_status", "none") for e in read(path).values())
    return counts


def calls_spent(run_dir: Path, agent: bool) -> int:
    """One per raw.json for a model-call arm; every reply in assays_raw.json for the agent."""
    if not agent:
        return sum(1 for _ in run_dir.glob("*/raw.json"))
    return sum(len(v) for p in run_dir.glob("*/assays_raw.json")
               for v in read(p).values() if isinstance(v, dict))


def arm_column(report: dict, run_dir: Path, agent: bool = False, calls: int | None = None,
               id_statuses: bool | None = None) -> dict:
    """One column of the summary table from a scored report. `calls` overrides the count read
    off disk (0 for an arm that calls nothing); `id_statuses` adds the model-id rows."""
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
        "recall": t["recall"], "precision": t["precision"], "F1": t["f1"],
        "term-only pairs": t.get("term_only_pairs", 0),
        "calls": calls_spent(run_dir, agent) if calls is None else calls,
    }
    if id_statuses is None:
        id_statuses = not agent
    if id_statuses:
        ids = id_counts(run_dir)
        col.update({f"ids: {k}": ids.get(k, 0) for k in ID_STATUSES})
    return col


def fmt(v) -> str:
    return f"{v:.1%}" if isinstance(v, float) else str(v)


def summary_table(cols: dict[str, dict], mean_of: list[str] | None = None) -> str:
    """Markdown table, one column per arm. `mean_of` names the columns (repeat runs of one arm)
    summarised as `mean (min-max)` in a last column; by default every column but the agent's."""
    runs = [n for n in cols if n != AGENT] if mean_of is None else mean_of
    metrics = list(dict.fromkeys(m for c in cols.values() for m in c))
    head = ["metric", *cols, "mean (min-max)"] if len(runs) > 1 else ["metric", *cols]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for m in metrics:
        cells = [fmt(cols[n][m]) if m in cols[n] else "—" for n in cols]
        if len(runs) > 1:
            vals = [cols[n][m] for n in runs if m in cols[n]]
            if vals:
                mean = sum(vals) / len(vals)
                pct = isinstance(vals[0], float)
                cells.append(f"{mean:.1%} ({min(vals):.1%}-{max(vals):.1%})" if pct
                             else f"{mean:.1f} ({min(vals)}-{max(vals)})")
            else:
                cells.append("—")
        lines.append(f"| {m} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def mode_tables(comparison_dir: Path, runs_dir: Path, run_calls: dict[str, int] | None = None,
                id_statuses: bool = False, repeats: bool = False) -> str:
    """The summary table for each scorer mode: agent first, then every scored run. `repeats`
    says the runs are repeats of one arm, worth a mean column; variants of an arm are not."""
    out = []
    for mode in MODES:
        agent_path = comparison_dir / f"{AGENT}{mode}.json"
        if not agent_path.exists():
            continue
        cols = {AGENT: arm_column(read(agent_path), SOURCE_DIR, agent=True)}
        for run in run_names(runs_dir):
            path = comparison_dir / f"{run}{mode}.json"
            if path.exists():
                calls = None if run_calls is None else run_calls.get(run, 0)
                cols[run] = arm_column(read(path), runs_dir / run, calls=calls, id_statuses=id_statuses)
        table = summary_table(cols, mean_of=None if repeats else [])
        out += [f"## Scorer mode: {'strict' if mode else 'default'}", "", table, ""]
    return "\n".join(out)
