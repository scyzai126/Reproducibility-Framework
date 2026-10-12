#!/usr/bin/env python3
"""Compare the agent's assay registries against the v2 curated benchmark and render a review page.

`data/benchmark_assay/Benchmark_assays_v2/` is the curators' second pass. Two things differ from the
v1 run that `compare_assay_benchmark.py` scores:

* Several assay names a curator listed separately map to the same OBI term (four flow-cytometry
  panels in SDY1289, two ELISPOTs in SDY984). Those are one assay at the ontology level, so they are
  merged into a single benchmark row before matching -- the agent's registry is already keyed by OBI
  label, and scoring four rows against its one would read as three misses.
* Some files are hand-edited JSON with trailing commas or an unclosed brace. They are repaired in
  memory, never on disk, and every repair is reported.

Matching tiers and statuses are the ones in `compare_assay_benchmark.py`, imported, not copied.
No LLM call.

Usage:
    ./.venv/bin/python scripts/compare_assay_benchmark_v2.py [--only SDY1289]

Reads  : data/benchmark_assay/Benchmark_assays_v2/*.json
         data/31paper_assays/assay_result_v1/<pmid>_<SDY>/{assays_benchmark,assays_OBI}.json
         data/OBI/obi.obo
Writes : data/benchmark_assay/comparison/benchmark_v2_vs_agent.{json,html}
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
    bench_evidence,
    bench_obi_id,
    match_tier,
    our_row,
    status_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_assay" / "Benchmark_assays_v2"
REGISTRY_DIR = REPO_ROOT / "data" / "31paper_assays" / "assay_result_v1"
OUT_DIR = REPO_ROOT / "data" / "benchmark_assay" / "comparison"
OUT_STEM = "benchmark_v2_vs_agent"

#: v2 filenames drop the PMID for the two studies that hold two papers each. Which paper each file
#: covers was read off its content against the v1 files, which did carry the PMID.
PINNED_PMIDS = {
    "SDY1276_1_assays_AS_v2.json": "21357945",
    "SDY1276_2_assays_AS_v2.json": "23878721",
    "SDY1364_Assay_Hailong.json": "23266342",
    "SDY1364_2_assays_AS_v2.json": "23844129",
}

_STUDY = re.compile(r"^(SDY\d+)")


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


# ── merging same-OBI benchmark rows ──────────────────────────────────────────


def _names(value) -> list[str]:
    return [v for v in (value if isinstance(value, list) else [value]) if isinstance(v, str) and v]


def merge_by_obi(bench: dict, obi: ObiGraph) -> dict:
    """Fold benchmark entries that share an OBI id into one entry keyed by that OBI label.

    Entries with no OBI id stay as they are: two unmapped names are not known to be one assay.
    A merged entry keeps every name, alias and quote so the name and quote tiers still see them.
    """
    groups: dict[str, list[tuple[str, dict]]] = {}
    order: list[tuple[str, str | None]] = []
    for key, entry in bench.items():
        obi_id = bench_obi_id(entry) or obi.resolve(key)
        if obi_id:
            if obi_id not in groups:
                groups[obi_id] = []
                order.append(("obi", obi_id))
            groups[obi_id].append((key, entry))
        else:
            order.append(("key", key))

    merged: dict[str, dict] = {}
    for kind, ref in order:
        if kind == "key":
            entry = bench[ref]
            merged[ref] = {**entry, "obi_id": None, "merged_from": [ref],
                           "quotes": [bench_evidence(entry)]}
            continue
        members = groups[ref]
        if len(members) == 1:
            key, entry = members[0]
            merged[key] = {**entry, "obi_id": ref, "merged_from": [key],
                           "quotes": [bench_evidence(entry)]}
            continue
        names: list[str] = []
        aliases: list[str] = []
        quotes: list[dict] = []
        for key, entry in members:
            names += [n for n in dict.fromkeys([key, *_names(entry.get("name_in_paper"))]) if n not in names]
            aliases += [a for a in dict.fromkeys(entry.get("aliases") or []) if a not in aliases]
            quotes.append({**bench_evidence(entry), "from": key})
        claims = {entry.get("generate_claim") for _, entry in members}
        merged_key = obi.label_of.get(ref) or members[0][0]
        merged[merged_key] = {
            "name_in_paper": names,
            "aliases": aliases,
            "generate_claim": True if True in claims else (False if False in claims else None),
            "obi_id": ref,
            "merged_from": [key for key, _ in members],
            "quotes": quotes,
            # match_tier's quote tier reads one evidence block; give it every quote at once.
            "evidence_location": {"quote": " ".join(q.get("quote", "") for q in quotes)},
        }
    return merged


# ── pairing papers ───────────────────────────────────────────────────────────


def discover_pairs(only: str | None = None) -> tuple[list[dict], list[str]]:
    registries = sorted(d for d in REGISTRY_DIR.iterdir()
                        if d.is_dir() and (d / "assays_benchmark.json").exists())
    pairs: list[dict] = []
    skipped: list[str] = []
    for path in sorted(BENCHMARK_DIR.glob("*.json")):
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


def compare_paper(bench: dict, registry: Path, obi: ObiGraph) -> dict:
    """Same algorithm as compare_assay_benchmark.compare_paper, over an already-merged benchmark."""
    ours = json.loads((registry / "assays_benchmark.json").read_text(encoding="utf-8"))
    ours_obi = json.loads((registry / "assays_OBI.json").read_text(encoding="utf-8"))
    our_rows = {key: {**our_row(key, entry, ours_obi.get(key, {})),
                      "generate_claim": entry.get("generate_claim")}
                for key, entry in ours.items()}

    rows: list[dict] = []
    claimed: set[str] = set()
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
        hits = []
        for row in our_rows.values():
            hit = match_tier(entry, bench_id, row, obi)
            if hit:
                hits.append((hit[0], hit[1], row))
        if not hits:
            rows.append({"status": "MISSED", "tier": None,
                         "reason": "no agent entry matches this benchmark assay",
                         "benchmark": bench_side, "ours": []})
            continue
        tier = min((h[0] for h in hits), key=TIERS.index)
        best = [h for h in hits if h[0] == tier]
        matches = [row for _, _, row in best]
        claimed |= {row["key"] for row in matches}
        status, reason = status_for(tier, best[0][1], bench_id, matches, obi)
        rows.append({"status": status, "tier": tier, "reason": reason,
                     "benchmark": bench_side, "ours": matches})

    for key, row in our_rows.items():
        if key not in claimed:
            rows.append({"status": "EXTRA", "tier": None,
                         "reason": "agent found it in the paper; the benchmark does not list it",
                         "benchmark": None, "ours": [row]})

    matched = sum(r["status"] in MATCHED_STATUSES for r in rows)
    return {
        "metrics": {
            "benchmark_total": len(bench),
            "ours_total": len(ours),
            "matched": matched,
            "exact": sum(r["status"] == "MATCH" for r in rows),
            "missed": sum(r["status"] == "MISSED" for r in rows),
            "extra": sum(r["status"] == "EXTRA" for r in rows),
            "recall": round(matched / len(bench), 4) if bench else None,
        },
        "rows": rows,
    }


# ── HTML ─────────────────────────────────────────────────────────────────────

STATUS_INFO = {
    "MATCH": ("match", "Same OBI term on both sides"),
    "MATCH_GRANULARITY": ("gran", "Same assay; one OBI term is a parent/child of the other"),
    "MATCH_OBI_CONFLICT": ("conflict", "Paired by name, but the two sides chose different OBI terms"),
    "MATCH_OBI_UNMAPPED": ("unmapped", "Paired by name, but one side has no OBI term"),
    "SPLIT": ("split", "One benchmark assay matched several agent entries"),
    "MISSED": ("missed", "In the benchmark, not found by the agent"),
    "EXTRA": ("extra", "Found by the agent, not in the benchmark"),
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
                f'<div class="sub">{e(r["tier"] or "")}</div></td>'
                f'<td>{_bench_cell(r["benchmark"])}</td><td>{_ours_cell(r["ours"])}</td>'
                f'<td class="reason">{e(r["reason"])}</td><td>{_evidence_cell(r)}</td></tr>'
            )
        note = f'<p class="note warn">Benchmark JSON was invalid; {e(p["repair"])}. File not modified.</p>' if p["repair"] else ""
        sections.append(
            f'<section class="paper" id="{anchor}"><h2>{p["study"]} <span class="pmid">PMID {p["pmid"]}</span></h2>'
            f'<p class="meta">benchmark <b>{m["benchmark_total"]}</b> (after merge) · agent <b>{m["ours_total"]}</b> · '
            f'matched <b>{m["matched"]}</b> (exact OBI {m["exact"]}) · missed <b>{m["missed"]}</b> · '
            f'extra <b>{m["extra"]}</b> · recall <b>{m["recall"]:.0%}</b></p>'
            f'<p class="files"><code>{e(p["benchmark_file"])}</code> vs <code>{e(p["registry_dir"])}</code></p>{note}'
            f'<table class="cmp"><thead><tr><th>Status</th><th>Benchmark assay</th><th>Agent assay</th>'
            f'<th>Why</th><th>Evidence</th></tr></thead><tbody>{"".join(body)}</tbody></table></section>'
        )

    legend = "".join(f'<label><input type="checkbox" class="flt" value="{s}" {"" if s == "MATCH" else "checked"}>'
                     f'<span class="badge {c}">{s.replace("_", " ")}</span> <span class="sub">{e(d)}</span></label>'
                     for s, (c, d) in STATUS_INFO.items())
    notes = "".join(f"<li>{e(s)}</li>" for s in t["skipped"])
    nobench = ", ".join(t["registries_without_benchmark"]) or "none"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assay Benchmark Review</title>
<style>
:root{{--bg:#fbfaf8;--fg:#1f2328;--muted:#6b7280;--card:#fff;--line:#e5e2dc;--code:#f3f1ec;
--match:#1a7f37;--gran:#0969da;--conflict:#bc4c00;--unmapped:#8250df;--split:#9a6700;--missed:#cf222e;--extra:#57606a}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#16181c;--fg:#e6e6e6;--muted:#9aa0a6;--card:#1e2126;--line:#2e3238;--code:#262a30;
--match:#3fb950;--gran:#58a6ff;--conflict:#f0883e;--unmapped:#bc8cff;--split:#d29922;--missed:#ff7b72;--extra:#8b949e}}}}
:root[data-theme="dark"]{{--bg:#16181c;--fg:#e6e6e6;--muted:#9aa0a6;--card:#1e2126;--line:#2e3238;--code:#262a30;
--match:#3fb950;--gran:#58a6ff;--conflict:#f0883e;--unmapped:#bc8cff;--split:#d29922;--missed:#ff7b72;--extra:#8b949e}}
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
.summary tr{{cursor:pointer}} .summary tbody tr:hover{{background:var(--code)}}
.paper{{margin-top:36px;scroll-margin-top:60px}}
.cmp td:nth-child(1){{width:120px}} .cmp td:nth-child(2),.cmp td:nth-child(3){{width:26%}} .cmp td:nth-child(4){{width:18%}}
.badge{{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:10px;color:#fff;white-space:nowrap}}
.match{{background:var(--match)}}.gran{{background:var(--gran)}}.conflict{{background:var(--conflict)}}.unmapped{{background:var(--unmapped)}}
.split{{background:var(--split)}}.missed{{background:var(--missed)}}.extra{{background:var(--extra)}}
.match-c{{color:var(--match)}}.gran-c{{color:var(--gran)}}.conflict-c{{color:var(--conflict)}}.unmapped-c{{color:var(--unmapped)}}
.split-c{{color:var(--split)}}.missed-c{{color:var(--missed)}}.extra-c{{color:var(--extra)}}
tr[data-status=MISSED]{{box-shadow:inset 3px 0 var(--missed)}} tr[data-status=EXTRA]{{box-shadow:inset 3px 0 var(--extra)}}
tr[data-status=MATCH_OBI_CONFLICT]{{box-shadow:inset 3px 0 var(--conflict)}}
.key{{font-weight:600}} .obi{{font-size:12px}} .noobi{{font-size:12px;color:var(--missed);font-style:italic}}
.ours-one+.ours-one{{margin-top:8px;padding-top:8px;border-top:1px dashed var(--line)}}
.tag{{display:inline-block;font-size:11px;padding:1px 6px;border-radius:4px;border:1px solid var(--line);margin-right:4px;background:var(--code)}}
.tag.warn,.note.warn{{color:var(--conflict)}}
.merged{{margin-top:4px}} .chip{{display:inline-block;font-size:11px;background:var(--code);border-radius:4px;padding:1px 6px;margin:2px 3px 0 0}}
.dash{{color:var(--muted)}} .reason{{font-size:13px}}
details summary{{cursor:pointer;color:var(--gran);font-size:12px}}
blockquote{{margin:4px 0 8px;padding:4px 8px;border-left:3px solid var(--line);color:var(--muted);font-size:12px;max-height:180px;overflow:auto}}
.q b{{font-size:12px}}
.hidden{{display:none}}
</style></head><body><main>
<h1>Assay benchmark v2 vs. agent</h1>
<p class="sub">Benchmark: <code>{e(report["benchmark_dir"])}</code> · Agent: <code>{e(report["registry_dir"])}</code> ·
benchmark entries that share an OBI id within a paper are merged into one row before matching.</p>
<div class="kpis">
<div class="kpi"><b>{t["papers"]}</b><span>papers scored</span></div>
<div class="kpi"><b>{t["benchmark_total"]}</b><span>benchmark assays (raw {t["benchmark_raw"]})</span></div>
<div class="kpi"><b>{t["ours_total"]}</b><span>agent assays</span></div>
<div class="kpi"><b>{t["matched"]}</b><span>matched (exact OBI {t["exact"]})</span></div>
<div class="kpi"><b>{t["missed"]}</b><span>missed</span></div>
<div class="kpi"><b>{t["extra"]}</b><span>extra</span></div>
<div class="kpi"><b>{t["recall"]:.1%}</b><span>recall</span></div>
</div>
<details><summary>Status legend &amp; notes</summary>
<ul>{"".join(f'<li><span class="badge {c}">{s.replace("_", " ")}</span> {e(d)}</li>' for s, (c, d) in STATUS_INFO.items())}</ul>
<p>Agent registries with no v2 benchmark (not scored): {e(nobench)}</p>
{f"<p>Skipped benchmark files:</p><ul>{notes}</ul>" if notes else ""}
<p>The benchmark is a recall reference, not an exhaustive list, so EXTRA rows are candidates for curator review rather than errors.</p>
</details>
<h2 style="margin-top:20px">Per paper</h2>
<div class="wrap"><table class="summary"><thead><tr><th>Study</th><th>PMID</th><th>Bench</th><th>Agent</th>
{"".join(f'<th class="{c}-c">{s.replace("MATCH_", "").replace("_", " ")}</th>' for s, (c, _) in STATUS_INFO.items())}
<th>Recall</th><th>Notes</th></tr></thead><tbody>{"".join(summary_rows)}</tbody></table></div>
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
    args = parser.parse_args()

    obi = ObiGraph()
    pairs, skipped = discover_pairs(args.only)
    papers = []
    for pair in pairs:
        raw, repair, error = load_lenient(pair["benchmark"])
        if raw is None:
            skipped.append(f"{pair['benchmark'].name}: unparseable JSON ({error})")
            continue
        bench = merge_by_obi(raw, obi)
        result = compare_paper(bench, pair["registry"], obi)
        papers.append({
            "study": pair["study"],
            "pmid": pair["pmid"],
            "benchmark_file": str(pair["benchmark"].relative_to(REPO_ROOT)),
            "registry_dir": str(pair["registry"].relative_to(REPO_ROOT)),
            "repair": repair,
            "benchmark_raw_total": len(raw),
            "merged_groups": [v["merged_from"] for v in bench.values() if len(v["merged_from"]) > 1],
            **result,
        })

    scored = {p["registry_dir"].rsplit("/", 1)[-1] for p in papers}
    all_regs = sorted(d.name for d in REGISTRY_DIR.iterdir() if d.is_dir())
    totals = {
        "papers": len(papers),
        "skipped": skipped,
        "registries_without_benchmark": [] if args.only else [r for r in all_regs if r not in scored],
        "benchmark_raw": sum(p["benchmark_raw_total"] for p in papers),
        **{k: sum(p["metrics"][k] for p in papers)
           for k in ("benchmark_total", "ours_total", "matched", "exact", "missed", "extra")},
    }
    totals["recall"] = totals["matched"] / totals["benchmark_total"] if totals["benchmark_total"] else 0.0
    report = {
        "benchmark_dir": str(BENCHMARK_DIR.relative_to(REPO_ROOT)),
        "registry_dir": str(REGISTRY_DIR.relative_to(REPO_ROOT)),
        "totals": totals,
        "papers": papers,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{OUT_STEM}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT_DIR / f"{OUT_STEM}.html").write_text(render_html(report), encoding="utf-8")

    print(f"scored {len(papers)}/{len(list(BENCHMARK_DIR.glob('*.json')))} benchmark files")
    for s in skipped:
        print(f"  SKIPPED  {s}")
    for p in papers:
        if p["repair"]:
            print(f"  REPAIRED {Path(p['benchmark_file']).name}: {p['repair']}")
        for g in p["merged_groups"]:
            print(f"  MERGED   {p['study']}: {' + '.join(g)}")
    print(f"benchmark {totals['benchmark_total']} (raw {totals['benchmark_raw']}) | agent {totals['ours_total']} | "
          f"matched {totals['matched']} (exact {totals['exact']}) | missed {totals['missed']} | "
          f"extra {totals['extra']} | recall {totals['recall']:.1%}")
    for p in papers:
        m = p["metrics"]
        print(f"  {p['study']:<8} {p['pmid']}  bench {m['benchmark_total']:>2} agent {m['ours_total']:>2} "
              f"matched {m['matched']:>2} missed {m['missed']} extra {m['extra']:>2}")
    print(f"\nwrote {(OUT_DIR / OUT_STEM).relative_to(REPO_ROOT)}.{{json,html}}")


if __name__ == "__main__":
    main()
