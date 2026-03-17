import asyncio
import json
import logging
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.description_analyzer import analyze_claims_batch, analyze_descriptions
from app.agent.file_reader import read_file
from app.agent.query_builder import (
    resolve_and_build_queries,
)
from app.agent.signature_parser import (
    format_claim_for_llm,
    format_claims_batch_for_llm,
    format_descriptions_for_llm,
    parse_claims,
    parse_signature,
)
from app.agent.study_sync import StudySyncer
from app.database import async_session

logger = logging.getLogger(__name__)


def _detect_json_type(file_content: str) -> str:
    """Return 'claims', 'signature', or 'plain' based on JSON content."""
    try:
        data = json.loads(file_content)
        if isinstance(data, dict):
            if "claims" in data:
                return "claims"
            if "participant_group" in data:
                return "signature"
    except (json.JSONDecodeError, TypeError):
        pass
    return "plain"


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


async def _execute_all_queries(
    group_queries: list[dict], session_factory, log_lines: list[str]
) -> list[dict]:
    """Execute all group queries concurrently, log results, and return subject_results list."""

    def _build_resolvers(gq: dict) -> dict:
        params = gq["params"]
        resolvers = {k: v for k, v in params.items() if v and k != "study_accession"}
        if gq.get("planned_visit_name"):
            resolvers["time_point"] = gq["planned_visit_name"]
        return resolvers

    async def _run_one(gq) -> tuple[dict, str]:
        params = gq["params"]
        try:
            async with session_factory() as s:
                rows = await _execute_group_query(s, gq["sql"], params)
            subject_ids = [row.get("subject_accession", "") for row in rows]
            logger.info("Group %s: found %d subjects", gq["group_id"], len(rows))
            resolvers = _build_resolvers(gq)
            return (
                {
                    "group_id": gq["group_id"],
                    "resolvers": resolvers,
                    "comparison": gq.get("comparison", []),
                    "subjects": rows,
                },
                f"Group {gq['group_id']}: {len(rows)} subjects found\n"
                f"  Resolvers: {json.dumps(resolvers)}\n"
                f"  Subject IDs: {json.dumps(subject_ids)}",
            )
        except RuntimeError as exc:
            logger.error("Query failed for group %s: %s", gq["group_id"], exc)
            resolvers = _build_resolvers(gq)
            return (
                {
                    "group_id": gq["group_id"],
                    "resolvers": resolvers,
                    "comparison": gq.get("comparison", []),
                    "subjects": [],
                    "error": str(exc),
                },
                f"Group {gq['group_id']}: ERROR - {exc}\n"
                f"  Resolvers: {json.dumps(resolvers)}",
            )

    pairs = await asyncio.gather(*[_run_one(gq) for gq in group_queries])
    subject_results = []
    for result, log_line in pairs:
        subject_results.append(result)
        log_lines.append(log_line)
    return subject_results


def _log_queries(group_queries: list[dict]) -> str:
    lines = ["--- Resolution & Query Building ---"]
    for gq in group_queries:
        lines.append(
            f"Group {gq['group_id']}:\n"
            f"  Resolution: {json.dumps(gq.get('resolution', {}))}\n"
            f"  SQL: {gq['sql']}\n"
            f"  Params: {json.dumps(gq['params'])}"
        )
    return "\n".join(lines)


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


async def _sync_study(study_accession: str, log_sections: list[str]) -> None:
    """Ensure study is present in local DB; append sync log entry."""
    syncer = StudySyncer()
    sync_result = await syncer.ensure_study_downloaded(study_accession)
    if sync_result["action"] == "skipped":
        detail = "action: skipped (already present in local DB)"
    else:
        detail = (
            f"action: imported\n"
            f"  zip_path: {sync_result['zip_path']}\n"
            f"  extract_dir: {sync_result['extract_dir']}"
        )
    log_sections.append(
        f"--- Study Sync ---\n"
        f"study_accession: {study_accession}\n"
        f"{detail}"
    )


async def _run_agent_core(file_content: str, session: AsyncSession) -> dict:
    """Shared agent core: parse/analyze -> build SQL -> execute -> summarize."""

    log_sections: list[str] = []
    json_type = _detect_json_type(file_content)
    log_sections.append(
        f"--- Step 1: Input ---\n"
        f"Content length: {len(file_content)} chars\n"
        f"JSON type: {json_type}"
    )

    # ── Claims-based JSON (new format) ───────────────────────────────────────
    if json_type == "claims":
        claims, study_accession = parse_claims(file_content)
        log_sections.append(
            f"--- Step 2: Claims Parsing ---\n"
            f"Study accession: {study_accession}\n"
            f"Claims found: {len(claims)}"
        )

        # Sync study once before processing any claims
        if study_accession:
            await _sync_study(study_accession, log_sections)

        # Single LLM call for all claims
        t_batch = time.time()
        batch_text = format_claims_batch_for_llm(claims, study_accession)
        batch_analysis, batch_raw = await analyze_claims_batch(batch_text)
        logger.info("Batch analyze_descriptions took %.2fs for %d claims", time.time() - t_batch, len(claims))
        log_sections.append(
            f"--- Step 2: Batch Claim Analysis ---\n"
            f"Claims: {len(claims)}\n"
            f"Raw LLM output:\n{batch_raw}"
        )

        async def _process_one_claim(claim: dict) -> tuple[dict, list[str]]:
            claim_id = claim["id"]
            claim_analysis = batch_analysis.get(str(claim_id), [])
            logger.info("Claim %s: %d groups from batch analysis", claim_id, len(claim_analysis))
            local_logs: list[str] = []
            try:
                if not claim_analysis:
                    local_logs.append(
                        f"--- Claim {claim_id}: Analysis ---\n"
                        f"LLM returned no groups — skipping."
                    )
                    return {"claim_id": claim_id, "claim_text": claim.get("claim_text", ""),
                            "source": claim.get("source", {}), "subject_results": []}, local_logs

                local_logs.append(
                    f"--- Claim {claim_id}: Analysis ---\n"
                    f"{json.dumps(claim_analysis, indent=2)}"
                )

                t1 = time.time()
                group_queries = await resolve_and_build_queries(
                    claim_analysis, study_accession, async_session
                )
                logger.info("Claim %s: resolve_and_build_queries took %.2fs", claim_id, time.time() - t1)
                local_logs.append(_log_queries(group_queries))

                t2 = time.time()
                exec_log: list[str] = [f"--- Claim {claim_id}: Query Execution ---"]
                subject_results = await _execute_all_queries(group_queries, async_session, exec_log)
                logger.info("Claim %s: execute_all_queries took %.2fs", claim_id, time.time() - t2)
                for i, sr in enumerate(subject_results):
                    sr["group_id"] = i
                local_logs.append("\n".join(exec_log))

                return {
                    "claim_id": claim_id,
                    "claim_text": claim.get("claim_text", ""),
                    "source": claim.get("source", {}),
                    "study_design": claim_analysis[0].get("study_design") if claim_analysis else None,
                    "subject_results": subject_results,
                }, local_logs

            except Exception as exc:
                logger.error("Claim %s failed: %s", claim_id, exc)
                local_logs.append(f"--- Claim {claim_id}: ERROR ---\n{exc}")
                return {"claim_id": claim_id, "claim_text": claim.get("claim_text", ""),
                        "source": claim.get("source", {}), "subject_results": [],
                        "error": str(exc)}, local_logs

        pairs = await asyncio.gather(*[_process_one_claim(c) for c in claims])

        claims_results: list[dict] = []
        for result, logs in pairs:
            claims_results.append(result)
            log_sections.extend(logs)

        _write_workflow_log(log_sections)
        return {
            "study_accession": study_accession or "",
            "claims": claims_results,
        }

    # ── Legacy signature JSON (old format) ───────────────────────────────────
    description_analysis: list[dict] = []
    subject_results: list[dict] = []
    study_accession: str | None = None

    if json_type == "signature":
        groups, study_accession = parse_signature(file_content)
        descriptions_text = format_descriptions_for_llm(groups, study_accession)

        step2_lines = [
            f"--- Step 2: Signature Parsing ---\n"
            f"Study accession: {study_accession}\n"
            f"Groups found: {len(groups)}\n"
            f"Paper descriptions:"
        ]
        for g in groups:
            step2_lines.append(f"  Group {g['group_id']}:")
            for desc in g.get("descriptions", []):
                step2_lines.append(f"    - \"{desc}\"")
        log_sections.append("\n".join(step2_lines))

        if descriptions_text:
            description_analysis, raw_llm = await analyze_descriptions(descriptions_text)
            log_sections.append(f"--- Step 3: LLM Raw Output ---\n{raw_llm}")

        log_sections.append(
            f"--- Step 3: Description Analysis ---\n"
            f"Study accession (resolved): {study_accession}\n"
            f"{json.dumps(description_analysis, indent=2)}"
        )

    # ── Plain text ────────────────────────────────────────────────────────────
    else:
        log_sections.append(
            f"--- Step 2: Plain Text Input ---\n"
            f"No structured JSON detected. Using raw text as descriptions input."
        )
        description_analysis, raw_llm = await analyze_descriptions(file_content)
        log_sections.append(f"--- Step 3: LLM Raw Output ---\n{raw_llm}")
        if description_analysis:
            study_accession = description_analysis[0].get("study_accession")

        log_sections.append(
            f"--- Step 3: Description Analysis ---\n"
            f"Study accession (resolved): {study_accession}\n"
            f"{json.dumps(description_analysis, indent=2)}"
        )

    if study_accession:
        await _sync_study(study_accession, log_sections)

    group_queries = await resolve_and_build_queries(
        description_analysis, study_accession, async_session
    )
    log_sections.append(_log_queries(group_queries))

    exec_log = ["--- Step 7: Query Execution ---"]
    subject_results = await _execute_all_queries(group_queries, async_session, exec_log)
    log_sections.append("\n".join(exec_log))

    _write_workflow_log(log_sections)
    return {
        "study_accession": study_accession or "",
        "subject_results": subject_results,
    }


async def run_agent(file_path: str, session: AsyncSession) -> dict:
    """Entry point for file-based input: reads file then runs the core pipeline."""
    file_content = read_file(file_path)
    return await _run_agent_core(file_content, session)


async def run_agent_from_text(message: str, session: AsyncSession) -> dict:
    """Entry point for plain-text input: passes message directly to the core pipeline."""
    return await _run_agent_core(message, session)
