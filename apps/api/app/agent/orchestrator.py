import asyncio
import json
import logging
import re
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.claim_parser import fetch_paper_content_async, parse_paper_claims_from_text, parse_paper_claims_step1_only
from app.agent.ncbi_utils import pmid_to_pmc_url
from app.agent.description_analyzer import analyze_claims_batch, analyze_descriptions
from app.agent.file_reader import read_file
from app.agent.paper_reader import extract_pdf_text, extract_pubmed_id_from_filename
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

# Fields that count as meaningful filter criteria (non-null = user specified something)
_FILTER_FIELDS = {"disease", "disease_stage", "cohort", "assay_method",
                  "tissue_type", "gender", "age", "time_point", "study_design"}

# Cache keyed by pubmed_id for the expensive LLM claim extraction steps.
# Different questions about the same paper skip re-parsing the paper entirely.
_paper_step1_cache: dict[str, dict] = {}   # pubmed_id → step1_json
_paper_claims_cache: dict[str, dict] = {}  # pubmed_id → step2_json (full analysis)

_EXAMPLE_CLAIMS_DIR = Path(__file__).resolve().parent.parent.parent / "exampleClaims"


def _load_example_claims(study_accession: str) -> tuple[dict, dict] | None:
    """Return (step1_json, step2_json) from exampleClaims/ for known studies, or None."""
    if not _EXAMPLE_CLAIMS_DIR.exists():
        return None
    for subdir in _EXAMPLE_CLAIMS_DIR.iterdir():
        if subdir.is_dir() and subdir.name.startswith(study_accession + "_"):
            step1_path = subdir / "step1.json"
            step2_files = list(subdir.glob("claims_LLM_*.json"))
            if step1_path.exists() and step2_files:
                step1 = json.loads(step1_path.read_text(encoding="utf-8"))
                step2 = json.loads(step2_files[0].read_text(encoding="utf-8"))
                logger.info("Loaded example claims for %s from %s", study_accession, subdir.name)
                return step1, step2
    return None



_URL_PATTERNS = [
    # PubMed: pubmed.ncbi.nlm.nih.gov/32788292
    (re.compile(r"https?://(?:www\.)?pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", re.I), "pubmed_id"),
    # PMC full: pmc.ncbi.nlm.nih.gov/articles/PMC7665312
    (re.compile(r"https?://(?:www\.)?pmc\.ncbi\.nlm\.nih\.gov/articles/PMC(\d+)", re.I), "pubmed_id"),
    # Europe PMC / other PMC links
    (re.compile(r"europepmc\.org/article/MED/(\d+)", re.I), "pubmed_id"),
]



async def _get_study_assay_methods(session: AsyncSession, study_accession: str) -> list[str]:
    """Return study assay labels with RNA-seq name fallback for multi-row studies.

    If a study has more than one experiment row with measurement_technique
    'RNA sequencing', we use each row's `name` as the assay label for those rows.
    Otherwise we use measurement_technique.
    """
    result = await session.execute(
        text(
            "SELECT measurement_technique, name "
            "FROM experiment "
            "WHERE study_accession = :sa AND measurement_technique IS NOT NULL"
        ),
        {"sa": study_accession},
    )
    rows = result.fetchall()

    def _is_rna_seq(mt: str | None) -> bool:
        return bool(mt and mt.strip().lower() == "rna sequencing")

    rna_seq_count = sum(1 for mt, _ in rows if _is_rna_seq(mt))
    use_rna_names = rna_seq_count > 1

    assay_methods: list[str] = []
    seen: set[str] = set()
    for measurement_technique, name in rows:
        mt = (measurement_technique or "").strip()
        nm = (name or "").strip()
        if not mt:
            continue
        assay = nm if (use_rna_names and _is_rna_seq(mt) and nm) else mt
        if assay not in seen:
            seen.add(assay)
            assay_methods.append(assay)
    return assay_methods


def _extract_pubmed_id_from_text(message: str) -> tuple[str | None, str | None, str]:
    """Scan message for a paper URL or bare PMC/PMID pattern.

    Returns (pubmed_id, paper_url, cleaned_message).
    paper_url is the matched URL string (for fetching paper text), or None for bare IDs.
    cleaned_message has the URL/ID stripped out.
    """
    for pattern, _ in _URL_PATTERNS:
        m = pattern.search(message)
        if m:
            pubmed_id = m.group(1)
            paper_url = m.group(0)          # full matched URL
            cleaned = pattern.sub("", message).strip()
            return pubmed_id, paper_url, cleaned

    # Bare patterns: PMC7665312 or PMID32788292 anywhere in text
    m = re.search(r"\bPMC(\d+)\b", message, re.I)
    if m:
        pubmed_id = m.group(1)
        # Reconstruct a PMC URL so _fetch_paper_text can use it
        paper_url = f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pubmed_id}/"
        cleaned = re.sub(r"\bPMC\d+\b", "", message, flags=re.I).strip()
        return pubmed_id, paper_url, cleaned

    m = re.search(r"\bPMID[:\s]*(\d+)\b", message, re.I)
    if m:
        pubmed_id = m.group(1)
        cleaned = re.sub(r"\bPMID[:\s]*\d+\b", "", message, flags=re.I).strip()
        # Return None for paper_url — caller must convert PMID → PMC ID via NCBI API
        return pubmed_id, None, cleaned

    return None, None, message


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
        # Replace experiment_accession with the human-readable assay method
        exp_res = gq.get("resolution", {}).get("experiment", {})
        if exp_res.get("assay_method"):
            resolvers.pop("experiment_accession", None)
            resolvers["assay_method"] = exp_res["assay_method"]
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


async def _run_paper_pipeline(
    paper_text: str,
    pubmed_id: str,
    study_accession: str,
    session: AsyncSession,
    question: str | None,
    log_sections: list[str],
) -> dict:
    """Shared pipeline after paper text + study are resolved.

    Runs for both the text (URL/PMID) path and the PDF upload path:
      1. Sync study data
      2. Extract filters from question (if any)
      3a. Filters found → parallel: step-1 claims + subject query
      3b. No filters → full step-2 deep claim analysis
    """
    await _sync_study(study_accession, log_sections)
    assay_methods = await _get_study_assay_methods(session, study_accession)
    log_sections.append(
        f"--- Assay Methods ---\n"
        f"study_accession: {study_accession}\n"
        f"assay_methods: {assay_methods}"
    )

    # Extract filters from the question
    _filters: list[dict] = []
    if question and question.strip():
        prompt = f"Study: {study_accession}\n{question}"
        _raw_filters, _ = await analyze_descriptions(prompt)
        _filters = [
            f for f in _raw_filters
            if any(f.get(field) for field in _FILTER_FIELDS) or f.get("comparison")
        ]
        log_sections.append(
            f"--- Filter Extraction ---\n"
            f"filters found: {len(_filters)} (raw: {len(_raw_filters)})"
        )

    if _filters:
        # Parallel: step-1 claims listing + subject query from filters
        async def _task_claims() -> list[dict]:
            example = _load_example_claims(study_accession)
            if example is not None:
                step1_json, _ = example
            elif pubmed_id in _paper_step1_cache:
                logger.info("Step1 cache hit for pubmed_id=%s", pubmed_id)
                step1_json = _paper_step1_cache[pubmed_id]
            else:
                step1_json = await parse_paper_claims_step1_only(
                    paper_text, study_accession, assay_methods
                )
                _paper_step1_cache[pubmed_id] = step1_json
                logger.info("Cached step1 claims for pubmed_id=%s", pubmed_id)
            return [
                {"claim_id": key, "claim_text": val.get("claim", ""), "sources": val.get("sources", [])}
                for key, val in step1_json.items()
                if key.startswith("claim_")
            ]

        async def _task_subjects() -> list[dict]:
            gqs = await resolve_and_build_queries(_filters, study_accession, async_session)
            exec_log: list[str] = []
            return await _execute_all_queries(gqs, async_session, exec_log)

        paper_claims, subject_results = await asyncio.gather(_task_claims(), _task_subjects())
        log_sections.append(
            f"--- Parallel Mode ---\n"
            f"Paper claims: {len(paper_claims)}, Subject groups: {len(subject_results)}"
        )
        _write_workflow_log(log_sections)
        return {
            "study_accession": study_accession,
            "paper_claims": paper_claims,
            "subject_results": subject_results,
        }

    # No filters → full deep claim analysis
    log_sections.append("--- Full Deep Analysis (no filters in question) ---")
    result = await _run_full_paper_analysis(
        paper_text, study_accession, assay_methods, pubmed_id, log_sections
    )
    _write_workflow_log(log_sections)
    return result


async def _run_full_paper_analysis(
    paper_text: str,
    study_accession: str,
    assay_methods: list[str],
    pubmed_id: str,
    log_sections: list[str],
) -> dict:
    """Full two-step claim extraction + DB queries for every claim."""
    example = _load_example_claims(study_accession)
    if example is not None:
        # Pre-computed example claims — skip LLM entirely
        step1_json, step2_json = example
    elif pubmed_id in _paper_claims_cache:
        # Both step1 + step2 cached — skip everything
        logger.info("Cache hit (step1+step2) for pubmed_id=%s — skipping both LLM steps", pubmed_id)
        step2_json = _paper_claims_cache[pubmed_id]
    elif pubmed_id in _paper_step1_cache:
        # Step1 cached — skip step1, run step2 only
        logger.info("Cache hit (step1 only) for pubmed_id=%s — skipping step1, running step2", pubmed_id)
        _, step2_json = await parse_paper_claims_from_text(
            paper_text, study_accession, assay_methods,
            cached_step1=_paper_step1_cache[pubmed_id]
        )
        _paper_claims_cache[pubmed_id] = step2_json
    else:
        # No cache — run both steps, populate both caches
        step1_json, step2_json = await parse_paper_claims_from_text(
            paper_text, study_accession, assay_methods
        )
        _paper_step1_cache[pubmed_id] = step1_json
        _paper_claims_cache[pubmed_id] = step2_json
        logger.info("Cached step1+step2 for pubmed_id=%s", pubmed_id)

    claims: list[dict] = []
    batch_analysis: dict[str, list[dict]] = {}
    for key, val in step2_json.items():
        try:
            num = int(key.split("_")[1])
        except (IndexError, ValueError):
            continue
        sources = val.get("sources") or []
        claims.append({
            "id": num,
            "claim_text": val.get("claim", ""),
            "source": sources[0] if sources else {},
        })
        comparison_strategy = val.get("comparison_strategy") or val.get("study_design") or ""
        groups = [
            {**g, "study_design": comparison_strategy} for g in val.get("groups", [])
        ]
        batch_analysis[str(num)] = groups

    log_sections.append(
        f"--- Full Claim Extraction ---\n"
        f"Claims extracted: {len(claims)}"
    )

    async def _process_claim(claim: dict) -> tuple[dict, list[str]]:
        claim_id = claim["id"]
        claim_analysis = batch_analysis.get(str(claim_id), [])
        local_logs: list[str] = []
        try:
            if not claim_analysis:
                local_logs.append(f"--- Claim {claim_id}: no groups — skipping.")
                return {
                    "claim_id": claim_id,
                    "claim_text": claim.get("claim_text", ""),
                    "source": claim.get("source", {}),
                    "subject_results": [],
                }, local_logs

            local_logs.append(
                f"--- Claim {claim_id}: Analysis ---\n"
                f"{json.dumps(claim_analysis, indent=2)}"
            )
            t1 = time.time()
            group_queries = await resolve_and_build_queries(claim_analysis, study_accession, async_session, claim_text=claim.get("claim_text"))
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
            return {
                "claim_id": claim_id,
                "claim_text": claim.get("claim_text", ""),
                "source": claim.get("source", {}),
                "subject_results": [],
                "error": str(exc),
            }, local_logs

    pairs = await asyncio.gather(*[_process_claim(c) for c in claims])
    claims_results: list[dict] = []
    for result, logs in pairs:
        claims_results.append(result)
        log_sections.extend(logs)

    return {"study_accession": study_accession, "claims": claims_results}


async def _run_agent_core(file_content: str, session: AsyncSession, study_accession_hint: str | None = None) -> dict:
    """Shared agent core: parse/analyze -> build SQL -> execute -> summarize.

    study_accession_hint: pre-resolved study accession (e.g. from an uploaded PDF).
    """

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
                    claim_analysis, study_accession, async_session,
                    claim_text=claim.get("claim_text"),
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
        question = file_content

        # Use pre-resolved study accession if provided (e.g. from PDF upload)
        if study_accession_hint:
            study_accession = study_accession_hint
            log_sections.append(
                f"--- Step 2: Plain Text Input ---\n"
                f"study_accession from uploaded paper: {study_accession}"
            )
        else:
            # Try to extract pubmed_id + URL from the question
            pmc_id, paper_url, question = _extract_pubmed_id_from_text(file_content)
            # Bare PMID (e.g. "PMID:32788292") has no URL yet — convert via NCBI
            if pmc_id and not paper_url:
                paper_url = await pmid_to_pmc_url(pmc_id)
                if not paper_url:
                    raise ValueError(
                        f"PubMed ID {pmc_id} has no open-access PMC article. "
                        "Please provide the full PMC URL instead."
                    )
            if pmc_id and paper_url:
                # Fetch paper XML once — get text + real PubMed ID (PMC ID ≠ PubMed ID)
                fetched_paper_text, pubmed_id_from_paper = await fetch_paper_content_async(paper_url)
                pubmed_id = pubmed_id_from_paper or pmc_id
                row = (await session.execute(
                    text("SELECT study_accession FROM study_pubmed WHERE pubmed_id = :pid LIMIT 1"),
                    {"pid": pubmed_id},
                )).fetchone()
                study_accession = row[0] if row else None
                log_sections.append(
                    f"--- Step 2: Plain Text Input ---\n"
                    f"PMC ID from URL: {pmc_id} → PubMed ID from paper: {pubmed_id} → study_accession: {study_accession}"
                )

                if not study_accession:
                    raise ValueError(
                        f"This paper (PubMed ID: {pubmed_id}) is not linked to any study in ImmPort. "
                        "Only papers associated with ImmPort studies can be analyzed."
                    )

                # ── Paper URL path: always do claim analysis ─────────────────
                if study_accession:
                    return await _run_paper_pipeline(
                        fetched_paper_text, pubmed_id, study_accession,
                        session, question or None, log_sections
                    )
            else:
                # Check for SDY accession → look up pubmed_id → fetch paper → claim analysis
                sdy_match = re.search(r"\bSDY\d+\b", file_content, re.I)
                if sdy_match:
                    sdy_accession = sdy_match.group(0).upper()
                    sdy_question = re.sub(r"\bSDY\d+\b", "", file_content, flags=re.I).strip()
                    sdy_row = (await session.execute(
                        text("SELECT pubmed_id FROM study_pubmed WHERE study_accession = :sa LIMIT 1"),
                        {"sa": sdy_accession},
                    )).fetchone()
                    if sdy_row:
                        sdy_pubmed_id = str(sdy_row[0])
                        sdy_paper_url = await pmid_to_pmc_url(sdy_pubmed_id)
                        if not sdy_paper_url:
                            raise ValueError(
                                f"Study {sdy_accession} (PubMed ID: {sdy_pubmed_id}) has no open-access PMC article. "
                                "Cannot fetch paper for claim analysis."
                            )
                        sdy_paper_text, _ = await fetch_paper_content_async(sdy_paper_url)

                        log_sections.append(
                            f"--- Step 2: SDY → Paper ---\n"
                            f"study_accession: {sdy_accession} → pubmed_id: {sdy_pubmed_id}"
                        )
                        return await _run_paper_pipeline(
                            sdy_paper_text, sdy_pubmed_id, sdy_accession,
                            session, sdy_question or None, log_sections
                        )
                    else:
                        raise ValueError(
                            f"Study {sdy_accession} was not found in ImmPort. "
                            "Please check the study accession and try again."
                        )
                else:
                    return {
                        "type": "clarification",
                        "question": (
                            "Which paper would you like me to analyze? Please include paper in one of these format:\n"
                            "• Paper URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC7665312/\n"
                            "• PubMed ID: PMID:32788292\n"
                            "• PMC ID: PMC7665312\n"
                            "• ImmPort study ID: SDY1669"
                        ),
                    }

        description_analysis, raw_llm = await analyze_descriptions(
            f"Study: {study_accession}\n{question}" if study_accession else question
        )
        log_sections.append(f"--- Step 3: LLM Raw Output ---\n{raw_llm}")
        if not study_accession and description_analysis:
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


async def run_agent_from_text(message: str, session: AsyncSession, study_accession_hint: str | None = None) -> dict:
    """Entry point for plain-text input: passes message directly to the core pipeline."""
    return await _run_agent_core(message, session, study_accession_hint=study_accession_hint)


async def run_agent_from_paper(pdf_bytes: bytes, filename: str, session: AsyncSession, question: str | None = None) -> dict:
    """Entry point for PDF upload: extract text, look up study, run full pipeline.

    Steps:
      1. Extract text from PDF bytes.
      2. Parse PubMed ID from filename.
      3. Look up study_accession in study_pubmed table.
      4. Fetch distinct measurement_technique values from experiment table.
      5. Sync study data to local DB if missing.
      6. Run two-step LLM claim extraction (claim_parser).
      7. Resolve terms → accessions and execute subject queries.
    """
    log_sections: list[str] = []

    # ── 1. PDF text ──────────────────────────────────────────────────────────
    paper_text = extract_pdf_text(pdf_bytes)
    log_sections.append(
        f"--- Step 1: PDF Input ---\n"
        f"Filename: {filename}\n"
        f"Extracted text length: {len(paper_text)} chars"
    )

    # ── 2. PubMed ID ─────────────────────────────────────────────────────────
    pubmed_id = extract_pubmed_id_from_filename(filename)
    if not pubmed_id:
        raise ValueError(
            f"Could not extract a PubMed ID from the filename '{filename}'. "
            "Please rename the file to include the PubMed ID before uploading. "
            "Accepted formats:\n"
            "• PMID32788292.pdf\n"
            "• 32788292.pdf"
        )
    log_sections.append(f"--- Step 2: PubMed ID ---\npubmed_id: {pubmed_id}")

    # ── 3. Study lookup ──────────────────────────────────────────────────────
    row = (await session.execute(
        text("SELECT study_accession FROM study_pubmed WHERE pubmed_id = :pid LIMIT 1"),
        {"pid": pubmed_id},
    )).fetchone()
    if not row:
        raise ValueError(f"No study found in study_pubmed for pubmed_id='{pubmed_id}'.")
    study_accession: str = row[0]
    log_sections.append(
        f"--- Step 3: Study Lookup ---\n"
        f"pubmed_id: {pubmed_id} → study_accession: {study_accession}"
    )

    # ── 4. Run shared pipeline (sync, assay extraction, filter extraction, claims/subjects) ──────
    return await _run_paper_pipeline(
        paper_text, pubmed_id, study_accession, session, question, log_sections
    )
