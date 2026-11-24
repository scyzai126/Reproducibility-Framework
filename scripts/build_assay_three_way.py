#!/usr/bin/env python3
"""One page per benchmark paper, three columns: curated benchmark | agent registry | ImmPort.

The first two columns are the rows `compare_assay_benchmark_v2.py --strict` already paired
(read from its JSON, not recomputed). The third is what ImmPort stores for the paper's study:
every row of `experiment` (accession, `measurement_technique`, free-text `name`), grouped by
technique, with the technique's OBI id from `lk_exp_measurement_tech.link`.

ImmPort registers per STUDY and by controlled technique, so its column is coarser than the other
two. Each ImmPort technique is graded against the paper's agent entries and against its
benchmark rows with `check_immport_measurements.classify` (EXACT / DESCENDANT / ANCESTOR / NAME /
EXPNAME / SIBLING / MISS) and shown on the row of its best partner -- the agent's, else the
benchmark's. A technique neither side has gets a row of its own. `Other` is shown too: it is
what ImmPort stores, even though it names no assay.

Read-only: SELECTs against MYSQL_URL and files on disk. No LLM call.

    python3 scripts/build_assay_three_way.py
    python3 scripts/build_assay_three_way.py --comparison <strict.json> --out <stem>

Writes <comparison dir>/benchmark_agent_immport.{html,json}
"""

from __future__ import annotations

import argparse
import collections
import datetime
import html
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from check_immport_measurements import (  # noqa: E402
    UNINFORMATIVE, classify, mysql_url, our_entries, term_ids,
)
from compare_assay_benchmark import ObiGraph, _surface_forms, normalize  # noqa: E402

COMPARISON = (_REPO_ROOT / "data" / "benchmark_agent_assays" / "assay_result_v3" / "comparison"
              / "benchmark_vs_agent_strict.json")
#: Levels that count as "this side has the assay ImmPort stored".
COVERED = {"EXACT", "DESCENDANT", "ANCESTOR", "NAME", "EXPNAME", "SIBLING"}


def immport_studies(studies: list[str]) -> dict[str, dict]:
    """{study: {title, pmids, techniques: [{technique, ids, experiments: [{accession, name}]}]}}"""
    from sqlalchemy import create_engine, text

    engine = create_engine(mysql_url())
    out: dict[str, dict] = {s: {"title": None, "pmids": [], "techniques": []} for s in studies}
    with engine.connect() as conn:
        links = {r[0]: r[1] for r in conn.execute(
            text("SELECT name, link FROM lk_exp_measurement_tech"))}
        for study, title in conn.execute(
                text("SELECT study_accession, brief_title FROM study WHERE study_accession IN :s"),
                {"s": tuple(studies)}):
            out[study]["title"] = title
        for study, pmid in conn.execute(
                text("SELECT study_accession, pubmed_id FROM study_pubmed "
                     "WHERE study_accession IN :s ORDER BY 1, 2"), {"s": tuple(studies)}):
            out[study]["pmids"].append(str(pmid))
        grouped: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
        for study, accession, technique, name in conn.execute(
                text("SELECT study_accession, experiment_accession, measurement_technique, name "
                     "FROM experiment WHERE study_accession IN :s ORDER BY 1, 3, 2"),
                {"s": tuple(studies)}):
            grouped[(study, technique or "(none)")].append({"accession": accession, "name": name})
    for (study, technique), experiments in grouped.items():
        out[study]["techniques"].append({
            "technique": technique, "ids": term_ids(links.get(technique)),
            "experiments": experiments,
        })
    return out


def build(comparison: dict) -> dict:
    registry_dir = _REPO_ROOT / comparison["registry_dir"]
    obi = ObiGraph()
    agent_entries = our_entries(registry_dir)
    studies = sorted({p["study"] for p in comparison["papers"]})
    immport = immport_studies(studies)

    papers = []
    for paper in comparison["papers"]:
        study, pmid = paper["study"], str(paper["pmid"])
        store = immport[study]
        ours = [e for e in agent_entries.get(study, []) if e["pmid"] == pmid]
        bench = [{
            "pmid": pmid, "key": r["benchmark"]["key"], "obi_id": r["benchmark"].get("obi_id"),
            "obi_label": r["benchmark"].get("obi_label"),
            "forms": _surface_forms(r["benchmark"].get("name_in_paper"),
                                    r["benchmark"].get("aliases")),
        } for r in paper["rows"] if r.get("benchmark")]

        rows = [{"status": r["status"], "reason": r.get("reason"), "benchmark": r.get("benchmark"),
                 "agent": r.get("ours") or [], "immport": []} for r in paper["rows"]]
        by_agent = {a["key"]: row for row in rows for a in row["agent"]}
        by_bench = {row["benchmark"]["key"]: row for row in rows if row["benchmark"]}

        for tech in store["techniques"]:
            names = [e["name"] for e in tech["experiments"] if e["name"]]
            a_level, a_hit = classify(tech["ids"], tech["technique"], ours, obi, names)
            b_level, b_hit = classify(tech["ids"], tech["technique"], bench, obi, names)
            item = {
                **tech,
                "obi_label": obi.label_of.get(tech["ids"][0]) if tech["ids"] else None,
                "informative": normalize(tech["technique"]) not in UNINFORMATIVE,
                "agent_level": a_level, "agent_key": a_hit and a_hit["key"],
                "benchmark_level": b_level, "benchmark_key": b_hit and b_hit["key"],
            }
            row = (a_hit and by_agent.get(a_hit["key"])) or (b_hit and by_bench.get(b_hit["key"]))
            if row is None:
                row = {"status": "IMMPORT_ONLY", "reason": None, "benchmark": None, "agent": [],
                       "immport": []}
                rows.append(row)
            row["immport"].append(item)

        informative = [t for r in rows for t in r["immport"] if t["informative"]]
        papers.append({
            "study": study, "pmid": pmid, "study_title": store["title"],
            "study_pmids": store["pmids"], "rows": rows,
            "counts": {
                "benchmark": sum(1 for r in rows if r["benchmark"]),
                "agent": sum(len(r["agent"]) for r in rows),
                "immport_experiments": sum(len(t["experiments"]) for t in store["techniques"]),
                "immport_techniques": len(store["techniques"]),
                "immport_informative": len(informative),
                "immport_in_agent": sum(t["agent_level"] in COVERED for t in informative),
                "immport_in_benchmark": sum(t["benchmark_level"] in COVERED for t in informative),
                "missed": sum(r["status"] == "MISSED" for r in rows),
                "extra": sum(r["status"] == "EXTRA" for r in rows),
            },
        })
    keys = ["benchmark", "agent", "immport_experiments", "immport_techniques",
            "immport_informative", "immport_in_agent", "immport_in_benchmark", "missed", "extra"]
    return {
        "generated": datetime.date.today().isoformat(),
        "comparison": comparison.get("mode"), "registry_dir": comparison["registry_dir"],
        "benchmark_dir": comparison["benchmark_dir"],
        "totals": {k: sum(p["counts"][k] for p in papers) for k in keys} | {"papers": len(papers)},
        "papers": papers,
    }


# ── HTML ─────────────────────────────────────────────────────────────────────

CSS = """
:root{--bg:#fbfaf8;--fg:#1f2328;--muted:#6b7280;--card:#fff;--line:#e5e2dc;--code:#f3f1ec;--head:#f6f4ef;
--match:#1a7f37;--gran:#0969da;--conflict:#bc4c00;--unmapped:#8250df;--split:#9a6700;--missed:#cf222e;--extra:#57606a;--imm:#0e7490}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#16181c;--fg:#e6e6e6;--muted:#9aa0a6;--card:#1e2126;--line:#2e3238;--code:#262a30;--head:#23272d;
--match:#3fb950;--gran:#58a6ff;--conflict:#f0883e;--unmapped:#bc8cff;--split:#d29922;--missed:#ff7b72;--extra:#8b949e;--imm:#22b8cf}}
:root[data-theme="dark"]{--bg:#16181c;--fg:#e6e6e6;--muted:#9aa0a6;--card:#1e2126;--line:#2e3238;--code:#262a30;--head:#23272d;
--match:#3fb950;--gran:#58a6ff;--conflict:#f0883e;--unmapped:#bc8cff;--split:#d29922;--missed:#ff7b72;--extra:#8b949e;--imm:#22b8cf}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1500px;margin:0 auto;padding:24px 16px 80px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:18px;margin:0}
a{color:var(--gran);text-decoration:none} a:hover{text-decoration:underline}
.sub,.meta{color:var(--muted);font-size:13px} .small{color:var(--muted);font-size:12px}
code{background:var(--code);padding:0 4px;border-radius:4px;font-size:12px}
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:130px}
.kpi b{display:block;font-size:22px;font-variant-numeric:tabular-nums} .kpi span{color:var(--muted);font-size:12px}
.note{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:0 0 16px;font-size:13px}
.note p{margin:4px 0}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 12px}
.bar input[type=search]{padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);font:inherit;min-width:220px}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
table{border-collapse:collapse;width:100%}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}
th{background:var(--head);font-size:12px;font-weight:600;white-space:nowrap}
tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
section.paper{margin:28px 0 0;scroll-margin-top:8px}
section.paper header{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;margin:0 0 4px}
table.three{min-width:900px;table-layout:fixed}
table.three th:first-child,table.three td:first-child{width:160px}
table.three td+td{border-left:1px solid var(--line)}
.name{font-weight:600;overflow-wrap:anywhere}
.term{font-size:12px;color:var(--muted);overflow-wrap:anywhere}
.item+.item{margin-top:10px;padding-top:10px;border-top:1px dashed var(--line)}
.empty{color:var(--muted);font-style:italic;font-size:12px}
.badge{display:inline-block;font-size:11px;font-weight:600;padding:1px 7px;border-radius:999px;border:1px solid currentColor;white-space:nowrap}
.s-MATCH{color:var(--match)}.s-MATCH_GRANULARITY{color:var(--gran)}.s-MATCH_OBI_CONFLICT{color:var(--conflict)}
.s-MATCH_OBI_UNMAPPED{color:var(--unmapped)}.s-SPLIT{color:var(--split)}.s-MISSED{color:var(--missed)}
.s-EXTRA{color:var(--extra)}.s-IMMPORT_ONLY{color:var(--imm)}
.lv{font-size:11px;white-space:nowrap}.lv b{font-weight:600}
.lv-EXACT b,.lv-DESCENDANT b,.lv-ANCESTOR b{color:var(--match)}
.lv-NAME b,.lv-EXPNAME b,.lv-SIBLING b{color:var(--split)}.lv-MISS b{color:var(--missed)}
details{margin-top:4px;font-size:12px} summary{cursor:pointer;color:var(--muted)}
blockquote{margin:4px 0 0;padding:4px 8px;border-left:3px solid var(--line);color:var(--muted);overflow-wrap:anywhere}
ul.exp{margin:4px 0 0;padding-left:16px;font-size:12px;overflow-wrap:anywhere}
.hidden{display:none}
"""

JS = """
const q=document.getElementById('q'),only=document.getElementById('only');
function apply(){const t=q.value.trim().toLowerCase();
document.querySelectorAll('[data-paper]').forEach(el=>{
const ok=(!t||el.dataset.text.includes(t))&&(!only.checked||el.dataset.diff==='1');
el.classList.toggle('hidden',!ok);});}
q.addEventListener('input',apply);only.addEventListener('change',apply);
"""

STATUS_LABEL = {
    "MATCH": "match", "MATCH_GRANULARITY": "match · granularity", "MATCH_OBI_CONFLICT": "match · OBI differs",
    "MATCH_OBI_UNMAPPED": "match · unmapped", "SPLIT": "split", "MISSED": "agent missed",
    "EXTRA": "agent only", "IMMPORT_ONLY": "ImmPort only",
}


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _term(obi_id, label) -> str:
    if not obi_id and not label:
        return '<div class="term">no OBI term</div>'
    return f'<div class="term">{esc(label or "")} <code>{esc(obi_id or "—")}</code></div>'


def _claim(flag) -> str:
    return "" if flag is None else f' · claim: {"yes" if flag else "no"}'


def _names(value) -> list[str]:
    return [v for v in (value if isinstance(value, list) else [value]) if v]


def _bench_cell(b) -> str:
    if not b:
        return '<span class="empty">not in the benchmark</span>'
    quotes = "".join(
        f'<blockquote>{esc(q.get("section") or "")}{" — " if q.get("section") else ""}'
        f'{esc(q.get("quote") or "")}</blockquote>'
        for q in b.get("quotes") or [] if isinstance(q, dict))
    aliases = ", ".join(esc(a) for a in b.get("aliases") or [])
    more = ""
    if aliases or quotes:
        more = (f'<details><summary>aliases &amp; quotes</summary>'
                f'{f"<div>{aliases}</div>" if aliases else ""}{quotes}</details>')
    return (f'<div class="item"><div class="name">{esc(b.get("name_in_paper") or b["key"])}</div>'
            f'{_term(b.get("obi_id"), b.get("obi_label"))}'
            f'<div class="small">curated{_claim(b.get("generate_claim"))}</div>{more}</div>')


def _agent_cell(entries) -> str:
    if not entries:
        return '<span class="empty">no agent entry</span>'
    out = []
    for a in entries:
        names = _names(a.get("name_in_paper")) or [a["key"]]
        ev = a.get("evidence") or {}
        aliases = ", ".join(esc(x) for x in names[1:] + (a.get("aliases") or []))
        quote = (f'<blockquote>{esc(ev.get("section") or "")} '
                 f'{esc(" ".join(ev.get("sentence_ids") or []))} — {esc(ev.get("quote"))}'
                 f'</blockquote>') if ev.get("quote") else ""
        more = ""
        if aliases or quote:
            more = (f'<details><summary>aliases &amp; evidence</summary>'
                    f'{f"<div>{aliases}</div>" if aliases else ""}{quote}</details>')
        out.append(
            f'<div class="item"><div class="name">{esc(names[0])}</div>'
            f'{_term(a.get("obi_id"), a.get("obi_label"))}'
            f'<div class="small">key <code>{esc(a["key"])}</code> · {esc(a.get("source") or "?")}'
            f'{_claim(a.get("generate_claim"))}</div>{more}</div>')
    return "".join(out)


def _level(side: str, level: str, key) -> str:
    if level == "MISS":
        return f'<span class="lv lv-MISS">{side}: <b>not found</b></span>'
    return (f'<span class="lv lv-{level}" title="{esc(key)}">{side}: <b>{level}</b></span>')


def _immport_cell(items) -> str:
    if not items:
        return '<span class="empty">nothing stored for this assay</span>'
    out = []
    for t in items:
        exps = "".join(f'<li><code>{esc(e["accession"])}</code> {esc(e["name"])}</li>'
                       for e in t["experiments"])
        levels = (f'{_level("agent", t["agent_level"], t["agent_key"])} · '
                  f'{_level("benchmark", t["benchmark_level"], t["benchmark_key"])}'
                  if t["informative"] else '<span class="lv">names no assay — not graded</span>')
        out.append(
            f'<div class="item"><div class="name">{esc(t["technique"])}</div>'
            f'{_term(t["ids"][0] if t["ids"] else None, t["obi_label"])}'
            f'<div>{levels}</div><ul class="exp">{exps}</ul></div>')
    return "".join(out)


def render(data: dict) -> str:
    t = data["totals"]
    kpis = [
        (t["papers"], "papers"), (t["benchmark"], "benchmark assays"), (t["agent"], "agent entries"),
        (t["immport_experiments"], "ImmPort experiments"),
        (t["immport_informative"], "ImmPort techniques (named)"),
        (f'{t["immport_in_agent"]}/{t["immport_informative"]}', "of those, agent has"),
        (f'{t["immport_in_benchmark"]}/{t["immport_informative"]}', "of those, benchmark has"),
    ]
    summary_rows, sections = [], []
    for p in data["papers"]:
        c = p["counts"]
        anchor = f'{p["study"]}_{p["pmid"]}'
        gaps_agent = c["immport_informative"] - c["immport_in_agent"]
        gaps_bench = c["immport_informative"] - c["immport_in_benchmark"]
        diff = "1" if (c["missed"] or c["extra"] or gaps_agent or gaps_bench) else "0"
        text = esc(f'{p["study"]} {p["pmid"]} {p["study_title"] or ""}'.lower())
        summary_rows.append(
            f'<tr data-paper data-diff="{diff}" data-text="{text}">'
            f'<td><a href="#{anchor}">{p["study"]}</a></td><td>{p["pmid"]}</td>'
            f'<td>{esc(p["study_title"])}</td>'
            f'<td class="n">{c["benchmark"]}</td><td class="n">{c["agent"]}</td>'
            f'<td class="n">{c["missed"]}</td><td class="n">{c["extra"]}</td>'
            f'<td class="n">{c["immport_experiments"]}</td><td class="n">{c["immport_informative"]}</td>'
            f'<td class="n">{c["immport_in_agent"]}</td><td class="n">{c["immport_in_benchmark"]}</td></tr>')
        body = "".join(
            f'<tr><td><span class="badge s-{r["status"]}">{STATUS_LABEL.get(r["status"], r["status"])}</span></td>'
            f'<td>{_bench_cell(r["benchmark"])}</td><td>{_agent_cell(r["agent"])}</td>'
            f'<td>{_immport_cell(r["immport"])}</td></tr>' for r in p["rows"])
        others = [x for x in p["study_pmids"] if x != p["pmid"]]
        shared = (f' · ImmPort links this study to {len(others)} other paper'
                  f'{"s" if len(others) != 1 else ""} ({", ".join(others)}), so its column is the '
                  f'whole study\'s') if others else ""
        sections.append(
            f'<section class="paper" id="{anchor}" data-paper data-diff="{diff}" data-text="{text}">'
            f'<header><h2>{p["study"]}</h2>'
            f'<a href="https://pubmed.ncbi.nlm.nih.gov/{p["pmid"]}/">PMID {p["pmid"]}</a>'
            f'<a href="https://www.immport.org/shared/study/{p["study"]}">ImmPort</a>'
            f'<a class="small" href="#top">top</a></header>'
            f'<div class="sub">{esc(p["study_title"])}</div>'
            f'<div class="small" style="margin:2px 0 8px">{c["benchmark"]} benchmark · {c["agent"]} agent · '
            f'{c["immport_techniques"]} ImmPort technique{"s" if c["immport_techniques"] != 1 else ""} '
            f'over {c["immport_experiments"]} experiment{"s" if c["immport_experiments"] != 1 else ""}'
            f'{shared}</div>'
            f'<div class="wrap"><table class="three"><thead><tr><th>Pairing</th>'
            f'<th>Benchmark (curated)</th><th>Agent result</th><th>ImmPort stored (study-level)</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div></section>')
    kpi_html = "".join(f'<div class="kpi"><b>{v}</b><span>{esc(label)}</span></div>' for v, label in kpis)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Benchmark · Agent · ImmPort</title><style>{CSS}</style></head><body><main id="top">
<h1>Assays per paper: benchmark, agent, ImmPort</h1>
<div class="meta">{t["papers"]} benchmark papers · benchmark <code>{esc(data["benchmark_dir"])}</code> ·
agent <code>{esc(data["registry_dir"])}</code> ({esc(data["comparison"])} pairing) ·
ImmPort <code>experiment</code> table · generated {esc(data["generated"])}</div>
<div class="kpis">{kpi_html}</div>
<div class="note">
<p><b>Benchmark ↔ agent</b> pairs and their status come from the strict comparison, unchanged. An agent cell with several entries is one paired entry plus the others on the same OBI term.</p>
<p><b>ImmPort</b> registers per study and by controlled <code>measurement_technique</code>, so it is coarser than the other two and usually lists fewer assays. Each technique sits on the row of its best partner and is graded against both sides: <code>EXACT</code> same OBI term, <code>DESCENDANT</code>/<code>ANCESTOR</code> finer/broader term, <code>NAME</code>/<code>EXPNAME</code> matched by technique or experiment name, <code>SIBLING</code> shared direct OBI parent. <code>Other</code> names no assay and is not graded.</p>
</div>
<div class="bar"><input id="q" type="search" placeholder="Filter by study, PMID or title">
<label><input id="only" type="checkbox"> only papers with a gap (missed, agent-only, or an ImmPort technique one side lacks)</label></div>
<div class="wrap"><table><thead><tr><th>Study</th><th>PMID</th><th>ImmPort study title</th>
<th class="n">Benchmark</th><th class="n">Agent</th><th class="n">Missed</th><th class="n">Agent only</th>
<th class="n">ImmPort exps</th><th class="n">ImmPort techniques</th><th class="n">in agent</th><th class="n">in benchmark</th>
</tr></thead><tbody>{"".join(summary_rows)}</tbody></table></div>
{"".join(sections)}
</main><script>{JS}</script></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--comparison", type=Path, default=COMPARISON,
                        help="JSON written by compare_assay_benchmark_v2.py")
    parser.add_argument("--out", default="benchmark_agent_immport", help="Output file stem")
    args = parser.parse_args()

    data = build(json.loads(args.comparison.read_text(encoding="utf-8")))
    stem = args.comparison.parent / args.out
    stem.with_suffix(".json").write_text(
        json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    stem.with_suffix(".html").write_text(render(data), encoding="utf-8")
    print(json.dumps(data["totals"]))
    for p in data["papers"]:
        for r in p["rows"]:
            for tech in r["immport"]:
                if tech["informative"] and "MISS" in (tech["agent_level"], tech["benchmark_level"]):
                    print(f'GAP  {p["study"]} {p["pmid"]}  {tech["technique"]}: '
                          f'agent {tech["agent_level"]}, benchmark {tech["benchmark_level"]}')
    print(f"wrote {stem.with_suffix('.html')}")


if __name__ == "__main__":
    main()
