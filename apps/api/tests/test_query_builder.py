import pytest

from app.agent.query_builder import build_subject_queries


# --- build_subject_queries tests ---


def test_build_subject_queries_basic():
    analysis = [
        {
            "group_id": 0,
            "group_name": "Healthy controls",
            "disease": "healthy",
            "experiment_accession": "EXP001",
            "study_accession": "SDY1",
        },
        {
            "group_id": 1,
            "group_name": "COVID-19 patients",
            "disease": "COVID-19",
            "experiment_accession": "EXP001",
            "study_accession": "SDY1",
        },
    ]

    result = build_subject_queries(analysis)
    assert len(result) == 2

    # Check first group
    assert result[0]["group_id"] == 0
    assert "WHERE" in result[0]["sql"] or "WHERE 1=1" in result[0]["sql"]
    assert "sdv.experiment_accession = :experiment_accession" in result[0]["sql"]
    assert "sdv.study_accession = :study_accession" in result[0]["sql"]
    assert "sdv.`condition` = :disease" in result[0]["sql"]
    assert result[0]["params"]["experiment_accession"] == "EXP001"
    assert result[0]["params"]["study_accession"] == "SDY1"
    assert result[0]["params"]["disease"] == "healthy"

    # Check second group
    assert result[1]["group_id"] == 1
    assert result[1]["params"]["disease"] == "COVID-19"


def test_build_subject_queries_no_condition():
    analysis = [
        {
            "group_id": 0,
            "group_name": "All subjects",
            "disease": "",
            "experiment_accession": "EXP001",
        },
    ]

    result = build_subject_queries(analysis)
    assert len(result) == 1
    assert "`condition`" not in result[0]["sql"]
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
    assert "WHERE 1=1" in result[0]["sql"]
    # No filters when all fields are empty
    assert "experiment_accession" not in result[0]["params"]
    assert "study_accession" not in result[0]["params"]
    assert "disease" not in result[0]["params"]


def test_build_subject_queries_select_columns():
    """Query selects the 3 ID columns (expsample, biosample, subject)."""
    analysis = [
        {
            "group_id": 0,
            "group_name": "Test",
            "disease": "healthy",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    assert "sdv.expsample_accession" in sql
    assert "sdv.biosample_accession" in sql
    assert "sdv.subject_accession" in sql
    assert "DISTINCT" in sql
    assert "ORDER BY sdv.subject_accession" in sql


def test_build_subject_queries_join_chain():
    """Query uses subject_data_view instead of manual joins."""
    analysis = [{"group_id": 0, "group_name": "Test"}]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    assert "FROM subject_data_view sdv" in sql
    # Old manual join tables should NOT be in the query
    assert "FROM expsample es" not in sql
    assert "JOIN biosample b" not in sql
    assert "JOIN immune_exposure" not in sql


def test_build_subject_queries_all_filters():
    """All fields (disease, experiment_accession, study_accession, arm_accession, tissue_type) become SQL filters."""
    analysis = [
        {
            "group_id": 2,
            "group_name": "Healthy PBMC from Atlanta",
            "disease": "healthy",
            "experiment_accession": "EXP12345",
            "study_accession": "SDY999",
            "arm_accession": "ARM5346",
            "tissue_type": "PBMC",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    params = result[0]["params"]

    assert "sdv.experiment_accession = :experiment_accession" in sql
    assert "sdv.study_accession = :study_accession" in sql
    assert "sdv.`condition` = :disease" in sql
    assert "sdv.arm_accession = :arm_accession" in sql
    assert "sdv.tissue_type = :tissue_type" in sql

    assert params["experiment_accession"] == "EXP12345"
    assert params["study_accession"] == "SDY999"
    assert params["disease"] == "healthy"
    assert params["arm_accession"] == "ARM5346"
    assert params["tissue_type"] == "PBMC"


def test_build_subject_queries_no_arm_no_tissue():
    """When arm_accession and tissue_type are empty, those filters are omitted."""
    analysis = [
        {
            "group_id": 0,
            "group_name": "All Olink",
            "disease": "healthy",
            "arm_accession": "",
            "tissue_type": "",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    assert "arm_accession =" not in sql
    assert "tissue_type =" not in sql


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
    assert "sdv.study_accession = :study_accession" in sql
    assert params["study_accession"] == "SDY1234"


def test_build_subject_queries_no_study_accession():
    """study_accession filter is omitted when not provided."""
    analysis = [
        {
            "group_id": 0,
            "group_name": "No study",
            "disease": "healthy",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    assert "study_accession" not in result[0]["params"]
    assert "sdv.study_accession" not in sql


def test_optional_filters_extensibility():
    """Adding a new entry to VIEW_FILTERS is picked up by _build_query."""
    from app.agent import query_builder

    # Temporarily add a new filter spec
    original = query_builder.VIEW_FILTERS[:]
    query_builder.VIEW_FILTERS.append(
        {"field": "study_time", "col": "study_time_collected", "type": "eq"}
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
        assert "study_time_collected" in sql
        assert params["study_time"] == "Day 7"
    finally:
        query_builder.VIEW_FILTERS[:] = original


def test_build_query_no_experiment_filter_when_missing():
    """When experiment_accession is missing, no experiment filter."""
    analysis = [
        {
            "group_id": 0,
            "group_name": "No experiment info",
            "disease": "healthy",
        },
    ]

    result = build_subject_queries(analysis)
    sql = result[0]["sql"]
    params = result[0]["params"]

    assert "experiment_accession" not in params
    assert "sdv.`condition` = :disease" in sql
