"""Round 5: key the registry by its OBI term, and fold entries that share a term or a technique.

Extraction is a single whole-paper call keyed by the paper's own wording, so one assay described
under two Methods subheadings lands two entries -- SDY1260 carries both `ELISA` (serum
anti-meningococcal antibodies) and `ELISA kits` (cytokines in culture supernatants). Nothing
downstream caught it: `clean_registry` is a dict comprehension, and the verifier judges one entry
at a time against the paper, never against a sibling.

**Two entries are one assay when they share an OBI term or a technique.** The term is the OBI
label the entry mapped to; the technique is its `normalized_name`, the extractor's judgement of
the measurement method. Either link is enough, and links chain: an entry mapped to one term and
sharing its technique with an unmapped entry pulls that entry in too. The technique link is what
catches an assay the paper named after a protocol section ("Whole transcriptome profiling of NK
cell subsets") and OBI therefore left unmapped, beside the same technique under a plainer name.

The merged entry is keyed by the OBI label of its first mapped member, rather than by a wording
-- `name_in_paper` already records every wording, as a list. A group with no mapped member keeps
its first member's paper name as its key. When a technique link joins two different OBI labels,
the first mapped member's label wins and the merge report lists every member's own label.

The rule is coarser than the paper's own language: one OBI term covers every ELISA a paper runs,
so SDY1640's two antigen-specific ELISAs and SDY1669's plate ELISA and SIMoA assay fold together
too. That is the trade this round exists to make. Nothing is discarded in the process -- each
folded write-up's specimen, platform, readouts and quote move to `additional_evidence` on the
surviving entry, so the coarser key never costs a measurement.

Deterministic and free: no model decides any of this, and the same registry always canonicalizes
the same way.
"""

import logging

from app.agent.assay_extractor import paper_names
from app.agent.assay_registry import normalize_assay_name

logger = logging.getLogger(__name__)

#: What a folded-away entry keeps on the survivor. Its wordings are not here -- those join the
#: survivor's `name_in_paper` and `aliases` -- but everything that describes the run itself is,
#: `generate_claim` included: the survivor's is the fold's, so a member's own answer would
#: otherwise be the one thing the fold destroyed rather than recorded.
_KEPT_ON_MEMBER = ("name_in_paper", "sample_type", "readouts", "generate_claim", "source",
                   "evidence")


def _technique_key(entry: dict, mapped: dict) -> str:
    """The entry's `normalized_name`, folded for comparison; "" when it has none.

    Read from the registry entry first and the OBI record second, because the OBI mapper carries
    the field on its own output and a registry written before the field existed has it nowhere.
    """
    value = entry.get("normalized_name") or mapped.get("normalized_name") or ""
    return " ".join(str(value).split()).lower()


def canonical_groups(assays: dict, obi: dict | None = None) -> list[dict]:
    """Group the registry into assays: one group per connected set of entries.

    Two entries are linked when they map to the same OBI label, or when they carry the same
    `normalized_name` (case- and whitespace-insensitive). Links are transitive -- A~B on the term
    and B~C on the technique puts all three in one group -- so the groups are found with a
    union-find rather than by bucketing on either key alone.

    The group is keyed by the OBI label of its first mapped member, and that member's mapping is
    the group's; a group with no mapped member keeps its first member's own key. Registry order is
    preserved, both between groups and within them, so the first entry is the one whose fields
    survive the fold. Deterministic by construction -- there is no scoring step to break a tie
    differently on a rerun.
    """
    obi = obi or {}
    keys = list(assays)
    parent = {key: key for key in keys}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # The root is always the earlier entry, so a group's order never depends on which
            # link happened to be found first.
            first, second = sorted((ra, rb), key=keys.index)
            parent[second] = first

    first_by_label: dict[str, str] = {}
    first_by_technique: dict[str, str] = {}
    for key in keys:
        mapped = obi.get(key) or {}
        label = mapped.get("obi_label")
        if label:
            union(first_by_label.setdefault(label, key), key)
        technique = _technique_key(assays[key], mapped)
        if technique:
            union(first_by_technique.setdefault(technique, key), key)

    members_by_root: dict[str, list[str]] = {}
    for key in keys:
        members_by_root.setdefault(find(key), []).append(key)

    groups: list[dict] = []
    taken: set[str] = set()
    for members in members_by_root.values():
        anchor = next((m for m in members if (obi.get(m) or {}).get("obi_label")), None)
        mapped = obi.get(anchor) or {} if anchor else {}
        key = mapped.get("obi_label") if anchor else members[0]
        # An unmapped group keeps its paper wording as its key, and nothing stops that wording
        # from being another group's OBI label. Two groups on one key would overwrite each
        # other in the registry, so the later one is suffixed instead of silently lost.
        base, n = key, 2
        while key in taken:
            key, n = f"{base} ({n})", n + 1
        taken.add(key)
        groups.append({
            "key": key,
            "members": members,
            "obi_id": mapped.get("obi_id"),
            "obi_label": mapped.get("obi_label"),
            "anchor": anchor or members[0],
            # Every member's own term, so a group joined across two OBI labels by a shared
            # technique shows that in the merge report instead of hiding the second label.
            "member_labels": {m: (obi.get(m) or {}).get("obi_label") for m in members},
        })
    return groups


def merge_entries(winner: dict, losers: list[dict]) -> dict:
    """One entry carrying every member's wording, and every member's write-up.

    The winner's own fields are left exactly as the verifier and corrector left them: a fold is not
    a re-extraction, and picking field-by-field between two records would be one. What the losers
    contribute is their wordings, as names, and their records, as evidence blocks.

    `generate_claim` is the single exception, because it is the one field that is about the assay
    rather than about the write-up: two wordings of one assay are one assay, so a finding drawn
    from either was drawn from it.
    """
    merged = dict(winner)

    names: list[str] = []
    seen: set[str] = set()
    for entry in [winner] + losers:
        for name in paper_names(entry):
            form = normalize_assay_name(name)
            if form and form not in seen:
                seen.add(form)
                names.append(name)
    merged["name_in_paper"] = names

    # Aliases are what is left over once every wording is a name: an alias that repeats a name
    # says nothing, and after a fold the second entry's name is the first entry's alias.
    aliases: list[str] = []
    for entry in [winner] + losers:
        for alias in (entry.get("aliases") or []):
            if not isinstance(alias, str) or not alias.strip():
                continue
            form = normalize_assay_name(alias)
            if form and form not in seen:
                seen.add(form)
                aliases.append(alias)
    merged["aliases"] = aliases

    # True if any member reported a finding; False only when no member did and at least one said
    # so; None when nobody answered, which must not collapse into False -- see clean_entry.
    answers = [entry.get("generate_claim") for entry in [winner] + losers]
    merged["generate_claim"] = (True if any(a is True for a in answers)
                                else False if any(a is False for a in answers) else None)

    blocks = list(winner.get("additional_evidence") or [])
    for loser in losers:
        blocks.append({field: loser.get(field) for field in _KEPT_ON_MEMBER})
        # A registry canonicalized twice must not lose the blocks it already carried.
        blocks += list(loser.get("additional_evidence") or [])
    if blocks:
        merged["additional_evidence"] = blocks
    return merged


def canonicalize_registry(assays: dict, obi: dict | None = None) -> tuple[dict, dict | None, list[dict]]:
    """Re-key the registry by OBI label and fold every group. Returns (assays, obi, folds).

    `obi` is re-keyed the same way and comes back beside it, because assays.json,
    assays_benchmark.json and assays_OBI.json are looked up across each other by key -- re-keying
    one alone would break that join silently. It is None in, None out.

    `folds` records only the groups that actually merged, which is what there is to report.
    """
    groups = canonical_groups(assays, obi)
    merged: dict = {}
    obi_out: dict | None = {} if obi is not None else None
    folds: list[dict] = []

    for group in groups:
        members = group["members"]
        winner_key = members[0]
        # Every entry goes through merge_entries, folded or not, so `name_in_paper` is a list on
        # all of them. A field whose type depends on whether this round happened to fold anything
        # is a field every reader has to branch on.
        entry = merge_entries(assays[winner_key], [assays[key] for key in members[1:]])
        if len(members) > 1:
            folds.append({"key": group["key"], "obi_id": group["obi_id"],
                          "obi_label": group["obi_label"], "members": members,
                          "folded": members[1:], "member_labels": group["member_labels"]})
        merged[group["key"]] = entry
        if obi_out is not None:
            # The group's term comes from its first *mapped* member, which is not the winner when
            # an unmapped entry heads a group joined on its technique.
            mapped = dict(obi.get(group["anchor"]) or {})
            # The mapping describes the same assay as the registry entry, so it carries the same
            # merged names rather than the one wording its own lookup happened to run on.
            if mapped:
                mapped["name_in_paper"] = entry.get("name_in_paper")
            obi_out[group["key"]] = mapped

    return merged, obi_out, folds


def key_map(assays: dict, obi: dict | None = None) -> dict[str, str]:
    """Which canonical key each entry of `assays` ends up under. Free, same grouping as the fold.

    Every file written before round 5 -- assays_verification.json, assays_corrections.json,
    assays_rejected.json -- is keyed by the extractor's wording, and round 5 re-keys the registry
    by OBI label. Without this map a REVIEW verdict names an assay that is no longer a key.
    """
    return {member: group["key"]
            for group in canonical_groups(assays, obi) for member in group["members"]}


def compose_key_maps(earlier: dict[str, str] | None, later: dict[str, str]) -> dict[str, str]:
    """Chain a stored map through a new one, so a registry canonicalized twice still maps its
    original wordings -- not only the keys the first pass left -- onto the final keys."""
    if not earlier:
        return dict(later)
    composed = {original: later.get(mid, mid) for original, mid in earlier.items()}
    for key, target in later.items():
        composed.setdefault(key, target)
    return composed


def build_merge_report(folds: list[dict], keys: dict[str, str] | None = None) -> dict:
    """The round's findings, for assays_merges.json.

    `key_map` is written on every run, folds or not: it is what joins the pre-round-5 files to
    the canonical registry, and a paper that folded nothing re-keys every entry all the same.
    """
    report = {
        "summary": {
            "groups_merged": len(folds),
            "entries_folded": sum(len(f["folded"]) for f in folds),
        },
        "results": folds,
    }
    if keys is not None:
        report["key_map"] = keys
    return report
