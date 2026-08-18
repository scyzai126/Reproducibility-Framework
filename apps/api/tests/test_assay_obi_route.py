"""Stats for the assay registry page are computed server-side, so they are tested here.

The one that matters is `by_resource`: the UI paints each segment a fixed colour by
position, so the order must come from _RESOURCE_ORDER rather than from whatever order
the rows happen to arrive in. Everything else is counting, but coverage is the number
the page leads with, so it gets a test too.
"""

from app.api.routes import _assay_obi_stats


def _row(study, assay, obi_id, resource):
    return {
        "study": study,
        "assay": assay,
        "normalized_name": assay,
        "sample_type": "PBMCs",
        "readouts": "cell frequencies",
        "obi_id": obi_id,
        "obi_label": f"{assay} assay" if obi_id else None,
        "resource": resource,
        "obi_confidence": "high" if obi_id else None,
    }


def test_counts_papers_and_terms_by_distinct_value():
    rows = [
        _row("a", "flow cytometry", "OBI:0000916", "exact_original"),
        _row("a", "FACS", "OBI:0000916", "exact_normalized"),
        _row("b", "ELISA", "OBI:0000661", "exact_original"),
    ]

    stats = _assay_obi_stats(rows)

    assert stats["total_rows"] == 3
    assert stats["papers"] == 2
    assert stats["obi_terms"] == 2  # OBI:0000916 counted once across two rows


def test_coverage_counts_rows_with_an_obi_id():
    rows = [
        _row("a", "flow cytometry", "OBI:0000916", "exact_original"),
        _row("a", "SIMoA", None, "unresolved"),
        _row("b", "ELISA", "OBI:0000661", "exact_original"),
        _row("b", "CPE", None, "unresolved"),
    ]

    stats = _assay_obi_stats(rows)

    assert stats["mapped_rows"] == 2
    assert stats["coverage_pct"] == 50.0
    assert stats["unresolved_names"] == ["CPE", "SIMoA"]


def test_by_resource_follows_the_fixed_display_order_not_the_row_order():
    """Segment colours are assigned by position, so a data reshuffle must not repaint them."""
    rows = [
        _row("a", "x", None, "unresolved"),
        _row("a", "y", "OBI:1", "embedding_llm"),
        _row("b", "z", "OBI:2", "exact_normalized"),
        _row("b", "w", "OBI:3", "exact_original"),
    ]

    resources = [entry["resource"] for entry in _assay_obi_stats(rows)["by_resource"]]

    assert resources == ["exact_original", "exact_normalized", "embedding_llm", "unresolved"]


def test_resources_with_no_rows_are_omitted_rather_than_shown_as_zero():
    rows = [_row("a", "flow cytometry", "OBI:0000916", "exact_original")]

    stats = _assay_obi_stats(rows)

    assert stats["by_resource"] == [{"resource": "exact_original", "count": 1}]


def test_a_missing_resource_key_is_treated_as_unresolved():
    rows = [{"study": "a", "assay": "mystery", "obi_id": None}]

    stats = _assay_obi_stats(rows)

    assert stats["by_resource"] == [{"resource": "unresolved", "count": 1}]
    assert stats["coverage_pct"] == 0.0


def test_empty_table_does_not_divide_by_zero():
    stats = _assay_obi_stats([])

    assert stats["total_rows"] == 0
    assert stats["coverage_pct"] == 0.0
    assert stats["by_resource"] == []
