"""Build the assay registry from claims that self-name their own assay.

Assay discovery used to be its own full-paper LLM pass (extract_assays_*.txt), reconciled
against the claims by app.agent.assay_claim_linker. Both are gone: every claim pipeline
now names its own assay -- extract_claims_pdf.txt emits an `assay` object per claim, and
claim_abstraction_v5 publishes the same value as `assay_method_in_paper` -- so the registry
is derived from the claims rather than extracted a second time and merged back.

The output shape matches what app.agent.assay_obi_mapper.enrich_assays_with_obi and
app.agent.query_builder's `assay_registry` lookup consume, with one caveat: `sample_type`
and `readouts` come back empty, because claims do not carry them. Those two are used only
by step 3 of OBI mapping (embedding top-10 + resolver_obi_assay.txt, whose prompt treats
them as secondary disambiguating context) and as the `readouts` hint handed to
resolve_experiment_accession. The exact-match steps ignore them entirely. They are left
empty rather than guessed.
"""

import re

#: Where a claim carries its self-reported assay name, in priority order:
#: ("assay", "name_in_paper") is the extract_claims_pdf.txt shape, and
#: ("assay_method_in_paper",) is claim_abstraction_v5's published field.
_ASSAY_NAME_PATHS = (("assay", "name_in_paper"), ("assay_method_in_paper",))


def _normalize(text: str) -> str:
    """Lowercase, strip a trailing ' assay'/' analysis', collapse whitespace."""
    key = re.sub(r"\s+", " ", (text or "").strip().lower())
    for suffix in (" assay", " analysis"):
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
    return key


def claim_assay_name(claim: dict) -> str:
    """The assay name a claim reports for itself, from whichever field carries it."""
    for path in _ASSAY_NAME_PATHS:
        value: object = claim
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def registry_from_claims(claims: dict) -> dict:
    """Build an assay registry keyed by the paper's own wording for each assay.

    Claims are visited in order, so the registry is deterministic. Names that normalize to
    the same key are one entry: the first exact wording seen becomes the registry key and
    `name_in_paper`, and every later variant of it becomes an alias. A claim with no assay
    name contributes nothing.
    """
    registry: dict[str, dict] = {}
    key_by_norm: dict[str, str] = {}

    for claim in claims.values():
        if not isinstance(claim, dict):
            continue
        name = claim_assay_name(claim)
        norm = _normalize(name)
        if not norm:
            continue

        registry_key = key_by_norm.get(norm)
        if registry_key is None:
            key_by_norm[norm] = name
            registry[name] = {
                "name_in_paper": name,
                "aliases": [],
                "sample_type": "",
                "readouts": "",
            }
        elif name != registry_key and name not in registry[registry_key]["aliases"]:
            registry[registry_key]["aliases"].append(name)

    return registry
