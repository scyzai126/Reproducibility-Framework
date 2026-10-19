"""Round 1 by majority: align several extractions of one paper and keep what most of them found.

One extraction call at temperature 0 does not give one answer. Measured over three papers run
twice each with the same prompt, two of the three came back with an inventory one entry longer
in one run than the other -- a secondary flow-cytometry panel the model sometimes lists and
sometimes folds into the main flow entry -- and free-text fields were reworded on a third of the
entries. Rounds 2-4 then cost ~25 calls to verify and map whichever inventory happened to come
out. Three extractions cost two more calls and turn that into a vote.

`consensus` takes the registries of N extraction calls and returns (registry, minority):

  * entries are aligned across runs without a model, in two tiers: first by their normalized
    `name_in_paper`, which is exact and is what the extractor keys by; then an entry only one run
    produced may join a cluster through `same_entry` (a shared alias, overlapping evidence
    sentence ids, or the same technique with one quote inside the other) -- but never a cluster
    that already holds an entry from its own run, so two entries a run deliberately kept apart
    (an ELISA and an `ELISA kits` aliased "ELISA") are never voted into one;
  * an aligned cluster present in a majority of runs becomes an entry; one present in fewer goes
    to `minority`, keyed by its own name, with the runs it appeared in -- reported as a MINORITY
    line rather than silently shipped or dropped;
  * each field takes the value at least two runs agree on (case and whitespace folded), else the
    first run's; aliases are the union, since an alias the paper does not contain is caught for
    free by round 2's string check, while one voted away is never recovered -- except a wording
    that is another delivered entry's name. A dissenting run that merged two assays lists the
    other one's name among its aliases, and the vote must not carry that over: SDY1264's CPE
    entry came out aliased "PRNT", and round 2 then had to contradict it. So a member that
    joined its cluster in the second tier -- a lone entry attached by alias, sentence or quote,
    which is exactly what a merged dissenting entry is -- contributes no wording that another
    delivered entry's first-tier members already use. First-tier members contribute everything,
    so a Methods heading several entries legitimately share stays an alias of each.

With one registry it is the identity: the single extraction, untouched.
"""

from __future__ import annotations

import re

from app.agent.assay_extractor import ENTRY_FIELDS, paper_names
from app.agent.assay_registry import normalize_assay_name
from app.agent.assay_verifier import _squash


# ── aligning ─────────────────────────────────────────────────────────────────

def _forms(key: str, entry: dict) -> set[str]:
    forms = {normalize_assay_name(key)}
    forms |= {normalize_assay_name(n) for n in paper_names(entry)}
    forms |= {normalize_assay_name(a) for a in (entry.get("aliases") or []) if isinstance(a, str)}
    return {f for f in forms if f}


def _ids(entry: dict) -> set[str]:
    return {str(s) for s in ((entry.get("evidence") or {}).get("sentence_ids") or [])}


def _quote(entry: dict) -> str:
    return _squash(str((entry.get("evidence") or {}).get("quote") or "")).lower()


def _technique(entry: dict) -> str:
    return " ".join(str(entry.get("standard_technique_name") or "").split()).lower()


def same_entry(a_key: str, a: dict, b_key: str, b: dict) -> bool:
    """Whether two entries from different runs describe the same assay. No model."""
    if _forms(a_key, a) & _forms(b_key, b):
        return True
    if _ids(a) & _ids(b):
        return True
    qa, qb = _quote(a), _quote(b)
    return bool(_technique(a)) and _technique(a) == _technique(b) and bool(qa) and bool(qb) \
        and (qa in qb or qb in qa)


# ── voting ───────────────────────────────────────────────────────────────────

def _fold(value: object) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "").lower()).strip()


def _vote(values: list[object]) -> object:
    """The value at least two runs agree on after folding, in its first spelling; else the first."""
    counts: dict[str, int] = {}
    first_spelling: dict[str, object] = {}
    for value in values:
        key = _fold(value)
        counts[key] = counts.get(key, 0) + 1
        first_spelling.setdefault(key, value)
    best = max(counts.items(), key=lambda item: (item[1], -list(counts).index(item[0])))
    return first_spelling[best[0]] if best[1] >= 2 else values[0]


def _voted_name(members: list[dict]) -> str:
    return str(_vote([paper_names(m)[0] if paper_names(m) else "" for m in members]) or
               (paper_names(members[0]) or [""])[0])


def _wordings(entry: dict) -> list[str]:
    return [w for w in [*paper_names(entry), *(entry.get("aliases") or [])]
            if isinstance(w, str) and w.strip()]


def _merge(members: list[dict], guarded: frozenset[int] = frozenset(),
           reserved: frozenset[str] = frozenset()) -> dict:
    """One entry from the cluster's members, field by field, in ENTRY_FIELDS order.

    Members at the indices in `guarded` joined the cluster in the second tier; their wordings
    that normalize to something in `reserved` -- the other delivered entries' own wordings --
    are a sibling's, not aliases of this entry.
    """
    name = _voted_name(members)
    chosen = normalize_assay_name(name)

    aliases: list[str] = []
    seen = {chosen}
    for i, member in enumerate(members):
        for wording in _wordings(member):
            form = normalize_assay_name(wording)
            if not form or form in seen or (i in guarded and form in reserved):
                continue
            seen.add(form)
            aliases.append(wording)

    quotes = [str((m.get("evidence") or {}).get("quote") or "") for m in members]
    quote = _vote(quotes)
    winner = next(m for m, q in zip(members, quotes) if q == quote)
    claims = [m.get("generate_claim") for m in members]
    claim = _vote(claims)

    entry = {
        "name_in_paper": name,
        "standard_technique_name": _vote([m.get("standard_technique_name") for m in members]),
        "aliases": aliases,
        "sample_type": _vote([m.get("sample_type") for m in members]),
        "readouts": _vote([m.get("readouts") for m in members]),
        "generate_claim": claim if isinstance(claim, bool) else None,
        "source": None,
        "evidence": {"section": (winner.get("evidence") or {}).get("section"),
                     "sentence_ids": [], "quote": quote or None},
    }
    return {field: entry[field] for field in ENTRY_FIELDS}


def _unique(key: str, taken: set[str]) -> str:
    base, n = key, 2
    while key in taken:
        key, n = f"{base} ({n})", n + 1
    taken.add(key)
    return key


def _strict_key(key: str, entry: dict) -> str:
    names = paper_names(entry)
    return normalize_assay_name(names[0] if names else key) or normalize_assay_name(key) or key


def cluster_for_vote(runs: list[tuple[str, dict]]
                     ) -> tuple[list[dict[str, list[str]]], set[tuple[str, str]]]:
    """Two-tier alignment for voting: exact name first, then `same_entry` for lone entries.
    Returns the clusters and the (label, key) nodes that joined one in the second tier.

    Tier 1 groups entries whose normalized `name_in_paper` is identical. Tier 2 takes each
    cluster that only one run produced and, in order, attaches it to the first earlier-or-later
    cluster one of whose members `same_entry` matches -- provided that cluster has no member from
    the same run. That proviso is the whole point: a run's two entries are two assays by that
    run's judgement, and the vote must count them, not merge them.
    """
    registries = dict(runs)
    clusters: list[dict[str, list[str]]] = []
    by_strict: dict[str, dict[str, list[str]]] = {}
    for label, registry in runs:
        for key, entry in registry.items():
            strict = _strict_key(key, entry)
            if strict not in by_strict:
                by_strict[strict] = {}
                clusters.append(by_strict[strict])
            by_strict[strict].setdefault(label, []).append(key)

    def matches(cluster: dict[str, list[str]], label: str, key: str) -> bool:
        return any(same_entry(k, registries[l][k], key, registries[label][key])
                   for l, keys in cluster.items() for k in keys)

    merged: list[dict[str, list[str]]] = []
    attached: set[tuple[str, str]] = set()
    for cluster in clusters:
        if len(cluster) == 1:
            (label, keys), = cluster.items()
            if len(keys) == 1:
                home = next((c for c in merged if label not in c and matches(c, label, keys[0])),
                            None)
                if home is not None:
                    home.setdefault(label, []).append(keys[0])
                    attached.add((label, keys[0]))
                    continue
        merged.append(cluster)
    return merged, attached


def consensus(registries: list[dict]) -> tuple[dict, dict]:
    """(registry, minority) from N extractions of one paper. One registry comes back untouched."""
    if not registries:
        return {}, {}
    if len(registries) == 1:
        return dict(registries[0]), {}
    runs = [(f"run{i + 1}", registry) for i, registry in enumerate(registries)]
    labels = [label for label, _ in runs]
    by_label = dict(runs)
    needed = len(runs) // 2 + 1

    registry: dict = {}
    minority: dict = {}
    taken: set[str] = set()
    clusters, attached = cluster_for_vote(runs)
    delivered: list[tuple[list[dict], frozenset[int], str]] = []
    for cluster in clusters:
        present = [label for label in labels if cluster.get(label)]
        nodes = [(label, key) for label in labels for key in cluster.get(label, [])]
        members = [by_label[label][key] for label, key in nodes]
        first_key = nodes[0][1]
        if len(present) < needed:
            minority[_unique(first_key, taken)] = {
                "entry": members[0], "runs": present, "of": len(runs)}
            continue
        guarded = frozenset(i for i, node in enumerate(nodes) if node in attached)
        delivered.append((members, guarded, first_key))
    # Every delivered cluster's own wordings -- those of its first-tier members -- are known
    # before any entry is built, so a second-tier member cannot hand a sibling's wording to it.
    own = [frozenset(normalize_assay_name(w) for i, m in enumerate(members) if i not in guarded
                     for w in _wordings(m))
           for members, guarded, _ in delivered]
    for i, (members, guarded, first_key) in enumerate(delivered):
        reserved = frozenset(w for j, forms in enumerate(own) if j != i for w in forms if w)
        entry = _merge(members, guarded, reserved)
        registry[_unique(str(entry["name_in_paper"]) or first_key, taken)] = entry
    return registry, minority
