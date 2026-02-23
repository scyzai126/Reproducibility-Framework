"""Resolve accessions and build deterministic SQL for ImmPort subject queries.

Combines field resolution (arm, experiment) with SQL construction into a single
pipeline: resolve → build.  Each resolver uses a two-step strategy: SQL keyword
match first, LLM fallback for ambiguous cases.
"""

import asyncio
import json
import logging

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional SQL filters — each applied only when its field is non-empty.
# To add a new filter (e.g. study_time), append one entry here.
# ---------------------------------------------------------------------------
OPTIONAL_FILTERS = [
    {"field": "experiment_accession", "sql": "es.experiment_accession = :experiment_accession"},
    {"field": "study_accession",      "sql": "b.study_accession = :study_accession"},
    {"field": "tissue_type",          "sql": "b.type = :tissue_type"},
    {"field": "condition",            "sql": "ie.disease_preferred = :condition"},
]

# ---------------------------------------------------------------------------
# Resolver configurations
# ---------------------------------------------------------------------------
_ARM_CONFIG = {
    "table": "arm_or_cohort",
    "id_col": "arm_accession",
    "search_cols": ["name", "description"],
    "all_cols": "arm_accession, name, description",
    "llm_system": (
        "You are a data mapping assistant. Match cohort names to "
        "ImmPort arm records. Return only the arm_accession ID."
    ),
    "llm_prompt": (
        "Given these arms from an ImmPort study:\n{candidates}\n\n"
        'Which arm best matches the cohort "{search_term}"?\n'
        "Return ONLY the arm_accession value (e.g. ARM5346). "
        "If none match, return NONE."
    ),
}

_EXPERIMENT_CONFIG = {
    "table": "experiment",
    "id_col": "experiment_accession",
    "search_cols": ["name", "measurement_technique"],
    "all_cols": "experiment_accession, name, measurement_technique",
    "llm_system": (
        "You are a data mapping assistant. Match assay method names to "
        "ImmPort experiment records. Return only the experiment_accession ID."
    ),
    "llm_prompt": (
        "Given these experiments from an ImmPort study:\n{candidates}\n\n"
        'Which experiment best matches the assay method "{search_term}"?\n'
        "Return ONLY the experiment_accession value (e.g. EXP12345). "
        "If none match, return NONE."
    ),
}

# ---------------------------------------------------------------------------
# Generic resolver (SQL LIKE → LLM fallback)
# ---------------------------------------------------------------------------


async def _resolve_accession(
    session: AsyncSession,
    search_term: str,
    study_accession: str,
    config: dict,
) -> tuple[str, str] | None:
    """Resolve a human-readable term to a database accession.

    Step 1: SQL LIKE match on configured search columns.
    Step 2: If 0 or 2+ matches, fall back to LLM disambiguation.

    Returns (accession, method) where method is "SQL" or "LLM", or None.
    """
    if not search_term or not study_accession:
        return None

    table = config["table"]
    id_col = config["id_col"]
    search_cols = config["search_cols"]
    all_cols = config["all_cols"]

    # Step 1: SQL keyword match
    like_clauses = " OR ".join(f"{col} LIKE :pattern" for col in search_cols)
    sql = text(
        f"SELECT {all_cols} "
        f"FROM {table} "
        f"WHERE ({like_clauses}) "
        f"  AND study_accession = :study_accession"
    )
    pattern = f"%{search_term}%"
    result = await session.execute(
        sql, {"pattern": pattern, "study_accession": study_accession}
    )
    rows = [dict(zip(result.keys(), row)) for row in result.fetchall()]

    if len(rows) == 1:
        accession = rows[0][id_col]
        logger.info(
            "%s resolved via SQL: %r → %s", id_col, search_term, accession,
        )
        return (accession, "SQL")

    # Step 2: LLM fallback — fetch all candidates for the study
    logger.info(
        "SQL match returned %d rows for %r; falling back to LLM",
        len(rows), search_term,
    )
    all_result = await session.execute(
        text(
            f"SELECT {all_cols} "
            f"FROM {table} "
            f"WHERE study_accession = :study_accession"
        ),
        {"study_accession": study_accession},
    )
    all_candidates = [
        dict(zip(all_result.keys(), row)) for row in all_result.fetchall()
    ]

    if not all_candidates:
        logger.warning("No %s rows found for study %s", table, study_accession)
        return None

    resolved = await _llm_resolve(search_term, all_candidates, config)
    if resolved is not None:
        return (resolved, "LLM")
    return None


async def _llm_resolve(
    search_term: str, candidates: list[dict], config: dict,
) -> str | None:
    """Ask the LLM to pick the best-matching candidate."""
    id_col = config["id_col"]
    candidates_text = json.dumps(candidates, indent=2)
    prompt = config["llm_prompt"].format(
        candidates=candidates_text, search_term=search_term,
    )

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": config["llm_system"]},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )

    answer = response.choices[0].message.content.strip()
    logger.info("LLM %s resolution: %r → %r", id_col, search_term, answer)

    if answer.upper() == "NONE":
        return None

    valid_ids = {c[id_col] for c in candidates}
    if answer in valid_ids:
        return answer

    # Try to extract an accession from a verbose response
    for candidate_id in valid_ids:
        if candidate_id in answer:
            return candidate_id

    logger.warning("LLM returned unrecognized %s: %r", id_col, answer)
    return None


# ---------------------------------------------------------------------------
# Public resolver helpers (thin wrappers for backward compat & clarity)
# ---------------------------------------------------------------------------


async def resolve_arm_accession(
    session: AsyncSession, cohort: str, study_accession: str,
) -> tuple[str, str] | None:
    """Resolve a cohort name → arm_accession."""
    return await _resolve_accession(session, cohort, study_accession, _ARM_CONFIG)


async def resolve_experiment_accession(
    session: AsyncSession, assay_method: str, study_accession: str,
) -> tuple[str, str] | None:
    """Resolve an assay method → experiment_accession."""
    return await _resolve_accession(session, assay_method, study_accession, _EXPERIMENT_CONFIG)


# ---------------------------------------------------------------------------
# SQL query builder
# ---------------------------------------------------------------------------


def _build_query(group: dict) -> tuple[str, dict]:
    """Build a single SQL query for a participant group.

    Returns (expsample_accession, biosample_accession, subject_accession)
    using the join path: expsample → expsample_2_biosample → biosample.
    """
    params: dict = {}

    query = (
        "SELECT DISTINCT\n"
        "  es.expsample_accession,\n"
        "  b.biosample_accession,\n"
        "  b.subject_accession\n"
        "FROM expsample es\n"
        "  JOIN expsample_2_biosample e2b ON e2b.expsample_accession = es.expsample_accession\n"
        "  JOIN biosample b ON b.biosample_accession = e2b.biosample_accession\n"
        "  LEFT JOIN immune_exposure ie ON ie.subject_accession = b.subject_accession\n"
        "WHERE 1=1"
    )

    for spec in OPTIONAL_FILTERS:
        value = group.get(spec["field"], "")
        if value:
            query += f"\n  AND {spec['sql']}"
            params[spec["field"]] = value

    # arm_accession requires an extra JOIN, handled separately
    arm_accession = group.get("arm_accession", "")
    if arm_accession:
        query += "\n  AND b.subject_accession IN (SELECT a2s.subject_accession FROM arm_2_subject a2s WHERE a2s.arm_accession = :arm_accession)"
        params["arm_accession"] = arm_accession

    query += "\nORDER BY b.subject_accession"

    return query, params


# ---------------------------------------------------------------------------
# High-level pipeline: resolve all fields then build queries
# ---------------------------------------------------------------------------


async def _resolve_group(
    group: dict,
    study_accession: str | None,
    session_factory,
) -> dict:
    """Resolve accessions and build SQL for a single participant group.

    Opens its own session so it can run safely alongside other groups in
    asyncio.gather (each aiomysql connection is not concurrency-safe).
    """
    group = dict(group)  # shallow copy — avoid mutating the caller's dict
    group_id = group.get("group_id")
    resolution_log: dict = {}

    cohort = group.get("cohort", "")
    assay_method = group.get("assay_method", "")

    # Each resolver gets its own session — a single AsyncSession wraps one
    # connection and cannot handle concurrent execute() calls.
    async def _arm():
        if not (cohort and study_accession):
            return None
        async with session_factory() as s:
            return await resolve_arm_accession(s, cohort, study_accession)

    async def _exp():
        if not (assay_method and study_accession):
            return None
        async with session_factory() as s:
            return await resolve_experiment_accession(s, assay_method, study_accession)

    arm_result, exp_result = await asyncio.gather(_arm(), _exp())

    if arm_result:
        arm_acc, method = arm_result
        group["arm_accession"] = arm_acc
        resolution_log["arm"] = {"accession": arm_acc, "method": method}
        logger.info(
            "Resolved cohort %r → arm_accession %s for group %s",
            cohort, arm_acc, group_id,
        )

    if exp_result:
        exp_acc, method = exp_result
        group["experiment_accession"] = exp_acc
        resolution_log["experiment"] = {"accession": exp_acc, "method": method}
        logger.info(
            "Resolved assay_method %r → experiment_accession %s for group %s",
            assay_method, exp_acc, group_id,
        )

    if study_accession:
        group["study_accession"] = study_accession

    sql, params = _build_query(group)
    logger.info(
        "Built query for group %s (%s):\n  SQL: %s\n  Params: %s",
        group_id, group.get("group_name"), sql, params,
    )
    return {
        "group_id": group_id or 0,
        "group_name": group.get("group_name", ""),
        "sql": sql,
        "params": params,
        "resolution": resolution_log,
    }


async def resolve_and_build_queries(
    description_analysis: list[dict],
    study_accession: str | None,
    session_factory,
) -> list[dict]:
    """Resolve accessions and build SQL queries for all participant groups.

    Groups are processed **concurrently** via asyncio.gather; within each
    group arm + experiment resolution also run concurrently.  Each group
    opens its own AsyncSession to satisfy aiomysql's single-connection
    concurrency constraint.

    Returns list of dicts with group_id, group_name, sql, params, and
    resolution metadata, in the same order as description_analysis.
    """
    if not description_analysis:
        return []

    results = await asyncio.gather(*[
        _resolve_group(group, study_accession, session_factory)
        for group in description_analysis
    ])
    return list(results)


def build_subject_queries(description_analysis: list[dict]) -> list[dict]:
    """Build deterministic SQL queries from already-resolved group dicts.

    This is the sync-only query builder (no resolution). Useful when
    accessions have already been resolved externally or in tests.

    Returns list of dicts with group_id, group_name, sql, params.
    """
    if not description_analysis:
        return []

    queries = []
    for group in description_analysis:
        sql, params = _build_query(group)
        queries.append(
            {
                "group_id": group.get("group_id", 0),
                "group_name": group.get("group_name", ""),
                "sql": sql,
                "params": params,
            }
        )
        logger.info(
            "Built query for group %s (%s):\n  SQL: %s\n  Params: %s",
            group.get("group_id"), group.get("group_name"), sql, params,
        )

    return queries
