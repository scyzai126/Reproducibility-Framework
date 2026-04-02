"""Resolve accessions and build deterministic SQL for ImmPort subject queries.

Combines field resolution (arm, experiment) with SQL construction into a single
pipeline: resolve → build.  Each resolver uses a two-step strategy: SQL keyword
match first, LLM fallback for ambiguous cases.
"""

import asyncio
import json
import logging
import re
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_prompt_cache: dict[str, tuple[str, str]] = {}

_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


def _load_resolver_prompt(name: str) -> tuple[str, str]:
    """Load a resolver prompt file. Returns (system, user_template).
    Reads from disk each time so edits take effect without restart."""
    text = (_PROMPTS_DIR / f"resolver_{name}.txt").read_text(encoding="utf-8").strip()
    system, _, user = text.partition("\n---\n")
    return system.strip(), user.strip()

# ---------------------------------------------------------------------------
# View filter registry — each entry maps an LLM output field to a column
# in subject_data_view.
#
# Types:
#   "eq"   — exact match:   col = :field
#   "like" — partial match: col LIKE :field  (auto-wrapped in %)
#   "gte"  — lower bound:   col >= :field
#   "lte"  — upper bound:   col <= :field
#
# To add a new filter: append one entry. Nothing else needs changing.
# study_accession is always applied first (see _build_query).
# ---------------------------------------------------------------------------
VIEW_FILTERS = [
    # resolved accessions
    {"field": "arm_accession",        "col": "arm_accession",        "type": "eq"},
    {"field": "experiment_accession", "col": "experiment_accession", "type": "eq"},
    # biosample — tissue_type handled separately in _build_query (type vs subtype)
    # immune exposure
    {"field": "disease",              "col": "`condition`",             "type": "eq"},
    {"field": "disease_stage",        "col": "disease_stage_preferred", "type": "eq"},
    {"field": "exposure_process",     "col": "exposure_process",     "type": "eq"},
    # subject demographics (ci = case-insensitive LIKE for robustness)
    {"field": "gender",               "col": "gender",               "type": "ci"},
    {"field": "ethnicity",            "col": "ethnicity",            "type": "ci"},
    {"field": "race",                 "col": "race",                 "type": "ci"},
    # planned visit — eq match on resolved accession
    {"field": "planned_visit_accession", "col": "planned_visit_accession", "type": "eq"},
    # age range — inclusive bounds in years
    {"field": "age_min", "col": "min_subject_age_in_years", "type": "gte"},
    {"field": "age_max", "col": "max_subject_age_in_years", "type": "lte"},
]

# ---------------------------------------------------------------------------
# Resolver configurations
# ---------------------------------------------------------------------------
def _make_config(
    prompt_name: str,
    table: str,
    id_col: str,
    search_cols: list[str],
    all_cols: str,
) -> dict:
    """Build a resolver config dict, loading prompts from file at first use."""
    return {
        "table": table,
        "id_col": id_col,
        "search_cols": search_cols,
        "all_cols": all_cols,
        "prompt_name": prompt_name,
    }


_ARM_CONFIG = _make_config(
    "arm", "arm_or_cohort", "arm_accession",
    ["name", "description"], "arm_accession, name, description",
)

_EXPERIMENT_CONFIG = _make_config(
    "experiment", "experiment", "experiment_accession",
    ["name", "measurement_technique"], "experiment_accession, name, measurement_technique",
)

_PLANNED_VISIT_CONFIG = _make_config(
    "planned_visit", "planned_visit", "planned_visit_accession",
    ["name"], "planned_visit_accession, name, min_start_day, max_start_day",
)

_TISSUE_TYPE_LLM_CONFIG = _make_config(
    "tissue_type", "biosample", "type",
    ["type"], "type",
)


_CONDITION_LLM_CONFIG = _make_config(
    "condition", "immune_exposure", "disease_preferred",
    ["disease_preferred"], "disease_preferred",
)

_DISEASE_STAGE_LLM_CONFIG = _make_config(
    "disease_stage", "immune_exposure", "disease_stage_preferred",
    ["disease_stage_preferred"], "disease_stage_preferred",
)


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
    system_prompt, user_template = _load_resolver_prompt(config["prompt_name"])
    candidates_text = json.dumps(candidates, indent=2)
    prompt = user_template.format(candidates=candidates_text, search_term=search_term)

    client = _get_openai_client()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
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


async def resolve_planned_visit_accession(
    session: AsyncSession, time_point: str, study_accession: str,
) -> tuple[str, str] | None:
    """Resolve a time point string → planned_visit_accession."""
    return await _resolve_accession(session, time_point, study_accession, _PLANNED_VISIT_CONFIG)


async def resolve_tissue_type(
    session: AsyncSession, tissue_type: str, study_accession: str,
) -> tuple[str, str, str] | None:
    """Resolve a tissue/sample type → (canonical_value, method, matched_col).

    Step 1: LIKE search on biosample.type — return on single hit.
    Step 2: LIKE search on biosample.subtype — return on single hit.
    Step 3: LLM fallback over all distinct type + subtype values combined.
    matched_col is "type" or "subtype".
    """
    if not tissue_type or not study_accession:
        return None

    pattern = f"%{tissue_type}%"

    # ── Step 1: fuzzy search on biosample.type ────────────────────────────
    result = await session.execute(
        text(
            "SELECT DISTINCT type FROM biosample "
            "WHERE study_accession = :sa AND type LIKE :pattern AND type IS NOT NULL"
        ),
        {"sa": study_accession, "pattern": pattern},
    )
    rows = [r[0] for r in result.fetchall() if r[0]]
    if len(rows) == 1:
        logger.info("Tissue type resolved via SQL (type): %r → %r", tissue_type, rows[0])
        return (rows[0], "SQL", "type")

    # ── Step 2: fuzzy search on biosample.subtype ─────────────────────────
    logger.info("SQL type match returned %d rows for %r; trying subtype", len(rows), tissue_type)
    result = await session.execute(
        text(
            "SELECT DISTINCT subtype FROM biosample "
            "WHERE study_accession = :sa AND subtype LIKE :pattern AND subtype IS NOT NULL"
        ),
        {"sa": study_accession, "pattern": pattern},
    )
    rows = [r[0] for r in result.fetchall() if r[0]]
    if len(rows) == 1:
        logger.info("Tissue type resolved via SQL (subtype): %r → %r", tissue_type, rows[0])
        return (rows[0], "SQL", "subtype")

    # ── Step 3: LLM fallback over combined type + subtype values ──────────
    logger.info("SQL subtype match returned %d rows for %r; falling back to LLM", len(rows), tissue_type)
    all_result = await session.execute(
        text(
            "SELECT DISTINCT type, subtype FROM biosample "
            "WHERE study_accession = :sa AND (type IS NOT NULL OR subtype IS NOT NULL)"
        ),
        {"sa": study_accession},
    )
    candidates = []
    for row in all_result.fetchall():
        if row[0]:
            candidates.append({"value": row[0], "col": "type"})
        if row[1]:
            candidates.append({"value": row[1], "col": "subtype"})
    # deduplicate
    seen = set()
    candidates = [c for c in candidates if (c["value"], c["col"]) not in seen and not seen.add((c["value"], c["col"]))]

    if not candidates:
        logger.warning("No biosample type/subtype values found for study %s", study_accession)
        return None

    system_prompt, user_template = _load_resolver_prompt("tissue_type")
    prompt = user_template.format(candidates=json.dumps(candidates, indent=2), search_term=tissue_type)
    client = _get_openai_client()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=50,
    )
    answer = response.choices[0].message.content.strip()
    if answer.upper() == "NONE" or "|" not in answer:
        logger.warning("LLM returned no tissue match for %r: %r", tissue_type, answer)
        return None

    value, _, col = answer.partition("|")
    value = value.strip()
    col = col.strip()
    if col not in ("type", "subtype") or not value:
        logger.warning("LLM returned unexpected tissue format %r for %r", answer, tissue_type)
        return None

    logger.info("Tissue type resolved via LLM (%s): %r → %r", col, tissue_type, value)
    return (value, "LLM", col)


async def resolve_condition(
    session: AsyncSession, condition: str, study_accession: str,
) -> tuple[str, str] | None:
    """Resolve a condition/disease name → canonical condition value in subject_data_view.

    Step 1: LIKE search on condition for this study.
    Step 2: LLM fallback using all distinct condition values for the study.
    """
    if not condition or not study_accession:
        return None

    # Step 1: LIKE match directly on the view
    result = await session.execute(
        text(
            "SELECT DISTINCT `condition` FROM subject_data_view "
            "WHERE study_accession = :sa "
            "AND `condition` LIKE :pattern "
            "AND `condition` IS NOT NULL"
        ),
        {"sa": study_accession, "pattern": f"%{condition}%"},
    )
    rows = [r[0] for r in result.fetchall() if r[0]]

    if len(rows) == 1:
        logger.info("Condition resolved via SQL: %r → %r", condition, rows[0])
        return (rows[0], "SQL")

    # Step 2: LLM fallback — fetch all distinct condition values for the study
    logger.info(
        "SQL condition match returned %d rows for %r; falling back to LLM",
        len(rows), condition,
    )
    all_result = await session.execute(
        text(
            "SELECT DISTINCT `condition` FROM subject_data_view "
            "WHERE study_accession = :sa AND `condition` IS NOT NULL"
        ),
        {"sa": study_accession},
    )
    all_candidates = [
        {"disease_preferred": r[0]} for r in all_result.fetchall() if r[0]
    ]

    if not all_candidates:
        logger.warning("No condition values found for study %s", study_accession)
        return None

    resolved = await _llm_resolve(condition, all_candidates, _CONDITION_LLM_CONFIG)
    if resolved:
        return (resolved, "LLM")
    return None


async def resolve_disease_stage(
    session: AsyncSession, condition: str, study_accession: str,
) -> tuple[str, str] | None:
    """Resolve a severity label → canonical disease_stage_preferred value in subject_data_view.

    Used for severity study designs instead of resolve_condition.
    Step 1: LIKE search on disease_stage_preferred for this study.
    Step 2: LLM fallback using all distinct disease_stage values for the study.
    """
    if not condition or not study_accession:
        return None

    # Step 1: LIKE match directly on the view
    result = await session.execute(
        text(
            "SELECT DISTINCT disease_stage_preferred FROM subject_data_view "
            "WHERE study_accession = :sa "
            "AND disease_stage_preferred LIKE :pattern "
            "AND disease_stage_preferred IS NOT NULL"
        ),
        {"sa": study_accession, "pattern": f"%{condition}%"},
    )
    rows = [r[0] for r in result.fetchall() if r[0]]

    if len(rows) == 1:
        logger.info("Disease stage resolved via SQL: %r → %r", condition, rows[0])
        return (rows[0], "SQL")

    # Step 2: LLM fallback
    logger.info(
        "SQL disease_stage match returned %d rows for %r; falling back to LLM",
        len(rows), condition,
    )
    all_result = await session.execute(
        text(
            "SELECT DISTINCT disease_stage_preferred FROM subject_data_view "
            "WHERE study_accession = :sa AND disease_stage_preferred IS NOT NULL"
        ),
        {"sa": study_accession},
    )
    all_candidates = [
        {"disease_stage_preferred": r[0]} for r in all_result.fetchall() if r[0]
    ]

    if not all_candidates:
        logger.warning("No disease_stage_preferred values found for study %s", study_accession)
        return None

    resolved = await _llm_resolve(condition, all_candidates, _DISEASE_STAGE_LLM_CONFIG)
    if resolved:
        return (resolved, "LLM")
    return None


async def fetch_planned_visits(session: AsyncSession, study_accession: str) -> list[dict]:
    """Fetch all planned_visit rows for a study from the DB."""
    result = await session.execute(
        text(
            "SELECT planned_visit_accession, name "
            "FROM planned_visit WHERE study_accession = :sa"
        ),
        {"sa": study_accession},
    )
    return [dict(zip(result.keys(), row)) for row in result.fetchall()]


def expand_groups_by_planned_visits(
    groups: list[dict], planned_visits: list[dict]
) -> list[dict]:
    """Expand groups with non-empty time_point into one copy per planned visit.

    Groups with empty or absent time_point pass through unchanged.
    Each expanded copy gets planned_visit_accession + planned_visit_name set
    and the time_point field removed.
    """
    expanded: list[dict] = []
    for group in groups:
        time_point = group.get("time_point")
        if time_point:  # non-empty list signals a time-series study
            for pv in planned_visits:
                copy = {k: v for k, v in group.items() if k != "time_point"}
                copy["planned_visit_accession"] = pv["planned_visit_accession"]
                copy["planned_visit_name"] = pv["name"]
                expanded.append(copy)
        else:
            expanded.append(group)
    return expanded


# ---------------------------------------------------------------------------
# SQL query builder
# ---------------------------------------------------------------------------


def _build_query(group: dict) -> tuple[str, dict]:
    """Build a SELECT DISTINCT query against subject_data_view for one group.

    study_accession is always applied first to let MySQL use idx_biosample_study
    before evaluating any other filter.
    """
    params: dict = {}
    where_clauses: list[str] = []

    # study_accession always goes first for index efficiency
    study_accession = group.get("study_accession", "")
    if study_accession:
        where_clauses.append("sdv.study_accession = :study_accession")
        params["study_accession"] = study_accession

    # remaining filters from the registry
    for spec in VIEW_FILTERS:
        value = group.get(spec["field"]) or ""
        if not value:
            continue
        col = spec["col"]
        ftype = spec["type"]
        param_key = spec["field"]

        if ftype == "eq":
            where_clauses.append(f"sdv.{col} = :{param_key}")
            params[param_key] = value
        elif ftype == "like":
            where_clauses.append(f"sdv.{col} LIKE :{param_key}")
            params[param_key] = f"%{value}%"
        elif ftype == "ci":
            # case-insensitive match — handles LLM capitalisation variance
            where_clauses.append(f"LOWER(sdv.{col}) = LOWER(:{param_key})")
            params[param_key] = value
        elif ftype == "fuzzy":
            # fuzzy LIKE — replaces hyphens/spaces with % so "whole-blood" matches "Whole blood"
            fuzzy_val = re.sub(r"[-\s]+", "%", value.strip())
            where_clauses.append(f"LOWER(sdv.{col}) LIKE LOWER(:{param_key})")
            params[param_key] = f"%{fuzzy_val}%"
        elif ftype == "gte":
            where_clauses.append(f"sdv.{col} >= :{param_key}")
            params[param_key] = value
        elif ftype == "lte":
            where_clauses.append(f"sdv.{col} <= :{param_key}")
            params[param_key] = value

    # tissue_type: column depends on which biosample column matched during resolution
    tissue_val = group.get("tissue_type") or ""
    if tissue_val:
        sdv_col = "tissue_subtype" if group.get("tissue_matched_col") == "subtype" else "tissue_type"
        where_clauses.append(f"sdv.{sdv_col} = :tissue_type")
        params["tissue_type"] = tissue_val

    sql = (
        "SELECT DISTINCT\n"
        "  sdv.expsample_accession,\n"
        "  sdv.biosample_accession,\n"
        "  sdv.subject_accession\n"
        "FROM subject_data_view sdv\n"
        "WHERE " + "\n  AND ".join(where_clauses) if where_clauses else
        "SELECT DISTINCT sdv.expsample_accession, sdv.biosample_accession, sdv.subject_accession "
        "FROM subject_data_view sdv WHERE 1=1"
    )

    sql += "\nORDER BY sdv.subject_accession"

    return sql, params


def _parse_age_range(age: str | None) -> tuple[float | None, float | None]:
    """Parse an age string from the LLM into (min, max) float years.

    Handles formats like:
      "18-65"       → (18, 65)
      "18–65"       → (18, 65)
      "median 45"   → (None, None)   # can't bound-filter on a median
      "65+"         → (65, None)
      "< 18"        → (None, 18)
      "45"          → (45, 45)
    """
    if not age:
        return None, None
    age = age.strip()
    # Range: "18-65" or "18–65"
    m = re.match(r"^(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)$", age)
    if m:
        return float(m.group(1)), float(m.group(2))
    # "65+" or ">65"
    m = re.match(r"^[>≥]?\s*(\d+(?:\.\d+)?)\s*\+?$", age)
    if m and (age.endswith("+") or age.startswith(">") or age.startswith("≥")):
        return float(m.group(1)), None
    # "<18" or "≤18"
    m = re.match(r"^[<≤]\s*(\d+(?:\.\d+)?)$", age)
    if m:
        return None, float(m.group(1))
    # Single number
    m = re.match(r"^(\d+(?:\.\d+)?)$", age)
    if m:
        v = float(m.group(1))
        return v, v
    return None, None


# ---------------------------------------------------------------------------
# High-level pipeline: resolve all fields then build queries
# ---------------------------------------------------------------------------


async def _resolve_group(
    group: dict,
    study_accession: str | None,
    session_factory,
) -> list[dict]:
    """Resolve accessions and build SQL for a single participant group.

    Returns a list of query dicts — one per resolved planned_visit when
    time_point is present, otherwise a single-element list.

    Opens its own session per resolver so it can run safely alongside other
    groups in asyncio.gather (each aiomysql connection is not concurrency-safe).
    """
    group = dict(group)  # shallow copy — avoid mutating the caller's dict
    group_id = group.get("group_id")
    resolution_log: dict = {}

    cohort = group.get("cohort", "")
    assay_method = group.get("assay_method", "")
    disease = group.get("disease", "") or ""
    disease_stage = group.get("disease_stage", "") or ""
    tissue_type = group.get("tissue_type", "") or ""
    study_design = group.get("study_design", "")
    time_point: str = group.pop("time_point", None) or ""
    age = group.get("age")
    comparison = group.get("comparison") or []

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

    async def _cond():
        if study_design == "longitudinal" or not study_accession:
            return None
        async with session_factory() as s:
            if study_design == "severity" and disease_stage:
                return await resolve_disease_stage(s, disease_stage, study_accession)
            if disease:
                return await resolve_condition(s, disease, study_accession)
            return None

    async def _tissue():
        if not (tissue_type and study_accession):
            return None
        async with session_factory() as s:
            return await resolve_tissue_type(s, tissue_type, study_accession)

    async def _pv():
        if not (time_point and study_accession):
            return None
        async with session_factory() as s:
            return await resolve_planned_visit_accession(s, time_point, study_accession)

    arm_result, exp_result, cond_result, tissue_result, pv_result = await asyncio.gather(
        _arm(), _exp(), _cond(), _tissue(), _pv()
    )

    if arm_result:
        arm_acc, method = arm_result
        group["arm_accession"] = arm_acc
        resolution_log["arm"] = {"accession": arm_acc, "method": method}
        logger.info("Resolved cohort %r → arm_accession %s for group %s", cohort, arm_acc, group_id)

    if exp_result:
        exp_acc, method = exp_result
        group["experiment_accession"] = exp_acc
        resolution_log["experiment"] = {"accession": exp_acc, "method": method}
        logger.info("Resolved assay_method %r → experiment_accession %s for group %s", assay_method, exp_acc, group_id)

    if cond_result:
        canonical, method = cond_result
        if study_design == "severity":
            group["disease_stage"] = canonical
            group["disease"] = ""
            resolution_log["disease_stage"] = {"value": canonical, "method": method}
            logger.info("Resolved disease_stage %r → %r for group %s", disease_stage, canonical, group_id)
        else:
            group["disease"] = canonical
            resolution_log["disease"] = {"value": canonical, "method": method}
            logger.info("Resolved disease %r → %r for group %s", disease, canonical, group_id)
    else:
        group["disease"] = ""

    if study_accession:
        group["study_accession"] = study_accession

    if tissue_result:
        resolved_tissue, method, matched_col = tissue_result
        group["tissue_type"] = resolved_tissue
        group["tissue_matched_col"] = matched_col
        resolution_log["tissue_type"] = {"value": resolved_tissue, "method": method, "matched_column": matched_col}
        logger.info("Resolved tissue_type %r → %r (column: %s) for group %s", tissue_type, resolved_tissue, matched_col, group_id)
    else:
        group["tissue_type"] = ""

    if pv_result:
        pv_acc, method = pv_result
        group["planned_visit_accession"] = pv_acc
        resolution_log["planned_visit"] = {"accession": pv_acc, "method": method}
        logger.info("Resolved time_point %r → planned_visit_accession %s for group %s", time_point, pv_acc, group_id)
    elif time_point:
        logger.warning("Could not resolve time_point %r for group %s — no planned_visit filter applied", time_point, group_id)

    # ── Build single query ────────────────────────────────────────────────────
    sql, params = _build_query(group)
    logger.info(
        "Built query for group %s:\n  SQL: %s\n  Params: %s",
        group_id, sql, params,
    )
    return [{
        "group_id": group_id or 0,
        "sql": sql,
        "params": params,
        "resolution": resolution_log,
        "planned_visit_name": time_point,
        "age": age,
        "comparison": comparison,
    }]



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

    Identical (search_term, resolver) pairs across groups are deduplicated:
    the first resolution is awaited and its result reused by all others,
    eliminating redundant DB queries and LLM calls.

    Returns list of dicts with group_id, sql, params, and
    resolution metadata, in the same order as description_analysis.
    """
    if not description_analysis:
        return []

    # Cache: (resolver_fn, search_term) → asyncio.Task so concurrent groups
    # that share the same term wait on the same underlying coroutine.
    _cache: dict[tuple, asyncio.Task] = {}

    def _cached(resolver_fn, search_term, *args):
        """Return a Task for resolver_fn(search_term, *args), reusing if already started."""
        key = (resolver_fn, search_term)
        if key not in _cache:
            _cache[key] = asyncio.ensure_future(resolver_fn(*args, search_term, study_accession))
        return _cache[key]

    async def _resolve_group_cached(group: dict) -> list[dict]:
        """Like _resolve_group but delegates to cached tasks for each resolver."""
        group = dict(group)
        group_id = group.get("group_id")
        resolution_log: dict = {}

        cohort       = group.get("cohort", "") or ""
        assay_method = group.get("assay_method", "") or ""
        disease      = group.get("disease", "") or ""
        disease_stage = group.get("disease_stage", "") or ""
        tissue_type  = group.get("tissue_type", "") or ""
        study_design = group.get("study_design", "")
        time_point   = group.pop("time_point", None) or ""
        age          = group.get("age")
        comparison   = group.get("comparison") or []

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

        async def _cond():
            if study_design == "longitudinal" or not study_accession:
                return None
            async with session_factory() as s:
                if study_design == "severity" and disease_stage:
                    return await resolve_disease_stage(s, disease_stage, study_accession)
                if disease:
                    return await resolve_condition(s, disease, study_accession)
            return None

        async def _tissue():
            if not (tissue_type and study_accession):
                return None
            async with session_factory() as s:
                return await resolve_tissue_type(s, tissue_type, study_accession)

        async def _pv():
            if not (time_point and study_accession):
                return None
            async with session_factory() as s:
                return await resolve_planned_visit_accession(s, time_point, study_accession)

        # Use cached tasks for arm, experiment, condition, tissue (commonly shared across groups)
        arm_key  = ("arm",  cohort)
        exp_key  = ("exp",  assay_method)
        cond_key = ("cond", disease_stage if study_design == "severity" else disease, study_design)
        tis_key  = ("tis",  tissue_type)
        pv_key   = ("pv",   time_point, study_design)

        def _get_or_create(key, coro_fn):
            if key not in _cache:
                _cache[key] = asyncio.ensure_future(coro_fn())
            return _cache[key]

        arm_result, exp_result, cond_result, tissue_result, pv_result = await asyncio.gather(
            _get_or_create(arm_key,  _arm),
            _get_or_create(exp_key,  _exp),
            _get_or_create(cond_key, _cond),
            _get_or_create(tis_key,  _tissue),
            _get_or_create(pv_key,   _pv),
        )

        if arm_result:
            arm_acc, method = arm_result
            group["arm_accession"] = arm_acc
            resolution_log["arm"] = {"accession": arm_acc, "method": method}
        if exp_result:
            exp_acc, method = exp_result
            group["experiment_accession"] = exp_acc
            resolution_log["experiment"] = {"accession": exp_acc, "method": method}
        if cond_result:
            canonical, method = cond_result
            if study_design == "severity":
                group["disease_stage"] = canonical
                group["disease"] = ""
                resolution_log["disease_stage"] = {"value": canonical, "method": method}
            else:
                group["disease"] = canonical
                resolution_log["disease"] = {"value": canonical, "method": method}
        else:
            group["disease"] = ""
        if study_accession:
            group["study_accession"] = study_accession
        if tissue_result:
            resolved_tissue, method, matched_col = tissue_result
            group["tissue_type"] = resolved_tissue
            group["tissue_matched_col"] = matched_col
            resolution_log["tissue_type"] = {"value": resolved_tissue, "method": method, "matched_column": matched_col}
        else:
            group["tissue_type"] = ""
        if pv_result:
            pv_acc, method = pv_result
            group["planned_visit_accession"] = pv_acc
            resolution_log["planned_visit"] = {"accession": pv_acc, "method": method}

        age_min, age_max = _parse_age_range(age)
        if age_min is not None:
            group["age_min"] = age_min
            resolution_log["age_min"] = {"value": age_min, "method": "parsed"}
        if age_max is not None:
            group["age_max"] = age_max
            resolution_log["age_max"] = {"value": age_max, "method": "parsed"}

        sql, params = _build_query(group)
        return [{
            "group_id": group_id or 0,
            "sql": sql,
            "params": params,
            "resolution": resolution_log,
            "planned_visit_name": time_point,
            "age": age,
            "comparison": comparison,
        }]

    nested = await asyncio.gather(*[
        _resolve_group_cached(group)
        for group in description_analysis
    ])
    return [item for sublist in nested for item in sublist]


def build_subject_queries(description_analysis: list[dict]) -> list[dict]:
    """Build deterministic SQL queries from already-resolved group dicts.

    This is the sync-only query builder (no resolution). Useful when
    accessions have already been resolved externally or in tests.

    Returns list of dicts with group_id, sql, params.
    """
    if not description_analysis:
        return []

    queries = []
    for group in description_analysis:
        sql, params = _build_query(group)
        queries.append(
            {
                "group_id": group.get("group_id", 0),
                "sql": sql,
                "params": params,
            }
        )
        logger.info(
            "Built query for group %s:\n  SQL: %s\n  Params: %s",
            group.get("group_id"), sql, params,
        )

    return queries
