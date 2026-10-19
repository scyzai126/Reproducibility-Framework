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

import json
import logging
import re
from pathlib import Path

from app.agent.assay_extractor import paper_names

logger = logging.getLogger(__name__)

#: Where a claim carries its self-reported assay name, in priority order:
#: ("assay", "name_in_paper") is the extract_claims_pdf.txt shape, and
#: ("assay_method_in_paper",) is claim_abstraction_v5's published field.
_ASSAY_NAME_PATHS = (("assay", "name_in_paper"), ("assay_method_in_paper",))


#: Suffixes stripped to reach the lookup key, longest first so " assays" is tried before
#: " assay". The plural forms matter for joining: a paper writes "HAI antibody titer assays"
#: in Methods and a claim reports "HAI antibody titer assay", and without folding both the
#: two never meet.
_STRIPPED_SUFFIXES = (" analyses", " analysis", " assays", " assay")


def normalize_assay_name(text: str) -> str:
    """Lowercase, strip a trailing ' assay(s)'/' analysis'/' analyses', collapse whitespace.

    Shared with app.agent.assay_obi_mapper, whose step-2 exact lookup uses it to reach OBI
    labels the paper's raw wording misses ("Flow Cytometry Analysis" -> "flow cytometry").
    Purely lexical on purpose: it is a dedup/lookup key, not a canonical name.
    """
    key = re.sub(r"\s+", " ", (text or "").strip().lower())
    for suffix in _STRIPPED_SUFFIXES:
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
            break
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
        norm = normalize_assay_name(name)
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


#: Fields the verified registry carries that a claims-derived entry cannot: `sample_type` and
#: `readouts` exist on one but are empty. `platform` is no longer extracted and stays listed only
#: so a registry written before it was dropped still contributes it -- the copy is conditional on
#: the value being there, so a current registry simply has nothing to give.
_ENRICHED_FIELDS = ("platform", "sample_type", "readouts")

#: The corpus folder, and the versioned result folder inside it that holds the benchmark
#: papers' registries. Every reader of `data/31paper_assays/<version>/<pmid>_<SDY>/` derives its
#: root from these two -- assay_service.REGISTRY_ROOT included -- so bumping the version is one
#: edit. Defined here rather than in assay_service because this module sits below it in the
#: import graph. The previous layout had the registries directly under the corpus folder; they
#: moved into a versioned subfolder and every root that still pointed one level up found nothing.
CORPUS_ROOT = Path(__file__).resolve().parents[4] / "data" / "31paper_assays"
RESULT_VERSION = "assay_result_v1"
#: Where scripts/run_assay_extract.py writes its registries.
_REGISTRY_ROOT = CORPUS_ROOT / RESULT_VERSION
#: Where a paper outside the benchmark keeps its registry (assay_service.CACHE_ROOT).
_CACHE_ROOT = Path(__file__).resolve().parents[4] / "data" / "cache" / "assays"


def load_verified_registry(pubmed_id: str, study_accession: str) -> dict:
    """Read the extracted registry for a paper, or `{}` when there is none.

    The directory is `<pmid>_<SDY>`, but the swapped spelling is tried too, for the reason
    run_assay_verify.locate_xml gives: the directory schemes in this repo were named
    independently and disagree on the order of the two halves.

    A missing or malformed file is not an error. This registry is an optional enrichment --
    every paper still resolves from its claims alone, exactly as before.
    """
    pmid, sdy = (pubmed_id or "").strip(), (study_accession or "").strip()
    if not pmid or not sdy:
        return {}

    # `_pdf` marks a registry built from the paper's PDF (assay_service.PDF_DIR_SUFFIX).
    stems = (f"{pmid}_{sdy}", f"{sdy}_{pmid}", f"{pmid}_{sdy}_pdf", f"{sdy}_{pmid}_pdf")
    for path in (root / stem / "assays.json" for root in (_REGISTRY_ROOT, _CACHE_ROOT)
                 for stem in stems):
        if not path.exists():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("assay registry at %s could not be read; ignoring it", path)
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def surface_forms(name: str, entry: dict) -> list[str]:
    """Every wording a registry entry answers to: its key, `name_in_paper`, and its aliases."""
    return [name] + paper_names(entry) + [
        a for a in (entry.get("aliases") or []) if isinstance(a, str)]


def index_registry(registry: dict) -> dict[str, str]:
    """Map the normalized form of every entry's surface forms to that entry's registry key.

    Indexed by every surface form, not by the key alone: round 5 re-keys the verified registry
    by its OBI term, so its keys are labels like "enzyme-linked immunosorbent assay" while a
    claim still says "ELISA". The wordings are all still there, in `name_in_paper` and
    `aliases` -- matching on the key alone would silently stop matching claims the day that
    round ran. The first entry to claim a form keeps it.
    """
    index: dict[str, str] = {}
    for name, entry in (registry or {}).items():
        if not isinstance(entry, dict):
            continue
        for form in surface_forms(name, entry):
            key = normalize_assay_name(form)
            if key:
                index.setdefault(key, name)
    return index


def merge_verified(claims_registry: dict, verified: dict) -> dict:
    """Enrich claims-derived entries with the verified registry's extra fields.

    Matched by `normalize_assay_name` over every wording an entry carries -- its key, its
    `name_in_paper` and its aliases -- so "HAI antibody titer assay" from a claim reaches
    "...assays" from Methods, and "ELISA" still reaches an entry round 5 re-keyed to
    "enzyme-linked immunosorbent assay".

    **Only ever adds.** The claims registry decides which entries exist -- it is keyed by the
    wording `query_builder` looks up, and an assay a claim names but the registry missed must
    keep its entry or that claim loses its resolution path entirely. A verified entry with no
    claim referencing it is likewise ignored: nothing would ever look it up.
    """
    by_key = {norm: verified[key] for norm, key in index_registry(verified).items()}

    merged: dict = {}
    for name, entry in (claims_registry or {}).items():
        entry = dict(entry)
        source = by_key.get(normalize_assay_name(name))
        if source:
            for field in _ENRICHED_FIELDS:
                value = source.get(field)
                if value and not entry.get(field):
                    entry[field] = value
            aliases = list(entry.get("aliases") or [])
            aliases += [a for a in (source.get("aliases") or [])
                        if isinstance(a, str) and a and a != name and a not in aliases]
            entry["aliases"] = aliases
        merged[name] = entry
    return merged
