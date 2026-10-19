import pytest

from app.agent.assay_obi_mapper import enrich_assays_with_obi, map_assay_to_obi


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

    def fake_top_k(query, k=10, allowed_ids=None):
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
    assert set(seen["ids"]) == {"OBI:0000916", "OBI:0001632"}
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

    def fake_top_k(query, k=10, allowed_ids=None):
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
    """A technique that changed nothing must not buy a second embedding call."""
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
        lambda query, k=20, allowed_ids=None: (
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
    """The model still judges by the paper's own wording; the technique is context.

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
