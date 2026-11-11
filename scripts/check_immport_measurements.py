#!/usr/bin/env python3
"""Does every assay ImmPort recorded for a study appear in the assays we extracted?

ImmPort registers only part of what a paper did -- `experiment.measurement_technique`, one row
per deposited experiment -- so the check is one-directional: an assay we found that ImmPort
never recorded is normal and is not reported here. The claim under test is the other way round.

Two things make a naive comparison misread:

* **ImmPort registers per STUDY, we extract per PAPER.** A study's technique may be described in
  a different paper of the same study. Studies whose ImmPort papers we do not all hold are
  counted separately, because a MISS there is not evidence against the claim.
* **`measurement_technique` is a controlled term**, so compare by ontology id, not by string.
  `lk_exp_measurement_tech.link` carries an OBI PURL for most of them; `Other` carries no
  information at all and is dropped.

Matching is graded, best level wins, using the full obi.obo is_a graph so a difference of
granularity (ImmPort "Luminex xMAP" vs our "analyte detection by flow based bead assay") does
not read as a miss:

    EXACT       our obi_id is one of the ids ImmPort's term resolves to
    DESCENDANT  ours is below ImmPort's term in is_a   (we were more specific)
    ANCESTOR    ours is above it                        (we were broader)
    SIBLING     neither, but they share a direct parent -- the same family named differently
    EXPNAME     ImmPort's free-text `experiment.name` and one of our wordings denote the same
                assay, whichever of the two is the longer string
    NAME        ImmPort's technique name matches one of our wordings, aliases or technique name
    MISS        none of the above -- printed with the study's whole entry list, to be judged

SIBLING exists because OBI's is_a is flatter than intuition and a strict ancestry test reads
agreement as disagreement. `real time reverse-transcription PCR` is *not* under `real time PCR`
-- both hang off `polymerase chain reaction assay` -- and `CyTOF` is not under `flow cytometry`;
both hang off `cytometry assay`. A paper whose entry is one of those did record what ImmPort
registered.

It requires a shared **direct** parent, deliberately. Any two assays share plenty of upper-level
ancestors, so "they meet somewhere below the root" matches almost everything: it paired ImmPort's
neutralization assay with our transcription array, and CyTOF with hemagglutination inhibition.
One is_a step is the whole difference between a sibling and a stranger.

Even one step is not enough on its own: a few direct parents group assays by what is measured
rather than by method, and children of those are not siblings in any useful sense. `HUB_PARENTS`
holds them.

Read-only: SELECTs against MYSQL_URL and the registries on disk. No LLM call, nothing written
except the report.

    python3 scripts/check_immport_measurements.py
    python3 scripts/check_immport_measurements.py --study SDY984 SDY1669
    python3 scripts/check_immport_measurements.py --json out.json
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from compare_assay_benchmark import ObiGraph, _surface_forms, normalize  # noqa: E402

REGISTRY_DIR = _REPO_ROOT / "data" / "31paper_assays" / "assay_result_v3"
REPORT = _REPO_ROOT / "docs" / "immport_measurement_coverage_2026-11.md"
#: Records that a measurement happened and nothing about which one.
UNINFORMATIVE = {"other", "not specified", "unknown", ""}
#: Every assay shares it, so it can never stand as evidence that two terms are the same family.
ASSAY_ROOT = "OBI:0000070"
#: Parents too broad for SIBLING, for the same reason as the root. These group assays by **what
#: is measured** or **on what sample**, never by technique, so two children of one of them can be
#: any two methods at all: ELISA, cytometric bead array and neutralizing-antibody titer all hang
#: directly off `analyte assay`. Found by the pairs they produced — ImmPort's neutralization
#: titer matched to our ELISA (SDY1289), ImmPort's ELISA to our bead array (SDY1655) — neither of
#: which is the same assay. Breadth alone does not identify them (`cytometry assay` has 69 direct
#: children and is a real family); the test is whether the node names a method.
HUB_PARENTS = frozenset({
    ASSAY_ROOT,
    "OBI:0000443",   # analyte assay — 89 direct children, grouped by having an analyte
    "OBI:0003040",   # blood assay — 331 direct children, grouped by the specimen
    "OBI:2100023",   # protein assay — 35 direct children, grouped by the analyte class
})
#: `link` holds one or more ontology PURLs, sometimes several separated by " ; ".
#: NCIT local ids carry a letter ("NCIT_C18113"), so the numeric part alone would drop them and
#: a technique whose only link is an NCIT term would read as having no ontology id at all.
_PURL = re.compile(r"obo/(OBI|NCIT|CHMO|EFO|BAO)_([A-Za-z]?\d+)")


def mysql_url() -> str:
    """The sync form of MYSQL_URL from .env — this module only ever runs SELECTs."""
    env = (_REPO_ROOT / ".env").read_text(encoding="utf-8")
    match = re.search(r"MYSQL_URL=(\S+)", env)
    if not match:
        raise SystemExit("MYSQL_URL not found in .env")
    return match.group(1).replace("mysql+aiomysql", "mysql+pymysql")


def term_ids(link: str | None) -> list[str]:
    """Ontology ids in a lookup row's `link`, OBI first — ours are OBI, so prefer those."""
    found = [f"{prefix}:{digits}" for prefix, digits in _PURL.findall(link or "")]
    return sorted(dict.fromkeys(found), key=lambda t: (not t.startswith("OBI:"), t))


def immport_rows(engine, studies: list[str]):
    """((study, technique) pairs, {technique: link}, {(study, technique): [experiment.name, ...]}).

    `experiment.name` is free text the depositor wrote for *this* experiment, while
    `measurement_technique` is one pick from a 102-row controlled list, so the name often carries
    what the controlled term loses: SDY1325's technique reads `Neutralizing Antibody Titer Assay`
    and its name reads `Serum bactericidal assay`, and SDY1373's RNA-seq data is filed under
    `Transcription profiling by array` while its name says `Next Generation Sequencing RNA Seq
    data ...`. Judging on the controlled term alone reports both as misses.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = list(conn.execute(
            text("SELECT DISTINCT study_accession, measurement_technique, name FROM experiment "
                 "WHERE study_accession IN :s AND measurement_technique IS NOT NULL"),
            {"s": tuple(studies)},
        ))
        links = {
            row[0]: row[1]
            for row in conn.execute(text("SELECT name, link FROM lk_exp_measurement_tech"))
        }
    names: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for study, technique, name in rows:
        if name and name not in names[(study, technique)]:
            names[(study, technique)].append(name)
    return sorted({(r[0], r[1]) for r in rows}), links, dict(names)


def immport_papers(engine, studies: list[str]) -> dict[str, set[str]]:
    """{study: every PMID ImmPort links to it} — the basis for 'do we hold all its papers'."""
    from sqlalchemy import text

    with engine.connect() as conn:
        out: dict[str, set[str]] = collections.defaultdict(set)
        for row in conn.execute(
            text("SELECT study_accession, pubmed_id FROM study_pubmed WHERE study_accession IN :s"),
            {"s": tuple(studies)},
        ):
            out[row[0]].add(str(row[1]))
    return out


def our_entries(registry_dir: Path) -> dict[str, list[dict]]:
    """{study: entries from every paper of that study}, each entry flattened for matching."""
    by_study: dict[str, list[dict]] = collections.defaultdict(list)
    for folder in sorted(registry_dir.iterdir()):
        if not folder.is_dir() or "_SDY" not in folder.name:
            continue
        pmid, study = folder.name.split("_")[0], folder.name.split("_")[1]
        obi = _read(folder / "assays_OBI.json") or {}
        bench = _read(folder / "assays_benchmark.json") or {}
        for key, record in bench.items():
            if not isinstance(record, dict):
                continue
            mapped = obi.get(key) if isinstance(obi.get(key), dict) else {}
            by_study[study].append({
                "pmid": pmid,
                "key": key,
                "obi_id": mapped.get("obi_id"),
                "obi_label": mapped.get("obi_label"),
                "forms": _surface_forms(record.get("name_in_paper"), record.get("aliases"))
                + [normalize(record.get("standard_technique_name") or "")],
            })
    return by_study


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


#: An `EXPNAME` match needs at least this many whole words, so a one-token form cannot carry a
#: pair on its own. `sba` or `elisa` appearing somewhere inside a free-text experiment name is
#: not evidence; `rna seq` or `serum bactericidal assay` is.
_EXPNAME_MIN_WORDS = 2


def _expname_match(exp_names: list[str], forms: set[str]) -> bool:
    """Does an ImmPort experiment name and one of our wordings denote the same assay?

    Either may be the longer string: the depositor writes `Serum bactericidal assay` where we
    write the same words, and `Cytokine Array` where the paper writes the full product name
    `Human Cytokine Array/Chemokine Array 71-403 Plex Panel (HD71)`. Containment is on whole
    words -- a bare substring would let `array` inside `microarray` pair anything.
    """
    for raw in exp_names:
        exp = normalize(raw)
        if not exp:
            continue
        for form in forms:
            if not form or form == exp:
                if form and form == exp:
                    return True
                continue
            longer, shorter = (exp, form) if len(exp) >= len(form) else (form, exp)
            if len(shorter.split()) < _EXPNAME_MIN_WORDS:
                continue
            if re.search(rf"(?:^| ){re.escape(shorter)}(?:$| )", longer):
                return True
    return False


def classify(ids: list[str], technique: str, entries: list[dict], obi: ObiGraph,
             exp_names: list[str] | None = None) -> tuple[str, dict | None]:
    """Best match level for one ImmPort technique against a study's entries."""
    wanted = set(ids)
    # The lookup's own name may itself be an OBI label ("Histological Assay").
    resolved = obi.resolve(technique)
    if resolved:
        wanted.add(resolved)
    want_ancestors = {a for term in wanted for a in obi.ancestors(term)}
    # Direct parents only — see the SIBLING note in the module docstring.
    want_parents = {p for term in wanted for p in obi.parents.get(term, [])}

    best = ("MISS", None)
    rank = {"MISS": 0, "SIBLING": 1, "EXPNAME": 2, "NAME": 3,
            "ANCESTOR": 4, "DESCENDANT": 5, "EXACT": 6}
    name_forms = {normalize(technique)}
    for entry in entries:
        level = None
        ours = entry.get("obi_id")
        if ours and ours in wanted:
            level = "EXACT"
        elif ours and wanted & obi.ancestors(ours):
            level = "DESCENDANT"
        elif ours and ours in want_ancestors:
            level = "ANCESTOR"
        elif name_forms & set(entry["forms"]):
            level = "NAME"
        elif _expname_match(exp_names or [], set(entry["forms"])):
            level = "EXPNAME"
        elif ours and (set(obi.parents.get(ours, [])) & want_parents) - HUB_PARENTS:
            level = "SIBLING"
        if level and rank[level] > rank[best[0]]:
            best = (level, entry)
    return best


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry-dir", type=Path, default=REGISTRY_DIR)
    parser.add_argument("--study", nargs="+", default=None, help="Limit to these studies")
    parser.add_argument("--json", type=Path, default=None, help="Also write machine-readable rows")
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    from sqlalchemy import create_engine

    entries_by_study = our_entries(args.registry_dir)
    studies = sorted(entries_by_study)
    if args.study:
        studies = [s for s in studies if s in set(args.study)]
    if not studies:
        raise SystemExit("no studies found")

    engine = create_engine(mysql_url())
    pairs, links, exp_names = immport_rows(engine, studies)
    papers = immport_papers(engine, studies)
    obi = ObiGraph()

    ours_pmids = collections.defaultdict(set)
    for study, entries in entries_by_study.items():
        ours_pmids[study] = {e["pmid"] for e in entries}
    complete = {s for s in studies if not (papers.get(s, set()) - ours_pmids.get(s, set()))}

    rows, dropped = [], []
    seen: set[tuple[str, str]] = set()
    for study, technique in pairs:
        if study not in studies:
            continue
        if normalize(technique) in UNINFORMATIVE:
            dropped.append((study, technique))
            continue
        ids = term_ids(links.get(technique))
        # Two ImmPort names can share an id (Virus Neutralization / Neutralizing Antibody Titer).
        fingerprint = (study, ids[0] if ids else normalize(technique))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        level, hit = classify(ids, technique, entries_by_study[study], obi,
                              exp_names.get((study, technique)))
        rows.append({
            "study": study, "technique": technique, "ids": ids, "level": level,
            "complete": study in complete,
            "experiment_names": exp_names.get((study, technique), []),
            "matched": None if hit is None else {
                "pmid": hit["pmid"], "key": hit["key"],
                "obi_id": hit["obi_id"], "obi_label": hit["obi_label"]},
        })

    _report(rows, dropped, complete, studies, papers, ours_pmids, entries_by_study, args.report)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        print(f"wrote {args.json}")


def _report(rows, dropped, complete, studies, papers, ours_pmids, entries_by_study, path: Path):
    def tally(subset):
        return collections.Counter(r["level"] for r in subset)

    full = [r for r in rows if r["complete"]]
    partial = [r for r in rows if not r["complete"]]
    lines = [
        "# Does every assay ImmPort recorded appear in what we extracted?",
        "",
        f"{len(studies)} studies, {len(rows)} (study, technique) pairs after dropping "
        f"{len(dropped)} uninformative row(s). One-directional: assays we found that ImmPort "
        "never recorded are expected and not reported.",
        "",
        "| group | pairs | EXACT | DESCENDANT | ANCESTOR | SIBLING | NAME | EXPNAME | MISS |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, subset in (("we hold every ImmPort paper", full),
                         ("we hold only some of them", partial)):
        c = tally(subset)
        lines.append(f"| {name} | {len(subset)} | {c['EXACT']} | {c['DESCENDANT']} | "
                     f"{c['ANCESTOR']} | {c['SIBLING']} | {c['NAME']} | {c['EXPNAME']} | "
                     f"{c['MISS']} |")

    for title, subset, note in (
        ("MISS where we hold every paper of the study — these test the claim", full,
         "A miss here cannot be blamed on a paper we do not have."),
        ("MISS where ImmPort links papers we did not process", partial,
         "The technique may well be described in one of those papers."),
    ):
        misses = [r for r in subset if r["level"] == "MISS"]
        lines += ["", f"## {title}", "", note, ""]
        if not misses:
            lines.append("None.")
            continue
        for row in misses:
            study = row["study"]
            lines += [
                f"### {study} — ImmPort: `{row['technique']}` "
                f"({', '.join(row['ids']) or 'no ontology id'})",
                "",
                f"ImmPort papers: {sorted(papers.get(study, []))}; "
                f"ours: {sorted(ours_pmids.get(study, []))}",
                "",
                "What we extracted for this study:",
                "",
            ]
            for entry in entries_by_study[study]:
                lines.append(f"- `{entry['key']}` — {entry['obi_id'] or 'unmapped'} "
                             f"{entry['obi_label'] or ''} (pmid {entry['pmid']})")
            lines.append("")

    if dropped:
        lines += ["", "## Dropped as uninformative", ""]
        for study, technique in dropped:
            lines.append(f"- {study}: `{technique}`")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12]))
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
