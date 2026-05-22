from unittest.mock import AsyncMock

import pytest

from app.agent import completeness_validator as cv


class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        if self._scalar is not None:
            return self._scalar
        if not self._rows:
            return None
        first = self._rows[0]
        return next(iter(first.values()))

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.queries = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.queries.append((sql, params or {}))
        for marker, response in self.responses:
            if marker in sql:
                return response
        raise AssertionError(f"Unexpected SQL: {sql}")


@pytest.mark.asyncio
async def test_get_result_table_names_discovers_only_result_tables():
    session = _FakeSession(
        [
            ("SELECT DATABASE()", _FakeResult(scalar="immport_dr62")),
            (
                "INFORMATION_SCHEMA.COLUMNS",
                _FakeResult(
                    rows=[
                        {"table_name": "expsample"},
                        {"table_name": "expsample_2_file_info"},
                        {"table_name": "elisa_result"},
                        {"table_name": "fcs_analyzed_result"},
                        {"table_name": "expsample_2_reagent"},
                    ]
                ),
            ),
        ]
    )

    assert await cv._get_result_table_names(session) == [
        "elisa_result",
        "fcs_analyzed_result",
    ]


@pytest.mark.asyncio
async def test_assay_result_or_file_check_flags_only_expsamples_with_neither(monkeypatch):
    session = _FakeSession(
        [
            (
                "FROM expsample es",
                _FakeResult(
                    rows=[
                        {
                            "study_accession": "SDY1",
                            "expsample_accession": "ES1",
                            "experiment_accession": "EXP1",
                            "linked_file_count": 0,
                        },
                        {
                            "study_accession": "SDY1",
                            "expsample_accession": "ES2",
                            "experiment_accession": "EXP1",
                            "linked_file_count": 0,
                        },
                        {
                            "study_accession": "SDY1",
                            "expsample_accession": "ES3",
                            "experiment_accession": "EXP2",
                            "linked_file_count": 1,
                        },
                    ]
                ),
            )
        ]
    )
    monkeypatch.setattr(cv, "_get_result_table_names", AsyncMock(return_value=["elisa_result"]))
    monkeypatch.setattr(
        cv,
        "_fetch_expsample_result_accessions",
        AsyncMock(return_value={"ES2"}),
    )

    check = await cv._check_assay_result_or_file_present(session, "SDY1")

    assert check["status"] == "fail"
    assert check["bad_count"] == 1
    assert check["example_rows"][0]["expsample_accession"] == "ES1"
    assert check["metadata"]["result_tables_checked"] == ["elisa_result"]
    assert check["metadata"]["expsamples_with_result_rows"] == 1


@pytest.mark.asyncio
async def test_validate_hard_fail_completeness_aggregates_failures(monkeypatch):
    async def pass_check(_session, _study_accession, **_kwargs):
        return cv._make_check(
            name="pass_check",
            description="passes",
            bad_count=0,
            total_count=1,
        )

    async def fail_check(_session, _study_accession):
        return cv._make_check(
            name="fail_check",
            description="fails",
            bad_count=2,
            total_count=10,
            example_rows=[{"id": "bad"}],
        )

    monkeypatch.setattr(cv, "_check_study_exists", pass_check)
    monkeypatch.setattr(cv, "_check_subject_accessions_present", pass_check)
    monkeypatch.setattr(cv, "_check_biosamples_link_subjects", pass_check)
    monkeypatch.setattr(cv, "_check_expsamples_link_biosamples", fail_check)
    monkeypatch.setattr(cv, "_check_expsamples_link_experiments", pass_check)
    monkeypatch.setattr(cv, "_check_experiment_measurement_technique", pass_check)
    monkeypatch.setattr(cv, "_check_assay_result_or_file_present", pass_check)

    report = await cv.validate_hard_fail_completeness(object(), " sdy1 ")

    assert report["study_accession"] == "SDY1"
    assert report["status"] == "fail"
    assert report["hard_fail_count"] == 1
    assert report["hard_failures"][0]["name"] == "fail_check"


def test_validate_hard_fail_completeness_requires_study_accession():
    with pytest.raises(ValueError, match="study_accession is required"):
        cv._normalize_study_accession(" ")


def test_classify_static_study_complete():
    hard_fail_report = {
        "study_accession": "SDY1",
        "status": "pass",
        "hard_fail_count": 0,
        "hard_failures": [],
        "checks": [
            {
                "name": "assay_result_or_file_present",
                "status": "pass",
                "bad_count": 0,
                "total_count": 10,
            }
        ],
    }
    profile = {
        "subject_count": 5,
        "biosample_count": 10,
        "biosamples_with_tissue_count": 10,
        "biosamples_missing_tissue_count": 0,
        "expsample_count": 10,
        "experiment_count": 2,
        "experiments_with_measurement_technique_count": 2,
        "experiments_missing_measurement_technique_count": 0,
    }

    summary = cv._classify_static_study(hard_fail_report, profile)

    assert summary["overall_status"] == "complete"
    assert summary["flags"] == []
    assert summary["coverage_status"] == {
        "assay": "complete",
        "tissue": "complete",
        "result_or_file": "complete",
    }


def test_classify_static_study_partial_tissue_and_result():
    hard_fail_report = {
        "study_accession": "SDY2",
        "status": "fail",
        "hard_fail_count": 1,
        "hard_failures": [
            {
                "name": "assay_result_or_file_present",
                "bad_count": 3,
                "total_count": 10,
            }
        ],
        "checks": [
            {
                "name": "assay_result_or_file_present",
                "status": "fail",
                "bad_count": 3,
                "total_count": 10,
            }
        ],
    }
    profile = {
        "subject_count": 5,
        "biosample_count": 10,
        "biosamples_with_tissue_count": 4,
        "biosamples_missing_tissue_count": 6,
        "expsample_count": 10,
        "experiment_count": 2,
        "experiments_with_measurement_technique_count": 2,
        "experiments_missing_measurement_technique_count": 0,
    }

    summary = cv._classify_static_study(hard_fail_report, profile)

    assert summary["overall_status"] == "partial"
    assert "partial_tissue" in summary["flags"]
    assert "partial_result" in summary["flags"]
    assert summary["counts"]["expsamples_missing_result_or_file_count"] == 3


def test_summarize_static_studies_counts_flags_and_failed_checks():
    studies = [
        {
            "overall_status": "complete",
            "flags": [],
            "failed_checks": [],
        },
        {
            "overall_status": "partial",
            "flags": ["hard_fail", "partial_result"],
            "failed_checks": [{"name": "assay_result_or_file_present"}],
        },
        {
            "overall_status": "no_tissue",
            "flags": ["hard_fail", "no_tissue"],
            "failed_checks": [{"name": "biosamples_link_to_subjects"}],
        },
    ]

    summary = cv._summarize_static_studies(studies)

    assert summary["study_count"] == 3
    assert summary["overall_status_counts"] == {
        "complete": 1,
        "no_tissue": 1,
        "partial": 1,
    }
    assert summary["flag_counts"]["hard_fail"] == 2
    assert summary["hard_fail_check_counts"] == {
        "assay_result_or_file_present": 1,
        "biosamples_link_to_subjects": 1,
    }
