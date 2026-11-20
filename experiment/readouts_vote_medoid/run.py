"""Round 1's lenient tie-break, before and after, measured on the stored v3 replies. Free.

Until 2026-11-02 `assay_consensus._vote_text` delivered the *shortest* of a group of free-text
values that agreed leniently (containment or token Jaccard >= 0.5). On SDY1289's gene array that
delivered "gene expression levels" over two runs that both wrote whole-blood RNA on Illumina
BeadChips: a detail a majority of runs asserted, voted away. The tie-break now prefers the value
sharing the most content words with the other values, and only then the shortest.

This script re-votes each v3 registry's three stored extraction replies (`assays_raw.json`,
round `extract`) under both rules and prints every delivered cluster whose
`standard_technique_name`, `sample_type` or `readouts` changed. It then checks that the new
`readouts` do not alter round 5: each changed value is substituted into the registry's
canonicalized `assays.json` (only where the entry still carries the old voted value, so a
correction from round 3 is never overwritten) and `canonical_groups` is run again, before and
after, to recount the blocked folds. Nothing on disk is written except the run log.

    python3 experiment/readouts_vote_medoid/run.py
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.assay_consensus import (  # noqa: E402
    _agree, _anchor_rank, _fold, _vote, _vote_text, cluster_for_vote,
)
from app.agent.assay_extractor import clean_registry, paper_names, parse_registry_json  # noqa: E402
from app.agent.assay_merger import blocked_folds, canonical_groups  # noqa: E402
from app.agent.assay_registry import normalize_assay_name  # noqa: E402

V3 = _REPO_ROOT / "data" / "benchmark_agent_assays" / "assay_result_v3"
FIELDS = ("standard_technique_name", "sample_type", "readouts")


def vote_text_shortest(values: list[object]) -> object:
    """The rule before 2026-11-02: exact majority, else the shortest of the best-agreeing."""
    counts: dict[str, int] = {}
    for value in values:
        counts[_fold(value)] = counts.get(_fold(value), 0) + 1
    if max(counts.values(), default=0) >= 2:
        return _vote(values)
    best, best_key = values[0] if values else None, None
    for i, value in enumerate(values):
        score = sum(1 for j, other in enumerate(values) if j != i and _agree(value, other))
        if score == 0:
            continue
        key = (-score, len(_fold(value)), i)
        if best_key is None or key < best_key:
            best, best_key = value, key
    return best


def _runs(registry_dir: Path) -> list[tuple[str, dict]]:
    raw = json.loads((registry_dir / "assays_raw.json").read_text(encoding="utf-8"))["extract"]
    return [(label, clean_registry(parse_registry_json(raw[label]["reply"])))
            for label in sorted(raw)]


def _clusters(runs: list[tuple[str, dict]]):
    """Delivered clusters as (first key, members in anchor order)."""
    by_label = dict(runs)
    labels = [label for label, _ in runs]
    clusters, attached = cluster_for_vote(runs)
    needed = len(runs) // 2 + 1
    for cluster in clusters:
        if sum(1 for label in labels if cluster.get(label)) < needed:
            continue
        nodes = sorted(((label, key) for label in labels for key in cluster.get(label, [])),
                       key=lambda node: (node in attached, _anchor_rank(by_label[node[0]][node[1]])))
        yield nodes[0][1], [by_label[label][key] for label, key in nodes]


def _forms(entry: dict) -> set[str]:
    names = paper_names(entry) + [a for a in (entry.get("aliases") or []) if isinstance(a, str)]
    return {normalize_assay_name(n) for n in names} - {""}


def main() -> None:
    lines: list[str] = []
    out = lambda s="": (print(s), lines.append(s))  # noqa: E731
    out(f"readouts vote tie-break: shortest -> most shared words, on {V3.relative_to(_REPO_ROOT)}")
    out(f"run {_dt.date.today().isoformat()}")
    out()
    total = changed = {f: 0 for f in FIELDS}
    changed = {f: 0 for f in FIELDS}
    n_clusters = 0
    blocked_before = blocked_after = 0
    substituted = 0
    for registry_dir in sorted(p for p in V3.iterdir() if (p / "assays_raw.json").exists()):
        runs = _runs(registry_dir)
        if len(runs) < 2:
            continue
        new_readouts: dict[str, tuple[str, str]] = {}  # voted key -> (old, new)
        voted_forms: dict[str, set[str]] = {}
        for key, members in _clusters(runs):
            n_clusters += 1
            for field in FIELDS:
                values = [m.get(field) for m in members]
                old, new = vote_text_shortest(values), _vote_text(values)
                if _fold(old) == _fold(new):
                    continue
                changed[field] += 1
                out(f"[{registry_dir.name}] {key} / {field}")
                for v in values:
                    out(f"      - {v}")
                out(f"    old: {old}")
                out(f"    new: {new}")
                if field == "readouts":
                    new_readouts[key] = (str(old), str(new))
                    voted_forms[key] = set().union(*(_forms(m) for m in members))
        # Round 5 recount on the canonicalized registry, with the new readouts substituted.
        assays_path, obi_path = registry_dir / "assays.json", registry_dir / "assays_OBI.json"
        if not assays_path.exists() or not obi_path.exists():
            continue
        assays = json.loads(assays_path.read_text(encoding="utf-8"))
        obi = json.loads(obi_path.read_text(encoding="utf-8"))
        before = blocked_folds(canonical_groups(assays, obi))
        blocked_before += len(before)
        patched = {k: dict(v) for k, v in assays.items()}
        for key, (old, new) in new_readouts.items():
            for akey, entry in patched.items():
                if _forms(entry) & voted_forms[key] and _fold(entry.get("readouts")) == _fold(old):
                    entry["readouts"] = new
                    substituted += 1
                    out(f"    substituted into {registry_dir.name} / {akey}")
        after = blocked_folds(canonical_groups(patched, obi))
        blocked_after += len(after)
        if len(after) != len(before):
            out(f"!! {registry_dir.name}: blocked folds {len(before)} -> {len(after)}")
            for r in after:
                out(f"      after: {r['member']} vs {r['anchor']}: {r['reason']}")
    out()
    out(f"delivered clusters: {n_clusters}")
    for field in FIELDS:
        out(f"  {field}: {changed[field]} delivered value(s) changed")
    out(f"new readouts substituted into canonicalized registries: {substituted}")
    out(f"blocked folds (round 5): {blocked_before} before, {blocked_after} after")
    log = Path(__file__).with_name(f"run_{_dt.date.today().isoformat()}.txt")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwritten {log.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
