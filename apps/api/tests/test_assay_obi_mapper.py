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

    normalized = map_assay_to_obi("XYZZY_unknown", "enzyme-linked immunosorbent assay")
    assert normalized["confidence"] == "high"
    assert normalized["resource"] == "exact_normalized"


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

    def fake_llm_pick(assay_name, candidates, sample_type="", readouts=""):
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

    def fake_llm_pick(assay_name, candidates, sample_type="", readouts=""):
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
    assert len(ids) == len(_term_ids(_OBI_DIR / "obi_generic_index.json"))


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
