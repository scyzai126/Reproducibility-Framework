import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.assay_resolver import get_study_assay_methods
from app.agent.claim_parser import fetch_paper_content_async, parse_paper_claims_from_text, parse_paper_claims_step1_only, parse_paper_claims_noimmport, PaperNotAvailableError
from app.agent.ncbi_utils import pmid_to_pmc_url, pmc_to_pmid
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

_DISK_CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "ValidatedPapersCache" / "paper_claims"

_DEDUP_SKIP = {"group_id", "study_accession", "study_design"}


def _dedup_groups(groups: list[dict]) -> list[dict]:
    """Remove duplicate groups where all scientific filter fields are identical."""
    seen: list[dict] = []
    for g in groups:
        normalized = {k: v for k, v in g.items() if k not in _DEDUP_SKIP}
        if normalized not in seen:
            seen.append(normalized)
    if len(seen) == len(groups):
        return groups
    # Reassign group_ids and restore metadata from first occurrence of each unique group
    result = []
    for i, normalized in enumerate(seen):
        original = next(g for g in groups if {k: v for k, v in g.items() if k not in _DEDUP_SKIP} == normalized)
        result.append({**original, "group_id": i})
    return result


def _load_disk_cache(pubmed_id: str | int, step: str) -> dict | None:
    path = _DISK_CACHE_DIR / str(pubmed_id) / f"{step}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Corrupt disk cache at %s — ignoring", path)
    return None


def _save_disk_cache(pubmed_id: str | int, step: str, data: dict) -> None:
    path = _DISK_CACHE_DIR / str(pubmed_id) / f"{step}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Disk cache written: %s", path)




_URL_PATTERNS = [
    # PubMed: pubmed.ncbi.nlm.nih.gov/32788292
    (re.compile(r"https?://(?:www\.)?pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", re.I), "pubmed_id"),
    # PMC full: pmc.ncbi.nlm.nih.gov/articles/PMC7665312
    (re.compile(r"https?://(?:www\.)?pmc\.ncbi\.nlm\.nih\.gov/articles/PMC(\d+)", re.I), "pubmed_id"),
    # Europe PMC / other PMC links
    (re.compile(r"europepmc\.org/article/MED/(\d+)", re.I), "pubmed_id"),
]





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
        keywords = gq.get("keywords", {}) or {}
        resolution = gq.get("resolution", {}) or {}
        resolvers: dict[str, str] = {}

        # Prefer readable keywords from groups.json / LLM output, but only
        # for fields that successfully resolved to accessions.
        arm_res = resolution.get("arm", {}) or {}
        if keywords.get("cohort") and arm_res.get("accession"):
            resolvers["cohort"] = keywords["cohort"]
        elif arm_res.get("accession"):
            resolvers["arm"] = arm_res["accession"]
        elif params.get("arm_accession"):
            resolvers["arm"] = params["arm_accession"]

        exp_res = resolution.get("experiment", {}) or {}
        if keywords.get("assay_method") and exp_res.get("accession"):
            resolvers["assay_method"] = keywords["assay_method"]
        elif exp_res.get("accession"):
            resolvers["experiment"] = exp_res["accession"]

        pv_res = resolution.get("planned_visit", {}) or {}
        _pv_resolved = pv_res.get("accession") or pv_res.get("accessions")
        if keywords.get("time_point") and _pv_resolved:
            resolvers["time_point"] = keywords["time_point"]
        elif _pv_resolved:
            resolvers["planned_visit"] = pv_res.get("accession") or str(pv_res.get("accessions"))

        if keywords.get("disease_stage"):
            resolvers["disease_stage"] = keywords["disease_stage"]
        elif keywords.get("disease"):
            resolvers["disease"] = keywords["disease"]

        if keywords.get("tissue_type"):
            resolvers["tissue_type"] = keywords["tissue_type"]

        if keywords.get("age"):
            resolvers["age"] = str(keywords["age"])
        if keywords.get("gender"):
            resolvers["gender"] = keywords["gender"]

        # Backfill from resolved values where keyword is absent.
        if exp_res.get("assay_method") and not resolvers.get("assay_method"):
            resolvers["assay_method"] = exp_res["assay_method"]

        disease_stage_res = resolution.get("disease_stage", {})
        if disease_stage_res.get("value") and not resolvers.get("disease_stage"):
            resolvers["disease_stage"] = disease_stage_res["value"]

        disease_res = resolution.get("disease", {})
        if disease_res.get("value") and not resolvers.get("disease"):
            resolvers["disease"] = disease_res["value"]

        tissue_res = resolution.get("tissue_type", {})
        if tissue_res.get("value") and not resolvers.get("tissue_type"):
            resolvers["tissue_type"] = tissue_res["value"]

        if gq.get("planned_visit_name") and _pv_resolved and not resolvers.get("time_point"):
            resolvers["time_point"] = gq["planned_visit_name"]

        # Last fallback: IDs only when no readable alternative exists.
        if params.get("experiment_accession") and exp_res.get("accession") and not resolvers.get("assay_method"):
            resolvers["experiment"] = params["experiment_accession"]
        if params.get("planned_visit_accession") and _pv_resolved and not resolvers.get("time_point"):
            resolvers["planned_visit"] = params["planned_visit_accession"]
        if params.get("arm_accession") and arm_res.get("accession") and not (resolvers.get("cohort") or resolvers.get("arm")):
            resolvers["arm"] = params["arm_accession"]

        return resolvers

    async def _run_one(gq) -> tuple[dict, str]:
        if gq.get("skipped"):
            return (
                {
                    "group_id": gq["group_id"],
                    "resolvers": {"assay_method": gq.get("keywords", {}).get("assay_method", "")},
                    "comparison": gq.get("comparison", []),
                    "subjects": [],
                    "samples": [],
                    "skipped": True,
                    "error": "Assay method not found in ImmPort for this study — group skipped",
                },
                f"Group {gq['group_id']}: skipped (assay not resolved in ImmPort)",
            )

        params = gq["params"]
        try:
            async with session_factory() as s:
                rows = await _execute_group_query(s, gq["sql"], params)
            subject_ids = [row.get("subject_accession", "") for row in rows]
            logger.info("Group %s: found %d samples", gq["group_id"], len(rows))
            resolvers = _build_resolvers(gq)
            return (
                {
                    "group_id": gq["group_id"],
                    "resolvers": resolvers,
                    "comparison": gq.get("comparison", []),
                    # Canonical key used by response schema + UI.
                    "subjects": rows,
                    # Backward-compat for cached/output consumers that still read "samples".
                    "samples": rows,
                },
                f"Group {gq['group_id']}: {len(rows)} samples found\n"
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
                    "samples": [],
                    "error": str(exc),
                },
                f"Group {gq['group_id']}: ERROR - {exc}\n"
                f"  Resolvers: {json.dumps(resolvers)}",
            )

    pairs = await asyncio.gather(*[_run_one(gq) for gq in group_queries])

    # Step 1: merge subjects from queries that share a group_id (time-range expansion
    # produces one query per planned visit, all with the same group_id).
    merged_by_gid: dict[int, dict] = {}
    for result, log_line in pairs:
        gid = result["group_id"]
        if gid not in merged_by_gid:
            merged_by_gid[gid] = result
        else:
            existing = merged_by_gid[gid]
            seen_accs = {s.get("subject_accession") for s in existing["subjects"]}
            new_rows = [s for s in result["subjects"] if s.get("subject_accession") not in seen_accs]
            if new_rows:
                existing["subjects"] = existing["subjects"] + new_rows
                existing["samples"] = existing["subjects"]
            log_lines.append(
                f"Group {gid}: merged {len(new_rows)} additional subjects "
                f"from planned_visit {result['resolvers'].get('time_point', '?')}"
            )

    # Step 2: dedup truly duplicate groups (different group_ids that resolved to
    # identical DB criteria — e.g. two LLM groups describing the same cohort).
    subject_results = []
    seen_resolvers: list[dict] = []
    for result in merged_by_gid.values():
        if result["resolvers"] not in seen_resolvers:
            seen_resolvers.append(result["resolvers"])
            subject_results.append(result)
        else:
            log_lines.append(f"Group {result['group_id']}: skipped (duplicate resolvers)")
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


def _save_output(result: dict) -> None:
    """Write agent result to data/generated/outputIDs/{study_accession}_subject_ids_LLM.json."""
    study_accession = result.get("study_accession", "").strip()
    if not study_accession:
        return
    out_dir = Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "generated" / "outputIDs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{study_accession}_subject_ids_LLM.json"
    out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved output to %s", out_file)


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


def _build_data_gaps(
    subject_results: list[dict],
    group_queries: list[dict],
    failed_group_ids: set,
) -> list[dict]:
    """Identify groups where all fields resolved but the DB returned 0 subjects."""
    gq_by_id = {gq["group_id"]: gq for gq in group_queries}
    gaps: list[dict] = []
    for sr in subject_results:
        if sr.get("skipped"):
            continue
        if len(sr.get("subjects", [])) > 0:
            continue
        if sr["group_id"] in failed_group_ids:
            continue
        gq = gq_by_id.get(sr["group_id"])
        if not gq:
            continue
        resolution = gq.get("resolution", {}) or {}
        if not (resolution.get("arm") or resolution.get("experiment")):
            continue
        keywords = gq.get("keywords", {}) or {}
        arm_acc = (resolution.get("arm") or {}).get("accession", "")
        exp_acc = (resolution.get("experiment") or {}).get("accession", "")
        assay = keywords.get("assay_method") or (resolution.get("experiment") or {}).get("assay_method", "")
        cohort = keywords.get("cohort", "")
        time_point = keywords.get("time_point", "")

        assay_label = f"'{assay}' ({exp_acc})" if assay else exp_acc
        reason_parts = [f"The {assay_label} assay exists in ImmPort but has no subjects or samples linked to it"]
        if cohort:
            reason_parts.append(f"for the {cohort} cohort")
        if time_point:
            reason_parts.append(f"at {time_point}")
        reason = " ".join(reason_parts)

        gaps.append({
            "group_id": sr["group_id"],
            "cohort": cohort,
            "assay_method": assay,
            "time_point": time_point,
            "arm_accession": arm_acc,
            "experiment_accession": exp_acc,
            "reason": reason,
        })
    return gaps


def _build_completeness_report(study_accession: str, claims_results: list[dict]) -> dict:
    """Build a completeness report from resolution_failures and data_gaps per claim."""
    claims_with_issues: list[dict] = []
    for r in claims_results:
        failures = r.get("resolution_failures") or []
        data_gaps = r.get("data_gaps") or []
        if not failures and not data_gaps:
            continue

        # Promote assay_method failures to claim level — all groups share the same assay
        claim_failures: list[dict] = []
        seen_assay_values: set[str] = set()
        filtered_groups: list[dict] = []

        for group in failures:
            non_assay = [f for f in group.get("failures", []) if f["field"] != "assay_method"]
            for f in group.get("failures", []):
                if f["field"] == "assay_method" and f["original_value"] not in seen_assay_values:
                    seen_assay_values.add(f["original_value"])
                    claim_failures.append(f)
            if non_assay:
                filtered_groups.append({**group, "failures": non_assay})

        if claim_failures or filtered_groups or data_gaps:
            claims_with_issues.append({
                "claim_id": r.get("claim_id"),
                "claim_text": r.get("claim_text", ""),
                "source": r.get("source", {}),
                "sources": r.get("sources", []),
                "claim_failures": claim_failures,
                "groups": filtered_groups,
                "data_gaps": data_gaps,
            })
    return {
        "study_accession": study_accession,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_claims": len(claims_results),
        "claims_with_failures": len(claims_with_issues),
        "claims": claims_with_issues,
    }


def _write_completeness_log(report: dict) -> None:
    """Write the completeness report to logs/completeness_report.json."""
    log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "completeness_report.json"
    log_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Completeness report written to %s", log_file)


def _build_completeness_summary(report: dict) -> dict:
    """Derive a flat summary from a completeness report (for the API response)."""
    from collections import Counter
    field_counter: Counter = Counter()
    failed_groups = 0
    data_gap_groups = 0
    for claim in report.get("claims", []):
        # Claim-level failures (e.g. assay_method) count once per claim
        for f in claim.get("claim_failures", []):
            field_counter[f["field"]] += 1
        for group in claim.get("groups", []):
            failed_groups += 1
            for f in group.get("failures", []):
                field_counter[f["field"]] += 1
        data_gap_groups += len(claim.get("data_gaps", []))
    return {
        "total_claims": report.get("total_claims", 0),
        "claims_with_failures": report.get("claims_with_failures", 0),
        "failed_groups": failed_groups,
        "data_gap_groups": data_gap_groups,
        "failed_fields": [
            {"field": field, "count": cnt}
            for field, cnt in field_counter.most_common()
        ],
    }


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
    step1_claims: dict | None = None,
) -> dict:
    """Shared pipeline after paper text + study are resolved.

    Runs for both the text (URL/PMID) path and the PDF upload path:
      1. Sync study data
      2. Extract filters from question (if any)
      3a. Filters found → parallel: step-1 claims + subject query
      3b. No filters → full step-2 deep claim analysis
    """
    await _sync_study(study_accession, log_sections)
    assay_methods = await get_study_assay_methods(session, study_accession)
    log_sections.append(
        f"--- Assay Methods ---\n"
        f"study_accession: {study_accession}\n"
        f"assay_methods: {assay_methods}"
    )

    # Filter extraction from question is disabled for now
    _filters: list[dict] = []

    if _filters:
        # Parallel: step-1 claims listing + subject query from filters
        async def _task_claims() -> list[dict]:
            if (disk := _load_disk_cache(pubmed_id, "claims")) is not None:
                logger.info("Step1 disk-cache hit for pubmed_id=%s", pubmed_id)
                step1_json = disk
            else:
                step1_json = await parse_paper_claims_step1_only(
                    paper_text, study_accession, assay_methods
                )
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
        result = {
            "study_accession": study_accession,
            "paper_claims": paper_claims,
            "subject_results": subject_results,
        }
        _save_output(result)
        return result

    # No filters → full deep claim analysis
    log_sections.append("--- Full Deep Analysis (no filters in question) ---")
    result = await _run_full_paper_analysis(
        paper_text, study_accession, assay_methods, pubmed_id, log_sections,
        step1_claims=step1_claims,
    )
    _write_workflow_log(log_sections)
    _save_output(result)
    return result


async def _run_full_paper_analysis(
    paper_text: str,
    study_accession: str,
    assay_methods: list[str],
    pubmed_id: str,
    log_sections: list[str],
    step1_claims: dict | None = None,
) -> dict:
    """Full two-step claim extraction + DB queries for every claim."""
    if (disk2 := _load_disk_cache(pubmed_id, "groups")) is not None:
        logger.info("Disk-cache hit (step2) for pubmed_id=%s", pubmed_id)
        step2_json = disk2
    elif step1_claims is not None:
        # Vision-extracted step1 provided — skip step1, run step2 only
        logger.info("Using vision step1 claims for pubmed_id=%s — running step2 only", pubmed_id)
        _, step2_json = await parse_paper_claims_from_text(
            paper_text, study_accession, assay_methods,
            cached_step1=step1_claims,
        )
    elif (disk1 := _load_disk_cache(pubmed_id, "claims")) is not None:
        # Step1 on disk — skip step1, run step2 only
        logger.info("Disk-cache hit (step1 only) for pubmed_id=%s — running step2", pubmed_id)
        _, step2_json = await parse_paper_claims_from_text(
            paper_text, study_accession, assay_methods,
            cached_step1=disk1
        )
    else:
        # No cache — run both steps fresh, no persistence
        step1_json, step2_json = await parse_paper_claims_from_text(
            paper_text, study_accession, assay_methods
        )

    claims: list[dict] = []
    batch_analysis: dict[str, list[dict]] = {}
    for key, val in step2_json.items():
        try:
            num = int(key.split("_")[1])
        except (IndexError, ValueError):
            continue
        if not isinstance(val, dict):
            logger.warning("Skipping malformed cache entry %r (not a dict)", key)
            continue
        sources = val.get("sources") or []
        claims.append({
            "id": num,
            "claim_text": val.get("claim", ""),
            "source": sources[0] if sources else {},
            "sources": sources,
            "comparison": val.get("comparison", []),
        })
        comparison_strategy = val.get("comparison_strategy") or val.get("study_design") or ""
        groups = [
            {**g, "study_design": comparison_strategy} for g in val.get("groups", [])
        ]
        batch_analysis[str(num)] = _dedup_groups(groups)

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
                    "source": claim.get("source", {}), "sources": claim.get("sources", []),
                    "comparison": claim.get("comparison", []),
                    "subject_results": [],
                }, local_logs

            comparison_strategy = (claim_analysis[0].get("study_design") or "") if claim_analysis else ""
            if not comparison_strategy or comparison_strategy.lower() == "none":
                local_logs.append(f"--- Claim {claim_id}: comparison_strategy='{comparison_strategy}' — skipping resolver and SQL.")
                return {
                    "claim_id": claim_id,
                    "claim_text": claim.get("claim_text", ""),
                    "source": claim.get("source", {}), "sources": claim.get("sources", []),
                    "study_design": comparison_strategy or None,
                    "comparison": claim.get("comparison", []),
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
            claim_group_failures = [
                {"group_id": gq["group_id"], "failures": gq["resolution_failures"]}
                for gq in group_queries
                if gq.get("resolution_failures")
            ]

            t2 = time.time()
            exec_log: list[str] = [f"--- Claim {claim_id}: Query Execution ---"]
            subject_results = await _execute_all_queries(group_queries, async_session, exec_log)
            logger.info("Claim %s: execute_all_queries took %.2fs", claim_id, time.time() - t2)

            # If multiple groups were defined but none resolved to distinct DB identifiers,
            # the group classification is wrong — drop the claim.
            if len(group_queries) > 1 and len(subject_results) <= 1:
                reason = (
                    f"Claim {claim_id} dropped: {len(group_queries)} groups defined "
                    f"but none resolved to distinct DB identifiers (all groups collapsed to the same resolvers). "
                    f"Group cohorts: {[g.get('cohort') or g.get('disease') for g in claim_analysis]}"
                )
                local_logs.append(f"--- Claim {claim_id}: DROPPED ---\n{reason}")
                logger.warning(reason)
                return {"claim_id": claim_id, "claim_text": claim.get("claim_text", ""), "source": claim.get("source", {}), "sources": claim.get("sources", []), "subject_results": [], "resolution_failures": claim_group_failures}, local_logs

            for i, sr in enumerate(subject_results):
                sr["group_id"] = i
            local_logs.append("\n".join(exec_log))

            failed_group_ids = {g["group_id"] for g in claim_group_failures}
            claim_data_gaps = _build_data_gaps(subject_results, group_queries, failed_group_ids)

            return {
                "claim_id": claim_id,
                "claim_text": claim.get("claim_text", ""),
                "source": claim.get("source", {}), "sources": claim.get("sources", []),
                "study_design": claim_analysis[0].get("study_design") if claim_analysis else None,
                "comparison": claim.get("comparison", []),
                "subject_results": subject_results,
                "resolution_failures": claim_group_failures,
                "data_gaps": claim_data_gaps,
            }, local_logs
        except Exception as exc:
            logger.error("Claim %s failed: %s", claim_id, exc)
            local_logs.append(f"--- Claim {claim_id}: ERROR ---\n{exc}")
            return {
                "claim_id": claim_id,
                "claim_text": claim.get("claim_text", ""),
                "source": claim.get("source", {}), "sources": claim.get("sources", []),
                "subject_results": [],
                "error": str(exc),
            }, local_logs

    pairs = await asyncio.gather(*[_process_claim(c) for c in claims])
    claims_results: list[dict] = []
    for result, logs in pairs:
        claims_results.append(result)
        log_sections.extend(logs)

    _completeness_report = _build_completeness_report(study_accession, claims_results)
    _write_completeness_log(_completeness_report)
    completeness = _build_completeness_summary(_completeness_report)
    for r in claims_results:
        r.pop("resolution_failures", None)
        r.pop("data_gaps", None)

    claims_results = [
        r for r in claims_results
        if any(len(sr.get("subjects", sr.get("samples", []))) > 0 for sr in r.get("subject_results", []))
    ]

    for i, r in enumerate(claims_results):
        r["claim_id"] = i + 1

    return {"study_accession": study_accession, "claims": claims_results, "completeness": completeness}


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
                            "source": claim.get("source", {}), "sources": claim.get("sources", []), "subject_results": []}, local_logs

                comparison_strategy = (claim_analysis[0].get("study_design") or "") if claim_analysis else ""
                if not comparison_strategy or comparison_strategy.lower() == "none":
                    local_logs.append(f"--- Claim {claim_id}: comparison_strategy='{comparison_strategy}' — skipping resolver and SQL.")
                    return {
                        "claim_id": claim_id,
                        "claim_text": claim.get("claim_text", ""),
                        "source": claim.get("source", {}), "sources": claim.get("sources", []),
                        "study_design": comparison_strategy or None,
                        "subject_results": [],
                    }, local_logs

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
                claim_group_failures = [
                    {"group_id": gq["group_id"], "failures": gq["resolution_failures"]}
                    for gq in group_queries
                    if gq.get("resolution_failures")
                ]

                t2 = time.time()
                exec_log: list[str] = [f"--- Claim {claim_id}: Query Execution ---"]
                subject_results = await _execute_all_queries(group_queries, async_session, exec_log)
                logger.info("Claim %s: execute_all_queries took %.2fs", claim_id, time.time() - t2)
                for i, sr in enumerate(subject_results):
                    sr["group_id"] = i
                local_logs.append("\n".join(exec_log))

                failed_group_ids = {g["group_id"] for g in claim_group_failures}
                claim_data_gaps = _build_data_gaps(subject_results, group_queries, failed_group_ids)

                return {
                    "claim_id": claim_id,
                    "claim_text": claim.get("claim_text", ""),
                    "source": claim.get("source", {}), "sources": claim.get("sources", []),
                    "study_design": claim_analysis[0].get("study_design") if claim_analysis else None,
                    "subject_results": subject_results,
                    "resolution_failures": claim_group_failures,
                    "data_gaps": claim_data_gaps,
                }, local_logs

            except Exception as exc:
                logger.error("Claim %s failed: %s", claim_id, exc)
                local_logs.append(f"--- Claim {claim_id}: ERROR ---\n{exc}")
                return {"claim_id": claim_id, "claim_text": claim.get("claim_text", ""),
                        "source": claim.get("source", {}), "sources": claim.get("sources", []), "subject_results": [],
                        "error": str(exc)}, local_logs

        pairs = await asyncio.gather(*[_process_one_claim(c) for c in claims])

        claims_results: list[dict] = []
        for result, logs in pairs:
            claims_results.append(result)
            log_sections.extend(logs)

        _completeness_report = _build_completeness_report(study_accession or "", claims_results)
        _write_completeness_log(_completeness_report)
        completeness = _build_completeness_summary(_completeness_report)
        for r in claims_results:
            r.pop("resolution_failures", None)
            r.pop("data_gaps", None)

        claims_results = [
            r for r in claims_results
            if any(len(sr.get("subjects", sr.get("samples", []))) > 0 for sr in r.get("subject_results", []))
        ]

        _write_workflow_log(log_sections)
        result = {
            "study_accession": study_accession or "",
            "claims": claims_results,
            "completeness": completeness,
        }
        _save_output(result)
        return result

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
            # Bare PMID (e.g. "PMID:32788292") has no URL yet — check cache first
            if pmc_id and not paper_url:
                # pmc_id is the PubMed ID here — check disk cache before any network call
                if _load_disk_cache(pmc_id, "groups") is not None:
                    row = (await session.execute(
                        text("SELECT study_accession FROM study_pubmed WHERE pubmed_id = :pid LIMIT 1"),
                        {"pid": pmc_id},
                    )).fetchone()
                    if row:
                        log_sections.append(
                            f"--- Step 2: PMID cache hit ---\n"
                            f"pubmed_id: {pmc_id} → study_accession: {row[0]}"
                        )
                        return await _run_paper_pipeline(
                            "", pmc_id, row[0], session, question or None, log_sections
                        )
                paper_url = await pmid_to_pmc_url(pmc_id)
                if not paper_url:
                    return {
                        "type": "pdf_upload_required",
                        "study_accession": "",
                        "pubmed_id": pmc_id,
                    }
            if pmc_id and paper_url:
                # pmc_id is the PMC numeric ID — resolve pubmed_id cheaply before fetching
                resolved_pubmed_id = await pmc_to_pmid(pmc_id)
                if resolved_pubmed_id and _load_disk_cache(resolved_pubmed_id, "groups") is not None:
                    row = (await session.execute(
                        text("SELECT study_accession FROM study_pubmed WHERE pubmed_id = :pid LIMIT 1"),
                        {"pid": resolved_pubmed_id},
                    )).fetchone()
                    if row:
                        log_sections.append(
                            f"--- Step 2: PMC URL cache hit ---\n"
                            f"pmc_id: {pmc_id} → pubmed_id: {resolved_pubmed_id} → study_accession: {row[0]}"
                        )
                        return await _run_paper_pipeline(
                            "", resolved_pubmed_id, row[0], session, question or None, log_sections
                        )

                # Cache miss — fetch full paper XML
                try:
                    fetched_paper_text, pubmed_id_from_paper = await fetch_paper_content_async(paper_url)
                except PaperNotAvailableError:
                    fallback_pid = resolved_pubmed_id or pmc_id
                    sdy_row = (await session.execute(
                        text("SELECT study_accession FROM study_pubmed WHERE pubmed_id = :pid LIMIT 1"),
                        {"pid": fallback_pid},
                    )).fetchone()
                    return {
                        "type": "pdf_upload_required",
                        "study_accession": sdy_row[0] if sdy_row else "",
                        "pubmed_id": fallback_pid,
                    }
                pubmed_id = pubmed_id_from_paper or resolved_pubmed_id or pmc_id
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
                    logger.info("PubMed ID %s not in ImmPort — running no-ImmPort claim extraction", pubmed_id)
                    log_sections.append(
                        f"--- No ImmPort Match ---\n"
                        f"PubMed ID {pubmed_id} is not linked to any ImmPort study. "
                        f"Running claim extraction without subject ID lookup."
                    )
                    paper_claims = await parse_paper_claims_noimmport(fetched_paper_text, paper_url)
                    _write_workflow_log(log_sections)
                    return {
                        "type": "no_immport",
                        "study_accession": "",
                        "paper_claims": paper_claims,
                        "subject_results": [],
                        "claims": [],
                    }

                # ── Paper URL path: always do claim analysis ─────────────────
                if study_accession:
                    return await _run_paper_pipeline(
                        fetched_paper_text, pubmed_id, study_accession,
                        session, question or None, log_sections
                    )
            else:
                # Check for SDY accession → look up all pubmed_ids → fetch each paper → claim analysis
                sdy_match = re.search(r"\bSDY\d+\b", file_content, re.I)
                if sdy_match:
                    sdy_accession = sdy_match.group(0).upper()
                    sdy_question = re.sub(r"\bSDY\d+\b", "", file_content, flags=re.I).strip()
                    sdy_rows = (await session.execute(
                        text("SELECT pubmed_id FROM study_pubmed WHERE study_accession = :sa"),
                        {"sa": sdy_accession},
                    )).fetchall()
                    if sdy_rows:
                        sdy_pubmed_ids = [str(r[0]) for r in sdy_rows]
                        paper_results = []

                        for sdy_pubmed_id in sdy_pubmed_ids:
                            paper_log = list(log_sections)

                            # Check cache before any network calls
                            if _load_disk_cache(sdy_pubmed_id, "groups") is not None:
                                paper_log.append(
                                    f"--- Step 2: SDY cache hit ---\n"
                                    f"study_accession: {sdy_accession} → pubmed_id: {sdy_pubmed_id}"
                                )
                                result = await _run_paper_pipeline(
                                    "", sdy_pubmed_id, sdy_accession,
                                    session, sdy_question or None, paper_log
                                )
                                result["pubmed_id"] = sdy_pubmed_id
                                paper_results.append(result)
                                continue

                            sdy_paper_url = await pmid_to_pmc_url(sdy_pubmed_id)
                            if not sdy_paper_url:
                                paper_results.append({
                                    "type": "pdf_upload_required",
                                    "study_accession": sdy_accession,
                                    "pubmed_id": sdy_pubmed_id,
                                })
                                continue
                            try:
                                sdy_paper_text, _ = await fetch_paper_content_async(sdy_paper_url)
                            except PaperNotAvailableError:
                                paper_results.append({
                                    "type": "pdf_upload_required",
                                    "study_accession": sdy_accession,
                                    "pubmed_id": sdy_pubmed_id,
                                })
                                continue

                            paper_log.append(
                                f"--- Step 2: SDY → Paper ---\n"
                                f"study_accession: {sdy_accession} → pubmed_id: {sdy_pubmed_id}"
                            )
                            result = await _run_paper_pipeline(
                                sdy_paper_text, sdy_pubmed_id, sdy_accession,
                                session, sdy_question or None, paper_log
                            )
                            result["pubmed_id"] = sdy_pubmed_id
                            paper_results.append(result)

                        # Single paper → return as before; multiple → return list
                        if len(paper_results) == 1:
                            return paper_results[0]
                        return {"type": "multi_paper", "papers": paper_results}
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
    result = {
        "study_accession": study_accession or "",
        "subject_results": subject_results,
    }
    _save_output(result)
    return result


async def run_agent(file_path: str, session: AsyncSession) -> dict:
    """Entry point for file-based input: reads file then runs the core pipeline."""
    file_content = read_file(file_path)
    return await _run_agent_core(file_content, session)


async def run_agent_from_text(message: str, session: AsyncSession, study_accession_hint: str | None = None) -> dict:
    """Entry point for plain-text input: passes message directly to the core pipeline."""
    return await _run_agent_core(message, session, study_accession_hint=study_accession_hint)


async def run_agent_from_pdf_vision(
    pdf_bytes: bytes,
    pubmed_id: str,
    session: AsyncSession,
    question: str | None = None,
) -> dict:
    """Entry point for PDF vision workflow: render PDF pages as images, extract claims
    via GPT-4o vision (step 1), then run step 2 structuring and DB queries.

    pubmed_id must be provided explicitly — it cannot be inferred from images.
    """
    from openai import AsyncOpenAI
    from app.agent.pdf_vision import extract_claims_from_pdf_images
    from app.config import settings

    log_sections: list[str] = []

    # ── Step 1: vision extraction ─────────────────────────────────────────────
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    logger.info("Vision pipeline: extracting claims from PDF (pubmed_id=%s)", pubmed_id)
    assays, step1_claims = await extract_claims_from_pdf_images(pdf_bytes, client)
    n_claims = len([k for k in step1_claims if k.startswith("claim_")])
    log_sections.append(
        f"--- Step 1: Vision Extraction ---\n"
        f"pubmed_id: {pubmed_id}\n"
        f"Assays: {list(assays.keys())}\n"
        f"Claims extracted: {n_claims}"
    )
    logger.info("Vision step1 complete: %d claims, assays=%s", n_claims, list(assays.keys()))

    # ── Step 2: study lookup ──────────────────────────────────────────────────
    row = (await session.execute(
        text("SELECT study_accession FROM study_pubmed WHERE pubmed_id = :pid LIMIT 1"),
        {"pid": pubmed_id},
    )).fetchone()

    if not row:
        logger.info("PubMed ID %s not in ImmPort — returning vision claims only", pubmed_id)
        log_sections.append(
            f"--- Step 2: No ImmPort Match ---\n"
            f"PubMed ID {pubmed_id} is not linked to any ImmPort study."
        )
        paper_claims = [
            {"claim_id": key, "claim_text": val.get("claim", ""), "sources": val.get("sources", [])}
            for key, val in step1_claims.items()
            if key.startswith("claim_")
        ]
        _write_workflow_log(log_sections)
        return {
            "type": "no_immport",
            "study_accession": "",
            "paper_claims": paper_claims,
            "claims": [],
        }

    study_accession: str = row[0]
    log_sections.append(
        f"--- Step 2: Study Lookup ---\n"
        f"pubmed_id: {pubmed_id} → study_accession: {study_accession}"
    )

    # ── Step 3–N: shared pipeline (step2 structuring + DB queries) ───────────
    return await _run_paper_pipeline(
        paper_text="",
        pubmed_id=pubmed_id,
        study_accession=study_accession,
        session=session,
        question=question,
        log_sections=log_sections,
        step1_claims=step1_claims,
    )


async def run_agent_from_paper(
    pdf_bytes: bytes,
    filename: str,
    session: AsyncSession,
    question: str | None = None,
    pubmed_id: str | None = None,
) -> dict:
    """Entry point for PDF upload: extract text, look up study, run full pipeline.

    Steps:
      1. Extract text from PDF bytes.
      2. Parse PubMed ID from filename (or use explicit pubmed_id parameter).
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
    if not pubmed_id:
        pubmed_id = extract_pubmed_id_from_filename(filename)
    if not pubmed_id:
        raise ValueError(
            f"Could not extract a PubMed ID from the filename '{filename}'. "
            "Please provide the PubMed ID explicitly or rename the file to include it. "
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
        logger.info("PubMed ID %s not in ImmPort — running no-ImmPort claim extraction from PDF", pubmed_id)
        log_sections.append(
            f"--- Step 3: No ImmPort Match ---\n"
            f"PubMed ID {pubmed_id} is not linked to any ImmPort study. "
            f"Running claim extraction without subject ID lookup."
        )
        paper_claims = await parse_paper_claims_noimmport(paper_text, filename)
        _write_workflow_log(log_sections)
        return {
            "type": "no_immport",
            "study_accession": "",
            "paper_claims": paper_claims,
            "subject_results": [],
            "claims": [],
        }
    study_accession: str = row[0]
    log_sections.append(
        f"--- Step 3: Study Lookup ---\n"
        f"pubmed_id: {pubmed_id} → study_accession: {study_accession}"
    )

    # ── 4. Run shared pipeline (sync, assay extraction, filter extraction, claims/samples) ──────
    return await _run_paper_pipeline(
        paper_text, pubmed_id, study_accession, session, question, log_sections
    )


async def run_agent_from_pubmed_id(
    pubmed_id: str,
    session: AsyncSession,
    question: str | None = None,
) -> dict:
    """Entry point for PubMed-ID-only requests (no PDF upload).

    Fetches full-text XML from PMC, then runs the same pipeline as run_agent_from_paper.
    Raises ValueError if the paper is not available as open-access XML on PMC.
    """
    from app.agent.ncbi_utils import pmid_to_pmc_url
    from app.agent.claim_parser import fetch_paper_content_async, PaperNotAvailableError

    log_sections: list[str] = []

    # ── 1. Resolve PMC URL ───────────────────────────────────────────────────
    pmc_url = await pmid_to_pmc_url(pubmed_id)
    if not pmc_url:
        raise ValueError(
            f"PubMed ID {pubmed_id} has no open-access PMC record. "
            "Please upload the PDF instead."
        )
    log_sections.append(f"--- Step 1: PMC URL ---\npubmed_id: {pubmed_id} → {pmc_url}")

    # ── 2. Fetch paper text ──────────────────────────────────────────────────
    try:
        paper_text, _ = await fetch_paper_content_async(pmc_url)
    except PaperNotAvailableError as exc:
        raise ValueError(str(exc)) from exc
    log_sections.append(
        f"--- Step 2: Paper Text ---\nFetched {len(paper_text)} chars from {pmc_url}"
    )

    # ── 3. Study lookup ──────────────────────────────────────────────────────
    row = (await session.execute(
        text("SELECT study_accession FROM study_pubmed WHERE pubmed_id = :pid LIMIT 1"),
        {"pid": pubmed_id},
    )).fetchone()
    if not row:
        logger.info("PubMed ID %s not in ImmPort — running no-ImmPort extraction", pubmed_id)
        log_sections.append(
            f"--- Step 3: No ImmPort Match ---\n"
            f"PubMed ID {pubmed_id} is not linked to any ImmPort study."
        )
        paper_claims = await parse_paper_claims_noimmport(paper_text, pmc_url)
        _write_workflow_log(log_sections)
        return {
            "type": "no_immport",
            "study_accession": "",
            "paper_claims": paper_claims,
            "subject_results": [],
            "claims": [],
        }
    study_accession: str = row[0]
    log_sections.append(
        f"--- Step 3: Study Lookup ---\n"
        f"pubmed_id: {pubmed_id} → study_accession: {study_accession}"
    )

    # ── 4. Run shared pipeline ───────────────────────────────────────────────
    return await _run_paper_pipeline(
        paper_text, pubmed_id, study_accession, session, question, log_sections
    )
