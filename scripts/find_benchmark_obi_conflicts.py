"""Find assays the curator benchmark names the same way in two papers but maps to different OBI terms.

This reads the benchmark files only -- no registry, no LLM. Two checks:

1. Same `name_in_paper` (normalized) -> more than one OBI term across the benchmark files.
2. An id/label pair that disagrees with `data/OBI/obi.obo` (the id names a different term).

Reads  : data/benchmark_assay/*.json, data/OBI/obi.obo
Writes : data/benchmark_assay/comparison/benchmark_same_name_different_obi.{csv,md}
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_assay" / "benchmark_assay_v4"
REGISTRY_DIR = REPO_ROOT / "data" / "31paper_assays" / "assay_result_v1"
OBO_PATH = REPO_ROOT / "data" / "OBI" / "obi.obo"
OUT_DIR = BENCHMARK_DIR.parent / "comparison"
OUT_STEM = "benchmark_same_name_different_obi"

_BENCH_NAME = re.compile(r"^(SDY\d+)(?:_(\d{7,8}))?")
_FILLER = re.compile(r"\b(assays?|analysis|analyses|tests?)\b")


def norm(name: str) -> str:
    """Matching key: lowercase, no parentheticals, no punctuation, no 'assay'/'analysis'/'test'."""
    s = re.sub(r"\(.*?\)", " ", name.lower())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(_FILLER.sub(" ", s).split())


def read_obi(entry: dict) -> tuple[str | None, str | None]:
    """(obi_id, obi_label) from any of the three layouts the curators used; '' counts as unmapped."""
    obi = entry.get("OBI ontology") or entry.get("OBI_ontology") or {}
    obi_id = obi.get("obi_id") or obi.get("id") or None
    label = obi.get("obi_label") or obi.get("label") or None
    unmapped = {"null", "none"}
    return (None if str(obi_id).lower() in unmapped else obi_id,
            None if str(label).lower() in unmapped else label)


def obo_labels() -> dict[str, str]:
    """OBI id -> its label, from obi.obo."""
    labels, current = {}, None
    for line in OBO_PATH.read_text().splitlines():
        if line.startswith("id: "):
            current = line[4:].strip()
        elif line.startswith("name: ") and current:
            labels[current] = line[6:].strip()
            current = None
    return labels


def benchmark_files() -> list[Path]:
    """Every benchmark file, preferring `_v2` when an older file for the same paper also exists."""
    files = sorted(BENCHMARK_DIR.glob("*.json"))
    keep = []
    for path in files:
        if "v2" not in path.stem:
            m = _BENCH_NAME.match(path.name)
            prefix = m.group(0) if m else path.stem
            if any(o != path and o.name.startswith(prefix) and "v2" in o.stem for o in files):
                continue
        keep.append(path)
    return keep


def pmid_for(path: Path) -> str:
    m = _BENCH_NAME.match(path.name)
    if not m:
        return ""
    study, pmid = m.group(1), m.group(2)
    if pmid:
        return pmid
    dirs = [d for d in REGISTRY_DIR.glob(f"*_{study}*") if d.is_dir()
            and re.fullmatch(rf"\d+_{study}(_pdf)?", d.name)]
    return dirs[0].name.split("_")[0] if len(dirs) == 1 else ""


def main() -> None:
    rows = []
    for path in benchmark_files():
        m = _BENCH_NAME.match(path.name)
        study, pmid = (m.group(1) if m else ""), pmid_for(path)
        for entry in json.loads(path.read_text()).values():
            obi_id, label = read_obi(entry)
            names = entry.get("name_in_paper")
            for name in names if isinstance(names, list) else [names]:
                if name:
                    rows.append({"match_key": norm(name), "study": study, "pmid": pmid,
                                 "benchmark_file": path.name, "name_in_paper": name,
                                 "obi_id": obi_id or "", "obi_label": label or "(unmapped)"})

    by_key = defaultdict(list)
    for r in rows:
        by_key[r["match_key"]].append(r)
    conflicts = {k: v for k, v in sorted(by_key.items())
                 if len({(r["obi_id"], r["obi_label"]) for r in v}) > 1}

    official = obo_labels()
    bad_pairs = defaultdict(list)
    for r in rows:
        if r["obi_id"] and official.get(r["obi_id"]) != r["obi_label"]:
            bad_pairs[(r["obi_id"], r["obi_label"])].append(r)
    id_conflicts = dict(sorted(bad_pairs.items()))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["match_key", "study", "pmid", "benchmark_file", "name_in_paper", "obi_id", "obi_label"]
    with open(OUT_DIR / f"{OUT_STEM}.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for group in conflicts.values():
            writer.writerows(group)

    md = ["# Benchmark: same assay name, different OBI", "",
          f"Benchmark files read: {len(benchmark_files())} (`_v2` preferred over older files "
          "for the same paper). Names match after lowercasing and dropping parentheticals, "
          "punctuation and the words assay/analysis/test.", "",
          f"## Same name in paper -> different OBI ({len(conflicts)})", ""]
    for key, group in conflicts.items():
        md += [f"### {key}", "", "| study | pmid | name_in_paper | OBI |", "|---|---|---|---|"]
        for r in group:
            obi = f"{r['obi_label']} ({r['obi_id']})" if r["obi_id"] else r["obi_label"]
            md.append(f"| {r['study']} | {r['pmid']} | {r['name_in_paper']} | {obi} |")
        md.append("")
    md += [f"## id/label pair disagrees with obi.obo ({len(id_conflicts)})", "",
           "| benchmark obi_id | benchmark obi_label | obi.obo label for that id | studies |",
           "|---|---|---|---|"]
    for (obi_id, label), group in id_conflicts.items():
        studies = ", ".join(sorted({r["study"] for r in group}))
        md.append(f"| {obi_id} | {label} | {official.get(obi_id, '(not in obi.obo)')} | {studies} |")
    md.append("")
    (OUT_DIR / f"{OUT_STEM}.md").write_text("\n".join(md))

    print(f"{len(conflicts)} name conflicts, {len(id_conflicts)} id/label conflicts")
    for key, group in conflicts.items():
        print(f"  {key}: " + "; ".join(f"{r['study']} -> {r['obi_label']}" for r in group))
    for (obi_id, label), group in id_conflicts.items():
        print(f"  {obi_id} '{label}' (obi.obo: '{official.get(obi_id, 'not in obi.obo')}'): "
              + ", ".join(sorted({r["study"] for r in group})))


if __name__ == "__main__":
    main()
