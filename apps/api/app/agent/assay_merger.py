"""Round 5: key the registry by its OBI term, and fold whatever lands on the same one.

Extraction is a single whole-paper call keyed by the paper's own wording, so one assay described
under two Methods subheadings lands two entries -- SDY1260 carries both `ELISA` (serum
anti-meningococcal antibodies) and `ELISA kits` (cytokines in culture supernatants). Nothing
downstream caught it: `clean_registry` is a dict comprehension, and the verifier judges one entry
at a time against the paper, never against a sibling.

**The OBI term is the identity.** Two entries that map to the same term are one assay, and the
entry is keyed by the term's label rather than by a wording -- `name_in_paper` already records
every wording, as a list. An entry OBI has no term for keeps its paper name as its key and never
merges, because there is nothing to merge it on.

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
#: survivor's `name_in_paper` and `aliases` -- but everything that describes the run itself is.
_KEPT_ON_MEMBER = ("name_in_paper", "platform", "sample_type", "readouts", "source", "evidence")


def canonical_groups(assays: dict, obi: dict | None = None) -> list[dict]:
    """Group the registry by OBI label: one group per term, plus one per unmapped entry.

    Registry order is preserved, both between groups and within them, so the first entry to claim
    a term is the one whose fields survive the fold. Deterministic by construction -- there is no
    scoring step to break a tie differently on a rerun.
    """
    obi = obi or {}
    groups: dict[str, dict] = {}
    for key, entry in assays.items():
        mapped = obi.get(key) or {}
        label = mapped.get("obi_label")
        # An unmapped entry is grouped under its own key, never under a shared `None`: two assays
        # OBI has no term for have nothing in common except that gap.
        group_key = label if label else key
        group = groups.get(group_key)
        if group is None:
            groups[group_key] = {"key": group_key, "members": [key],
                                 "obi_id": mapped.get("obi_id"), "obi_label": label}
        else:
            group["members"].append(key)
    return list(groups.values())


def merge_entries(winner: dict, losers: list[dict]) -> dict:
    """One entry carrying every member's wording, and every member's write-up.

    The winner's own fields are left exactly as the verifier and corrector left them: a fold is not
    a re-extraction, and picking field-by-field between two records would be one. What the losers
    contribute is their wordings, as names, and their records, as evidence blocks.
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
                          "folded": members[1:]})
        merged[group["key"]] = entry
        if obi_out is not None:
            mapped = dict(obi.get(winner_key) or {})
            # The mapping describes the same assay as the registry entry, so it carries the same
            # merged names rather than the one wording its own lookup happened to run on.
            if mapped:
                mapped["name_in_paper"] = entry.get("name_in_paper")
            obi_out[group["key"]] = mapped

    return merged, obi_out, folds


def build_merge_report(folds: list[dict]) -> dict:
    """The round's findings, for assays_merges.json."""
    return {
        "summary": {
            "groups_merged": len(folds),
            "entries_folded": sum(len(f["folded"]) for f in folds),
        },
        "results": folds,
    }
