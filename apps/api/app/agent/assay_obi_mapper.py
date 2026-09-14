"""Map extracted assay names to OBI ontology terms.

Matching chain (stops at first hit):
  1a. Exact match on name_in_paper     → resource: exact_original,       confidence: "high"
  1b. Exact match on normalized_name   → resource: exact_normalized_llm, confidence: "high"
  2.  Embedding top-K + LLM pick       → resource: embedding_llm,        confidence: <float>

Both names feed both rounds: each is tried as an exact key, and step 2 retrieves on each and
merges the two candidate pools. `normalized_name` is the extractor's judgement of which
*technique* an assay is, written while reading the whole paper -- see extract_assays.txt. It is
what lets "Surface and intracellular cytokine staining" reach `flow cytometry assay`, a term the
paper's own wording ranks 44th out of 700.

Step 1b replaces an earlier step of the same shape but a different mechanism: an exact match on
the *lexically* normalized name (trailing " assay"/" analysis" stripped), reported as resource
"exact_normalized". That one caught 7 of 156 names and was removed. This one, measured over the
171 curated rows of all_assays_full.json, takes the step-1 hit rate from 39% to 62%. The two are
kept apart under different resource values on purpose: "exact_normalized" is still carried by 40
rows of data/claims/all_assays_full_OBI.json with the retired lexical meaning, and the API route
and web UI still render it.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from openai import OpenAI

from app.agent.assay_extractor import paper_names
from app.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[4]
_OBI_DIR = _REPO_ROOT / "data" / "OBI"
# Pruned vocabulary + matching vectors — see data/OBI/README.md for how they are built.
_OBI_TERMS_PATH = _OBI_DIR / "obi_generic_index.json"
_EMBEDDINGS_PATH = _OBI_DIR / "obi_generic_embeddings.json"
_PROMPTS_DIR = _REPO_ROOT / "apps" / "api" / "app" / "prompts"

#: Not settings.OPENAI_MODEL: this one names an *embedding* model, and the vectors in
#: obi_generic_embeddings.json were built with it. Changing it silently invalidates every one
#: of them -- a query embedded by a different model is not comparable to that matrix.
EMBED_MODEL = "text-embedding-3-small"
TOP_K = 10


# ── Vocabulary pruning ────────────────────────────────────────────────────────

_COMPOSITIONAL_LABEL_RE = re.compile(r"\b(measuring|detecting)\b", re.IGNORECASE)


def _is_generic_assay_label(label: str) -> bool:
    """False for IEDB-style compositional labels ("... assay measuring epitope specific X of
    Y cells").

    These are ~30% of the OBI assay branch (546 of the 1794 terms we index) and they outrank
    the plain family terms in similarity search — 43 of the 45 ELISPOT-ish labels are
    compositional, so an "IFN-y ELISPOT" query buries OBI:0600031 under cytokine-specific
    IEDB constructs. They never belong in the candidate pool.

    "detecting" is the same construct with a different verb, and matching only "measuring" let
    four of them through -- most consequentially OBI:1110207 "assay detecting IFN-gamma
    production", which the resolver then picked four times in a 30-paper run, twice in place of
    OBI:0600031 for an entry the paper called an ELISpot. Exactly the failure described above,
    surviving the filter written to prevent it.

    Only these two verbs. "determining"/"quantifying" match nothing in the index today, and a
    wider pattern starts catching legitimate technique names rather than analyte-specific
    constructs.
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
            # The string this row was actually embedded from: "label | syn1 | syn2 | ...", per
            # build_obi_embeddings.build_text. Carried so _llm_pick can show the model the same
            # wording retrieval matched on, rather than the bare label.
            "text": entries[i].get("text") or entries[i]["label"],
            "similarity": round(float(scores[i]), 4),
        }
        for i in top_indices
    ]


#: How many of a candidate's synonyms to show. CHMO:0000089 carries nine; printing them all
#: for ten candidates buries the labels the model is choosing between.
_MAX_SHOWN_SYNONYMS = 4


def _candidate_line(index: int, candidate: dict[str, Any]) -> str:
    """One numbered candidate, with the synonyms retrieval matched on.

    The `text` field is "label | syn1 | syn2 | ..."; the label is already the first part, so
    only the remainder is appended. Showing them closes a gap that made the model judge a term
    by a name no paper uses -- it saw "enzyme-linked immunosorbent assay" and never "ELISA",
    though the vector it was retrieved by encoded both.
    """
    label = candidate["label"]
    parts = [p.strip() for p in str(candidate.get("text") or label).split("|")]
    synonyms = [p for p in parts[1:] if p and p.lower() != label.lower()][:_MAX_SHOWN_SYNONYMS]
    shown = f"{label} | {' | '.join(synonyms)}" if synonyms else label
    return f"{index}. {candidate['id']} | {shown} (similarity: {candidate['similarity']})"


def build_pick_prompt(
    assay_name: str,
    candidates: list[dict[str, Any]],
    sample_type: str = "",
    readouts: str = "",
    aliases: list[str] | None = None,
) -> str:
    """Render resolver_obi_assay.txt for one pick. Split out so a test can read it without
    reaching the network."""
    named = [a.strip() for a in (aliases or []) if isinstance(a, str) and a.strip()]
    return (
        (_PROMPTS_DIR / "resolver_obi_assay.txt").read_text(encoding="utf-8")
        .replace("{assay_name}", assay_name)
        .replace("{aliases}", ", ".join(named) if named else "none given")
        .replace("{candidates}",
                 "\n".join(_candidate_line(i + 1, c) for i, c in enumerate(candidates)))
        .replace("{sample_type}", sample_type.strip() or "not specified")
        .replace("{readouts}", readouts.strip() or "not specified")
    )


def _llm_pick(
    assay_name: str,
    candidates: list[dict[str, Any]],
    sample_type: str = "",
    readouts: str = "",
    model: str = settings.OPENAI_MODEL,
    aliases: list[str] | None = None,
) -> dict[str, Any] | None:
    """Ask the LLM to pick the best OBI candidate, or say none.

    Runs on the configured model like every other call in the pipeline. It used to be pinned
    to a cheap one on the reasoning that ten labels are already retrieved and the answer is a
    single integer -- but this pick *is* the mapping. Retrieval only narrows to ten; which of
    the ten is right, and whether none of them is, is the whole judgement, and it is the step
    that produced this corpus's wrong answers (phosphoflow analysis onto an imaging-based
    term, whole-transcriptome profiling onto a targeted one). The prompt also asks for
    restraint -- prefer the specific match "only when the specificity is warranted", answer
    "none" when the name is too vague -- and abstention is the system's only defence, since
    _top_k_candidates applies no similarity threshold.
    """
    prompt = build_pick_prompt(assay_name, candidates, sample_type, readouts, aliases)

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model,
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


def _merge_candidates(*pools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union several retrieval pools into one top-K list, keeping each term's best score.

    Neither query dominates, which is the whole reason to merge rather than choose. Measured
    over the 101 distinct (paper name, normalized name) pairs in all_assays_full.json that
    reach this round, the normalized name retrieves a better top-1 on 52% of them and a *worse*
    one on 32%. The losses are systematic, not noise: "hemagglutination inhibition (HAI)
    assays" scores 0.809 against OBI's `viral hemagglutination inhibition assay` and its
    normalized form "Hemagglutination Inhibition" only 0.658, because the verbose paper wording
    is simply closer to the verbose label. Replacing one query with the other trades one set of
    failures for another; the union takes the better of the two every time, for the price of a
    second embedding call and no extra LLM call.

    A term retrieved by both queries is kept once, at its higher similarity — the score is the
    strength of the best evidence for it, not an average over how it was found.
    """
    best: dict[str, dict[str, Any]] = {}
    for pool in pools:
        for candidate in pool or []:
            previous = best.get(candidate["id"])
            if previous is None or candidate.get("similarity", 0) > previous.get("similarity", 0):
                best[candidate["id"]] = candidate
    ranked = sorted(best.values(), key=lambda c: c.get("similarity", 0), reverse=True)
    return ranked[:TOP_K]


def _embedding_llm_match(
    query: str,
    allowed_ids: frozenset[str] | None = None,
    sample_type: str = "",
    readouts: str = "",
    display_name: str = "",
    model: str = settings.OPENAI_MODEL,
    aliases: list[str] | None = None,
    normalized_query: str = "",
) -> dict[str, Any] | None:
    """Retrieve on `query` and `normalized_query`, but show the LLM `display_name`.

    Retrieval and display do different jobs. The normalized name is often the better
    *retrieval* query — it is the conventional technique wording, so it pulls the right
    neighbourhood of OBI terms. But it is the worse thing to *show the model*, because
    normalizing can drop the very detail that picks between a parent term and its child:
    "ImmunoChip array" normalized to "Genome-wide SNP genotyping" loses the word "array", and
    with it the evidence for `genotyping by SNP array assay` over plain `genotyping assay`.

    Both strings are retrieved on and their pools merged — see _merge_candidates for why
    neither can be dropped. The paper's name goes first so the normalized pool, which is the
    one a caller supplies deliberately, is the last thing retrieved.
    """
    if not _EMBEDDINGS_PATH.exists():
        return None
    raw_pool = _top_k_candidates(query, allowed_ids=allowed_ids)
    pools = [raw_pool]
    normalized = normalized_query.strip()
    if normalized and normalized.lower() != query.strip().lower():
        pools.append(_top_k_candidates(normalized, allowed_ids=allowed_ids))
    candidates = _merge_candidates(*pools)
    if not candidates:
        return None
    picked = _llm_pick(
        display_name or query, candidates,
        sample_type=sample_type, readouts=readouts, model=model, aliases=aliases,
    )
    # Attribute the win when only the normalized query could reach the chosen term. Without
    # this, a benchmark run cannot tell whether the normalization earned its keep in step 2 or
    # merely rode along -- and the two justify very different things.
    if picked and len(pools) > 1:
        if picked.get("obi_id") not in {c["id"] for c in raw_pool}:
            picked["resource"] = "embedding_llm_normalized"
    return picked


# ── Public API ────────────────────────────────────────────────────────────────

def map_assay_to_obi(
    name_in_paper: str,
    normalized_name: str = "",
    terms_path: Path = _OBI_TERMS_PATH,
    sample_type: str = "",
    readouts: str = "",
    model: str = settings.OPENAI_MODEL,
    aliases: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return OBI metadata for an assay, or None if nothing passes the threshold.

    terms_path selects the standard vocabulary used for exact-match lookup and
    restricts the embedding fallback's candidate pool to that vocabulary's ids
    (embeddings themselves are still drawn from the full precomputed OBI set).

    sample_type/readouts are only used by the embedding+LLM fallback (step 2), as
    disambiguating context for the LLM's pick among candidates — the exact match
    doesn't need them.

    normalized_name is used in *both* rounds: as an exact-match key of its own (step 1b) and as
    a second retrieval query alongside the paper's name (step 2).

    Step 1b reverses an earlier decision, so it is worth saying why. A lexical normalization
    round used to sit here -- it stripped a trailing " assay"/" analysis" and looked the result
    up -- and it was removed for catching only 7 of 156 names. This is a different mechanism:
    the field now holds an LLM's judgement of *which technique* the assay is, made while reading
    the whole paper, not a string with a suffix chopped off. Measured over the 171 curated rows
    of all_assays_full.json it takes the step-1 hit rate from 39% to 62% -- 40 entries that cost
    two paid calls each now cost none. That is a large enough difference in kind to justify
    reviving the step the lexical version did not earn.

    The paper's own name wins when both keys hit. It is what the paper actually said; the
    normalized form is derived from it, and deriving cannot outrank the source. Only 3 of those
    171 rows disagree at all, and all three are the same pair -- "RNA-seq" resolving to
    `RNA-seq assay` where "RNA sequencing" resolves to `RNA sequencing assay`, two live OBI
    terms for one technique -- where the paper's wording is also the better answer.

    Note what step 1b gives up: an exact match returns immediately, with no similarity score and
    no LLM adjudication, so a confidently wrong normalized_name becomes an unchallenged answer
    where the step-2 path would still have let the picker say "none". The verifier cannot catch
    it either -- `normalized_name` sits in assay_verifier._NOT_PROPOSED because it is a
    judgement about the technique, not a claim about the text. The extraction prompt's wording
    is the only guard, and `resource: "exact_normalized_llm"` is the only way to audit which
    answers took the unguarded path; keep that value distinct from "exact_normalized", which 40
    rows of all_assays_full_OBI.json still carry with the retired lexical meaning.
    """
    lookup = _build_lookup(terms_path)

    # Step 1a — exact on the paper's own name
    result = lookup.get(name_in_paper.strip().lower())
    if result:
        return {**result, "resource": "exact_original", "confidence": "high"}

    # Step 1b — exact on the normalized technique name
    normalized = normalized_name.strip()
    if normalized:
        result = lookup.get(normalized.lower())
        if result:
            return {**result, "resource": "exact_normalized_llm", "confidence": "high"}

    # Step 2 — embedding candidates from both queries (restricted to terms_path's
    # vocabulary), merged into one top-K list, LLM picks best
    original = name_in_paper.strip()
    query = original or normalized
    display_name = query
    if original and normalized and original.lower() != normalized.lower():
        display_name = f"{original} (also described as: {normalized})"
    allowed_ids = _term_ids(terms_path)
    return _embedding_llm_match(
        query,
        allowed_ids=allowed_ids,
        sample_type=sample_type,
        readouts=readouts,
        display_name=display_name,
        model=model,
        aliases=aliases,
        normalized_query=normalized,
    )


def enrich_assays_with_obi(
    assays: dict[str, Any],
    terms_path: Path = _OBI_TERMS_PATH,
    model: str = settings.OPENAI_MODEL,
) -> dict[str, dict[str, Any]]:
    """Add OBI fields to a Phase-1 assay registry keyed by assay name.

    The OBI score is written as `obi_confidence`, never `confidence`: registries carry the
    *extraction* confidence under the latter (how clearly the paper identifies the technique),
    and overwriting it destroys that. scripts/map_assays_to_obi.py, data/claims/all_assays_full_OBI.json
    and the UI (apps/web/src/lib/types.ts) are all already on `obi_confidence`.
    Whatever `confidence` the caller passed in is left exactly as it was.

    **`obi_confidence` is not comparable across resources, and is not a correctness signal.**
    It is the literal string "high" for an exact match and a raw cosine similarity for an
    embedding one -- measured over a 30-paper corpus, 47 of the former and 117 of the latter.
    Worse, the float does not track whether the mapping is right: correct ELISA matches scored
    0.47 while a wrong `phosphoflow analysis` -> imaging-based term scored 0.61, because the
    query is a bare assay name and the row it is compared against is "label | syn1 | syn2 | ...",
    so a short name against a many-synonym term scores low however right it is. Do not threshold
    on this field. What separates a good mapping from a bad one is whether the OBI term names
    the same technique or a parent of it, which no number here expresses.

    `normalized_name` is read when the entry carries it and never written. Registries extracted
    before it joined assay_extractor.ENTRY_FIELDS do not have it, and neither do the ones
    assay_registry.registry_from_claims builds -- it lists the field among those a claims-derived
    registry structurally cannot supply. Both cases pass the empty string, which makes step 1b a
    no-op and leaves step 2 retrieving on `name_in_paper` alone: exactly the behaviour every
    existing registry had before this field existed. Nothing needs re-extracting to keep working;
    re-extraction is only how a registry starts benefiting.
    """
    enriched: dict[str, dict[str, Any]] = {}
    for canonical, value in assays.items():
        entry: dict[str, Any] = dict(value) if isinstance(value, dict) else {"description": value}
        # First wording, not the whole list: a registry already canonicalized by round 5 carries
        # every wording of a folded entry, and the lookup takes one name. The stored list is
        # preserved as-is -- only the query is a single string.
        names = paper_names(entry)
        original = names[0] if names else canonical
        if not names:
            entry["name_in_paper"] = original

        sample_type = str(entry.get("sample_type") or "")
        readouts = str(entry.get("readouts") or "")
        raw_aliases = entry.get("aliases")
        normalized_name = str(entry.get("normalized_name") or "")
        mapped = map_assay_to_obi(
            original, normalized_name, terms_path=terms_path,
            sample_type=sample_type, readouts=readouts, model=model,
            aliases=raw_aliases if isinstance(raw_aliases, list) else None,
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
