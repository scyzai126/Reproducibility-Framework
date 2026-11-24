"""Write the "Agent assays vs ImmPort experiments, study by study" section of the grain page.

Reads the mapping `map_agent_assays_to_immport.py` wrote and the hand-written review notes in
`comparison/agent_to_immport_comments.json`, and rewrites only the text between the BEGIN / END
markers of `docs/assay_same_term_grain_question_2026-11-20.html`. No LLM call; read-only SELECTs.

The notes file is where the paper-by-paper review lives. Per study:

    {"agent":   {"<agent key>": {"verdict": "...", "comment": "...",
                                 "match": ["EXP1"]  |  "agent_only": true}},
     "immport": {"<EXP accession>": {"verdict": "...", "comment": "..."}}}

`match` pairs an assay with experiments the rule could not pair; `agent_only` removes a rule
match. A row the review has not reached gets an automatic line that says only what the rule knows.
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPARISON = REPO_ROOT / "data/benchmark_agent_assays/assay_result_v3/comparison"
MAPPING = COMPARISON / "agent_to_immport.json"
NOTES = COMPARISON / "agent_to_immport_comments.json"
PAGE = REPO_ROOT / "docs/assay_same_term_grain_question_2026-11-20.html"

ORDER = {"EXACT": 0, "DESCENDANT": 1, "ANCESTOR": 2, "NAME": 3, "EXPNAME": 4, "HAND": 4.5,
         "SIBLING": 5, "NONE": 6}
LABEL = {"HAND": "Same assay (checked by hand)", "EXACT": "Same term",
         "DESCENDANT": "Agent more specific", "ANCESTOR": "Agent broader", "NAME": "Name match",
         "EXPNAME": "Experiment name match", "SIBLING": "Weak (sibling terms)",
         "NONE": "Agent only", "IMMPORT_ONLY": "ImmPort only"}
CLS = {"SIBLING": "weak", "NONE": "none", "IMMPORT_ONLY": "none"}
MAPPED = ("EXACT", "DESCENDANT", "ANCESTOR", "NAME", "EXPNAME", "HAND")
NOT_REVIEWED = "Not reviewed yet."
AUTO = {
    "DESCENDANT": "Agent term is more specific than ImmPort's.",
    "ANCESTOR": "Agent term is broader than ImmPort's.",
    "NAME": "ImmPort's technique name equals a name the paper uses.",
    "SIBLING": "Terms only share a parent; weak link, not counted. " + NOT_REVIEWED,
}


def auto_comment(level: str, evidence: str = "", n_extra: int = 0) -> str:
    """The line a row gets when the review wrote none: only what the rule itself knows."""
    if level == "EXACT":
        return ""
    if level == "EXPNAME":
        return f"Matched on the experiment name: {evidence}." if evidence else AUTO["NAME"]
    if level in ("NONE", "IMMPORT_ONLY"):
        other = f" Study has {n_extra} other paper{'s' if n_extra != 1 else ''}." if n_extra else ""
        return NOT_REVIEWED + other
    return AUTO.get(level, "")


def plan_study(recs: list[dict], mine: list[dict], notes: dict, n_extra: int = 0):
    """Rows for one study, and the note keys that matched nothing.

    `mine` is the study's experiments as {accession, name, technique}. Returns (rows, warnings).
    A row is {side, level, record, technique, experiments, chosen, evidence, uninformative,
    verdict, comment, reviewed}; `level` is the level after any hand correction.
    """
    agent_notes, exp_notes = notes.get("agent", {}), notes.get("immport", {})
    by_acc = {e["accession"]: e for e in mine}
    warnings = [f"agent key not in this study: {k}"
                for k in agent_notes if k not in {r["key"] for r in recs}]
    warnings += [f"experiment not in this study: {a}" for a in exp_notes if a not in by_acc]
    warnings += [f"match names an unknown experiment: {a}" for n in agent_notes.values()
                 for a in n.get("match", []) if a not in by_acc]
    claimed = {a for n in agent_notes.values() for a in n.get("match", [])}

    rows, used = [], set()

    def add(record, level, note, technique=None, experiments=(), chosen=(), evidence="",
            uninformative=False):
        used.update(e["accession"] for e in experiments)
        text = note.get("comment") or auto_comment(level, evidence, n_extra)
        inner = [f"{e['accession']}: {exp_notes[e['accession']]['comment']}"
                 for e in experiments if e["accession"] in exp_notes] if record else []
        rows.append({
            "side": "agent" if record else "immport", "level": level, "record": record,
            "technique": technique, "experiments": list(experiments), "chosen": set(chosen),
            "evidence": evidence, "uninformative": uninformative,
            "verdict": note.get("verdict", ""), "comment": " ".join([text, *inner]).strip(),
            "reviewed": bool(note.get("comment")),
        })

    def level_of(r):
        note = agent_notes.get(r["key"], {})
        return "NONE" if note.get("agent_only") else "HAND" if note.get("match") else r["level"]

    for r in sorted(recs, key=lambda r: (ORDER[level_of(r)], r["key"])):
        note, level = agent_notes.get(r["key"], {}), level_of(r)
        if level == "HAND":
            picked = [by_acc[a] for a in note["match"] if a in by_acc]
            for tech in dict.fromkeys(e["technique"] for e in picked):
                add(r, level, note, tech, [e for e in picked if e["technique"] == tech])
            continue
        before = len(rows)
        for link in [] if level == "NONE" else r["links"]:
            if link.get("uninformative"):   # 'Other' is a bucket: only the name-matched ones
                exps = [by_acc.get(e["accession"], e) for e in link["experiments"]]
            else:
                exps = [e for e in mine if e["technique"] == link["technique"]]
            exps = [e for e in exps if e["accession"] not in claimed]
            if not exps:
                continue
            chosen = ({e["accession"] for e in link["experiments"]}
                      if link["status"] == "NAMED" and not link.get("uninformative") else ())
            add(r, level, note, link["technique"], exps, chosen, link.get("evidence", ""),
                bool(link.get("uninformative")))
        if len(rows) == before:
            add(r, level, note)
    for e in mine:
        if e["accession"] not in used:
            add(None, "IMMPORT_ONLY", exp_notes.get(e["accession"], {}), e["technique"], [e])
    return rows, warnings


def count_levels(rows: list[dict]) -> collections.Counter:
    """Each agent assay once (it can span several rows), each ImmPort-only experiment once."""
    seen, counts = set(), collections.Counter()
    for row in rows:
        ident = id(row["record"]) if row["record"] else row["experiments"][0]["accession"]
        if ident not in seen:
            seen.add(ident)
            counts[row["level"]] += 1
    return counts


def review_progress(rows: list[dict]) -> tuple[int, int]:
    """(rows the review commented, rows that are not a same-term match)."""
    open_rows = [r for r in rows if r["level"] != "EXACT"]
    return sum(r["reviewed"] for r in open_rows), len(open_rows)


E = html.escape


def _sub(text: str) -> str:
    return f'<span class="sub">{text}</span>'


def _pill(level: str) -> str:
    return f'<span class="pill {CLS.get(level, "ok")}">{LABEL[level]}</span>'


def _obi_cell(ids: list[str], label_of: dict) -> str:
    if not ids:
        return _sub("no ontology id")
    return "<br>".join(f"{E(i)}<br>{_sub(E(label_of.get(i, '')))}" for i in ids)


def _experiments_cell(row: dict) -> str:
    exps = row["experiments"]
    lines = [f"{E(e['accession'])} {_sub(E(e['name'] or ''))}"
             + (' <span class="pill ok">closest</span>' if e["accession"] in row["chosen"] else "")
             for e in exps]
    if len(exps) > 1 and row["level"] != "HAND" and not row["uninformative"]:
        lines.insert(0, _sub(f"{len(exps)} experiments under this technique:"))
    if row["chosen"]:
        lines.append(_sub(f"closest chosen by: {E(row['evidence'])}"))
    return "<br>".join(lines)


def _comment_cell(row: dict) -> str:
    verdict = f"<b>{E(row['verdict'])}.</b> " if row["verdict"] else ""
    return f'<td class="cmt">{verdict}{E(row["comment"])}</td>'


def render_row(row: dict, tech_ids: dict, label_of: dict, show_pmid: bool = False) -> str:
    r = row["record"]
    if r is None:
        left = f'<td colspan="2" class="sub">No agent assay matches this experiment</td>'
    else:
        agent = E(r["key"])
        names = "; ".join(r.get("name_in_paper") or [])
        if names:
            agent += "<br>" + _sub(f"paper: {E(names)}")
        if show_pmid:
            agent += "<br>" + _sub(f"PMID {E(r['pmid'])}")
        term = (f"{E(r['obi_id'])}<br>{_sub(E(r.get('obi_label') or ''))}" if r.get("obi_id")
                else _sub("no OBI term"))
        left = f"<td>{agent}</td><td>{term}</td>"
    if row["experiments"]:
        right = (f"<td>{E(row['technique'])}</td>"
                 f"<td>{_obi_cell(tech_ids.get(row['technique'], []), label_of)}</td>"
                 f"<td>{_experiments_cell(row)}</td>")
    else:
        right = '<td colspan="3" class="sub">No experiment in ImmPort for this assay</td>'
    return f"<tr>{left}<td>{_pill(row['level'])}</td>{right}{_comment_cell(row)}</tr>"


def render_study(n, study, title, rows, pmids, extra, notin, n_experiments, tech_ids, label_of):
    c = count_levels(rows)
    n_assays = sum(v for k, v in c.items() if k != "IMMPORT_ONLY")
    mapped = sum(c[k] for k in MAPPED)
    worked = ("Paper we worked on: " if len(pmids) == 1 else "Papers we worked on: ") \
        + ", ".join("PMID " + p for p in pmids)
    plural = "s" if len(extra) > 1 else ""
    cover = (f"ImmPort links <b>{len(extra)}</b> other paper{plural} to this study that we did "
             f"not process (PMID {', '.join(extra)})" if extra
             else "ImmPort links no other paper to this study")
    if notin:
        cover += f"; note PMID {', '.join(notin)} is not in ImmPort&rsquo;s paper list for this study"
    done, todo = review_progress(rows)
    review = (f"Comments: <b>{done} of {todo}</b> rows that are not a same-term match have a "
              f"reviewed comment." if todo else "Every row is a same-term match.")
    more = f" · +{len(extra)} other paper{plural}" if extra else ""
    body = "\n".join("  " + render_row(r, tech_ids, label_of, len(pmids) > 1) for r in rows)
    return f'''<h3 class="study" id="st-{study}">{n}. {study} {_sub(f"PMID {', '.join(pmids)}{more}")}</h3>
<p class="studymeta">{E(title or "")}<br>{worked}. {cover}.<br>Agent: <b>{n_assays}</b> assays ({mapped} mapped, {c["SIBLING"]} weak, {c["NONE"]} agent only) · ImmPort: <b>{n_experiments}</b> experiments ({c["IMMPORT_ONLY"]} with no agent assay).<br>{review}</p>
<div class="scroll"><table class="cmp">
  <tr><th>Agent assay</th><th>Agent OBI term</th><th>Match</th><th>ImmPort technique</th><th>ImmPort OBI term</th><th>ImmPort experiment</th><th>Comment</th></tr>
{body}
</table></div>'''


STYLE = '''<style>
  .sub { font-size: 13px; color: var(--text); font-weight: 400; }
  .pill { display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 10px; white-space: nowrap; }
  .pill.ok { background: var(--hl); color: var(--ink); }
  .pill.weak { background: var(--warn-bg); color: var(--warn-ink); }
  .pill.none { background: var(--head); color: var(--ink); }
  h3.study { font: 600 19px/1.3 Georgia, "Times New Roman", serif; color: var(--ink); margin: 34px 0 4px; }
  .studymeta { font-size: 14px; margin: 0 0 10px; }
  table.cmp { font-size: 14px; min-width: 1080px; }
  table.cmp td.cmt { min-width: 220px; font-size: 13px; }
  .studynav { display: flex; flex-wrap: wrap; gap: 6px 12px; font-size: 14px; margin: 0 0 16px; }
  .studynav a { color: var(--accent); }
</style>'''


def render_section(blocks: list[str], studies: list[str], tot: collections.Counter,
                   n_records: int, progress: tuple[int, int], today: str) -> str:
    mapped = sum(tot[k] for k in MAPPED)
    nav = " ".join(f'<a href="#st-{s}">{s}</a>' for s in studies)
    return f'''
<!-- BEGIN agent-vs-immport (generated by scripts/build_agent_immport_section.py) -->
{STYLE}
<h2 id="agent-vs-immport">Agent assays vs ImmPort experiments, study by study</h2>
<p>For each of the {len(studies)} studies behind the 31 benchmark papers: every assay the agent extracted with its OBI term, beside the experiment ImmPort records for that study with the OBI term ImmPort assigns to its technique. Rule-based matching, no LLM call; {tot["HAND"]} assays were then paired by hand after reading the papers, and say so. Generated {today}.</p>
<div class="scroll"><table>
  <tr><th>Match</th><th class="n">Agent assays</th><th>Meaning</th></tr>
  <tr><td>{_pill("EXACT")}</td><td class="n">{tot["EXACT"]}</td><td>Agent and ImmPort carry the same OBI id</td></tr>
  <tr><td>{_pill("DESCENDANT")}</td><td class="n">{tot["DESCENDANT"]}</td><td>The agent’s term is a child of ImmPort’s</td></tr>
  <tr><td>{_pill("ANCESTOR")}</td><td class="n">{tot["ANCESTOR"]}</td><td>The agent’s term is a parent of ImmPort’s</td></tr>
  <tr><td>{_pill("EXPNAME")}</td><td class="n">{tot["EXPNAME"] + tot["NAME"]}</td><td>OBI terms differ or ImmPort files it under “Other”, but the experiment’s name matches the assay</td></tr>
  <tr><td>{_pill("HAND")}</td><td class="n">{tot["HAND"]}</td><td>OBI terms differ or ImmPort has none, but reading the paper shows it is the same assay</td></tr>
  <tr><td>{_pill("SIBLING")}</td><td class="n">{tot["SIBLING"]}</td><td>The two terms only share a parent; not counted as a match</td></tr>
  <tr><td>{_pill("NONE")}</td><td class="n">{tot["NONE"]}</td><td>The paper reports the assay; ImmPort has no experiment for it</td></tr>
  <tr><td>{_pill("IMMPORT_ONLY")}</td><td class="n">{tot["IMMPORT_ONLY"]} {_sub("experiments")}</td><td>An ImmPort experiment no agent assay matched</td></tr>
</table></div>
<p><b>{mapped} of {n_records}</b> agent assays map to an ImmPort technique. Where ImmPort files several experiments under the matched technique, the row lists all of them, since one assay in the paper often covers several ImmPort experiments. An experiment tagged “closest” is the one whose name best fits this assay; when chosen by shared words it is a suggestion to check, not a verified match.</p>
<p><b>Comment column.</b> A row that is not a same-term match carries the reason. A comment that opens with a bold verdict was written after reading the paper (and its supplement where we hold it); <b>{progress[0]} of {progress[1]}</b> such rows have one so far. “Not reviewed yet” means only the rule has looked at the row.</p>
<p class="studynav">{nav}</p>
''' + "\n".join(blocks) + '''
<p class="sources">Source for this section: <code>data/benchmark_agent_assays/assay_result_v3/comparison/agent_to_immport.json</code>, written by <code>scripts/map_agent_assays_to_immport.py</code>; review comments and hand pairings in <code>comparison/agent_to_immport_comments.json</code>; ImmPort DR62 tables <code>experiment</code> and <code>lk_exp_measurement_tech</code>. Full text version: <code>docs/agent_to_immport_mapping_2026-11.md</code>.</p>
<!-- END agent-vs-immport -->
'''


def replace_section(page_text: str, section: str) -> str:
    page_text = re.sub(r"\n<!-- BEGIN agent-vs-immport.*?<!-- END agent-vs-immport -->\n", "",
                       page_text, flags=re.S)
    if page_text.count("</main>") != 1:
        raise SystemExit("expected exactly one </main> in the page")
    return page_text.replace("</main>", section + "</main>")


def main() -> None:
    import datetime

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mapping", type=Path, default=MAPPING)
    parser.add_argument("--notes", type=Path, default=NOTES)
    parser.add_argument("--page", type=Path, default=PAGE)
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
    from check_immport_measurements import mysql_url, term_ids
    from compare_assay_benchmark import ObiGraph
    from sqlalchemy import create_engine, text

    records = json.loads(args.mapping.read_text(encoding="utf-8"))["records"]
    notes = json.loads(args.notes.read_text(encoding="utf-8")) if args.notes.exists() else {}
    studies = sorted({r["study"] for r in records}, key=lambda s: int(s[3:]))
    with create_engine(mysql_url()).connect() as conn:
        params = {"s": tuple(studies)}
        exps = conn.execute(text(
            "SELECT study_accession, experiment_accession, name, measurement_technique "
            "FROM experiment WHERE study_accession IN :s ORDER BY experiment_accession"),
            params).all()
        tech_ids = {name: term_ids(link) for name, link in conn.execute(
            text("SELECT name, link FROM lk_exp_measurement_tech")).all()}
        papers = collections.defaultdict(set)
        for study, pmid in conn.execute(text(
                "SELECT study_accession, pubmed_id FROM study_pubmed "
                "WHERE study_accession IN :s"), params):
            papers[study].add(str(pmid))
        titles = dict(conn.execute(text(
            "SELECT study_accession, brief_title FROM study WHERE study_accession IN :s"),
            params).all())

    label_of = ObiGraph().label_of
    blocks, tot, done, todo = [], collections.Counter(), 0, 0
    warnings = [f"{s}: study not in the mapping" for s in notes if s not in studies]
    for n, study in enumerate(studies, 1):
        recs = [r for r in records if r["study"] == study]
        mine = [{"accession": a, "name": name or "", "technique": tech}
                for s, a, name, tech in exps if s == study]
        pmids = sorted({r["pmid"] for r in recs})
        extra = sorted(papers[study] - set(pmids))
        rows, warns = plan_study(recs, mine, notes.get(study, {}), len(extra))
        warnings += [f"{study}: {w}" for w in warns]
        tot += count_levels(rows)
        d, t = review_progress(rows)
        done, todo = done + d, todo + t
        blocks.append(render_study(n, study, titles.get(study), rows, pmids, extra,
                                   sorted(set(pmids) - papers[study]), len(mine),
                                   tech_ids, label_of))
    section = render_section(blocks, studies, tot, len(records), (done, todo),
                             datetime.date.today().isoformat())
    args.page.write_text(replace_section(args.page.read_text(encoding="utf-8"), section),
                         encoding="utf-8")
    print(f"{len(studies)} studies  {dict(tot)}  reviewed comments {done} of {todo}")
    for w in warnings:
        print("WARNING  notes file:", w)


if __name__ == "__main__":
    main()
