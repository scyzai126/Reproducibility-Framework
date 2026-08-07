"""Reconcile independently-extracted claims against an independently-extracted assay
registry for the same paper.

Assays (extract_assays_pdf.txt/extract_assays_xml.txt) and claims
(extract_claims_pdf.txt/extract_claims_xml.txt) are now extracted in two separate,
concurrent passes that don't see each other's output — each claim self-names its own
assay rather than being handed a pre-built registry. This module links each claim back
to a canonical, OBI-mappable registry entry:

  1. match_claims_exact()      - fast path: normalized exact/alias string match
  2. validate_unmatched_claims() - one batched LLM call, checked against the source
                                    paper, for whatever didn't exact-match
  3. apply_verdicts()           - merges both into a final claim -> registry-key
                                    mapping, growing the registry for genuine misses
                                    and reporting claims that don't hold up
  4. attach_assay_links()       - writes the resolved assay onto every claim

Linking never deletes a claim. A claim this module cannot tie to a registry entry keeps
its own self-reported assay name and is flagged `link_status: "unlinked"` by
attach_assay_links, with the validator's reason attached. Whether a claim is even exposed
to the LLM validator depends on whether its self-named assay happened to string-match the
registry, which says nothing about the claim's quality — so a verdict from that pass is
not a sound basis for dropping a finding. Grounding is adjudicated by the dedicated
accuracy judge (app.agent.claim_validator, prompts/validate_claims.txt), which reports
rather than deletes; this module stays consistent with that.

Callers are responsible for OBI-enriching the merged registry (via
app.agent.assay_obi_mapper.enrich_assays_with_obi) and attaching obi_id/obi_label to
each resolved claim afterward — this module only resolves *which* registry entry each
claim belongs to.
"""

import json
import re
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings
from app.agent.claim_parser import _strip_fences

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _normalize(text: str) -> str:
    """Lowercase, strip a trailing ' assay'/' analysis', collapse whitespace."""
    key = re.sub(r"\s+", " ", (text or "").strip().lower())
    for suffix in (" assay", " analysis"):
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
    return key


def _build_registry_lookup(assays: dict) -> dict[str, str]:
    """Map every normalized name_in_paper/alias to its registry key."""
    lookup: dict[str, str] = {}
    for registry_key, entry in assays.items():
        names = [entry.get("name_in_paper") or registry_key, *(entry.get("aliases") or [])]
        for name in names:
            norm = _normalize(name)
            if norm:
                lookup.setdefault(norm, registry_key)
    return lookup


def match_claims_exact(claims: dict, assays: dict) -> tuple[dict[str, str], list[str]]:
    """Normalized exact/alias match each claim's self-reported assay name against the
    registry.

    Returns:
        (claim_key -> registry_key for every match, list of unmatched claim keys)
    """
    lookup = _build_registry_lookup(assays)
    matched: dict[str, str] = {}
    unmatched: list[str] = []
    for claim_key, claim in claims.items():
        raw_name = (claim.get("assay") or {}).get("name_in_paper", "")
        registry_key = lookup.get(_normalize(raw_name))
        if registry_key:
            matched[claim_key] = registry_key
        else:
            unmatched.append(claim_key)
    return matched, unmatched


async def validate_unmatched_claims(
    claims: dict,
    unmatched_keys: list[str],
    assays: dict,
    paper_content: list[dict],
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> dict:
    """One batched LLM call (validate_claim_assays.txt) to resolve every claim that
    didn't exact/alias-match, checked directly against the source paper.

    Returns {claim_key: {"verdict": "linked"|"new_assay"|"invalid", ...}}.
    """
    if not unmatched_keys:
        return {}

    payload = {
        claim_key: {
            "claim": claims[claim_key].get("claim", ""),
            "self_reported_assay": (claims[claim_key].get("assay") or {}).get("name_in_paper", ""),
            "sources": claims[claim_key].get("sources", []),
        }
        for claim_key in unmatched_keys
    }

    template = (_PROMPTS_DIR / "validate_claim_assays.txt").read_text(encoding="utf-8").strip()
    system_prompt = (
        template.replace("{assays}", json.dumps(assays, indent=2, ensure_ascii=False))
        .replace("{unmatched_claims}", json.dumps(payload, indent=2, ensure_ascii=False))
    )

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": paper_content},
        ],
        temperature=0,
    )

    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    return json.loads(raw) if raw else {}


def apply_verdicts(
    claims: dict,
    exact_matches: dict[str, str],
    verdicts: dict,
    assays: dict,
) -> tuple[dict[str, str], dict, list[dict]]:
    """Merge exact-match results with validation verdicts into a final resolution.

    Returns:
        claim_key -> registry_key for every linked (or newly-added) claim
        assays, with any "new_assay" verdicts appended
        unlinked_claims: [{"claim_key", "claim", "reason"}] for claims left unlinked

    A claim in `unlinked_claims` is absent from the returned mapping but is NOT dropped:
    attach_assay_links keeps it, flagged with the reason recorded here.
    """
    resolved: dict[str, str] = dict(exact_matches)
    merged_assays = dict(assays)
    unlinked_claims: list[dict] = []

    def _unlink(claim_key: str, reason: str) -> None:
        unlinked_claims.append({
            "claim_key": claim_key,
            "claim": claims.get(claim_key, {}).get("claim", ""),
            "reason": reason,
        })

    for claim_key, verdict in verdicts.items():
        kind = verdict.get("verdict")
        if kind == "linked":
            matched_assay = verdict.get("matched_assay")
            if matched_assay in merged_assays:
                resolved[claim_key] = matched_assay
            else:
                _unlink(claim_key, f"validation returned unknown matched_assay {matched_assay!r}")
        elif kind == "new_assay":
            new_entry = verdict.get("new_assay") or {}
            registry_key = new_entry.get("name_in_paper")
            if registry_key:
                merged_assays.setdefault(registry_key, new_entry)
                resolved[claim_key] = registry_key
            else:
                _unlink(claim_key, "validation returned a new_assay verdict with no name_in_paper")
        elif kind == "invalid":
            _unlink(claim_key, verdict.get("reason", "no reason given"))
        else:
            _unlink(claim_key, f"validation returned unrecognized verdict {kind!r}")

    return resolved, merged_assays, unlinked_claims


UNLINKED_STATUS = "unlinked"

NO_MATCH_REASON = "no registry match and no validation verdict"


def attach_assay_links(
    claims: dict,
    resolved: dict[str, str],
    merged_assays: dict,
    unlinked_claims: list[dict],
) -> dict:
    """Write the resolved assay onto every claim, keeping the ones that stayed unlinked.

    A linked claim's `assay` is replaced with the registry's canonical wording, so claims
    sharing an assay agree on its name. An unlinked claim keeps the name the extraction
    pass gave it and gains `link_status`/`link_note`, which is what makes it visible
    downstream as unresolved rather than silently absent.

    Claim order is preserved from `claims`, and only the `assay` key is touched.
    """
    reasons = {
        entry.get("claim_key"): entry.get("reason", "")
        for entry in unlinked_claims
        if isinstance(entry, dict)
    }
    final: dict = {}
    for claim_key, claim in claims.items():
        registry_key = resolved.get(claim_key)
        if registry_key:
            entry = merged_assays.get(registry_key) or {}
            claim["assay"] = {"name_in_paper": entry.get("name_in_paper", registry_key)}
        else:
            self_named = (claim.get("assay") or {}).get("name_in_paper", "")
            claim["assay"] = {
                "name_in_paper": self_named,
                "link_status": UNLINKED_STATUS,
                "link_note": reasons.get(claim_key) or NO_MATCH_REASON,
            }
        final[claim_key] = claim
    return final


async def reconcile_claims_with_assays(
    claims: dict,
    assays: dict,
    paper_content: list[dict],
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> tuple[dict[str, str], dict, list[dict]]:
    """Full reconciliation: exact/alias match first, then paper-grounded validation for
    whatever's left.

    Returns:
        claim_key -> registry_key for every valid claim
        assays, merged with any validated new entries (not yet OBI-enriched)
        invalid_claims for exclusion/diagnostics

    Callers should run app.agent.assay_obi_mapper.enrich_assays_with_obi on the
    returned registry, then attach obi_id/obi_label to each resolved claim.
    """
    exact_matches, unmatched_keys = match_claims_exact(claims, assays)
    verdicts = await validate_unmatched_claims(
        claims, unmatched_keys, assays, paper_content, client, model
    )
    return apply_verdicts(claims, exact_matches, verdicts, assays)
