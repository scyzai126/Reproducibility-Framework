"""Round 5: key the registry by its OBI term, and fold entries that share a term.

Extraction is a single whole-paper call keyed by the paper's own wording, so one assay described
under two Methods subheadings lands two entries -- SDY1260 carries both `ELISA` (serum
anti-meningococcal antibodies) and `ELISA kits` (cytokines in culture supernatants). Nothing
downstream caught it: `clean_registry` is a dict comprehension, and the verifier judges one entry
at a time against the paper, never against a sibling.

**Two entries are one assay when they share an OBI term that is exact for both. Nothing else
folds.** The term is the OBI label the entry mapped to; one round 4 marked BROAD -- the picker
could only name a family, `flow cytometry assay` for an ICS panel -- is not the entry's identity,
so an entry carrying it keeps its own key (`broad_unfolded` in the merge report, `BROAD` on the
CLI) rather than folding onto every sibling in the family. A shared `standard_technique_name` used to be a second link, pulling
an unmapped entry onto a mapped sibling with the same technique; it was removed because the
technique is the instrument the numbers came off, and one instrument runs many assays. The link
first folded mapped entries onto each other (SDY1640's AIM assay into its immunophenotyping,
SDY1389's proliferation assay, SDY1289's CFSE and ICS assays), and once that was stopped it still
folded SDY1328's unmapped `multiplex ELISA` into plain `ELISA` -- the one case the resolver's own
rule 10 says is a different assay. An entry OBI has no term for is now its own entry under the
paper's wording, and reported UNMAPPED, which is a finding a human can act on; a fold hid it.

The merged entry is keyed by its OBI label rather than by a wording -- `name_in_paper` already
records every wording, as a list. An unmapped entry keeps its paper name as its key.

The rule is coarser than the paper's own language: one OBI term covers every ELISA a paper runs,
so SDY1640's two antigen-specific ELISAs and SDY1669's plate ELISA and SIMoA assay fold together
too. That is the trade this round exists to make. Nothing is discarded in the process -- each
folded write-up's specimen, platform, readouts and quote move to `additional_evidence` on the
surviving entry, so the coarser key never costs a measurement.

An identity the judge did not support (`identity_review`, assay_extractor.REVIEW_FIELD) travels
with the fold inside the member's own `additional_evidence` block, and is never copied onto the
survivor: the judge ruled on that member's name ("ELISA kits" names a product), and the survivor's
name was ruled on separately. Promoting it made SDY1260's supported ELISA read as doubted.

Deterministic and free: no model decides any of this, and the same registry always canonicalizes
the same way.
"""

import logging

from app.agent.assay_extractor import REVIEW_FIELD, paper_names
from app.agent.assay_registry import normalize_assay_name

logger = logging.getLogger(__name__)

#: What a folded-away entry keeps on the survivor. Its wordings are not here -- those join the
#: survivor's `name_in_paper` and `aliases` -- but everything that describes the run itself is,
#: `generate_claim` included: the survivor's is the fold's, so a member's own answer would
#: otherwise be the one thing the fold destroyed rather than recorded.
_KEPT_ON_MEMBER = ("name_in_paper", "sample_type", "readouts", "generate_claim", "source",
                   "evidence")


#: The `obi_granularity` round 4 records when the picker could only name a term broader than
#: the assay (prompts/resolver_obi_assay.txt). The other value is "EXACT"; a free exact-label
#: match, and every mapping written before the field existed, carry None.
BROAD = "BROAD"


def _stands_alone(mapped: dict, entry: dict) -> str | None:
    """Why an entry is a group of its own under its paper name, or None when it may fold.

    * "unmapped": OBI has no term for it, so there is nothing to key it by.
    * "broad": round 4 could only name a term broader than the assay. Two entries sharing such
      a term are in the same family, not one assay -- ICS and an immunophenotyping panel both
      resolve to `flow cytometry assay` as BROAD, and folding them on it is how SDY1630's NK
      functional assay disappeared into "Flow cytometry analysis and cell sorting".
    """
    if not mapped.get("obi_label"):
        return "unmapped"
    if mapped.get("obi_granularity") == BROAD:
        return "broad"
    return None


def canonical_groups(assays: dict, obi: dict | None = None) -> list[dict]:
    """Group the registry into assays: one group per OBI label, plus one per entry that stands
    alone -- unmapped, or mapped only to a term broader than itself.

    Two entries are linked when they map to the same OBI label as an exact term; that is the
    only link, so the groups are a bucketing on the label. Registry order is preserved, both
    between groups and within them, so the first entry is the one whose fields survive the fold.
    Deterministic by construction -- there is no scoring step to break a tie differently on a
    rerun.

    The group is keyed by its OBI label, and the first member's mapping is the group's. An entry
    that stands alone keeps its own key and its own record -- a BROAD one keeps its term too,
    since the term is still what round 4 found; it just is not the entry's identity -- and
    `alone` says why (`_stands_alone`), or is None for a label group.
    """
    obi = obi or {}
    members_by_label: dict[str, list[str]] = {}
    order: list[tuple[str, list[str], str | None]] = []
    for key in assays:
        mapped = obi.get(key) or {}
        alone = _stands_alone(mapped, assays[key])
        if alone:
            order.append((key, [key], alone))
            continue
        label = mapped["obi_label"]
        if label not in members_by_label:
            members_by_label[label] = []
            order.append((label, members_by_label[label], None))
        members_by_label[label].append(key)

    groups: list[dict] = []
    taken: set[str] = set()
    for key, members, alone in order:
        mapped = obi.get(members[0]) or {}
        # An entry that stands alone keeps its paper wording as its key, and nothing stops that
        # wording from being another group's OBI label. Two groups on one key would overwrite
        # each other in the registry, so the later one is suffixed instead of silently lost.
        base, n = key, 2
        while key in taken:
            key, n = f"{base} ({n})", n + 1
        taken.add(key)
        groups.append({
            "key": key,
            "members": members,
            "obi_id": mapped.get("obi_id"),
            "obi_label": mapped.get("obi_label"),
            "anchor": members[0],
            "alone": alone,
            # Every member's own term. One label per group now that the technique link is gone;
            # kept so the merge report's shape, and every reader of it, stays the same.
            "member_labels": {m: (obi.get(m) or {}).get("obi_label") for m in members},
        })
    return groups


def _unfolded(assays: dict, obi: dict | None, why: str) -> list[str]:
    return [group["key"] for group in canonical_groups(assays, obi) if group["alone"] == why]


def broad_unfolded(assays: dict, obi: dict | None = None) -> list[str]:
    """The keys of entries left as their own entry because their term is BROAD. Free, same
    grouping as the fold; for the merge report, where a reader finds out why a sibling that
    shares a term was not folded onto it."""
    return _unfolded(assays, obi, "broad")


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
        block = {field: loser.get(field) for field in _KEPT_ON_MEMBER}
        # Only where present: an unreviewed member must not gain a `None` review slot.
        if loser.get(REVIEW_FIELD):
            block[REVIEW_FIELD] = loser[REVIEW_FIELD]
        blocks.append(block)
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


def build_merge_report(folds: list[dict], keys: dict[str, str] | None = None,
                       broad: list[str] | None = None) -> dict:
    """The round's findings, for assays_merges.json.

    `key_map` is written on every run, folds or not: it is what joins the pre-round-5 files to
    the canonical registry, and a paper that folded nothing re-keys every entry all the same.
    `broad_unfolded` is always present too, empty or not, so no reader branches on it: the
    entries that kept their own key although a sibling shares their (BROAD) term.
    """
    report = {
        "summary": {
            "groups_merged": len(folds),
            "entries_folded": sum(len(f["folded"]) for f in folds),
            "broad_unfolded": list(broad or []),
        },
        "results": folds,
    }
    if keys is not None:
        report["key_map"] = keys
    return report
