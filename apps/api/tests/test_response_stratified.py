"""Tests for the `response_stratified` comparison strategy.

Claims whose groups differ only by an outcome label ("responders" vs.
"non-responders") have no corresponding arm in ImmPort.  These tests pin the
three behaviours that keep such claims alive through the pipeline:

  1. arm resolution is skipped (no wasted LLM call, no arbitrary arm match)
  2. the unresolved cohort is not reported as a resolution failure
  3. the stratum label survives into `resolvers`, so the strata are not
     deduplicated into a single group by _execute_all_queries
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.query_builder import resolve_and_build_queries


@pytest.fixture
def session_factory():
    """A session_factory whose sessions are never actually queried."""

    @asynccontextmanager
    async def _factory():
        yield AsyncMock()

    return _factory


def _group(group_id: int, cohort: str, study_design: str) -> dict:
    return {
        "group_id": group_id,
        "cohort": cohort,
        "assay_method": "DNA microarray",
        "tissue_type": "whole blood",
        "disease": None,
        "disease_stage": None,
        "time_point": "day 3",
        "study_design": study_design,
    }


RESPONSE_GROUPS = [
    _group(0, "MCV4 vaccinees — responders", "response_stratified"),
    _group(1, "MCV4 vaccinees — non-responders", "response_stratified"),
]


async def _run(groups, session_factory):
    """Resolve groups with every resolver but the arm one stubbed out."""
    with patch(
        "app.agent.query_builder.resolve_arm_accession", new_callable=AsyncMock
    ) as arm, patch(
        "app.agent.query_builder.resolve_experiment_accession", new_callable=AsyncMock
    ) as exp, patch(
        "app.agent.query_builder.resolve_tissue_type", new_callable=AsyncMock
    ) as tis, patch(
        "app.agent.query_builder.resolve_time_point_placement", new_callable=AsyncMock
    ) as pv:
        arm.return_value = ("ARM9999", "LLM")
        exp.return_value = ("EXP15660", "SQL")
        tis.return_value = ("Whole blood", "SQL", "type")
        pv.return_value = None
        queries = await resolve_and_build_queries(groups, "SDY1260", session_factory)
    return queries, arm, exp


@pytest.mark.asyncio
async def test_response_stratified_skips_arm_resolution(session_factory):
    """No arm_or_cohort lookup is attempted for a response stratum."""
    _queries, arm, _exp = await _run(RESPONSE_GROUPS, session_factory)
    arm.assert_not_called()


@pytest.mark.asyncio
async def test_response_stratified_still_resolves_assay(session_factory):
    """Skipping the arm must not disable the other resolvers."""
    queries, _arm, exp = await _run(RESPONSE_GROUPS, session_factory)
    assert exp.called
    assert all(q["resolution"].get("experiment", {}).get("accession") == "EXP15660" for q in queries)


@pytest.mark.asyncio
async def test_response_stratified_cohort_is_not_a_resolution_failure(session_factory):
    """An unresolved response stratum is expected, not a failure to report."""
    queries, _arm, _exp = await _run(RESPONSE_GROUPS, session_factory)
    for q in queries:
        fields = {f["field"] for f in q.get("resolution_failures", [])}
        assert "cohort" not in fields


@pytest.mark.asyncio
async def test_response_stratified_carries_study_design_and_cohort(session_factory):
    """study_design + the stratum label reach the query dict for _build_resolvers."""
    queries, _arm, _exp = await _run(RESPONSE_GROUPS, session_factory)
    assert [q["study_design"] for q in queries] == ["response_stratified"] * 2
    assert [q["keywords"]["cohort"] for q in queries] == [
        "MCV4 vaccinees — responders",
        "MCV4 vaccinees — non-responders",
    ]


@pytest.mark.asyncio
async def test_non_response_strategy_still_resolves_arm(session_factory):
    """Control: the skip is scoped to response_stratified only."""
    groups = [_group(0, "Atlanta cohort", "case_control")]
    _queries, arm, _exp = await _run(groups, session_factory)
    arm.assert_called()
