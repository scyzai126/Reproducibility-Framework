#!/usr/bin/env python3
"""Compare the agent's assay registries against the human-curated benchmarks.

`data/benchmark_assay/<SDY>[_<pmid>]_*.json` holds a curator's assay list per paper, keyed by
**OBI label**. Several curator suffixes are in use (`_Assay_Hailong`, `_assays_AS_v2`, ...); every
file in the folder is scored, and the suffix is not read. `data/31paper_assays/<pmid>_<SDY>/assays_benchmark.json` holds ours, keyed by
the paper's own wording, and the sibling `assays_OBI.json` carries an `obi_id` per entry. Most of the
pairing is therefore ontology-ID equality; the rest falls through name/alias/quote tiers. No LLM call.

The benchmark is treated as a **recall reference, not exhaustive truth** — some benchmarks list one
assay where the paper describes nine — so recall is reported and precision deliberately is not. Our
unmatched assays are listed as EXTRA with their paper evidence, for a human to judge.

Usage:
    ./.venv/bin/python scripts/compare_assay_benchmark.py [--only SDY2189] [--stdout]

Reads  : data/benchmark_assay/*.json
         data/31paper_assays/<pmid>_<SDY>/{assays_benchmark,assays_OBI}.json
         data/OBI/obi.obo
Writes : data/benchmark_assay/comparison/{comparison.json,comparison.md}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# The same two folders app.agent.assay_table names -- this script is loaded by it, so it cannot
# import from the app without a cycle; keep the two in step by hand.
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_assay" / "benchmark_assay_v4"
REGISTRY_DIR = REPO_ROOT / "data" / "31paper_assays" / "assay_result_v1"
#: The benchmark side resolves against the FULL assay vocabulary — the 1794-term assay branch
#: of obi.obo — not `obi_generic_index.json`. That 700-term file is the pruned pool our own
#: mapper retrieves from; a curator is free to use a term the prune dropped, and resolving their
#: key against the pool would report a correct term as "not an OBI term". Coverage is nested
#: (700 of these 1794 are the pool), so widening here changes nothing about what we map to.
OBO_PATH = REPO_ROOT / "data" / "OBI" / "obi.obo"
OUT_DIR = BENCHMARK_DIR.parent / "comparison"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prune_obi_domain import assay_branch, parse_obo  # noqa: E402  (reuses the [Term] stanza reader)

# Matching tiers, strongest first. Only the best tier a benchmark row reaches is kept: a section
# heading like "Flow Cytometry Analysis and Cell Sorting for RNA Sequencing" quotes two assays, so a
# weaker tier's hits are decoys once a stronger one has paired the row.
TIERS = ["obi_exact", "obi_ancestry", "name", "name_containment", "quote"]

# Statuses that mean "the curator's assay was found", however imperfectly.
MATCHED_STATUSES = {"MATCH", "MATCH_GRANULARITY", "MATCH_OBI_CONFLICT", "MATCH_OBI_UNMAPPED", "SPLIT"}
# Statuses a reviewer has to look at.
CONFLICT_STATUSES = {"MATCH_OBI_CONFLICT", "MATCH_OBI_UNMAPPED", "SPLIT", "MISSED"}

QUOTE_CAP = 400  # Markdown only; the JSON keeps quotes whole.


# ── normalization ────────────────────────────────────────────────────────────

_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "κ": "kappa", "λ": "lambda", "μ": "mu", "σ": "sigma", "τ": "tau", "ω": "omega",
}


def normalize(text: str) -> str:
    """Casefold, spell greek letters out, drop punctuation, collapse whitespace.

    `IFNγ ELISpot` and `IFN-γ ELISPOT assay` have to land on comparable strings — the curator and the
    agent quote the same assay from the same paper with different typography.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).casefold()
    for greek, spelled in _GREEK.items():
        text = text.replace(greek, f" {spelled} ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _surface_forms(name: str | list[str] | None, aliases: list[str] | None) -> list[str]:
    """Every normalized wording. `name` is a list on our side once round 5 has canonicalized the
    registry -- one entry then carries every wording the paper used for it."""
    names = name if isinstance(name, list) else [name]
    forms = [normalize(n) for n in names if isinstance(n, str)]
    forms += [normalize(a) for a in (aliases or [])]
    return [f for f in dict.fromkeys(forms) if f]


# ── OBI vocabulary ───────────────────────────────────────────────────────────


class ObiGraph:
    """Label/synonym -> id lookup over the live vocabulary, plus is_a ancestry over full OBI."""

    def __init__(self, index_path: Path | None = None, obo_path: Path = OBO_PATH):
        """`index_path` overrides the vocabulary (tests); by default it is obi.obo's assay branch."""
        self.by_label: dict[str, str] = {}
        self.label_of: dict[str, str] = {}
        vocabulary = (
            json.loads(index_path.read_text(encoding="utf-8"))
            if index_path is not None
            else assay_branch(obo_path)
        )
        for term in vocabulary:
            self.label_of[term["id"]] = term["label"]
            self.by_label.setdefault(normalize(term["label"]), term["id"])
            for syn in term.get("synonyms", []):
                self.by_label.setdefault(normalize(syn), term["id"])
        names, children, _ = parse_obo(obo_path)
        self.label_of.update({tid: nm for tid, nm in names.items() if nm})
        self.parents: dict[str, list[str]] = defaultdict(list)
        for parent, kids in children.items():
            for kid in kids:
                self.parents[kid].append(parent)

    def resolve(self, label: str) -> str | None:
        """OBI id for a curator's key, or None when the key is not an OBI term."""
        return self.by_label.get(normalize(label))

    def ancestors(self, term_id: str) -> set[str]:
        seen: set[str] = set()
        stack = [term_id]
        while stack:
            for parent in self.parents.get(stack.pop(), ()):
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return seen

    def relation(self, bench_id: str | None, ours_id: str | None) -> str | None:
        """'exact' | 'ours_narrower' | 'ours_broader' | None."""
        if not bench_id or not ours_id:
            return None
        if bench_id == ours_id:
            return "exact"
        if bench_id in self.ancestors(ours_id):
            return "ours_narrower"
        if ours_id in self.ancestors(bench_id):
            return "ours_broader"
        return None


# ── reading the curator's side ────────────────────────────────────────────────

#: Spellings seen across the 31 benchmark files for the block holding the curator's OBI term, and for
#: the id inside it. Hand-curated files drift, and a reader that knows only one spelling silently
#: loses the term.
_OBI_CONTAINERS = ("OBI ontology", "OBI_ontology", "obi_ontology", "OBI", "obi")
_OBI_ID_KEYS = ("obi_id", "id", "obi id")
_OBI_ID = re.compile(r"^[A-Za-z]+:\d+$")


def bench_obi_id(entry: dict) -> str | None:
    """The OBI id the curator recorded, or None.

    Preferred over re-resolving the entry's dictionary key, because the key is prose a curator edits:
    `microarray assay` is an OBI label and `microarray` is not, so an innocuous rename silently
    demoted a pairing from the ontology tier to a name match. The id is what they actually asserted.
    """
    blocks = [entry[name] for name in _OBI_CONTAINERS
              if isinstance(entry.get(name), dict)] + [entry]
    for block in blocks:
        for key in _OBI_ID_KEYS:
            value = block.get(key)
            if isinstance(value, str) and _OBI_ID.match(value.strip()):
                return value.strip()
    return None


def bench_evidence(entry: dict) -> dict:
    """The curator's evidence block under either spelling (`evidence_location` or `evidence`)."""
    for name in ("evidence_location", "evidence"):
        block = entry.get(name)
        if isinstance(block, dict):
            return block
    return {}


# ── pairing papers ───────────────────────────────────────────────────────────


#: A benchmark filename starts with the study accession, optionally followed by the PMID. Everything
#: after that is the curator's own suffix -- `_Assay_Hailong`, `_assays_AS_v2`, `_assay_AS`,
#: `_assaysAS_v2`, `_assays_AS_v2_edit` -- and carries no meaning here. Matching on the accession
#: rather than on one curator's suffix is what lets every benchmark in the folder be scored.
_BENCH_NAME = re.compile(r"^(SDY\d+)(?:_(\d{7,8}))?")


def discover_pairs(only: str | None = None) -> tuple[list[dict], list[str]]:
    """Pair each benchmark file with its registry directory.

    The PMID is in the filename only where it is needed to disambiguate (SDY1364 and SDY1276 each
    have two papers in the same study); without one, exactly one registry directory must end in
    `_<SDY>` or the pairing is ambiguous.

    Returns `(pairs, skipped)`. A benchmark that cannot be paired is skipped with a reason rather
    than stopping the run: with 31 benchmark files, one unpairable file must not cost the other 30
    papers their score. The caller reports `skipped` so a silent loss of coverage is impossible --
    the failure this replaces was exactly that, a hard exit nobody saw because the glob had already
    hidden 22 of the files from it.
    """
    pairs: list[dict] = []
    skipped: list[str] = []
    paired_registries: dict[Path, str] = {}
    for path in sorted(BENCHMARK_DIR.glob("*.json")):
        matched = _BENCH_NAME.match(path.name)
        if not matched:
            skipped.append(f"{path.name}: filename does not start with an SDY accession")
            continue
        study, pmid = matched.group(1), matched.group(2)
        if only and study.upper() != only.upper():
            continue
        if pmid:
            candidates = [REGISTRY_DIR / f"{pmid}_{study}", REGISTRY_DIR / f"{pmid}_{study}_pdf"]
        else:
            candidates = sorted(d for d in REGISTRY_DIR.iterdir() if d.is_dir()
                                and d.name.endswith((f"_{study}", f"_{study}_pdf")))
        candidates = [d for d in candidates if (d / "assays_benchmark.json").exists()]
        if len(candidates) != 1:
            skipped.append(
                f"{path.name}: expected exactly one registry for {study}"
                f"{f' (pmid {pmid})' if pmid else ''}, found {[d.name for d in candidates]}"
            )
            continue
        registry = candidates[0]
        # Two curators' files for the same paper would each score the same registry and double it in
        # the totals. Score the first and name both, rather than silently inflating recall.
        if registry in paired_registries:
            skipped.append(
                f"{path.name}: {registry.name} is already scored against "
                f"{paired_registries[registry]}; two benchmarks for one paper cannot both count"
            )
            continue
        paired_registries[registry] = path.name
        pairs.append({"study": study, "pmid": registry.name.split("_")[0],
                      "benchmark": path, "registry": registry})
    if only and not pairs:
        raise SystemExit(f"no benchmark file for {only}"
                         + (f" (skipped: {'; '.join(skipped)})" if skipped else ""))
    return pairs, skipped


# ── matching ─────────────────────────────────────────────────────────────────


def match_tier(bench: dict, bench_id: str | None, ours: dict, obi: ObiGraph) -> tuple[str, str | None] | None:
    """Strongest matching tier for one (benchmark row, our row) pair, or None.

    Returns (tier, detail). See TIERS for the order.
    """
    ours_id = ours.get("obi_id")
    relation = obi.relation(bench_id, ours_id)
    if relation == "exact":
        return "obi_exact", None
    if relation:
        return "obi_ancestry", relation

    bench_forms = _surface_forms(bench["name_in_paper"], bench.get("aliases"))
    our_forms = _surface_forms(ours["name_in_paper"], ours.get("aliases"))
    if set(bench_forms) & set(our_forms):
        return "name", None

    for bf in bench_forms:
        for of in our_forms:
            if len(bf) >= 6 and len(of) >= 6 and (bf in of or of in bf):
                return "name_containment", "one name contains the other"

    # Weakest tier: the benchmark quote names our assay. A quote often spans a whole heading or
    # sentence covering several assays, so refuse it when the two sides carry OBI terms that are not
    # related at all — that is a different assay being named in the same sentence.
    if bench_id and ours_id and not obi.relation(bench_id, ours_id):
        return None
    quote = normalize(bench_evidence(bench).get("quote", ""))
    for our_name in _surface_forms(ours["name_in_paper"], None):
        if quote and len(our_name) >= 6 and our_name in quote:
            return "quote", "benchmark quote names our assay"
    return None


def status_for(tier: str, detail: str | None, bench_id: str | None, matches: list[dict], obi: ObiGraph) -> tuple[str, str]:
    """Status + human-readable reason for a benchmark row that found at least one match."""
    if len(matches) > 1:
        names = ", ".join(f"`{m['key']}`" for m in matches)
        detail_reason = status_for(tier, detail, bench_id, matches[:1], obi)[1]
        return "SPLIT", (
            f"one benchmark assay matched {len(matches)} of our entries: {names}"
            + (f" ({detail_reason})" if detail_reason != "same OBI term" else "")
        )

    ours = matches[0]
    ours_id = ours.get("obi_id")
    if tier == "obi_exact":
        return "MATCH", "same OBI term"
    if tier == "obi_ancestry":
        direction = "more specific than" if detail == "ours_narrower" else "broader than"
        return (
            "MATCH_GRANULARITY",
            f"our term {ours_id} {obi.label_of.get(ours_id, '?')} is {direction} "
            f"the benchmark's {bench_id} {obi.label_of.get(bench_id, '?')}",
        )
    # Name/containment tiers: the ontology did not do the pairing, so say why it did not.
    if ours_id is None:
        return "MATCH_OBI_UNMAPPED", "we mapped this assay to no OBI term"
    if bench_id is None:
        return "MATCH_OBI_UNMAPPED", "the benchmark key is not an OBI term, so the mapping cannot be compared"
    return (
        "MATCH_OBI_CONFLICT",
        f"benchmark maps this assay to {bench_id} {obi.label_of.get(bench_id, '?')}; "
        f"we mapped it to {ours_id} {obi.label_of.get(ours_id, '?')}",
    )


def our_row(key: str, entry: dict, obi_entry: dict) -> dict:
    return {
        "key": key,
        "name_in_paper": entry["name_in_paper"],
        "aliases": entry.get("aliases", []),
        "obi_id": obi_entry.get("obi_id"),
        "obi_label": obi_entry.get("obi_label"),
        "source": entry.get("source"),
        "evidence": entry.get("evidence", {}),
    }


def compare_paper(pair: dict, obi: ObiGraph) -> dict:
    bench = json.loads(pair["benchmark"].read_text(encoding="utf-8"))
    ours = json.loads((pair["registry"] / "assays_benchmark.json").read_text(encoding="utf-8"))
    ours_obi = json.loads((pair["registry"] / "assays_OBI.json").read_text(encoding="utf-8"))
    our_rows = {key: our_row(key, entry, ours_obi.get(key, {})) for key, entry in ours.items()}

    rows: list[dict] = []
    claimed: set[str] = set()
    for bench_key, bench_entry in bench.items():
        # The curator's own id first; their key only as a fallback for an entry that carries none.
        bench_id = bench_obi_id(bench_entry) or obi.resolve(bench_key)
        hits: list[tuple[str, str | None, dict]] = []
        for key, row in our_rows.items():
            hit = match_tier(bench_entry, bench_id, row, obi)
            if hit:
                hits.append((hit[0], hit[1], row))

        bench_side = {
            "key": bench_key,
            "obi_id": bench_id,
            "name_in_paper": bench_entry["name_in_paper"],
            "aliases": bench_entry.get("aliases", []),
            "evidence_location": bench_evidence(bench_entry),
        }
        if not hits:
            rows.append({
                "status": "MISSED",
                "tier": None,
                "reason": "no entry of ours matches this benchmark assay",
                "benchmark": bench_side,
                "ours": [],
            })
            continue

        tier = min((h[0] for h in hits), key=TIERS.index)
        best = [h for h in hits if h[0] == tier]
        detail = best[0][1]
        matches = [row for _, _, row in best]
        claimed |= {row["key"] for row in matches}
        status, reason = status_for(tier, detail, bench_id, matches, obi)
        rows.append({"status": status, "tier": tier, "reason": reason, "benchmark": bench_side, "ours": matches})

    # An entry of ours left over that carries the same OBI term as one already paired is the same
    # assay written up twice (a wild-type and a variant run, a surface and an intracellular panel),
    # not a find the benchmark lacks. Fold it into that row so it reads as a split, not an extra.
    matched_by_obi = {
        row["ours"][0]["obi_id"]: row
        for row in rows
        if row["status"] in MATCHED_STATUSES and row["ours"] and row["ours"][0]["obi_id"]
    }
    for key, row in our_rows.items():
        target = matched_by_obi.get(row["obi_id"]) if key not in claimed and row["obi_id"] else None
        if target:
            target["ours"].append(row)
            claimed.add(key)
            target["status"], target["reason"] = status_for(
                target["tier"], None, target["benchmark"]["obi_id"], target["ours"], obi
            )

    for key, row in our_rows.items():
        if key not in claimed:
            rows.append({
                "status": "EXTRA",
                "tier": None,
                "reason": "found in the paper, absent from the benchmark",
                "benchmark": None,
                "ours": [row],
            })

    matched = sum(1 for r in rows if r["status"] in MATCHED_STATUSES)
    missed = sum(1 for r in rows if r["status"] == "MISSED")
    extra = sum(1 for r in rows if r["status"] == "EXTRA")
    return {
        "study": pair["study"],
        "pmid": pair["pmid"],
        "benchmark_file": str(pair["benchmark"].relative_to(REPO_ROOT)),
        "registry_dir": str(pair["registry"].relative_to(REPO_ROOT)),
        "metrics": {
            "benchmark_total": len(bench),
            "ours_total": len(ours),
            "matched": matched,
            "missed": missed,
            "extra": extra,
            "recall": round(matched / len(bench), 4) if bench else None,
        },
        "rows": rows,
    }


# ── reporting ────────────────────────────────────────────────────────────────


def _clip(text: str, cap: int = QUOTE_CAP) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= cap else text[:cap].rstrip() + " …"


def _evidence_block(row: dict, show_key: bool = True) -> list[str]:
    """The paper evidence a reviewer needs to adjudicate one conflict row."""
    out: list[str] = []
    if row["status"] == "MISSED":
        loc = row["benchmark"]["evidence_location"]
        out.append(f"- benchmark evidence — section: {loc.get('section', '?')}")
        out.append(f"  > {_clip(loc.get('quote', ''))}")
        return out
    for ours in row["ours"]:
        ev = ours.get("evidence", {})
        sids = ", ".join(ev.get("sentence_ids", []) or [])
        prefix = f"- `{ours['key']}` — " if show_key else "- "
        out.append(
            f"{prefix}source: {ours.get('source') or '?'} | "
            f"section: {ev.get('section', '?')}" + (f" | sentences: {sids}" if sids else "")
        )
        out.append(f"  > {_clip(ev.get('quote', ''))}")
    return out


def render_markdown(report: dict) -> str:
    t = report["totals"]
    lines = [
        "# Assay extraction vs. curated benchmark",
        "",
        f"{t['papers']} papers · {t['benchmark_total']} benchmark assays · {t['ours_total']} extracted assays",
        "",
        "The benchmark is a **recall reference, not an exhaustive list** — on some papers it records one "
        "assay where the paper describes nine. Recall is therefore the headline metric and no precision "
        "figure is given; our unmatched assays are listed as EXTRA with their paper evidence to be judged "
        "individually.",
        "",
        "## Totals",
        "",
        "| Study | PMID | Benchmark | Ours | Matched | Missed | Extra | Recall |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for paper in report["papers"]:
        m = paper["metrics"]
        lines.append(
            f"| {paper['study']} | {paper['pmid']} | {m['benchmark_total']} | {m['ours_total']} | "
            f"{m['matched']} | {m['missed']} | {m['extra']} | {m['recall']:.0%} |"
        )
    lines.append(
        f"| **All** | | **{t['benchmark_total']}** | **{t['ours_total']}** | **{t['matched']}** | "
        f"**{t['missed']}** | **{t['extra']}** | **{t['recall']:.0%}** |"
    )

    lines += ["", "## Status legend", "",
              "| Status | Meaning |", "|---|---|",
              "| MATCH | paired on the same OBI term |",
              "| MATCH_GRANULARITY | paired through the OBI is_a hierarchy — same assay, different specificity |",
              "| MATCH_OBI_CONFLICT | paired by name, but the two sides carry disagreeing OBI terms |",
              "| MATCH_OBI_UNMAPPED | paired by name, but one side carries no OBI term at all |",
              "| SPLIT | one benchmark assay matched several of our entries |",
              "| MISSED | benchmark assay we did not find |",
              "| EXTRA | assay we found that the benchmark does not list |"]

    for paper in report["papers"]:
        m = paper["metrics"]
        lines += ["", "---", "",
                  f"## {paper['study']} ({paper['pmid']}) — {m['benchmark_total']} benchmark / {m['ours_total']} ours",
                  "", f"`{paper['registry_dir']}/assays_benchmark.json`", "",
                  "| Benchmark assay | Our assay | Tier | Status |", "|---|---|---|---|"]
        for row in paper["rows"]:
            bench = f"`{row['benchmark']['key']}`" if row["benchmark"] else "—"
            ours = ", ".join(f"`{o['key']}`" for o in row["ours"]) or "—"
            lines.append(f"| {bench} | {ours} | {row['tier'] or '—'} | **{row['status']}** |")

        conflicts = [r for r in paper["rows"] if r["status"] in CONFLICT_STATUSES]
        extras = [r for r in paper["rows"] if r["status"] == "EXTRA"]
        if conflicts:
            lines += ["", f"### Conflicts ({len(conflicts)})", ""]
            for row in conflicts:
                title = row["benchmark"]["key"] if row["benchmark"] else row["ours"][0]["key"]
                lines.append(f"**{row['status']} — `{title}`**  ")
                lines.append(f"{row['reason']}")
                lines.append("")
                lines += _evidence_block(row)
                lines.append("")
        if extras:
            lines += ["", f"### Extra assays not in the benchmark ({len(extras)})", ""]
            for row in extras:
                ours = row["ours"][0]
                obi = f"{ours['obi_id']} {ours['obi_label']}" if ours["obi_id"] else "no OBI term"
                lines.append(f"**`{ours['key']}`** — {obi}  ")
                lines += _evidence_block(row, show_key=False)
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _report_coverage(scored: int, available: int, skipped: list[str], stream=sys.stdout) -> None:
    """Say how many benchmark files were scored out of how many exist, and why any were not.

    Printed before the metrics on purpose: a recall figure over a subset of the benchmark is the one
    number that must never be read without knowing it is a subset.
    """
    print(f"scored {scored}/{available} benchmark files", file=stream)
    for reason in skipped:
        print(f"  SKIPPED  {reason}", file=stream)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="Restrict to one study accession, e.g. SDY2189")
    parser.add_argument("--stdout", action="store_true", help="Print the Markdown report instead of writing files")
    args = parser.parse_args()

    obi = ObiGraph()
    pairs, skipped = discover_pairs(args.only)
    papers = [compare_paper(pair, obi) for pair in pairs]
    benchmark_files = len(list(BENCHMARK_DIR.glob("*.json")))
    totals = {
        "papers": len(papers),
        "benchmark_files": benchmark_files,
        "skipped": skipped,
        "benchmark_total": sum(p["metrics"]["benchmark_total"] for p in papers),
        "ours_total": sum(p["metrics"]["ours_total"] for p in papers),
        "matched": sum(p["metrics"]["matched"] for p in papers),
        "missed": sum(p["metrics"]["missed"] for p in papers),
        "extra": sum(p["metrics"]["extra"] for p in papers),
    }
    totals["recall"] = round(totals["matched"] / totals["benchmark_total"], 4) if totals["benchmark_total"] else None
    report = {
        "generated_from": {
            "benchmark_dir": str(BENCHMARK_DIR.relative_to(REPO_ROOT)),
            "registry_dir": str(REGISTRY_DIR.relative_to(REPO_ROOT)),
            "obi_index": f"{OBO_PATH.relative_to(REPO_ROOT)} (assay branch)",
        },
        "totals": totals,
        "papers": papers,
    }

    markdown = render_markdown(report)
    if args.stdout:
        _report_coverage(len(papers), benchmark_files, skipped, stream=sys.stderr)
        print(markdown)
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "comparison.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT_DIR / "comparison.md").write_text(markdown, encoding="utf-8")

    _report_coverage(len(papers), benchmark_files, skipped)
    print(f"{totals['papers']} papers | benchmark {totals['benchmark_total']} | ours {totals['ours_total']}")
    print(f"matched {totals['matched']} | missed {totals['missed']} | extra {totals['extra']} "
          f"| recall {totals['recall']:.1%}")
    for paper in papers:
        m = paper["metrics"]
        flags = sorted({r["status"] for r in paper["rows"] if r["status"] in CONFLICT_STATUSES})
        print(f"  {paper['study']:<8} bench {m['benchmark_total']:>2} ours {m['ours_total']:>2} "
              f"matched {m['matched']:>2} missed {m['missed']} extra {m['extra']:>2}"
              + (f"  [{', '.join(flags)}]" if flags else ""))
    print(f"\nwrote {OUT_DIR.relative_to(REPO_ROOT)}/comparison.json and comparison.md")


if __name__ == "__main__":
    main()
