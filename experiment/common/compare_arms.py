#!/usr/bin/env python3
"""One table over every comparison arm that has been scored, in both scorer modes.

Each arm is read from its own `comparison/` folder (the reports `arms.score_runs` wrote there);
an arm whose reports are not on disk is left out with a note, so the table is always what has
actually been run. Repeat runs of one arm (`r1`, `r2`, `r3`) are shown as `mean (min-max)`;
named variants of one arm (`pruned_paper`, `full_methods`) are separate columns.

    python3 experiment/common/compare_arms.py [--mode default|strict|both] [--out PATH]

Writes experiment/common/comparison/arms_table.md by default. Free.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from arms import AGENT, AGENT_REPORTS, MODES, SOURCE_DIR, arm_column, fmt, read  # noqa: E402

EXPERIMENT = HERE.parent
OUT_PATH = HERE / "comparison" / "arms_table.md"

#: name -> (comparison folder, run stems, calls per run or None to count raw.json, repeats?)
ARMS: dict[str, tuple[Path, list[str], int | None, bool]] = {
    "bare LLM ×3 (strict ids)": (EXPERIMENT / "llm_baseline" / "comparison", ["r1", "r2", "r3"], None, True),
    "bare LLM ×3 (labels read)": (EXPERIMENT / "llm_baseline" / "comparison" / "label", ["r1", "r2", "r3"], None, True),
    "RAG single call ×3": (EXPERIMENT / "rag_single_call" / "comparison", ["r1", "r2", "r3"], None, True),
    # 31 is stated, not counted: OntoGPT writes `output.json` per paper, not the `raw.json` that
    # `calls_spent` looks for, so counting read 0 calls for an arm that makes one call per paper
    # (`experiment/ontogpt/README.md`: "31 extractions, one model call each").
    "OntoGPT": (EXPERIMENT / "ontogpt" / "comparison", ["r1"], 31, True),
    "NCBO Annotator, pruned/paper": (EXPERIMENT / "ncbo_annotator" / "comparison", ["pruned_paper"], 0, False),
    "NCBO Annotator, pruned/methods": (EXPERIMENT / "ncbo_annotator" / "comparison", ["pruned_methods"], 0, False),
    "dictionary, pruned/paper": (EXPERIMENT / "dictionary_baseline" / "comparison", ["pruned_paper"], 0, False),
    "dictionary, pruned/methods": (EXPERIMENT / "dictionary_baseline" / "comparison", ["pruned_methods"], 0, False),
    "dictionary, full/paper": (EXPERIMENT / "dictionary_baseline" / "comparison", ["full_paper"], 0, False),
    "agent, old same-term fold": (EXPERIMENT / "no_fold" / "comparison", ["term_fold"], 512, False),
}
ROWS = ["curated rows", "entries", "matched", "MISSED", "EXTRA", "exact (same OBI term as curator)",
        "OBI ok (same or parent/child)", "obi_exact_rate", "obi_recall", "wrong term (CONFLICT)",
        "no usable term (UNMAPPED)", "recall", "precision", "F1", "term-only pairs", "calls"]


def _runs_dir(comparison_dir: Path) -> Path:
    """The runs folder beside a comparison folder (`comparison/label` -> `runs_label`)."""
    if comparison_dir.name == "label":
        return comparison_dir.parents[1] / "runs_label"
    return comparison_dir.parent / "runs"


def columns(mode: str) -> tuple[dict[str, list[dict]], list[str]]:
    """{arm name: [one column per run]} for a scorer mode, and the arms left out."""
    cols: dict[str, list[dict]] = {}
    missing = []
    agent = AGENT_REPORTS[mode]
    cols[AGENT] = [arm_column(read(agent), SOURCE_DIR, agent=True)] if agent.exists() else []
    if not cols[AGENT]:
        missing.append(AGENT)
    for name, (cdir, runs, calls, _) in ARMS.items():
        got = []
        for run in runs:
            path = cdir / f"{run}{mode}.json"
            if path.exists():
                got.append(arm_column(read(path), _runs_dir(cdir) / run, calls=calls, id_statuses=False))
        if got:
            cols[name] = got
        else:
            missing.append(name)
    return cols, missing


def cell(values: list, repeats: bool) -> str:
    if not values:
        return "—"
    if len(values) == 1 or not repeats:
        return fmt(values[0])
    mean = sum(values) / len(values)
    if isinstance(values[0], float):
        return f"{mean:.1%} ({min(values):.1%}–{max(values):.1%})"
    return f"{mean:.1f} ({min(values)}–{max(values)})"


def table(mode: str) -> str:
    cols, missing = columns(mode)
    names = list(cols)
    lines = ["| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for row in ROWS:
        cells = []
        for n in names:
            repeats = ARMS[n][3] if n in ARMS else False
            cells.append(cell([c[row] for c in cols[n] if row in c], repeats))
        lines.append(f"| {row} | " + " | ".join(cells) + " |")
    if missing:
        lines += ["", "Not yet run: " + ", ".join(missing) + "."]
    return "\n".join(lines)


def render(modes: list[str]) -> str:
    out = ["# Comparison arms vs the assay agent, benchmark v5 (31 papers)", "",
           "Repeat runs are `mean (min–max)`. Calls are per run; the agent's 512 cover all five rounds.", ""]
    for mode in modes:
        out += [f"## Scorer mode: {'strict' if mode else 'default'}", "", table(mode), ""]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["default", "strict", "both"], default="both")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    modes = list(MODES) if args.mode == "both" else ["" if args.mode == "default" else "_strict"]
    text = render(modes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
