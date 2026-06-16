import pytest

from app.agent.query_builder import build_subject_queries, _split_multi_tissue, _apply_placement_result


# --- _split_multi_tissue tests ---


def test_split_single_tissue():
    assert _split_multi_tissue("PBMC") == ["PBMC"]


def test_split_comma():
    assert _split_multi_tissue("PBMC, bone marrow") == ["PBMC", "bone marrow"]


def test_split_semicolon():
    assert _split_multi_tissue("PBMC; T cells") == ["PBMC", "T cells"]


def test_split_and():
    assert _split_multi_tissue("PBMC and bone marrow") == ["PBMC", "bone marrow"]


def test_split_mixed_and_trailing_and():
    assert _split_multi_tissue("PBMC, bone marrow, and liver") == ["PBMC", "bone marrow", "liver"]


def test_split_empty():
    assert _split_multi_tissue("") == []
    assert _split_multi_tissue(None) == []


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


# --- Multi-cohort arm resolution tests ---


def test_build_query_multi_arm_in_clause():
    """arm_accessions list → IN (:arm_0, :arm_1) clause; no eq filter alongside it."""
    result = build_subject_queries([{
        "group_id": 1,
        "study_accession": "SDY1",
        "arm_accessions": ["ARM1", "ARM2"],
        "experiment_accession": "EXP1",
    }])
    sql = result[0]["sql"]
    params = result[0]["params"]

    assert "sdv.arm_accession IN (:arm_0, :arm_1)" in sql
    assert params["arm_0"] == "ARM1"
    assert params["arm_1"] == "ARM2"
    assert "arm_accession = :arm_accession" not in sql


def test_build_query_single_arm_still_eq():
    """Single arm_accession still uses = not IN."""
    result = build_subject_queries([{
        "group_id": 1,
        "study_accession": "SDY1",
        "arm_accession": "ARM1",
        "experiment_accession": "EXP1",
    }])
    sql = result[0]["sql"]

    assert "sdv.arm_accession = :arm_accession" in sql
    assert " IN " not in sql


# --- Placement dict / study_time_collected tests ---


def test_build_query_study_time_collected_range():
    result = build_subject_queries([{
        "group_id": 1,
        "study_accession": "SDY1",
        "experiment_accession": "EXP1",
        "bio_time_min": 0.0,
        "bio_time_max": 7.0,
    }])
    sql, params = result[0]["sql"], result[0]["params"]
    assert "study_time_collected >= :bio_time_min" in sql
    assert "study_time_collected <= :bio_time_max" in sql
    assert params["bio_time_min"] == 0.0
    assert params["bio_time_max"] == 7.0


def test_build_query_study_time_collected_min_only():
    result = build_subject_queries([{
        "group_id": 1,
        "study_accession": "SDY1",
        "experiment_accession": "EXP1",
        "bio_time_min": 3.0,
    }])
    sql = result[0]["sql"]
    assert "study_time_collected >= :bio_time_min" in sql
    assert "bio_time_max" not in sql


def test_apply_placement_result_disease_stage():
    group, log = {}, {}
    pv = _apply_placement_result(group, log, {"field": "disease_stage", "value": "Severe", "method": "SQL"})
    assert pv == []
    assert group["disease_stage"] == "Severe"
    assert group["disease"] == ""
    assert log["disease_stage"] == {"value": "Severe", "method": "SQL"}


def test_apply_placement_result_disease():
    group, log = {}, {}
    pv = _apply_placement_result(group, log, {"field": "disease", "value": "COVID-19", "method": "SQL"})
    assert pv == []
    assert group["disease"] == "COVID-19"


def test_apply_placement_result_planned_visit():
    group, log = {}, {}
    pv = _apply_placement_result(group, log, {
        "field": "planned_visit_accession", "value": ["PV1", "PV2"], "method": "range",
    })
    assert pv == [("PV1", "range"), ("PV2", "range")]
    assert log["planned_visit"]["accessions"] == ["PV1", "PV2"]
    assert "planned_visit_accession" not in group


def test_apply_placement_result_time_collected():
    group, log = {}, {}
    _apply_placement_result(group, log, {
        "field": "study_time_collected", "value": {"min": 0.0, "max": 7.0}, "method": "range",
    })
    assert group["bio_time_min"] == 0.0
    assert group["bio_time_max"] == 7.0
    assert log["study_time_collected"]["range"] == {"min": 0.0, "max": 7.0}


def test_apply_placement_result_arm():
    group, log = {"disease_stage": "x", "disease": "y"}, {}
    _apply_placement_result(group, log, {"field": "arm_accession", "value": "ARM1", "method": "SQL"})
    assert group["arm_accession"] == "ARM1"
    assert "disease_stage" not in group
    assert "disease" not in group


def test_apply_placement_result_sdv_scan():
    group, log = {}, {}
    _apply_placement_result(group, log, {"field": "exposure_process", "value": "Vaccination", "method": "scan"})
    assert group["exposure_process"] == "Vaccination"
    assert log["exposure_process"] == {"value": "Vaccination", "method": "scan"}
