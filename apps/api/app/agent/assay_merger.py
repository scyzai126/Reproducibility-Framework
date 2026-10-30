"""Round 5: key the registry by its OBI term, and fold entries that share a term.

Extraction is a whole-paper call keyed by the paper's own wording, so one assay described
under two Methods subheadings lands two entries -- SDY1260 carries both `ELISA` (serum
anti-meningococcal antibodies) and `ELISA kits` (cytokines in culture supernatants). Nothing
downstream caught it: `clean_registry` is a dict comprehension, and the verifier judges one entry
at a time against the paper, never against a sibling.

**Two entries are one assay when they share an OBI term and the same measurement identity --
technique, analyte and specimen. Nothing else folds.** The term is the `obi_id` the entry mapped
to (the label is only the key it is delivered under). Two rules, each from a fold that cost a
measurement:

- Same `obi_id`, not same label: the id is what the mapper chose, and a label is a spelling of it.
- Same identity triple, the one round 1 extracts by: `standard_technique_name`, `readouts` and
  `sample_type` must not conflict, though a field absent on one side never blocks. The same term
  reached from two different techniques (SDY1264's cytopathic-effect and plaque-reduction
  neutralization tests) is two write-ups a reader should see side by side; so is one technique
  pointed at two analytes (SDY984's IFN-gamma and IgG ELISPOTs, SDY1260's serum-antibody and
  supernatant-cytokine ELISAs), which the curator lists apart and an earlier rule folded.

Because `readouts` is a sentence the model wrote rather than a value copied from a span, this
rule folds only entries whose readout prose matches outright, so it refuses far more than it
accepts. That is the intended direction: the adjudication counts nine merge-or-drop faults
against three over-splits, and an entry kept apart is visible as `REVIEW  not folded` while a
measurement folded away is not.

An entry a rule keeps apart stays its own entry under the same label, suffixed, and is reported
as a blocked fold (`REVIEW  not folded`) rather than silently kept or silently merged.

A shared `standard_technique_name` used to be a second link, pulling
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
folded write-up's specimen, readouts and quote move to `additional_evidence` on the
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


#: The identity triple round 1 extracts by: the technique, the analyte it measures, and the
#: specimen it measures it in (`extract_assays.txt`, "One entry per distinct measurement").
#: Two entries are one assay only when all three agree, so these are the legs a fold is tested on.
#: `sample_type` is the one leg compared loosely -- see `_differs`.
_IDENTITY_FIELDS = ("standard_technique_name", "sample_type", "readouts")

#: Legs where one side naming the specimen more fully than the other is the same specimen, not a
#: second one: SDY1364 wrote 'frozen peripheral blood mononuclear cells' against 'peripheral blood
#: mononuclear cells', SDY2189 'sera samples' against 'samples'. Nothing similar holds of a
#: technique or a readout, where a longer string routinely names a different measurement.
_CONTAINMENT_FIELDS = frozenset({"sample_type"})


def _field(entry: dict, name: str) -> str:
    return normalize_assay_name(str(entry.get(name) or ""))


def _differs(field: str, a: str, b: str) -> bool:
    """Whether two non-empty values of `field` name different things."""
    if a == b:
        return False
    if field in _CONTAINMENT_FIELDS:
        return a not in b and b not in a
    return True


def _refusal(anchor: dict, entry: dict) -> str | None:
    """Why `entry` may not fold onto `anchor`, or None when the fold is justified.

    The test is the extraction's own identity triple, not the mapping's quality. A leg present on
    only one side never blocks -- an absent field is a gap in the write-up, not a difference --
    so a null `sample_type` on either side leaves the other two legs to decide, and one side
    naming the specimen more fully than the other is the same specimen (`_CONTAINMENT_FIELDS`).

    `obi_granularity` was this rule's first leg: a mapping the picker marked BROAD never folded,
    and nothing folded onto it. It was dropped because BROAD describes the term, not the assay.
    The picker marks it when no candidate names the assay's function, which for a whole class is
    permanent rather than fixable -- `_is_generic_assay_label` prunes the compositional labels
    that would name it, so the round 5 re-pick answered `none` on all 27 BROAD mappings in the
    31-paper corpus. Every pair BROAD kept apart differs on `readouts` too, so the splits it was
    protecting survive this rule; what it could not do was keep SDY984's two ELISPOTs or SDY1260's
    two ELISAs apart, both mapped EXACT on one term and folded although their analytes differ.
    """
    for field in _IDENTITY_FIELDS:
        a, b = _field(anchor, field), _field(entry, field)
        if a and b and _differs(field, a, b):
            return f"{field} differs: {anchor.get(field)!r} vs {entry.get(field)!r}"
    return None


def _term(mapped: dict) -> str | None:
    """The identity a mapping gives an entry: its id, or its label for a record with no id."""
    return mapped.get("obi_id") or mapped.get("obi_label") or None


def canonical_groups(assays: dict, obi: dict | None = None) -> list[dict]:
    """Group the registry into assays: one group per OBI term, plus one per unmapped entry.

    Two entries are linked when they map to the same `obi_id` and the module's fold rules allow
    it (same technique, neither mapping BROAD). Registry order is preserved, both between groups
    and within them, so the first entry is the one whose fields survive the fold. Deterministic
    by construction -- there is no scoring step to break a tie differently on a rerun.

    A group is keyed by its OBI label, and the first member's mapping is the group's; an entry a
    rule kept apart from an earlier group on the same term is its own group under the same label,
    suffixed, and the earlier group records it under `refused` with the reason. An unmapped entry
    keeps its own key and its own (unresolved) record.
    """
    obi = obi or {}
    groups: list[dict] = []
    by_term: dict[str, list[dict]] = {}
    for key in assays:
        mapped = obi.get(key) or {}
        term = _term(mapped)
        if not term:
            groups.append({"label": key, "members": [key], "mapped": mapped, "refused": []})
            continue
        candidates = by_term.setdefault(term, [])
        reasons: list[tuple[dict, str]] = []
        for group in candidates:
            anchor = group["members"][0]
            reason = _refusal(assays[anchor], assays[key])
            if reason is None:
                group["members"].append(key)
                break
            reasons.append((group, reason))
        else:
            group = {"label": mapped.get("obi_label") or key, "members": [key], "mapped": mapped,
                     "refused": []}
            candidates.append(group)
            groups.append(group)
            if reasons:
                # Refused from every earlier group on this term; the first is the one a reader
                # expects it to have joined, so that is where the refusal is recorded.
                reasons[0][0]["refused"].append({"member": key, "reason": reasons[0][1]})

    taken: set[str] = set()
    out: list[dict] = []
    for group in groups:
        mapped = group["mapped"]
        # An unmapped entry keeps its paper wording as its key, and nothing stops that wording
        # from being another group's OBI label; a refused entry shares its label with the group
        # it was kept apart from. Two groups on one key would overwrite each other in the
        # registry, so the later one is suffixed instead of silently lost.
        base, key, n = group["label"], group["label"], 2
        while key in taken:
            key, n = f"{base} ({n})", n + 1
        taken.add(key)
        members = group["members"]
        out.append({
            "key": key,
            "members": members,
            "obi_id": mapped.get("obi_id"),
            "obi_label": mapped.get("obi_label"),
            "anchor": members[0],
            # Every member's own term. One label per group now that the technique link is gone;
            # kept so the merge report's shape, and every reader of it, stays the same.
            "member_labels": {m: (obi.get(m) or {}).get("obi_label") for m in members},
            "refused": group["refused"],
        })
    return out


def blocked_folds(groups: list[dict]) -> list[dict]:
    """The folds the rules refused, as report records: which entry was kept apart from which
    group, on which term, and why. Empty when every shared term folded."""
    return [{"member": refusal["member"], "kept_apart_from": group["key"],
             "anchor": group["anchor"], "obi_id": group["obi_id"],
             "obi_label": group["obi_label"], "reason": refusal["reason"]}
            for group in groups for refusal in group.get("refused") or []]


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
                       blocked: list[dict] | None = None) -> dict:
    """The round's findings, for assays_merges.json.

    `key_map` is written on every run, folds or not: it is what joins the pre-round-5 files to
    the canonical registry, and a paper that folded nothing re-keys every entry all the same.
    `blocked` is every fold the rules refused (blocked_folds): a finding in its own right, since
    two entries on one term that were kept apart is exactly what a reader checks.
    """
    blocked = list(blocked or [])
    report = {
        "summary": {
            "groups_merged": len(folds),
            "entries_folded": sum(len(f["folded"]) for f in folds),
            "folds_blocked": len(blocked),
        },
        "results": folds,
        "blocked": blocked,
    }
    if keys is not None:
        report["key_map"] = keys
    return report
