#!/usr/bin/env python3
"""Compare the agent's assay registries against the curated assay benchmark and render a review page.

`data/benchmark_assay/benchmark_assay_v4/` is the curators' current pass. Three things differ from
the run that `compare_assay_benchmark.py` scores:

* Pairing is one-to-one, strongest pair first. Several assay names a curator listed separately map
  to the same OBI term (four flow-cytometry panels in SDY1289, ICS beside flow cytometry in
  SDY1640), and the agent's registry is keyed by OBI label; a curated row the agent gave no entry of
  its own reads as MISSED. An earlier version folded such leftover rows onto the paired one, which
  hid every case where round 5 had merged two different measurements into one entry. A second
  agent entry on the very same term as a paired row is a SPLIT row of its own, counted against
  precision like an EXTRA.
* An agent entry the verifier's identity judge did not support carries `identity_review`. It is
  never taken as a SPLIT partner; left unpaired it is UNSUPPORTED_EXTRA, and `precision` leaves it
  out of the denominator (`precision_v1` keeps it in). Paired, it keeps its status, flagged
  `reviewed`.
* Some benchmark files are hand-edited JSON with trailing commas or an unclosed brace. They are
  repaired in memory, never on disk, and every repair is reported.

Matching tiers and statuses are the ones in `compare_assay_benchmark.py`, imported, not copied,
except that SPLIT is not a match here. No LLM call.

Usage:
    ./.venv/bin/python scripts/compare_assay_benchmark_v2.py [--only SDY1289] [--registry-dir DIR] [--out-stem STEM]

Reads  : data/benchmark_assay/benchmark_assay_v4/*.json
         data/31paper_assays/assay_result_v1/<pmid>_<SDY>/{assays_benchmark,assays_OBI}.json
         data/OBI/obi.obo
Writes : data/benchmark_assay/comparison/benchmark_vs_agent.{json,html}
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_assay_benchmark import (  # noqa: E402
    MATCHED_STATUSES,
    TIERS,
    ObiGraph,
    _surface_forms,
    bench_evidence,
    bench_obi_id,
    match_tier,
    normalize,
    our_row,
    status_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_assay" / "benchmark_assay_v4"
REGISTRY_DIR = REPO_ROOT / "data" / "31paper_assays" / "assay_result_v1"
OUT_DIR = REPO_ROOT / "data" / "benchmark_assay" / "comparison"
OUT_STEM = "benchmark_vs_agent"

#: The shared set minus SPLIT: here a SPLIT is the surplus agent entry, not the benchmark row.
MATCHED = MATCHED_STATUSES - {"SPLIT"}

#: v2 filenames drop the PMID for the two studies that hold two papers each. Which paper each file
#: covers was read off its content against the v1 files, which did carry the PMID.
PINNED_PMIDS = {
    "SDY1276_1_assays_AS_v2.json": "21357945",
    "SDY1276_2_assays_AS_v2.json": "23878721",
    "SDY1364_Assay_Hailong.json": "23266342",
    "SDY1364_2_assays_AS_v2.json": "23844129",
}

_STUDY = re.compile(r"^(SDY\d+)")


def _rel(path: Path) -> str:
    """Repo-relative when the path is inside the repo, else absolute: `--registry-dir` may point anywhere."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ── reading hand-edited JSON ─────────────────────────────────────────────────


def _strip_trailing_commas(text: str) -> str:
    """Drop a comma that directly precedes `}` or `]`, outside string literals."""
    out: list[str] = []
    in_str = escape = False
    for i, ch in enumerate(text):
        if in_str:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == ",":
            rest = text[i + 1:].lstrip()
            if rest[:1] in ("}", "]"):
                continue
        out.append(ch)
    return "".join(out)


def _close_open_brackets(text: str) -> str:
    """Append whatever `}`/`]` are still open at the end of the text, innermost first."""
    stack: list[str] = []
    in_str = escape = False
    for ch in text:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    return text.rstrip() + "\n" + "".join(reversed(stack))


def load_lenient(path: Path) -> tuple[dict | None, str | None, str | None]:
    """(data, repair, error). `repair` names what was fixed in memory; the file is left untouched."""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text), None, None
    except json.JSONDecodeError as first:
        original = f"{first.msg} at line {first.lineno} col {first.colno}"
    repairs = [
        ("removed trailing commas", _strip_trailing_commas),
        ("closed unbalanced braces", _close_open_brackets),
        ("removed trailing commas + closed unbalanced braces",
         lambda t: _close_open_brackets(_strip_trailing_commas(t))),
    ]
    for label, fix in repairs:
        try:
            data = json.loads(fix(text))
        except json.JSONDecodeError:
            continue
        data, hoisted = _hoist_nested_entries(data)
        if hoisted:
            label += f"; un-nested {len(hoisted)} entries swallowed by an unclosed one ({', '.join(hoisted)})"
        return data, f"{label} (was: {original})", None
    return None, None, original


def _hoist_nested_entries(data: dict) -> tuple[dict, list[str]]:
    """Lift assay entries that a mid-file missing `}` left nested inside the previous entry.

    Closing the braces at the end of the file makes it parse, but everything after the unclosed
    entry then sits inside it. An assay entry is recognisable by its `name_in_paper` field.
    """
    out: dict = {}
    hoisted: list[str] = []
    for key, entry in data.items():
        if not isinstance(entry, dict):
            out[key] = entry
            continue
        nested = {k: v for k, v in entry.items() if isinstance(v, dict) and "name_in_paper" in v}
        out[key] = {k: v for k, v in entry.items() if k not in nested}
        for k, v in nested.items():
            out[k] = v
            hoisted.append(k)
    return out, hoisted


# ── preparing benchmark rows ─────────────────────────────────────────────────


def _names(value) -> list[str]:
    return [v for v in (value if isinstance(value, list) else [value]) if isinstance(v, str) and v]


def prepare_benchmark(bench: dict, obi: ObiGraph) -> dict:
    """One row per curated entry, carrying its OBI id, its quote and `merged_from: [key]`.

    Nothing is merged, here or later. Merging same-OBI entries before matching erased real assays:
    curators put CFSE labeling (SDY1289) and the NK-mediated ADCC assay (SDY1294) under the generic
    `flow cytometry assay`, so both vanished into immunophenotyping and the agent's own CFSE and
    ADCC entries scored as EXTRA. Folding the leftovers after matching hid the opposite error, an
    agent entry that covers two curated rows, so every curated row now scores on its own.
    """
    return {key: {**entry, "obi_id": bench_obi_id(entry) or obi.resolve(key), "merged_from": [key],
                  "quotes": [bench_evidence(entry)]}
            for key, entry in bench.items()}


# ── pairing papers ───────────────────────────────────────────────────────────


def discover_pairs(only: str | None = None, benchmark_dir: Path = BENCHMARK_DIR,
                   registry_dir: Path = REGISTRY_DIR) -> tuple[list[dict], list[str]]:
    registries = sorted(d for d in registry_dir.iterdir()
                        if d.is_dir() and (d / "assays_benchmark.json").exists())
    pairs: list[dict] = []
    skipped: list[str] = []
    for path in sorted(benchmark_dir.glob("*.json")):
        m = _STUDY.match(path.name)
        if not m:
            skipped.append(f"{path.name}: filename does not start with an SDY accession")
            continue
        study = m.group(1)
        if only and study.upper() != only.upper():
            continue
        pmid = PINNED_PMIDS.get(path.name)
        cands = [d for d in registries if re.search(rf"_{study}(_pdf)?$", d.name)
                 and (pmid is None or d.name.startswith(f"{pmid}_"))]
        if len(cands) != 1:
            skipped.append(f"{path.name}: expected one registry for {study}, found {[d.name for d in cands]}")
            continue
        pairs.append({"study": study, "pmid": cands[0].name.split("_")[0],
                      "benchmark": path, "registry": cands[0]})
    return pairs, skipped


# ── comparing one paper ──────────────────────────────────────────────────────


#: The shared tiers, then two weaker ones only this script uses. `short_name` lets an acronym the
#: shared containment rule is too short for ("CFU") match as a whole word. `evidence` pairs two
#: entries that quote the same sentence even when their OBI terms are unrelated -- the shared quote
#: tier refuses that, which turned a real disagreement over the term into a MISSED plus an EXTRA.
PAIR_TIERS = TIERS + ["short_name", "evidence"]

#: Only a second agent entry on the very same term is a split of one assay. A child term is not:
#: SDY984's BD CBA (`antigen detection by cytometric bead array assay`) is a separate assay from
#: the Luminex panel the benchmark lists under `cytometric bead array assay`, and stays EXTRA.
_SPLIT_TIERS = ("obi_exact",)

_SHORT = (3, 5)
_SENTENCE_MIN_WORDS = 8
_SENTENCE_OVERLAP = 0.8

_EXTRA_TIER_REASON = {
    "short_name": "paired by a short name",
    "evidence": "paired by a shared evidence sentence",
}


def _words(text: str) -> list[str]:
    return normalize(text or "").split()


def _bench_quote(bench: dict) -> str:
    return bench_evidence(bench).get("quote", "") or ""


def _our_quote(ours: dict) -> str:
    return (ours.get("evidence") or {}).get("quote", "") or ""


def _short_word_hit(forms: list[str], texts: list[str]) -> bool:
    """A 3-5 character form that appears as a whole word in any of `texts`."""
    words = [set(t.split()) for t in texts if t]
    return any(_SHORT[0] <= len(f) <= _SHORT[1] and " " not in f and any(f in w for w in words)
               for f in forms)


def _shared_sentence(a: str, b: str) -> bool:
    """Whether two quotes come from the same sentence: most of the shorter one is in the longer."""
    wa, wb = _words(a), _words(b)
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if len(short) < _SENTENCE_MIN_WORDS:
        return False
    pool = set(long_)
    return sum(w in pool for w in short) / len(short) >= _SENTENCE_OVERLAP


def pair_signals(bench: dict, ours: dict) -> list[str]:
    """Every independent piece of evidence, besides the OBI terms, that the two are one assay."""
    bench_forms = _surface_forms(bench["name_in_paper"], bench.get("aliases"))
    our_forms = _surface_forms(ours["name_in_paper"], ours.get("aliases"))
    bench_q, our_q = normalize(_bench_quote(bench)), normalize(_our_quote(ours))
    signals = []
    if set(bench_forms) & set(our_forms):
        signals.append("same name")
    if any(len(b) >= 6 and len(o) >= 6 and (b in o or o in b)
           for b in bench_forms for o in our_forms):
        signals.append("name containment")
    if (_short_word_hit(bench_forms, our_forms + [our_q])
            or _short_word_hit(our_forms, bench_forms + [bench_q])):
        signals.append("short name")
    if any(len(o) >= 6 and o in bench_q for o in our_forms) or \
            any(len(b) >= 6 and b in our_q for b in bench_forms):
        signals.append("quote names the other side")
    if _shared_sentence(_bench_quote(bench), _our_quote(ours)):
        signals.append("shared evidence sentence")
    return signals


def pair_score(bench: dict, bench_id: str | None, ours: dict, obi: ObiGraph) -> tuple[str, str | None, list[str]] | None:
    """(tier, detail, signals) for one (benchmark row, agent entry) pair, or None.

    The tier is the shared `match_tier` when it finds one, else one of the two weak tiers. The
    signals are what ranks two pairs on the same tier, so an ancestry match that also shares the
    quote and the name beats one that only shares an ancestor.
    """
    signals = pair_signals(bench, ours)
    hit = match_tier(bench, bench_id, ours, obi)
    if hit:
        return hit[0], hit[1], signals
    if "short name" in signals:
        return "short_name", None, signals
    if "shared evidence sentence" in signals:
        return "evidence", None, signals
    return None


def compare_paper(bench: dict, registry: Path, obi: ObiGraph) -> dict:
    """Score one paper, pairing each benchmark row with at most one agent entry.

    Every pair is scored, then pairs are taken strongest first -- by tier, then by how many other
    signals agree -- and each side is used once. The shared algorithm let every benchmark row
    claim every agent entry on its best tier, so one entry could be counted under two rows while
    its real partner showed as EXTRA. An agent entry left over on the same OBI term as an
    already-paired row is a SPLIT row of its own, pointing at that row; anything else left over is
    EXTRA, or UNSUPPORTED_EXTRA when the verifier's identity judge had already objected to it. A
    reviewed entry is never a SPLIT partner either: the registry says it may not be an assay at
    all, so it is not evidence that the agent split one.
    """
    ours = json.loads((registry / "assays_benchmark.json").read_text(encoding="utf-8"))
    ours_obi = json.loads((registry / "assays_OBI.json").read_text(encoding="utf-8"))
    our_rows = {key: {**our_row(key, entry, ours_obi.get(key, {})),
                      "generate_claim": entry.get("generate_claim"),
                      "identity_review": entry.get("identity_review")}
                for key, entry in ours.items()}
    bench_keys, our_keys = list(bench), list(our_rows)

    scored = []
    for bi, bench_key in enumerate(bench_keys):
        for oi, our_key in enumerate(our_keys):
            hit = pair_score(bench[bench_key], bench[bench_key]["obi_id"], our_rows[our_key], obi)
            if hit:
                # A name both sides use outranks a shared term: the curator's "CFSE labeling" is
                # filed under `flow cytometry assay`, and would otherwise take the agent's flow
                # cytometry entry on the term before reaching the agent's own "CFSE labeling".
                scored.append(("same name" not in hit[2], PAIR_TIERS.index(hit[0]), -len(hit[2]),
                               bi, oi, hit))
    scored.sort(key=lambda t: t[:5])

    assigned: dict[str, tuple[str, tuple]] = {}
    used: set[str] = set()
    for _, _, _, bi, oi, hit in scored:
        bench_key, our_key = bench_keys[bi], our_keys[oi]
        if bench_key in assigned or our_key in used:
            continue
        assigned[bench_key] = (our_key, hit)
        used.add(our_key)
    splits: dict[str, list[tuple[str, tuple]]] = {}
    for _, _, _, bi, oi, hit in scored:
        bench_key, our_key = bench_keys[bi], our_keys[oi]
        if (our_key in used or bench_key not in assigned or hit[0] not in _SPLIT_TIERS
                or our_rows[our_key]["identity_review"]):
            continue
        splits.setdefault(bench_key, []).append((our_key, hit))
        used.add(our_key)

    rows: list[dict] = []
    for bench_key, entry in bench.items():
        bench_id = entry["obi_id"]
        bench_side = {
            "key": bench_key,
            "obi_id": bench_id,
            "obi_label": obi.label_of.get(bench_id) if bench_id else None,
            "name_in_paper": entry["name_in_paper"],
            "aliases": entry.get("aliases", []),
            "merged_from": entry["merged_from"],
            "generate_claim": entry.get("generate_claim"),
            "quotes": entry["quotes"],
        }
        if bench_key not in assigned:
            rows.append({"status": "MISSED", "tier": None, "signals": [],
                         "reason": "no agent entry matches this benchmark assay",
                         "benchmark": bench_side, "ours": []})
            continue
        our_key, (tier, detail, signals) = assigned[bench_key]
        match = our_rows[our_key]
        status, reason = status_for(tier, detail, bench_id, [match], obi)
        if tier in _EXTRA_TIER_REASON:
            reason = f"{_EXTRA_TIER_REASON[tier]}; {reason}"
        row = {"status": status, "tier": tier, "signals": signals, "reason": reason,
               "benchmark": bench_side, "ours": [match]}
        if match["identity_review"]:
            row["reviewed"] = True
        rows.append(row)
        # Each surplus entry on the paired term sits right under its host, with the pointer back.
        for split_key, (split_tier, _, split_signals) in splits.get(bench_key, []):
            rows.append({"status": "SPLIT", "tier": split_tier, "signals": split_signals,
                         "reason": f"a second agent entry on the same OBI term as `{our_key}`, "
                                   f"which is already paired with this benchmark assay",
                         "benchmark": None, "split_of": bench_key, "ours": [our_rows[split_key]]})

    for key, row in our_rows.items():
        if key in used:
            continue
        review = row["identity_review"]
        if review:
            rows.append({"status": "UNSUPPORTED_EXTRA", "tier": None, "signals": [],
                         "reason": f"agent found it in the paper, but the verifier did not support its "
                                   f"identity ({review.get('verdict')}: {review.get('reason')}); "
                                   f"the benchmark does not list it",
                         "benchmark": None, "ours": [row]})
        else:
            rows.append({"status": "EXTRA", "tier": None, "signals": [],
                         "reason": "agent found it in the paper; the benchmark does not list it",
                         "benchmark": None, "ours": [row]})

    # Invariants: matched + missed = benchmark_total; matched + extra + split + unsupported_extra
    # = ours_total. Every benchmark row is one of the first two, every agent entry one of the rest.
    matched = sum(r["status"] in MATCHED for r in rows)
    return {
        "metrics": {
            "benchmark_total": len(bench),
            "ours_total": len(ours),
            "matched": matched,
            "exact": sum(r["status"] == "MATCH" for r in rows),
            "missed": sum(r["status"] == "MISSED" for r in rows),
            "extra": sum(r["status"] == "EXTRA" for r in rows),
            "split": sum(r["status"] == "SPLIT" for r in rows),
            "unsupported_extra": sum(r["status"] == "UNSUPPORTED_EXTRA" for r in rows),
            "recall": round(matched / len(bench), 4) if bench else None,
        },
        "merged_groups": [],
        "rows": rows,
    }


# ── HTML ─────────────────────────────────────────────────────────────────────

STATUS_INFO = {
    "MATCH": ("match", "Same OBI term on both sides"),
    "MATCH_GRANULARITY": ("gran", "Same assay; one OBI term is a parent/child of the other"),
    "MATCH_OBI_CONFLICT": ("conflict", "Paired by name, but the two sides chose different OBI terms"),
    "MATCH_OBI_UNMAPPED": ("unmapped", "Paired by name, but one side has no OBI term"),
    "SPLIT": ("split", "A second agent entry on the OBI term of an already-paired benchmark assay (counts against precision)"),
    "MISSED": ("missed", "In the benchmark, not found by the agent"),
    "EXTRA": ("extra", "Found by the agent, not in the benchmark"),
    "UNSUPPORTED_EXTRA": ("unsupp", "Found by the agent, not in the benchmark, and the verifier did not support its identity (left out of precision)"),
}

e = html.escape


def _obi(obi_id: str | None, label: str | None) -> str:
    if not obi_id:
        return '<span class="noobi">no OBI term</span>'
    return f'<span class="obi"><code>{e(obi_id)}</code> {e(label or "?")}</span>'


def _claim(v) -> str:
    return {True: "claim ✓", False: "claim ✗"}.get(v, "claim ?")


def _bench_cell(b: dict | None) -> str:
    if not b:
        return '<span class="dash">—</span>'
    parts = [f'<div class="key">{e(b["key"])}</div>', _obi(b["obi_id"], b["obi_label"])]
    if len(b["merged_from"]) > 1:
        chips = "".join(f'<span class="chip">{e(n)}</span>' for n in b["merged_from"])
        parts.append(f'<div class="merged"><span class="tag">merged {len(b["merged_from"])}</span>{chips}</div>')
    else:
        names = [n for n in _names(b["name_in_paper"]) if n != b["key"]]
        if names:
            parts.append(f'<div class="sub">paper: {e("; ".join(names))}</div>')
    if b["aliases"]:
        parts.append(f'<div class="sub">aliases: {e("; ".join(b["aliases"]))}</div>')
    parts.append(f'<div class="sub">{_claim(b.get("generate_claim"))}</div>')
    return "".join(parts)


def _ours_cell(ours: list[dict]) -> str:
    if not ours:
        return '<span class="dash">—</span>'
    blocks = []
    for o in ours:
        parts = [f'<div class="key">{e(o["key"])}</div>', _obi(o["obi_id"], o["obi_label"])]
        review = o.get("identity_review")
        if review:
            parts.append(f'<span class="tag review" title="{e(str(review.get("reason") or ""))}">'
                         f'identity {e(str(review.get("verdict") or "reviewed"))}</span>')
        names = [n for n in _names(o["name_in_paper"]) if n != o["key"]]
        if names:
            parts.append(f'<div class="sub">paper: {e("; ".join(names))}</div>')
        if o.get("aliases"):
            parts.append(f'<div class="sub">aliases: {e("; ".join(o["aliases"]))}</div>')
        parts.append(f'<div class="sub">{_claim(o.get("generate_claim"))} · source: {e(o.get("source") or "?")}</div>')
        blocks.append(f'<div class="ours-one">{"".join(parts)}</div>')
    return "".join(blocks)


def _evidence_cell(row: dict) -> str:
    items = []
    if row["benchmark"]:
        for q in row["benchmark"]["quotes"]:
            src = f' ({e(q["from"])})' if q.get("from") else ""
            items.append(f'<div class="q"><b>Benchmark{src}</b> · {e(q.get("section") or "?")}'
                         f'<blockquote>{e(q.get("quote") or "")}</blockquote></div>')
    for o in row["ours"]:
        ev = o.get("evidence") or {}
        sids = ", ".join(ev.get("sentence_ids") or [])
        items.append(f'<div class="q"><b>Agent ({e(o["key"])})</b> · {e(ev.get("section") or "?")}'
                     + (f" · {e(sids)}" if sids else "")
                     + f'<blockquote>{e(ev.get("quote") or "")}</blockquote></div>')
    return f'<details><summary>evidence ({len(items)})</summary>{"".join(items)}</details>'


def overall_totals(papers: list[dict]) -> dict:
    """Corpus-wide counts and rates over every scored paper.

    `status_counts` counts comparison rows by status, so MATCH* and MISSED are benchmark rows and
    SPLIT, EXTRA and UNSUPPORTED_EXTRA are agent rows. `precision` is matched / the agent assays
    the registry itself stands behind (ours_total minus unsupported_extra); `precision_v1` is
    matched / every agent assay, the figure before the verifier's verdict was read. `f1` and
    `f1_v1` follow each. `obi_exact_rate` is the share of matched assays that landed on the
    identical OBI term, and `obi_recall` the share of benchmark assays the agent gave that
    identical term. A zero denominator gives 0.0.
    """
    def ratio(num: float, den: float) -> float:
        return num / den if den else 0.0

    totals = {
        **{k: sum(p["metrics"].get(k, 0) for p in papers)
           for k in ("benchmark_total", "ours_total", "matched", "exact", "missed", "extra",
                     "split", "unsupported_extra")},
        "status_counts": {s: sum(r["status"] == s for p in papers for r in p["rows"])
                          for s in STATUS_INFO},
    }
    totals["recall"] = ratio(totals["matched"], totals["benchmark_total"])
    totals["precision"] = ratio(totals["matched"], totals["ours_total"] - totals["unsupported_extra"])
    totals["precision_v1"] = ratio(totals["matched"], totals["ours_total"])
    totals["f1"] = ratio(2 * totals["precision"] * totals["recall"],
                         totals["precision"] + totals["recall"])
    totals["f1_v1"] = ratio(2 * totals["precision_v1"] * totals["recall"],
                            totals["precision_v1"] + totals["recall"])
    totals["obi_exact_rate"] = ratio(totals["exact"], totals["matched"])
    totals["obi_recall"] = ratio(totals["exact"], totals["benchmark_total"])
    return totals


def render_html(report: dict) -> str:
    t = report["totals"]
    summary_rows = []
    sections = []
    for p in report["papers"]:
        m = p["metrics"]
        anchor = f'{p["study"]}_{p["pmid"]}'
        flags = []
        if p["merged_groups"]:
            flags.append(f'<span class="tag">merged {sum(len(g) for g in p["merged_groups"])}→{len(p["merged_groups"])}</span>')
        if p["repair"]:
            flags.append('<span class="tag warn" title="%s">JSON repaired</span>' % e(p["repair"]))
        counts = {s: sum(r["status"] == s for r in p["rows"]) for s in STATUS_INFO}
        summary_rows.append(
            f'<tr onclick="location.hash=\'{anchor}\'"><td><a href="#{anchor}">{p["study"]}</a></td><td>{p["pmid"]}</td>'
            f'<td class="n">{m["benchmark_total"]}</td><td class="n">{m["ours_total"]}</td>'
            + "".join(f'<td class="n {STATUS_INFO[s][0]}-c">{counts[s] or ""}</td>' for s in STATUS_INFO)
            + f'<td class="n"><b>{m["recall"]:.0%}</b></td><td>{" ".join(flags)}</td></tr>'
        )
        body = []
        for r in p["rows"]:
            cls = STATUS_INFO[r["status"]][0]
            body.append(
                f'<tr class="row" data-status="{r["status"]}">'
                f'<td><span class="badge {cls}">{r["status"].replace("_", " ")}</span>'
                f'<div class="sub">{e(r["tier"] or "")}</div>'
                + (f'<div class="sub">{e("; ".join(r.get("signals") or []))}</div>' if r.get("signals") else "")
                + '</td>'
                f'<td>{_bench_cell(r["benchmark"])}</td><td>{_ours_cell(r["ours"])}</td>'
                f'<td class="reason">{e(r["reason"])}</td><td>{_evidence_cell(r)}</td></tr>'
            )
        note = f'<p class="note warn">Benchmark JSON was invalid; {e(p["repair"])}. File not modified.</p>' if p["repair"] else ""
        sections.append(
            f'<section class="paper" id="{anchor}"><h2>{p["study"]} <span class="pmid">PMID {p["pmid"]}</span></h2>'
            f'<p class="meta">benchmark <b>{m["benchmark_total"]}</b> · agent <b>{m["ours_total"]}</b> · '
            f'matched <b>{m["matched"]}</b> (exact OBI {m["exact"]}) · missed <b>{m["missed"]}</b> · '
            f'extra <b>{m["extra"]}</b> · split <b>{m["split"]}</b> · unsupported extra <b>{m["unsupported_extra"]}</b> · '
            f'recall <b>{m["recall"]:.0%}</b></p>'
            f'<p class="files"><code>{e(p["benchmark_file"])}</code> vs <code>{e(p["registry_dir"])}</code></p>{note}'
            f'<table class="cmp"><thead><tr><th>Status</th><th>Benchmark assay</th><th>Agent assay</th>'
            f'<th>Why</th><th>Evidence</th></tr></thead><tbody>{"".join(body)}</tbody></table></section>'
        )

    legend = "".join(f'<label><input type="checkbox" class="flt" value="{s}" {"" if s == "MATCH" else "checked"}>'
                     f'<span class="badge {c}">{s.replace("_", " ")}</span> <span class="sub">{e(d)}</span></label>'
                     for s, (c, d) in STATUS_INFO.items())
    notes = "".join(f"<li>{e(s)}</li>" for s in t["skipped"])
    nobench = ", ".join(t["registries_without_benchmark"]) or "none"
    label = Path(report["benchmark_dir"]).name
    # A report written before status_counts existed is recounted from its rows.
    status_counts = t.get("status_counts") or {
        s: sum(r["status"] == s for p in report["papers"] for r in p["rows"]) for s in STATUS_INFO}
    total_row = (
        f'<tr><td>Total</td><td>{t["papers"]} papers</td>'
        f'<td class="n">{t["benchmark_total"]}</td><td class="n">{t["ours_total"]}</td>'
        + "".join(f'<td class="n {c}-c">{status_counts[s] or ""}</td>' for s, (c, _) in STATUS_INFO.items())
        + f'<td class="n">{t["recall"]:.0%}</td><td></td></tr>'
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assay Benchmark Review</title>
<style>
:root{{--bg:#fbfaf8;--fg:#1f2328;--muted:#6b7280;--card:#fff;--line:#e5e2dc;--code:#f3f1ec;
--match:#1a7f37;--gran:#0969da;--conflict:#bc4c00;--unmapped:#8250df;--split:#9a6700;--missed:#cf222e;--extra:#57606a;--unsupp:#1b7c83}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#16181c;--fg:#e6e6e6;--muted:#9aa0a6;--card:#1e2126;--line:#2e3238;--code:#262a30;
--match:#3fb950;--gran:#58a6ff;--conflict:#f0883e;--unmapped:#bc8cff;--split:#d29922;--missed:#ff7b72;--extra:#8b949e;--unsupp:#39c5bb}}}}
:root[data-theme="dark"]{{--bg:#16181c;--fg:#e6e6e6;--muted:#9aa0a6;--card:#1e2126;--line:#2e3238;--code:#262a30;
--match:#3fb950;--gran:#58a6ff;--conflict:#f0883e;--unmapped:#bc8cff;--split:#d29922;--missed:#ff7b72;--extra:#8b949e;--unsupp:#39c5bb}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
main{{max-width:1500px;margin:0 auto;padding:24px 16px 80px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:18px;margin:0 0 4px}}
.pmid,.sub,.meta,.files{{color:var(--muted);font-size:12px}} .meta{{font-size:13px}}
code{{background:var(--code);padding:0 4px;border-radius:4px;font-size:12px}}
.kpis{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:120px}}
.kpi b{{display:block;font-size:22px}} .kpi span{{color:var(--muted);font-size:12px}}
.toolbar{{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 0;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}}
.toolbar label{{display:inline-flex;gap:4px;align-items:center;cursor:pointer}}
.toolbar label .sub{{display:none}}
.toolbar input[type=search]{{padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);min-width:220px}}
.toolbar button{{padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}}
.wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:8px}}
th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}}
th{{font-size:12px;color:var(--muted);font-weight:600;background:var(--code)}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}
.summary tbody tr{{cursor:pointer}} .summary tbody tr:hover{{background:var(--code)}}
.summary tfoot td{{font-weight:700;border-top:2px solid var(--line);background:var(--code)}}
.paper{{margin-top:36px;scroll-margin-top:60px}}
.cmp td:nth-child(1){{width:120px}} .cmp td:nth-child(2),.cmp td:nth-child(3){{width:26%}} .cmp td:nth-child(4){{width:18%}}
.badge{{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:10px;color:#fff;white-space:nowrap}}
.match{{background:var(--match)}}.gran{{background:var(--gran)}}.conflict{{background:var(--conflict)}}.unmapped{{background:var(--unmapped)}}
.split{{background:var(--split)}}.missed{{background:var(--missed)}}.extra{{background:var(--extra)}}.unsupp{{background:var(--unsupp)}}
.match-c{{color:var(--match)}}.gran-c{{color:var(--gran)}}.conflict-c{{color:var(--conflict)}}.unmapped-c{{color:var(--unmapped)}}
.split-c{{color:var(--split)}}.missed-c{{color:var(--missed)}}.extra-c{{color:var(--extra)}}.unsupp-c{{color:var(--unsupp)}}
tr[data-status=MISSED]{{box-shadow:inset 3px 0 var(--missed)}} tr[data-status=EXTRA]{{box-shadow:inset 3px 0 var(--extra)}}
tr[data-status=MATCH_OBI_CONFLICT]{{box-shadow:inset 3px 0 var(--conflict)}}
tr[data-status=SPLIT]{{box-shadow:inset 3px 0 var(--split)}} tr[data-status=UNSUPPORTED_EXTRA]{{box-shadow:inset 3px 0 var(--unsupp)}}
.key{{font-weight:600}} .obi{{font-size:12px}} .noobi{{font-size:12px;color:var(--missed);font-style:italic}}
.ours-one+.ours-one{{margin-top:8px;padding-top:8px;border-top:1px dashed var(--line)}}
.tag{{display:inline-block;font-size:11px;padding:1px 6px;border-radius:4px;border:1px solid var(--line);margin-right:4px;background:var(--code)}}
.tag.warn,.note.warn{{color:var(--conflict)}}
.tag.review{{color:var(--unsupp);border-color:var(--unsupp);margin-top:4px}}
.merged{{margin-top:4px}} .chip{{display:inline-block;font-size:11px;background:var(--code);border-radius:4px;padding:1px 6px;margin:2px 3px 0 0}}
.dash{{color:var(--muted)}} .reason{{font-size:13px}}
details summary{{cursor:pointer;color:var(--gran);font-size:12px}}
blockquote{{margin:4px 0 8px;padding:4px 8px;border-left:3px solid var(--line);color:var(--muted);font-size:12px;max-height:180px;overflow:auto}}
.q b{{font-size:12px}}
.hidden{{display:none}}
</style></head><body><main>
<h1>Assay benchmark {e(label)} vs. agent</h1>
<p class="sub">Benchmark: <code>{e(report["benchmark_dir"])}</code> · Agent: <code>{e(report["registry_dir"])}</code> ·
every benchmark row pairs with at most one agent entry; a second agent entry on a paired term is a SPLIT row,
and an unpaired entry whose identity the verifier did not support is UNSUPPORTED EXTRA.</p>
<div class="kpis">
<div class="kpi"><b>{t["papers"]}</b><span>papers scored</span></div>
<div class="kpi"><b>{t["benchmark_total"]}</b><span>benchmark assays</span></div>
<div class="kpi"><b>{t["ours_total"]}</b><span>agent assays</span></div>
<div class="kpi"><b>{t["matched"]}</b><span>matched (exact OBI {t["exact"]})</span></div>
<div class="kpi"><b>{t["missed"]}</b><span>missed</span></div>
<div class="kpi"><b>{t["extra"]}</b><span>extra</span></div>
<div class="kpi"><b>{t["split"]}</b><span>split</span></div>
<div class="kpi"><b>{t["unsupported_extra"]}</b><span>unsupported extra</span></div>
<div class="kpi"><b>{t["recall"]:.1%}</b><span>recall</span></div>
<div class="kpi"><b>{t.get("obi_recall", 0):.1%}</b><span>OBI recall (same term as curator)</span></div>
</div>
<details><summary>Status legend &amp; notes</summary>
<ul>{"".join(f'<li><span class="badge {c}">{s.replace("_", " ")}</span> {e(d)}</li>' for s, (c, d) in STATUS_INFO.items())}</ul>
<p>Agent registries with no {e(label)} benchmark (not scored): {e(nobench)}</p>
{f"<p>Skipped benchmark files:</p><ul>{notes}</ul>" if notes else ""}
<p>The benchmark is a recall reference, not an exhaustive list, so EXTRA rows are candidates for curator review rather than errors.</p>
</details>
<h2 style="margin-top:20px">Per paper</h2>
<div class="wrap"><table class="summary"><thead><tr><th>Study</th><th>PMID</th><th>Bench</th><th>Agent</th>
{"".join(f'<th class="{c}-c">{s.replace("MATCH_", "").replace("_", " ")}</th>' for s, (c, _) in STATUS_INFO.items())}
<th>Recall</th><th>Notes</th></tr></thead><tbody>{"".join(summary_rows)}</tbody>
<tfoot>{total_row}</tfoot></table></div>
<div class="toolbar">{legend}
<input type="search" id="q" placeholder="Search assay, OBI, quote…">
<button id="exp">Expand evidence</button><button id="theme">Theme</button>
<span class="sub" id="cnt"></span></div>
{"".join(sections)}
</main>
<script>
const rows=[...document.querySelectorAll('tr.row')];
function apply(){{
  const on=new Set([...document.querySelectorAll('.flt:checked')].map(x=>x.value));
  const q=document.getElementById('q').value.trim().toLowerCase();
  let n=0;
  rows.forEach(r=>{{const ok=on.has(r.dataset.status)&&(!q||r.textContent.toLowerCase().includes(q));r.classList.toggle('hidden',!ok);if(ok)n++;}});
  document.querySelectorAll('section.paper').forEach(s=>s.classList.toggle('hidden',!s.querySelector('tr.row:not(.hidden)')));
  document.getElementById('cnt').textContent=n+' rows shown';
}}
document.querySelectorAll('.flt').forEach(x=>x.addEventListener('change',apply));
document.getElementById('q').addEventListener('input',apply);
let open=false;
document.getElementById('exp').onclick=e=>{{open=!open;document.querySelectorAll('.cmp details').forEach(d=>d.open=open);e.target.textContent=open?'Collapse evidence':'Expand evidence';}};
document.getElementById('theme').onclick=()=>{{const r=document.documentElement;const dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;r.dataset.theme=dark?'light':'dark';}};
apply();
</script></body></html>
"""


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="Restrict to one study accession, e.g. SDY1289")
    parser.add_argument("--benchmark-dir", type=Path, default=BENCHMARK_DIR,
                        help="Folder of curated benchmark JSON files (default: benchmark_assay_v4)")
    parser.add_argument("--registry-dir", type=Path, default=REGISTRY_DIR,
                        help="Folder of <pmid>_<SDY> agent registries (default: assay_result_v1)")
    parser.add_argument("--out-stem", default=OUT_STEM, help="Output filename stem under comparison/")
    args = parser.parse_args()
    benchmark_dir = args.benchmark_dir.resolve()
    registry_dir = args.registry_dir.resolve()
    out_stem = args.out_stem

    obi = ObiGraph()
    pairs, skipped = discover_pairs(args.only, benchmark_dir, registry_dir)
    papers = []
    for pair in pairs:
        raw, repair, error = load_lenient(pair["benchmark"])
        if raw is None:
            skipped.append(f"{pair['benchmark'].name}: unparseable JSON ({error})")
            continue
        result = compare_paper(prepare_benchmark(raw, obi), pair["registry"], obi)
        papers.append({
            "study": pair["study"],
            "pmid": pair["pmid"],
            "benchmark_file": _rel(pair["benchmark"]),
            "registry_dir": _rel(pair["registry"]),
            "repair": repair,
            **result,
        })

    scored = {p["registry_dir"].rsplit("/", 1)[-1] for p in papers}
    all_regs = sorted(d.name for d in registry_dir.iterdir() if d.is_dir())
    totals = {
        "papers": len(papers),
        "skipped": skipped,
        "registries_without_benchmark": [] if args.only else [r for r in all_regs if r not in scored],
        **overall_totals(papers),
    }
    report = {
        "benchmark_dir": _rel(benchmark_dir),
        "registry_dir": _rel(registry_dir),
        "totals": totals,
        "papers": papers,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{out_stem}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT_DIR / f"{out_stem}.html").write_text(render_html(report), encoding="utf-8")

    print(f"scored {len(papers)}/{len(list(benchmark_dir.glob('*.json')))} benchmark files")
    for s in skipped:
        print(f"  SKIPPED  {s}")
    for p in papers:
        if p["repair"]:
            print(f"  REPAIRED {Path(p['benchmark_file']).name}: {p['repair']}")
    print(f"benchmark {totals['benchmark_total']} | agent {totals['ours_total']} | "
          f"matched {totals['matched']} (exact {totals['exact']}) | missed {totals['missed']} | "
          f"extra {totals['extra']} | split {totals['split']} | unsupported extra {totals['unsupported_extra']} | "
          f"recall {totals['recall']:.1%} | precision {totals['precision']:.1%} (v1 {totals['precision_v1']:.1%})")
    for p in papers:
        m = p["metrics"]
        print(f"  {p['study']:<8} {p['pmid']}  bench {m['benchmark_total']:>2} agent {m['ours_total']:>2} "
              f"matched {m['matched']:>2} missed {m['missed']} extra {m['extra']:>2} "
              f"split {m['split']} unsupported {m['unsupported_extra']}")
    print(f"\nwrote {_rel(OUT_DIR / out_stem)}.{{json,html}}")


if __name__ == "__main__":
    main()
