import json
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.description_analyzer import analyze_descriptions
from app.agent.file_reader import read_file
from app.agent.query_builder import resolve_and_build_queries
from app.agent.signature_parser import format_descriptions_for_llm, parse_signature
from app.agent.study_sync import StudySyncer
from app.database import async_session

logger = logging.getLogger(__name__)


def _is_signature_json(file_content: str) -> bool:
    """Check whether file_content looks like a signature JSON structure."""
    try:
        data = json.loads(file_content)
        return isinstance(data, dict) and "participant_group" in data
    except (json.JSONDecodeError, TypeError):
        return False


async def _execute_group_query(
    session: AsyncSession, sql: str, params: dict
) -> list[dict]:
    """Execute a parameterized SQL query and return rows as dicts."""
    try:
        result = await session.execute(text(sql), params)
        columns = list(result.keys())
        return [dict(zip(columns, row)) for row in result.fetchall()]
    except Exception as exc:
        raise RuntimeError(f"Query execution failed: {exc}") from exc


def _write_workflow_log(log_sections: list[str]) -> None:
    """Write accumulated workflow log sections to logs/agent_run.log."""
    log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "agent_run.log"

    with open(log_file, "w", encoding="utf-8") as f:
        f.write("=== Agent Workflow Log ===\n\n")
        f.write("\n".join(log_sections))
        f.write("\n")

    logger.info("Workflow log written to %s", log_file)


async def run_agent(file_path: str, session: AsyncSession) -> dict:
    """Main agent loop: read -> parse -> analyze -> build SQL -> execute -> enrich -> summarize."""

    log_sections: list[str] = []

    # 1. Read file content
    file_content = read_file(file_path)
    is_sig = _is_signature_json(file_content)
    log_sections.append(
        f"--- Step 1: File Read ---\n"
        f"File: {file_path}\n"
        f"Content length: {len(file_content)} chars\n"
        f"Is signature JSON: {str(is_sig).lower()}"
    )

    # 2. Parse signature JSON and analyze descriptions (if applicable)
    description_analysis: list[dict] = []
    subject_results: list[dict] = []
    study_accession: str | None = None
    groups: list[dict] = []

    if is_sig:
        groups, study_accession = parse_signature(file_content)
        descriptions_text = format_descriptions_for_llm(groups)

        # Log Step 2: Signature Parsing
        step2_lines = [
            f"--- Step 2: Signature Parsing ---\n"
            f"Study accession: {study_accession}\n"
            f"Groups found: {len(groups)}\n"
            f"Paper descriptions:"
        ]
        for g in groups:
            step2_lines.append(f"  Group {g['group_id']} ({g['group_name']}):")
            for desc in g.get("descriptions", []):
                step2_lines.append(f"    - \"{desc}\"")
        log_sections.append("\n".join(step2_lines))

        if descriptions_text:
            description_analysis = await analyze_descriptions(descriptions_text)

        # Log Step 3: Description Analysis
        log_sections.append(
            f"--- Step 3: Description Analysis ---\n"
            f"{json.dumps(description_analysis, indent=2)}"
        )

    # Step 3.5: Ensure study data is present in local DB
    if study_accession:
        syncer = StudySyncer()
        sync_result = await syncer.ensure_study_downloaded(study_accession)
        if sync_result["action"] == "skipped":
            sync_detail = f"action: skipped (already present in local DB)"
        else:
            sync_detail = (
                f"action: imported\n"
                f"  zip_path: {sync_result['zip_path']}\n"
                f"  extract_dir: {sync_result['extract_dir']}"
            )
        log_sections.append(
            f"--- Step 3.5: Study Sync ---\n"
            f"study_accession: {study_accession}\n"
            f"{sync_detail}"
        )

    # 3. Resolve accessions and build deterministic SQL queries
    group_queries = await resolve_and_build_queries(
        description_analysis, study_accession, async_session
    )

    # Log Step 4: Resolution & Query Building
    step6_lines = ["--- Step 4: Resolution & Query Building ---"]
    for gq in group_queries:
        resolution = gq.get("resolution", {})
        step6_lines.append(
            f"Group {gq['group_id']} ({gq['group_name']}):\n"
            f"  Resolution: {json.dumps(resolution)}\n"
            f"  SQL: {gq['sql']}\n"
            f"  Params: {json.dumps(gq['params'])}"
        )
    log_sections.append("\n".join(step6_lines))

    # 5. Execute each group's query
    step7_lines = ["--- Step 7: Query Execution ---"]
    for gq in group_queries:
        try:
            rows = await _execute_group_query(session, gq["sql"], gq["params"])
            subject_ids = [row.get("subject_accession", "") for row in rows]
            params = gq["params"]
            subject_results.append(
                {
                    "group_id": gq["group_id"],
                    "group_name": gq["group_name"],
                    "arm_accession": params.get("arm_accession", ""),
                    "experiment_accession": params.get("experiment_accession", ""),
                    "tissue_type": params.get("tissue_type", ""),
                    "condition": params.get("condition", ""),
                    "subjects": rows,
                }
            )
            step7_lines.append(
                f"Group {gq['group_id']} ({gq['group_name']}): {len(rows)} subjects found\n"
                f"  Subject IDs: {json.dumps(subject_ids)}"
            )
            logger.info(
                "Group %s (%s): found %d subjects",
                gq["group_id"],
                gq["group_name"],
                len(rows),
            )
        except RuntimeError as exc:
            logger.error("Query failed for group %s: %s", gq["group_id"], exc)
            params = gq["params"]
            subject_results.append(
                {
                    "group_id": gq["group_id"],
                    "group_name": gq["group_name"],
                    "arm_accession": params.get("arm_accession", ""),
                    "experiment_accession": params.get("experiment_accession", ""),
                    "tissue_type": params.get("tissue_type", ""),
                    "condition": params.get("condition", ""),
                    "subjects": [],
                    "error": str(exc),
                }
            )
            step7_lines.append(
                f"Group {gq['group_id']} ({gq['group_name']}): ERROR - {exc}"
            )
    log_sections.append("\n".join(step7_lines))

    # Write consolidated workflow log
    _write_workflow_log(log_sections)

    return {
        "study_accession": study_accession or "",
        "subject_results": subject_results,
    }
