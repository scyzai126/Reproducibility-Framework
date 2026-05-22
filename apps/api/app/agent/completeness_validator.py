"""SQL-only hard-fail completeness checks for ImmPort studies."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


EXAMPLE_LIMIT = 50

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")
_NON_RESULT_EXPSAMPLE_TABLES = {
    "expsample",
    "expsample_2_biosample",
    "expsample_2_file_info",
    "expsample_2_reagent",
    "expsample_2_treatment",
    "expsample_mbaa_detail",
    "expsample_public_repository",
}

_STUDY_EXPSAMPLE_SUBQUERY = """
    SELECT DISTINCT es.expsample_accession, es.experiment_accession
    FROM expsample es
    JOIN experiment e
      ON e.experiment_accession = es.experiment_accession
    WHERE e.study_accession = :study_accession
    UNION
    SELECT DISTINCT es.expsample_accession, es.experiment_accession
    FROM expsample es
    JOIN expsample_2_biosample e2b
      ON e2b.expsample_accession = es.expsample_accession
    JOIN biosample b
      ON b.biosample_accession = e2b.biosample_accession
    WHERE b.study_accession = :study_accession
"""


def _normalize_study_accession(study_accession: str) -> str:
    normalized = (study_accession or "").strip().upper()
    if not normalized:
        raise ValueError("study_accession is required")
    return normalized


def _quote_identifier(identifier: str) -> str:
    if not _SAFE_IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Unsafe SQL identifier from schema metadata: {identifier!r}")
    return f"`{identifier}`"


async def _fetch_dicts(
    session: AsyncSession,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = await session.execute(text(sql), params or {})
    return [dict(row) for row in result.mappings().all()]


async def _fetch_scalar(
    session: AsyncSession,
    sql: str,
    params: dict[str, Any] | None = None,
) -> Any:
    result = await session.execute(text(sql), params or {})
    return result.scalar_one()


def _make_check(
    *,
    name: str,
    description: str,
    bad_count: int,
    total_count: int | None = None,
    example_rows: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "severity": "hard_fail",
        "status": "fail" if bad_count else "pass",
        "description": description,
        "total_count": total_count,
        "bad_count": bad_count,
        "example_rows": example_rows or [],
        "metadata": metadata or {},
    }


async def _check_study_exists(
    session: AsyncSession,
    study_accession: str,
) -> dict[str, Any]:
    count = int(
        await _fetch_scalar(
            session,
            """
            SELECT COUNT(*) AS count
            FROM `study`
            WHERE study_accession = :study_accession
            """,
            {"study_accession": study_accession},
        )
    )
    examples = [] if count else [{"study_accession": study_accession}]
    return _make_check(
        name="study_accession_exists",
        description="The study accession must exist in the study table.",
        total_count=count,
        bad_count=0 if count else 1,
        example_rows=examples,
    )


async def _check_subject_accessions_present(
    session: AsyncSession,
    study_accession: str,
) -> dict[str, Any]:
    total_count = int(
        await _fetch_scalar(
            session,
            """
            SELECT COUNT(DISTINCT b.subject_accession) AS count
            FROM biosample b
            JOIN `subject` s
              ON s.subject_accession = b.subject_accession
            WHERE b.study_accession = :study_accession
              AND b.subject_accession IS NOT NULL
              AND TRIM(b.subject_accession) != ''
            """,
            {"study_accession": study_accession},
        )
    )
    missing_count = int(
        await _fetch_scalar(
            session,
            """
            SELECT COUNT(*) AS count
            FROM biosample
            WHERE study_accession = :study_accession
              AND (subject_accession IS NULL OR TRIM(subject_accession) = '')
            """,
            {"study_accession": study_accession},
        )
    )
    examples = await _fetch_dicts(
        session,
        f"""
        SELECT study_accession, biosample_accession, subject_accession
        FROM biosample
        WHERE study_accession = :study_accession
          AND (subject_accession IS NULL OR TRIM(subject_accession) = '')
        ORDER BY biosample_accession
        LIMIT {EXAMPLE_LIMIT}
        """,
        {"study_accession": study_accession},
    )

    bad_count = missing_count
    if total_count == 0:
        bad_count = 1
        examples = [{"study_accession": study_accession, "reason": "No subject rows found"}]

    return _make_check(
        name="subject_accessions_present",
        description="The study must have biosamples linked to non-empty, valid subject_accession values.",
        total_count=total_count,
        bad_count=bad_count,
        example_rows=examples,
        metadata={"missing_subject_accession_count": missing_count},
    )


async def _check_biosamples_link_subjects(
    session: AsyncSession,
    study_accession: str,
) -> dict[str, Any]:
    total_count = int(
        await _fetch_scalar(
            session,
            """
            SELECT COUNT(*) AS count
            FROM biosample
            WHERE study_accession = :study_accession
            """,
            {"study_accession": study_accession},
        )
    )
    bad_count = int(
        await _fetch_scalar(
            session,
            """
            SELECT COUNT(*) AS count
            FROM biosample b
            LEFT JOIN `subject` s
              ON s.subject_accession = b.subject_accession
            WHERE b.study_accession = :study_accession
              AND (
                b.subject_accession IS NULL
                OR TRIM(b.subject_accession) = ''
                OR s.subject_accession IS NULL
              )
            """,
            {"study_accession": study_accession},
        )
    )
    examples = await _fetch_dicts(
        session,
        f"""
        SELECT
          b.study_accession,
          b.biosample_accession,
          b.subject_accession
        FROM biosample b
        LEFT JOIN `subject` s
          ON s.subject_accession = b.subject_accession
        WHERE b.study_accession = :study_accession
          AND (
            b.subject_accession IS NULL
            OR TRIM(b.subject_accession) = ''
            OR s.subject_accession IS NULL
          )
        ORDER BY b.biosample_accession
        LIMIT {EXAMPLE_LIMIT}
        """,
        {"study_accession": study_accession},
    )
    return _make_check(
        name="biosamples_link_to_subjects",
        description="Every biosample in the study must link to a valid subject in the same study.",
        total_count=total_count,
        bad_count=bad_count,
        example_rows=examples,
    )


async def _check_expsamples_link_biosamples(
    session: AsyncSession,
    study_accession: str,
) -> dict[str, Any]:
    total_count = int(
        await _fetch_scalar(
            session,
            f"""
            SELECT COUNT(*) AS count
            FROM ({_STUDY_EXPSAMPLE_SUBQUERY}) study_es
            """,
            {"study_accession": study_accession},
        )
    )
    bad_count = int(
        await _fetch_scalar(
            session,
            f"""
            SELECT COUNT(*) AS count
            FROM (
              SELECT study_es.expsample_accession
              FROM ({_STUDY_EXPSAMPLE_SUBQUERY}) study_es
              LEFT JOIN expsample_2_biosample e2b
                ON e2b.expsample_accession = study_es.expsample_accession
              LEFT JOIN biosample b
                ON b.biosample_accession = e2b.biosample_accession
               AND b.study_accession = :study_accession
              GROUP BY study_es.expsample_accession
              HAVING SUM(CASE WHEN b.biosample_accession IS NOT NULL THEN 1 ELSE 0 END) = 0
            ) missing_links
            """,
            {"study_accession": study_accession},
        )
    )
    examples = await _fetch_dicts(
        session,
        f"""
        SELECT
          :study_accession AS study_accession,
          study_es.expsample_accession,
          study_es.experiment_accession,
          COUNT(e2b.biosample_accession) AS linked_biosample_refs,
          SUM(CASE WHEN b.biosample_accession IS NOT NULL THEN 1 ELSE 0 END) AS valid_biosample_links
        FROM ({_STUDY_EXPSAMPLE_SUBQUERY}) study_es
        LEFT JOIN expsample_2_biosample e2b
          ON e2b.expsample_accession = study_es.expsample_accession
        LEFT JOIN biosample b
          ON b.biosample_accession = e2b.biosample_accession
         AND b.study_accession = :study_accession
        GROUP BY study_es.expsample_accession, study_es.experiment_accession
        HAVING SUM(CASE WHEN b.biosample_accession IS NOT NULL THEN 1 ELSE 0 END) = 0
        ORDER BY study_es.expsample_accession
        LIMIT {EXAMPLE_LIMIT}
        """,
        {"study_accession": study_accession},
    )
    return _make_check(
        name="expsamples_link_to_biosamples",
        description="Every experiment sample must link to at least one valid biosample in the same study.",
        total_count=total_count,
        bad_count=bad_count,
        example_rows=examples,
    )


async def _check_expsamples_link_experiments(
    session: AsyncSession,
    study_accession: str,
) -> dict[str, Any]:
    total_count = int(
        await _fetch_scalar(
            session,
            f"""
            SELECT COUNT(*) AS count
            FROM ({_STUDY_EXPSAMPLE_SUBQUERY}) study_es
            """,
            {"study_accession": study_accession},
        )
    )
    bad_count = int(
        await _fetch_scalar(
            session,
            f"""
            SELECT COUNT(*) AS count
            FROM ({_STUDY_EXPSAMPLE_SUBQUERY}) study_es
            LEFT JOIN experiment e
              ON e.experiment_accession = study_es.experiment_accession
             AND e.study_accession = :study_accession
            WHERE 1 = 1
              AND (
                study_es.experiment_accession IS NULL
                OR TRIM(study_es.experiment_accession) = ''
                OR e.experiment_accession IS NULL
              )
            """,
            {"study_accession": study_accession},
        )
    )
    examples = await _fetch_dicts(
        session,
        f"""
        SELECT
          :study_accession AS study_accession,
          study_es.expsample_accession,
          study_es.experiment_accession
        FROM ({_STUDY_EXPSAMPLE_SUBQUERY}) study_es
        LEFT JOIN experiment e
          ON e.experiment_accession = study_es.experiment_accession
         AND e.study_accession = :study_accession
        WHERE 1 = 1
          AND (
            study_es.experiment_accession IS NULL
            OR TRIM(study_es.experiment_accession) = ''
            OR e.experiment_accession IS NULL
          )
        ORDER BY study_es.expsample_accession
        LIMIT {EXAMPLE_LIMIT}
        """,
        {"study_accession": study_accession},
    )
    return _make_check(
        name="expsamples_link_to_experiments",
        description="Every experiment sample must link to a valid experiment in the same study.",
        total_count=total_count,
        bad_count=bad_count,
        example_rows=examples,
    )


async def _check_experiment_measurement_technique(
    session: AsyncSession,
    study_accession: str,
) -> dict[str, Any]:
    total_count = int(
        await _fetch_scalar(
            session,
            """
            SELECT COUNT(*) AS count
            FROM experiment
            WHERE study_accession = :study_accession
            """,
            {"study_accession": study_accession},
        )
    )
    missing_count = int(
        await _fetch_scalar(
            session,
            """
            SELECT COUNT(*) AS count
            FROM experiment
            WHERE study_accession = :study_accession
              AND (measurement_technique IS NULL OR TRIM(measurement_technique) = '')
            """,
            {"study_accession": study_accession},
        )
    )
    examples = await _fetch_dicts(
        session,
        f"""
        SELECT
          study_accession,
          experiment_accession,
          name,
          measurement_technique
        FROM experiment
        WHERE study_accession = :study_accession
          AND (measurement_technique IS NULL OR TRIM(measurement_technique) = '')
        ORDER BY experiment_accession
        LIMIT {EXAMPLE_LIMIT}
        """,
        {"study_accession": study_accession},
    )

    bad_count = missing_count
    if total_count == 0:
        bad_count = 1
        examples = [{"study_accession": study_accession, "reason": "No experiment rows found"}]

    return _make_check(
        name="experiments_have_measurement_technique",
        description="Every experiment must have a non-empty measurement_technique.",
        total_count=total_count,
        bad_count=bad_count,
        example_rows=examples,
        metadata={"missing_measurement_technique_count": missing_count},
    )


async def _check_biosamples_have_tissue(
    session: AsyncSession,
    study_accession: str,
) -> dict[str, Any]:
    total_count = int(
        await _fetch_scalar(
            session,
            """
            SELECT COUNT(*) AS count
            FROM biosample
            WHERE study_accession = :study_accession
            """,
            {"study_accession": study_accession},
        )
    )
    missing_count = int(
        await _fetch_scalar(
            session,
            """
            SELECT COUNT(*) AS count
            FROM biosample
            WHERE study_accession = :study_accession
              AND TRIM(COALESCE(`type`, '')) = ''
              AND TRIM(COALESCE(subtype, '')) = ''
            """,
            {"study_accession": study_accession},
        )
    )
    examples = await _fetch_dicts(
        session,
        f"""
        SELECT
          study_accession,
          biosample_accession,
          `type`,
          subtype
        FROM biosample
        WHERE study_accession = :study_accession
          AND TRIM(COALESCE(`type`, '')) = ''
          AND TRIM(COALESCE(subtype, '')) = ''
        ORDER BY biosample_accession
        LIMIT {EXAMPLE_LIMIT}
        """,
        {"study_accession": study_accession},
    )

    bad_count = missing_count
    if total_count == 0:
        bad_count = 1
        examples = [{"study_accession": study_accession, "reason": "No biosample rows found"}]

    return _make_check(
        name="biosamples_have_tissue",
        description="Every biosample must have a non-empty type or subtype (tissue annotation).",
        total_count=total_count,
        bad_count=bad_count,
        example_rows=examples,
        metadata={"missing_tissue_count": missing_count},
    )


async def _get_result_table_names(session: AsyncSession) -> list[str]:
    database_name = await _fetch_scalar(session, "SELECT DATABASE() AS database_name")
    rows = await _fetch_dicts(
        session,
        """
        SELECT DISTINCT TABLE_NAME AS table_name
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :database_name
          AND COLUMN_NAME = 'expsample_accession'
        ORDER BY TABLE_NAME
        """,
        {"database_name": database_name},
    )

    result_tables: list[str] = []
    for row in rows:
        table_name = str(row["table_name"])
        lowered = table_name.lower()
        if lowered in _NON_RESULT_EXPSAMPLE_TABLES:
            continue
        if "result" not in lowered:
            continue
        _quote_identifier(table_name)
        result_tables.append(table_name)
    return result_tables


async def _fetch_expsample_result_accessions(
    session: AsyncSession,
    study_accession: str,
    result_tables: list[str],
) -> set[str]:
    accessions: set[str] = set()
    for table_name in result_tables:
        quoted_table = _quote_identifier(table_name)
        rows = await _fetch_dicts(
            session,
            f"""
            SELECT DISTINCT r.expsample_accession
            FROM {quoted_table} r
            JOIN ({_STUDY_EXPSAMPLE_SUBQUERY}) study_es
              ON study_es.expsample_accession = r.expsample_accession
            """,
            {"study_accession": study_accession},
        )
        accessions.update(str(row["expsample_accession"]) for row in rows if row.get("expsample_accession"))
    return accessions


async def _check_assay_result_or_file_present(
    session: AsyncSession,
    study_accession: str,
    result_tables: list[str] | None = None,
) -> dict[str, Any]:
    expsamples = await _fetch_dicts(
        session,
        f"""
        SELECT
          :study_accession AS study_accession,
          study_es.expsample_accession,
          study_es.experiment_accession,
          COUNT(DISTINCT fi.file_info_id) AS linked_file_count
        FROM ({_STUDY_EXPSAMPLE_SUBQUERY}) study_es
        LEFT JOIN expsample_2_file_info e2f
          ON e2f.expsample_accession = study_es.expsample_accession
        LEFT JOIN file_info fi
          ON fi.file_info_id = e2f.file_info_id
        GROUP BY study_es.expsample_accession, study_es.experiment_accession
        ORDER BY study_es.expsample_accession
        """,
        {"study_accession": study_accession},
    )
    if result_tables is None:
        result_tables = await _get_result_table_names(session)
    result_accessions = await _fetch_expsample_result_accessions(
        session,
        study_accession,
        result_tables,
    )

    missing_rows: list[dict[str, Any]] = []
    for row in expsamples:
        expsample_accession = row.get("expsample_accession")
        linked_file_count = int(row.get("linked_file_count") or 0)
        has_result_row = expsample_accession in result_accessions
        if linked_file_count == 0 and not has_result_row:
            missing_rows.append(
                {
                    **row,
                    "has_result_row": False,
                    "checked_result_tables": result_tables,
                }
            )

    if not expsamples:
        missing_rows = [
            {
                "study_accession": study_accession,
                "reason": "No expsample rows found, so assay result/file completeness cannot pass",
                "checked_result_tables": result_tables,
            }
        ]

    return _make_check(
        name="assay_result_or_file_present",
        description="Every experiment sample must have at least one linked file_info row or one assay result row.",
        total_count=len(expsamples),
        bad_count=len(missing_rows),
        example_rows=missing_rows[:EXAMPLE_LIMIT],
        metadata={
            "result_tables_checked": result_tables,
            "expsamples_with_result_rows": len(result_accessions),
        },
    )


async def validate_hard_fail_completeness(
    session: AsyncSession,
    study_accession: str,
    result_tables: list[str] | None = None,
) -> dict[str, Any]:
    """Run deterministic hard-fail completeness checks for one ImmPort study."""
    normalized_study_accession = _normalize_study_accession(study_accession)
    if result_tables is None:
        result_tables = await _get_result_table_names(session)

    checks = [
        await _check_study_exists(session, normalized_study_accession),
        await _check_subject_accessions_present(session, normalized_study_accession),
        await _check_biosamples_link_subjects(session, normalized_study_accession),
        await _check_biosamples_have_tissue(session, normalized_study_accession),
        await _check_expsamples_link_biosamples(session, normalized_study_accession),
        await _check_expsamples_link_experiments(session, normalized_study_accession),
        await _check_experiment_measurement_technique(session, normalized_study_accession),
        await _check_assay_result_or_file_present(
            session,
            normalized_study_accession,
            result_tables=result_tables,
        ),
    ]
    hard_failures = [check for check in checks if check["status"] == "fail"]
    return {
        "study_accession": normalized_study_accession,
        "mode": "hard_fail_only",
        "status": "fail" if hard_failures else "pass",
        "hard_fail_count": len(hard_failures),
        "checks": checks,
        "hard_failures": hard_failures,
    }


async def fetch_all_study_accessions(
    session: AsyncSession,
    limit: int | None = None,
) -> list[str]:
    """Fetch all study accessions from the ImmPort study table."""
    sql = """
        SELECT study_accession
        FROM `study`
        WHERE study_accession IS NOT NULL
          AND TRIM(study_accession) != ''
        ORDER BY study_accession
    """
    if limit is not None:
        sql += "\nLIMIT :limit"
    params = {"limit": limit} if limit is not None else {}
    rows = await _fetch_dicts(session, sql, params)
    return [str(row["study_accession"]) for row in rows]


async def _fetch_study_static_profile(
    session: AsyncSession,
    study_accession: str,
) -> dict[str, int]:
    rows = await _fetch_dicts(
        session,
        f"""
        SELECT
          (SELECT COUNT(*)
             FROM (
               SELECT DISTINCT b.subject_accession
               FROM biosample b
               JOIN `subject` s
                 ON s.subject_accession = b.subject_accession
               WHERE b.study_accession = :study_accession
                 AND b.subject_accession IS NOT NULL
                 AND TRIM(b.subject_accession) != ''
             ) study_subjects) AS subject_count,
          (SELECT COUNT(*)
             FROM biosample
            WHERE study_accession = :study_accession) AS biosample_count,
          (SELECT COUNT(*)
             FROM biosample
            WHERE study_accession = :study_accession
              AND (
                TRIM(COALESCE(`type`, '')) != ''
                OR TRIM(COALESCE(subtype, '')) != ''
              )) AS biosamples_with_tissue_count,
          (SELECT COUNT(*)
             FROM ({_STUDY_EXPSAMPLE_SUBQUERY}) study_es) AS expsample_count,
          (SELECT COUNT(*)
             FROM experiment
            WHERE study_accession = :study_accession) AS experiment_count,
          (SELECT COUNT(*)
             FROM experiment
            WHERE study_accession = :study_accession
              AND TRIM(COALESCE(measurement_technique, '')) != '') AS experiments_with_measurement_technique_count
        """,
        {"study_accession": study_accession},
    )
    row = rows[0] if rows else {}
    profile = {key: int(row.get(key) or 0) for key in row}
    profile["biosamples_missing_tissue_count"] = max(
        profile.get("biosample_count", 0) - profile.get("biosamples_with_tissue_count", 0),
        0,
    )
    profile["experiments_missing_measurement_technique_count"] = max(
        profile.get("experiment_count", 0)
        - profile.get("experiments_with_measurement_technique_count", 0),
        0,
    )
    return profile


def _coverage_status(total_count: int, covered_count: int) -> str:
    if total_count <= 0:
        return "none"
    if covered_count <= 0:
        return "none"
    if covered_count < total_count:
        return "partial"
    return "complete"


def _classify_static_study(
    hard_fail_report: dict[str, Any],
    profile: dict[str, int],
) -> dict[str, Any]:
    checks_by_name = {check["name"]: check for check in hard_fail_report.get("checks", [])}
    result_check = checks_by_name.get("assay_result_or_file_present", {})

    subject_count = profile.get("subject_count", 0)
    biosample_count = profile.get("biosample_count", 0)
    expsample_count = profile.get("expsample_count", 0)
    experiment_count = profile.get("experiment_count", 0)

    tissue_status = _coverage_status(
        biosample_count,
        profile.get("biosamples_with_tissue_count", 0),
    )
    assay_status = _coverage_status(
        experiment_count,
        profile.get("experiments_with_measurement_technique_count", 0),
    )

    result_total = int(result_check.get("total_count") or expsample_count)
    result_missing = int(result_check.get("bad_count") or 0)
    result_status = _coverage_status(result_total, max(result_total - result_missing, 0))

    failed_check_names = [
        check["name"] for check in hard_fail_report.get("hard_failures", [])
    ]

    flags: list[str] = []
    if hard_fail_report.get("status") == "fail":
        flags.append("hard_fail")
    if subject_count == 0:
        flags.append("no_subjects")
    if biosample_count == 0:
        flags.append("no_biosamples")
    if expsample_count == 0:
        flags.append("no_expsamples")
    if assay_status == "none":
        flags.append("no_assay")
    elif assay_status == "partial":
        flags.append("partial_assay")
    if tissue_status == "none":
        flags.append("no_tissue")
    elif tissue_status == "partial":
        flags.append("partial_tissue")
    if result_status == "none":
        flags.append("no_result")
    elif result_status == "partial":
        flags.append("partial_result")
    if any(
        name in failed_check_names
        for name in (
            "biosamples_link_to_subjects",
            "expsamples_link_to_biosamples",
            "expsamples_link_to_experiments",
        )
    ):
        flags.append("broken_linkage")

    if not flags:
        overall_status = "complete"
    elif {"no_subjects", "no_biosamples", "no_expsamples"}.intersection(flags):
        overall_status = "missing_core"
    elif "no_assay" in flags:
        overall_status = "no_assay"
    elif "no_result" in flags:
        overall_status = "no_result"
    elif "no_tissue" in flags:
        overall_status = "no_tissue"
    else:
        overall_status = "partial"

    failed_checks = [
        {
            "name": check["name"],
            "bad_count": check["bad_count"],
            "total_count": check.get("total_count"),
        }
        for check in hard_fail_report.get("hard_failures", [])
    ]

    return {
        "study_accession": hard_fail_report["study_accession"],
        "overall_status": overall_status,
        "flags": flags,
        "counts": {
            **profile,
            "expsamples_missing_result_or_file_count": result_missing,
        },
        "coverage_status": {
            "assay": assay_status,
            "tissue": tissue_status,
            "result_or_file": result_status,
        },
        "hard_fail_count": hard_fail_report.get("hard_fail_count", 0),
        "failed_checks": failed_checks,
    }


def _summarize_static_studies(studies: list[dict[str, Any]]) -> dict[str, Any]:
    overall_status_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    hard_fail_check_counts: dict[str, int] = {}

    for study in studies:
        overall_status = study.get("overall_status", "unknown")
        overall_status_counts[overall_status] = overall_status_counts.get(overall_status, 0) + 1

        for flag in study.get("flags", []):
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

        for check in study.get("failed_checks", []):
            name = check["name"]
            hard_fail_check_counts[name] = hard_fail_check_counts.get(name, 0) + 1

    return {
        "study_count": len(studies),
        "overall_status_counts": dict(sorted(overall_status_counts.items())),
        "flag_counts": dict(sorted(flag_counts.items())),
        "hard_fail_check_counts": dict(sorted(hard_fail_check_counts.items())),
    }


async def build_static_completeness_report(
    session: AsyncSession,
    *,
    limit: int | None = None,
    include_checks: bool = False,
) -> dict[str, Any]:
    """Build a static all-study completeness report from the current database."""
    database_name = await _fetch_scalar(session, "SELECT DATABASE() AS database_name")
    result_tables = await _get_result_table_names(session)
    study_accessions = await fetch_all_study_accessions(session, limit=limit)

    studies: list[dict[str, Any]] = []
    for study_accession in study_accessions:
        try:
            hard_fail_report = await validate_hard_fail_completeness(
                session,
                study_accession,
                result_tables=result_tables,
            )
            profile = await _fetch_study_static_profile(session, study_accession)
            study_summary = _classify_static_study(hard_fail_report, profile)
            if include_checks:
                study_summary["checks"] = hard_fail_report["checks"]
            studies.append(study_summary)
        except Exception as exc:
            studies.append(
                {
                    "study_accession": study_accession,
                    "overall_status": "error",
                    "flags": ["error"],
                    "counts": {},
                    "coverage_status": {},
                    "hard_fail_count": 1,
                    "failed_checks": [
                        {
                            "name": "report_generation_error",
                            "bad_count": 1,
                            "total_count": None,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    ],
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "hard_fail_static_all_studies",
        "source": {
            "database": database_name,
            "study_table": "study",
            "result_tables_checked": result_tables,
        },
        "definitions": {
            "complete": "No hard-fail checks, complete assay metadata, complete biosample tissue coverage, and result/file coverage for all expsamples.",
            "partial": "The study has core data but at least one assay, tissue, result/file, or linkage category is incomplete.",
            "missing_core": "The study has no subjects, no biosamples, or no expsamples.",
            "no_assay": "No experiment rows, or no experiment rows with measurement_technique.",
            "no_tissue": "No biosamples with populated type or subtype.",
            "no_result": "No expsamples with linked file_info or discovered result-table rows.",
        },
        "summary": _summarize_static_studies(studies),
        "studies": studies,
    }
