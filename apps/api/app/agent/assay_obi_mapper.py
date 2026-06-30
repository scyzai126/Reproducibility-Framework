"""Map extracted assay names to local OBI ontology terms."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[4]
_CURATED_MAP = _REPO_ROOT / "data" / "claims" / "assay_obi_map.json"
_ONTOLOGY_FILES = (
    _REPO_ROOT / "data" / "obi_immuno_assay_terms.json",
    _REPO_ROOT / "data" / "obi_assay_terms.json",
)


def _normalize(text: str) -> str:
    """Normalize assay labels for exact matching across punctuation variants."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _match_keys(text: str) -> set[str]:
    key = _normalize(text)
    keys = {key} if key else set()
    if key.endswith(" assay"):
        keys.add(key.removesuffix(" assay").strip())
    return keys


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


@lru_cache(maxsize=1)
def _obi_lookup() -> dict[str, dict[str, str]]:
    """Build normalized label/synonym -> OBI term lookup from curated and OBI files."""
    lookup: dict[str, dict[str, str]] = {}

    # Curated names take precedence over ontology synonym matches. This lets us
    # choose intentionally broad parent terms for project-level assay categories.
    for row in _load_json_list(_CURATED_MAP):
        assay = str(row.get("assay") or "")
        obi_id = str(row.get("obi_id") or "")
        obi_label = str(row.get("obi_label") or "")
        if assay and obi_id and obi_label:
            term = {
                "obi_id": obi_id,
                "obi_label": obi_label,
                "obi_match_type": "curated",
            }
            for key in _match_keys(assay):
                lookup[key] = term

    for path in _ONTOLOGY_FILES:
        for row in _load_json_list(path):
            obi_id = str(row.get("id") or "")
            label = str(row.get("label") or "")
            if not obi_id or not label:
                continue
            term = {
                "obi_id": obi_id,
                "obi_label": label,
                "obi_match_type": "ontology_exact",
            }
            for candidate in [label, *row.get("synonyms", [])]:
                for key in _match_keys(str(candidate or "")):
                    lookup.setdefault(key, term)

    return lookup


def map_assay_to_obi(assay_name: str) -> dict[str, str] | None:
    """Return OBI metadata for an extracted assay name, if locally resolvable."""
    return _obi_lookup().get(_normalize(assay_name))


def enrich_assays_with_obi(assays: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Add OBI metadata to a Phase-1 assay registry without changing assay keys."""
    enriched: dict[str, dict[str, Any]] = {}
    for assay_name, value in assays.items():
        entry: dict[str, Any]
        if isinstance(value, dict):
            entry = dict(value)
        else:
            entry = {"description": value}

        mapped = map_assay_to_obi(assay_name)
        if mapped:
            entry.update(mapped)
        else:
            entry.setdefault("obi_id", None)
            entry.setdefault("obi_label", None)
            entry.setdefault("obi_match_type", "unresolved")

        enriched[assay_name] = entry
    return enriched
