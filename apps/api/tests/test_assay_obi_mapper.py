from app.agent.assay_obi_mapper import enrich_assays_with_obi, map_assay_to_obi


def test_curated_assay_map_takes_precedence():
    mapped = map_assay_to_obi("ELISA")

    assert mapped == {
        "obi_id": "OBI:0000661",
        "obi_label": "enzyme-linked immunosorbent assay",
        "obi_match_type": "curated",
    }


def test_ontology_synonym_maps_prompt_canonical_names():
    assert map_assay_to_obi("CyTOF")["obi_id"] == "OBI:0002115"
    assert map_assay_to_obi("CITE-seq")["obi_id"] == "OBI:0003788"
    assert map_assay_to_obi("Olink")["obi_id"] == "OBI:0003112"


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
    assert enriched["Unknown Custom Assay"]["obi_match_type"] == "unresolved"
