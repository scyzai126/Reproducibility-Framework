"""Map extracted assay names to OBI ontology terms.

Matching chain (stops at first hit):
  1. Exact match on name_in_paper   → resource: exact_original,  confidence: "high"
  2. Exact match on normalized_name → resource: exact_normalized, confidence: "high"
  3. Embedding top-10 + LLM pick    → resource: embedding_llm,   confidence: <similarity float>
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from openai import OpenAI

from app.agent.assay_registry import normalize_assay_name
from app.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[4]
_OBI_DIR = _REPO_ROOT / "data" / "OBI"
# Pruned vocabulary + matching vectors — see data/OBI/README.md for how they are built.
_OBI_TERMS_PATH = _OBI_DIR / "obi_generic_index.json"
_EMBEDDINGS_PATH = _OBI_DIR / "obi_generic_embeddings.json"
_PROMPTS_DIR = _REPO_ROOT / "apps" / "api" / "app" / "prompts"

EMBED_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4o-mini"
TOP_K = 10


# ── Vocabulary pruning ────────────────────────────────────────────────────────

_COMPOSITIONAL_LABEL_RE = re.compile(r"\bmeasuring\b", re.IGNORECASE)


def _is_generic_assay_label(label: str) -> bool:
    """False for IEDB-style compositional labels ("... assay measuring epitope specific X of
    Y cells").

    These are ~30% of the OBI assay branch (532 of the 1794 terms we index) and they outrank
    the plain family terms in similarity search — 43 of the 45 ELISPOT-ish labels are
    compositional, so an "IFN-y ELISPOT" query buries OBI:0600031 under cytokine-specific
    IEDB constructs. They never belong in the candidate pool.
    """
    return not _COMPOSITIONAL_LABEL_RE.search(label or "")


# ── Exact-match helpers ───────────────────────────────────────────────────────

def _index_keys(text: str) -> list[str]:
    """Lowercase + optionally strip trailing ' assay' (OBI labels carry it, paper names don't)."""
    key = text.strip().lower()
    keys = [key]
    if key.endswith(" assay"):
        keys.append(key[: -len(" assay")].strip())
    return keys


@lru_cache(maxsize=8)
def _build_lookup(terms_path: Path = _OBI_TERMS_PATH) -> dict[str, dict[str, str]]:
    terms = json.loads(terms_path.read_text(encoding="utf-8"))
    lookup: dict[str, dict[str, str]] = {}
    for term in terms:
        obi_id = term.get("id", "")
        label = term.get("label", "")
        if not obi_id or not label or not _is_generic_assay_label(label):
            continue
        entry = {"obi_id": obi_id, "obi_label": label}
        for key in _index_keys(label):
            lookup.setdefault(key, entry)
        for syn in term.get("synonyms", []):
            if syn:
                for key in _index_keys(str(syn)):
                    lookup.setdefault(key, entry)
    return lookup


@lru_cache(maxsize=8)
def _term_ids(terms_path: Path) -> frozenset[str]:
    """Generic OBI ids in a given terms file — used to restrict embedding candidates."""
    terms = json.loads(terms_path.read_text(encoding="utf-8"))
    return frozenset(
        t["id"] for t in terms if t.get("id") and _is_generic_assay_label(t.get("label", ""))
    )


# ── Embedding helpers ─────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_embeddings() -> tuple[list[dict], np.ndarray]:
    """Load cached OBI embeddings. Returns (entries, matrix) where matrix shape is (N, 1536)."""
    entries = json.loads(_EMBEDDINGS_PATH.read_text(encoding="utf-8"))
    # Prune before the matrix is built so entries and matrix rows stay index-aligned
    entries = [e for e in entries if _is_generic_assay_label(e.get("label", ""))]
    matrix = np.array([e["embedding"] for e in entries], dtype=np.float64)
    # Pre-normalise rows so cosine similarity reduces to a dot product
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.where(norms == 0, 1, norms)
    return entries, matrix


def _embed_query(text: str) -> np.ndarray:
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
    vec = np.array(resp.data[0].embedding, dtype=np.float64)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def _top_k_candidates(
    query: str, k: int = TOP_K, allowed_ids: frozenset[str] | None = None
) -> list[dict[str, Any]]:
    """Return the top-k OBI entries by cosine similarity to the query string.

    If allowed_ids is given, restrict candidates to entries whose id is in that set
    (e.g. a curated subset like obi_immuno_assay_terms.json) even though embeddings
    are precomputed over the full OBI term list.
    """
    entries, matrix = _load_embeddings()
    if allowed_ids is not None:
        keep = [i for i, e in enumerate(entries) if e["id"] in allowed_ids]
        entries = [entries[i] for i in keep]
        matrix = matrix[keep]
    vec = _embed_query(query)
    scores = np.dot(matrix, vec)
    k = min(k, len(entries))
    top_indices = np.argsort(scores)[-k:][::-1]
    return [
        {
            "id": entries[i]["id"],
            "label": entries[i]["label"],
            "similarity": round(float(scores[i]), 4),
        }
        for i in top_indices
    ]


def _llm_pick(
    assay_name: str, candidates: list[dict[str, Any]], sample_type: str = "", readouts: str = ""
) -> dict[str, Any] | None:
    """Ask the LLM to pick the best OBI candidate, or say none."""
    prompt_template = (_PROMPTS_DIR / "resolver_obi_assay.txt").read_text(encoding="utf-8")
    candidate_lines = "\n".join(
        f"{i + 1}. {c['id']} | {c['label']} (similarity: {c['similarity']})"
        for i, c in enumerate(candidates)
    )
    prompt = (
        prompt_template.replace("{assay_name}", assay_name)
        .replace("{candidates}", candidate_lines)
        .replace("{sample_type}", sample_type.strip() or "not specified")
        .replace("{readouts}", readouts.strip() or "not specified")
    )

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
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
        "resource": "embedding_llm",
        "confidence": chosen["similarity"],
    }


def _embedding_llm_match(
    query: str,
    allowed_ids: frozenset[str] | None = None,
    sample_type: str = "",
    readouts: str = "",
    display_name: str = "",
) -> dict[str, Any] | None:
    """Retrieve on `query`, but show the LLM `display_name` when they differ.

    The two do different jobs. The normalized name is the better *retrieval* query —
    it is the cleaned-up, conventional wording, so it pulls the right neighbourhood of
    OBI terms. But it is the worse thing to *show the model*, because normalizing can
    drop the very detail that picks between a parent term and its child: "ImmunoChip
    array" normalized to "Genome-wide SNP genotyping" loses the word "array", and with
    it the evidence for `genotyping by SNP array assay` over plain `genotyping assay`.
    """
    if not _EMBEDDINGS_PATH.exists():
        return None
    candidates = _top_k_candidates(query, allowed_ids=allowed_ids)
    if not candidates:
        return None
    return _llm_pick(
        display_name or query, candidates, sample_type=sample_type, readouts=readouts
    )


# ── Public API ────────────────────────────────────────────────────────────────

def map_assay_to_obi(
    name_in_paper: str,
    normalized_name: str = "",
    terms_path: Path = _OBI_TERMS_PATH,
    sample_type: str = "",
    readouts: str = "",
) -> dict[str, Any] | None:
    """Return OBI metadata for an assay, or None if nothing passes the threshold.

    terms_path selects the standard vocabulary used for exact-match lookup and
    restricts the embedding fallback's candidate pool to that vocabulary's ids
    (embeddings themselves are still drawn from the full precomputed OBI set).

    sample_type/readouts are only used by the embedding+LLM fallback (step 3), as
    disambiguating context for the LLM's pick among candidates — exact matches
    (steps 1-2) don't need them.

    The lexical key normalize_assay_name() derives is used for the step-2 lookup only. It is
    deliberately kept out of step 3: lowercasing and dropping a trailing " assay"/" analysis"
    adds no semantic information, so it is no better as a retrieval query, and threading it
    into display_name would put a meaningless "(also described as: ...)" in front of the LLM.
    """
    lookup = _build_lookup(terms_path)

    # Step 1 — exact on original
    result = lookup.get(name_in_paper.strip().lower())
    if result:
        return {**result, "resource": "exact_original", "confidence": "high"}

    # Step 2 — exact on normalized. Two keys are tried: the caller's normalized_name, then
    # the lexical form of the paper's own name. The second is what saves registries that
    # carry no normalized_name at all (the extract-assay-methods skill emits none, so
    # enrich_assays_with_obi passes the registry key back in and the first key is a no-op):
    # "Flow Cytometry Analysis" reduces to "flow cytometry", an exact hit for OBI:0000916,
    # instead of falling through to a paid embedding+LLM round.
    original_key = name_in_paper.strip().lower()
    for norm in (normalized_name.strip().lower(), normalize_assay_name(name_in_paper)):
        if norm and norm != original_key:
            result = lookup.get(norm)
            if result:
                return {**result, "resource": "exact_normalized", "confidence": "high"}

    # Step 3 — embedding top-10 candidates (restricted to terms_path's vocabulary), LLM picks best
    query = normalized_name.strip() or name_in_paper.strip()
    original = name_in_paper.strip()
    display_name = query
    if original and original.lower() != query.lower():
        display_name = f"{original} (also described as: {query})"
    allowed_ids = _term_ids(terms_path)
    return _embedding_llm_match(
        query,
        allowed_ids=allowed_ids,
        sample_type=sample_type,
        readouts=readouts,
        display_name=display_name,
    )


def enrich_assays_with_obi(
    assays: dict[str, Any], terms_path: Path = _OBI_TERMS_PATH
) -> dict[str, dict[str, Any]]:
    """Add OBI fields to a Phase-1 assay registry keyed by assay name.

    The OBI score is written as `obi_confidence`, never `confidence`: registries carry the
    *extraction* confidence under the latter (how clearly the paper identifies the technique),
    and overwriting it destroys that. scripts/map_assays_to_obi.py, data/claims/all_assays_full_OBI.json
    and the UI (apps/web/src/lib/types.ts) are all already on `obi_confidence`.
    Whatever `confidence` the caller passed in is left exactly as it was.
    """
    enriched: dict[str, dict[str, Any]] = {}
    for canonical, value in assays.items():
        entry: dict[str, Any] = dict(value) if isinstance(value, dict) else {"description": value}
        original = entry.get("name_in_paper") or canonical
        normalized = entry.get("normalized_name") or canonical

        # Always write these so the output file is self-contained
        entry["name_in_paper"] = original
        entry["normalized_name"] = normalized

        sample_type = str(entry.get("sample_type") or "")
        readouts = str(entry.get("readouts") or "")
        mapped = map_assay_to_obi(
            original, normalized, terms_path=terms_path, sample_type=sample_type, readouts=readouts
        )
        if mapped:
            entry["obi_id"] = mapped["obi_id"]
            entry["obi_label"] = mapped["obi_label"]
            entry["resource"] = mapped["resource"]
            entry["obi_confidence"] = mapped["confidence"]
        else:
            entry["obi_id"] = None
            entry["obi_label"] = None
            entry["resource"] = "unresolved"
            # Unconditional, not setdefault: a stale extraction confidence sitting next to
            # resource="unresolved" reads as an OBI score.
            entry["obi_confidence"] = None

        enriched[canonical] = entry
    return enriched
