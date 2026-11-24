"""For every assay the agent extracted, which ImmPort experiment(s) of the same study is it?

`check_immport_measurements.py` asks the opposite question -- is each technique ImmPort recorded
somewhere in what we extracted -- and keeps one best entry per technique. This script walks the
agent's entries instead, one at a time, and answers in two levels:

* **Level 1, the technique.** Each entry is graded against each `(study, measurement_technique)`
  group with that script's own `classify()`, called on a one-entry list, so the levels (EXACT,
  DESCENDANT, ANCESTOR, NAME, EXPNAME, SIBLING) mean exactly what they mean there. The best
  level wins and every group tied on it is kept. An entry no group reaches is `NONE`: an assay
  the paper reports and ImmPort holds no experiment for, which is normal -- ImmPort registers
  deposited data, not everything a paper did. SIBLING is reported and never counted as mapped.

* **Level 2, the experiment row.** A technique with one experiment is `SINGLE`. With several,
  the entry is `NAMED` onto one of them only when the evidence singles it out: exactly one
  experiment name matches the entry's wordings (the EXPNAME test), or exactly one shares the
  most words with the entry's names, `sample_type` and `readouts` once the words every sibling
  experiment carries are set aside. Otherwise it is `AMBIGUOUS` and every candidate is listed.
  Nothing is guessed: ImmPort's names are free text (`T reg`, `IM_panel_BD`) and one OBI term
  covers all of them, so an honest answer is often "one of these".

* **Experiments filed under an uninformative technique** (`Other`, `not specified`) carry no
  ontology id, so there is no technique to grade. They are not skipped -- SDY1669's Olink panel
  and its LPS reporter assay are both filed under `Other` and both are in the paper -- but
  matched one experiment at a time on the experiment's own name, as `EXPNAME`: the name matches
  one of the entry's wordings or its OBI label, or is the assay's own name written differently
  (`O-link` / `Olink`), or shares at least two content words with the entry (`Determination of
  LPS in plasma` / readouts `lipopolysaccharide (LPS) levels in plasma`). The link names only
  the experiments that matched, never the rest of the `Other` bucket.

Experiments no entry reaches are listed per study, so this direction reconciles with the other.

Read-only: SELECTs against MYSQL_URL and the registries on disk. No LLM call.

    python scripts/map_agent_assays_to_immport.py
    python scripts/map_agent_assays_to_immport.py --study SDY1252
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from check_immport_measurements import (  # noqa: E402
    REGISTRY_DIR, UNINFORMATIVE, _expname_match, _read, classify, immport_papers, mysql_url,
    our_entries, term_ids,
)
from compare_assay_benchmark import ObiGraph, normalize  # noqa: E402

REPORT = _REPO_ROOT / "docs" / "agent_to_immport_mapping_2026-11.md"
JSON_OUT = REGISTRY_DIR / "comparison" / "agent_to_immport.json"

RANK = {"NONE": 0, "SIBLING": 1, "EXPNAME": 2, "NAME": 3, "ANCESTOR": 4, "DESCENDANT": 5,
        "EXACT": 6}
#: Levels that say "this is that assay". SIBLING only says the two terms share a parent.
MAPPED = ("EXACT", "DESCENDANT", "ANCESTOR", "NAME", "EXPNAME")
#: Words that pair any two descriptions and so are no evidence for one experiment over another.
_STOPWORDS = frozenset(
    "a an and are as at by for from in into is of on or the to using via with was were "
    "assay assays analysis data measurement measurements level levels sample samples".split())
#: Words that open an experiment name without saying which assay it is.
_NAME_FILLER = frozenset("determination quantification quantitation detection".split())
#: The run-together form of a name must be at least this long to count as the assay's own name,
#: so `O-link` reads as `olink` while a two-letter code cannot pair with anything.
_SQUASHED_MIN_CHARS = 5


def immport_groups(engine, studies: list[str]):
    """({study: [group, ...]}, [(study, technique, accessions) filed under an uninformative one]).

    One group is one `(study, measurement_technique)` with every experiment row under it.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = list(conn.execute(
            text("SELECT study_accession, measurement_technique, experiment_accession, name, "
                 "description FROM experiment WHERE study_accession IN :s "
                 "AND measurement_technique IS NOT NULL ORDER BY experiment_accession"),
            {"s": tuple(studies)},
        ))
        links = {
            row[0]: row[1]
            for row in conn.execute(text("SELECT name, link FROM lk_exp_measurement_tech"))
        }
    return build_groups(rows, links)


def build_groups(rows, links: dict[str, str | None]):
    """Group experiment rows `(study, technique, accession, name, description)` by technique."""
    grouped: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for study, technique, accession, name, description in rows:
        grouped[(study, technique)].append(
            {"accession": accession, "name": name or "", "description": description or ""})
    by_study: dict[str, list[dict]] = collections.defaultdict(list)
    uninformative = []
    for (study, technique), experiments in sorted(grouped.items()):
        vague = normalize(technique) in UNINFORMATIVE
        if vague:
            uninformative.append((study, technique, [e["accession"] for e in experiments]))
        by_study[study].append({
            "technique": technique, "ids": [] if vague else term_ids(links.get(technique)),
            "experiments": experiments, "uninformative": vague})
    return dict(by_study), uninformative


def entry_extras(registry_dir: Path) -> dict[tuple[str, str], dict]:
    """{(pmid, key): sample_type / readouts / name_in_paper} -- what `our_entries` leaves out."""
    out = {}
    for folder in sorted(registry_dir.iterdir()):
        if not folder.is_dir() or "_SDY" not in folder.name:
            continue
        pmid = folder.name.split("_")[0]
        for key, record in (_read(folder / "assays_OBI.json") or {}).items():
            if isinstance(record, dict):
                out[(pmid, key)] = {
                    "sample_type": record.get("sample_type") or "",
                    "readouts": record.get("readouts") or "",
                    "name_in_paper": record.get("name_in_paper") or [],
                }
    return out


def _words(*texts: str) -> set[str]:
    return {w for t in texts for w in normalize(t or "").split()} - _STOPWORDS


def name_evidence(entry: dict, exp_name: str) -> str:
    """Why this experiment name denotes this entry's assay, or "" when nothing says so.

    The only test there is for an experiment filed under an uninformative technique.
    """
    forms = {f for f in entry.get("forms") or [] if f}
    forms.add(normalize(entry.get("obi_label") or ""))
    forms.discard("")
    if _expname_match([exp_name], forms):
        return "experiment name matches the assay's wording"
    squashed = normalize(exp_name).replace(" ", "")
    if len(squashed) >= _SQUASHED_MIN_CHARS and (
            squashed in {w for f in forms for w in f.split()}
            or squashed in {f.replace(" ", "") for f in forms}):
        return "experiment name is the assay's own name"
    named = _words(exp_name) - _NAME_FILLER
    shared = named & _words(*forms, entry.get("sample_type", ""), entry.get("readouts", ""))
    if len(shared) >= 2 and 2 * len(shared) >= len(named):
        return "shared words: " + ", ".join(sorted(shared))
    return ""


def pick_experiments(entry: dict, experiments: list[dict]) -> dict:
    """Which of a technique's experiments is this entry: SINGLE, NAMED or AMBIGUOUS."""
    brief = [{"accession": e["accession"], "name": e["name"]} for e in experiments]
    if len(experiments) == 1:
        return {"status": "SINGLE", "experiments": brief, "candidates": [], "evidence": ""}

    forms = set(entry.get("forms") or [])
    by_name = [e for e in experiments if _expname_match([e["name"]], forms)]
    if len(by_name) == 1:
        chosen = by_name[0]
        return {"status": "NAMED",
                "experiments": [{"accession": chosen["accession"], "name": chosen["name"]}],
                "candidates": [], "evidence": "experiment name matches the assay's wording"}

    exp_words = [_words(e["name"], e["description"]) for e in experiments]
    # A word every sibling experiment carries (the technique's own name, usually) cannot choose.
    shared_by_all = set.intersection(*exp_words) if exp_words else set()
    mine = _words(*forms, entry.get("sample_type", ""), entry.get("readouts", ""))
    overlaps = [(words - shared_by_all) & mine for words in exp_words]
    top = max(len(o) for o in overlaps)
    winners = [i for i, o in enumerate(overlaps) if len(o) == top]
    if top > 0 and len(winners) == 1:
        chosen = experiments[winners[0]]
        return {"status": "NAMED",
                "experiments": [{"accession": chosen["accession"], "name": chosen["name"]}],
                "candidates": [],
                "evidence": "shared words: " + ", ".join(sorted(overlaps[winners[0]]))}
    return {"status": "AMBIGUOUS", "experiments": [], "candidates": brief, "evidence": ""}


def map_entry(entry: dict, groups: list[dict], obi: ObiGraph) -> dict:
    """Best technique level for one agent entry, with the experiment pick for each tied group."""
    best, hits = "NONE", []
    for group in groups:
        if group.get("uninformative"):
            named = [(e, name_evidence(entry, e["name"])) for e in group["experiments"]]
            named = [(e, why) for e, why in named if why]
            if not named:
                continue
            level = "EXPNAME"
            link = {"technique": group["technique"], "ids": [], "uninformative": True,
                    "status": "NAMED", "candidates": [],
                    "experiments": [{"accession": e["accession"], "name": e["name"]}
                                    for e, _ in named],
                    "evidence": named[0][1]}
        else:
            level, hit = classify(group["ids"], group["technique"], [entry], obi,
                                  [e["name"] for e in group["experiments"]])
            if hit is None or level == "MISS":
                continue
            link = {"technique": group["technique"], "ids": group["ids"],
                    **pick_experiments(entry, group["experiments"])}
        if RANK[level] > RANK[best]:
            best, hits = level, [link]
        elif level == best:
            hits.append(link)
    return {"level": best, "links": hits}


def map_all(entries_by_study: dict[str, list[dict]], groups_by_study: dict[str, list[dict]],
            obi: ObiGraph, extras: dict[tuple[str, str], dict] | None = None):
    """(one record per agent entry, {study: experiments no mapped entry reaches})."""
    extras = extras or {}
    records, unreached = [], {}
    for study in sorted(entries_by_study):
        groups = groups_by_study.get(study, [])
        by_technique = {g["technique"]: g["experiments"] for g in groups}
        reached: set[str] = set()   # experiment accessions
        for entry in entries_by_study[study]:
            full = {**entry, **extras.get((entry["pmid"], entry["key"]), {})}
            result = map_entry(full, groups, obi)
            if result["level"] in MAPPED:
                for link in result["links"]:
                    # An uninformative technique is a bucket: only the named experiments count.
                    covered = (link["experiments"] if link.get("uninformative")
                               else by_technique[link["technique"]])
                    reached |= {e["accession"] for e in covered}
            records.append({
                "pmid": entry["pmid"], "study": study, "key": entry["key"],
                "obi_id": entry.get("obi_id"), "obi_label": entry.get("obi_label"),
                "name_in_paper": full.get("name_in_paper", []), **result})
        left = [{"technique": g["technique"], "accession": e["accession"], "name": e["name"]}
                for g in groups for e in g["experiments"] if e["accession"] not in reached]
        if left:
            unreached[study] = left
    return records, unreached


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry-dir", type=Path, default=REGISTRY_DIR)
    parser.add_argument("--study", nargs="+", default=None, help="Limit to these studies")
    parser.add_argument("--json", type=Path, default=JSON_OUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    from sqlalchemy import create_engine

    entries_by_study = our_entries(args.registry_dir)
    if args.study:
        entries_by_study = {s: e for s, e in entries_by_study.items() if s in set(args.study)}
    if not entries_by_study:
        raise SystemExit("no studies found")
    studies = sorted(entries_by_study)

    engine = create_engine(mysql_url())
    groups_by_study, dropped = immport_groups(engine, studies)
    papers = immport_papers(engine, studies)
    held = {s: {e["pmid"] for e in entries} for s, entries in entries_by_study.items()}
    partial = sorted(s for s in studies if papers.get(s, set()) - held[s])

    records, unreached = map_all(entries_by_study, groups_by_study, ObiGraph(),
                                 entry_extras(args.registry_dir))
    lines = report_lines(records, unreached, dropped, groups_by_study, partial)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(
        {"registry_dir": str(args.registry_dir), "records": records, "unreached": unreached,
         "dropped_uninformative": dropped, "partial_studies": partial},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\n".join(lines[:24]))
    print(f"\nwrote {args.report}\nwrote {args.json}")


def _exp_text(link: dict) -> str:
    def show(items):
        return ", ".join(f"{e['accession']} `{e['name']}`" for e in items)
    if link["status"] == "AMBIGUOUS":
        return f"AMBIGUOUS, one of {len(link['candidates'])}: {show(link['candidates'])}"
    note = f" ({link['evidence']})" if link["evidence"] else ""
    return f"{link['status']}: {show(link['experiments'])}{note}"


def report_lines(records, unreached, dropped, groups_by_study, partial) -> list[str]:
    levels = collections.Counter(r["level"] for r in records)
    mapped = [r for r in records if r["level"] in MAPPED]
    statuses = collections.Counter(link["status"] for r in mapped for link in r["links"])
    n_exp = sum(len(g["experiments"]) for gs in groups_by_study.values() for g in gs)
    n_groups = sum(len(gs) for gs in groups_by_study.values())
    n_left = sum(len(v) for v in unreached.values())
    papers = sorted({(r["study"], r["pmid"]) for r in records})

    lines = [
        "# Which ImmPort experiment is each assay the agent extracted?",
        "",
        f"{len(papers)} papers in {len(groups_by_study)} studies with ImmPort experiments "
        f"({len({s for s, _ in papers})} studies in all). {len(records)} agent assay entries "
        f"against {n_exp} ImmPort experiments in {n_groups} (study, technique) groups. "
        "Generated by `scripts/map_agent_assays_to_immport.py`; rules only, no LLM call.",
        "",
        "## Level 1: agent assay to ImmPort technique",
        "",
        "| level | entries | meaning |",
        "|---|---|---|",
    ]
    meaning = {
        "EXACT": "same OBI id as the ImmPort technique",
        "DESCENDANT": "the agent's term is more specific than ImmPort's",
        "ANCESTOR": "the agent's term is broader than ImmPort's",
        "NAME": "ImmPort's technique name equals one of the assay's wordings",
        "EXPNAME": "an ImmPort experiment name matches one of the assay's wordings",
        "SIBLING": "terms share a direct parent only; weak, not counted as mapped",
        "NONE": "no experiment in ImmPort for this assay",
    }
    for level in ("EXACT", "DESCENDANT", "ANCESTOR", "NAME", "EXPNAME", "SIBLING", "NONE"):
        lines.append(f"| {level} | {levels[level]} | {meaning[level]} |")
    lines += [
        "",
        f"**Mapped: {len(mapped)} of {len(records)}** agent entries. "
        f"Not in ImmPort: {levels['NONE']}. Weak (SIBLING) only: {levels['SIBLING']}.",
        "",
        "## Level 2: which experiment row",
        "",
        f"Over the {sum(statuses.values())} technique links of the mapped entries (an entry "
        "tied across two techniques has two links):",
        "",
        "| status | links | meaning |",
        "|---|---|---|",
        f"| SINGLE | {statuses['SINGLE']} | the technique has one experiment in the study |",
        f"| NAMED | {statuses['NAMED']} | several experiments, the evidence singles one out |",
        f"| AMBIGUOUS | {statuses['AMBIGUOUS']} | several experiments, nothing chooses between "
        "them |",
        "",
        f"ImmPort experiments no mapped agent entry reaches: **{n_left} of {n_exp}** "
        "(listed at the end).",
        "",
        "## Every agent assay, by paper",
    ]
    by_paper = collections.defaultdict(list)
    for r in records:
        by_paper[(r["study"], r["pmid"])].append(r)
    for (study, pmid), rows in sorted(by_paper.items()):
        flag = " (ImmPort links papers we do not hold)" if study in partial else ""
        lines += ["", f"### {study}, PMID {pmid}{flag}", "",
                  "| agent assay | OBI | level | ImmPort technique | experiment |",
                  "|---|---|---|---|---|"]
        for r in rows:
            obi = r["obi_id"] or "unmapped"
            if not r["links"]:
                lines.append(f"| {r['key']} | {obi} | NONE | not in ImmPort | |")
            for link in r["links"]:
                lines.append(f"| {r['key']} | {obi} | {r['level']} | {link['technique']} | "
                             f"{_exp_text(link)} |")

    lines += ["", "## ImmPort experiments no mapped agent entry reaches", ""]
    if not unreached:
        lines.append("None.")
    for study, items in sorted(unreached.items()):
        flag = " (ImmPort links papers we do not hold)" if study in partial else ""
        lines.append(f"- **{study}**{flag}: " + "; ".join(
            f"{e['accession']} `{e['name']}` [{e['technique']}]" for e in items))
    if dropped:
        lines += ["", "## Experiments filed under an uninformative technique", "",
                  "No ontology id to grade, so these are matched on the experiment's name only.",
                  ""]
        for study, technique, accessions in dropped:
            lines.append(f"- {study}: `{technique}` ({', '.join(accessions)})")
    lines += [
        "",
        "## Reading this",
        "",
        "- ImmPort's grain is the technique: one OBI id per technique name, shared by every "
        "experiment filed under it. Level 1 is therefore the dependable link and Level 2 is "
        "often AMBIGUOUS by nature.",
        "- NAMED by shared words is a suggestion with its evidence shown, not a verified link.",
        "- NONE is not an agent error. ImmPort registers the data a study deposited, not every "
        "assay its paper reports.",
        "- A study flagged as having papers we do not hold may have unreached experiments that "
        "belong to those papers.",
    ]
    return lines


if __name__ == "__main__":
    main()
