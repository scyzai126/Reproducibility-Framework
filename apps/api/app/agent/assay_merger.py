"""Round 5: key the registry by its OBI term, and fold entries a judge confirms are one measurement.

Extraction is a single whole-paper call keyed by the paper's own wording, so one assay described
under two Methods subheadings lands two entries -- SDY1260 carries both `ELISA` (serum
anti-meningococcal antibodies) and `ELISA kits` (cytokines in culture supernatants). Nothing
downstream caught it: `clean_registry` is a dict comprehension, and the verifier judges one entry
at a time against the paper, never against a sibling.

**Two entries are candidates to fold when they share an OBI term. They fold when a judge says
they are one measurement.** The term is the OBI label the entry mapped to, whatever
`obi_granularity` round 4 recorded: a rule that kept BROAD mappings apart was tried and
withdrawn, because the label is not stable (SDY2189's two FRNT write-ups came back EXACT in one
run and BROAD in the next, and split the paper's one assay in two) and the wrong folds it was
meant to stop (SDY1630's flow panels, SDY1640's ICS) had been mapped EXACT anyway. A shared
`standard_technique_name` used to be a second link, pulling an unmapped entry onto a mapped
sibling with the same technique; it was removed because the technique is the instrument the
numbers came off, and one instrument runs many assays. The link first folded mapped entries onto
each other (SDY1640's AIM assay into its immunophenotyping, SDY1389's proliferation assay,
SDY1289's CFSE and ICS assays), and once that was stopped it still folded SDY1328's unmapped
`multiplex ELISA` into plain `ELISA` -- the one case the resolver's own rule 10 says is a
different assay. An entry OBI has no term for is now its own entry under the paper's wording,
and reported UNMAPPED, which is a finding a human can act on; a fold hid it.

The term alone was the whole rule until the 31-paper `stability` run was read fold by fold: 12
of its 18 folds had merged different measurements the extractor had correctly split -- six
ICS or stimulation assays into phenotyping, a supernatant cytokine ELISA into a serum IgG
ELISA, IgM-capture into inhibition ELISA, B-cell into cytokine ELISPOT, phosphoflow into subset
frequencies, DC-activation into ASC flow. One term covers every flow cytometry experiment a
paper runs. The judge (app.agent.assay_fold_judge, one call per candidate group) reads the
members' records against the extraction prompt's own identity rule -- technique + analyte +
specimen -- and answers with a partition; `canonical_groups` folds each set of it and keeps the
sets apart. A label the partition does not mention folds as it always did, so a caller that
asks no judge (`partition=None`) gets exactly the old registry; a label whose call failed
(`None`) folds nothing, because a fold is irreversible and a split is not.

The merged entry is keyed by its OBI label rather than by a wording -- `name_in_paper` already
records every wording, as a list. An unmapped entry keeps its paper name as its key. An entry
kept apart from its siblings keeps the term too: it is keyed `<label>` + KEY_SEP + its first
wording (`flow cytometry assay — intracellular cytokine staining`), carries the same `obi_id`
in the mapping, and is listed under `kept_apart` in the merge report (`KEPT APART` on the CLI).

Nothing is discarded in a fold -- each folded write-up's specimen, platform, readouts and quote
move to `additional_evidence` on the surviving entry.

An identity the judge did not support (`identity_review`, assay_extractor.REVIEW_FIELD) is never
folded at all: the entry keeps its own key (`review_unfolded` in the merge report, `REVIEW
UNFOLDED` on the CLI), so a wording nobody confirmed names this assay cannot become a supported
sibling's `name_in_paper`, and the mark stays where a reader of the deliverable sees it. For a
registry folded before that rule, merge_entries still keeps a folded member's mark inside its
own `additional_evidence` block rather than promoting it: the judge ruled on that member's name
("ELISA kits" names a product), and the survivor's name was ruled on separately.

Deterministic given the partition: the same registry and the same partition always canonicalize
the same way, and nothing here calls a model. What costs is the partition -- one call per
candidate group, made by the caller (assay_service round 5, `run_assay_merge.py --judge`).
"""

import logging

from app.agent.assay_extractor import KEY_SEP, REVIEW_FIELD, paper_names
from app.agent.assay_registry import normalize_assay_name

logger = logging.getLogger(__name__)

#: What a folded-away entry keeps on the survivor. Its wordings are not here -- those join the
#: survivor's `name_in_paper` and `aliases` -- but everything that describes the run itself is,
#: `generate_claim` included: the survivor's is the fold's, so a member's own answer would
#: otherwise be the one thing the fold destroyed rather than recorded.
_KEPT_ON_MEMBER = ("name_in_paper", "sample_type", "readouts", "generate_claim", "source",
                   "evidence")

#: `alone` values a judged partition adds to `_stands_alone`'s two. KEPT_APART: the judge ruled
#: this set a different measurement from the set holding the bare label. JUDGE_FAILED: the
#: judge could not rule on the group, so every member stands alone -- the extractor's split is
#: the one state a later pass can still fold from.
KEPT_APART = "kept_apart"
JUDGE_FAILED = "judge_failed"


def _stands_alone(mapped: dict, entry: dict) -> str | None:
    """Why an entry is a group of its own under its paper name, or None when it may fold.

    * "unmapped": OBI has no term for it, so there is nothing to key it by.
    * "review": the judge did not support the entry's identity (REVIEW_FIELD). A wording nobody
      confirmed names this assay must not become a supported sibling's `name_in_paper`, nor
      absorb that sibling when it happens to come first; and a mark that survived only inside
      a survivor's `additional_evidence` was a doubt the deliverable no longer showed. Checked
      first, because it holds whatever the term is -- an ERROR record's NOT_REPORTED included.
    """
    if entry.get(REVIEW_FIELD):
        return "review"
    if not mapped.get("obi_label"):
        return "unmapped"
    return None


def _apart_key(label: str, assays: dict, key: str) -> str:
    """The key of an entry kept apart from its siblings: the term, then its own first wording.

    `paper_names(entry)[0]` rather than the registry key, because a registry canonicalized once
    already is keyed by labels, and `<label> — <label>` would say nothing; the wording is what
    tells a reader which of the paper's experiments this is. The key itself is the fallback for
    an entry with no wording at all.
    """
    names = paper_names(assays.get(key) or {})
    return f"{label}{KEY_SEP}{names[0] if names else key}"


def _covers(sets: list[list[str]], members: list[str]) -> bool:
    """Whether a partition names each member exactly once. The judge module checks this before
    it hands a partition over; checked again here because a partition that lost a member would
    lose an entry from the registry, silently, and that is the one failure this round must not
    have."""
    flat = [key for group in sets for key in group]
    return sorted(flat) == sorted(members) and all(sets)


def canonical_groups(assays: dict, obi: dict | None = None,
                     partition: dict[str, list[list[str]] | None] | None = None) -> list[dict]:
    """Group the registry into assays: one group per OBI label -- split as the judge's partition
    says -- plus one per entry that stands alone (unmapped, or with an identity the judge did
    not support).

    Two entries are candidates when they map to the same OBI label; that is the only link, so
    the first pass is a bucketing on the label. `partition`, keyed by label, then says what
    each bucket really is (assay_fold_judge.judge_fold_groups):

    * absent -- not judged: the bucket is one group, folded as before the judge existed;
    * a list of sets -- the first set keeps the bare label as its key and the rest are keyed
      `_apart_key` with `alone == KEPT_APART`;
    * None -- the judge could not rule: every member is its own group, `alone == JUDGE_FAILED`,
      the first still under the bare label. Nothing folds, because a fold cannot be undone from
      the registry and a split can.

    Registry order is preserved, both between groups and within them, so the first entry is the
    one whose fields survive the fold. Deterministic by construction -- there is no scoring step
    to break a tie differently on a rerun, and `partition=None` or `{}` reproduces the unjudged
    grouping exactly.

    The group is keyed by its OBI label, and the first member's mapping is the group's. An entry
    that stands alone keeps its own key and its own record, and `alone` says why
    (`_stands_alone`, KEPT_APART, JUDGE_FAILED), or is None for a label group.
    """
    obi = obi or {}
    partition = partition or {}
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

    # The judged buckets are expanded in place, so a kept-apart set sits right after the set
    # that kept the bare label rather than at the end of the registry.
    if partition:
        expanded: list[tuple[str, list[str], str | None]] = []
        for label, members, alone in order:
            if alone is not None or len(members) < 2 or label not in partition:
                expanded.append((label, members, alone))
                continue
            sets = partition[label]
            if sets is not None and not _covers(sets, members):
                logger.warning("%s: partition %r does not cover members %r; treated as a "
                               "failed judgement", label, sets, members)
                sets = None
            if sets is None:
                sets, why = [[member] for member in members], JUDGE_FAILED
            else:
                sets, why = [list(group) for group in sets], KEPT_APART
            expanded.append((label, sets[0], JUDGE_FAILED if why == JUDGE_FAILED else None))
            for group in sets[1:]:
                expanded.append((_apart_key(label, assays, group[0]), group, why))
        order = expanded

    groups: list[dict] = []
    taken: set[str] = set()
    for key, members, alone in order:
        mapped = obi.get(members[0]) or {}
        # An entry that stands alone keeps its paper wording as its key, and nothing stops that
        # wording from being another group's OBI label -- or two kept-apart sets from opening on
        # the same wording. Two groups on one key would overwrite each other in the registry, so
        # the later one is suffixed instead of silently lost.
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


def fold_candidates(assays: dict, obi: dict | None = None) -> list[dict]:
    """The groups a judge has something to rule on: two or more entries sharing a term, none of
    them standing alone already. What round 5 pays for -- one call each -- and what the estimate
    counts. Free, same grouping as the fold, before any partition."""
    return [group for group in canonical_groups(assays, obi)
            if group["alone"] is None and len(group["members"]) > 1]


def _unfolded(assays: dict, obi: dict | None, why: str,
              partition: dict | None = None) -> list[str]:
    return [group["key"] for group in canonical_groups(assays, obi, partition)
            if group["alone"] == why]


def review_unfolded(assays: dict, obi: dict | None = None,
                    partition: dict | None = None) -> list[str]:
    """The keys of entries left as their own entry because their identity carries a review
    mark. Free, same grouping as the fold; for the merge report, where a reader finds out why a
    sibling that shares a term was not folded onto it."""
    return _unfolded(assays, obi, "review", partition)


def kept_apart(assays: dict, obi: dict | None = None,
               partition: dict | None = None) -> list[str]:
    """The keys of entries the judge ruled a different measurement from the sibling that kept
    the bare label: `<label> — <wording>`. For the merge report and the CLI's KEPT APART lines."""
    return _unfolded(assays, obi, KEPT_APART, partition)


def judge_failed(assays: dict, obi: dict | None = None,
                 partition: dict | None = None) -> list[str]:
    """The labels whose candidate group the judge could not rule on, each once -- the group's
    members all stand alone, and a reader wants the group named, not every member of it."""
    labels: list[str] = []
    for group in canonical_groups(assays, obi, partition):
        if group["alone"] == JUDGE_FAILED and group["obi_label"] not in labels:
            labels.append(group["obi_label"])
    return labels


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


def canonicalize_registry(assays: dict, obi: dict | None = None,
                          partition: dict | None = None) -> tuple[dict, dict | None, list[dict]]:
    """Re-key the registry by OBI label and fold every group. Returns (assays, obi, folds).

    `partition` is the judge's answer per label (canonical_groups); without one every label
    group folds, which is the registry this function wrote before the judge existed.

    `obi` is re-keyed the same way and comes back beside it, because assays.json,
    assays_benchmark.json and assays_OBI.json are looked up across each other by key -- re-keying
    one alone would break that join silently. It is None in, None out.

    `folds` records only the groups that actually merged, which is what there is to report.
    """
    groups = canonical_groups(assays, obi, partition)
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


def key_map(assays: dict, obi: dict | None = None,
            partition: dict | None = None) -> dict[str, str]:
    """Which canonical key each entry of `assays` ends up under. Free, same grouping as the fold.

    Every file written before round 5 -- assays_verification.json, assays_corrections.json,
    assays_rejected.json -- is keyed by the extractor's wording, and round 5 re-keys the registry
    by OBI label. Without this map a REVIEW verdict names an assay that is no longer a key.
    """
    return {member: group["key"]
            for group in canonical_groups(assays, obi, partition) for member in group["members"]}


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
                       review: list[str] | None = None, kept_apart: list[str] | None = None,
                       judge_failed: list[str] | None = None,
                       judge: list[dict] | None = None) -> dict:
    """The round's findings, for assays_merges.json.

    `key_map` is written on every run, folds or not: it is what joins the pre-round-5 files to
    the canonical registry, and a paper that folded nothing re-keys every entry all the same.
    `review_unfolded`, `kept_apart` and `judge_failed` are always present too, empty or not, so
    no reader branches on them: the entries that kept their own key because the judge did not
    support their identity; the entries the fold judge ruled a different measurement from their
    sibling; and the labels whose group the fold judge could not rule on.

    `judge` is the fold judge's records (assay_fold_judge.judge_fold_groups), written only when
    the caller made the calls: they carry the reason a group was split and the error that
    failed one, which is what the CLI prints beside KEPT APART and FOLD JUDGE FAILED and what a
    human reading the file needs to decide whether to re-run the group.
    """
    report = {
        "summary": {
            "groups_merged": len(folds),
            "entries_folded": sum(len(f["folded"]) for f in folds),
            "review_unfolded": list(review or []),
            "kept_apart": list(kept_apart or []),
            "judge_failed": list(judge_failed or []),
        },
        "results": folds,
    }
    if keys is not None:
        report["key_map"] = keys
    if judge is not None:
        report["judge"] = list(judge)
    return report
