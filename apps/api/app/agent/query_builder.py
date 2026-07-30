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

# ---------------------------------------------------------------------------
# Functional marker extraction
# ---------------------------------------------------------------------------

_MARKER_RE = re.compile(
    r'\b(IFN[γgΓG]|TNF[αaΑ]|IL-?\d+[a-zA-Z]?|MIP-1[αβab]|GM-CSF|perforin|granzyme\s*[A-Za-z]?)\s*([+\-])',
    re.IGNORECASE,
)
_GREEK_NORMALIZE = str.maketrans({"γ": "g", "Γ": "g", "α": "a", "Α": "a", "β": "b", "Β": "b"})

_MULTI_TISSUE_SEP = re.compile(r'\s*(?:,|;|\band\b)\s*', re.IGNORECASE)


def _split_multi_tissue(tissue_type: str) -> list[str]:
    """Split a tissue_type string on commas, semicolons, or 'and'.

    Returns a list of stripped, non-empty tokens. Returns a 1-element list
    when no separator is found so callers can always iterate uniformly.
    """
    if not tissue_type:
        return []
    tokens = [t.strip() for t in _MULTI_TISSUE_SEP.split(tissue_type)]
    return [t for t in tokens if t]


def _extract_functional_marker(cell_type: str) -> tuple[str, str]:
    """Strip a functional marker (e.g. IFNγ-) from a cell type string.

    Returns (cleaned_cell_type, normalized_marker) where normalized_marker is
    ASCII-normalized for DB LIKE matching (γ→g, α→a, β→b).  marker is '' if
    no functional marker is found.
    """
    m = _MARKER_RE.search(cell_type)
    if not m:
        return cell_type, ""
    marker_raw = m.group(0).strip()
    marker_normalized = marker_raw.translate(_GREEK_NORMALIZE)
    cleaned = (cell_type[: m.start()] + cell_type[m.end() :]).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned, marker_normalized
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
    session: AsyncSession,
    assay_method: str,
    study_accession: str,
    claim_text: str | None = None,
    original_name: str = "",
    readouts: str = "",
) -> tuple[str, str] | None:
    """Resolve an assay method → experiment_accession.

    SQL step tries canonical name then original_name (if different).
    If both miss, one LLM call is made with canonical name, original name,
    and readouts all included for richer context.
    """
    if not assay_method or not study_accession:
        return None

    config = _EXPERIMENT_CONFIG
    table = config["table"]
    id_col = config["id_col"]
    search_cols = config["search_cols"]
    all_cols = config["all_cols"]

    # SQL step — try canonical name, then original_name
    seen: set[str] = set()
    for term in [assay_method, original_name]:
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())
        like_clauses = " OR ".join(f"{col} LIKE :pattern" for col in search_cols)
        result = await session.execute(
            text(
                f"SELECT {all_cols} FROM {table} "
                f"WHERE ({like_clauses}) AND study_accession = :study_accession"
            ),
            {"pattern": f"%{term}%", "study_accession": study_accession},
        )
        rows = [dict(zip(result.keys(), row)) for row in result.fetchall()]
        if len(rows) == 1:
            accession = rows[0][id_col]
            logger.info("experiment resolved via SQL (%r): %r → %s", term, assay_method, accession)
            return (accession, "SQL")
        logger.info("SQL match for %r returned %d rows — trying next term", term, len(rows))

    # LLM fallback — one call with all available context
    all_result = await session.execute(
        text(f"SELECT {all_cols} FROM {table} WHERE study_accession = :study_accession"),
        {"study_accession": study_accession},
    )
    all_candidates = [dict(zip(all_result.keys(), row)) for row in all_result.fetchall()]
    if not all_candidates:
        logger.warning("No experiment rows found for study %s", study_accession)
        return None

    system_prompt, user_template = _load_resolver_prompt(config["prompt_name"])
    prompt = user_template.format(
        candidates=json.dumps(all_candidates, indent=2),
        search_term=assay_method,
        original_name=original_name or assay_method,
        readouts=readouts or "",
    )
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
    answer = (response.choices[0].message.content or "").strip()
    logger.info("LLM experiment resolution: %r → %r", assay_method, answer)

    if answer.upper() == "NONE":
        return None
    valid_ids = {c[id_col] for c in all_candidates}
    if answer in valid_ids:
        return (answer, "LLM")
    for candidate_id in valid_ids:
        if candidate_id in answer:
            return (candidate_id, "LLM")
    logger.warning("LLM returned unrecognized experiment_accession: %r", answer)
    return None


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


def _parse_day_range(time_point: str) -> tuple[float, float] | None:
    """Extract (low, high) day bounds from natural language time point phrases.

    Returns None if no numeric range pattern is found.
    high=9999 represents open-ended upper bounds (e.g. "8+ days").

    Handles:
      "4-7 days post fever onset"  → (4, 7)
      "day 4-7"                    → (4, 7)
      "8+ days"                    → (8, 9999)
      ">= 8 days"                  → (8, 9999)
      "< 14 days"                  → (0, 14)
      "within 10 days"             → (0, 10)
      "day 7"                      → (7, 7)     single day, incl. "day -7"
    """
    s = time_point.strip()

    # "X-Y days" or "X–Y days" anywhere in the phrase
    m = re.search(r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*day', s, re.I)
    if m:
        return float(m.group(1)), float(m.group(2))

    # "day(s) X-Y" or "day(s) X–Y"
    m = re.search(r'days?\s+(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)', s, re.I)
    if m:
        return float(m.group(1)), float(m.group(2))

    # "X+ days" — open-ended lower bound
    m = re.search(r'(\d+(?:\.\d+)?)\s*\+\s*day', s, re.I)
    if m:
        return float(m.group(1)), 9999.0

    # ">= X days" or "> X days" or "≥ X days"
    m = re.search(r'[>≥]=?\s*(\d+(?:\.\d+)?)\s*day', s, re.I)
    if m:
        return float(m.group(1)), 9999.0

    # "X or more days"
    m = re.search(r'(\d+(?:\.\d+)?)\s+or\s+more\s+day', s, re.I)
    if m:
        return float(m.group(1)), 9999.0

    # "<= X days" or "< X days" or "≤ X days"
    m = re.search(r'[<≤]=?\s*(\d+(?:\.\d+)?)\s*day', s, re.I)
    if m:
        return 0.0, float(m.group(1))

    # "within X days"
    m = re.search(r'within\s+(\d+(?:\.\d+)?)\s*day', s, re.I)
    if m:
        return 0.0, float(m.group(1))

    # Bare single day: "day 7", "day 0", "day -7". This is the canonical form
    # classify_groups.txt emits, so it must reach the numeric day columns —
    # without it a bare day falls through to name LIKE/LLM only, and when those
    # miss, the group is built with no time filter at all and every timepoint
    # group collapses to the same subject set.
    # Anchored and checked last so no range phrase above can reach it.
    m = re.fullmatch(r'days?\s*(-?\d+(?:\.\d+)?)', s, re.I)
    if m:
        day = float(m.group(1))
        return day, day

    return None


async def resolve_planned_visit_accession(
    session: AsyncSession, time_point: str, study_accession: str,
    claim_text: str | None = None,
) -> list[tuple[str, str]] | None:
    """Resolve a time point string → list of (planned_visit_accession, method) tuples.

    For range format "Xdays<time<Ydays" returns all visits whose min_start_day
    falls in [X, Y]. For exact time points returns a single-element list.
    """
    if not time_point:
        return None

    async def _range_query(low: float, high: float) -> list[tuple[str, str]] | None:
        result = await session.execute(
            text(
                "SELECT planned_visit_accession, name, min_start_day, max_start_day "
                "FROM planned_visit WHERE study_accession = :sa"
            ),
            {"sa": study_accession},
        )
        rows = [dict(zip(result.keys(), row)) for row in result.fetchall()]
        matches = [
            r for r in rows
            if r.get("min_start_day") is not None
            # Standard range overlap: visit window [min, max] overlaps search window [low, high]
            and float(r["min_start_day"]) <= high
            and float(r.get("max_start_day") or r["min_start_day"]) >= low
        ]
        if not matches:
            return None
        # Searching a single day: prefer visits starting exactly on it. Without this
        # a bare "day 1" also matches every wide-window visit that merely spans it
        # (e.g. a day 0-14 visit), and each match fans out into its own query.
        if low == high:
            exact = [r for r in matches if float(r["min_start_day"]) == low]
            if exact:
                matches = exact
        return [(r["planned_visit_accession"], "range") for r in matches]

    # Step 1: strict internal range format "Xdays<time<Ydays"
    range_m = re.match(r'^(\d+(?:\.\d+)?)days<time<(\d+(?:\.\d+)?)days$', time_point.strip())
    if range_m:
        low, high = float(range_m.group(1)), float(range_m.group(2))
        matches = await _range_query(low, high)
        if matches:
            logger.info("Range %s matched %d planned visits for study %s", time_point, len(matches), study_accession)
            return matches
        logger.warning("No planned visits found in range %s for study %s", time_point, study_accession)
        return None

    # Step 2: natural language range (e.g. "4-7 days post fever onset", "8+ days")
    nl_range = _parse_day_range(time_point)
    if nl_range:
        low, high = nl_range
        matches = await _range_query(low, high)
        if matches:
            logger.info(
                "Natural language range %r → [%g, %g] matched %d planned visits for study %s",
                time_point, low, high, len(matches), study_accession,
            )
            return matches
        logger.warning(
            "Natural language range %r → [%g, %g] matched no planned visits for study %s — falling through to LIKE/LLM",
            time_point, low, high, study_accession,
        )
        # Fall through: range extracted but no visit in that window — try LIKE/LLM

    # Step 3: exact match via SQL LIKE → LLM fallback
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
            "SELECT DISTINCT type, subtype, description FROM biosample "
            "WHERE study_accession = :sa AND (type IS NOT NULL OR subtype IS NOT NULL)"
        ),
        {"sa": study_accession},
    )
    candidates = []
    for row in all_result.fetchall():
        desc = row[2] or ""
        if row[0]:
            candidates.append({"value": row[0], "col": "type", "description": desc})
        if row[1]:
            candidates.append({"value": row[1], "col": "subtype", "description": desc})
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


async def _study_has_subtype(session: AsyncSession, study_accession: str) -> bool:
    """Return True if any biosample row for the study has a non-null subtype."""
    result = await session.execute(
        text(
            "SELECT 1 FROM biosample WHERE study_accession = :sa "
            "AND subtype IS NOT NULL LIMIT 1"
        ),
        {"sa": study_accession},
    )
    return result.fetchone() is not None


async def resolve_cell_type(
    session: AsyncSession,
    tissue_type: str,
    cell_type: str,
    study_accession: str,
    claim_text: str | None = None,
) -> tuple[str | None, str | None, str, str] | None:
    """Resolve a (tissue_type, cell_type) pair against biosample using four strategies.

    Returns (type_val, subtype_val, method, functional_marker) or None.
    type_val   → filter on sdv.tissue_type   (biosample.type)
    subtype_val → filter on sdv.tissue_subtype (biosample.subtype)
    functional_marker → ASCII-normalized marker (e.g. "IFNg-") for description LIKE filter; "" if none.

    Strategies tried in order:
      SQL_two_col   — type LIKE tissue AND subtype LIKE cell (exact 1+1 match)
      SQL_cell_as_type — cell_type directly against biosample.type
      SQL_split     — resolve tissue_type first, then cell_type against subtype
      fallback_cell — resolve cell_type alone via resolve_tissue_type()
    Early bail-out when the study has no subtype data: resolve tissue_type only.
    """
    if not study_accession:
        return None

    # Strip functional markers before any SQL/LLM matching
    cleaned_cell, functional_marker = _extract_functional_marker(cell_type) if cell_type else ("", "")

    # Early bail-out: study has no subtype data — resolve tissue_type only
    has_sub = await _study_has_subtype(session, study_accession)
    if not has_sub:
        fallback_term = tissue_type or cleaned_cell
        if not fallback_term:
            return None
        result = await resolve_tissue_type(session, fallback_term, study_accession, claim_text=claim_text)
        if result:
            val, method, matched_col = result
            type_val = val if matched_col == "type" else None
            subtype_val = val if matched_col == "subtype" else None
            logger.info("Cell type resolved (tissue_only, no subtype in study): %r/%r → %r", tissue_type, cell_type, val)
            return (type_val, subtype_val, "tissue_only", functional_marker)
        return None

    # ── Strategy 1: two-column SQL match ─────────────────────────────────────
    if tissue_type and cleaned_cell:
        result = await session.execute(
            text(
                "SELECT DISTINCT type, subtype FROM biosample "
                "WHERE study_accession = :sa "
                "AND type LIKE :tp AND subtype LIKE :cp "
                "AND type IS NOT NULL AND subtype IS NOT NULL"
            ),
            {"sa": study_accession, "tp": f"%{tissue_type}%", "cp": f"%{cleaned_cell}%"},
        )
        rows = result.fetchall()
        distinct_types = {r[0] for r in rows if r[0]}
        distinct_subs = {r[1] for r in rows if r[1]}
        if len(distinct_types) == 1 and len(distinct_subs) == 1:
            tv, sv = next(iter(distinct_types)), next(iter(distinct_subs))
            logger.info("Cell type resolved via SQL_two_col: (%r, %r) → (%r, %r)", tissue_type, cell_type, tv, sv)
            return (tv, sv, "SQL_two_col", functional_marker)

    # ── Strategy 2: cell_type as type ────────────────────────────────────────
    if cleaned_cell:
        result = await session.execute(
            text(
                "SELECT DISTINCT type FROM biosample "
                "WHERE study_accession = :sa AND type LIKE :cp AND type IS NOT NULL"
            ),
            {"sa": study_accession, "cp": f"%{cleaned_cell}%"},
        )
        rows = [r[0] for r in result.fetchall() if r[0]]
        if len(rows) == 1:
            logger.info("Cell type resolved via SQL_cell_as_type: %r → type=%r", cell_type, rows[0])
            return (rows[0], None, "SQL_cell_as_type", functional_marker)

    # ── Strategy 3: split resolve ─────────────────────────────────────────────
    if tissue_type and cleaned_cell:
        tis_result = await resolve_tissue_type(session, tissue_type, study_accession, claim_text=claim_text)
        if tis_result and tis_result[2] == "type":
            type_val = tis_result[0]
            sub_result = await session.execute(
                text(
                    "SELECT DISTINCT subtype FROM biosample "
                    "WHERE study_accession = :sa AND type = :tv "
                    "AND subtype LIKE :cp AND subtype IS NOT NULL"
                ),
                {"sa": study_accession, "tv": type_val, "cp": f"%{cleaned_cell}%"},
            )
            sub_rows = [r[0] for r in sub_result.fetchall() if r[0]]
            if len(sub_rows) == 1:
                logger.info("Cell type resolved via SQL_split: (%r, %r) → (%r, %r)", tissue_type, cell_type, type_val, sub_rows[0])
                return (type_val, sub_rows[0], "SQL_split", functional_marker)
            # Subtype ambiguous — return tissue-only
            logger.info("SQL_split: subtype ambiguous (%d rows) for %r under type=%r; using tissue-only", len(sub_rows), cell_type, type_val)
            return (type_val, None, "SQL_split_tissue_only", functional_marker)

    # ── Strategy 4: cell_type alone fallback ──────────────────────────────────
    fallback_term = cleaned_cell or tissue_type
    if fallback_term:
        result = await resolve_tissue_type(session, fallback_term, study_accession, claim_text=claim_text)
        if result:
            val, method, matched_col = result
            type_val = val if matched_col == "type" else None
            subtype_val = val if matched_col == "subtype" else None
            logger.info("Cell type resolved via fallback_cell: %r → (%r, %r)", cell_type, type_val, subtype_val)
            return (type_val, subtype_val, f"fallback_cell_{method}", functional_marker)

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


async def resolve_disease_stage(
    session: AsyncSession, condition: str, study_accession: str,
    claim_text: str | None = None,
) -> tuple[str, str, str] | None:
    """Resolve a severity label → (value, method, field) where field is
    'disease_stage' (filter on disease_stage_preferred) or 'arm_accession'
    (filter on arm_accession — used when severity is encoded in arm names).

    Step 1: LIKE search on disease_stage_preferred.
    Step 2: LIKE search on arm_or_cohort name/description.
    Step 3: LLM fallback over all distinct disease_stage_preferred values.
    """
    if not condition or not study_accession:
        return None

    pattern = f"%{condition}%"

    # Step 1: LIKE match on disease_stage_preferred
    result = await session.execute(
        text(
            "SELECT DISTINCT disease_stage_preferred FROM subject_data_view "
            "WHERE study_accession = :sa "
            "AND disease_stage_preferred LIKE :pattern "
            "AND disease_stage_preferred IS NOT NULL"
        ),
        {"sa": study_accession, "pattern": pattern},
    )
    rows = [r[0] for r in result.fetchall() if r[0]]

    if len(rows) == 1:
        logger.info("Disease stage resolved via SQL (disease_stage_preferred): %r → %r", condition, rows[0])
        return (rows[0], "SQL", "disease_stage")

    # Step 2: LIKE match on arm name/description — some studies encode severity
    # in arm names (e.g. "Severe COVID-19") rather than disease_stage_preferred.
    logger.info(
        "SQL disease_stage_preferred match returned %d rows for %r; trying arm names",
        len(rows), condition,
    )
    arm_result = await session.execute(
        text(
            "SELECT arm_accession, name FROM arm_or_cohort "
            "WHERE study_accession = :sa "
            "AND (name LIKE :pattern OR description LIKE :pattern)"
        ),
        {"sa": study_accession, "pattern": pattern},
    )
    arm_rows = [dict(zip(arm_result.keys(), row)) for row in arm_result.fetchall()]

    if len(arm_rows) == 1:
        acc = arm_rows[0]["arm_accession"]
        logger.info("Disease stage resolved via arm name fuzzy match: %r → %s (%s)", condition, acc, arm_rows[0]["name"])
        return (acc, "SQL", "arm_accession")

    # Step 3: LLM fallback — combined disease_stage_preferred + arm name candidates.
    # Prompt instructs the LLM to try disease_stage first, then arm names.
    logger.info(
        "Arm name match returned %d rows for %r; falling back to LLM with combined candidates",
        len(arm_rows), condition,
    )
    ds_result = await session.execute(
        text(
            "SELECT DISTINCT disease_stage_preferred FROM subject_data_view "
            "WHERE study_accession = :sa AND disease_stage_preferred IS NOT NULL"
        ),
        {"sa": study_accession},
    )
    ds_candidates = [
        {"value": r[0], "field": "disease_stage"}
        for r in ds_result.fetchall() if r[0]
    ]
    all_arms_result = await session.execute(
        text(
            "SELECT arm_accession, name FROM arm_or_cohort "
            "WHERE study_accession = :sa"
        ),
        {"sa": study_accession},
    )
    arm_candidates = [
        {"value": row[0], "name": row[1], "field": "arm_accession"}
        for row in all_arms_result.fetchall() if row[0]
    ]
    combined = ds_candidates + arm_candidates

    if not combined:
        logger.warning("No disease_stage or arm candidates found for study %s", study_accession)
        return None

    system_prompt, user_template = _load_resolver_prompt("disease_stage")
    prompt = user_template.format(candidates=json.dumps(combined, indent=2), search_term=condition)
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
    logger.info("LLM disease_stage resolution: %r → %r", condition, answer)

    if answer.upper() == "NONE" or "|" not in answer:
        return None

    value, _, field = answer.partition("|")
    value = value.strip()
    field = field.strip()

    if field not in ("disease_stage", "arm_accession"):
        logger.warning("LLM returned unexpected field %r for disease_stage resolution of %r", field, condition)
        return None

    valid_values = {c["value"] for c in combined}
    if value in valid_values:
        return (value, "LLM", field)

    # Try to extract a valid value from a verbose response
    for v in valid_values:
        if v in answer:
            matched_field = next((c["field"] for c in combined if c["value"] == v), field)
            return (v, "LLM", matched_field)

    logger.warning("LLM returned unrecognized value %r for disease_stage resolution of %r", value, condition)
    return None


# Categorical SDV columns tried when disease_stage doesn't match its primary location.
_SDV_SCAN_COLS: list[str] = ["exposure_process"]


async def resolve_disease_stage_placement(
    session: AsyncSession, condition: str, study_accession: str,
    claim_text: str | None = None,
) -> dict | None:
    """Resolve a severity/condition label → placement dict saying where it belongs.

    Tries five strategies in order; returns the first hit.

    Step 1  LIKE on disease_stage_preferred          → field "disease_stage"
    Step 2  LIKE on subject_data_view.condition       → field "disease"
    Step 3  planned_visit name LIKE / LLM             → field "planned_visit_accession"
    Step 4  arm_or_cohort name LIKE (single hit)      → field "arm_accession"
    Step 5  Broad SDV column scan (_SDV_SCAN_COLS)    → field <col>
    LLM fallback over combined disease_stage + arm candidates (last resort)
    """
    if not condition or not study_accession:
        return None

    pattern = f"%{condition}%"

    # Step 1: disease_stage_preferred
    result = await session.execute(
        text(
            "SELECT DISTINCT disease_stage_preferred FROM subject_data_view "
            "WHERE study_accession = :sa "
            "AND disease_stage_preferred LIKE :pattern AND disease_stage_preferred IS NOT NULL"
        ),
        {"sa": study_accession, "pattern": pattern},
    )
    rows = [r[0] for r in result.fetchall() if r[0]]
    if len(rows) == 1:
        logger.info("DS-placement step1 (disease_stage_preferred): %r → %r", condition, rows[0])
        return {"field": "disease_stage", "value": rows[0], "method": "SQL"}

    # Step 2: condition column
    result = await session.execute(
        text(
            "SELECT DISTINCT `condition` FROM subject_data_view "
            "WHERE study_accession = :sa "
            "AND `condition` LIKE :pattern AND `condition` IS NOT NULL"
        ),
        {"sa": study_accession, "pattern": pattern},
    )
    rows = [r[0] for r in result.fetchall() if r[0]]
    if len(rows) == 1:
        logger.info("DS-placement step2 (condition): %r → %r", condition, rows[0])
        return {"field": "disease", "value": rows[0], "method": "SQL"}

    # Step 3: planned_visit name
    pv_result = await resolve_planned_visit_accession(session, condition, study_accession, claim_text=claim_text)
    if pv_result:
        pv_accs = [acc for acc, _ in pv_result]
        method = pv_result[0][1]
        logger.info("DS-placement step3 (planned_visit): %r → %s", condition, pv_accs)
        return {"field": "planned_visit_accession", "value": pv_accs, "method": method}

    # Step 4: arm name LIKE (single hit)
    arm_result = await session.execute(
        text(
            "SELECT arm_accession, name FROM arm_or_cohort "
            "WHERE study_accession = :sa "
            "AND (name LIKE :pattern OR description LIKE :pattern)"
        ),
        {"sa": study_accession, "pattern": pattern},
    )
    arm_rows = [dict(zip(arm_result.keys(), row)) for row in arm_result.fetchall()]
    if len(arm_rows) == 1:
        acc = arm_rows[0]["arm_accession"]
        logger.info("DS-placement step4 (arm name): %r → %s (%s)", condition, acc, arm_rows[0]["name"])
        return {"field": "arm_accession", "value": acc, "method": "SQL"}

    # Step 5: broad SDV scan
    for col in _SDV_SCAN_COLS:
        result = await session.execute(
            text(
                f"SELECT DISTINCT {col} FROM subject_data_view "
                f"WHERE study_accession = :sa AND {col} LIKE :pattern AND {col} IS NOT NULL"
            ),
            {"sa": study_accession, "pattern": pattern},
        )
        rows = [r[0] for r in result.fetchall() if r[0]]
        if len(rows) == 1:
            logger.info("DS-placement step5 (scan %s): %r → %r", col, condition, rows[0])
            return {"field": col, "value": rows[0], "method": "scan"}

    # LLM fallback over combined disease_stage + arm candidates
    ds_result = await session.execute(
        text(
            "SELECT DISTINCT disease_stage_preferred FROM subject_data_view "
            "WHERE study_accession = :sa AND disease_stage_preferred IS NOT NULL"
        ),
        {"sa": study_accession},
    )
    ds_candidates = [{"value": r[0], "field": "disease_stage"} for r in ds_result.fetchall() if r[0]]
    all_arms = await session.execute(
        text("SELECT arm_accession, name FROM arm_or_cohort WHERE study_accession = :sa"),
        {"sa": study_accession},
    )
    arm_candidates = [{"value": r[0], "name": r[1], "field": "arm_accession"} for r in all_arms.fetchall() if r[0]]
    combined = ds_candidates + arm_candidates
    if not combined:
        logger.warning("DS-placement: no candidates for study %s", study_accession)
        return None

    system_prompt, user_template = _load_resolver_prompt("disease_stage")
    prompt = user_template.format(candidates=json.dumps(combined, indent=2), search_term=condition)
    if claim_text:
        prompt += f"\n\nOriginal claim for context:\n{claim_text}"
    client = _get_openai_client()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
        temperature=0,
    )
    answer = response.choices[0].message.content.strip()
    logger.info("DS-placement LLM: %r → %r", condition, answer)
    if answer.upper() == "NONE" or "|" not in answer:
        return None
    llm_value, _, llm_field = answer.partition("|")
    llm_value, llm_field = llm_value.strip(), llm_field.strip()
    if llm_field not in ("disease_stage", "arm_accession"):
        logger.warning("DS-placement LLM returned unexpected field %r", llm_field)
        return None
    valid_ids = {c["value"] for c in combined}
    resolved = llm_value if llm_value in valid_ids else next((v for v in valid_ids if v in answer), None)
    if resolved:
        return {"field": llm_field, "value": resolved, "method": "LLM"}
    return None


async def resolve_time_point_placement(
    session: AsyncSession, time_point: str, study_accession: str,
    claim_text: str | None = None,
) -> dict | None:
    """Resolve a time_point string → placement dict.

    Step 1  Existing planned_visit resolution (range + LIKE + LLM)
               → field "planned_visit_accession", value list[str]
    Step 2  biosample.study_time_collected range fallback
               → field "study_time_collected", value {"min": float, "max": float}
    Step 3  arm_accession fallback — LIKE on arm_or_cohort name
               → field "arm_accession", value str
    """
    if not time_point or not study_accession:
        return None

    # Step 1: existing planned_visit logic
    pv_result = await resolve_planned_visit_accession(session, time_point, study_accession, claim_text=claim_text)
    if pv_result:
        pv_accs = [acc for acc, _ in pv_result]
        method = pv_result[0][1]
        logger.info("TP-placement step1 (planned_visit): %r → %s", time_point, pv_accs)
        return {"field": "planned_visit_accession", "value": pv_accs, "method": method}

    # Step 2: study_time_collected range on biosample
    day_range = _parse_day_range(time_point)
    if day_range:
        low, high = day_range
        exists = await session.execute(
            text(
                "SELECT 1 FROM biosample "
                "WHERE study_accession = :sa "
                "AND study_time_collected >= :low AND study_time_collected <= :high LIMIT 1"
            ),
            {"sa": study_accession, "low": low, "high": high},
        )
        if exists.fetchone():
            logger.info(
                "TP-placement step2 (study_time_collected): %r → [%g, %g]", time_point, low, high
            )
            return {"field": "study_time_collected", "value": {"min": low, "max": high}, "method": "range"}

    # Step 3: arm_accession fallback
    pattern = f"%{time_point}%"
    arm_result = await session.execute(
        text(
            "SELECT arm_accession, name FROM arm_or_cohort "
            "WHERE study_accession = :sa AND name LIKE :pattern"
        ),
        {"sa": study_accession, "pattern": pattern},
    )
    arm_rows = [dict(zip(arm_result.keys(), r)) for r in arm_result.fetchall()]
    if len(arm_rows) == 1:
        acc = arm_rows[0]["arm_accession"]
        logger.info("TP-placement step3 (arm name): %r → %s", time_point, acc)
        return {"field": "arm_accession", "value": acc, "method": "arm_name"}

    return None


def _apply_placement_result(
    group: dict, resolution_log: dict, placement: dict,
) -> list[tuple[str, str]]:
    """Route a placement dict to the right group field.

    Returns a list of (pv_accession, method) tuples when the placement targets
    planned_visit_accession (to drive query fan-out); empty list otherwise.
    """
    field = placement["field"]
    value = placement["value"]
    method = placement["method"]

    if field == "planned_visit_accession":
        pv_list = [(acc, method) for acc in value]
        resolution_log["planned_visit"] = {"accessions": value, "method": method}
        return pv_list

    if field == "arm_accession":
        group["arm_accession"] = value
        group.pop("disease_stage", None)
        group.pop("disease", None)
        resolution_log["arm"] = {"accession": value, "method": method}
    elif field == "disease_stage":
        group["disease_stage"] = value
        group["disease"] = ""
        resolution_log["disease_stage"] = {"value": value, "method": method}
    elif field == "disease":
        group["disease"] = value
        resolution_log["disease"] = {"value": value, "method": method}
    elif field == "study_time_collected":
        group["bio_time_min"] = value["min"]
        group["bio_time_max"] = value["max"]
        resolution_log["study_time_collected"] = {"range": value, "method": method}
    else:
        # Broad SDV scan result (e.g. exposure_process)
        group[field] = value
        resolution_log[field] = {"value": value, "method": method}

    return []


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

    # Multi-arm: arm_accessions (list) → IN (...) clause.
    # Single arm stays in VIEW_FILTERS as an eq filter below.
    arm_accessions = group.get("arm_accessions") or []
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

    # biosample type/subtype/description from multi-strategy cell type resolution
    bio_type = group.get("bio_type") or ""
    bio_subtype = group.get("bio_subtype") or ""
    bio_marker = group.get("bio_description_marker") or ""
    if bio_type:
        where_clauses.append("sdv.tissue_type = :bio_type")
        params["bio_type"] = bio_type
    if bio_subtype:
        where_clauses.append("sdv.tissue_subtype = :bio_subtype")
        params["bio_subtype"] = bio_subtype
    if bio_marker:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM biosample b "
            "WHERE b.biosample_accession = sdv.biosample_accession "
            "AND b.description LIKE :bio_marker)"
        )
        params["bio_marker"] = f"%{bio_marker}%"

    # study_time_collected range — biosample EXISTS subquery
    bio_time_min = group.get("bio_time_min")
    bio_time_max = group.get("bio_time_max")
    if bio_time_min is not None or bio_time_max is not None:
        time_conds = []
        if bio_time_min is not None:
            time_conds.append("b.study_time_collected >= :bio_time_min")
            params["bio_time_min"] = bio_time_min
        if bio_time_max is not None:
            time_conds.append("b.study_time_collected <= :bio_time_max")
            params["bio_time_max"] = bio_time_max
        where_clauses.append(
            "EXISTS (SELECT 1 FROM biosample b "
            "WHERE b.biosample_accession = sdv.biosample_accession "
            f"AND {' AND '.join(time_conds)})"
        )

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
        # response_stratified cohorts ("... — responders" / "... — non-responders") are
        # outcome labels, not study arms: no arm_or_cohort row can match them, and the
        # LLM fallback would pick an arbitrary arm — the same one for every stratum.
        if study_design == "response_stratified":
            return None
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
                return await resolve_disease_stage(s, disease_stage, study_accession, claim_text=claim_text)
            if disease:
                result = await resolve_condition(s, disease, study_accession, claim_text=claim_text)
                if result is None:
                    return None
                val, method = result
                return (val, method, "disease")
        return None

    cell_type = group.get("cell_type", "") or ""

    async def _tissue():
        if not (study_accession and (tissue_type or cell_type)):
            return None
        async with session_factory() as s:
            if cell_type:
                return await resolve_cell_type(s, tissue_type, cell_type, study_accession, claim_text=claim_text)
            result = await resolve_tissue_type(s, tissue_type, study_accession, claim_text=claim_text)
            if result:
                val, method, matched_col = result
                type_val = val if matched_col == "type" else None
                subtype_val = val if matched_col == "subtype" else None
                return (type_val, subtype_val, method, "")
            return None

    async def _pv():
        if not (time_point and study_accession):
            return None
        async with session_factory() as s:
            return await resolve_planned_visit_accession(s, time_point, study_accession, claim_text=claim_text)

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

    if cond_result:
        canonical, method, field = cond_result
        if field == "arm_accession":
            group["arm_accession"] = canonical
            group["disease_stage"] = ""
            group["disease"] = ""
            resolution_log["arm"] = {"accession": canonical, "method": method}
            logger.info("Resolved disease_stage %r → arm_accession %s for group %s (arm fallback)", disease_stage, canonical, group_id)
        elif field == "disease_stage":
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
        group["disease_stage"] = ""

    if study_accession:
        group["study_accession"] = study_accession

    if tissue_result:
        type_val, subtype_val, method, functional_marker = tissue_result
        group["bio_type"] = type_val or ""
        group["bio_subtype"] = subtype_val or ""
        group["bio_description_marker"] = functional_marker or ""
        resolution_log["tissue_type"] = {
            "type_value": type_val, "subtype_value": subtype_val,
            "method": method, "functional_marker": functional_marker,
        }
    else:
        group["bio_type"] = ""
        group["bio_subtype"] = ""
        group["bio_description_marker"] = ""

    if pv_result:
        pv_accessions = pv_result  # list[tuple[str, str]]
        resolution_log["planned_visit"] = {
            "accessions": [a for a, _ in pv_accessions],
            "method": pv_accessions[0][1],
        }
        logger.info(
            "Resolved time_point %r → %d planned_visit(s) for group %s",
            time_point, len(pv_accessions), group_id,
        )
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
            "study_design": study_design,
        }

    if pv_accessions:
        return [_make_query_dict(pv_acc) for pv_acc, _ in pv_accessions]
    return [_make_query_dict(None)]



async def resolve_and_build_queries(
    description_analysis: list[dict],
    study_accession: str | None,
    session_factory,
    claim_text: str | None = None,
    assay_registry: dict | None = None,
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
    # Cache for ImmPort candidate lists, fetched lazily on resolution failure.
    _candidates_cache: dict[str, list[dict]] = {}

    def _cached(resolver_fn, search_term, *args):
        """Return a Task for resolver_fn(search_term, *args), reusing if already started."""
        key = (resolver_fn, search_term)
        if key not in _cache:
            _cache[key] = asyncio.ensure_future(resolver_fn(*args, search_term, study_accession))
        return _cache[key]

    async def _fetch_candidates(table: str, cols: str) -> list[dict]:
        """Return all rows for the study from table, cached per table name."""
        if table not in _candidates_cache:
            async with session_factory() as s:
                result = await s.execute(
                    text(f"SELECT {cols} FROM {table} WHERE study_accession = :sa"),
                    {"sa": study_accession},
                )
                _candidates_cache[table] = [
                    dict(zip(result.keys(), row)) for row in result.fetchall()
                ]
        return _candidates_cache[table]

    async def _resolve_group_cached(group: dict) -> list[dict]:
        """Like _resolve_group but delegates to cached tasks for each resolver."""
        group = dict(group)
        group_id = group.get("group_id")
        resolution_log: dict = {}
        resolution_failures: list[dict] = []

        cohort       = group.get("cohort", "") or ""
        assay_method = group.get("assay_method", "") or ""
        disease      = group.get("disease", "") or ""
        disease_stage = group.get("disease_stage", "") or ""
        tissue_type  = group.get("tissue_type", "") or ""
        cell_type    = group.get("cell_type", "") or ""
        study_design = group.get("study_design", "")
        time_point   = group.pop("time_point", None) or ""
        age          = group.get("age")
        comparison   = group.get("comparison") or []

        # Multi-tissue fan-out: split "PBMC, bone marrow" → one sub-group per token.
        # Sub-groups share the same group_id so _execute_all_queries unions their subjects.
        tissue_tokens = _split_multi_tissue(tissue_type)
        if len(tissue_tokens) > 1:
            logger.info("Group %s: multi-tissue fan-out → %s", group_id, tissue_tokens)
            sub_groups = []
            for token in tissue_tokens:
                g = dict(group)
                g["tissue_type"] = token
                if time_point:
                    g["time_point"] = time_point
                sub_groups.append(g)
            nested = await asyncio.gather(*[_resolve_group_cached(g) for g in sub_groups])
            return [item for sub in nested for item in sub]

        async def _arm():
            # See _resolve_group._arm: response strata are outcome labels, not study arms.
            if study_design == "response_stratified":
                return None
            if not (cohort and study_accession):
                return None
            tokens = _split_multi_tissue(cohort)
            if len(tokens) <= 1:
                async with session_factory() as s:
                    return await resolve_arm_accession(s, cohort, study_accession, claim_text=claim_text)
            # Multi-cohort: resolve each token independently in parallel.
            # Returns list[tuple] so the caller can distinguish from a single-arm (acc, method) tuple.
            async def _resolve_one(token: str):
                async with session_factory() as s:
                    return await resolve_arm_accession(s, token, study_accession, claim_text=claim_text)
            results = await asyncio.gather(*[_resolve_one(t) for t in tokens])
            resolved = [r for r in results if r]
            return resolved if resolved else None

        async def _exp():
            if not (assay_method and study_accession):
                return None
            registry_entry = ((assay_registry or {}).get(assay_method) or {})
            async with session_factory() as s:
                return await resolve_experiment_accession(
                    s, assay_method, study_accession,
                    claim_text=claim_text,
                    original_name=registry_entry.get("name_in_paper", ""),
                    readouts=registry_entry.get("readouts", ""),
                )

        async def _cond():
            if study_design == "longitudinal" or not study_accession:
                return None
            search_term = disease_stage or disease
            if not search_term:
                return None
            async with session_factory() as s:
                return await resolve_disease_stage_placement(s, search_term, study_accession, claim_text=claim_text)

        async def _tissue():
            if not (study_accession and (tissue_type or cell_type)):
                return None
            async with session_factory() as s:
                if cell_type:
                    return await resolve_cell_type(s, tissue_type, cell_type, study_accession, claim_text=claim_text)
                result = await resolve_tissue_type(s, tissue_type, study_accession, claim_text=claim_text)
                if result:
                    val, method, matched_col = result
                    type_val = val if matched_col == "type" else None
                    subtype_val = val if matched_col == "subtype" else None
                    return (type_val, subtype_val, method, "")
                return None

        async def _pv():
            if not (time_point and study_accession):
                return None
            async with session_factory() as s:
                return await resolve_time_point_placement(s, time_point, study_accession, claim_text=claim_text)

        # Use cached tasks for arm, experiment, condition, tissue (commonly shared across groups)
        arm_key  = ("arm",  cohort)
        exp_key  = ("exp",  assay_method)
        cond_key = ("cond", disease_stage or disease, study_design)
        tis_key  = ("tis",  tissue_type, cell_type)
        pv_key   = ("pv",   time_point, study_design)

        def _get_or_create(key, coro_fn):
            if key not in _cache:
                _cache[key] = asyncio.ensure_future(coro_fn())
            return _cache[key]

        # Phase 1: resolve experiment first — it gates all other resolvers.
        # If the assay is absent from ImmPort there is nothing to query.
        exp_result = await _get_or_create(exp_key, _exp)

        if not exp_result and assay_method and study_accession:
            exp_candidates = await _fetch_candidates(
                "experiment", "experiment_accession, name, measurement_technique"
            )
            return [{
                "group_id": group_id or 0,
                "sql": "",
                "params": {},
                "resolution": {},
                "resolution_failures": [{
                    "field": "assay_method",
                    "original_value": assay_method,
                    "tried": "SQL LIKE on experiment(name, measurement_technique), then LLM fallback over all experiments",
                    "result": "not_resolved",
                    "immport_candidates": exp_candidates,
                }],
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
                "planned_visit_name": time_point,
                "age": age,
                "comparison": comparison,
                "study_design": study_design,
                "skipped": True,
                "skip_reason": "assay_not_resolved",
            }]

        # Phase 2: assay resolved — proceed with remaining resolvers concurrently
        arm_result, cond_result, tissue_result, pv_result = await asyncio.gather(
            _get_or_create(arm_key,  _arm),
            _get_or_create(cond_key, _cond),
            _get_or_create(tis_key,  _tissue),
            _get_or_create(pv_key,   _pv),
        )

        # exp_result is guaranteed truthy here
        exp_acc, method = exp_result
        group["experiment_accession"] = exp_acc
        resolution_log["experiment"] = {"accession": exp_acc, "method": method, "assay_method": assay_method}

        if arm_result:
            if isinstance(arm_result, list):
                # Multi-cohort: list of (acc, method) tuples, one per resolved token
                if len(arm_result) >= 2:
                    group["arm_accessions"] = [acc for acc, _ in arm_result]
                    resolution_log["arm"] = {
                        "accessions": group["arm_accessions"],
                        "method": arm_result[0][1],
                    }
                    logger.info(
                        "Group %s: multi-cohort resolved %d arms → %s",
                        group_id, len(arm_result), group["arm_accessions"],
                    )
                else:
                    arm_acc, method = arm_result[0]
                    group["arm_accession"] = arm_acc
                    resolution_log["arm"] = {"accession": arm_acc, "method": method}
            else:
                arm_acc, method = arm_result
                group["arm_accession"] = arm_acc
                resolution_log["arm"] = {"accession": arm_acc, "method": method}
        elif cohort and study_accession and study_design != "response_stratified":
            # response_stratified skips arm resolution by design, so an unresolved cohort
            # is expected there and must not be reported as a resolution failure.
            arm_candidates = await _fetch_candidates(
                "arm_or_cohort", "arm_accession, name, description"
            )
            resolution_failures.append({
                "field": "cohort",
                "original_value": cohort,
                "tried": "SQL LIKE on arm_or_cohort(name, description), then LLM fallback over all study arms",
                "result": "not_resolved",
                "immport_candidates": arm_candidates,
            })

        extra_pv_from_cond: list[tuple[str, str]] = []
        if cond_result:
            extra_pv_from_cond = _apply_placement_result(group, resolution_log, cond_result)
        else:
            group["disease"] = ""
            group["disease_stage"] = ""  # clear so the unresolved value is never used as a literal exact-match filter
            if study_design != "longitudinal" and study_accession:
                search_term = disease_stage or disease
                if search_term:
                    resolution_failures.append({
                        "field": "disease_stage" if disease_stage else "disease",
                        "original_value": search_term,
                        "tried": "DS-placement: disease_stage_preferred, condition, planned_visit, arm name, SDV scan, LLM",
                        "result": "not_resolved",
                    })

        if study_accession:
            group["study_accession"] = study_accession

        if tissue_result:
            type_val, subtype_val, method, functional_marker = tissue_result
            group["bio_type"] = type_val or ""
            group["bio_subtype"] = subtype_val or ""
            group["bio_description_marker"] = functional_marker or ""
            resolution_log["tissue_type"] = {
                "type_value": type_val,
                "subtype_value": subtype_val,
                "method": method,
                "functional_marker": functional_marker,
            }
            logger.info(
                "Resolved cell type for group %s: type=%r subtype=%r marker=%r (method=%s)",
                group_id, type_val, subtype_val, functional_marker, method,
            )
        else:
            group["bio_type"] = ""
            group["bio_subtype"] = ""
            group["bio_description_marker"] = ""

        if pv_result:
            pv_accessions = _apply_placement_result(group, resolution_log, pv_result)
        else:
            pv_accessions = []
            if time_point and study_accession:
                resolution_failures.append({
                    "field": "time_point",
                    "original_value": time_point,
                    "tried": "TP-placement: planned_visit (range+LIKE+LLM), study_time_collected range, arm name",
                    "result": "not_resolved",
                })

        # Merge any PVs produced by cond resolution (disease_stage drifted into time_point slot)
        if extra_pv_from_cond:
            seen_pv = {acc for acc, _ in pv_accessions}
            pv_accessions += [(a, m) for a, m in extra_pv_from_cond if a not in seen_pv]

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
                "resolution_failures": resolution_failures,
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
                "study_design": study_design,
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
