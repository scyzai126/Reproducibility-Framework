"""Map extracted assay names to OBI ontology terms.

Matching chain (stops at first hit):
  1. Exact match on original_name   → confidence: high
  2. Exact match on normalized_name → confidence: medium
  3. Embedding top-10 + LLM pick    → confidence: low  (fallback)
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from openai import OpenAI

_REPO_ROOT = Path(__file__).resolve().parents[4]
_OBI_TERMS_PATH = _REPO_ROOT / "data" / "obi_assay_terms.json"
_EMBEDDINGS_PATH = _REPO_ROOT / "data" / "obi_assay_embeddings.json"
_PROMPTS_DIR = _REPO_ROOT / "apps" / "api" / "app" / "prompts"

EMBED_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4o-mini"
TOP_K = 10


# ── Exact-match helpers ───────────────────────────────────────────────────────

def _index_keys(text: str) -> list[str]:
    """Lowercase + optionally strip trailing ' assay' (OBI labels carry it, paper names don't)."""
    key = text.strip().lower()
    keys = [key]
    if key.endswith(" assay"):
        keys.append(key[: -len(" assay")].strip())
    return keys


@lru_cache(maxsize=1)
def _build_lookup() -> dict[str, dict[str, str]]:
    terms = json.loads(_OBI_TERMS_PATH.read_text(encoding="utf-8"))
    lookup: dict[str, dict[str, str]] = {}
    for term in terms:
        obi_id = term.get("id", "")
        label = term.get("label", "")
        if not obi_id or not label:
            continue
        entry = {"obi_id": obi_id, "obi_label": label}
        for key in _index_keys(label):
            lookup.setdefault(key, entry)
        for syn in term.get("synonyms", []):
            if syn:
                for key in _index_keys(str(syn)):
                    lookup.setdefault(key, entry)
    return lookup


# ── Embedding helpers ─────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_embeddings() -> tuple[list[dict], np.ndarray]:
    """Load cached OBI embeddings. Returns (entries, matrix) where matrix shape is (N, 1536)."""
    entries = json.loads(_EMBEDDINGS_PATH.read_text(encoding="utf-8"))
    matrix = np.array([e["embedding"] for e in entries], dtype=np.float64)
    # Pre-normalise rows so cosine similarity reduces to a dot product
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.where(norms == 0, 1, norms)
    return entries, matrix


def _embed_query(text: str) -> np.ndarray:
    client = OpenAI()
    resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
    vec = np.array(resp.data[0].embedding, dtype=np.float64)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def _top_k_candidates(query: str, k: int = TOP_K) -> list[dict[str, Any]]:
    """Return the top-k OBI entries by cosine similarity to the query string."""
    entries, matrix = _load_embeddings()
    vec = _embed_query(query)
    scores = np.dot(matrix, vec)
    top_indices = np.argsort(scores)[-k:][::-1]
    return [
        {
            "id": entries[i]["id"],
            "label": entries[i]["label"],
            "similarity": round(float(scores[i]), 4),
        }
        for i in top_indices
    ]


def _llm_pick(assay_name: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Ask the LLM to pick the best OBI candidate, or say none."""
    prompt_template = (_PROMPTS_DIR / "resolver_obi_assay.txt").read_text(encoding="utf-8")
    candidate_lines = "\n".join(
        f"{i + 1}. {c['id']} | {c['label']} (similarity: {c['similarity']})"
        for i, c in enumerate(candidates)
    )
    prompt = prompt_template.replace("{assay_name}", assay_name).replace("{candidates}", candidate_lines)

    client = OpenAI()
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    reply = (resp.choices[0].message.content or "").strip().lower()

    if reply == "none":
        return None
    match = re.search(r"\d+", reply)
    if not match:
        return None
    idx = int(match.group()) - 1
    if not (0 <= idx < len(candidates)):
        return None
    chosen = candidates[idx]
    return {
        "obi_id": chosen["id"],
        "obi_label": chosen["label"],
        "obi_match_type": "embedding_llm",
        "confidence": "low",
        "similarity": chosen["similarity"],
    }


def _embedding_llm_match(query: str) -> dict[str, Any] | None:
    if not _EMBEDDINGS_PATH.exists():
        return None
    candidates = _top_k_candidates(query)
    return _llm_pick(query, candidates)


# ── Public API ────────────────────────────────────────────────────────────────

def map_assay_to_obi(original_name: str, normalized_name: str) -> dict[str, Any] | None:
    """Return OBI metadata for an assay, or None if nothing passes the threshold."""
    lookup = _build_lookup()

    # Step 1 — exact on original
    result = lookup.get(original_name.strip().lower())
    if result:
        return {**result, "obi_match_type": "original", "confidence": "high"}

    # Step 2 — exact on normalized
    norm = normalized_name.strip().lower()
    if norm and norm != original_name.strip().lower():
        result = lookup.get(norm)
        if result:
            return {**result, "obi_match_type": "normalized", "confidence": "medium"}

    # Step 3 — embedding top-10 candidates, LLM picks best
    return _embedding_llm_match(normalized_name.strip())


def enrich_assays_with_obi(assays: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Add OBI fields to a Phase-1 assay registry keyed by canonical assay name."""
    enriched: dict[str, dict[str, Any]] = {}
    for canonical, value in assays.items():
        entry: dict[str, Any] = dict(value) if isinstance(value, dict) else {"description": value}
        original = entry.get("original_name") or canonical
        normalized = entry.get("normalized_name") or canonical

        mapped = map_assay_to_obi(original, normalized)
        if mapped:
            entry.update(mapped)
        else:
            entry.setdefault("obi_id", None)
            entry.setdefault("obi_label", None)
            entry.setdefault("obi_match_type", "unresolved")
            entry.setdefault("confidence", "low")
            entry.setdefault("similarity", None)

        enriched[canonical] = entry
    return enriched
