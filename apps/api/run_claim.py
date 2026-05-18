"""Run a claim JSON file through the query pipeline and save subject IDs to data/generated/outputIDs."""

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

IMMPORT_URL = "mysql+aiomysql://cs2635:Edic-123@localhost:3306/immport_dr62"

_SCRIPT_DIR = Path(__file__).resolve().parent
_DATA_DIR = _SCRIPT_DIR.parent.parent / "data"

engine = create_async_engine(IMMPORT_URL, echo=False)
immport_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _execute_group_query(session: AsyncSession, sql: str, params: dict) -> list[dict]:
    result = await session.execute(text(sql), params)
    columns = list(result.keys())
    return [dict(zip(columns, row)) for row in result.fetchall()]


async def run(claim_path: Path, study_accession: str, output_path: Path, session_factory=None):
    from app.agent.query_builder import resolve_and_build_queries

    if session_factory is None:
        session_factory = immport_session

    raw = json.loads(claim_path.read_text(encoding="utf-8"))

    # Fields that are metadata/internal, not query filters
    _SKIP_FIELDS = {"group_id", "study_accession", "sample_size", "comparison"}
    _DEDUP_SKIP = {"group_id", "study_accession", "study_design"}

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

        # Deduplicate groups with identical scientific filter fields
        seen: list[dict] = []
        deduped = []
        for g in groups:
            normalized = {k: v for k, v in g.items() if k not in _DEDUP_SKIP}
            if normalized not in seen:
                seen.append(normalized)
                deduped.append({**g, "group_id": len(deduped)})
        if len(deduped) < len(groups):
            print(f"  {claim_key}: deduplicated {len(groups)} → {len(deduped)} groups")
        groups = deduped

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
        group_queries = await resolve_and_build_queries(groups, study_accession, session_factory, claim_text=claim_text)

        results[claim_key] = {
            "claim": claim_text,
            "comparison_strategy": comparison_strategy,
            "comparison": claim_data.get("comparison", []),
            "groups": [],
        }

        # Group query dicts by group_id — multi-tissue fan-out produces multiple
        # query dicts per original group, all sharing the same group_id.
        orig_by_id = {str(g["group_id"]): g for g in groups}
        gqs_by_id: dict[str, list] = defaultdict(list)
        for gq in group_queries:
            gqs_by_id[str(gq["group_id"])].append(gq)

        for orig in groups:
            group_id = str(orig.get("group_id"))
            gqs = gqs_by_id.get(group_id, [])

            input_filters = {
                k: v for k, v in orig.items()
                if k not in _SKIP_FIELDS and v not in (None, "", [])
            }

            # Use the first query dict for resolved_params (representative)
            first_gq = gqs[0] if gqs else {}
            params = first_gq.get("params", {})
            resolved_params = {k: v for k, v in params.items() if v and k != "study_accession"}
            pv_res = first_gq.get("resolution", {}).get("planned_visit")
            if pv_res and "planned_visit_accession" not in resolved_params:
                resolved_params["planned_visit_accession"] = pv_res.get("accession")
            tissue_res = first_gq.get("resolution", {}).get("tissue_type")
            if tissue_res:
                resolved_params["tissue_type"] = tissue_res.get("value")
                resolved_params["tissue_matched_col"] = tissue_res.get("matched_column")
            elif orig.get("tissue_type"):
                resolved_params["tissue_type"] = None
                resolved_params["tissue_matched_col"] = None
            # Surface all tissue tokens when multi-tissue fan-out occurred
            tissue_tokens = [gq.get("tissue_token") for gq in gqs if gq.get("tissue_token")]
            if len(tissue_tokens) > 1:
                resolved_params["tissue_tokens"] = tissue_tokens

            # Execute all sub-queries and union rows across tissue tokens
            all_rows: list[dict] = []
            error: str | None = None
            for gq in gqs:
                try:
                    async with session_factory() as s:
                        rows = await _execute_group_query(s, gq["sql"], gq["params"])
                    all_rows.extend(rows)
                except Exception as exc:
                    print(f"  Group {group_id}: ERROR - {exc}")
                    error = str(exc)
                    break

            if error:
                results[claim_key]["groups"].append({
                    "group_id": group_id,
                    "input_filters": input_filters,
                    "resolved_params": {},
                    "subjects": [],
                    "experiment_count": 0,
                    "subject_count": 0,
                    "error": error,
                })
            else:
                subjects = [
                    f"{r.get('subject_accession', '')};{r.get('biosample_accession', '')};{r.get('expsample_accession', '')}"
                    for r in all_rows
                ]
                unique_subjects = len({r.get("subject_accession") for r in all_rows if r.get("subject_accession")})
                sub_note = f" ({len(gqs)} tissue sub-queries)" if len(gqs) > 1 else ""
                print(f"  Group {group_id}: {len(all_rows)} rows, {unique_subjects} unique subjects{sub_note}")
                results[claim_key]["groups"].append({
                    "group_id": group_id,
                    "input_filters": input_filters,
                    "resolved_params": resolved_params,
                    "subjects": subjects,
                    "experiment_count": len(all_rows),
                    "subject_count": unique_subjects,
                })

    output = {"study_accession": study_accession, "results": list(results.values())}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nSaved to {output_path}")


async def main():
    _VC = _DATA_DIR / "claims/validated_claims"
    jobs = [
        (_VC / "claims_LLM_SDY1373_AS.json",        "SDY1373", _DATA_DIR / "generated/outputIDs/SDY1373_subject_ids.json"),
        (_VC / "claims_LLM_SDY1288_ASedit.json",    "SDY1288", _DATA_DIR / "generated/outputIDs/SDY1288_subject_ids.json"),
        (_VC / "claims_LLM_SDY1708_HailongEdit.json","SDY1708", _DATA_DIR / "generated/outputIDs/SDY1708_subject_ids.json"),
        (_VC / "claims_LLM_SDY1991_HailongEdit.json","SDY1991", _DATA_DIR / "generated/outputIDs/SDY1991_subject_ids.json"),
        (_VC / "claims_LLM_SDY1995_HailongEdit.json","SDY1995", _DATA_DIR / "generated/outputIDs/SDY1995_subject_ids.json"),
        (_VC / "claims_LLM_SDY1654_AS.json",        "SDY1654", _DATA_DIR / "generated/outputIDs/SDY1654_subject_ids.json"),
        (_VC / "claims_LLM_SDY1393_HailongEdit.json","SDY1393", _DATA_DIR / "generated/outputIDs/SDY1393_subject_ids.json"),
    ]
    for claim_file, study, out_file in jobs:
        await run(claim_file, study, out_file)
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
