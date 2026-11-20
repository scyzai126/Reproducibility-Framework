"""The BROAD re-pick that round 5 used to make, kept here with its evidence after its removal.

Until 2026-10-30 round 5 asked the OBI picker once more for every mapping marked BROAD: "is any
term the same technique made more specific?" Over round 4's top-20 that was 27 asked, 27 "none"
on assay_result_v3. This script is the full-vocabulary version (commit 489bcec): all 701 terms
minus the BROAD one, the answer kept only when it is an `is_a` descendant of that term. Run on
copies of the v3 registries the same day: 25 asked, 2 skipped (no descendant in the vocabulary),
24 "none", 1 moved -- SDY1289's intracellular cytokine staining onto `T cell activation induced
marker assay`, whose definition excludes cytokine readouts. See run_2026-10-30.txt. The step
was then removed from the pipeline; the functions it needs are vendored below, with prompt.txt
beside this file, so the measurement can be repeated.

Nothing is written in place. Each registry's `assays.json` and `assays_OBI.json` are copied
under runs/<registry>/ and `repick_broad` is run on the copies; the model replies land in
runs/<registry>/assays_raw.json under `repick`, with `rejected` on any answer the descendant
guard refused.

    python3 experiment/obi_repick_fulllist/run.py --dry-run     # which entries would be asked
    python3 experiment/obi_repick_fulllist/run.py               # one call per listed entry
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "apps" / "api"))

from app.agent import assay_trace  # noqa: E402
from app.agent.assay_extractor import paper_names  # noqa: E402
from app.agent.assay_obi_mapper import (  # noqa: E402
    _OBI_TERMS_PATH,
    FULLLIST_RESOURCE,
    _candidate_line,
    _fulllist_candidates,
    _index_children,
    parse_pick_reply,
)
from app.config import settings  # noqa: E402
from openai import OpenAI  # noqa: E402

logger = logging.getLogger(__name__)
_PROMPT = Path(__file__).resolve().parent / "prompt.txt"


# ── vendored from app.agent.assay_obi_mapper as of commit 489bcec ───────────────
#: What a re-pick is attributed to. Paid, so not in assay_service._OBI_FREE_RESOURCES. Registries
#: written before 2026-10-30 carry "embedding_llm_repick": the same step, asked over round 4's
#: top-20 instead of the whole vocabulary.
REPICK_RESOURCE = "fulllist_llm_repick"


def build_repick_prompt(
    assay_name: str,
    candidates: list[dict[str, Any]],
    broad_id: str,
    broad_label: str,
    sample_type: str = "",
    readouts: str = "",
    aliases: list[str] | None = None,
    standard_technique_name: str = "",
) -> str:
    """Render repick_obi_assay.txt for one re-pick. The category term is named in the prompt and
    must already be absent from `candidates`. The list comes first and the record last, as in
    the full-list prompt: with the whole vocabulary as candidates the list is the same text for
    every re-pick on a term, and the provider caches that prefix."""
    named = [a.strip() for a in (aliases or []) if isinstance(a, str) and a.strip()]
    return (
        _PROMPT.read_text(encoding="utf-8")
        .replace("{assay_name}", assay_name)
        .replace("{aliases}", ", ".join(named) if named else "none given")
        .replace("{standard_technique_name}", standard_technique_name.strip() or "not given")
        .replace("{broad_id}", broad_id)
        .replace("{broad_label}", broad_label)
        .replace("{candidates}",
                 "\n".join(_candidate_line(i + 1, c).removesuffix(" ()")
                           for i, c in enumerate(candidates)))
        .replace("{sample_type}", sample_type.strip() or "not specified")
        .replace("{readouts}", readouts.strip() or "not specified")
    )


def repick_obi(
    key: str,
    entry: dict[str, Any],
    mapping: dict[str, Any],
    terms_path: Path = _OBI_TERMS_PATH,
    model: str = settings.OPENAI_MODEL,
) -> dict[str, Any] | None:
    """One more pick for an entry whose mapping the picker marked BROAD, over the whole
    vocabulary with that term removed.

    BROAD means the term is a category the assay falls under, not the assay. This asks the
    narrower question the first pick did not: with the category gone, is any term in the
    vocabulary the same technique made more specific?

    The candidates are every term the vocabulary allows (_fulllist_candidates), not round 4's
    top-20. The first version re-ran round 4's retrieval and removed the BROAD term, which left
    the picker the 19 terms it had just judged not EXACT: 27 re-picks in assay_result_v3, 27
    "none". Shown the whole list, the picker can at least reach a child the embedding ranked
    outside the top-20. The expected gain is small and is known: the 2026-10-27 full-list A/B
    (experiment/obi_llm_fulllist) gave every entry all 701 terms and, on those same 27 BROAD
    entries, named a more specific term 0 times -- it answered the category BROAD 22 times,
    another category 3 times (a parent, `pathogen neutralization assay`, or a sideways
    `cell viability assay`) and nothing twice. The vocabulary is the limit: the compositional
    terms that would name ICS, degranulation or PRNT were pruned (see _is_generic_assay_label).

    That sideways drift is why the answer is kept only when it is an `is_a` descendant of the
    BROAD term (_descends_from): a parent or a sibling category is not "the same technique made
    more specific", and swapping one category for another would change the entry's identity
    without making it finer. A refused pick is recorded in the trace as `rejected`.

    One chat call; no embeddings are needed. The reply is kept in the trace under `repick`,
    beside the first pick's `obi` record rather than over it, with the candidate count rather
    than 700 candidate lines. Returns None when the picker still finds nothing or its answer
    is refused.
    """
    broad_id = str(mapping.get("obi_id") or "")
    broad_label = str(mapping.get("obi_label") or "")
    if not broad_id:
        return None
    names = paper_names(entry)
    name = (names[0] if names else key).strip()
    raw_aliases = entry.get("aliases")
    aliases = names[1:] + [a for a in (raw_aliases if isinstance(raw_aliases, list) else [])
                           if isinstance(a, str)]
    technique = str(entry.get("standard_technique_name") or "").strip()
    sample_type = str(entry.get("sample_type") or "")
    readouts = str(entry.get("readouts") or "")

    candidates = [c for c in _fulllist_candidates(terms_path) if c["id"] != broad_id]
    if not candidates:
        return None

    prompt = build_repick_prompt(
        name, candidates, broad_id, broad_label, sample_type=sample_type, readouts=readouts,
        aliases=aliases, standard_technique_name=technique if technique.lower() != name.lower() else "",
    )
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}], temperature=0)
    reply = (resp.choices[0].message.content or "").strip().lower()
    # The candidates are the vocabulary minus one term, the same for every entry on that term,
    # so only their count is kept -- the same economy _fulllist_pick makes.
    record = {"reply": reply, "broad_id": broad_id, "broad_label": broad_label,
              "n_candidates": len(candidates)}
    idx, granularity = parse_pick_reply(reply, len(candidates))
    if idx is None:
        assay_trace.record("repick", key, **record)
        return None
    chosen = candidates[idx]
    if not _descends_from(chosen["id"], broad_id, _index_children(terms_path)):
        # A parent or a sibling of the category: the prompt forbids it, and the full-list A/B
        # showed the picker doing exactly this when handed the whole list. The entry keeps its
        # BROAD term; the refused label is in the trace so the call is not lost.
        logger.info("%s: OBI re-pick refused - %s (%s) is not under %s (%s)",
                    key, chosen["label"], chosen["id"], broad_label, broad_id)
        assay_trace.record("repick", key, rejected=f"{chosen['id']} {chosen['label']}", **record)
        return None
    assay_trace.record("repick", key, **record)
    return {
        "obi_id": chosen["id"],
        "obi_label": chosen["label"],
        "resource": REPICK_RESOURCE,
        "confidence": None,
        "granularity": granularity or "EXACT",
    }


def _descends_from(term_id: str, ancestor_id: str, children: dict[str, tuple[str, ...]]) -> bool:
    """Whether `term_id` sits under `ancestor_id` by one or more `is_a` steps in the index.

    `children` is _index_children's map of direct children. A term is not its own descendant,
    and an empty map (no obi.obo on disk) makes every answer False -- the re-pick then changes
    nothing, which is the conservative reading of not being able to check.
    """
    seen: set[str] = set()
    frontier = list(children.get(ancestor_id, ()))
    while frontier:
        current = frontier.pop()
        if current == term_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        frontier.extend(children.get(current, ()))
    return False


def repick_broad(
    assays: dict[str, Any],
    obi: dict[str, Any],
    model: str = settings.OPENAI_MODEL,
    terms_path: Path = _OBI_TERMS_PATH,
) -> tuple[dict[str, Any], dict[str, dict[str, str]], int]:
    """Re-pick every BROAD mapping in the registry. Returns (obi, repicked, attempts).

    `attempts` is the number of picker calls made -- one per BROAD mapping -- whether or not the
    answer changed the term, because a "none" was paid for too. The first version billed only
    the entries whose term changed, and SDY1289's two BROAD flow entries, both answered "none",
    showed as a free round.

    The trigger is the mapping, not a conflict: BROAD says the term is a category the assay
    falls under, and that is as true for an entry with no sibling on the term as for one whose
    fold round 5 refused. It used to fire only for the latter, which left ten of the corpus's
    twelve BROAD mappings on their category term with nobody asking again.

    `repicked` is {key: {"from": old label, "to": new label}} for the entries whose term
    changed; the returned mapping carries the new term on them with `obi_repicked_from` saying
    what it was. An entry the picker still answers "none" for, or whose call fails, keeps its
    BROAD term -- the failure is logged, never raised, because everything before this step has
    already been paid for.

    A BROAD mapping from the full-list fallback is not asked again: that entry has already
    seen the whole vocabulary once and answered BROAD, and the re-pick's list is the same
    vocabulary minus that one term.
    """
    obi = {key: dict(value) for key, value in (obi or {}).items()}
    repicked: dict[str, dict[str, str]] = {}
    attempts = 0
    for key, mapping in obi.items():
        if not _is_broad_mapping(mapping) or mapping.get("resource") == FULLLIST_RESOURCE:
            continue
        if not repick_can_help(mapping, terms_path):
            # The guard would refuse every answer, so the call is not made. Free, and the
            # dry-run (assay_service.estimate_run) leaves these out for the same reason.
            logger.info("%s: OBI re-pick skipped - %s has no descendant in the vocabulary",
                        key, mapping.get("obi_label"))
            continue
        attempts += 1
        try:
            picked = repick_obi(key, assays.get(key) or {}, mapping, terms_path=terms_path,
                                model=model)
        except Exception as exc:  # noqa: BLE001 - one failed re-pick must not cost the round
            logger.warning("%s: OBI re-pick failed - %s", key, exc)
            continue
        if not picked or picked["obi_id"] == mapping.get("obi_id"):
            continue
        repicked[key] = {"from": str(mapping.get("obi_label")), "to": picked["obi_label"]}
        mapping["obi_repicked_from"] = {"obi_id": mapping.get("obi_id"),
                                        "obi_label": mapping.get("obi_label")}
        mapping.update({"obi_id": picked["obi_id"], "obi_label": picked["obi_label"],
                        "resource": picked["resource"], "obi_confidence": picked["confidence"],
                        "obi_granularity": picked["granularity"]})
    return obi, repicked, attempts


def _is_broad_mapping(mapping: dict[str, Any]) -> bool:
    return str(mapping.get("obi_granularity") or "").upper() == "BROAD"


def repick_can_help(mapping: dict[str, Any], terms_path: Path = _OBI_TERMS_PATH) -> bool:
    """Whether a re-pick of this BROAD mapping could change it: only when the term has at least
    one `is_a` descendant in the vocabulary, since _descends_from refuses anything else.

    Two of v3's eleven BROAD terms have none (`population count assay`, `single-value binding
    of antibody with reporter to antigen assay`); asking about them would be a call whose every
    answer is refused. Shared with assay_service.estimate_run so the dry-run counts the same
    calls the round makes.
    """
    return bool(_index_children(terms_path).get(str(mapping.get("obi_id") or "")))



# ── the experiment ───────────────────────────────────────────────────────────────

SOURCE = _REPO / "data" / "benchmark_agent_assays" / "assay_result_v3"
RUNS = Path(__file__).resolve().parent / "runs"


def _broad_entries(obi: dict) -> list[tuple[str, dict, bool]]:
    return [(key, mapping, repick_can_help(mapping)) for key, mapping in obi.items()
            if str(mapping.get("obi_granularity") or "").upper() == "BROAD"
            and mapping.get("resource") != FULLLIST_RESOURCE]


def main(dry_run: bool) -> None:
    asked = skipped = changed = 0
    for registry in sorted(p for p in SOURCE.iterdir() if (p / "assays_OBI.json").exists()):
        obi = json.loads((registry / "assays_OBI.json").read_text(encoding="utf-8"))
        broad = _broad_entries(obi)
        if not broad:
            continue
        print(f"\n{registry.name}")
        for key, mapping, can_help in broad:
            label = mapping.get("obi_label")
            if not can_help:
                skipped += 1
                print(f"  SKIP      {key}: {label} has no descendant in the vocabulary")
            else:
                asked += 1
                print(f"  {'WOULD ASK' if dry_run else 'ASK':9} {key}: {label}")
        if dry_run:
            continue
        target = RUNS / registry.name
        target.mkdir(parents=True, exist_ok=True)
        for name in ("assays.json", "assays_OBI.json"):
            shutil.copy(registry / name, target / name)
        assays = json.loads((target / "assays.json").read_text(encoding="utf-8"))
        trace = assay_trace.start()
        try:
            new_obi, repicked, attempts = repick_broad(assays, obi)
        finally:
            assay_trace.stop()
        trace.write(target / assay_trace.RAW_FILE)
        (target / "assays_OBI.json").write_text(
            json.dumps(new_obi, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        raw = json.loads((target / assay_trace.RAW_FILE).read_text(encoding="utf-8"))
        for key, record in (raw.get("repick") or {}).items():
            if key in repicked:
                changed += 1
                print(f"  REPICKED  {key}: {repicked[key]['from']} → {repicked[key]['to']}")
            elif record.get("rejected"):
                print(f"  REJECTED  {key}: picked {record['rejected']}, not under "
                      f"{record.get('broad_label')}; kept")
            else:
                print(f"  unchanged {key}: {record.get('reply')}")
        print(f"  {attempts} call(s)")
    verb = "would be asked" if dry_run else "asked"
    print(f"\n{asked} BROAD entr{'y' if asked == 1 else 'ies'} {verb}, {skipped} skipped "
          f"(no descendant), {changed} changed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="list the entries; call nothing")
    main(parser.parse_args().dry_run)
