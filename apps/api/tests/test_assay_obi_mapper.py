from app.agent.assay_obi_mapper import enrich_assays_with_obi, map_assay_to_obi


def test_exact_original_match():
    mapped = map_assay_to_obi("ELISA", "ELISA")

    assert mapped["obi_id"] == "OBI:0000661"
    assert mapped["resource"] == "exact_original"
    assert mapped["confidence"] == "high"


def test_ontology_synonym_maps_prompt_canonical_names():
    assert map_assay_to_obi("CyTOF", "CyTOF")["obi_id"] == "OBI:0002115"
    assert map_assay_to_obi("CITE-seq", "CITE-seq")["obi_id"] == "OBI:0003788"
    assert map_assay_to_obi("Olink", "Olink")["obi_id"] == "OBI:0003112"


def test_exact_match_confidence_is_always_high():
    original = map_assay_to_obi("ELISA", "ELISA")
    assert original["confidence"] == "high"
    assert original["resource"] == "exact_original"


def test_the_normalized_name_is_an_exact_match_key_of_its_own(monkeypatch):
    """Step 1b. Replaces test_the_normalized_name_is_never_tried_as_a_lookup_key.

    That test pinned the opposite rule, and it was right about the round it was written for:
    the old normalization was *lexical* (strip a trailing " assay") and earned nothing. This
    field holds an LLM's judgement of which technique the assay is, and looking it up takes the
    step-1 hit rate over the 171 curated rows of all_assays_full.json from 39% to 62%.

    "enzyme-linked immunosorbent assay" is a verbatim OBI label, so a paper name the vocabulary
    has never heard of still resolves through it -- without reaching the paid round at all.
    """
    from app.agent import assay_obi_mapper
    _no_step3(monkeypatch)

    mapped = assay_obi_mapper.map_assay_to_obi(
        "XYZZY_unknown", "enzyme-linked immunosorbent assay")

    assert mapped["obi_id"] == "OBI:0000661"
    assert mapped["resource"] == "exact_normalized_llm"
    assert mapped["confidence"] == "high"


def test_the_normalized_name_reaches_flow_cytometry_for_a_staining_section(monkeypatch):
    """The row this whole change exists for.

    The paper calls its assay "Surface and intracellular cytokine staining" -- a protocol
    section heading. Against that string OBI:0000916 ranks 44th of 700, outside TOP_K, so the
    picker never saw it and chose `immuno staining assay`. The curator gold files
    (data/benchmark_assay/SDY2189_*.json, SDY1364_*.json) both say flow cytometry assay.

    Normalized to the technique, it is an exact match: `_index_keys` strips the trailing
    " assay" from the label, so "flow cytometry" is a key. No embedding, no LLM call.
    """
    from app.agent import assay_obi_mapper
    _no_step3(monkeypatch)

    mapped = assay_obi_mapper.map_assay_to_obi(
        "Surface and intracellular cytokine staining", "flow cytometry")

    assert mapped["obi_id"] == "OBI:0000916"
    assert mapped["obi_label"] == "flow cytometry assay"
    assert mapped["resource"] == "exact_normalized_llm"


def test_the_paper_name_wins_when_both_names_exact_match(monkeypatch):
    """Deriving cannot outrank the source.

    OBI carries `RNA-seq assay` and `RNA sequencing assay` as separate live terms, and this is
    the only disagreement among the 171 curated rows: the paper's "RNA-seq" hits the first, its
    normalization "RNA sequencing" the second. The paper's own wording is also the better
    answer here, which is what makes step 1a-before-1b the right order rather than a coin toss.
    """
    from app.agent import assay_obi_mapper
    _no_step3(monkeypatch)

    mapped = assay_obi_mapper.map_assay_to_obi("RNA-seq", "RNA sequencing")

    assert mapped["resource"] == "exact_original"
    assert mapped["obi_label"] == "RNA-seq assay"


def test_an_absent_normalized_name_leaves_step_1_exactly_as_it_was(monkeypatch):
    """The 44 registries on disk predate the field, and registry_from_claims cannot supply it.

    An empty normalized name must make step 1b a no-op rather than matching something -- an
    empty lookup key resolving to any term would silently remap every legacy entry.
    """
    from app.agent import assay_obi_mapper
    _no_step3(monkeypatch)

    assert assay_obi_mapper.map_assay_to_obi("XYZZY_unknown", "") is None
    assert assay_obi_mapper.map_assay_to_obi("XYZZY_unknown", "   ") is None


def test_enrich_assays_preserves_registry_fields():
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


def test_step3_retrieves_on_the_normalized_name_but_shows_the_llm_the_paper_name(monkeypatch):
    """Normalizing can delete the detail that separates a parent OBI term from its child.

    "ImmunoChip array" normalizes to "Genome-wide SNP genotyping", which drops the word
    "array" — and with it the evidence for `genotyping by SNP array assay` over plain
    `genotyping assay`. The normalized name is still the better retrieval query (the
    paper's own wording pulls ChIP-chip terms on the "Chip" substring), so the two roles
    have to be split: retrieve on one, show the other.
    """
    from app.agent import assay_obi_mapper

    seen = {}

    def fake_top_k(query, k=10, allowed_ids=None):
        seen["query"] = query
        return [{"id": "OBI:0002031", "label": "genotyping by SNP array assay", "similarity": 0.67}]

    def fake_llm_pick(assay_name, candidates, sample_type="", readouts="", **_):
        seen["shown"] = assay_name
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
    assert "ImmunoChip array" in seen["shown"]
    assert "Genome-wide SNP genotyping" in seen["shown"]


def test_step3_shows_one_name_when_normalization_changed_nothing(monkeypatch):
    """No parenthetical when the two names are the same — it would just be noise."""
    from app.agent import assay_obi_mapper

    seen = {}

    def fake_llm_pick(assay_name, candidates, sample_type="", readouts="", **_):
        seen["shown"] = assay_name
        return None

    monkeypatch.setattr(
        assay_obi_mapper,
        "_top_k_candidates",
        lambda query, k=10, allowed_ids=None: [{"id": "OBI:1", "label": "x", "similarity": 0.5}],
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


def test_filter_still_guards_an_unpruned_vocabulary():
    """The default vocabulary is pre-pruned, so the load-time filter has nothing to do there.

    It still has to work, because --terms lets a caller point the mapper at any term list —
    including the unpruned original kept alongside it for reference.
    """
    from app.agent.assay_obi_mapper import _OBI_DIR, _term_ids

    unpruned = _OBI_DIR / "obi_assay_terms_full.json"
    assert unpruned.exists(), "reference copy of the unfiltered vocabulary is missing"

    _term_ids.cache_clear()
    ids = _term_ids(unpruned)

    assert "OBI:1110059" not in ids  # filtered out of the raw list, not merely absent from it
    assert "OBI:0600031" in ids

    # The live index is a *subset* of the label-filtered full list, not an equal-sized twin: on
    # top of the compositional filter it is also domain-pruned (scripts/prune_obi_domain.py),
    # which no label regex can express. Subset is the property worth guarding — a domain prune
    # only ever removes.
    live = _term_ids(_OBI_DIR / "obi_generic_index.json")
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
    assert all(assay_obi_mapper._is_generic_assay_label(c["label"]) for c in candidates)


# ── Extraction confidence vs OBI confidence ───────────────────────────────────

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

    scripts/map_assays_to_obi.py, data/claims/all_assays_full_OBI.json and the UI were already
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
    """enrich_assays_with_obi used to pass the registry key in as normalized_name."""
    from app.agent import assay_obi_mapper
    _no_step3(monkeypatch)

    enriched = enrich_assays_with_obi({"Flow Cytometry Analysis": {"sample_type": "PBMCs"}})

    assert enriched["Flow Cytometry Analysis"]["obi_id"] is None
    assert enriched["Flow Cytometry Analysis"]["resource"] == "unresolved"
    # The field is no longer written at all: it only ever echoed the key back.
    assert "normalized_name" not in enriched["Flow Cytometry Analysis"]


def test_the_paper_name_is_what_step2_queries_and_shows(monkeypatch):
    """With no normalized name in play, retrieval query and display name are both the raw name."""
    from app.agent import assay_obi_mapper

    seen = {}

    monkeypatch.setattr(
        assay_obi_mapper,
        "_top_k_candidates",
        lambda query, k=10, allowed_ids=None: (
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

    Measured over the 101 curated pairs that reach this round, the normalized name gives a
    better top-1 on 52% of them and a worse one on 32% -- "hemagglutination inhibition (HAI)
    assays" scores 0.809 against `viral hemagglutination inhibition assay` where its terse
    normalization scores 0.658. Choosing either one alone trades one set of failures for
    another, so both are retrieved and merged.
    """
    from app.agent import assay_obi_mapper

    queries = []

    monkeypatch.setattr(
        assay_obi_mapper, "_top_k_candidates",
        lambda query, k=10, allowed_ids=None: (
            queries.append(query), [{"id": "OBI:1", "label": "x", "similarity": 0.5}])[1],
    )
    monkeypatch.setattr(
        assay_obi_mapper, "_llm_pick",
        lambda assay_name, candidates, sample_type="", readouts="", **_: None,
    )

    assay_obi_mapper.map_assay_to_obi("ImmunoChip array", "Genome-wide SNP genotyping")

    assert queries == ["ImmunoChip array", "Genome-wide SNP genotyping"]


def test_step2_retrieves_once_when_the_two_names_agree(monkeypatch):
    """A normalization that changed nothing must not buy a second embedding call."""
    from app.agent import assay_obi_mapper

    queries = []

    monkeypatch.setattr(
        assay_obi_mapper, "_top_k_candidates",
        lambda query, k=10, allowed_ids=None: (
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


def test_a_term_only_the_normalized_query_could_reach_is_attributed_to_it(monkeypatch):
    """Otherwise a benchmark run cannot tell whether normalization earned its keep in step 2.

    A term present in the paper-name pool stays plain `embedding_llm` even when the normalized
    query also found it -- riding along is not the same as making the difference.
    """
    from app.agent import assay_obi_mapper

    def fake_top_k(query, k=10, allowed_ids=None):
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
        lambda query, k=10, allowed_ids=None: [
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
    """The model still judges by the paper's own wording; the normalization is context.

    Normalizing can delete the detail that separates a parent OBI term from its child --
    "ImmunoChip array" normalized to "Genome-wide SNP genotyping" drops the word "array", and
    with it the evidence for `genotyping by SNP array assay` over plain `genotyping assay`.
    """
    from app.agent import assay_obi_mapper

    seen = {}

    monkeypatch.setattr(
        assay_obi_mapper, "_top_k_candidates",
        lambda query, k=10, allowed_ids=None: [
            {"id": "OBI:0002031", "label": "genotyping by SNP array assay", "similarity": 0.67}],
    )
    monkeypatch.setattr(
        assay_obi_mapper, "_llm_pick",
        lambda assay_name, candidates, sample_type="", readouts="", **_: seen.__setitem__(
            "shown", assay_name),
    )

    assay_obi_mapper.map_assay_to_obi("ImmunoChip array", "Genome-wide SNP genotyping")

    assert seen["shown"].startswith("ImmunoChip array")
    assert "Genome-wide SNP genotyping" in seen["shown"]


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
    index is a *derived* file, and `obi_assay_terms_full.json` + `obi.obo` + the roots in
    scripts/prune_obi_domain.py are its source. If they ever disagree, someone hand-edited the
    index or changed the roots without rebuilding, and the difference is otherwise invisible.
    """
    import importlib.util
    import json
    from pathlib import Path

    from app.agent.assay_obi_mapper import _OBI_DIR, _is_generic_assay_label

    # scripts/ is not an importable package — same loader shim as test_map_assays_to_obi.py
    script = Path(__file__).resolve().parents[3] / "scripts" / "prune_obi_domain.py"
    spec = importlib.util.spec_from_file_location("prune_obi_domain", script)
    prune = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prune)

    source = json.loads((_OBI_DIR / "obi_assay_terms_full.json").read_text(encoding="utf-8"))
    generic = [t for t in source if _is_generic_assay_label(t["label"])]
    _, children = prune.parse_obo(prune.OBO_PATH)
    dropped = prune.out_of_scope_ids(generic, children)
    rebuilt = [t for t in generic if t["id"] not in dropped]

    committed = json.loads((_OBI_DIR / "obi_generic_index.json").read_text(encoding="utf-8"))

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
