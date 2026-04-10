import pytest

from app.agent.query_builder import build_subject_queries, OPTIONAL_FILTERS


# --- build_subject_queries tests ---


def test_build_subject_queries_basic():
    analysis = [
        {
            "group_id": 0,
            "group_name": "Healthy controls",
            "condition": "healthy",
            "experiment_accession": "EXP001",
            "study_accession": "SDY1",
        },
        {
            "group_id": 1,
            "group_name": "COVID-19 patients",
            "condition": "COVID-19",
            "experiment_accession": "EXP001",
            "study_accession": "SDY1",
        },
    ]

    result = build_subject_queries(analysis)
    assert len(result) == 2

    # Check first group
    assert result[0]["group_id"] == 0
    assert result[0]["group_name"] == "Healthy controls"
    assert "WHERE 1=1" in result[0]["sql"]
    assert "es.experiment_accession = :experiment_accession" in result[0]["sql"]
    assert "es.study_accession = :study_accession" in result[0]["sql"]
    assert "ie.disease_preferred = :condition" in result[0]["sql"]
    assert result[0]["params"]["experiment_accession"] == "EXP001"
    assert result[0]["params"]["study_accession"] == "SDY1"
    assert result[0]["params"]["condition"] == "healthy"

    # Check second group
    assert result[1]["group_id"] == 1
    assert result[1]["params"]["condition"] == "COVID-19"


def test_build_subject_queries_no_condition():
    analysis = [
        {
            "group_id": 0,
            "group_name": "All subjects",
            "condition": "",
            "experiment_accession": "EXP001",
        },
    ]

    result = build_subject_queries(analysis)
    assert len(result) == 1
    assert "disease_preferred = :condition" not in result[0]["sql"]
    assert result[0]["params"]["experiment_accession"] == "EXP001"


def test_build_subject_queries_empty_analysis():
    assert build_subject_queries([]) == []
    assert build_subject_queries(None) == []


def test_build_subject_queries_missing_fields():
    """Groups with missing fields should still produce valid queries."""
    analysis = [{"group_id": 2}]

    result = build_subject_queries(analysis)
    assert len(result) == 1
    assert result[0]["group_id"] == 2
    assert result[0]["group_name"] == ""
    assert "WHERE 1=1" in result[0]["sql"]
    # No filters when all fields are empty
    assert "experiment_accession" not in result[0]["params"]
    assert "study_accession" not in result[0]["params"]
    assert "condition" not in result[0]["params"]


def test_build_subject_queries_select_columns():
    """Query selects the 3 ID columns (expsample, biosample, subject)."""
    analysis = [
        {
            "group_id": 0,
            "group_name": "Test",
            "condition": "healthy",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    assert "es.expsample_accession" in sql
    assert "b.biosample_accession" in sql
    assert "b.subject_accession" in sql
    assert "DISTINCT" in sql
    assert "ORDER BY b.subject_accession" in sql


def test_build_subject_queries_join_chain():
    """Query uses the correct join path: expsample → expsample_2_biosample → biosample."""
    analysis = [{"group_id": 0, "group_name": "Test"}]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    assert "FROM expsample es" in sql
    assert "JOIN expsample_2_biosample e2b ON e2b.expsample_accession = es.expsample_accession" in sql
    assert "JOIN biosample b ON b.biosample_accession = e2b.biosample_accession" in sql
    assert "LEFT JOIN immune_exposure ie ON ie.subject_accession = b.subject_accession" in sql
    # experiment table should NOT be in the join chain
    assert "FROM experiment e" not in sql


def test_build_subject_queries_all_filters():
    """All fields (condition, experiment_accession, study_accession, arm_accession, tissue_type) become SQL filters."""
    analysis = [
        {
            "group_id": 2,
            "group_name": "Healthy PBMC from Atlanta",
            "condition": "healthy",
            "experiment_accession": "EXP12345",
            "study_accession": "SDY999",
            "arm_accession": "ARM5346",
            "tissue_type": "PBMC",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    params = result[0]["params"]

    assert "es.experiment_accession = :experiment_accession" in sql
    assert "es.study_accession = :study_accession" in sql
    assert "ie.disease_preferred = :condition" in sql
    assert "arm_accession = :arm_accession" in sql
    assert "b.type = :tissue_type" in sql

    assert params["experiment_accession"] == "EXP12345"
    assert params["study_accession"] == "SDY999"
    assert params["condition"] == "healthy"
    assert params["arm_accession"] == "ARM5346"
    assert params["tissue_type"] == "PBMC"


def test_build_subject_queries_no_arm_no_tissue():
    """When arm_accession and tissue_type are empty, those filters are omitted."""
    analysis = [
        {
            "group_id": 0,
            "group_name": "All Olink",
            "condition": "healthy",
            "arm_accession": "",
            "tissue_type": "",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    assert "arm_accession =" not in sql
    assert "b.type =" not in sql


def test_build_subject_queries_study_accession_filter():
    """study_accession is added as a filter when present."""
    analysis = [
        {
            "group_id": 0,
            "group_name": "Study group",
            "study_accession": "SDY1234",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    params = result[0]["params"]
    assert "es.study_accession = :study_accession" in sql
    assert params["study_accession"] == "SDY1234"


def test_build_subject_queries_no_study_accession():
    """study_accession filter is omitted when not provided."""
    analysis = [
        {
            "group_id": 0,
            "group_name": "No study",
            "condition": "healthy",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    assert "study_accession" not in result[0]["params"]
    assert "es.study_accession" not in sql


def test_optional_filters_extensibility():
    """Adding a new entry to OPTIONAL_FILTERS is picked up by _build_query."""
    from app.agent import query_builder

    # Temporarily add a new filter spec
    original = query_builder.OPTIONAL_FILTERS[:]
    query_builder.OPTIONAL_FILTERS.append(
        {"field": "study_time", "sql": "b.study_time_collected = :study_time"}
    )
    try:
        analysis = [
            {
                "group_id": 0,
                "group_name": "Time filter test",
                "study_time": "Day 7",
            },
        ]
        result = build_subject_queries(analysis)
        sql = result[0]["sql"]
        params = result[0]["params"]
        assert "b.study_time_collected = :study_time" in sql
        assert params["study_time"] == "Day 7"
    finally:
        query_builder.OPTIONAL_FILTERS[:] = original


def test_build_query_no_experiment_filter_when_missing():
    """When experiment_accession is missing, no experiment filter."""
    analysis = [
        {
            "group_id": 0,
            "group_name": "No experiment info",
            "condition": "healthy",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    params = result[0]["params"]

    assert "experiment_accession" not in params
    assert "ie.disease_preferred = :condition" in sql
