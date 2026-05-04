from unittest.mock import AsyncMock, patch

import pytest

from app.agent.query_builder import (
    resolve_disease_stage_placement,
    resolve_time_point_placement,
)


@pytest.mark.asyncio
async def test_disease_stage_placement_falls_back_to_condition():
    session = AsyncMock()

    with patch("app.agent.query_builder.resolve_disease_stage", new_callable=AsyncMock) as mock_stage, \
         patch("app.agent.query_builder.resolve_condition", new_callable=AsyncMock) as mock_cond:
        mock_stage.return_value = None
        mock_cond.return_value = ("healthy", "SQL")

        result = await resolve_disease_stage_placement(session, "healthy", "SDY1708")

    assert result["placement"] == "disease"
    assert result["value"] == "healthy"
    assert result["method"] == "condition_fallback"


@pytest.mark.asyncio
async def test_disease_stage_placement_uses_time_fallback_before_arm():
    session = AsyncMock()

    with patch("app.agent.query_builder.resolve_disease_stage", new_callable=AsyncMock) as mock_stage, \
         patch("app.agent.query_builder.resolve_condition", new_callable=AsyncMock) as mock_cond, \
         patch("app.agent.query_builder.resolve_time_point_placement", new_callable=AsyncMock) as mock_time, \
         patch("app.agent.query_builder.resolve_arm_accession", new_callable=AsyncMock) as mock_arm:
        mock_stage.return_value = None
        mock_cond.return_value = None
        mock_time.return_value = {
            "placement": "planned_visit",
            "accessions": [("PV1", "SQL")],
            "method": "SQL",
            "source_value": "acute phase",
        }
        mock_arm.return_value = ("ARM1", "SQL")

        result = await resolve_disease_stage_placement(session, "acute phase", "SDY1288")

    assert result["placement"] == "planned_visit"
    mock_arm.assert_not_called()


@pytest.mark.asyncio
async def test_disease_stage_placement_uses_view_scan_last():
    session = AsyncMock()

    with patch("app.agent.query_builder.resolve_disease_stage", new_callable=AsyncMock) as mock_stage, \
         patch("app.agent.query_builder.resolve_condition", new_callable=AsyncMock) as mock_cond, \
         patch("app.agent.query_builder.resolve_time_point_placement", new_callable=AsyncMock) as mock_time, \
         patch("app.agent.query_builder.resolve_arm_accession", new_callable=AsyncMock) as mock_arm, \
         patch("app.agent.query_builder.scan_subject_data_view_for_value", new_callable=AsyncMock) as mock_scan:
        mock_stage.return_value = None
        mock_cond.return_value = None
        mock_time.return_value = None
        mock_arm.return_value = None
        mock_scan.return_value = {
            "placement": "disease",
            "value": "healthy",
            "method": "view_scan_fallback",
            "source_value": "healthy",
        }

        result = await resolve_disease_stage_placement(session, "healthy", "SDY1708")

    assert result["placement"] == "disease"
    assert result["method"] == "view_scan_fallback"


@pytest.mark.asyncio
async def test_time_point_placement_prefers_planned_visit():
    session = AsyncMock()

    with patch("app.agent.query_builder.resolve_planned_visit_accession", new_callable=AsyncMock) as mock_pv:
        mock_pv.return_value = [("PV10", "SQL")]

        result = await resolve_time_point_placement(session, "day 10", "SDY2189")

    assert result["placement"] == "planned_visit"
    assert result["accessions"] == [("PV10", "SQL")]


@pytest.mark.asyncio
async def test_time_point_placement_falls_back_to_view_scan():
    session = AsyncMock()

    with patch("app.agent.query_builder.resolve_planned_visit_accession", new_callable=AsyncMock) as mock_pv, \
         patch("app.agent.query_builder.resolve_arm_accession", new_callable=AsyncMock) as mock_arm, \
         patch("app.agent.query_builder.scan_subject_data_view_for_value", new_callable=AsyncMock) as mock_scan:
        mock_pv.return_value = None
        mock_arm.return_value = None
        mock_scan.return_value = {
            "placement": "disease_stage",
            "value": "convalescent",
            "method": "view_scan_fallback",
            "source_value": "convalescent",
        }

        result = await resolve_time_point_placement(session, "convalescent", "SDY1991")

    assert result["placement"] == "disease_stage"
    assert result["value"] == "convalescent"
