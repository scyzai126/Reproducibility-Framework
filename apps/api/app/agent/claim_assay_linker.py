"""Link a paper's claims to its verified assay registry, and report where the two disagree.

The assay pipeline and the claim pipeline read the same paper independently: the registry
(`assays.json`, keyed by OBI label after round 5) says which assays the paper performed, and
each claim names its own assay in the paper's wording (`assay_method_in_paper`). This module
joins them, deterministically -- **it calls nothing** -- and reads both files without changing
either. Its output is its own file, `claim_assay_links.json`, which the grouping step reads.

Per claim:
    exact      the claim's wording normalizes to the registry key (the OBI label)
    alias      it normalizes to another wording the entry records (name_in_paper, aliases,
               standard_technique_name)
    unlinked   neither; `candidates` lists entries whose wordings the claim's text or quotes
               mention, for a human or a later LLM step to decide

Per registry entry, `status`:
    claimed                  one or more claims link to it
    generate_claim_mismatch  claims link to it, but the registry says it generates none
    no_claim_expected        no claim, and `generate_claim` is false
    no_claim_unlabelled      no claim, and `generate_claim` is null (a pre-flag registry)
    and, for `generate_claim: true` with no claim, the gap triage, first match wins:
    possible_wording_mismatch  an unlinked claim mentions one of its wordings
    generate_claim_doubtful    no Results or caption sentence mentions any of its wordings
    unexplained                it is mentioned in Results/captions, but no claim came of it
                               (also the answer when no paper text was supplied to check)
"""

import json
import re
from pathlib import Path

from app.agent.assay_registry import (
    claim_assay_name,
    index_registry,
    normalize_assay_name,
    surface_forms,
)
from app.agent.assay_verifier import sentence_index
from app.agent.jats_parser import CAPTIONS, sentence_sections

#: Sections whose sentences can carry a finding. Methods mentions every assay the paper ran,
#: so a mention there says nothing about whether it produced a result.
_FINDING_SECTIONS = ("results", CAPTIONS)

#: Forms shorter than this are too likely to match inside unrelated words or abbreviations.
_MIN_FORM_LENGTH = 3


def load_registry(assay_dir: Path) -> dict:
    """`assays.json`, with `obi_id`/`obi_label` copied in from `assays_OBI.json` by key.

    `assays.json` is the finished registry; round 4 writes the OBI term only to the OBI file.
    Round 5 keys both files alike, so a key match is the join. A missing OBI file leaves the
    two fields absent rather than failing: linking by wording works without them.
    """
    registry = json.loads((assay_dir / "assays.json").read_text(encoding="utf-8"))
    obi_path = assay_dir / "assays_OBI.json"
    obi = json.loads(obi_path.read_text(encoding="utf-8")) if obi_path.exists() else {}
    for key, entry in registry.items():
        mapped = obi.get(key) if isinstance(obi, dict) else None
        if isinstance(entry, dict) and isinstance(mapped, dict):
            for field in ("obi_id", "obi_label"):
                if mapped.get(field) and not entry.get(field):
                    entry[field] = mapped[field]
    return registry


def finding_sentences(numbered_text: str) -> dict[str, str]:
    """{sentence id: text} for every Results and caption sentence of a numbered parse."""
    sections = sentence_sections(numbered_text)
    return {sid: text for sid, text in sentence_index(numbered_text).items()
            if sections.get(sid) in _FINDING_SECTIONS}


def _all_forms(name: str, entry: dict) -> list[str]:
    forms = surface_forms(name, entry)
    if isinstance(entry.get("standard_technique_name"), str) and entry["standard_technique_name"].strip():
        forms.append(entry["standard_technique_name"])
    return forms


def _search_patterns(forms: list[str]) -> list[re.Pattern]:
    """Whole-word, case-insensitive patterns for each form and its normalized spelling."""
    words: set[str] = set()
    for form in forms:
        for word in (form.strip().lower(), normalize_assay_name(form)):
            if len(word) >= _MIN_FORM_LENGTH:
                words.add(word)
    return [re.compile(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", re.IGNORECASE)
            for w in sorted(words)]


def _mentions(text: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


def _claim_text(claim: dict) -> str:
    """Everything a claim says about itself: its assay name, its sentence, its quotes."""
    parts = [claim_assay_name(claim), claim.get("claim") or ""]
    parts += [s.get("quote") or "" for s in claim.get("sources") or [] if isinstance(s, dict)]
    return "\n".join(p for p in parts if p)


def link_claims(claims: dict, registry: dict,
                finding_text: dict[str, str] | None = None) -> dict:
    """Join claims to registry entries and triage the gaps. See the module docstring.

    `finding_text` is `finding_sentences(...)` of the paper. Without it the
    generate_claim_doubtful check cannot run, and an uncovered assay is reported `unexplained`
    with `text_checked: false`.
    """
    entries = {k: v for k, v in (registry or {}).items() if isinstance(v, dict)}
    index = index_registry(entries)
    for name, entry in entries.items():
        norm = normalize_assay_name(entry.get("standard_technique_name") or "")
        if norm:
            index.setdefault(norm, name)
    patterns = {name: _search_patterns(_all_forms(name, entry)) for name, entry in entries.items()}

    claim_links: dict[str, dict] = {}
    linked_to: dict[str, list[str]] = {name: [] for name in entries}
    for claim_id, claim in (claims or {}).items():
        if not isinstance(claim, dict):
            continue
        wording = claim_assay_name(claim)
        norm = normalize_assay_name(wording)
        key = index.get(norm) if norm else None
        record = {"assay_method_in_paper": wording or None}
        if key is None:
            text = _claim_text(claim)
            record.update({
                "link": "unlinked",
                "assay_key": None,
                "candidates": [name for name, pats in patterns.items() if _mentions(text, pats)],
            })
        else:
            entry = entries[key]
            record.update({
                "link": "exact" if norm == normalize_assay_name(key) else "alias",
                "assay_key": key,
                "obi_id": entry.get("obi_id"),
                "obi_label": entry.get("obi_label"),
                "registry_sample_type": entry.get("sample_type") or None,
            })
            linked_to[key].append(claim_id)
        claim_links[claim_id] = record

    assays: dict[str, dict] = {}
    for name, entry in entries.items():
        linked = linked_to[name]
        flag = entry.get("generate_claim")
        record = {
            "obi_id": entry.get("obi_id"),
            "obi_label": entry.get("obi_label"),
            "generate_claim": flag,
            "claims": linked,
        }
        if linked:
            record["status"] = "generate_claim_mismatch" if flag is False else "claimed"
        elif flag is False:
            record["status"] = "no_claim_expected"
        elif flag is None:
            record["status"] = "no_claim_unlabelled"
        else:
            record.update(_triage_gap(name, patterns[name], claim_links, finding_text))
        assays[name] = record

    unclaimed = [name for name, r in assays.items() if r["status"] in _GAP_STATUSES]
    unlinked = [cid for cid, r in claim_links.items() if r["link"] == "unlinked"]
    statuses: dict[str, int] = {}
    for r in assays.values():
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    links: dict[str, int] = {}
    for r in claim_links.values():
        links[r["link"]] = links.get(r["link"], 0) + 1

    return {
        "summary": {
            "claims": len(claim_links),
            "claim_links": links,
            "assays": len(assays),
            "assay_status": statuses,
        },
        "claims": claim_links,
        "assays": assays,
        "unclaimed_assays": unclaimed,
        "unlinked_claims": unlinked,
    }


_GAP_STATUSES = ("possible_wording_mismatch", "generate_claim_doubtful", "unexplained")


def _triage_gap(name: str, patterns: list[re.Pattern], claim_links: dict[str, dict],
                finding_text: dict[str, str] | None) -> dict:
    """Why an assay flagged `generate_claim: true` has no claim. First match wins."""
    candidates = [cid for cid, r in claim_links.items()
                  if r["link"] == "unlinked" and name in r["candidates"]]
    if candidates:
        return {"status": "possible_wording_mismatch", "candidate_claims": candidates}
    if finding_text is None:
        return {"status": "unexplained", "text_checked": False}
    hits = [sid for sid, text in finding_text.items() if _mentions(text, patterns)]
    if not hits:
        return {"status": "generate_claim_doubtful", "text_checked": True}
    return {"status": "unexplained", "text_checked": True, "finding_sentence_ids": hits}
