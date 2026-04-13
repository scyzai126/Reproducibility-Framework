"""Run a claim JSON file through the query pipeline and save subject IDs to data/generated/outputIDs."""

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

IMMPORT_URL = "mysql+aiomysql://cs2635:Edic-123@localhost:3306/immport_dr62"

engine = create_async_engine(IMMPORT_URL, echo=False)
immport_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _execute_group_query(session: AsyncSession, sql: str, params: dict) -> list[dict]:
    result = await session.execute(text(sql), params)
    columns = list(result.keys())
    return [dict(zip(columns, row)) for row in result.fetchall()]


async def run(claim_path: Path, study_accession: str, output_path: Path):
    from app.agent.query_builder import resolve_and_build_queries

    raw = json.loads(claim_path.read_text(encoding="utf-8"))

    # Fields that are metadata/internal, not query filters
    _SKIP_FIELDS = {"group_id", "study_accession", "sample_size", "comparison"}

    results = {}

    for claim_key, claim_data in raw.items():
        claim_text = claim_data.get("claim", "")
        comparison_strategy = claim_data.get("comparison_strategy") or ""
        groups = []
        for group in claim_data.get("groups", []):
            group = dict(group)
            group["study_accession"] = study_accession
            group["study_design"] = comparison_strategy
            groups.append(group)

        if not groups:
            results[claim_key] = {
                "claim": claim_text,
                "comparison_strategy": comparison_strategy,
                "comparison": claim_data.get("comparison", []),
                "groups": [],
            }
            continue

        print(f"Resolving {len(groups)} groups for {claim_key} ({study_accession})...")
        # Process per-claim with claim_text, matching orchestrator behavior
        group_queries = await resolve_and_build_queries(groups, study_accession, immport_session, claim_text=claim_text)

        results[claim_key] = {
            "claim": claim_text,
            "comparison_strategy": comparison_strategy,
            "comparison": claim_data.get("comparison", []),
            "groups": [],
        }

        for gq, orig in zip(group_queries, groups):
            params = gq["params"]
            group_id = str(orig.get("group_id"))

            input_filters = {
                k: v for k, v in orig.items()
                if k not in _SKIP_FIELDS and v not in (None, "", [])
            }
            resolved_params = {k: v for k, v in params.items() if v and k != "study_accession"}
            pv_res = gq.get("resolution", {}).get("planned_visit")
            if pv_res and "planned_visit_accession" not in resolved_params:
                resolved_params["planned_visit_accession"] = pv_res.get("accession")
            tissue_res = gq.get("resolution", {}).get("tissue_type")
            if tissue_res:
                resolved_params["tissue_type"] = tissue_res.get("value")
                resolved_params["tissue_matched_col"] = tissue_res.get("matched_column")
            elif orig.get("tissue_type"):
                resolved_params["tissue_type"] = None
                resolved_params["tissue_matched_col"] = None

            try:
                async with immport_session() as s:
                    rows = await _execute_group_query(s, gq["sql"], params)
                subjects = [
                    f"{r.get('subject_accession', '')};{r.get('biosample_accession', '')};{r.get('expsample_accession', '')}"
                    for r in rows
                ]
                unique_subjects = len({r.get("subject_accession") for r in rows if r.get("subject_accession")})
                print(f"  Group {group_id}: {len(rows)} rows, {unique_subjects} unique subjects")
                results[claim_key]["groups"].append({
                    "group_id": group_id,
                    "input_filters": input_filters,
                    "resolved_params": resolved_params,
                    "subjects": subjects,
                    "experiment_count": len(rows),
                    "subject_count": unique_subjects,
                })
            except Exception as exc:
                print(f"  Group {group_id}: ERROR - {exc}")
                results[claim_key]["groups"].append({
                    "group_id": group_id,
                    "input_filters": input_filters,
                    "resolved_params": {},
                    "subjects": [],
                    "experiment_count": 0,
                    "subject_count": 0,
                    "error": str(exc),
                })

    output = {"study_accession": study_accession, "results": list(results.values())}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nSaved to {output_path}")


async def main():
    jobs = [
        ("claims/SDY1393_PMC9924941/claims_LLM_SDY1393_HailongEdit.json", "SDY1393", "data/generated/outputIDs/SDY1393_subject_ids.json"),
        ("claims/SDY1264_PMC4049462/claims_LLM_SDY1264_HailongEdit.json", "SDY1264", "data/generated/outputIDs/SDY1264_subject_ids.json"),
        ("claims/SDY1669_PMC7665312/claims_LLM_SDY1669.json", "SDY1669", "data/generated/outputIDs/SDY1669_subject_ids.json"),
    ]
    for claim_file, study, out_file in jobs:
        await run(Path(claim_file), study, Path(out_file))
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
