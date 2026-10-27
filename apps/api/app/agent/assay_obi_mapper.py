"""Map extracted assay names to OBI ontology terms.

Matching chain (stops at first hit):
  1. Exact match on name_in_paper, onto a term with no children in the index
                                       → resource: exact_original,       confidence: "high"
  1b. Exact match onto a term that has children: the hit and its direct children are pinned
      into step 2's candidates, and the picker chooses
                                       → resource: exact_original_llm
  2. Embedding top-K + LLM pick        → resource: embedding_llm,        confidence: <float>
  3. Only when step 2's picker answers "none" and there was no exact hit: one more pick over
     the whole vocabulary            → resource: fulllist_llm,         confidence: None

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

Step 3 is for the names retrieval cannot reach at all. "complete blood count" does not embed
near `hematology assay`, nor "multianalyte profiling" near `cytometric bead array assay`, and
those were the two entries of the 31-paper v3 results left unmapped. Shown all 701 terms, the
picker finds both. It is a fallback and not the default: given the whole list for every entry,
the picker stops at parent terms ("RNA-seq" for bulk RNA-seq, "genotyping by array" for SNP
array) and scored 128 exact against step 2's 141 (docs/obi_fulllist_llm_vs_embedding.md).
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from openai import OpenAI

from app.agent import assay_trace
from app.agent.assay_extractor import paper_names
from app.config import settings

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_OBI_DIR = _REPO_ROOT / "data" / "OBI"
# Pruned vocabulary + matching vectors — see data/OBI/README.md for how they are built.
_OBI_TERMS_PATH = _OBI_DIR / "obi_assay_pruned_index.json"
_EMBEDDINGS_PATH = _OBI_DIR / "obi_assay_pruned_embeddings.json"
#: Source of the `is_a` edges. The index carries no parent links, only `n_descendants`, which
#: counts the full ontology and so calls ELISA (53) a parent though the index holds none of them.
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
    terms = json.loads(terms_path.read_text(encoding="utf-8"))
    lookup: dict[str, dict[str, str]] = {}
    for term in terms:
        obi_id = term.get("id", "")
        label = term.get("label", "")
        if not obi_id or not label or not _is_generic_assay_term(obi_id, label):
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
        t["id"]
        for t in terms
        if t.get("id") and _is_generic_assay_term(t["id"], t.get("label", ""))
    )


_OBO_TERM_ID = re.compile(r"^id: (\S+)", re.MULTILINE)
_OBO_IS_A = re.compile(r"^is_a: (\S+)", re.MULTILINE)


@lru_cache(maxsize=8)
def _index_children(terms_path: Path = _OBI_TERMS_PATH) -> dict[str, tuple[str, ...]]:
    """Direct `is_a` children per term, both ends inside the index's generic vocabulary.

    Direct only: walking further is _pinned_candidates' decision, and it does so for the RNA
    sequencing family alone (_TWO_TIER_PIN_IDS).
    An absent obi.obo gives {}, which leaves every exact hit answering outright as before.
    """
    if not _OBO_PATH.exists():
        return {}
    allowed = _term_ids(terms_path)
    children: dict[str, list[str]] = {}
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
    details = _term_details()
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


@lru_cache(maxsize=1)
def _term_details() -> dict[str, dict[str, Any]]:
    """Definition and descendant count per id, from the index the embeddings were built over.

    The embeddings file carries the definition only inside `embed_input`, joined to the label
    and synonyms; the index keeps it as its own field, alongside `n_descendants`. The picker is
    told to judge by definition and break ties on fewer descendants, so both have to reach it.
    """
    if not _OBI_TERMS_PATH.exists():
        return {}
    return {
        t["id"]: {"definition": t.get("definition") or "", "n_descendants": t.get("n_descendants")}
        for t in json.loads(_OBI_TERMS_PATH.read_text(encoding="utf-8")) if t.get("id")
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


@lru_cache(maxsize=256)
def _embed_query(text: str) -> np.ndarray:
    """One embedding call per distinct query string per process. The vector for a string never
    changes, and round 5's re-pick retrieves on the same queries round 4 just did."""
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
    details = _term_details()
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
    marks = []
    if candidate.get("pin") == "exact":
        marks.append("exact name match")
    elif candidate.get("pin") == "child":
        marks.append("child of exact name match")
    elif candidate.get("pin") == "grandchild":
        marks.append("grandchild of exact name match")
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
_PICK_REPLY = re.compile(r"#?\s*(\d+)\s*[.)]?(?:[\s\t]+(exact|broad))?")


def parse_pick_reply(reply: str, n_candidates: int) -> tuple[int | None, str | None]:
    """(0-based candidate index, "EXACT"/"BROAD" or None), or (None, None) for "none" or
    anything ambiguous."""
    reply = reply.strip().strip("*`'\"").strip().lower()
    match = _PICK_REPLY.fullmatch(reply)
    if not match:
        if reply not in ("none", "none."):
            logger.warning("OBI pick reply not understood, treated as none: %r", reply[:80])
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
    """
    prompt = build_pick_prompt(assay_name, candidates, sample_type, readouts, aliases,
                               standard_technique_name)

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    reply = (resp.choices[0].message.content or "").strip().lower()
    # The numbered lines are retrieval's output and are gone once the pick is parsed; with the
    # reply beside them a wrong term can be read as a retrieval miss or a picker miss.
    assay_trace.record("obi", registry_key or assay_name, reply=reply,
                       candidates=[_candidate_line(i + 1, c) for i, c in enumerate(candidates)])
    idx, granularity = parse_pick_reply(reply, len(candidates))
    if idx is None:
        return None
    chosen = candidates[idx]
    return {
        "obi_id": chosen["id"],
        "obi_label": chosen["label"],
        "resource": "embedding_llm",
        "confidence": chosen["similarity"],
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
    is also the floor: if the picker answers "none" -- or there are no embeddings to retrieve
    with -- the verbatim match stands rather than being lost.
    """
    exact_hit = next((p for p in pinned or [] if p.get("pin") == "exact"), None)
    fallback = ({"obi_id": exact_hit["id"], "obi_label": exact_hit["label"],
                 "resource": "exact_original", "confidence": "high"} if exact_hit else None)
    if not _EMBEDDINGS_PATH.exists():
        return fallback
    raw_pool = _top_k_candidates(_paper_query(query, aliases), allowed_ids=allowed_ids)
    pools = [raw_pool]
    normalized = standard_technique_query.strip()
    if normalized and normalized.lower() != query.strip().lower():
        pools.append(_top_k_candidates(normalized, allowed_ids=allowed_ids))
    candidates = _merge_candidates(*pools)
    if pinned:
        candidates = _with_pinned(candidates, pinned)
    if not candidates:
        return None
    picked = _llm_pick(
        display_name or query, candidates,
        sample_type=sample_type, readouts=readouts, model=model, aliases=aliases,
        standard_technique_name=normalized if normalized.lower() != (display_name or query).strip().lower()
        else "",
        registry_key=registry_key,
    )
    if not picked and not exact_hit:
        return _fulllist_pick(
            display_name or query, sample_type=sample_type, readouts=readouts, model=model,
            aliases=aliases,
            standard_technique_name=normalized if normalized.lower() != (display_name or query).strip().lower()
            else "",
            registry_key=registry_key,
        )
    if exact_hit:
        if not picked:
            return {**fallback, "resource": "exact_original_llm"}
        chosen = next(c for c in candidates if c["id"] == picked["obi_id"])
        if chosen.get("pin") == "exact" or chosen.get("similarity") is None:
            picked["confidence"] = "high"
        picked["resource"] = "exact_original_llm"
        return picked
    # Attribute the win when only the technique query could reach the chosen term. Without
    # this, a benchmark run cannot tell whether the technique earned its keep in step 2 or
    # merely rode along -- and the two justify very different things.
    if picked and len(pools) > 1:
        if picked.get("obi_id") not in {c["id"] for c in raw_pool}:
            picked["resource"] = "embedding_llm_normalized"
    return picked


# ── Full-list fallback: the picker said none of the retrieved terms fits ─────────

#: What a full-list pick is attributed to. Paid, so not in assay_service._OBI_FREE_RESOURCES.
FULLLIST_RESOURCE = "fulllist_llm"


def _fulllist_candidates(terms_path: Path = _OBI_TERMS_PATH) -> list[dict[str, Any]]:
    """Every term the vocabulary allows, in index order, as the picker renders a candidate."""
    allowed = _term_ids(terms_path)
    return [{"id": t["id"], "label": t["label"],
             "text": " | ".join([t["label"], *(str(s) for s in t.get("synonyms") or [])]),
             "definition": t.get("definition") or "", "n_descendants": t.get("n_descendants"),
             "similarity": None}
            for t in json.loads(terms_path.read_text(encoding="utf-8"))
            if t.get("id") in allowed]


def build_fulllist_prompt(
    assay_name: str,
    candidates: list[dict[str, Any]],
    sample_type: str = "",
    readouts: str = "",
    aliases: list[str] | None = None,
    standard_technique_name: str = "",
) -> str:
    """Render resolver_obi_assay_fulllist.txt. The term list comes before the assay record, so
    every call of a run shares one long prefix the provider caches (95% of prompt tokens in the
    31-paper experiment)."""
    named = [a.strip() for a in (aliases or []) if isinstance(a, str) and a.strip()]
    lines = [_candidate_line(i + 1, c).removesuffix(" ()") for i, c in enumerate(candidates)]
    return (
        (_PROMPTS_DIR / "resolver_obi_assay_fulllist.txt").read_text(encoding="utf-8")
        .replace("{candidates}", "\n".join(lines))
        .replace("{assay_name}", assay_name)
        .replace("{aliases}", ", ".join(named) if named else "none given")
        .replace("{standard_technique_name}", standard_technique_name.strip() or "not given")
        .replace("{sample_type}", sample_type.strip() or "not specified")
        .replace("{readouts}", readouts.strip() or "not specified")
    )


def _fulllist_pick(
    assay_name: str,
    sample_type: str = "",
    readouts: str = "",
    model: str = settings.OPENAI_MODEL,
    aliases: list[str] | None = None,
    standard_technique_name: str = "",
    registry_key: str = "",
    terms_path: Path = _OBI_TERMS_PATH,
) -> dict[str, Any] | None:
    """One pick over the whole vocabulary, for an entry the retrieved candidates could not map.

    The mapping it returns is never re-picked (see repick_broad): the re-pick retrieves the
    same top-K that just failed this entry, so it could only move it back onto a term step 2
    already rejected.
    """
    candidates = _fulllist_candidates(terms_path)
    if not candidates:
        return None
    prompt = build_fulllist_prompt(assay_name, candidates, sample_type, readouts, aliases,
                                   standard_technique_name)
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}], temperature=0)
    reply = (resp.choices[0].message.content or "").strip().lower()
    # The candidates are the vocabulary, the same for every entry, so only their count is kept.
    assay_trace.record("obi_fulllist", registry_key or assay_name, reply=reply,
                       n_candidates=len(candidates))
    idx, granularity = parse_pick_reply(reply, len(candidates))
    if idx is None:
        return None
    chosen = candidates[idx]
    return {
        "obi_id": chosen["id"],
        "obi_label": chosen["label"],
        "resource": FULLLIST_RESOURCE,
        "confidence": None,
        "granularity": granularity,
    }


# ── Re-pick: every BROAD mapping gets one narrower question ──────────────────────

#: What a re-pick is attributed to. Paid, so not in assay_service._OBI_FREE_RESOURCES.
REPICK_RESOURCE = "embedding_llm_repick"


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
    must already be absent from `candidates`."""
    named = [a.strip() for a in (aliases or []) if isinstance(a, str) and a.strip()]
    return (
        (_PROMPTS_DIR / "repick_obi_assay.txt").read_text(encoding="utf-8")
        .replace("{assay_name}", assay_name)
        .replace("{aliases}", ", ".join(named) if named else "none given")
        .replace("{standard_technique_name}", standard_technique_name.strip() or "not given")
        .replace("{broad_id}", broad_id)
        .replace("{broad_label}", broad_label)
        .replace("{candidates}",
                 "\n".join(_candidate_line(i + 1, c) for i, c in enumerate(candidates)))
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
    """One more pick for an entry whose mapping the picker marked BROAD, with that term removed.

    BROAD means the term is a category the assay falls under, not the assay. This asks the
    narrower question the first pick did not: with the category gone, does any candidate's
    definition describe the function?
    SDY1640's intracellular cytokine staining had `cytokine assay` fourth in its own candidate
    list and was still answered `flow cytometry assay, BROAD`.

    Retrieval is the one round 4 did (paper wording + technique, merged), so with `_embed_query`
    cached this costs one chat call. The reply and candidates are kept in the trace under
    `repick`, beside the first pick's `obi` record rather than over it. Returns None when the
    picker still finds nothing, or when there is nothing to retrieve with.
    """
    broad_id = str(mapping.get("obi_id") or "")
    broad_label = str(mapping.get("obi_label") or "")
    if not broad_id or not _EMBEDDINGS_PATH.exists():
        return None
    names = paper_names(entry)
    name = (names[0] if names else key).strip()
    raw_aliases = entry.get("aliases")
    aliases = names[1:] + [a for a in (raw_aliases if isinstance(raw_aliases, list) else [])
                           if isinstance(a, str)]
    technique = str(entry.get("standard_technique_name") or "").strip()
    sample_type = str(entry.get("sample_type") or "")
    readouts = str(entry.get("readouts") or "")

    allowed_ids = _term_ids(terms_path)
    pools = [_top_k_candidates(_paper_query(name, aliases), allowed_ids=allowed_ids)]
    if technique and technique.lower() != name.lower():
        pools.append(_top_k_candidates(technique, allowed_ids=allowed_ids))
    candidates = [c for c in _merge_candidates(*pools) if c["id"] != broad_id]
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
    assay_trace.record("repick", key, reply=reply, broad_id=broad_id, broad_label=broad_label,
                       candidates=[_candidate_line(i + 1, c) for i, c in enumerate(candidates)])
    idx, granularity = parse_pick_reply(reply, len(candidates))
    if idx is None:
        return None
    chosen = candidates[idx]
    return {
        "obi_id": chosen["id"],
        "obi_label": chosen["label"],
        "resource": REPICK_RESOURCE,
        "confidence": chosen.get("similarity"),
        "granularity": granularity or "EXACT",
    }


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

    A BROAD mapping from the full-list fallback is not asked again: the re-pick retrieves the
    top-K whose picker already answered "none" for that entry.
    """
    obi = {key: dict(value) for key, value in (obi or {}).items()}
    repicked: dict[str, dict[str, str]] = {}
    attempts = 0
    for key, mapping in obi.items():
        if not _is_broad_mapping(mapping) or mapping.get("resource") == FULLLIST_RESOURCE:
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
) -> dict[str, Any] | None:
    """Return OBI metadata for an assay, or None when no candidate fits.

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

    # Step 2 — embedding candidates from both queries (restricted to terms_path's
    # vocabulary), merged into one top-K list, LLM picks best
    original = name_in_paper.strip()
    query = original or normalized
    display_name = query
    allowed_ids = _term_ids(terms_path)
    return _embedding_llm_match(
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
    )


def enrich_assays_with_obi(
    assays: dict[str, Any],
    terms_path: Path = _OBI_TERMS_PATH,
    model: str = settings.OPENAI_MODEL,
) -> dict[str, dict[str, Any]]:
    """Add OBI fields to a Phase-1 assay registry keyed by assay name.

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
            # call threw away every mapping the paper had already paid for.
            logger.warning("%s: OBI lookup failed - %s", canonical, exc)
            entry.update({"obi_id": None, "obi_label": None, "resource": "error",
                          "obi_confidence": None, "obi_granularity": None,
                          "obi_error": f"{type(exc).__name__}: {exc}"})
            enriched[canonical] = entry
            continue
        if mapped:
            entry["obi_id"] = mapped["obi_id"]
            entry["obi_label"] = mapped["obi_label"]
            entry["resource"] = mapped["resource"]
            entry["obi_confidence"] = mapped["confidence"]
            # The picker's own EXACT/BROAD; None for an exact name match (no pick was asked)
            # and for a reply that gave only a number.
            entry["obi_granularity"] = mapped.get("granularity")
        else:
            entry["obi_id"] = None
            entry["obi_label"] = None
            entry["resource"] = "unresolved"
            # Unconditional, not setdefault: a stale extraction confidence sitting next to
            # resource="unresolved" reads as an OBI score.
            entry["obi_confidence"] = None
            entry["obi_granularity"] = None

        enriched[canonical] = entry
    return enriched
