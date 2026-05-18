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
# Functional marker extraction helpers
# ---------------------------------------------------------------------------

# Matches cytokine/activation markers with a +/- suffix in cell_type strings.
# Intentionally excludes lineage markers like CD4, CD8 which are not stored
# in biosample.description.
_FUNCTIONAL_MARKER_RE = re.compile(
    r'\b('
    r'IFN[- ]?(?:[αβγ]|alpha|beta|gamma|g)'
    r'|TNF[- ]?(?:α|alpha|a)?'
    r'|IL-?\d+'
    r'|perforin'
    r'|granzyme\s*[A-Za-z]?'
    r'|Ki-?67'
    r'|PD-?[L1]?\d*'
    r'|LAG-?3|TIM-?3|CTLA-?4'
    r')\s*([+-])',
    re.I,
)


def _split_multi_tissue(tissue_type: str) -> list[str]:
    """Split a comma/semicolon/and-separated tissue string into individual tokens.

    Returns a list with a single element when the string contains no separator,
    so callers can use len() > 1 to detect the multi-tissue case.
    """
    tokens = re.split(r'\s*[,;]\s*|\s+and\s+', tissue_type, flags=re.I)
    return [t.strip() for t in tokens if t.strip()]


def _extract_functional_marker(cell_type: str) -> str | None:
    """Return the first functional marker token (e.g. 'IFNγ+') from a cell_type string."""
    m = _FUNCTIONAL_MARKER_RE.search(cell_type)
    if m:
        return m.group(0).strip()
    return None


def _normalize_marker_for_like(marker: str) -> str:
    """Normalize a functional marker to ASCII so LIKE search covers common spellings.

    'IFNγ+' and 'IFN-gamma+' both become 'IFNg+'.
    """
    s = marker.strip()
    s = re.sub(r'IFN[- ]?[γΓ]', 'IFNg', s)
    s = re.sub(r'IFN[- ]?gamma', 'IFNg', s, flags=re.I)
    s = re.sub(r'IFN[- ]?beta',  'IFNb', s, flags=re.I)
    s = re.sub(r'IFN[- ]?alpha', 'IFNa', s, flags=re.I)
    s = re.sub(r'TNF[- ]?[αΑ]', 'TNFa', s)
    s = re.sub(r'TNF[- ]?alpha', 'TNFa', s, flags=re.I)
    return s


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

_VIEW_PLACEMENT_SCAN_SPECS = [
    {"placement": "disease_stage", "column": "disease_stage_preferred", "value_key": "value"},
    {"placement": "disease", "column": "`condition`", "value_key": "value"},
    {"placement": "tissue_type", "column": "tissue_type", "value_key": "value"},
    {"placement": "tissue_type", "column": "tissue_subtype", "value_key": "value", "matched_col": "subtype"},
    {"placement": "gender", "column": "gender", "value_key": "value"},
    {"placement": "ethnicity", "column": "ethnicity", "value_key": "value"},
    {"placement": "race", "column": "race", "value_key": "value"},
]


# ---------------------------------------------------------------------------
# Generic resolver (SQL LIKE → LLM fallback)
# ---------------------------------------------------------------------------


async def _resolve_accession(
    session: AsyncSession,
    search_term: str,
    study_accession: str,
    config: dict,
    claim_text: str | None = None,
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

    resolved = await _llm_resolve(search_term, all_candidates, config, claim_text=claim_text)
    if resolved is not None:
        return (resolved, "LLM")
    return None


async def _llm_resolve(
    search_term: str, candidates: list[dict], config: dict,
    claim_text: str | None = None,
) -> str | None:
    """Ask the LLM to pick the best-matching candidate."""
    id_col = config["id_col"]
    system_prompt, user_template = _load_resolver_prompt(config["prompt_name"])
    candidates_text = json.dumps(candidates, indent=2)
    prompt = user_template.format(candidates=candidates_text, search_term=search_term)
    if claim_text:
        prompt += f"\n\nOriginal claim for context:\n{claim_text}"

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
    claim_text: str | None = None,
) -> tuple[str, str] | None:
    """Resolve a cohort name → arm_accession."""
    return await _resolve_accession(session, cohort, study_accession, _ARM_CONFIG, claim_text=claim_text)


async def resolve_experiment_accession(
    session: AsyncSession, assay_method: str, study_accession: str,
    claim_text: str | None = None,
) -> tuple[str, str] | None:
    """Resolve an assay method → experiment_accession."""
    return await _resolve_accession(session, assay_method, study_accession, _EXPERIMENT_CONFIG, claim_text=claim_text)


async def get_assay_method_for_experiment(
    session: AsyncSession, experiment_accession: str,
) -> str | None:
    """Look up measurement_technique for a resolved experiment_accession."""
    result = await session.execute(
        text("SELECT measurement_technique FROM experiment WHERE experiment_accession = :acc LIMIT 1"),
        {"acc": experiment_accession},
    )
    row = result.fetchone()
    return row[0] if row and row[0] else None


def _parse_time_point_to_range(time_point: str) -> tuple[float, float | None] | None:
    """Extract a (low, high) day range from a natural-language time_point string.

    Returns (low, high) where high is None for open-ended ranges (e.g. "8+ days").
    Returns None when no numeric day information is found (fall through to LLM).

    Examples:
      "4-7 days post fever onset"  → (4.0, 7.0)
      "4 to 7 days"                → (4.0, 7.0)
      "early (4-7 days PFO)"       → (4.0, 7.0)
      "8+ days"                    → (8.0, None)
      "≥8 days" / ">8 days"        → (8.0, None)
      "<7 days" / "within 7 days"  → (0.0, 7.0)
      "day 14" / "14 days"         → (14.0, 14.0)
      "baseline"                   → (0.0, 0.0)
    """
    s = time_point.strip().lower()

    # "baseline" → day 0
    if re.search(r'\bbaseline\b', s):
        return (0.0, 0.0)

    # Range: "4-7 days", "4 to 7 days", "4–7 days" (en-dash)
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*days?', s)
    if m:
        return (float(m.group(1)), float(m.group(2)))

    # Open upper bound: "8+ days", "≥8 days", ">8 days", "8 or more days"
    m = re.search(r'(?:[≥>]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*\+)\s*days?', s)
    if m:
        return (float(m.group(1) or m.group(2)), None)
    m = re.search(r'(\d+(?:\.\d+)?)\s*days?\s+or\s+more', s)
    if m:
        return (float(m.group(1)), None)

    # Open lower bound: "<7 days", "≤7 days", "within 7 days", "up to 7 days"
    m = re.search(r'(?:[<≤]|within|up\s+to)\s*(\d+(?:\.\d+)?)\s*days?', s)
    if m:
        return (0.0, float(m.group(1)))

    # Exact: "day 14", "14 days", "day14"
    m = re.search(r'(?:day\s*)?(\d+(?:\.\d+)?)\s*days?', s)
    if m:
        v = float(m.group(1))
        return (v, v)

    return None


async def resolve_planned_visit_accession(
    session: AsyncSession, time_point: str, study_accession: str,
    claim_text: str | None = None,
) -> list[tuple[str, str]] | None:
    """Resolve a time point string → list of (planned_visit_accession, method) tuples.

    Tries natural-language range parsing first, then the legacy "Xdays<time<Ydays"
    format, then falls back to SQL LIKE → LLM for named visits.
    """
    if not time_point:
        return None

    # ── Step 1: parse natural-language day ranges ─────────────────────────────
    parsed = _parse_time_point_to_range(time_point)

    # ── Step 2: legacy machine format "Xdays<time<Ydays" ─────────────────────
    if parsed is None:
        range_m = re.match(r'^(\d+(?:\.\d+)?)days<time<(\d+(?:\.\d+)?)days$', time_point.strip())
        if range_m:
            parsed = (float(range_m.group(1)), float(range_m.group(2)))

    # ── Step 3: run range query if we have bounds ─────────────────────────────
    if parsed is not None:
        low, high = parsed
        result = await session.execute(
            text(
                "SELECT planned_visit_accession, name, min_start_day "
                "FROM planned_visit WHERE study_accession = :sa"
            ),
            {"sa": study_accession},
        )
        rows = [dict(zip(result.keys(), row)) for row in result.fetchall()]

        def _in_range(day_val) -> bool:
            if day_val is None:
                return False
            d = float(day_val)
            if high is None:
                return d >= low
            return low <= d <= high

        matches = [r for r in rows if _in_range(r.get("min_start_day"))]
        if not matches:
            logger.warning("No planned visits found in range %s for study %s", time_point, study_accession)
            return None
        logger.info(
            "Range %r → [%s, %s] matched %d planned visit(s) for study %s",
            time_point, low, high, len(matches), study_accession,
        )
        return [(r["planned_visit_accession"], "range") for r in matches]

    # ── Step 4: exact match via SQL LIKE → LLM ───────────────────────────────
    result = await _resolve_accession(session, time_point, study_accession, _PLANNED_VISIT_CONFIG, claim_text=claim_text)
    if result is None:
        return None
    return [result]


async def resolve_tissue_type(
    session: AsyncSession, tissue_type: str, study_accession: str,
    claim_text: str | None = None,
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
    if claim_text:
        prompt += f"\n\nOriginal claim for context:\n{claim_text}"
    client = _get_openai_client()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_completion_tokens=50,
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


async def resolve_tissue_and_cell_type(
    session: AsyncSession,
    tissue_type: str,
    cell_type: str,
    study_accession: str,
    claim_text: str | None = None,
) -> dict | None:
    """Resolve tissue_type and cell_type against biosample.type / biosample.subtype.

    Tries four strategies in order and returns a dict with optional keys
    ``type_value`` (maps to sdv.tissue_type) and ``subtype_value``
    (maps to sdv.tissue_subtype), plus ``method``.

    Strategy 1 — two-column: type LIKE tissue_type AND subtype LIKE cell_type.
    Strategy 2 — cell_type as type: type LIKE cell_type.
    Strategy 3 — tissue_type resolves to type, cell_type resolves to subtype.
    Strategy 4 — fallback: resolve either term alone via resolve_tissue_type().
    """
    tissue_pat = f"%{tissue_type}%"
    cell_pat = f"%{cell_type}%"

    # Early check: if the study has no subtype data at all, skip all subtype
    # strategies and resolve tissue_type alone.
    subtype_count_res = await session.execute(
        text(
            "SELECT COUNT(*) FROM biosample "
            "WHERE study_accession = :sa AND subtype IS NOT NULL"
        ),
        {"sa": study_accession},
    )
    has_subtypes = (subtype_count_res.scalar() or 0) > 0
    if not has_subtypes:
        logger.info(
            "cell_type dropped: study %s has no subtype data — resolving tissue_type only",
            study_accession,
        )
        tissue_result = await resolve_tissue_type(session, tissue_type, study_accession, claim_text=claim_text)
        if tissue_result:
            val, method, col = tissue_result
            key = "type_value" if col == "type" else "subtype_value"
            return {key: val, "method": method, "cell_type_dropped_reason": "no subtype data in study"}
        return None

    # Strategy 1: both columns simultaneously
    count_res = await session.execute(
        text(
            "SELECT COUNT(*) FROM biosample "
            "WHERE study_accession = :sa "
            "AND type LIKE :tp AND subtype LIKE :cp AND subtype IS NOT NULL"
        ),
        {"sa": study_accession, "tp": tissue_pat, "cp": cell_pat},
    )
    if (count_res.scalar() or 0) > 0:
        type_rows = await session.execute(
            text(
                "SELECT DISTINCT type FROM biosample "
                "WHERE study_accession = :sa AND type LIKE :tp AND subtype LIKE :cp AND subtype IS NOT NULL"
            ),
            {"sa": study_accession, "tp": tissue_pat, "cp": cell_pat},
        )
        sub_rows = await session.execute(
            text(
                "SELECT DISTINCT subtype FROM biosample "
                "WHERE study_accession = :sa AND type LIKE :tp AND subtype LIKE :cp AND subtype IS NOT NULL"
            ),
            {"sa": study_accession, "tp": tissue_pat, "cp": cell_pat},
        )
        type_vals = [r[0] for r in type_rows.fetchall() if r[0]]
        sub_vals  = [r[0] for r in sub_rows.fetchall() if r[0]]
        if len(type_vals) == 1 and len(sub_vals) == 1:
            logger.info(
                "Two-col match: tissue_type %r→%r, cell_type %r→%r",
                tissue_type, type_vals[0], cell_type, sub_vals[0],
            )
            return {"type_value": type_vals[0], "subtype_value": sub_vals[0], "method": "SQL_two_col"}

    # Strategy 2: cell_type matches biosample.type directly
    cell_as_type = await session.execute(
        text(
            "SELECT DISTINCT type FROM biosample "
            "WHERE study_accession = :sa AND type LIKE :cp AND type IS NOT NULL"
        ),
        {"sa": study_accession, "cp": cell_pat},
    )
    cell_type_rows = [r[0] for r in cell_as_type.fetchall() if r[0]]
    if len(cell_type_rows) == 1:
        logger.info("cell_type as type: %r → %r", cell_type, cell_type_rows[0])
        return {"type_value": cell_type_rows[0], "method": "SQL_cell_as_type"}

    # Strategy 3: resolve tissue_type normally; if it lands on type, also resolve cell_type as subtype
    tissue_result = await resolve_tissue_type(session, tissue_type, study_accession, claim_text=claim_text)
    if tissue_result:
        val, method, col = tissue_result
        if col == "type":
            sub_res = await session.execute(
                text(
                    "SELECT DISTINCT subtype FROM biosample "
                    "WHERE study_accession = :sa AND subtype LIKE :cp AND subtype IS NOT NULL"
                ),
                {"sa": study_accession, "cp": cell_pat},
            )
            sub_vals = [r[0] for r in sub_res.fetchall() if r[0]]
            if len(sub_vals) == 1:
                logger.info(
                    "Split match: tissue_type %r→%r (type), cell_type %r→%r (subtype)",
                    tissue_type, val, cell_type, sub_vals[0],
                )
                return {"type_value": val, "subtype_value": sub_vals[0], "method": f"SQL_split({method})"}
            logger.info(
                "tissue_type resolved but cell_type subtype ambiguous (%d rows); tissue only",
                len(sub_vals),
            )
            return {"type_value": val, "method": method}
        return {"subtype_value": val, "method": method}

    # Strategy 4: resolve cell_type alone
    cell_result = await resolve_tissue_type(session, cell_type, study_accession, claim_text=claim_text)
    if cell_result:
        val, method, col = cell_result
        logger.info("cell_type resolved via tissue resolver: %r→%r (col=%s)", cell_type, val, col)
        key = "type_value" if col == "type" else "subtype_value"
        return {key: val, "method": f"fallback_cell({method})"}

    logger.warning(
        "resolve_tissue_and_cell_type: no match for tissue_type=%r, cell_type=%r in study %s",
        tissue_type, cell_type, study_accession,
    )
    return None


async def resolve_condition(
    session: AsyncSession, condition: str, study_accession: str,
    claim_text: str | None = None,
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

    resolved = await _llm_resolve(condition, all_candidates, _CONDITION_LLM_CONFIG, claim_text=claim_text)
    if resolved:
        return (resolved, "LLM")
    return None


async def resolve_biosample_description(
    session: AsyncSession, marker: str, study_accession: str,
) -> tuple[str, str] | None:
    """Resolve a functional marker (e.g. 'IFNγ+') to a LIKE value for biosample.description.

    Normalizes Unicode/ASCII variants then checks whether any biosample rows for
    the study match.  Returns (normalized_marker, method) for use as
    biosample_description LIKE '%normalized_marker%', or None if no match found.
    """
    if not marker or not study_accession:
        return None

    normalized = _normalize_marker_for_like(marker)
    pattern = f"%{normalized}%"

    result = await session.execute(
        text(
            "SELECT COUNT(*) FROM biosample "
            "WHERE study_accession = :sa AND description LIKE :pattern"
        ),
        {"sa": study_accession, "pattern": pattern},
    )
    count = result.scalar() or 0
    if count > 0:
        logger.info(
            "Biosample description marker %r → LIKE %r (%d rows) for study %s",
            marker, pattern, count, study_accession,
        )
        return (normalized, "SQL")

    # No rows matched — check whether the study has any description data at all
    result2 = await session.execute(
        text(
            "SELECT COUNT(*) FROM biosample "
            "WHERE study_accession = :sa AND description IS NOT NULL"
        ),
        {"sa": study_accession},
    )
    if not (result2.scalar() or 0):
        logger.warning("No biosample descriptions for study %s — skipping marker filter", study_accession)
    else:
        logger.warning(
            "Marker %r (normalized: %r) not found in biosample.description for study %s",
            marker, normalized, study_accession,
        )
    return None


async def scan_subject_data_view_for_value(
    session: AsyncSession,
    search_term: str,
    study_accession: str,
    placements: list[str] | None = None,
) -> dict | None:
    """Inspect populated subject_data_view columns for a likely placement match.

    This is a last-resort fallback after the controlled resolver order fails.
    It helps recover from extractor drift by checking which populated study
    columns actually contain the requested value.
    """
    if not search_term or not study_accession:
        return None

    allowed = set(placements or [])
    specs = [
        spec for spec in _VIEW_PLACEMENT_SCAN_SPECS
        if not allowed or spec["placement"] in allowed
    ]
    if not specs:
        return None

    pattern = f"%{search_term}%"
    for spec in specs:
        result = await session.execute(
            text(
                f"SELECT DISTINCT {spec['column']} "
                f"FROM subject_data_view "
                f"WHERE study_accession = :sa "
                f"AND {spec['column']} LIKE :pattern "
                f"AND {spec['column']} IS NOT NULL"
            ),
            {"sa": study_accession, "pattern": pattern},
        )
        matches = [r[0] for r in result.fetchall() if r[0]]
        if len(matches) == 1:
            payload = {
                "placement": spec["placement"],
                spec["value_key"]: matches[0],
                "method": "view_scan_fallback",
                "scanned_column": spec["column"].replace("`", ""),
                "source_value": search_term,
            }
            if spec.get("matched_col"):
                payload["matched_col"] = spec["matched_col"]
            logger.info(
                "View scan fallback resolved %r via %s → %r",
                search_term, spec["column"], matches[0],
            )
            return payload

    return None


async def resolve_disease_stage(
    session: AsyncSession, condition: str, study_accession: str,
    claim_text: str | None = None,
) -> tuple[str, str] | None:
    """Resolve a severity label → canonical disease_stage_preferred value in subject_data_view.

    Used for severity study designs when the value truly belongs in
    disease_stage_preferred. Ambiguous fallbacks to condition, planned visit,
    or arm/cohort are handled separately by resolve_disease_stage_placement().
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

    resolved = await _llm_resolve(condition, all_candidates, _DISEASE_STAGE_LLM_CONFIG, claim_text=claim_text)
    if resolved:
        return (resolved, "LLM")
    return None


async def resolve_time_point_placement(
    session: AsyncSession, time_point: str, study_accession: str,
    claim_text: str | None = None, allow_arm_fallback: bool = True,
) -> dict | None:
    """Resolve an ambiguous time-like value to its most likely metadata placement.

    Resolution order:
    1. planned_visit_accession
    2. study_time_collected range fallback
    3. arm_accession fallback when visit labels are encoded in arm names
    """
    if not time_point or not study_accession:
        return None

    pv_result = await resolve_planned_visit_accession(
        session, time_point, study_accession, claim_text=claim_text,
    )
    if pv_result:
        return {
            "placement": "planned_visit",
            "accessions": pv_result,
            "method": pv_result[0][1],
            "source_value": time_point,
        }

    parsed_range = _parse_time_point_to_range(time_point)
    if parsed_range is not None:
        low, high = parsed_range
        return {
            "placement": "time_collected",
            "low": low,
            "high": high,
            "method": "biosample_fallback",
            "source_value": time_point,
        }

    if allow_arm_fallback:
        arm_result = await resolve_arm_accession(
            session, time_point, study_accession, claim_text=claim_text,
        )
        if arm_result:
            arm_acc, arm_method = arm_result
            logger.info(
                "Time point resolved via arm-name fallback: %r → arm_accession %s (%s)",
                time_point, arm_acc, arm_method,
            )
            return {
                "placement": "arm",
                "value": arm_acc,
                "method": "arm_fallback",
                "fallback_method": arm_method,
                "source_value": time_point,
            }

    scan_result = await scan_subject_data_view_for_value(
        session, time_point, study_accession, placements=["disease_stage", "disease"],
    )
    if scan_result:
        return scan_result

    return None


async def resolve_disease_stage_placement(
    session: AsyncSession, disease_stage: str, study_accession: str,
    claim_text: str | None = None, allow_time_fallback: bool = True,
    allow_arm_fallback: bool = True,
) -> dict | None:
    """Resolve an ambiguous disease_stage-like label to the right query placement.

    This handles extractor drift where values such as "healthy", "acute phase",
    or cohort-like labels land in disease_stage even though they belong in a
    different metadata column/table.
    """
    if not disease_stage or not study_accession:
        return None

    stage_result = await resolve_disease_stage(
        session, disease_stage, study_accession, claim_text=claim_text,
    )
    if stage_result:
        value, method = stage_result
        return {
            "placement": "disease_stage",
            "value": value,
            "method": method,
            "source_value": disease_stage,
        }

    condition_result = await resolve_condition(
        session, disease_stage, study_accession, claim_text=claim_text,
    )
    if condition_result:
        value, method = condition_result
        logger.info(
            "Disease stage resolved via condition fallback: %r → %r (%s)",
            disease_stage, value, method,
        )
        return {
            "placement": "disease",
            "value": value,
            "method": "condition_fallback",
            "fallback_method": method,
            "source_value": disease_stage,
        }

    if allow_time_fallback:
        time_result = await resolve_time_point_placement(
            session,
            disease_stage,
            study_accession,
            claim_text=claim_text,
            allow_arm_fallback=False,
        )
        if time_result:
            logger.info(
                "Disease stage resolved via time fallback: %r → %s",
                disease_stage, time_result["placement"],
            )
            time_result = dict(time_result)
            time_result["method"] = "timepoint_fallback"
            return time_result

    if allow_arm_fallback:
        arm_result = await resolve_arm_accession(
            session, disease_stage, study_accession, claim_text=claim_text,
        )
        if arm_result:
            arm_acc, arm_method = arm_result
            logger.info(
                "Disease stage resolved via arm-name fallback: %r → arm_accession %s (%s)",
                disease_stage, arm_acc, arm_method,
            )
            return {
                "placement": "arm",
                "value": arm_acc,
                "method": "arm_fallback",
                "fallback_method": arm_method,
                "source_value": disease_stage,
            }

    scan_result = await scan_subject_data_view_for_value(
        session,
        disease_stage,
        study_accession,
        placements=["disease_stage", "disease", "tissue_type", "gender", "ethnicity", "race"],
    )
    if scan_result:
        return scan_result

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

    # multi-arm: IN clause (set when cohort resolves to more than one arm_accession)
    arm_accessions = group.get("arm_accessions")
    if arm_accessions:
        placeholders = ", ".join(f":arm_{i}" for i in range(len(arm_accessions)))
        where_clauses.append(f"sdv.arm_accession IN ({placeholders})")
        for i, acc in enumerate(arm_accessions):
            params[f"arm_{i}"] = acc

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

    # tissue_type → sdv.tissue_type (biosample.type)
    tissue_val = group.get("tissue_type") or ""
    if tissue_val:
        where_clauses.append("sdv.tissue_type = :tissue_type")
        params["tissue_type"] = tissue_val

    # cell_type_resolved → sdv.tissue_subtype (biosample.subtype)
    cell_type_val = group.get("cell_type_resolved") or ""
    if cell_type_val:
        where_clauses.append("sdv.tissue_subtype = :cell_type_resolved")
        params["cell_type_resolved"] = cell_type_val

    # study_time_collected fallback — used when no planned_visit matched the time_point
    time_low = group.get("time_collected_low")
    if time_low is not None:
        time_high = group.get("time_collected_high")
        where_clauses.append("sdv.study_time_collected_unit = 'Days'")
        where_clauses.append("sdv.study_time_collected >= :time_collected_low")
        params["time_collected_low"] = time_low
        if time_high is not None:
            where_clauses.append("sdv.study_time_collected <= :time_collected_high")
            params["time_collected_high"] = time_high

    # functional marker (e.g. IFNg+) — filter via biosample.description subquery
    desc_val = group.get("biosample_description") or ""
    if desc_val:
        where_clauses.append(
            "sdv.biosample_accession IN ("
            "SELECT biosample_accession FROM biosample "
            "WHERE study_accession = :study_accession "
            "AND description LIKE :biosample_description"
            ")"
        )
        params["biosample_description"] = f"%{desc_val}%"

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


def _apply_placement_result(
    group: dict,
    resolution_log: dict,
    source_field: str,
    source_value: str,
    placement_result: dict,
    group_id,
) -> list[tuple[str, str]]:
    """Apply a placement resolver result onto the group query payload."""
    placement = placement_result.get("placement")
    method = placement_result.get("method")

    if placement == "arm":
        if not group.get("arm_accession") and not group.get("arm_accessions"):
            group["arm_accession"] = placement_result["value"]
        resolution_log[source_field] = {
            "value": placement_result["value"],
            "method": method,
            "resolved_as": "arm_accession",
        }
        logger.info(
            "Resolved %s %r → arm_accession %s for group %s",
            source_field, source_value, placement_result["value"], group_id,
        )
        return []

    if placement == "planned_visit":
        accessions = placement_result["accessions"]
        resolution_log[source_field] = {
            "accessions": [a for a, _ in accessions],
            "method": method,
            "resolved_as": "planned_visit",
        }
        logger.info(
            "Resolved %s %r → %d planned visit(s) for group %s",
            source_field, source_value, len(accessions), group_id,
        )
        return accessions

    if placement == "time_collected":
        group["time_collected_low"] = placement_result["low"]
        group["time_collected_high"] = placement_result["high"]
        resolution_log[source_field] = {
            "low": placement_result["low"],
            "high": placement_result["high"],
            "method": method,
            "resolved_as": "study_time_collected",
        }
        logger.info(
            "Resolved %s %r → study_time_collected [%s, %s] for group %s",
            source_field, source_value, placement_result["low"], placement_result["high"], group_id,
        )
        return []

    if placement == "disease":
        group["disease"] = placement_result["value"]
        if source_field == "disease_stage":
            group["disease_stage"] = ""
        resolution_log[source_field] = {
            "value": placement_result["value"],
            "method": method,
            "resolved_as": "condition",
        }
        return []

    if placement == "disease_stage":
        group["disease_stage"] = placement_result["value"]
        group["disease"] = ""
        resolution_log[source_field] = {
            "value": placement_result["value"],
            "method": method,
            "resolved_as": "disease_stage_preferred",
        }
        return []

    if placement == "tissue_type":
        group["tissue_type"] = placement_result["value"]
        if placement_result.get("matched_col"):
            group["tissue_matched_col"] = placement_result["matched_col"]
        resolution_log[source_field] = {
            "value": placement_result["value"],
            "method": method,
            "resolved_as": placement_result.get("matched_col") or "tissue_type",
        }
        return []

    if placement in {"gender", "ethnicity", "race"}:
        group[placement] = placement_result["value"]
        resolution_log[source_field] = {
            "value": placement_result["value"],
            "method": method,
            "resolved_as": placement,
        }
        return []

    return []


# ---------------------------------------------------------------------------
# High-level pipeline: resolve all fields then build queries
# ---------------------------------------------------------------------------


async def _resolve_group(
    group: dict,
    study_accession: str | None,
    session_factory,
    claim_text: str | None = None,
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
            return await resolve_arm_accession(s, cohort, study_accession, claim_text=claim_text)

    async def _exp():
        if not (assay_method and study_accession):
            return None
        async with session_factory() as s:
            return await resolve_experiment_accession(s, assay_method, study_accession, claim_text=claim_text)

    async def _cond():
        if study_design == "longitudinal" or not study_accession:
            return None
        async with session_factory() as s:
            if study_design == "severity" and disease_stage:
                return await resolve_disease_stage_placement(
                    s,
                    disease_stage,
                    study_accession,
                    claim_text=claim_text,
                    allow_time_fallback=not bool(time_point),
                    allow_arm_fallback=not bool(cohort),
                )
            if disease:
                return await resolve_condition(s, disease, study_accession, claim_text=claim_text)
            return None

    async def _tissue():
        if not (tissue_type and study_accession):
            return None
        async with session_factory() as s:
            return await resolve_tissue_type(s, tissue_type, study_accession, claim_text=claim_text)

    async def _pv():
        if not (time_point and study_accession):
            return None
        async with session_factory() as s:
            return await resolve_time_point_placement(
                s,
                time_point,
                study_accession,
                claim_text=claim_text,
                allow_arm_fallback=not bool(cohort),
            )

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
        resolution_log["experiment"] = {"accession": exp_acc, "method": method, "assay_method": assay_method}
        logger.info("Resolved assay_method %r → experiment_accession %s for group %s", assay_method, exp_acc, group_id)

    cond_stage_pv_accessions: list[tuple[str, str]] = []
    if cond_result:
        if isinstance(cond_result, dict):
            cond_stage_pv_accessions = _apply_placement_result(
                group, resolution_log, "disease_stage", disease_stage, cond_result, group_id,
            )
        else:
            canonical, method = cond_result
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
        pv_accessions = _apply_placement_result(
            group, resolution_log, "time_point", time_point, pv_result, group_id,
        )
    elif cond_stage_pv_accessions:
        pv_accessions = cond_stage_pv_accessions
        resolution_log["planned_visit"] = {
            "accessions": [a for a, _ in pv_accessions],
            "method": "timepoint_fallback",
            "resolved_from": "disease_stage",
        }
    elif time_point:
        logger.warning("Could not resolve time_point %r for group %s — no planned_visit filter applied", time_point, group_id)
        pv_accessions = []
    else:
        pv_accessions = []

    # ── Build one query per planned visit (or one query if no planned visit) ──
    def _make_query_dict(pv_acc: str | None) -> dict:
        g = dict(group)
        if pv_acc:
            g["planned_visit_accession"] = pv_acc
        sql, params = _build_query(g)
        logger.info(
            "Built query for group %s (pv=%s):\n  SQL: %s\n  Params: %s",
            group_id, pv_acc, sql, params,
        )
        return {
            "group_id": group_id or 0,
            "sql": sql,
            "params": params,
            "resolution": resolution_log,
            "keywords": {
                "cohort": cohort or "",
                "assay_method": assay_method or "",
                "time_point": time_point or "",
                "disease": disease or "",
                "disease_stage": disease_stage or "",
                "tissue_type": tissue_type or "",
                "age": age or "",
                "gender": (group.get("gender") or ""),
            },
            "planned_visit_name": pv_acc or time_point,
            "age": age,
            "comparison": comparison,
        }

    if pv_accessions:
        return [_make_query_dict(pv_acc) for pv_acc, _ in pv_accessions]
    return [_make_query_dict(None)]



async def resolve_and_build_queries(
    description_analysis: list[dict],
    study_accession: str | None,
    session_factory,
    claim_text: str | None = None,
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

    # Work on copies so we don't mutate the caller's dicts.
    description_analysis = [dict(g) for g in description_analysis]

    # Extract functional markers from cell_type (e.g. "IFNγ+" → biosample.description filter).
    # tissue_type and cell_type are kept separate; resolve_tissue_and_cell_type() handles
    # matching each against biosample.type / biosample.subtype respectively.
    for g in description_analysis:
        cell_type = g.get("cell_type") or ""
        if not cell_type:
            continue
        marker = _extract_functional_marker(cell_type)
        if marker:
            g["cell_marker"] = marker

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
        cell_type    = group.get("cell_type", "") or ""
        cell_marker  = group.get("cell_marker", "") or ""
        study_design = group.get("study_design", "")
        time_point   = group.pop("time_point", None) or ""
        age          = group.get("age")
        comparison   = group.get("comparison") or []

        # Fan out multi-tissue groups: resolve each token independently and union.
        # time_point was already popped, so pass it back explicitly for each sub-group.
        tissue_tokens = _split_multi_tissue(tissue_type)
        if len(tissue_tokens) > 1:
            logger.info(
                "Multi-tissue group %s: fanning out into %d sub-groups: %s",
                group_id, len(tissue_tokens), tissue_tokens,
            )
            sub_results = await asyncio.gather(*[
                _resolve_group_cached({**group, "tissue_type": token, "time_point": time_point})
                for token in tissue_tokens
            ])
            for token, sub_list in zip(tissue_tokens, sub_results):
                for qd in sub_list:
                    qd.setdefault("tissue_token", token)
            return [qd for sub_list in sub_results for qd in sub_list]

        # Split cohort on commas or "and" so "D+L group, D-L group" resolves both arms.
        cohort_parts = (
            [p.strip() for p in re.split(r'\s*,\s*|\s+and\s+', cohort, flags=re.I) if p.strip()]
            if cohort else []
        )

        async def _arm():
            if not (cohort_parts and study_accession):
                return None
            # Resolve each part with its own cached task so shared parts across
            # groups (e.g. "D+L group" appearing in multiple cohort strings) reuse
            # the same DB + LLM call.
            part_tasks = []
            for part in cohort_parts:
                part_key = ("arm_part", part)
                if part_key not in _cache:
                    async def _resolve_one(p=part):
                        async with session_factory() as s:
                            return await resolve_arm_accession(s, p, study_accession, claim_text=claim_text)
                    _cache[part_key] = asyncio.ensure_future(_resolve_one())
                part_tasks.append(_cache[part_key])
            results = await asyncio.gather(*part_tasks)
            valid = [r for r in results if r is not None]
            return valid if valid else None

        async def _exp():
            if not (assay_method and study_accession):
                return None
            async with session_factory() as s:
                return await resolve_experiment_accession(s, assay_method, study_accession, claim_text=claim_text)

        async def _cond():
            if study_design == "longitudinal" or not study_accession:
                return None
            async with session_factory() as s:
                if study_design == "severity" and disease_stage:
                    return await resolve_disease_stage_placement(
                        s,
                        disease_stage,
                        study_accession,
                        claim_text=claim_text,
                        allow_time_fallback=not bool(time_point),
                        allow_arm_fallback=not bool(cohort_parts),
                    )
                if disease:
                    return await resolve_condition(s, disease, study_accession, claim_text=claim_text)
            return None

        async def _tissue():
            if not study_accession:
                return None
            if cell_type and tissue_type:
                async with session_factory() as s:
                    return await resolve_tissue_and_cell_type(
                        s, tissue_type, cell_type, study_accession, claim_text=claim_text
                    )
            term = tissue_type or cell_type
            if not term:
                return None
            async with session_factory() as s:
                result = await resolve_tissue_type(s, term, study_accession, claim_text=claim_text)
                if result:
                    val, method, col = result
                    key = "type_value" if col == "type" else "subtype_value"
                    return {key: val, "method": method}
            return None

        async def _pv():
            if not (time_point and study_accession):
                return None
            async with session_factory() as s:
                return await resolve_time_point_placement(
                    s,
                    time_point,
                    study_accession,
                    claim_text=claim_text,
                    allow_arm_fallback=not bool(cohort_parts),
                )

        async def _desc():
            if not (cell_marker and study_accession):
                return None
            async with session_factory() as s:
                return await resolve_biosample_description(s, cell_marker, study_accession)

        # Use cached tasks for arm, experiment, condition, tissue (commonly shared across groups)
        arm_key  = ("arm",  tuple(cohort_parts))
        exp_key  = ("exp",  assay_method)
        cond_key = ("cond", disease_stage if study_design == "severity" else disease, study_design)
        tis_key  = ("tis",  tissue_type, cell_type)
        pv_key   = ("pv",   time_point, study_design)
        desc_key = ("desc", cell_marker)

        def _get_or_create(key, coro_fn):
            if key not in _cache:
                _cache[key] = asyncio.ensure_future(coro_fn())
            return _cache[key]

        arm_result, exp_result, cond_result, tissue_result, pv_result, desc_result = await asyncio.gather(
            _get_or_create(arm_key,  _arm),
            _get_or_create(exp_key,  _exp),
            _get_or_create(cond_key, _cond),
            _get_or_create(tis_key,  _tissue),
            _get_or_create(pv_key,   _pv),
            _get_or_create(desc_key, _desc),
        )

        if arm_result:
            # arm_result is list[tuple[accession, method]] — one entry per cohort part
            if len(arm_result) == 1:
                arm_acc, method = arm_result[0]
                group["arm_accession"] = arm_acc
                resolution_log["arm"] = {"accession": arm_acc, "method": method}
                logger.info("Resolved cohort %r → arm_accession %s for group %s", cohort, arm_acc, group_id)
            else:
                arm_accs = [acc for acc, _ in arm_result]
                group["arm_accessions"] = arm_accs  # IN clause handled in _build_query
                resolution_log["arm"] = {"accessions": arm_accs, "method": "multi"}
                logger.info("Resolved cohort %r → arm_accessions %s for group %s", cohort, arm_accs, group_id)
        if exp_result:
            exp_acc, method = exp_result
            group["experiment_accession"] = exp_acc
            resolution_log["experiment"] = {"accession": exp_acc, "method": method, "assay_method": assay_method}
        cond_stage_pv_accessions: list[tuple[str, str]] = []
        if cond_result:
            if isinstance(cond_result, dict):
                cond_stage_pv_accessions = _apply_placement_result(
                    group, resolution_log, "disease_stage", disease_stage, cond_result, group_id,
                )
            else:
                canonical, method = cond_result
                group["disease"] = canonical
                resolution_log["disease"] = {"value": canonical, "method": method}
        else:
            group["disease"] = ""
        if study_accession:
            group["study_accession"] = study_accession
        if tissue_result:
            method = tissue_result.get("method", "")
            type_val    = tissue_result.get("type_value", "")
            subtype_val = tissue_result.get("subtype_value", "")
            group["tissue_type"]       = type_val
            group["cell_type_resolved"] = subtype_val
            resolution_log["tissue_type"] = {
                "type_value": type_val,
                "subtype_value": subtype_val,
                "method": method,
            }
            logger.info(
                "Resolved tissue/cell_type for group %s: type=%r, subtype=%r (%s)",
                group_id, type_val, subtype_val, method,
            )
        else:
            group["tissue_type"]       = ""
            group["cell_type_resolved"] = ""
        if desc_result:
            normalized_marker, method = desc_result
            group["biosample_description"] = normalized_marker
            resolution_log["biosample_description"] = {"marker": cell_marker, "value": normalized_marker, "method": method}
            logger.info("Resolved cell_marker %r → biosample description LIKE %%%s%% for group %s", cell_marker, normalized_marker, group_id)
        if pv_result:
            pv_accessions = _apply_placement_result(
                group, resolution_log, "time_point", time_point, pv_result, group_id,
            )
        elif cond_stage_pv_accessions:
            pv_accessions = cond_stage_pv_accessions
            resolution_log["planned_visit"] = {
                "accessions": [a for a, _ in pv_accessions],
                "method": "timepoint_fallback",
                "resolved_from": "disease_stage",
            }
        else:
            pv_accessions = []

        age_min, age_max = _parse_age_range(age)
        if age_min is not None:
            group["age_min"] = age_min
            resolution_log["age_min"] = {"value": age_min, "method": "parsed"}
        if age_max is not None:
            group["age_max"] = age_max
            resolution_log["age_max"] = {"value": age_max, "method": "parsed"}

        def _make_query_dict(pv_acc: str | None) -> dict:
            g = dict(group)
            if pv_acc:
                g["planned_visit_accession"] = pv_acc
            sql, params = _build_query(g)
            return {
                "group_id": group_id or 0,
                "sql": sql,
                "params": params,
                "resolution": resolution_log,
                "keywords": {
                    "cohort": cohort or "",
                    "assay_method": assay_method or "",
                    "time_point": time_point or "",
                    "disease": disease or "",
                    "disease_stage": disease_stage or "",
                    "tissue_type": tissue_type or "",
                    "cell_type": cell_type or "",
                    "age": age or "",
                    "gender": (group.get("gender") or ""),
                },
                "planned_visit_name": pv_acc or time_point,
                "age": age,
                "comparison": comparison,
            }

        if pv_accessions:
            return [_make_query_dict(pv_acc) for pv_acc, _ in pv_accessions]
        return [_make_query_dict(None)]

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
