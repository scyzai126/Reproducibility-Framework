import pytest

from app.agent.assay_obi_mapper import enrich_assays_with_obi, map_assay_to_obi
from app.config import settings


@pytest.fixture(autouse=True)
def _embedding_strategy(monkeypatch):
    """Every test above the "2026-10-20: tree descent" section exercises step 2's embedding
    path, which is the default; pinning it here keeps those tests meaning what they say even
    when a developer's .env sets OBI_MAPPING_STRATEGY=descend (settings reads .env). The
    descent tests set the strategy themselves, and one of them checks the default."""
    monkeypatch.setattr(settings, "OBI_MAPPING_STRATEGY", "embedding")


def test_exact_original_match():
    mapped = map_assay_to_obi("ELISA", "ELISA")

    assert mapped["obi_id"] == "OBI:0000661"
    assert mapped["resource"] == "exact_original"
    assert mapped["confidence"] == "high"


def test_ontology_synonym_maps_prompt_canonical_names(monkeypatch):
    # CyTOF's term has children in the index, so its hit goes to the picker; the stub abstains
    # and the exact hit stands.
    _no_pick(monkeypatch)
    assert map_assay_to_obi("CyTOF", "CyTOF")["obi_id"] == "OBI:0002115"
    assert map_assay_to_obi("CITE-seq", "CITE-seq")["obi_id"] == "OBI:0003788"
    assert map_assay_to_obi("Olink", "Olink")["obi_id"] == "OBI:0003112"


def test_exact_match_confidence_is_always_high():
    original = map_assay_to_obi("ELISA", "ELISA")
    assert original["confidence"] == "high"
    assert original["resource"] == "exact_original"


def test_the_technique_is_not_an_exact_match_key(monkeypatch):
    """Only the paper's own name is looked up exactly; the technique goes to step 2.

    It was an exact key until 2026-10-02 ("exact_normalized_llm") and was removed for answering
    too generally: 33 of 52 benchmark disagreements were its hits. "enzyme-linked immunosorbent
    assay" is a verbatim OBI label, so an exact round would have resolved this pair for free --
    it must instead reach the embedding + LLM step, carrying the technique as a query.
    """
    from app.agent import assay_obi_mapper

    calls = []
    monkeypatch.setattr(
        assay_obi_mapper, "_embedding_llm_match",
        lambda query, **kwargs: calls.append((query, kwargs)) or None,
    )

    assert assay_obi_mapper.map_assay_to_obi(
        "XYZZY_unknown", "enzyme-linked immunosorbent assay") is None
    assert len(calls) == 1
    query, kwargs = calls[0]
    assert query == "XYZZY_unknown"
    assert kwargs["standard_technique_query"] == "enzyme-linked immunosorbent assay"


def test_a_staining_section_reaches_flow_cytometry_through_the_picker(monkeypatch):
    """The row technique exists for, now decided by the picker rather than a lookup.

    The paper calls its assay "Surface and intracellular cytokine staining" -- a protocol
    section heading. Against that string OBI:0000916 ranks 44th of 700, outside TOP_K. The
    technique query "flow cytometry" retrieves it, so the merged pool holds it, and the picker
    is shown the paper's wording with the technique alongside.
    """
    from app.agent import assay_obi_mapper

    def fake_top_k(query, k=10, allowed_ids=None, **_):
        if query == "Surface and intracellular cytokine staining":
            return [{"id": "OBI:0001632", "label": "immuno staining assay", "similarity": 0.52}]
        return [{"id": "OBI:0000916", "label": "flow cytometry assay", "similarity": 0.88}]

    seen = {}

    def fake_pick(assay_name, candidates, standard_technique_name="", **_):
        seen.update(name=assay_name, normalized=standard_technique_name,
                    ids=[c["id"] for c in candidates])
        flow = next(c for c in candidates if c["id"] == "OBI:0000916")
        return {"obi_id": flow["id"], "obi_label": flow["label"],
                "resource": "embedding_llm", "confidence": flow["similarity"]}

    monkeypatch.setattr(assay_obi_mapper, "_top_k_candidates", fake_top_k)
    monkeypatch.setattr(assay_obi_mapper, "_llm_pick", fake_pick)

    mapped = assay_obi_mapper.map_assay_to_obi(
        "Surface and intracellular cytokine staining", "flow cytometry")

    assert mapped["obi_id"] == "OBI:0000916"
    assert mapped["resource"] == "embedding_llm_normalized"
    # Both retrieved terms reach the picker; their OBI neighbours ride along after them
    # (_with_neighbours), which is why this is a subset and not an equality.
    assert {"OBI:0000916", "OBI:0001632"} <= set(seen["ids"])
    assert seen["ids"][:2] == ["OBI:0000916", "OBI:0001632"]
    assert seen["name"] == "Surface and intracellular cytokine staining"
    assert seen["normalized"] == "flow cytometry"


def test_the_paper_name_wins_when_both_names_exact_match(monkeypatch):
    """Deriving cannot outrank the source.

    OBI carries `RNA-seq assay` and `RNA sequencing assay` as separate live terms, and this is
    the only disagreement among the 171 curated rows: the paper's "RNA-seq" hits the first, its
    technique "RNA sequencing" the second. The paper's own wording is also the better
    answer here, which is what makes step 1a-before-1b the right order rather than a coin toss.
    """
    from app.agent import assay_obi_mapper
    _no_pick(monkeypatch)

    mapped = assay_obi_mapper.map_assay_to_obi("RNA-seq", "RNA sequencing")

    # RNA-seq assay has children, so the picker is asked; it abstains here, and the paper's own
    # exact hit -- not the technique's -- is what stands.
    assert mapped["resource"] == "exact_original_llm"
    assert mapped["obi_label"] == "RNA-seq assay"


def test_an_absent_technique_leaves_step_1_exactly_as_it_was(monkeypatch):
    """The 44 registries on disk predate the field, and registry_from_claims cannot supply it.

    An empty technique must not match anything -- an empty lookup key resolving to any
    term would silently remap every legacy entry.
    """
    from app.agent import assay_obi_mapper
    _no_step3(monkeypatch)

    assert assay_obi_mapper.map_assay_to_obi("XYZZY_unknown", "") is None
    assert assay_obi_mapper.map_assay_to_obi("XYZZY_unknown", "   ") is None


def test_enrich_assays_preserves_registry_fields(monkeypatch):
    # Stubbed: unstubbed, the unknown name reached step 2 and called OpenAI for real.
    _no_step3(monkeypatch)
    assays = {
        "Bulk RNA-seq": {
            "sample_type": "whole blood",
            "readouts": "transcriptional signatures",
        },
        "Unknown Custom Assay": {
            "sample_type": "serum",
            "readouts": "custom readout",
        },
    }

    enriched = enrich_assays_with_obi(assays)

    assert enriched["Bulk RNA-seq"]["sample_type"] == "whole blood"
    assert enriched["Bulk RNA-seq"]["obi_id"] == "OBI:0003090"
    assert enriched["Unknown Custom Assay"]["obi_id"] is None
    assert enriched["Unknown Custom Assay"]["resource"] == "unresolved"


def test_step3_retrieves_on_the_technique_but_shows_the_llm_the_paper_name(monkeypatch):
    """Normalizing can delete the detail that separates a parent OBI term from its child.

    "ImmunoChip array" normalizes to "Genome-wide SNP genotyping", which drops the word
    "array" — and with it the evidence for `genotyping by SNP array assay` over plain
    `genotyping assay`. The technique is still the better retrieval query (the
    paper's own wording pulls ChIP-chip terms on the "Chip" substring), so the two roles
    have to be split: retrieve on one, show the other.
    """
    from app.agent import assay_obi_mapper

    seen = {}

    def fake_top_k(query, k=10, allowed_ids=None, **_):
        seen["query"] = query
        return [{"id": "OBI:0002031", "label": "genotyping by SNP array assay", "similarity": 0.67}]

    def fake_llm_pick(assay_name, candidates, sample_type="", readouts="", standard_technique_name="",
                      **_):
        seen.update(shown=assay_name, normalized=standard_technique_name)
        return {
            "obi_id": "OBI:0002031",
            "obi_label": candidates[0]["label"],
            "resource": "embedding_llm",
            "confidence": 0.67,
        }

    monkeypatch.setattr(assay_obi_mapper, "_top_k_candidates", fake_top_k)
    monkeypatch.setattr(assay_obi_mapper, "_llm_pick", fake_llm_pick)

    assay_obi_mapper.map_assay_to_obi("ImmunoChip array", "Genome-wide SNP genotyping")

    assert seen["query"] == "Genome-wide SNP genotyping"
    assert seen["shown"] == "ImmunoChip array"
    assert seen["normalized"] == "Genome-wide SNP genotyping"


def test_step3_shows_one_name_when_technique_changed_nothing(monkeypatch):
    """No parenthetical when the two names are the same — it would just be noise."""
    from app.agent import assay_obi_mapper

    seen = {}

    def fake_llm_pick(assay_name, candidates, sample_type="", readouts="", **_):
        seen["shown"] = assay_name
        return None

    monkeypatch.setattr(
        assay_obi_mapper,
        "_top_k_candidates",
        lambda query, k=10, allowed_ids=None, **_: [{"id": "OBI:1", "label": "x", "similarity": 0.5}],
    )
    monkeypatch.setattr(assay_obi_mapper, "_llm_pick", fake_llm_pick)

    assay_obi_mapper.map_assay_to_obi("SIMoA", "SIMoA")

    assert seen["shown"] == "SIMoA"


# ── Compositional-label pruning ───────────────────────────────────────────────

_ELISPOT_IFNG = "ELISPOT assay measuring epitope specific interferon-gamma production by T cells"


def test_compositional_labels_are_not_generic():
    """The IEDB "... assay measuring X" constructs are excluded; plain family terms are kept."""
    from app.agent.assay_obi_mapper import _is_generic_assay_label

    assert _is_generic_assay_label("enzyme-linked immunospot assay")
    assert _is_generic_assay_label("flow cytometry assay")
    assert _is_generic_assay_label("")

    assert not _is_generic_assay_label(_ELISPOT_IFNG)
    assert not _is_generic_assay_label(
        "radioactivity detection assay measuring half maximal inhibitory concentration [IC50] "
        "to determine competitive binding of a purified-MHC:ligand complex"
    )


def test_the_detecting_variant_of_the_construct_is_excluded_too():
    """Same IEDB shape, different verb -- and matching only "measuring" let four of them stay.

    OBI:1110207 was then chosen four times in a 30-paper run, twice over OBI:0600031 for entries
    the papers called an ELISpot. A term naming the analyte it detects is not a technique family.
    """
    from app.agent.assay_obi_mapper import _OBI_TERMS_PATH, _build_lookup, _is_generic_assay_label, _term_ids

    assert not _is_generic_assay_label("assay detecting IFN-gamma production")
    assert not _is_generic_assay_label(
        "cell death assay detecting lactate dehydrogenase (LDH) release")
    # A technique whose name merely contains "detection" is untouched -- the filter keys on the
    # participial verb, which is what marks the compositional construct.
    assert _is_generic_assay_label("infectious agent detection assay")

    _term_ids.cache_clear()
    _build_lookup.cache_clear()
    assert "OBI:1110207" not in _term_ids(_OBI_TERMS_PATH)
    assert "assay detecting ifn-gamma production" not in _build_lookup()
    assert _build_lookup()["enzyme-linked immunospot assay"]["obi_id"] == "OBI:0600031"


def test_pinned_compositional_term_survives_every_filter():
    """OBI:1110179 is OBI's replacement for the obsolete MHC multimer staining assay. Without it a
    tetramer stain maps to flow cytometry and round 5 folds it into the paper's flow panels.

    The pin must hold at all three load-time filters as well as in the index, and pinning one id
    must not reopen the rest of the construct -- OBI:1110207 stays out.
    """
    from app.agent import assay_obi_mapper
    from app.agent.assay_obi_mapper import (
        _OBI_TERMS_PATH, _build_lookup, _is_generic_assay_term, _term_ids,
    )

    tetramer = "MHC tetramer/multimer assay measuring binding of a T cell epitope:MHC:TCR complex"
    assert _is_generic_assay_term("OBI:1110179", tetramer)
    assert not _is_generic_assay_term("OBI:1110207", "assay detecting IFN-gamma production")

    _term_ids.cache_clear()
    _build_lookup.cache_clear()
    assert "OBI:1110179" in _term_ids(_OBI_TERMS_PATH)
    assert "OBI:1110207" not in _term_ids(_OBI_TERMS_PATH)
    assert _build_lookup()[tetramer.lower()]["obi_id"] == "OBI:1110179"

    assay_obi_mapper._load_embeddings.cache_clear()
    entries, _ = assay_obi_mapper._load_embeddings()
    assert "OBI:1110179" in {e["id"] for e in entries}


def test_exact_lookup_excludes_compositional_terms():
    from app.agent.assay_obi_mapper import _build_lookup

    _build_lookup.cache_clear()
    lookup = _build_lookup()

    assert _ELISPOT_IFNG.lower() not in lookup
    # The generic terms still resolve
    assert lookup["enzyme-linked immunosorbent assay"]["obi_id"] == "OBI:0000661"
    assert lookup["enzyme-linked immunospot assay"]["obi_id"] == "OBI:0600031"


def test_term_ids_exclude_compositional_terms():
    from app.agent.assay_obi_mapper import _OBI_TERMS_PATH, _term_ids

    _term_ids.cache_clear()
    ids = _term_ids(_OBI_TERMS_PATH)

    assert "OBI:1110059" not in ids  # ELISPOT ... measuring epitope specific IFN-gamma
    assert "OBI:1110172" not in ids  # ICS ... measuring epitope specific IFN-gamma
    assert "OBI:0600031" in ids  # enzyme-linked immunospot assay
    assert "OBI:0000916" in ids  # flow cytometry assay


def test_filter_still_guards_an_unpruned_vocabulary(tmp_path):
    """The default vocabulary is pre-pruned, so the load-time filter has nothing to do there.

    It still has to work, because --terms lets a caller point the mapper at any term list —
    including the unpruned assay branch of obi.obo, written out here.
    """
    import importlib.util
    import json
    from pathlib import Path

    from app.agent.assay_obi_mapper import _OBI_DIR, _term_ids

    script = Path(__file__).resolve().parents[3] / "scripts" / "prune_obi_domain.py"
    spec = importlib.util.spec_from_file_location("prune_obi_domain", script)
    prune = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prune)

    unpruned = tmp_path / "obi_assay_branch.json"
    unpruned.write_text(json.dumps(prune.assay_branch(prune.OBO_PATH)), encoding="utf-8")

    _term_ids.cache_clear()
    ids = _term_ids(unpruned)

    assert "OBI:1110059" not in ids  # filtered out of the raw list, not merely absent from it
    assert "OBI:0600031" in ids

    # The live index is a *subset* of the label-filtered full list, not an equal-sized twin: on
    # top of the compositional filter it is also domain-pruned (scripts/prune_obi_domain.py),
    # which no label regex can express. Subset is the property worth guarding — a domain prune
    # only ever removes.
    live = _term_ids(_OBI_DIR / "obi_assay_pruned_index.json")
    assert set(live) <= set(ids)


def test_embedding_candidates_are_all_generic(monkeypatch):
    """Step 3 can never surface a compositional term, whatever the query embeds near."""
    import numpy as np

    from app.agent import assay_obi_mapper

    assay_obi_mapper._load_embeddings.cache_clear()
    entries, matrix = assay_obi_mapper._load_embeddings()
    assert len(entries) == matrix.shape[0]

    # Aim the query straight at what used to be the top compositional hit for an ELISPOT
    monkeypatch.setattr(assay_obi_mapper, "_embed_query", lambda text: matrix[0])

    candidates = assay_obi_mapper._top_k_candidates("IFN-gamma ELISPOT")

    assert candidates
    assert all(
        assay_obi_mapper._is_generic_assay_term(c["id"], c["label"]) for c in candidates
    )


# ── Extraction confidence vs OBI confidence ───────────────────────────────────

def _no_pick(monkeypatch):
    """Run step 2 offline: retrieval returns nothing and the picker abstains, so only the
    pinned exact hit and its children reach the (stubbed) picker."""
    from app.agent import assay_obi_mapper

    monkeypatch.setattr(assay_obi_mapper, "_top_k_candidates", lambda *a, **k: [])
    monkeypatch.setattr(assay_obi_mapper, "_llm_pick", lambda *a, **k: None)


def _no_step3(monkeypatch):
    """Stub the embedding+LLM fallback so a deliberately unmatchable name resolves to None.

    Without this the unresolved branch reaches OpenAI, and the suite's stub API key 401s.
    """
    from app.agent import assay_obi_mapper

    monkeypatch.setattr(
        assay_obi_mapper, "_embedding_llm_match", lambda *a, **k: None
    )



def test_enrich_writes_obi_confidence_and_never_the_bare_confidence_key():
    """`confidence` means the *extraction* confidence in a registry; the OBI score is its own key.

    scripts/build_assay_table.py, the corpus table it writes and the UI were already
    on `obi_confidence`; enrich_assays_with_obi was the last path still overwriting.
    """
    enriched = enrich_assays_with_obi({"ELISA": {"sample_type": "serum", "readouts": "titers"}})

    assert enriched["ELISA"]["obi_confidence"] == "high"
    assert "confidence" not in enriched["ELISA"]


def test_extraction_confidence_survives_enrichment_on_both_branches(monkeypatch):
    _no_step3(monkeypatch)
    assays = {
        "ELISA": {"sample_type": "serum", "readouts": "titers", "extraction_confidence": 0.98},
        "Unknown Custom Assay": {"sample_type": "serum", "readouts": "x", "extraction_confidence": 0.45},
    }

    enriched = enrich_assays_with_obi(assays)

    assert enriched["ELISA"]["extraction_confidence"] == 0.98
    assert enriched["ELISA"]["obi_id"] == "OBI:0000661"
    assert enriched["Unknown Custom Assay"]["extraction_confidence"] == 0.45
    assert enriched["Unknown Custom Assay"]["resource"] == "unresolved"


def test_an_unresolved_entry_never_inherits_a_stale_confidence_as_its_obi_score(monkeypatch):
    """The old code used setdefault, so a registry's own `confidence` survived as the OBI score."""
    _no_step3(monkeypatch)
    enriched = enrich_assays_with_obi({"Unknown Custom Assay": {"confidence": 0.9}})

    assert enriched["Unknown Custom Assay"]["resource"] == "unresolved"
    assert enriched["Unknown Custom Assay"]["obi_confidence"] is None
    assert enriched["Unknown Custom Assay"]["confidence"] == 0.9


# ── The lexical exact-match round is gone ─────────────────────────────────────

def test_a_name_the_vocabulary_carries_only_as_a_suffix_variant_now_costs_a_call(monkeypatch):
    """"Flow Cytometry Analysis" reduces lexically to "flow cytometry", an exact OBI label.

    That reduction used to be a free hit (resource exact_normalized). With the round removed
    the name is not in the vocabulary verbatim, so it reaches the paid round like any other
    miss -- which is the whole cost of the removal, measured at 7 names across the corpus.
    """
    from app.agent import assay_obi_mapper
    _no_step3(monkeypatch)

    assert assay_obi_mapper.map_assay_to_obi("Flow Cytometry Analysis", "") is None


def test_enrichment_does_not_resurrect_the_lexical_key_through_the_registry_key(monkeypatch):
    """enrich_assays_with_obi used to pass the registry key in as technique."""
    from app.agent import assay_obi_mapper
    _no_step3(monkeypatch)

    enriched = enrich_assays_with_obi({"Flow Cytometry Analysis": {"sample_type": "PBMCs"}})

    assert enriched["Flow Cytometry Analysis"]["obi_id"] is None
    assert enriched["Flow Cytometry Analysis"]["resource"] == "unresolved"
    # The field is no longer written at all: it only ever echoed the key back.
    assert "standard_technique_name" not in enriched["Flow Cytometry Analysis"]


def test_the_paper_name_is_what_step2_queries_and_shows(monkeypatch):
    """With no technique in play, retrieval query and display name are both the raw name."""
    from app.agent import assay_obi_mapper

    seen = {}

    monkeypatch.setattr(
        assay_obi_mapper,
        "_top_k_candidates",
        lambda query, k=10, allowed_ids=None, **_: (
            seen.__setitem__("query", query),
            [{"id": "OBI:1", "label": "x", "similarity": 0.5}],
        )[1],
    )
    monkeypatch.setattr(
        assay_obi_mapper,
        "_llm_pick",
        lambda assay_name, candidates, sample_type="", readouts="", **_: seen.__setitem__("shown", assay_name),
    )

    assay_obi_mapper.map_assay_to_obi("Von Mises Stress Analysis", "")

    assert seen["query"] == "Von Mises Stress Analysis"
    assert seen["shown"] == "Von Mises Stress Analysis"


# ── Step 2: both names are retrieved on, and their pools merged ───────────────

def test_step2_retrieves_on_both_names(monkeypatch):
    """Neither query is dropped.

    Measured over the 101 curated pairs that reach this round, the technique gives a
    better top-1 on 52% of them and a worse one on 32% -- "hemagglutination inhibition (HAI)
    assays" scores 0.809 against `viral hemagglutination inhibition assay` where its terse
    technique scores 0.658. Choosing either one alone trades one set of failures for
    another, so both are retrieved and merged.
    """
    from app.agent import assay_obi_mapper

    queries = []

    monkeypatch.setattr(
        assay_obi_mapper, "_top_k_candidates",
        lambda query, k=10, allowed_ids=None, **_: (
            queries.append(query), [{"id": "OBI:1", "label": "x", "similarity": 0.5}])[1],
    )
    monkeypatch.setattr(
        assay_obi_mapper, "_llm_pick",
        lambda assay_name, candidates, sample_type="", readouts="", **_: None,
    )

    assay_obi_mapper.map_assay_to_obi("ImmunoChip array", "Genome-wide SNP genotyping")

    assert queries == ["ImmunoChip array", "Genome-wide SNP genotyping"]


def test_step2_retrieves_once_when_the_two_names_agree(monkeypatch):
    """A technique that changed nothing must not buy a second embedding call."""
    from app.agent import assay_obi_mapper

    queries = []

    monkeypatch.setattr(
        assay_obi_mapper, "_top_k_candidates",
        lambda query, k=10, allowed_ids=None, **_: (
            queries.append(query), [{"id": "OBI:1", "label": "x", "similarity": 0.5}])[1],
    )
    monkeypatch.setattr(
        assay_obi_mapper, "_llm_pick",
        lambda assay_name, candidates, sample_type="", readouts="", **_: None,
    )

    assay_obi_mapper.map_assay_to_obi("SIMoA ", "simoa")

    assert queries == ["SIMoA"]


def test_merged_pools_dedupe_on_the_better_score():
    """A term found by both queries is kept once, at its higher similarity.

    The score records the strength of the best evidence for a candidate, not an average over
    how many ways it was reached -- averaging would penalise a term precisely for being found
    twice.
    """
    from app.agent.assay_obi_mapper import _merge_candidates

    merged = _merge_candidates(
        [{"id": "OBI:1", "label": "a", "similarity": 0.40},
         {"id": "OBI:2", "label": "b", "similarity": 0.90}],
        [{"id": "OBI:1", "label": "a", "similarity": 0.80},
         {"id": "OBI:3", "label": "c", "similarity": 0.10}],
    )

    assert [c["id"] for c in merged] == ["OBI:2", "OBI:1", "OBI:3"]
    assert [c["similarity"] for c in merged] == [0.90, 0.80, 0.10]


def test_merged_pools_are_capped_at_top_k():
    """Two pools of TOP_K must not hand the picker a list twice as long as it was tuned for."""
    from app.agent.assay_obi_mapper import TOP_K, _merge_candidates

    left = [{"id": f"OBI:L{i}", "label": "l", "similarity": 0.5} for i in range(TOP_K)]
    right = [{"id": f"OBI:R{i}", "label": "r", "similarity": 0.4} for i in range(TOP_K)]

    assert len(_merge_candidates(left, right)) == TOP_K


def test_the_paper_wordings_top_slots_survive_higher_scoring_normalized_hits():
    """The technique query's broad terms score higher, but cannot push the paper's out.

    A plain merge by score kept the 20 best of both pools; here that would be all 20 from the
    technique query. With PRIMARY_SLOTS reserved, the paper wording's 14 best always stay.
    """
    from app.agent.assay_obi_mapper import PRIMARY_SLOTS, TOP_K, _merge_candidates

    paper = [{"id": f"OBI:P{i}", "label": "p", "similarity": 0.4} for i in range(TOP_K)]
    normalized = [{"id": f"OBI:N{i}", "label": "n", "similarity": 0.9} for i in range(TOP_K)]

    merged = [c["id"] for c in _merge_candidates(paper, normalized)]

    assert len(merged) == TOP_K
    assert {f"OBI:P{i}" for i in range(PRIMARY_SLOTS)} <= set(merged)
    assert sum(m.startswith("OBI:N") for m in merged) == TOP_K - PRIMARY_SLOTS
    assert merged[0].startswith("OBI:N")  # still shown best-score first


def test_the_paper_query_carries_the_aliases_but_not_sample_or_readouts(monkeypatch):
    """Retrieval embeds "name | alias | ..."; sample type and readouts only reach the picker."""
    from app.agent import assay_obi_mapper

    queries = []
    monkeypatch.setattr(
        assay_obi_mapper, "_top_k_candidates",
        lambda query, k=20, allowed_ids=None, **_: (
            queries.append(query), [{"id": "OBI:1", "label": "x", "similarity": 0.5}])[1],
    )
    monkeypatch.setattr(assay_obi_mapper, "_llm_pick", lambda *a, **k: None)

    assay_obi_mapper.map_assay_to_obi(
        "Whole transcriptome profiling", "RNA sequencing",
        sample_type="PBMC", readouts="gene expression",
        aliases=["RNA-seq", "whole transcriptome profiling", " "],
    )

    assert queries == ["Whole transcriptome profiling | RNA-seq", "RNA sequencing"]


def test_a_term_only_the_standard_technique_query_could_reach_is_attributed_to_it(monkeypatch):
    """Otherwise a benchmark run cannot tell whether technique earned its keep in step 2.

    A term present in the paper-name pool stays plain `embedding_llm` even when the normalized
    query also found it -- riding along is not the same as making the difference.
    """
    from app.agent import assay_obi_mapper

    def fake_top_k(query, k=10, allowed_ids=None, **_):
        if query == "Surface and intracellular cytokine staining":
            return [{"id": "OBI:0001632", "label": "immuno staining assay", "similarity": 0.52}]
        return [{"id": "OBI:0000916", "label": "flow cytometry assay", "similarity": 0.88}]

    monkeypatch.setattr(assay_obi_mapper, "_top_k_candidates", fake_top_k)
    monkeypatch.setattr(
        assay_obi_mapper, "_llm_pick",
        lambda assay_name, candidates, sample_type="", readouts="", **_: {
            "obi_id": candidates[0]["id"], "obi_label": candidates[0]["label"],
            "resource": "embedding_llm", "confidence": candidates[0]["similarity"],
        },
    )

    mapped = assay_obi_mapper.map_assay_to_obi(
        "Surface and intracellular cytokine staining", "flow cytometry analysis")

    assert mapped["obi_id"] == "OBI:0000916"
    assert mapped["resource"] == "embedding_llm_normalized"


def test_a_term_both_queries_found_stays_plain_embedding_llm(monkeypatch):
    from app.agent import assay_obi_mapper

    monkeypatch.setattr(
        assay_obi_mapper, "_top_k_candidates",
        lambda query, k=10, allowed_ids=None, **_: [
            {"id": "OBI:0000916", "label": "flow cytometry assay", "similarity": 0.7}],
    )
    monkeypatch.setattr(
        assay_obi_mapper, "_llm_pick",
        lambda assay_name, candidates, sample_type="", readouts="", **_: {
            "obi_id": candidates[0]["id"], "obi_label": candidates[0]["label"],
            "resource": "embedding_llm", "confidence": 0.7,
        },
    )

    mapped = assay_obi_mapper.map_assay_to_obi("polychromatic FCM", "flow cytometry analysis")

    assert mapped["resource"] == "embedding_llm"


def test_the_picker_is_shown_both_names_but_retrieval_is_not_display(monkeypatch):
    """The model still judges by the paper's own wording; the technique is context.

    Normalizing can delete the detail that separates a parent OBI term from its child --
    "ImmunoChip array" normalized to "Genome-wide SNP genotyping" drops the word "array", and
    with it the evidence for `genotyping by SNP array assay` over plain `genotyping assay`.
    """
    from app.agent import assay_obi_mapper

    seen = {}

    monkeypatch.setattr(
        assay_obi_mapper, "_top_k_candidates",
        lambda query, k=10, allowed_ids=None, **_: [
            {"id": "OBI:0002031", "label": "genotyping by SNP array assay", "similarity": 0.67}],
    )
    monkeypatch.setattr(
        assay_obi_mapper, "_llm_pick",
        lambda assay_name, candidates, sample_type="", readouts="", standard_technique_name="", **_:
        seen.update(shown=assay_name, normalized=standard_technique_name),
    )

    assay_obi_mapper.map_assay_to_obi("ImmunoChip array", "Genome-wide SNP genotyping")

    assert seen["shown"] == "ImmunoChip array"
    assert seen["normalized"] == "Genome-wide SNP genotyping"


# ── domain prune guards (scripts/prune_obi_domain.py) ────────────────────────────────

# Families a paper in this corpus actually cites. Losing any of these to a future re-derivation
# of the domain prune would silently degrade mappings, so they are pinned.
_IMMUNOLOGY_CORE = (
    "OBI:0600031",  # enzyme-linked immunospot assay
    "OBI:0000661",  # enzyme-linked immunosorbent assay
    "OBI:0000916",  # flow cytometry assay
    "OBI:0000920",  # cytometric bead array assay
    "OBI:0002115",  # cytometry time of flight assay (reachable only via the "CyTOF" synonym)
    "OBI:0003788",  # CITE-seq (synonym-only)
    "OBI:0003112",  # Olink assay (synonym-only)
    "OBI:0003090",  # bulk RNA-seq assay (synonym-only)
    "OBI:0002766",  # cytokine assay — fallback parent for obsolete ICS OBI:0000665
    "OBI:0001632",  # immuno staining assay — fallback parent for obsolete MHC multimer OBI:0000667
    "OBI:0000470",  # mass spectrometry assay
    "OBI:0001985",  # microarray assay
    "OBI:0000910",  # radio immuno assay
    "OBI:0003798",  # viral plaque assay
    "OBI:0000875",  # viral hemagglutination inhibition assay
    "OBI:0003789",  # immune receptor repertoire profiling assay
    "OBI:0003790",  # antibody-dependent complement deposition assay
    "OBI:0003796",  # pathogen neutralization assay
    "OBI:0002106",  # carboxyfluorescein succinimidyl ester staining assay
    "OBI:0000743",  # immune response assay
    "OBI:0600047",  # sequencing assay
    "OBI:0000424",  # transcription profiling assay
)


def test_index_is_reproducible_from_the_full_source():
    """The committed index must be exactly what re-running the prune produces.

    Neither set of removed terms is committed, so this is what keeps the vocabulary honest: the
    index is a *derived* file, and `obi.obo` + the roots in scripts/prune_obi_domain.py are its
    source. If they ever disagree, someone hand-edited the index or changed the roots without
    rebuilding, and the difference is otherwise invisible.
    """
    import importlib.util
    import json
    from pathlib import Path

    from app.agent.assay_obi_mapper import _OBI_DIR

    # scripts/ is not an importable package — same loader shim as test_compare_assay_benchmark.py
    script = Path(__file__).resolve().parents[3] / "scripts" / "prune_obi_domain.py"
    spec = importlib.util.spec_from_file_location("prune_obi_domain", script)
    prune = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prune)

    _, _, rebuilt, _ = prune.build_index(prune.OBO_PATH)

    committed = json.loads((_OBI_DIR / "obi_assay_pruned_index.json").read_text(encoding="utf-8"))

    # Order matters, not just membership: _build_lookup uses setdefault, so index order decides
    # which term wins a synonym collision.
    assert rebuilt == committed


def test_domain_prune_keeps_the_immunology_core():
    from app.agent.assay_obi_mapper import _OBI_TERMS_PATH, _term_ids

    _term_ids.cache_clear()
    ids = _term_ids(_OBI_TERMS_PATH)

    missing = [term_id for term_id in _IMMUNOLOGY_CORE if term_id not in ids]
    assert not missing, f"domain prune dropped immunology-core terms: {missing}"


def test_domain_prune_drops_clinical_panel_terms():
    from app.agent.assay_obi_mapper import _OBI_TERMS_PATH, _term_ids

    _term_ids.cache_clear()
    ids = _term_ids(_OBI_TERMS_PATH)

    # Hospital analyzer/panel constructs — decoys that outrank plain family terms in search
    assert "OBI:2100318" not in ids  # GEM4000 ANLCOOX arterial blood glucose assay
    assert "OBI:2100362" not in ids  # CBC with manual differential venous blood neutrophil count

    # ... but the OBI:21xxxxx band is filtered by label, never dropped wholesale
    assert "OBI:2100402" in ids  # pooled clone sequencing assay — a real assay in that band
    assert "OBI:2100047" in ids  # C-reactive protein assay — a plain analyte a paper cites
    assert "OBI:2100177" in ids  # quantitative venous blood IgG assay — KEEP_WHITELIST

    # KEEP_WHITELIST also rescues from a pure subtree tier: tier F would take every X-ray
    # crystallography term, leaving ImmPort's "X-Ray Crystallography" nothing to map to.
    assert "OBI:0000912" in ids  # X-ray crystallography 3D molecular structure determination
    assert "OBI:0001595" not in ids  # ... but its MHC:ligand-complex sibling still goes


def test_index_entries_keep_their_synonyms():
    """CyTOF / CITE-seq / Olink / Bulk RNA-seq resolve only through synonyms[], so a prune that
    rewrites the index must copy entries through untouched."""
    import json

    from app.agent.assay_obi_mapper import _OBI_TERMS_PATH, _build_lookup

    terms = json.loads(_OBI_TERMS_PATH.read_text(encoding="utf-8"))
    assert all("synonyms" in t for t in terms)

    _build_lookup.cache_clear()
    lookup = _build_lookup()
    assert lookup["cytof"]["obi_id"] == "OBI:0002115"
    assert lookup["cite-seq"]["obi_id"] == "OBI:0003788"


# ── What the pick prompt actually carries ─────────────────────────────────────

def _candidates():
    return [
        {"id": "OBI:0000661", "label": "enzyme-linked immunosorbent assay",
         "text": "enzyme-linked immunosorbent assay | ELISA", "similarity": 0.61},
        {"id": "OBI:0000916", "label": "flow cytometry assay",
         "text": "flow cytometry assay | FACS", "similarity": 0.55},
    ]


def test_the_prompt_shows_the_synonyms_retrieval_matched_on():
    """Retrieval compares against "label | syn1 | ...", so the pick must see the same wording.

    Showing only the label made the model judge OBI:0000661 by a name no paper writes, while
    the vector it was retrieved by encoded "ELISA" too.
    """
    from app.agent.assay_obi_mapper import build_pick_prompt

    prompt = build_pick_prompt("multiplex ELISA", _candidates())

    assert "OBI:0000661 | enzyme-linked immunosorbent assay | ELISA (similarity: 0.61)" in prompt
    assert "OBI:0000916 | flow cytometry assay | FACS (similarity: 0.55)" in prompt


def test_the_prompt_carries_the_papers_aliases():
    """An alias often names the technique more directly than the heading it was extracted from."""
    from app.agent.assay_obi_mapper import build_pick_prompt

    prompt = build_pick_prompt(
        "Whole transcriptome profiling of NK cell subsets", _candidates(),
        aliases=["RNA-seq", "transcriptomics"])

    assert "Also called in the paper: RNA-seq, transcriptomics" in prompt


def test_absent_context_is_stated_rather_than_left_blank():
    """A blank slot reads as a missing prompt; "none given" reads as an answered question."""
    from app.agent.assay_obi_mapper import build_pick_prompt

    prompt = build_pick_prompt("SIMoA", _candidates(), aliases=[None, "  ", ""])

    assert "Also called in the paper: none given" in prompt
    assert "Sample type: not specified" in prompt
    assert "Readouts: not specified" in prompt


def test_a_candidate_with_no_synonyms_shows_only_its_label():
    from app.agent.assay_obi_mapper import build_pick_prompt

    prompt = build_pick_prompt("plaque assay", [
        {"id": "OBI:0003798", "label": "viral plaque assay",
         "text": "viral plaque assay", "similarity": 0.7}])

    assert "1. OBI:0003798 | viral plaque assay (similarity: 0.7)" in prompt


def test_the_synonym_list_is_capped():
    """CHMO:0000089 carries nine; ten such candidates would bury the labels being chosen between."""
    from app.agent.assay_obi_mapper import _MAX_SHOWN_SYNONYMS, build_pick_prompt

    syns = [f"syn{i}" for i in range(9)]
    prompt = build_pick_prompt("x", [
        {"id": "OBI:1", "label": "lab", "text": " | ".join(["lab"] + syns), "similarity": 0.5}])

    assert f"syn{_MAX_SHOWN_SYNONYMS - 1}" in prompt
    assert f"syn{_MAX_SHOWN_SYNONYMS}" not in prompt


def test_the_aliases_are_evidence_not_an_override():
    """The instruction has to say so, or a broader alias starts pulling picks to broader terms.

    Measured: in 15 of the corpus's mappings an alias named a different OBI term than the model
    chose, and the model was right in several ("Polychromatic FCM" -> flow cytometry assay beats
    the alias's broader "cytometry assay").
    """
    from app.agent.assay_obi_mapper import build_pick_prompt

    prompt = build_pick_prompt("x", _candidates(), aliases=["y"])

    assert "do not outrank the assay name" in prompt
    assert "does not justify choosing a broader term" in prompt


# ── one failed lookup, and a reply the picker cannot read ─────────────────────

def test_one_failed_lookup_leaves_the_other_entries_mapped(monkeypatch):
    """The round used to be all-or-nothing: one raised embedding call lost every mapping."""
    from app.agent import assay_obi_mapper

    def flaky(name, *args, **kwargs):
        if name == "boom":
            raise TimeoutError("embedding timed out")
        return {"obi_id": "OBI:1", "obi_label": "flow cytometry", "resource": "exact_original",
                "confidence": "high"}

    monkeypatch.setattr(assay_obi_mapper, "map_assay_to_obi", flaky)

    enriched = enrich_assays_with_obi({"flow cytometry": {}, "boom": {}})

    assert enriched["flow cytometry"]["obi_id"] == "OBI:1"
    assert enriched["boom"]["resource"] == "error"
    assert enriched["boom"]["obi_id"] is None
    assert "TimeoutError" in enriched["boom"]["obi_error"]


@pytest.mark.parametrize("reply, expected", [
    ("3", 2), ("#3", 2), ("3.", 2), ("**3**", 2),
    ("none", None), ("OBI:0000661", None), ("3 or 5", None), ("12", None), ("0", None),
    ("3 EXACT", 2), ("3\tBROAD", 2), ("3 maybe", None), ("12 EXACT", None),
])
def test_the_pick_reply_is_read_strictly(reply, expected):
    from app.agent.assay_obi_mapper import parse_pick

    assert parse_pick(reply, 10) == expected


@pytest.mark.parametrize("reply, expected", [
    ("3 EXACT", (2, "EXACT")), ("**7 broad**", (6, "BROAD")), ("3", (2, None)),
    ("none", (None, None)), ("3 ANCESTOR_ONLY", (None, None)),
])
def test_the_pick_reply_carries_its_granularity(reply, expected):
    """The prompt asks for "<n> EXACT|BROAD"; a bare number still parses, with no granularity."""
    from app.agent.assay_obi_mapper import parse_pick_reply

    assert parse_pick_reply(reply, 10) == expected


def test_the_prompt_shows_the_definition_and_descendant_count():
    """The picker is told the definition is primary and to break ties on fewer descendants,
    so both have to be on the candidate line -- a rule about text it cannot see is no rule."""
    from app.agent.assay_obi_mapper import _MAX_DEFINITION_CHARS, build_pick_prompt

    prompt = build_pick_prompt("x", [
        {"id": "OBI:0000916", "label": "flow cytometry assay", "text": "flow cytometry assay | FACS",
         "similarity": 0.55, "definition": "A cytometry assay in which cells pass a laser.",
         "n_descendants": 50},
        {"id": "OBI:2", "label": "long", "text": "long", "similarity": 0.4,
         "definition": "word " * 200, "n_descendants": 0},
    ])

    assert ("1. OBI:0000916 | flow cytometry assay | FACS | definition: A cytometry assay in "
            "which cells pass a laser. | descendants: 50 (similarity: 0.55)") in prompt
    long_line = next(line for line in prompt.splitlines() if line.startswith("2. "))
    assert "..." in long_line and len(long_line) < _MAX_DEFINITION_CHARS + 100
    assert "descendants: 0" in long_line


def test_the_prompt_carries_the_technique_on_its_own_line():
    from app.agent.assay_obi_mapper import build_pick_prompt

    assert "Standard technique name: flow cytometry" in build_pick_prompt(
        "Surface and intracellular cytokine staining", _candidates(),
        standard_technique_name="flow cytometry")
    prompt = build_pick_prompt("SIMoA", _candidates())
    assert "Standard technique name: not given" in prompt
    assert "{standard_technique_name}" not in prompt


def test_retrieved_candidates_carry_definition_and_descendants():
    """Every live candidate gets them from the index; the embeddings file has neither field."""
    from app.agent import assay_obi_mapper

    details = assay_obi_mapper._term_details()
    assert details["OBI:0001463"]["n_descendants"] is not None
    assert details["OBI:0001463"]["definition"]


def test_enrich_records_the_pickers_granularity(monkeypatch):
    from app.agent import assay_obi_mapper

    monkeypatch.setattr(assay_obi_mapper, "map_assay_to_obi", lambda name, *a, **k: None if name == "x" else {
        "obi_id": "OBI:0000916", "obi_label": "flow cytometry assay", "resource": "embedding_llm",
        "confidence": 0.6, "granularity": "BROAD"})

    enriched = enrich_assays_with_obi({"intracellular cytokine staining": {}, "x": {}})

    assert enriched["intracellular cytokine staining"]["obi_granularity"] == "BROAD"
    assert enriched["x"]["obi_granularity"] is None


# ── exact hits on terms with children ─────────────────────────────────────────

def test_an_exact_hit_on_a_leaf_term_answers_without_the_picker(monkeypatch):
    """ELISA has no child left in the index (its 53 OBI descendants were pruned), so there is
    nothing more specific to choose and the hit stays free."""
    from app.agent import assay_obi_mapper

    monkeypatch.setattr(assay_obi_mapper, "_embedding_llm_match",
                        lambda *a, **k: pytest.fail("a leaf hit must not reach step 2"))

    mapped = assay_obi_mapper.map_assay_to_obi("ELISA", "ELISA")

    assert mapped["resource"] == "exact_original"
    assert mapped["obi_id"] == "OBI:0000661"


def test_index_children_are_direct_and_inside_the_index():
    from app.agent.assay_obi_mapper import _index_children, _term_ids, _OBI_TERMS_PATH

    children = _index_children()
    allowed = _term_ids(_OBI_TERMS_PATH)
    assert all(p in allowed and set(c) <= allowed for p, c in children.items())
    # RNA sequencing assay -> RNA-seq assay -> bulk RNA-seq assay: direct only.
    assert "OBI:0001271" in children["OBI:0001177"]
    assert "OBI:0003090" not in children["OBI:0001177"]
    assert {"OBI:0003090", "OBI:0002631"} <= set(children["OBI:0001271"])
    assert "OBI:0000661" not in children


def test_every_index_entry_carries_its_is_a_parents():
    """The index holds the graph the mapper walks: direct `is_a` parents, unfiltered, each with
    its label so a reviewer can read the edge without obi.obo. A pruned term can name a parent
    the index does not hold (its IEDB children are not in, and point nowhere)."""
    import json

    from app.agent.assay_obi_mapper import _OBI_TERMS_PATH

    terms = json.loads(_OBI_TERMS_PATH.read_text(encoding="utf-8"))
    assert all(isinstance(t.get("parents"), list) for t in terms)
    by_id = {t["id"]: t for t in terms}
    assert by_id["OBI:0600031"]["parents"] == [  # ELISPOT, obo order
        {"id": "OBI:0001977", "label": "cytometry assay"},
        {"id": "OBI:0003587", "label": "cell culture assay"},
    ]
    assert by_id["OBI:0000661"]["parents"] == [{"id": "OBI:0000443", "label": "analyte assay"}]


def test_index_children_come_from_the_index_not_obi_obo(monkeypatch, tmp_path):
    """With `parents` in the index, the mapper no longer needs obi.obo at run time: pointing
    _OBO_PATH at nothing changes no edge. A terms file without the field still falls back."""
    import json

    from app.agent import assay_obi_mapper as m

    m._index_children.cache_clear()
    with_obo = m._index_children()
    monkeypatch.setattr(m, "_OBO_PATH", tmp_path / "missing.obo")
    m._index_children.cache_clear()
    try:
        assert m._index_children() == with_obo
        assert "OBI:0001271" in m._index_children()["OBI:0001177"]
        # an older index, without the field, has only obi.obo to go on -- and it is gone
        stripped = tmp_path / "old_index.json"
        stripped.write_text(json.dumps([{k: v for k, v in t.items() if k != "parents"}
                                        for t in m._index_entries(m._OBI_TERMS_PATH).values()]))
        assert m._index_children(stripped) == {}
    finally:
        m._index_children.cache_clear()
        m._index_entries.cache_clear()
        m._term_ids.cache_clear()


def test_an_rna_seq_hit_pins_its_children_and_the_picker_can_choose_bulk(monkeypatch):
    from app.agent import assay_obi_mapper

    monkeypatch.setattr(assay_obi_mapper, "_top_k_candidates", lambda *a, **k: [
        {"id": "OBI:0001177", "label": "RNA sequencing assay", "similarity": 0.8}])
    seen = {}

    def fake_pick(assay_name, candidates, **_):
        seen["candidates"] = candidates
        bulk = next(c for c in candidates if c["id"] == "OBI:0003090")
        return {"obi_id": bulk["id"], "obi_label": bulk["label"], "resource": "embedding_llm",
                "confidence": bulk["similarity"], "granularity": "EXACT"}

    monkeypatch.setattr(assay_obi_mapper, "_llm_pick", fake_pick)

    mapped = assay_obi_mapper.map_assay_to_obi("RNA-seq", "RNA sequencing",
                                               sample_type="whole blood in PAXgene")

    pins = {c["id"]: c.get("pin") for c in seen["candidates"]}
    assert seen["candidates"][0]["id"] == "OBI:0001271"
    assert pins["OBI:0001271"] == "exact"
    assert pins["OBI:0003090"] == pins["OBI:0002631"] == "child"
    assert pins["OBI:0001177"] is None  # retrieved, not pinned
    assert mapped == {"obi_id": "OBI:0003090", "obi_label": "bulk RNA-seq assay",
                      "resource": "exact_original_llm", "confidence": "high",
                      "granularity": "EXACT"}


def test_the_exact_hit_stands_when_the_picker_abstains(monkeypatch):
    _no_pick(monkeypatch)

    mapped = map_assay_to_obi("RNA Sequencing", "RNA sequencing")

    assert mapped == {"obi_id": "OBI:0001177", "obi_label": "RNA sequencing assay",
                      "resource": "exact_original_llm", "confidence": "high"}


def test_pinned_candidates_are_labelled_in_the_pick_prompt():
    from app.agent.assay_obi_mapper import _pinned_candidates, build_pick_prompt

    pinned = _pinned_candidates("OBI:0001271")
    prompt = build_pick_prompt("RNA-seq", pinned)

    assert "OBI:0001271 | RNA-seq assay" in prompt
    assert "(exact name match)" in prompt
    assert "single-cell RNA sequencing assay | scRNA-seq" in prompt
    assert "(child of exact name match)" in prompt
    assert "similarity: None" not in prompt
    assert "8. EXACT NAME MATCH" in prompt


def test_an_rna_sequencing_hit_also_pins_its_grandchildren():
    """Bulk and single-cell RNA-seq sit under RNA-seq assay, two levels below the term a paper's
    "RNA Sequencing" hits; only the RNA sequencing family walks that far."""
    from app.agent.assay_obi_mapper import _pinned_candidates

    pins = {c["id"]: c["pin"] for c in _pinned_candidates("OBI:0001177")}

    assert pins["OBI:0001177"] == "exact"
    assert pins["OBI:0001271"] == "child"
    assert pins["OBI:0003090"] == pins["OBI:0002631"] == "grandchild"


def test_other_hits_pin_direct_children_only():
    """microarray assay has a grandchild in the index (genotyping by SNP array, under genotyping
    by array) that must not be pinned."""
    from app.agent.assay_obi_mapper import _index_children, _pinned_candidates

    children = _index_children()
    direct = set(children["OBI:0001985"])
    grand = {g for c in direct for g in children.get(c, ())} - direct
    pinned = {c["id"]: c["pin"] for c in _pinned_candidates("OBI:0001985")}

    assert grand and not grand & set(pinned)
    assert set(pinned) == direct | {"OBI:0001985"}
    assert "grandchild" not in pinned.values()


def test_grandchildren_are_labelled_in_the_pick_prompt():
    from app.agent.assay_obi_mapper import _pinned_candidates, build_pick_prompt

    prompt = build_pick_prompt("RNA Sequencing", _pinned_candidates("OBI:0001177"))

    assert "bulk RNA-seq assay" in prompt
    assert "(grandchild of exact name match)" in prompt


def test_a_flow_read_bead_kit_can_reach_the_flow_based_child():
    """A cytometric bead array hit pins "analyte detection by flow based bead assay", and rule 10
    names the flow-cytometer acquisition that licenses it (LEGENDplex read on a FACS Canto)."""
    from app.agent.assay_obi_mapper import _pinned_candidates, build_pick_prompt

    pins = {c["id"]: c["pin"] for c in _pinned_candidates("OBI:0000920")}
    prompt = build_pick_prompt("Cytokine bead assays", _pinned_candidates("OBI:0000920"),
                               readouts="13 cytokine concentrations; beads acquired on a flow cytometer")

    assert pins["OBI:0003799"] == "child"
    assert "beads were acquired on a flow cytometer" in prompt
    assert "Luminex" in prompt and "stays on the parent" in prompt


def test_platelet_rna_counts_as_bulk_evidence_in_the_pick_prompt():
    from app.agent.assay_obi_mapper import _pinned_candidates, build_pick_prompt

    prompt = build_pick_prompt("RNA-seq", _pinned_candidates("OBI:0001177"),
                               sample_type="platelet-rich plasma (platelets)")

    assert "platelets or platelet-rich plasma" in prompt


def test_enrichment_retrieves_on_every_wording_of_a_canonical_entry(monkeypatch):
    """A registry round 5 already folded carries every wording in `name_in_paper`. On a re-map
    the first is the name and the rest retrieve as aliases; dropping them queried on one of the
    names the fold kept and lost the others."""
    from app.agent import assay_obi_mapper

    seen = {}

    def _capture(name, technique="", **kwargs):
        seen["name"], seen["aliases"] = name, kwargs.get("aliases")
        return None

    monkeypatch.setattr(assay_obi_mapper, "map_assay_to_obi", _capture)

    enrich_assays_with_obi({"enzyme-linked immunosorbent assay": {
        "name_in_paper": ["ELISA", "ELISA kits"], "aliases": ["plate ELISA"]}})

    assert seen["name"] == "ELISA"
    assert seen["aliases"] == ["ELISA kits", "plate ELISA"]


# ── the picker's reply and candidates are kept in the run's trace ────────────

class _PickClient:
    def __init__(self, body: str):
        completions = type("Completions", (), {
            "create": lambda self, **_: type("R", (), {"choices": [
                type("C", (), {"message": type("M", (), {"content": body})()})()]})()})()
        self.chat = type("Chat", (), {"completions": completions})()


def test_llm_pick_records_the_candidate_lines_and_the_reply_under_the_registry_key(monkeypatch):
    from app.agent import assay_obi_mapper, assay_trace
    monkeypatch.setattr(assay_obi_mapper, "OpenAI", lambda **_: _PickClient("2 BROAD"))
    candidates = [{"id": "OBI:1", "label": "x", "similarity": 0.5},
                  {"id": "OBI:2", "label": "y", "similarity": 0.4}]
    trace = assay_trace.start()
    try:
        picked = assay_obi_mapper._llm_pick("Immunofluorescence", candidates,
                                            registry_key="Immunofluorescence (IF)")
    finally:
        assay_trace.stop()

    assert picked["obi_id"] == "OBI:2" and picked["granularity"] == "BROAD"
    record = trace.as_json()["obi"]["Immunofluorescence (IF)"]
    assert record["reply"] == "2 broad"
    assert record["candidates"] == ["1. OBI:1 | x (similarity: 0.5)", "2. OBI:2 | y (similarity: 0.4)"]


def test_enrichment_hands_the_registry_key_to_the_lookup(monkeypatch):
    from app.agent import assay_obi_mapper
    seen = {}
    monkeypatch.setattr(assay_obi_mapper, "map_assay_to_obi",
                        lambda name, technique="", **kw: seen.update(kw) or None)

    enrich_assays_with_obi({"enzyme-linked immunosorbent assay": {"name_in_paper": ["ELISA"]}})

    assert seen["registry_key"] == "enzyme-linked immunosorbent assay"


def test_the_pick_prompt_prefers_broad_to_none():
    from app.agent.assay_obi_mapper import build_pick_prompt
    prompt = build_pick_prompt("PRNT", [{"id": "OBI:1", "label": "x", "similarity": 0.5}])

    assert "PREFER BROAD TO NONE" in prompt


# ── 2026-10-19: reproducibility and diagnostics ────────────────────────────────

class _RecordingClient:
    """A chat client that answers `body` and keeps the kwargs of every call it was made."""

    def __init__(self, body: str):
        self.calls: list[dict] = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                message = type("M", (), {"content": body})()
                return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

        self.chat = type("Chat", (), {"completions": _Completions()})()


_ONE = [{"id": "OBI:1", "label": "x", "similarity": 0.5}]


def test_the_pick_call_is_seeded_like_extraction(monkeypatch):
    """The pick was the largest source of run-to-run change on the 31-paper re-run."""
    from app.agent import assay_obi_mapper
    from app.agent.assay_extractor import EXTRACTION_SEED
    client = _RecordingClient("1 EXACT")
    monkeypatch.setattr(assay_obi_mapper, "OpenAI", lambda **_: client)

    assay_obi_mapper._llm_pick("ELISA", _ONE)

    assert client.calls[0]["seed"] == EXTRACTION_SEED
    assert client.calls[0]["temperature"] == 0


@pytest.mark.parametrize("reply", ["3 EXACT.", "3, EXACT", "3 (EXACT)", "3: EXACT", "3 - exact",
                                   "**3 EXACT**", "3 exact\n"])
def test_punctuation_around_the_granularity_does_not_void_the_pick(reply):
    from app.agent.assay_obi_mapper import parse_pick_reply

    assert parse_pick_reply(reply, 10) == (2, "EXACT")


@pytest.mark.parametrize("reply", ["candidate 3", "3 maybe", "OBI:0000661", "12 EXACT", ""])
def test_a_reply_naming_no_candidate_is_a_failed_call_not_an_abstention(monkeypatch, reply):
    """"none" is a judgement and is reported UNMAPPED; a reply nobody can read is not."""
    from app.agent import assay_obi_mapper
    monkeypatch.setattr(assay_obi_mapper, "OpenAI", lambda **_: _RecordingClient(reply))

    with pytest.raises(assay_obi_mapper.PickReplyError):
        assay_obi_mapper._llm_pick("x", _ONE)


def test_none_is_still_an_abstention(monkeypatch):
    from app.agent import assay_obi_mapper
    monkeypatch.setattr(assay_obi_mapper, "OpenAI", lambda **_: _RecordingClient("None."))

    assert assay_obi_mapper._llm_pick("x", _ONE) is None


def test_an_unreadable_reply_is_reported_as_an_error_not_a_vocabulary_gap(monkeypatch):
    from app.agent import assay_obi_mapper
    monkeypatch.setattr(assay_obi_mapper, "_top_k_candidates", lambda *a, **k: list(_ONE))
    monkeypatch.setattr(assay_obi_mapper, "OpenAI",
                        lambda **_: _RecordingClient("candidate 1 looks right"))

    entry = enrich_assays_with_obi({"XYZZY_unknown": {"name_in_paper": "XYZZY_unknown"}})[
        "XYZZY_unknown"]

    assert entry["resource"] == "error" and entry["obi_id"] is None
    assert "PickReplyError" in entry["obi_error"]
    assert "candidate 1 looks right" in entry["obi_error"]


def test_an_unreadable_reply_on_an_exact_hit_leaves_the_exact_hit_standing(monkeypatch):
    from app.agent import assay_obi_mapper
    monkeypatch.setattr(assay_obi_mapper, "_top_k_candidates", lambda *a, **k: [])
    monkeypatch.setattr(assay_obi_mapper, "OpenAI", lambda **_: _RecordingClient("the first one"))

    mapped = assay_obi_mapper.map_assay_to_obi("RNA-seq", "RNA sequencing")

    assert mapped["resource"] == "exact_original_llm"
    assert mapped["obi_label"] == "RNA-seq assay"


def test_a_label_beats_a_synonym_on_a_shared_key(tmp_path):
    import json
    from app.agent.assay_obi_mapper import _build_lookup
    terms = tmp_path / "terms.json"
    terms.write_text(json.dumps([
        {"id": "OBI:A", "label": "histological assay", "synonyms": ["histopathology"]},
        {"id": "OBI:B", "label": "histopathology assay", "synonyms": []},
    ]), encoding="utf-8")

    lookup = _build_lookup(terms)

    assert lookup["histopathology"]["obi_id"] == "OBI:B"
    assert lookup["histopathology assay"]["obi_id"] == "OBI:B"
    assert lookup["histological"]["obi_id"] == "OBI:A"


def test_lookup_collisions_are_the_known_four():
    """Keys two index terms claim. Pinned so an OBI release that adds one is noticed: for a
    synonym shared by two terms, index order -- not a judgement -- decides which one wins."""
    import json
    from app.agent.assay_obi_mapper import _OBI_TERMS_PATH, _build_lookup, _index_keys
    owners: dict[str, set[str]] = {}
    for term in json.loads(_OBI_TERMS_PATH.read_text(encoding="utf-8")):
        for text in [term["label"], *term.get("synonyms", [])]:
            for key in _index_keys(str(text)):
                owners.setdefault(key, set()).add(term["id"])

    assert {k for k, ids in owners.items() if len(ids) > 1} == {
        "at-iii", "at-iii assay", "histopathology", "lps"}
    assert _build_lookup()["histopathology"]["obi_id"] == "OBI:0002564"


def test_enrichment_keeps_registry_order_whatever_order_the_lookups_finish(monkeypatch):
    import time
    from app.agent import assay_obi_mapper

    def slow_first(name, *args, **kwargs):
        if name == "slow":
            time.sleep(0.05)
        return {"obi_id": f"OBI:{name}", "obi_label": name, "resource": "exact_original",
                "confidence": "high"}

    monkeypatch.setattr(assay_obi_mapper, "map_assay_to_obi", slow_first)
    done: list[tuple[str, int, int]] = []

    enriched = enrich_assays_with_obi({"slow": {}, "fast": {}},
                                      on_done=lambda key, n, total: done.append((key, n, total)))

    assert list(enriched) == ["slow", "fast"]
    assert [d[0] for d in done] == ["fast", "slow"]
    assert [(n, total) for _, n, total in done] == [(1, 2), (2, 2)]


def test_replies_made_on_worker_threads_reach_the_runs_trace(monkeypatch):
    """assay_trace is a ContextVar; a bare thread would not see the active trace."""
    from app.agent import assay_obi_mapper, assay_trace

    def record(name, *args, **kwargs):
        assay_trace.record("obi", kwargs["registry_key"], reply="1 exact")
        return None

    monkeypatch.setattr(assay_obi_mapper, "map_assay_to_obi", record)
    trace = assay_trace.start()
    try:
        enrich_assays_with_obi({"a": {}, "b": {}, "c": {}})
    finally:
        assay_trace.stop()

    assert set(trace.as_json()["obi"]) == {"a", "b", "c"}


def test_a_broken_progress_listener_does_not_cost_the_round(monkeypatch):
    from app.agent import assay_obi_mapper
    monkeypatch.setattr(assay_obi_mapper, "map_assay_to_obi", lambda *a, **k: None)

    def boom(*_):
        raise RuntimeError("listener broke")

    enriched = enrich_assays_with_obi({"a": {}}, on_done=boom)

    assert enriched["a"]["resource"] == "unresolved"


# ── 2026-10-19: OBI neighbours of the top retrieved candidates ─────────────────

def _c(obi_id: str, label: str, similarity: float | None = 0.5, **extra) -> dict:
    return {"id": obi_id, "label": label, "similarity": similarity, **extra}


def test_index_parents_is_the_inverse_of_index_children():
    from app.agent.assay_obi_mapper import _index_children, _index_parents
    children, parents = _index_children(), _index_parents()

    assert all(kid in parents and parent in parents[kid]
               for parent, kids in children.items() for kid in kids)
    assert all(kid in children.get(parent, ()) for kid, ps in parents.items() for parent in ps)
    # CBA's antibody-detection child, the SDY1260 miss, is one edge below it.
    assert "OBI:0003116" in children["OBI:0000920"]


def test_neighbours_of_the_top_retrieved_terms_join_the_list_after_it():
    """The curator's term the 31-paper run never retrieved sat one is_a edge from a top-3
    candidate; the picker can only choose among what it is shown."""
    from app.agent import assay_obi_mapper
    retrieved = [_c("OBI:0000920", "cytometric bead array assay", 0.7),
                 _c("OBI:0000661", "enzyme-linked immunosorbent assay", 0.6)]

    out = assay_obi_mapper._with_neighbours(retrieved)

    assert out[:2] == retrieved
    added = {c["id"]: c for c in out[2:]}
    assert "OBI:0003116" in added                       # child of CBA
    assert added["OBI:0003116"]["pin"] == "child_of"
    assert added["OBI:0003116"]["of"] == 1
    assert added["OBI:0003116"]["similarity"] is None
    assert all(c["id"] not in {"OBI:0000920", "OBI:0000661"} for c in out[2:])
    assert len({c["id"] for c in out}) == len(out)


def test_only_the_first_top_retrieved_terms_anchor_neighbours():
    from app.agent import assay_obi_mapper
    retrieved = [_c(f"OBI:{i}", f"t{i}") for i in range(1, 6)]
    seen = []
    monkeypatch_children = {f"OBI:{i}": (f"OBI:{i}0",) for i in range(1, 6)}
    entries = {f"OBI:{i}0": {"id": f"OBI:{i}0", "label": f"child of t{i}"} for i in range(1, 6)}
    with _patched_graph(assay_obi_mapper, monkeypatch_children, {}, entries):
        out = assay_obi_mapper._with_neighbours(retrieved)
    seen = [c["of"] for c in out[5:]]

    assert seen == [1, 2, 3]


def test_a_term_over_the_child_cap_contributes_no_children_but_still_its_parents():
    from app.agent import assay_obi_mapper
    big = assay_obi_mapper.MAX_NEIGHBOUR_CHILDREN + 1
    children = {"OBI:1": tuple(f"OBI:1{i:02d}" for i in range(big))}
    parents = {"OBI:1": ("OBI:0",)}
    entries = {"OBI:0": {"id": "OBI:0", "label": "parent"},
               **{k: {"id": k, "label": k} for k in children["OBI:1"]}}
    with _patched_graph(assay_obi_mapper, children, parents, entries):
        out = assay_obi_mapper._with_neighbours([_c("OBI:1", "big family")])

    assert [c["id"] for c in out] == ["OBI:1", "OBI:0"]
    assert out[1]["pin"] == "parent_of" and out[1]["of"] == 1


def test_pinned_rows_are_not_anchors_and_keep_leading_the_list():
    from app.agent import assay_obi_mapper
    pinned_hit = _c("OBI:9", "exact hit", None, pin="exact")
    retrieved = [_c("OBI:1", "a"), _c("OBI:2", "b")]
    children = {"OBI:9": ("OBI:90",), "OBI:1": ("OBI:10",)}
    entries = {"OBI:90": {"id": "OBI:90", "label": "kid of hit"}, "OBI:10": {"id": "OBI:10", "label": "kid of a"}}
    with _patched_graph(assay_obi_mapper, children, {}, entries):
        out = assay_obi_mapper._with_neighbours([pinned_hit, *retrieved])

    assert out[0] is pinned_hit
    assert [c["id"] for c in out[3:]] == ["OBI:10"]
    assert out[3]["of"] == 2          # "a" is candidate 2 in the list the picker sees


def test_neighbour_rows_are_labelled_by_their_anchor_in_the_prompt():
    from app.agent.assay_obi_mapper import build_pick_prompt
    prompt = build_pick_prompt("x", [_c("OBI:1", "a"), _c("OBI:10", "kid", None, pin="child_of", of=1),
                                     _c("OBI:0", "mum", None, pin="parent_of", of=1)])

    assert "2. OBI:10 | kid (child of candidate 1)" in prompt
    assert "3. OBI:0 | mum (parent of candidate 1)" in prompt
    assert 'marked "child of\ncandidate N" or "parent of candidate N"' in prompt
    assert "Entries marked \"child of candidate N\" / \"parent of candidate N\" are the OBI neighbours" in prompt


def test_a_pick_only_a_neighbour_could_reach_is_attributed_to_the_expansion(monkeypatch):
    from app.agent import assay_obi_mapper
    monkeypatch.setattr(assay_obi_mapper, "_top_k_candidates",
                        lambda *a, **k: [_c("OBI:0000920", "cytometric bead array assay", 0.7)])

    def pick_child(assay_name, candidates, **_):
        child = next(c for c in candidates if c["id"] == "OBI:0003116")
        return {"obi_id": child["id"], "obi_label": child["label"], "resource": "embedding_llm",
                "confidence": child["similarity"], "granularity": "EXACT"}

    monkeypatch.setattr(assay_obi_mapper, "_llm_pick", pick_child)

    mapped = assay_obi_mapper.map_assay_to_obi("anti-Diphtheria IgG by Luminex", "Luminex")

    assert mapped["obi_id"] == "OBI:0003116"
    assert mapped["resource"] == "embedding_llm_neighbour"


def test_a_pick_on_a_retrieved_term_keeps_its_attribution(monkeypatch):
    from app.agent import assay_obi_mapper
    monkeypatch.setattr(assay_obi_mapper, "_top_k_candidates",
                        lambda *a, **k: [_c("OBI:0000920", "cytometric bead array assay", 0.7)])
    monkeypatch.setattr(assay_obi_mapper, "_llm_pick",
                        lambda name, candidates, **_: {"obi_id": "OBI:0000920", "obi_label": "cba",
                                                      "resource": "embedding_llm", "confidence": 0.7})

    assert assay_obi_mapper.map_assay_to_obi("Luminex panel", "Luminex")["resource"] == "embedding_llm"


class _patched_graph:
    """Swap the index graph for a small one, for tests that need a shape the real index lacks."""

    def __init__(self, module, children, parents, entries):
        self.module, self.children, self.parents, self.entries = module, children, parents, entries

    def __enter__(self):
        m = self.module
        self.saved = (m._index_children, m._index_parents, m._index_entries, m._term_details)
        m._index_children = lambda terms_path=None: self.children
        m._index_parents = lambda terms_path=None: self.parents
        m._index_entries = lambda terms_path=None: self.entries
        m._term_details = lambda terms_path=None: {}
        return self

    def __exit__(self, *exc):
        (self.module._index_children, self.module._index_parents,
         self.module._index_entries, self.module._term_details) = self.saved


# ── 2026-10-20: tree descent ──────────────────────────────────────────────────
#
# A six-term vocabulary with the shape the walk has to handle: two roots (one a leaf), a
# branch two deep, and a term with children under an exact-match label.
#
#   R1 "imaging assay" (root, leaf)
#   R2 "sequencing assay" (root)
#     └─ S1 "RNA-seq" ──┬─ S1a "bulk RNA-seq assay"
#                       └─ S1b "single-cell RNA sequencing assay"
#     └─ S2 "DNA sequencing assay" (leaf)

_WALK_TERMS = [
    {"id": "OBI:R1", "label": "imaging assay", "synonyms": [], "definition": "Makes a picture.",
     "n_descendants": 0, "parents": []},
    {"id": "OBI:R2", "label": "sequencing assay", "synonyms": ["seq"],
     "definition": "Determines a sequence.", "n_descendants": 3, "parents": []},
    {"id": "OBI:S1", "label": "RNA-seq", "synonyms": ["RNA sequencing"],
     "definition": "Sequences RNA.", "n_descendants": 2, "parents": [{"id": "OBI:R2"}]},
    {"id": "OBI:S1a", "label": "bulk RNA-seq assay", "synonyms": [],
     "definition": "Sequences pooled RNA.", "n_descendants": 0, "parents": [{"id": "OBI:S1"}]},
    {"id": "OBI:S1b", "label": "single-cell RNA sequencing assay", "synonyms": ["scRNA-seq"],
     "definition": "Sequences RNA per cell.", "n_descendants": 0, "parents": [{"id": "OBI:S1"}]},
    {"id": "OBI:S2", "label": "DNA sequencing assay", "synonyms": [],
     "definition": "Sequences DNA.", "n_descendants": 0, "parents": [{"id": "OBI:R2"}]},
]


@pytest.fixture
def walk_terms(tmp_path, monkeypatch):
    """The vocabulary above as a terms file, with the descent strategy selected and every
    cache the walk reads cleared on the way out."""
    import json
    from app.agent import assay_obi_mapper as m
    path = tmp_path / "walk_terms.json"
    path.write_text(json.dumps(_WALK_TERMS), encoding="utf-8")
    monkeypatch.setattr(settings, "OBI_MAPPING_STRATEGY", "descend")
    yield path
    for cached in (m._term_ids, m._build_lookup, m._index_entries, m._index_children,
                   m._index_parents, m._index_roots, m._term_details):
        cached.cache_clear()


class _WalkClient:
    """A chat client that answers the scripted replies in order and keeps every prompt."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.prompts: list[str] = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.prompts.append(kwargs["messages"][0]["content"])
                body = outer.replies.pop(0)
                message = type("M", (), {"content": body})()
                return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

        self.chat = type("Chat", (), {"completions": _Completions()})()


def _walk(monkeypatch, *replies: str) -> _WalkClient:
    from app.agent import assay_obi_mapper
    client = _WalkClient(*replies)
    monkeypatch.setattr(assay_obi_mapper, "OpenAI", lambda **_: client)
    return client


def test_the_default_strategy_is_embedding_until_the_descent_is_benchmarked():
    """The descent is opt-in: it has no benchmark comparison yet, its first level is a 96-way
    choice nothing below can recover from, and it spends 1-2 more chat calls per unmatched
    assay. The default moves only on data (see the module docstring)."""
    from app.config import Settings

    assert Settings.model_fields["OBI_MAPPING_STRATEGY"].default == "embedding"


def test_the_roots_are_the_parentless_generic_terms(walk_terms):
    from app.agent.assay_obi_mapper import _index_roots

    assert _index_roots(walk_terms) == ("OBI:R1", "OBI:R2")


def test_the_live_index_has_the_measured_ninety_six_roots():
    """The number the module docstring and the prompt's cost reasoning rest on."""
    from app.agent.assay_obi_mapper import _index_roots, _index_children

    roots = _index_roots()
    assert len(roots) == 96
    assert "OBI:0000443" in roots                      # analyte assay, 79 children
    assert len(_index_children()["OBI:0000443"]) == 79


@pytest.mark.parametrize("reply, expected", [
    ("3", ("pick", 2, None)),
    ("3 exact", ("pick", 2, "EXACT")),
    ("#2, (broad).", ("pick", 1, "BROAD")),
    ("STOP EXACT", ("stop", None, "EXACT")),
    ("stop broad", ("stop", None, "BROAD")),
    ("stop", ("stop", None, None)),          # the term is unambiguous; granularity is diagnostic
    ("none", ("none", None, None)),
])
def test_the_descend_reply_grammar(reply, expected):
    from app.agent.assay_obi_mapper import parse_descend_reply

    assert parse_descend_reply(reply, 5) == expected


@pytest.mark.parametrize("reply", ["OBI:0000916", "3 or 5", "7", "maybe 2", "stop here"])
def test_a_descend_reply_outside_the_grammar_is_a_failed_call(reply):
    """An unreadable reply, or a child number that is not listed, is reported like a failed
    call, never read as an abstention or a step."""
    from app.agent.assay_obi_mapper import PickReplyError, parse_descend_reply

    with pytest.raises(PickReplyError):
        parse_descend_reply(reply, 5)


def test_a_walk_from_the_root_steps_down_until_a_granularity_ends_it(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper, assay_trace
    client = _walk(monkeypatch, "2", "1", "2 EXACT")
    trace = assay_trace.start()
    try:
        mapped = assay_obi_mapper.map_assay_to_obi(
            "10x Chromium transcriptomes", "single-cell RNA sequencing", terms_path=walk_terms,
            registry_key="10x", aliases=["scRNA-seq"])
    finally:
        assay_trace.stop()

    assert mapped["obi_id"] == "OBI:S1b" and mapped["obi_label"] == "single-cell RNA sequencing assay"
    assert mapped["resource"] == "descend_llm"
    assert mapped["confidence"] is None
    assert mapped["granularity"] == "EXACT"
    assert mapped["path"] == ["OBI:R2", "OBI:S1", "OBI:S1b"]
    assert mapped["calls"] == 3 and mapped["backoff"] is False
    # The root prompt lists the two roots; the next the chosen root's two children.
    assert "1. OBI:R1 | imaging assay" in client.prompts[0]
    assert "children in vocabulary: 2" in client.prompts[0]
    assert "OBI:0000070 | assay (the root" in client.prompts[0]
    assert "1. OBI:S1 | RNA-seq | RNA sequencing" in client.prompts[1]
    assert "OBI:R2 | sequencing assay | seq | definition: Determines a sequence." in client.prompts[1]
    # One trace record for the whole walk, every level in it.
    record = trace.as_json()["obi"]["10x"]
    assert record["strategy"] == "descend" and record["path"] == mapped["path"]
    assert [(lvl["node"], lvl["reply"]) for lvl in record["levels"]] == [
        ("OBI:0000070", "2"), ("OBI:R2", "1"), ("OBI:S1", "2 exact")]
    assert record["levels"][1]["candidates"][1] == (
        "2. OBI:S2 | DNA sequencing assay | definition: Sequences DNA. | descendants: 0"
        " | children in vocabulary: 0")


def test_stepping_into_a_leaf_ends_the_walk_without_another_call(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    client = _walk(monkeypatch, "2", "2")

    mapped = assay_obi_mapper.map_assay_to_obi("whole genome sequencing", "", terms_path=walk_terms)

    assert mapped["obi_id"] == "OBI:S2"
    assert mapped["calls"] == 2 and not client.replies
    assert mapped["granularity"] is None      # a bare number carries none, as before


def test_stop_ends_the_walk_on_the_current_term(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    _walk(monkeypatch, "2", "STOP BROAD")

    mapped = assay_obi_mapper.map_assay_to_obi("nanopore sequencing", "", terms_path=walk_terms)

    assert mapped["obi_id"] == "OBI:R2" and mapped["granularity"] == "BROAD"
    assert mapped["path"] == ["OBI:R2"] and mapped["backoff"] is False


def test_none_below_the_root_backs_off_onto_the_current_term_as_broad(walk_terms, monkeypatch):
    """"none" at a level below the root contradicts the step that entered the term; the term
    stands, BROAD, and the walk is marked so a run that does this often can be found."""
    from app.agent import assay_obi_mapper
    _walk(monkeypatch, "2", "none")

    mapped = assay_obi_mapper.map_assay_to_obi("nanopore sequencing", "", terms_path=walk_terms)

    assert mapped["obi_id"] == "OBI:R2" and mapped["granularity"] == "BROAD"
    assert mapped["backoff"] is True and mapped["calls"] == 2


def test_none_at_the_root_is_unresolved_and_so_is_stop(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    _walk(monkeypatch, "none", "STOP EXACT")

    assert assay_obi_mapper.map_assay_to_obi("bespoke readout", "", terms_path=walk_terms) is None
    assert assay_obi_mapper.map_assay_to_obi("bespoke readout", "", terms_path=walk_terms) is None


def test_an_exact_hit_with_children_is_where_the_walk_starts(walk_terms, monkeypatch):
    """"RNA-seq" is a label with children, so the first level shown is its children -- not the
    96 roots -- and the result keeps the exact-hit attribution and confidence."""
    from app.agent import assay_obi_mapper
    client = _walk(monkeypatch, "1 EXACT")

    mapped = assay_obi_mapper.map_assay_to_obi("RNA-seq", "RNA sequencing", terms_path=walk_terms,
                                               sample_type="PAXgene whole blood")

    assert mapped["obi_id"] == "OBI:S1a"
    assert mapped["resource"] == "exact_original_llm" and mapped["confidence"] == "high"
    assert mapped["path"] == ["OBI:S1", "OBI:S1a"] and mapped["calls"] == 1
    assert len(client.prompts) == 1
    assert "OBI:S1 | RNA-seq | RNA sequencing | definition: Sequences RNA." in client.prompts[0]
    assert "OBI:R1" not in client.prompts[0]


def test_an_exact_hit_stands_when_its_first_level_abstains_or_cannot_be_read(walk_terms,
                                                                            monkeypatch):
    from app.agent import assay_obi_mapper
    _walk(monkeypatch, "none", "3 or 5")

    backed_off = assay_obi_mapper.map_assay_to_obi("RNA-seq", "", terms_path=walk_terms)
    unreadable = assay_obi_mapper.map_assay_to_obi("RNA-seq", "", terms_path=walk_terms)

    assert backed_off["obi_id"] == "OBI:S1" and backed_off["granularity"] == "BROAD"
    assert backed_off["resource"] == "exact_original_llm" and backed_off["backoff"] is True
    assert unreadable == {"obi_id": "OBI:S1", "obi_label": "RNA-seq",
                          "resource": "exact_original_llm", "confidence": "high"}


def test_an_unreadable_reply_with_no_exact_hit_propagates_with_the_walk_recorded(walk_terms,
                                                                                 monkeypatch):
    from app.agent import assay_obi_mapper, assay_trace
    _walk(monkeypatch, "2", "which one?")
    trace = assay_trace.start()
    try:
        with pytest.raises(assay_obi_mapper.PickReplyError):
            assay_obi_mapper.map_assay_to_obi("nanopore", "", terms_path=walk_terms,
                                              registry_key="nanopore")
    finally:
        assay_trace.stop()

    record = trace.as_json()["obi"]["nanopore"]
    assert [lvl["reply"] for lvl in record["levels"]] == ["2", "which one?"]


def test_an_exact_hit_on_a_leaf_still_answers_for_free(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    client = _walk(monkeypatch)

    mapped = assay_obi_mapper.map_assay_to_obi("imaging assay", "", terms_path=walk_terms)

    assert mapped == {"obi_id": "OBI:R1", "obi_label": "imaging assay",
                      "resource": "exact_original", "confidence": "high"}
    assert not client.prompts


def test_the_walk_stops_where_it_is_after_the_level_limit(walk_terms, monkeypatch):
    """A reply that keeps naming a child with children cannot run forever; the walk ends
    where it is, BROAD, marked as a back-off."""
    from app.agent import assay_obi_mapper
    monkeypatch.setattr(assay_obi_mapper, "MAX_DESCENT_LEVELS", 1)
    _walk(monkeypatch, "2", "1")

    mapped = assay_obi_mapper.map_assay_to_obi("nanopore", "", terms_path=walk_terms)

    assert mapped["obi_id"] == "OBI:R2" and mapped["granularity"] == "BROAD"
    assert mapped["backoff"] is True and mapped["calls"] == 1


def test_the_embedding_strategy_is_still_selectable(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    seen = []
    monkeypatch.setattr(assay_obi_mapper, "_embedding_llm_match",
                        lambda query, **kw: seen.append(query) or None)
    monkeypatch.setattr(assay_obi_mapper, "_llm_descend_pick",
                        lambda *a, **k: pytest.fail("the walk ran under the embedding strategy"))

    monkeypatch.setattr(settings, "OBI_MAPPING_STRATEGY", "embedding")
    assert assay_obi_mapper.map_assay_to_obi("SIMoA", "", terms_path=walk_terms) is None
    assert seen == ["SIMoA"]
    # The argument outranks the setting.
    monkeypatch.setattr(settings, "OBI_MAPPING_STRATEGY", "descend")
    assay_obi_mapper.map_assay_to_obi("SIMoA", "", terms_path=walk_terms, strategy="embedding")
    assert seen == ["SIMoA", "SIMoA"]


def test_an_unknown_strategy_is_refused_before_anything_is_spent(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    monkeypatch.setattr(settings, "OBI_MAPPING_STRATEGY", "bm25")

    with pytest.raises(ValueError, match="OBI_MAPPING_STRATEGY"):
        assay_obi_mapper.map_assay_to_obi("SIMoA", "", terms_path=walk_terms)


def test_the_descend_call_is_seeded_at_temperature_zero_on_the_configured_model(walk_terms,
                                                                               monkeypatch):
    from app.agent import assay_obi_mapper
    from app.agent.assay_extractor import EXTRACTION_SEED
    client = _RecordingClient("1 EXACT")
    monkeypatch.setattr(assay_obi_mapper, "OpenAI", lambda **_: client)

    assay_obi_mapper.map_assay_to_obi("RNA-seq", "", terms_path=walk_terms, model="m-test")

    assert client.calls[0]["seed"] == EXTRACTION_SEED
    assert client.calls[0]["temperature"] == 0
    assert client.calls[0]["model"] == "m-test"


def test_enrichment_writes_the_walk_beside_the_term(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    _walk(monkeypatch, "2", "2")

    out = enrich_assays_with_obi({"WGS": {"name_in_paper": ["WGS"], "confidence": "high"}},
                                 terms_path=walk_terms)

    entry = out["WGS"]
    assert entry["obi_id"] == "OBI:S2" and entry["resource"] == "descend_llm"
    assert entry["obi_path"] == ["OBI:R2", "OBI:S2"]
    assert entry["obi_calls"] == 2 and entry["obi_backoff"] is False
    assert entry["obi_confidence"] is None
    assert entry["confidence"] == "high"      # the extraction confidence is untouched


def test_the_descend_prompt_carries_the_record_and_every_legal_reply(walk_terms):
    from app.agent.assay_obi_mapper import _descend_candidates, build_descend_prompt

    prompt = build_descend_prompt(
        "ICS", None, _descend_candidates(["OBI:R1", "OBI:R2"], walk_terms),
        sample_type="PBMC", readouts="IFN-g+ CD8 T cells", aliases=["intracellular staining"],
        standard_technique_name="flow cytometry")

    assert 'Assay name from paper: "ICS"' in prompt
    assert "Also called in the paper: intracellular staining" in prompt
    assert "Standard technique name: flow cytometry" in prompt
    assert "Sample type: PBMC" in prompt and "Readouts: IFN-g+ CD8 T cells" in prompt
    for form in ("N EXACT", "N BROAD", "STOP EXACT", "STOP BROAD", "none"):
        assert form in prompt


def test_the_root_prompt_over_the_live_index_fits_one_call():
    """Ninety-six candidate lines, each capped at four synonyms and 300 definition
    characters: the one level every unmatched assay pays for has to stay a single prompt."""
    from app.agent.assay_obi_mapper import _descend_candidates, _index_roots, build_descend_prompt

    prompt = build_descend_prompt("x", None, _descend_candidates(_index_roots()))

    assert prompt.count("\n") < 300
    assert len(prompt) < 40_000


# ── 2026-10-21: hybrid -- the embedding pick, then a descent from it ───────────

def _pick(obi_id: str, label: str, granularity: str | None = "EXACT") -> dict:
    return {"obi_id": obi_id, "obi_label": label, "resource": "embedding_llm",
            "confidence": 0.61, "granularity": granularity}


def _hybrid(monkeypatch, pick: dict | None, *replies: str) -> tuple[list, _WalkClient]:
    """Stub step 2's embedding pick and script the walk; returns (pick kwargs seen, client)."""
    from app.agent import assay_obi_mapper
    seen = []
    monkeypatch.setattr(assay_obi_mapper, "_embedding_llm_match",
                        lambda query, **kw: seen.append((query, kw)) or pick)
    monkeypatch.setattr(settings, "OBI_MAPPING_STRATEGY", "hybrid")
    return seen, _walk(monkeypatch, *replies)


def test_hybrid_descends_from_the_pick_and_attributes_a_move(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper, assay_trace
    seen, client = _hybrid(monkeypatch, _pick("OBI:S1", "RNA-seq", "BROAD"), "2 EXACT")
    trace = assay_trace.start()
    try:
        mapped = assay_obi_mapper.map_assay_to_obi(
            "10x transcriptomes", "single-cell RNA sequencing", terms_path=walk_terms,
            registry_key="10x", aliases=["scRNA-seq"])
    finally:
        assay_trace.stop()

    assert mapped["obi_id"] == "OBI:S1b" and mapped["resource"] == "embedding_llm_descended"
    assert mapped["confidence"] == 0.61          # the pick's score is kept
    assert mapped["granularity"] == "EXACT"
    assert mapped["path"] == ["OBI:S1", "OBI:S1b"]
    assert mapped["calls"] == 3 + 1              # technique query differs from the name: 3, plus the walk
    assert len(client.prompts) == 1 and "OBI:S1 | RNA-seq | RNA sequencing" in client.prompts[0]
    # the walk is recorded beside the pick, not over it
    assert "10x" in trace.as_json()["obi_descend"]
    assert trace.as_json()["obi_descend"]["10x"]["path"] == ["OBI:S1", "OBI:S1b"]


def test_hybrid_spends_nothing_on_a_pick_that_is_a_leaf(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    _, client = _hybrid(monkeypatch, _pick("OBI:S1a", "bulk RNA-seq assay"))

    mapped = assay_obi_mapper.map_assay_to_obi("pooled RNA sequencing", "", terms_path=walk_terms)

    assert mapped["obi_id"] == "OBI:S1a" and mapped["resource"] == "embedding_llm"
    assert mapped["path"] == ["OBI:S1a"] and mapped["calls"] == 2 and mapped["backoff"] is False
    assert not client.prompts


def test_hybrid_keeps_the_pick_when_the_walk_stops_on_it(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    _hybrid(monkeypatch, _pick("OBI:S1", "RNA-seq", None), "STOP BROAD")

    mapped = assay_obi_mapper.map_assay_to_obi("RNA sequencing of sorted cells", "", terms_path=walk_terms)

    assert mapped["obi_id"] == "OBI:S1" and mapped["resource"] == "embedding_llm"
    assert mapped["granularity"] == "BROAD"      # the walk's call, more informed than the pick's
    assert mapped["path"] == ["OBI:S1"] and mapped["calls"] == 3


def test_hybrid_keeps_the_pick_when_the_walk_cannot_be_read(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    _hybrid(monkeypatch, _pick("OBI:S1", "RNA-seq"), "either of them")

    mapped = assay_obi_mapper.map_assay_to_obi("RNA-seq data", "", terms_path=walk_terms)

    assert mapped["obi_id"] == "OBI:S1" and mapped["resource"] == "embedding_llm"
    assert mapped["calls"] == 3 and mapped["descend_error"].startswith("PickReplyError")


def test_hybrid_does_not_walk_when_the_picker_abstained(walk_terms, monkeypatch):
    from app.agent import assay_obi_mapper
    _, client = _hybrid(monkeypatch, None)

    assert assay_obi_mapper.map_assay_to_obi("bespoke readout", "", terms_path=walk_terms) is None
    assert not client.prompts


def test_hybrid_still_runs_the_embedding_step_with_the_exact_hit_pinned(walk_terms, monkeypatch):
    """Step 1 and the embedding step are untouched: an exact hit with children is pinned
    into the pick as before, and the walk then starts from whatever the picker chose."""
    from app.agent import assay_obi_mapper
    seen, _ = _hybrid(monkeypatch, _pick("OBI:S1a", "bulk RNA-seq assay"))

    assay_obi_mapper.map_assay_to_obi("RNA-seq", "", terms_path=walk_terms)

    (query, kwargs), = seen
    assert query == "RNA-seq" and [p["id"] for p in kwargs["pinned"]] == ["OBI:S1", "OBI:S1a", "OBI:S1b"]


def test_enrichment_writes_the_hybrid_walk_beside_the_term(walk_terms, monkeypatch):
    _hybrid(monkeypatch, _pick("OBI:S1", "RNA-seq"), "1 BROAD")

    out = enrich_assays_with_obi({"RNA-seq": {"name_in_paper": ["RNA-seq"]}}, terms_path=walk_terms)

    entry = out["RNA-seq"]
    assert entry["obi_id"] == "OBI:S1a" and entry["resource"] == "embedding_llm_descended"
    assert entry["obi_path"] == ["OBI:S1", "OBI:S1a"] and entry["obi_calls"] == 3
    assert entry["obi_confidence"] == 0.61 and entry["obi_granularity"] == "BROAD"
