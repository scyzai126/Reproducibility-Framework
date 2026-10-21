"""Map extracted assay names to OBI ontology terms.

Matching chain (stops at first hit):
  1. Exact match on name_in_paper, onto a term with no children in the index
                                       → resource: exact_original,       confidence: "high"
  1b. Exact match onto a term that has children: the hit is where step 2 starts from
      (descend: the walk begins at the hit; embedding: the hit and its direct children are
      pinned into the candidates), and the picker chooses
                                       → resource: exact_original_llm
  2. Step 2 is one of two strategies, chosen by settings.OBI_MAPPING_STRATEGY:
     "embedding" (default): top-K by vector similarity + one LLM pick (_embedding_llm_match)
                                       → resource: embedding_llm,        confidence: <float>
     The list also carries the direct OBI parents and children of its top retrieved terms
     (_with_neighbours); a pick that only they could reach is attributed
     "embedding_llm_neighbour", one only the technique query reached "embedding_llm_normalized".
     "descend" (opt-in): walk the OBI assay tree top-down, one chat call per level, each
     choosing among the current term's direct children or stopping on the current term
     (_descend)                        → resource: descend_llm,          confidence: None

The descent (2026-10-20) is an alternative under evaluation, not the default. The case for
it: retrieval ranks the term a paper's wording *resembles*, which is often a parent or
sibling of the term the record warrants, and the picker can only choose among the twenty it
is shown, whereas the walk shows the picker every child of the term it is on, so the choice
between a term and its children is always made by the record and never by what retrieval
happened to rank. The tree is shallow -- 701 terms, 96 at the top, 335 at depth 2, the deepest
at 5 -- so a walk is typically 2-3 chat calls and spends no embedding calls. The case against
making it the default yet: it has not been compared with the embedding path on the curated
benchmark (where retrieval puts the curator's term among the 20 shown 91% of the time); its
first level, the 96 parentless terms of the index (47 of them leaves, many there only because
their real parent was pruned), is a wrong turn nothing below can recover from; it spends 1-2
more chat calls per unmatched assay, the first on a ~8k-token prompt; and a mapping made of
2-3 consecutive judgements compounds the run-to-run variance the single pick already shows.
An exact hit on the paper's name skips the first level (the walk starts at the hit). The two
strategies are meant to be run side by side on the same registries (scripts/run_assay_merge.py
--map-all under each setting, scored by scripts/compare_assay_benchmark.py) before the
default moves.

Only the paper's own name is an exact key. Step 2 retrieves on it and on `standard_technique_name` and
merges the two candidate pools. `standard_technique_name` is the extractor's judgement of which
*technique* an assay is, written while reading the whole paper -- see extract_assays.txt. It is
what pulls `flow cytometry assay` into the pool for "Surface and intracellular cytokine
staining", a term the paper's own wording ranks 44th out of 700.

Two exact rounds on a technique existed and were both removed, and their resource values
stay known because stored registries carry them: "exact_normalized" (a lexical strip of
" assay"/" analysis", 7 of 156 names, removed first) and "exact_normalized_llm" (an exact match
on `standard_technique_name`, removed 2026-10-02). The second answered for free but too generally: it
was the source of 33 of the 52 rows that disagreed with the curator benchmark, because the
technique name drops exactly the words that pick a child term over its parent ("single-cell",
"bulk", "reverse transcription", "transcription profiling") and an exact hit never reached the
picker that could have chosen the child.

Step 1 on the paper's own name has the same failure, less often: papers name an assay by the
bare technique word ("RNA-seq", "microarray", "flow cytometry"), which is the *parent* label.
In the 31-paper v1 results 29 of 39 exact hits landed on a term with children in the index --
"RNA Sequencing" on the most generic `RNA sequencing assay`, every "RNA-seq" on `RNA-seq assay`
and never on its bulk or single-cell child. So an exact hit only answers outright when the
index holds nothing more specific under it (ELISA, ELISpot: their compositional children were
pruned). Otherwise it becomes a guaranteed candidate, together with its direct children, which
embedding retrieval on a bare "RNA-seq" does not reliably rank.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from openai import OpenAI

from app.agent import assay_trace
from app.agent.assay_extractor import EXTRACTION_SEED, paper_names
from app.config import settings

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_OBI_DIR = _REPO_ROOT / "data" / "OBI"
# Pruned vocabulary + matching vectors — see data/OBI/README.md for how they are built.
_OBI_TERMS_PATH = _OBI_DIR / "obi_assay_pruned_index.json"
_EMBEDDINGS_PATH = _OBI_DIR / "obi_assay_pruned_embeddings.json"
#: Fallback source of the `is_a` edges, for a terms file built before the index carried
#: `parents` (every entry's direct is_a parents, id and label). The live index has carried them since
#: 2026-10-20, so obi.obo is off the serving path; `n_descendants` still counts the full
#: ontology and so calls ELISA (53) a parent though the index holds none of them.
_OBO_PATH = _OBI_DIR / "obi.obo"
_PROMPTS_DIR = _REPO_ROOT / "apps" / "api" / "app" / "prompts"

#: Not settings.OPENAI_MODEL: this one names an *embedding* model, and the vectors in
#: obi_assay_pruned_embeddings.json were built with it. Changing it silently invalidates every one
#: of them -- a query embedded by a different model is not comparable to that matrix.
EMBED_MODEL = "text-embedding-3-small"
#: Candidates the picker sees. 20, not 10, since 2026-10-02: over 150 benchmark rows the
#: curator's term is among the merged candidates 87% of the time at 10 and 91% at 20, and the
#: rows 11-20 recovers are real misses (transcription profiling by array assay, bulk RNA-seq).
TOP_K = 20
#: Slots in the merged list reserved for the paper-wording query; the technique query fills
#: the rest. The technique name scores high against short generic labels, and a plain merge by
#: score let those push the paper wording's specific candidates out.
PRIMARY_SLOTS = 14
#: Retrieved candidates whose direct OBI parents and children join the list (_with_neighbours),
#: and the family size above which a term's children stay out. Measured over 144 curated rows
#: (benchmark v4 vs the stability run, scripts/eval_obi_retrieval.py): the curator's term was
#: among the 20 retrieved in 140; of the 4 misses, 1 was a child of the top candidate (SDY1260
#: antibody detection by CBA under our CBA pick), 0 were reachable by lexical (BM25) retrieval,
#: and 3 were neither (two CBA panels the picker had other terms for, one blood count). Three is
#: where that sat; uncapped, the expansion added ~2.6 terms per entry. The cap keeps `analyte
#: assay` (79 index children) and `cytometry assay` (45) from burying the list when they rank --
#: parents are always added, there are few.
NEIGHBOUR_TOP = 3
MAX_NEIGHBOUR_CHILDREN = 8
#: Entries mapped at once by enrich_assays_with_obi. Each entry is 2-3 blocking network calls
#: and none depends on another, so a 15-assay paper mapped one entry at a time spent most of
#: round 4 waiting. Four, like the verifier's bound on concurrent calls in spirit: enough to
#: overlap the latency, few enough not to trip the API's rate limit alongside nothing else.
OBI_WORKERS = 4
#: Levels the descent walks before it stops where it is. The index's deepest term sits at
#: depth 5 (bulk / single-cell RNA-seq at 4), so six is never reached on a straight walk; it
#: is a guard against a reply that keeps naming a child with children, not a tuning knob.
MAX_DESCENT_LEVELS = 6
#: The OBI assay branch root. Not in the index (scripts/prune_obi_domain.py starts below it),
#: so the walk's first level is the index's parentless terms (_index_roots), and the record
#: for that level names this id as the node.
OBI_ASSAY_ROOT = "OBI:0000070"
#: The values settings.OBI_MAPPING_STRATEGY takes; anything else is refused at map time.
#: "hybrid" is the embedding pick followed, when the picked term has children in the index, by
#: one descent from it (_descend_from_pick): the walk only ever goes down from a term retrieval
#: already chose, so it cannot take the wrong top-level branch, which is where the root walk
#: lost on the three-paper comparison (docs/obi_descent_vs_embedding_3papers.md).
OBI_STRATEGIES = ("embedding", "descend", "hybrid")


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


#: Compositional labels kept anyway, because the family has no generic term left to map to.
#: OBI:1110179 is what OBI itself names as the replacement for the obsolete OBI:0000667 "MHC
#: multimer staining assay"; without it a tetramer stain could only map to its platform
#: (OBI:0000916 flow cytometry), where the round-5 merge folds it into the paper's other flow
#: panels. scripts/prune_obi_domain.py reads this set, so the index and the load-time filter
#: below agree.
_COMPOSITIONAL_KEEP = frozenset({
    "OBI:1110179",  # MHC tetramer/multimer assay measuring binding of a T cell epitope:MHC:TCR complex
})


def _is_generic_assay_term(obi_id: str, label: str) -> bool:
    """`_is_generic_assay_label`, except for the ids pinned in `_COMPOSITIONAL_KEEP`."""
    return obi_id in _COMPOSITIONAL_KEEP or _is_generic_assay_label(label)


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
    """Every label and synonym key in the vocabulary, each pointing at one term.

    Labels are indexed before any synonym, so when a key is both one term's label and another
    term's synonym the label wins ("histopathology" is OBI:0002564's label and OBI:0600020's
    synonym). Within a tier, index order decides, as before: the index is in obo order, and
    `test_lookup_collisions_are_the_known_four` pins the keys this matters for.
    """
    terms = [
        t for t in json.loads(terms_path.read_text(encoding="utf-8"))
        if t.get("id") and t.get("label") and _is_generic_assay_term(t["id"], t["label"])
    ]
    lookup: dict[str, dict[str, str]] = {}
    for term in terms:
        entry = {"obi_id": term["id"], "obi_label": term["label"]}
        for key in _index_keys(term["label"]):
            lookup.setdefault(key, entry)
    for term in terms:
        entry = {"obi_id": term["id"], "obi_label": term["label"]}
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
        t["id"]
        for t in terms
        if t.get("id") and _is_generic_assay_term(t["id"], t.get("label", ""))
    )


_OBO_TERM_ID = re.compile(r"^id: (\S+)", re.MULTILINE)
_OBO_IS_A = re.compile(r"^is_a: (\S+)", re.MULTILINE)


@lru_cache(maxsize=8)
def _index_children(terms_path: Path = _OBI_TERMS_PATH) -> dict[str, tuple[str, ...]]:
    """Direct `is_a` children per term, both ends inside the index's generic vocabulary.

    Read from each entry's `parents` (its direct is_a parents as {"id", "label"}, written by
    scripts/prune_obi_domain.py from the full ontology; a bare id is accepted too) and
    inverted; a parent outside the
    vocabulary is dropped, so a pruned index never points at a term it does not hold. A terms
    file without `parents` falls back to parsing obi.obo as before, and an absent obi.obo then
    gives {}, which leaves every exact hit answering outright.

    Direct only: walking further is _pinned_candidates' decision, and it does so for the RNA
    sequencing family alone (_TWO_TIER_PIN_IDS).
    """
    allowed = _term_ids(terms_path)
    children: dict[str, list[str]] = {}
    entries = _index_entries(terms_path)
    if entries and all("parents" in t for t in entries.values()):
        for obi_id, term in entries.items():
            if obi_id not in allowed:
                continue
            for parent in term.get("parents") or []:
                parent_id = parent.get("id") if isinstance(parent, dict) else parent
                if parent_id in allowed:
                    children.setdefault(parent_id, []).append(obi_id)
        return {parent: tuple(kids) for parent, kids in children.items()}
    if not _OBO_PATH.exists():
        return {}
    for block in _OBO_PATH.read_text(encoding="utf-8").split("\n\n"):
        if not block.startswith("[Term]"):
            continue
        match = _OBO_TERM_ID.search(block)
        if not match or match.group(1) not in allowed:
            continue
        for parent in _OBO_IS_A.findall(block):
            if parent in allowed:
                children.setdefault(parent, []).append(match.group(1))
    return {parent: tuple(kids) for parent, kids in children.items()}


@lru_cache(maxsize=8)
def _index_parents(terms_path: Path = _OBI_TERMS_PATH) -> dict[str, tuple[str, ...]]:
    """Direct `is_a` parents per term: the inverse of _index_children, from the same parse."""
    parents: dict[str, list[str]] = {}
    for parent, kids in _index_children(terms_path).items():
        for kid in kids:
            parents.setdefault(kid, []).append(parent)
    return {kid: tuple(ps) for kid, ps in parents.items()}


@lru_cache(maxsize=8)
def _index_roots(terms_path: Path = _OBI_TERMS_PATH) -> tuple[str, ...]:
    """The generic terms with no parent inside the index, in index (obo) order.

    These are the descent's first level: the assay root itself is not in the index, and a
    term whose only parents were pruned (an out-of-scope domain term, a compositional one)
    has nothing above it here either, so it is reachable only from the top. 96 in the live
    index, 47 of them leaves.
    """
    allowed = _term_ids(terms_path)
    parents = _index_parents(terms_path)
    return tuple(obi_id for obi_id in _index_entries(terms_path)
                 if obi_id in allowed and not parents.get(obi_id))


@lru_cache(maxsize=8)
def _index_entries(terms_path: Path) -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in json.loads(terms_path.read_text(encoding="utf-8")) if t.get("id")}


#: Exact hits whose grandchildren are pinned too. "RNA sequencing assay" is what a paper's
#: "RNA Sequencing" hits, and bulk / single-cell RNA-seq sit two levels below it, under
#: "RNA-seq assay". Only this family: on a broad term the second tier runs to 92 terms
#: ("analyte assay") and buries the retrieved candidates.
_TWO_TIER_PIN_IDS = frozenset({"OBI:0001177", "OBI:0001271"})  # RNA sequencing / RNA-seq assay


def _pinned_candidates(hit_id: str, terms_path: Path = _OBI_TERMS_PATH) -> list[dict[str, Any]]:
    """The exact hit and its direct children, as candidates the picker sees whatever they score
    -- plus its grandchildren when the hit is in _TWO_TIER_PIN_IDS.

    `similarity` is None: none of them was retrieved by similarity, and _candidate_line says
    why each is there instead. `text` is built like the embedded rows ("label | syn | ...").
    """
    entries = _index_entries(terms_path)
    details = _term_details(terms_path)
    children = _index_children(terms_path)
    order = [(hit_id, "exact"), *((c, "child") for c in children.get(hit_id, ()))]
    if hit_id in _TWO_TIER_PIN_IDS:
        order += [(g, "grandchild") for c in children.get(hit_id, ()) for g in children.get(c, ())]
    pinned, seen = [], set()
    for obi_id, pin in order:
        if obi_id in seen:
            continue
        seen.add(obi_id)
        term = entries.get(obi_id)
        if not term:
            continue
        pinned.append({
            **details.get(obi_id, {}),
            "id": obi_id,
            "label": term["label"],
            "text": " | ".join([term["label"], *(str(s) for s in term.get("synonyms") or [])]),
            "similarity": None,
            "pin": pin,
        })
    return pinned


def _with_pinned(
    candidates: list[dict[str, Any]], pinned: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Pinned terms first, then the retrieved ones; a pinned term that was also retrieved keeps
    its similarity. The list may run past TOP_K by the pinned count -- the pins are the point."""
    retrieved = {c["id"]: c for c in candidates}
    head = [{**p, "similarity": retrieved[p["id"]]["similarity"]} if p["id"] in retrieved else p
            for p in pinned]
    pinned_ids = {p["id"] for p in pinned}
    return head + [c for c in candidates if c["id"] not in pinned_ids]


#: The `pin` values _with_neighbours writes; _candidate_line names the anchor for each.
_NEIGHBOUR_PINS = ("child_of", "parent_of")


def _with_neighbours(
    candidates: list[dict[str, Any]], terms_path: Path = _OBI_TERMS_PATH
) -> list[dict[str, Any]]:
    """The list plus the direct OBI parents and children of its first NEIGHBOUR_TOP retrieved
    entries, appended after it.

    Retrieval ranks the term a paper's wording resembles, which is often the parent of the
    term the record warrants or a sibling of it, and the picker can only choose among what it is
    shown: of the four curated terms the 31-paper run never retrieved, the one a structural
    change could reach was one `is_a` edge below the top candidate (see NEIGHBOUR_TOP). So the
    neighbours join the list the way an exact hit's children do
    (_pinned_candidates) -- regardless of similarity, marked with the candidate they belong to,
    and the choice between parent and child is left to the picker under its rule 2.

    Anchors are the first NEIGHBOUR_TOP entries that retrieval found (no `pin`): a pinned exact
    hit already brings its own children. Called after _with_pinned so `of` is the 1-based number
    the picker sees. A term with more than MAX_NEIGHBOUR_CHILDREN children in the index
    contributes none of them; its parents still join. Nothing already listed is repeated.
    """
    present = {c["id"] for c in candidates}
    entries = _index_entries(terms_path)
    details = _term_details(terms_path)
    children = _index_children(terms_path)
    parents = _index_parents(terms_path)
    added: list[dict[str, Any]] = []
    anchors = [(i, c) for i, c in enumerate(candidates, 1) if not c.get("pin")][:NEIGHBOUR_TOP]
    for position, anchor in anchors:
        order = [(p, "parent_of") for p in parents.get(anchor["id"], ())]
        kids = children.get(anchor["id"], ())
        if len(kids) <= MAX_NEIGHBOUR_CHILDREN:
            order += [(k, "child_of") for k in kids]
        for obi_id, pin in order:
            term = entries.get(obi_id)
            if obi_id in present or not term:
                continue
            present.add(obi_id)
            added.append({
                **details.get(obi_id, {}),
                "id": obi_id,
                "label": term["label"],
                "text": " | ".join([term["label"], *(str(s) for s in term.get("synonyms") or [])]),
                "similarity": None,
                "pin": pin,
                "of": position,
            })
    return list(candidates) + added


@lru_cache(maxsize=8)
def _term_details(terms_path: Path = _OBI_TERMS_PATH) -> dict[str, dict[str, Any]]:
    """Definition and descendant count per id, from the vocabulary being searched.

    The embeddings file carries the definition only inside `embed_input`, joined to the label
    and synonyms; the index keeps it as its own field, alongside `n_descendants`. The picker is
    told to judge by definition and break ties on fewer descendants, so both have to reach it.
    Keyed on `terms_path` like `_index_entries` and `_index_children`: it used to read the
    default index whatever vocabulary the caller passed.
    """
    if not terms_path.exists():
        return {}
    return {
        t["id"]: {"definition": t.get("definition") or "", "n_descendants": t.get("n_descendants")}
        for t in json.loads(terms_path.read_text(encoding="utf-8")) if t.get("id")
    }


# ── Embedding helpers ─────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_embeddings() -> tuple[list[dict], np.ndarray]:
    """Load cached OBI embeddings. Returns (entries, matrix) where matrix shape is (N, 1536)."""
    entries = json.loads(_EMBEDDINGS_PATH.read_text(encoding="utf-8"))
    # Prune before the matrix is built so entries and matrix rows stay index-aligned
    entries = [
        e for e in entries if _is_generic_assay_term(e.get("id", ""), e.get("label", ""))
    ]
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
    query: str, k: int = TOP_K, allowed_ids: frozenset[str] | None = None,
    terms_path: Path = _OBI_TERMS_PATH,
) -> list[dict[str, Any]]:
    """Return the top-k OBI entries by cosine similarity to the query string.

    The vectors are exactly the index's terms (data/OBI/README.md), so `allowed_ids` is a
    no-op for the default vocabulary; it still restricts retrieval when a caller searches a
    different terms file (`run_obi_map.py --terms`), whose definitions and descendant counts
    then come from `terms_path`. There is no similarity threshold: the k best are returned
    however low they score, and abstention is the picker's alone.
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
    details = _term_details(terms_path)
    return [
        {
            **details.get(entries[i]["id"], {}),
            "id": entries[i]["id"],
            "label": entries[i]["label"],
            # "label | syn1 | syn2 | ...", per build_obi_embeddings.build_text — the embedded
            # string minus its definition. Carried so _llm_pick can show the model the wording
            # retrieval matched on, rather than the bare label.
            "text": entries[i].get("text") or entries[i]["label"],
            "similarity": round(float(scores[i]), 4),
        }
        for i in top_indices
    ]


#: How many of a candidate's synonyms to show. CHMO:0000089 carries nine; printing them all
#: for every candidate buries the labels the model is choosing between.
_MAX_SHOWN_SYNONYMS = 4
#: Characters of a definition to show. The longest in the index runs to ~1000; the median is
#: ~110, so this trims only the outliers that would dominate twenty candidate lines.
_MAX_DEFINITION_CHARS = 300


def _candidate_line(index: int, candidate: dict[str, Any]) -> str:
    """One numbered candidate, with the synonyms retrieval matched on.

    The `text` field is "label | syn1 | syn2 | ..."; the label is already the first part, so
    only the remainder is appended. Showing them closes a gap that made the model judge a term
    by a name no paper uses -- it saw "enzyme-linked immunosorbent assay" and never "ELISA",
    though the vector it was retrieved by encoded both.
    """
    shown = _candidate_text(candidate)
    marks = []
    if candidate.get("pin") == "exact":
        marks.append("exact name match")
    elif candidate.get("pin") == "child":
        marks.append("child of exact name match")
    elif candidate.get("pin") == "grandchild":
        marks.append("grandchild of exact name match")
    elif candidate.get("pin") == "child_of":
        marks.append(f"child of candidate {candidate.get('of')}")
    elif candidate.get("pin") == "parent_of":
        marks.append(f"parent of candidate {candidate.get('of')}")
    if candidate.get("similarity") is not None:
        marks.append(f"similarity: {candidate['similarity']}")
    return f"{index}. {candidate['id']} | {shown} ({'; '.join(marks)})"


def build_pick_prompt(
    assay_name: str,
    candidates: list[dict[str, Any]],
    sample_type: str = "",
    readouts: str = "",
    aliases: list[str] | None = None,
    standard_technique_name: str = "",
) -> str:
    """Render resolver_obi_assay.txt for one pick. Split out so a test can read it without
    reaching the network."""
    named = [a.strip() for a in (aliases or []) if isinstance(a, str) and a.strip()]
    return (
        (_PROMPTS_DIR / "resolver_obi_assay.txt").read_text(encoding="utf-8")
        .replace("{assay_name}", assay_name)
        .replace("{aliases}", ", ".join(named) if named else "none given")
        .replace("{standard_technique_name}", standard_technique_name.strip() or "not given")
        .replace("{candidates}",
                 "\n".join(_candidate_line(i + 1, c) for i, c in enumerate(candidates)))
        .replace("{sample_type}", sample_type.strip() or "not specified")
        .replace("{readouts}", readouts.strip() or "not specified")
    )


#: The whole reply the pick prompt asks for: a candidate number, optionally "#3" or "3.",
#: optionally followed by its granularity -- nothing else. The old `re.search(r"\d+")` read
#: "OBI:0000661" as candidate 0000661 and "3 or 5" as a confident 3. The granularity is
#: optional so a bare number, the reply the prompt asked for before it existed, still parses.
#: Punctuation around the granularity ("3, EXACT", "3 (EXACT)", "3 EXACT.") is tolerated: it
#: changes nothing about which candidate was named, and a reply refused for it used to be
#: taken as "none".
_PICK_REPLY = re.compile(r"#?\s*(\d+)\s*[.):,-]?\s*(?:\(?\s*(exact|broad)\s*\)?)?\s*\.?")
_ABSTENTIONS = ("none", "none.")


class PickReplyError(ValueError):
    """The picker's reply named neither a listed candidate nor "none".

    Raised rather than read as "none": an abstention is the model's judgement that no term
    fits, and is reported UNMAPPED as a vocabulary gap; a reply nobody could parse is a failed
    call, and is reported like one (`resource: error`, `obi_error`), so a re-run is known to
    be worth paying for. The two used to be indistinguishable in the output.
    """


def _normalize_reply(reply: str) -> str:
    return reply.strip().strip("*`'\"").strip().lower()


def is_abstention(reply: str) -> bool:
    """Whether the reply is the prompt's "none"."""
    return _normalize_reply(reply) in _ABSTENTIONS


def parse_pick_reply(reply: str, n_candidates: int) -> tuple[int | None, str | None]:
    """(0-based candidate index, "EXACT"/"BROAD" or None), or (None, None) for "none" or
    anything ambiguous -- `is_abstention` tells the two apart."""
    reply = _normalize_reply(reply)
    match = _PICK_REPLY.fullmatch(reply)
    if not match:
        if reply not in _ABSTENTIONS:
            logger.warning("OBI pick reply not understood: %r", reply[:80])
        return None, None
    idx = int(match.group(1)) - 1
    if not 0 <= idx < n_candidates:
        return None, None
    return idx, match.group(2).upper() if match.group(2) else None


def parse_pick(reply: str, n_candidates: int) -> int | None:
    """The 0-based candidate index the reply names, or None for "none" or anything ambiguous."""
    return parse_pick_reply(reply, n_candidates)[0]


def _llm_pick(
    assay_name: str,
    candidates: list[dict[str, Any]],
    sample_type: str = "",
    readouts: str = "",
    model: str = settings.OPENAI_MODEL,
    aliases: list[str] | None = None,
    standard_technique_name: str = "",
    registry_key: str = "",
) -> dict[str, Any] | None:
    """Ask the LLM to pick the best OBI candidate, or say none.

    `registry_key` only labels the run's trace record (assay_trace) the way assays_OBI.json is
    keyed; the model is shown `assay_name`.

    Runs on the configured model like every other call in the pipeline. It used to be pinned
    to a cheap one on the reasoning that the labels are already retrieved and the answer is a
    single integer -- but this pick *is* the mapping. Retrieval only narrows to TOP_K; which of
    them is right, and whether none of them is, is the whole judgement, and it is the step
    that produced this corpus's wrong answers (phosphoflow analysis onto an imaging-based
    term, whole-transcriptome profiling onto a targeted one). The prompt also asks for
    restraint -- prefer the specific match "only when the specificity is warranted", answer
    "none" when the name is too vague -- and abstention is the system's only defence, since
    _top_k_candidates applies no similarity threshold.

    Seeded like the extraction call (EXTRACTION_SEED): on the 31-paper re-run this pick was
    the largest source of change between two runs of the same paper (9 of 31 papers moved on
    the OBI term with no extraction change), and a seed is the one lever on that which costs
    nothing. Best-effort on the provider's side, so it narrows the variance rather than ends it.

    Returns None only for an abstention. A reply that names no listed candidate raises
    PickReplyError, which enrich_assays_with_obi records as a failed lookup.
    """
    prompt = build_pick_prompt(assay_name, candidates, sample_type, readouts, aliases,
                               standard_technique_name)

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        seed=EXTRACTION_SEED,
    )
    reply = (resp.choices[0].message.content or "").strip().lower()
    # The numbered lines are retrieval's output and are gone once the pick is parsed; with the
    # reply beside them a wrong term can be read as a retrieval miss or a picker miss.
    assay_trace.record("obi", registry_key or assay_name, reply=reply,
                       candidates=[_candidate_line(i + 1, c) for i, c in enumerate(candidates)])
    idx, granularity = parse_pick_reply(reply, len(candidates))
    if idx is None:
        if is_abstention(reply):
            return None
        raise PickReplyError(f"pick reply not understood: {reply[:80]!r}")
    chosen = candidates[idx]
    return {
        "obi_id": chosen["id"],
        "obi_label": chosen["label"],
        "resource": "embedding_llm",
        "confidence": chosen["similarity"],
        # Diagnostic only. Nothing downstream reads it: round 5 folds on the label whatever
        # the granularity (assay_merger), and the deliverable does not carry it. It is kept
        # because the adjudication of a disputed term starts from whether the picker itself
        # called the term broad.
        "granularity": granularity,
    }


def _paper_query(name: str, aliases: list[str] | None) -> str:
    """The paper-wording retrieval query: its name and every alias, "name | alias | ...".

    Aliases are the paper's other names for the assay and often name the technique more
    directly than a section-heading name does; adding them took benchmark recall@10 from 70% to
    73%. Sample type and readouts are left out on purpose -- each made retrieval slightly worse
    in the same measurement -- and stay in the pick prompt as disambiguating context.
    """
    seen: set[str] = set()
    parts: list[str] = []
    for part in [name, *(aliases or [])]:
        part = part.strip() if isinstance(part, str) else ""
        if part and part.lower() not in seen:
            seen.add(part.lower())
            parts.append(part)
    return " | ".join(parts)


def _merge_candidates(
    primary: list[dict[str, Any]],
    *others: list[dict[str, Any]],
    k: int = TOP_K,
    primary_slots: int = PRIMARY_SLOTS,
) -> list[dict[str, Any]]:
    """Union the retrieval pools into one top-k list, the paper-wording pool's best kept first.

    Neither query dominates, which is the whole reason to merge rather than choose. Measured
    over 150 benchmark rows, the technique alone puts the curator's term in its top 10
    79% of the time and the paper wording (name + aliases) 73%, and they miss different rows:
    "hemagglutination inhibition (HAI) assays" scores 0.809 against OBI's `viral
    hemagglutination inhibition assay` and its normalized form only 0.658, while a section
    heading like "Surface and intracellular cytokine staining" ranks `flow cytometry assay`
    44th and its technique "flow cytometry" ranks it first. The merge reaches 87% at 10.

    The first `primary_slots` of `primary` are always kept; the other pools then fill to `k` in
    rank order, and anything left over comes from the rest of `primary`. A plain merge by score
    let the technique query's broad, high-scoring terms push out the paper wording's specific
    ones -- the parent-for-child failure in a milder form.

    A term retrieved by more than one query is kept once, at its higher similarity -- the score
    is the strength of the best evidence for it, not an average over how it was found. The
    result is ordered by that similarity, which is the order the picker sees.
    """
    chosen: dict[str, dict[str, Any]] = {}

    def take(candidate: dict[str, Any]) -> None:
        previous = chosen.get(candidate["id"])
        if previous is None or candidate.get("similarity", 0) > previous.get("similarity", 0):
            chosen[candidate["id"]] = candidate

    primary = primary or []
    for candidate in primary[:primary_slots]:
        take(candidate)
    for candidate in [c for pool in others for c in pool or []] + primary[primary_slots:]:
        if candidate["id"] in chosen:
            take(candidate)
        elif len(chosen) < k:
            take(candidate)
    ranked = sorted(chosen.values(), key=lambda c: c.get("similarity", 0), reverse=True)
    return ranked[:k]


def _embedding_llm_match(
    query: str,
    allowed_ids: frozenset[str] | None = None,
    sample_type: str = "",
    readouts: str = "",
    display_name: str = "",
    model: str = settings.OPENAI_MODEL,
    aliases: list[str] | None = None,
    standard_technique_query: str = "",
    pinned: list[dict[str, Any]] | None = None,
    registry_key: str = "",
    terms_path: Path = _OBI_TERMS_PATH,
) -> dict[str, Any] | None:
    """Retrieve on `query` and `standard_technique_query`, but show the LLM `display_name`.

    Retrieval and display do different jobs. The technique is often the better
    *retrieval* query — it is the conventional technique wording, so it pulls the right
    neighbourhood of OBI terms. But it is the worse thing to show the model *as the name*, so it
    reaches the picker on its own "Technique" line, as evidence, because
    normalizing can drop the very detail that picks between a parent term and its child:
    "ImmunoChip array" normalized to "Genome-wide SNP genotyping" loses the word "array", and
    with it the evidence for `genotyping by SNP array assay` over plain `genotyping assay`.

    Both are retrieved on -- the paper's name joined with its aliases (_paper_query), and the
    technique -- and their pools merged; see _merge_candidates for why neither can be
    dropped and why the paper-wording pool gets reserved slots. The paper's name goes first so
    the normalized pool, which is the one a caller supplies deliberately, is the last thing
    retrieved.

    `pinned` is step 1's exact hit and its direct children (_pinned_candidates). They lead the
    list whatever they score, and the result is attributed "exact_original_llm". The exact hit
    is also the floor: if the picker answers "none", or its reply cannot be read, or there are
    no embeddings to retrieve with, the verbatim match stands rather than being lost. Without
    an exact hit an unreadable reply propagates (PickReplyError): there is no answer to fall
    back on, and "unresolved" would misreport a failed call as a vocabulary gap.
    """
    exact_hit = next((p for p in pinned or [] if p.get("pin") == "exact"), None)
    fallback = ({"obi_id": exact_hit["id"], "obi_label": exact_hit["label"],
                 "resource": "exact_original", "confidence": "high"} if exact_hit else None)
    if not _EMBEDDINGS_PATH.exists():
        return fallback
    raw_pool = _top_k_candidates(_paper_query(query, aliases), allowed_ids=allowed_ids,
                                 terms_path=terms_path)
    pools = [raw_pool]
    normalized = standard_technique_query.strip()
    if normalized and normalized.lower() != query.strip().lower():
        pools.append(_top_k_candidates(normalized, allowed_ids=allowed_ids,
                                       terms_path=terms_path))
    candidates = _merge_candidates(*pools)
    if pinned:
        candidates = _with_pinned(candidates, pinned)
    if not candidates:
        return None
    candidates = _with_neighbours(candidates, terms_path)
    try:
        picked = _llm_pick(
            display_name or query, candidates,
            sample_type=sample_type, readouts=readouts, model=model, aliases=aliases,
            standard_technique_name=normalized
            if normalized.lower() != (display_name or query).strip().lower() else "",
            registry_key=registry_key,
        )
    except PickReplyError as exc:
        if not exact_hit:
            raise
        logger.warning("%s: %s; the exact name match stands", registry_key or query, exc)
        return {**fallback, "resource": "exact_original_llm"}
    if exact_hit:
        if not picked:
            return {**fallback, "resource": "exact_original_llm"}
        chosen = next(c for c in candidates if c["id"] == picked["obi_id"])
        if chosen.get("pin") == "exact" or chosen.get("similarity") is None:
            picked["confidence"] = "high"
        picked["resource"] = "exact_original_llm"
        return picked
    # Attribute the win to whatever alone could reach the chosen term: the neighbour expansion
    # (the term was retrieved by neither query), else the technique query. Without this, a
    # benchmark run cannot tell whether either earned its keep in step 2 or merely rode along --
    # and the two justify very different things.
    if picked:
        chosen = next(c for c in candidates if c["id"] == picked["obi_id"])
        if chosen.get("pin") in _NEIGHBOUR_PINS:
            picked["resource"] = "embedding_llm_neighbour"
        elif len(pools) > 1 and picked["obi_id"] not in {c["id"] for c in raw_pool}:
            picked["resource"] = "embedding_llm_normalized"
    return picked


# ── Tree descent ──────────────────────────────────────────────────────────────

def _descend_candidates(ids: tuple[str, ...] | list[str],
                        terms_path: Path = _OBI_TERMS_PATH) -> list[dict[str, Any]]:
    """The candidate dicts for one level: the given terms, in the order given, shaped like a
    retrieved candidate (id, label, text, definition, n_descendants) plus `n_children`, the
    number of index terms directly under each -- what tells the picker whether stepping into
    a child ends the walk or shows another level. An id the index does not hold is skipped."""
    entries = _index_entries(terms_path)
    details = _term_details(terms_path)
    children = _index_children(terms_path)
    out = []
    for obi_id in ids:
        term = entries.get(obi_id)
        if not term:
            continue
        out.append({
            **details.get(obi_id, {}),
            "id": obi_id,
            "label": term["label"],
            "text": " | ".join([term["label"], *(str(s) for s in term.get("synonyms") or [])]),
            "similarity": None,
            "n_children": len(children.get(obi_id, ())),
        })
    return out


def _candidate_text(candidate: dict[str, Any]) -> str:
    """`label | syn1 | ... | definition: ... | descendants: n`, the part of a candidate line
    that describes the term -- shared by the pick and descent prompts."""
    label = candidate["label"]
    parts = [p.strip() for p in str(candidate.get("text") or label).split("|")]
    synonyms = [p for p in parts[1:] if p and p.lower() != label.lower()][:_MAX_SHOWN_SYNONYMS]
    shown = f"{label} | {' | '.join(synonyms)}" if synonyms else label
    definition = " ".join(str(candidate.get("definition") or "").split())
    if definition:
        if len(definition) > _MAX_DEFINITION_CHARS:
            definition = definition[:_MAX_DEFINITION_CHARS].rstrip() + "..."
        shown += f" | definition: {definition}"
    if candidate.get("n_descendants") is not None:
        shown += f" | descendants: {candidate['n_descendants']}"
    return shown


def _descend_candidate_line(index: int, candidate: dict[str, Any]) -> str:
    """One numbered child for the descent prompt: the term as _candidate_line shows it, with
    no similarity or pin (neither exists here) and the child's own child count appended."""
    return (f"{index}. {candidate['id']} | {_candidate_text(candidate)}"
            f" | children in vocabulary: {candidate.get('n_children', 0)}")


def _current_term_line(current: dict[str, Any] | None) -> str:
    if current is None:
        return (f"{OBI_ASSAY_ROOT} | assay (the root of the OBI assay branch; not itself a "
                "mappable term -- choose a child or answer none)")
    return f"{current['id']} | {_candidate_text(current)}"


def build_descend_prompt(
    assay_name: str,
    current: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    sample_type: str = "",
    readouts: str = "",
    aliases: list[str] | None = None,
    standard_technique_name: str = "",
) -> str:
    """Render resolver_obi_descend.txt for one level of the walk. `current` is None at the
    root. Split out so a test can read it without reaching the network."""
    named = [a.strip() for a in (aliases or []) if isinstance(a, str) and a.strip()]
    return (
        (_PROMPTS_DIR / "resolver_obi_descend.txt").read_text(encoding="utf-8")
        .replace("{assay_name}", assay_name)
        .replace("{aliases}", ", ".join(named) if named else "none given")
        .replace("{standard_technique_name}", standard_technique_name.strip() or "not given")
        .replace("{current_term}", _current_term_line(current))
        .replace("{candidates}",
                 "\n".join(_descend_candidate_line(i + 1, c) for i, c in enumerate(candidates)))
        .replace("{sample_type}", sample_type.strip() or "not specified")
        .replace("{readouts}", readouts.strip() or "not specified")
    )


#: The whole reply one level of the descent asks for: a child number with an optional
#: granularity (bare = step in, with granularity = end on it), "stop" with a granularity, or
#: "none". The same punctuation tolerance as _PICK_REPLY.
_DESCEND_REPLY = re.compile(
    r"(?:#?\s*(?P<idx>\d+)|(?P<stop>stop))\s*[.):,-]?\s*"
    r"(?:\(?\s*(?P<gran>exact|broad)\s*\)?)?\s*\.?"
)


def parse_descend_reply(reply: str, n_candidates: int) -> tuple[str, int | None, str | None]:
    """(action, 0-based child index or None, "EXACT"/"BROAD"/None).

    action is "pick" (a child was named; the walk ends on it when a granularity came with the
    number, continues below it otherwise), "stop" (the current term) or "none". A reply that is
    none of these, or names a child that is not listed, raises PickReplyError: as with the
    embedding picker, an unreadable reply is a failed call and is reported like one rather than
    read as an abstention.
    """
    reply = _normalize_reply(reply)
    if reply in _ABSTENTIONS:
        return "none", None, None
    match = _DESCEND_REPLY.fullmatch(reply)
    if not match:
        raise PickReplyError(f"descend reply not understood: {reply[:80]!r}")
    granularity = match.group("gran").upper() if match.group("gran") else None
    if match.group("stop"):
        return "stop", None, granularity
    idx = int(match.group("idx")) - 1
    if not 0 <= idx < n_candidates:
        raise PickReplyError(f"descend reply names child {idx + 1} of {n_candidates}")
    return "pick", idx, granularity


def _llm_descend_pick(
    assay_name: str,
    current: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    sample_type: str = "",
    readouts: str = "",
    model: str = settings.OPENAI_MODEL,
    aliases: list[str] | None = None,
    standard_technique_name: str = "",
) -> str:
    """One level of the walk: ask the model, return its reply lowercased and stripped. Seeded
    and at temperature 0 like _llm_pick, for the same reason. Recording is left to _descend,
    which keeps every level of one assay in a single trace record."""
    prompt = build_descend_prompt(assay_name, current, candidates, sample_type, readouts,
                                  aliases, standard_technique_name)
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        seed=EXTRACTION_SEED,
    )
    return (resp.choices[0].message.content or "").strip().lower()


def _descend(
    start_id: str | None,
    assay_name: str,
    sample_type: str = "",
    readouts: str = "",
    model: str = settings.OPENAI_MODEL,
    aliases: list[str] | None = None,
    standard_technique_name: str = "",
    registry_key: str = "",
    terms_path: Path = _OBI_TERMS_PATH,
    trace_round: str = "obi",
) -> dict[str, Any] | None:
    """Walk the OBI assay tree from `start_id` (None: the root) down to the term the record
    warrants, one chat call per level.

    `trace_round` names the trace round the walk is recorded under: "obi" when the walk *is*
    round 4, "obi_descend" when it follows an embedding pick that already holds the "obi" slot
    for this key (a second record under one key would overwrite the first).

    At each level the picker sees the current term and its direct children in the index
    (_index_children; at the root, _index_roots) and answers one of: a child's number (step
    into it), a number with EXACT/BROAD (end on that child), STOP EXACT/BROAD (end on the
    current term) or none. The walk also ends on its own when the chosen child has no children
    in the index, and when it has run MAX_DESCENT_LEVELS levels.

    Two replies are read against the grammar on purpose. "none" below the root contradicts
    the previous level, which stepped into the current term because it covered the assay; it
    ends the walk on the current term as BROAD and is marked `backoff`, so a run that did this
    often can be found. A STOP at the root is an abstention: there is no term to stop on.

    Returns None only for an abstention at the root. A reply nobody could parse raises
    PickReplyError out of whatever level it happened at; the caller decides whether an exact
    hit stands in for the answer. The result carries `path` (every term the walk entered,
    `start_id` first), `calls` and `backoff` beside the usual fields; `confidence` is None
    because the walk measures nothing -- the caller sets "high" when it started at an exact hit.
    The whole walk is one trace record under `registry_key`, with the candidate lines and reply
    of every level, so a wrong term is diagnosed from disk by reading which turn went wrong.
    """
    entries = _index_entries(terms_path)
    children = _index_children(terms_path)
    current_id = start_id
    path: list[str] = [start_id] if start_id else []
    levels: list[dict[str, Any]] = []
    chosen_id: str | None = None
    granularity: str | None = None
    backoff = False

    def finish(obi_id: str | None, gran: str | None) -> None:
        nonlocal chosen_id, granularity
        chosen_id, granularity = obi_id, gran

    def record() -> None:
        assay_trace.record(trace_round, registry_key or assay_name, strategy="descend",
                           path=list(path), levels=levels,
                           reply=levels[-1]["reply"] if levels else None)

    for _level in range(MAX_DESCENT_LEVELS):
        child_ids = children.get(current_id, ()) if current_id else _index_roots(terms_path)
        candidates = _descend_candidates(child_ids, terms_path)
        if not candidates:
            # A leaf (or a root with nothing under it): the previous level's answer stands.
            finish(current_id, granularity)
            break
        current = _descend_candidates([current_id], terms_path)[0] if current_id else None
        reply = _llm_descend_pick(assay_name, current, candidates, sample_type, readouts,
                                  model, aliases, standard_technique_name)
        levels.append({"node": current_id or OBI_ASSAY_ROOT, "reply": reply,
                       "candidates": [_descend_candidate_line(i + 1, c)
                                      for i, c in enumerate(candidates)]})
        try:
            action, idx, gran = parse_descend_reply(reply, len(candidates))
        except PickReplyError:
            record()
            raise
        if action == "none":
            if current_id is None:
                finish(None, None)
            else:
                backoff = True
                finish(current_id, "BROAD")
            break
        if action == "stop":
            if current_id is None:
                # Nothing to stop on at the root: read as the abstention it amounts to.
                finish(None, None)
            else:
                finish(current_id, gran)
            break
        chosen = candidates[idx]
        path.append(chosen["id"])
        current_id = chosen["id"]
        granularity = gran
        if gran is not None or not children.get(current_id):
            finish(current_id, gran)
            break
    else:
        # MAX_DESCENT_LEVELS replies, every one of them a step into a term with children.
        backoff = True
        finish(current_id, "BROAD")
    record()
    if chosen_id is None:
        return None
    return {
        "obi_id": chosen_id,
        "obi_label": entries[chosen_id]["label"],
        "resource": "descend_llm",
        "confidence": None,
        "granularity": granularity,
        "path": path,
        "calls": len(levels),
        "backoff": backoff,
    }


def _descend_from_pick(
    picked: dict[str, Any],
    assay_name: str,
    sample_type: str = "",
    readouts: str = "",
    model: str = settings.OPENAI_MODEL,
    aliases: list[str] | None = None,
    standard_technique_name: str = "",
    registry_key: str = "",
    terms_path: Path = _OBI_TERMS_PATH,
    prior_calls: int = 0,
) -> dict[str, Any]:
    """The hybrid strategy's second step: from a term already picked, walk down only.

    Nothing is spent when the picked term has no children in the index -- the pick is returned
    as it came, plus the bookkeeping fields (`path` = [its id], `calls` = `prior_calls`). Otherwise
    _descend starts at the pick, recorded under the "obi_descend" trace round so the pick's own
    record survives. A walk that ends where it started keeps the pick's resource and takes the
    walk's granularity (STOP EXACT/BROAD is the more informed call); one that moves to a
    descendant is attributed "embedding_llm_descended". A walk whose reply could not be read
    leaves the pick standing: the pick was paid for and is an answer. `prior_calls` is what the
    pick cost, so `calls` is the entry's whole bill.
    """
    start = picked["obi_id"]
    if not _index_children(terms_path).get(start):
        return {**picked, "path": [start], "calls": prior_calls, "backoff": False}
    try:
        walked = _descend(
            start, assay_name, sample_type=sample_type, readouts=readouts, model=model,
            aliases=aliases, standard_technique_name=standard_technique_name,
            registry_key=registry_key, terms_path=terms_path, trace_round="obi_descend",
        )
    except PickReplyError as exc:
        logger.warning("%s: %s; the embedding pick stands", registry_key or assay_name, exc)
        return {**picked, "path": [start], "calls": prior_calls + 1, "backoff": False,
                "descend_error": f"{type(exc).__name__}: {exc}"}
    # _descend returns None only for an abstention at the root, and this walk has a start.
    assert walked is not None
    walked["calls"] += prior_calls
    if walked["obi_id"] == start:
        return {**picked, "granularity": walked["granularity"] or picked.get("granularity"),
                "path": walked["path"], "calls": walked["calls"], "backoff": walked["backoff"]}
    walked["resource"] = "embedding_llm_descended"
    walked["confidence"] = picked.get("confidence")
    return walked


# ── Public API ────────────────────────────────────────────────────────────────

def map_assay_to_obi(
    name_in_paper: str,
    standard_technique_name: str = "",
    terms_path: Path = _OBI_TERMS_PATH,
    sample_type: str = "",
    readouts: str = "",
    model: str = settings.OPENAI_MODEL,
    aliases: list[str] | None = None,
    registry_key: str = "",
    strategy: str | None = None,
) -> dict[str, Any] | None:
    """Return OBI metadata for an assay, or None when no candidate fits.

    `strategy` is step 2's method, "embedding", "descend" or "hybrid" (OBI_STRATEGIES); None
    reads settings.OBI_MAPPING_STRATEGY at call time. "hybrid" is the embedding pick and then,
    when the picked term has children in the index, one descent from it (_descend_from_pick). Under "descend" the walk starts at the exact
    hit when step 1 found one with children, and at the root otherwise; the hit is also the
    answer when the walk's first level abstains or its reply cannot be read, as the embedding
    path keeps it when the picker says none.

    terms_path selects the standard vocabulary used for exact-match lookup and
    restricts the embedding fallback's candidate pool to that vocabulary's ids
    (embeddings themselves are still drawn from the full precomputed OBI set).

    sample_type/readouts are only used by the embedding+LLM fallback (step 2), as
    disambiguating context for the LLM's pick among candidates — the exact match
    doesn't need them.

    `standard_technique_name` is used only in step 2: as a second retrieval query alongside the paper's
    name, and on its own line of the pick prompt, beside the paper's name rather than folded
    into it.
    It is deliberately **not** an exact-match key. It was one from 2026-09 to 2026-10-02, and
    that round accounted for 33 of the 52 rows disagreeing with the curator benchmark: the
    technique name is the parent ("RNA sequencing", "microarray", "real time polymerase chain
    reaction"), the curator's term is usually its child (single-cell RNA sequencing, transcription
    profiling by array, real time reverse-transcription PCR), and an exact hit returned before
    the picker -- which sees the paper's own wording and could choose the child -- was asked.

    An exact hit on the paper's own name answers outright only when the index holds no child of
    that term; otherwise it is pinned into step 2 with its direct children (see the module
    docstring).
    """
    lookup = _build_lookup(terms_path)

    # Step 1 — exact on the paper's own name
    result = lookup.get(name_in_paper.strip().lower())
    pinned = None
    if result:
        if not _index_children(terms_path).get(result["obi_id"]):
            return {**result, "resource": "exact_original", "confidence": "high"}
        pinned = _pinned_candidates(result["obi_id"], terms_path)
    normalized = standard_technique_name.strip()
    strategy = strategy or settings.OBI_MAPPING_STRATEGY
    if strategy not in OBI_STRATEGIES:
        raise ValueError(f"OBI_MAPPING_STRATEGY must be one of {OBI_STRATEGIES}, not {strategy!r}")

    original = name_in_paper.strip()
    query = original or normalized
    display_name = query

    if strategy == "descend":
        # Step 2 (descend) — walk the tree from the exact hit, or from the root
        exact = {**result, "resource": "exact_original_llm", "confidence": "high"} if result else None
        try:
            walked = _descend(
                result["obi_id"] if result else None, display_name,
                sample_type=sample_type, readouts=readouts, model=model, aliases=aliases,
                standard_technique_name=normalized
                if normalized.lower() != display_name.lower() else "",
                registry_key=registry_key, terms_path=terms_path,
            )
        except PickReplyError as exc:
            if not exact:
                raise
            logger.warning("%s: %s; the exact name match stands", registry_key or query, exc)
            return exact
        if exact:
            if not walked:
                return exact
            walked["resource"] = "exact_original_llm"
            walked["confidence"] = "high"
        return walked

    # Step 2 (embedding) — candidates from both queries (restricted to terms_path's
    # vocabulary), merged into one top-K list, LLM picks best
    allowed_ids = _term_ids(terms_path)
    picked = _embedding_llm_match(
        query,
        allowed_ids=allowed_ids,
        sample_type=sample_type,
        readouts=readouts,
        display_name=display_name,
        model=model,
        aliases=aliases,
        standard_technique_query=normalized,
        pinned=pinned,
        registry_key=registry_key,
        terms_path=terms_path,
    )
    if strategy != "hybrid" or not picked:
        return picked
    # Step 2b (hybrid) — from the pick, down only
    second_query = bool(normalized) and normalized.lower() != query.lower()
    return _descend_from_pick(
        picked, display_name, sample_type=sample_type, readouts=readouts, model=model,
        aliases=aliases,
        standard_technique_name=normalized if normalized.lower() != display_name.lower() else "",
        registry_key=registry_key, terms_path=terms_path,
        prior_calls=3 if second_query else 2,
    )


def enrich_assays_with_obi(
    assays: dict[str, Any],
    terms_path: Path = _OBI_TERMS_PATH,
    model: str = settings.OPENAI_MODEL,
    on_done: Callable[[str, int, int], None] | None = None,
    workers: int = OBI_WORKERS,
) -> dict[str, dict[str, Any]]:
    """Add OBI fields to a Phase-1 assay registry keyed by assay name.

    Entries are mapped `workers` at a time (OBI_WORKERS) and returned in registry order
    whatever order they finished in. Each worker runs in a copy of the caller's context, so
    the replies still land in the run's trace (assay_trace is a ContextVar, and a bare thread
    would not see it). `on_done(key, done, total)` fires as each entry finishes, from the
    calling thread, for a caller showing progress; an exception it raises is logged and does
    not cost the run.

    Fields written per entry: `obi_id`, `obi_label`, `resource`, `obi_confidence` and
    `obi_granularity`, plus `obi_path`, `obi_calls` and `obi_backoff` when the descent or
    hybrid strategy mapped it (the terms the walk entered, the calls the entry cost, and
    whether the walk ended by backing off onto the term it was on). The granularity is the picker's own EXACT/BROAD and is diagnostic only:
    nothing downstream reads it -- round 5 folds on the label whatever it says, and it is not in
    the deliverable -- but the adjudication of a disputed term starts from it.

    The OBI score is written as `obi_confidence`, never `confidence`: registries carry the
    *extraction* confidence under the latter (how clearly the paper identifies the technique),
    and overwriting it destroys that. scripts/build_assay_table.py, the corpus table it writes,
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

    `standard_technique_name` is read when the entry carries it and never written. Registries extracted
    before it joined assay_extractor.ENTRY_FIELDS do not have it, and neither do the ones
    assay_registry.registry_from_claims builds -- it lists the field among those a claims-derived
    registry structurally cannot supply. Both cases pass the empty string, which leaves step 2
    retrieving on `name_in_paper` alone: exactly the behaviour every
    existing registry had before this field existed. Nothing needs re-extracting to keep working;
    re-extraction is only how a registry starts benefiting.
    """
    def map_one(canonical: str) -> dict[str, Any]:
        value = assays[canonical]
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
        # The other wordings of a canonical entry retrieve beside its aliases: on a re-map of a
        # registry round 5 already folded, dropping them would query on one of the names the
        # fold kept and lose the others.
        aliases = names[1:] + [a for a in (raw_aliases if isinstance(raw_aliases, list) else [])
                               if isinstance(a, str)]
        standard_technique_name = str(entry.get("standard_technique_name") or "")
        try:
            mapped = map_assay_to_obi(
                original, standard_technique_name, terms_path=terms_path,
                sample_type=sample_type, readouts=readouts, model=model,
                aliases=aliases or None, registry_key=canonical,
            )
        except Exception as exc:  # noqa: BLE001 - one failed lookup must not cost the others
            # Per entry, because the round used to be all-or-nothing: one timed-out embedding
            # call threw away every mapping the paper had already paid for. A PickReplyError
            # lands here too: the call was made and paid for, and its reply could not be read.
            logger.warning("%s: OBI lookup failed - %s", canonical, exc)
            entry.update({"obi_id": None, "obi_label": None, "resource": "error",
                          "obi_confidence": None, "obi_granularity": None,
                          "obi_error": f"{type(exc).__name__}: {exc}"})
            return entry
        if mapped:
            entry["obi_id"] = mapped["obi_id"]
            entry["obi_label"] = mapped["obi_label"]
            entry["resource"] = mapped["resource"]
            entry["obi_confidence"] = mapped["confidence"]
            # The picker's own EXACT/BROAD; None for an exact name match (no pick was asked)
            # and for a reply that gave only a number.
            entry["obi_granularity"] = mapped.get("granularity")
            if "path" in mapped:
                # The descent's own record: the terms it entered and what it spent. Written
                # only by that strategy, so an embedding mapping keeps the shape it always had,
                # and assay_service.obi_calls bills from `obi_calls` when it is there.
                entry["obi_path"] = mapped["path"]
                entry["obi_calls"] = mapped["calls"]
                entry["obi_backoff"] = mapped["backoff"]
        else:
            entry["obi_id"] = None
            entry["obi_label"] = None
            entry["resource"] = "unresolved"
            # Unconditional, not setdefault: a stale extraction confidence sitting next to
            # resource="unresolved" reads as an OBI score.
            entry["obi_confidence"] = None
            entry["obi_granularity"] = None
        return entry

    keys = list(assays)
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        # One context copy per task: a Context can be entered by one thread at a time, and the
        # copy is what carries the active trace into the worker.
        futures = {pool.submit(contextvars.copy_context().run, map_one, key): key for key in keys}
        for future in as_completed(futures):
            key = futures[future]
            results[key] = future.result()
            if on_done is not None:
                try:
                    on_done(key, len(results), len(keys))
                except Exception:  # noqa: BLE001 - a listener must never cost the run
                    logger.exception("OBI progress listener raised; the round continues")
    return {key: results[key] for key in keys}
