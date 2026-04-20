from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.assay_resolver import get_study_assay_methods as _get_study_assay_methods


def _mock_sql_result(rows: list[tuple[str, str | None]]):
    result = MagicMock()
    result.fetchall.return_value = rows
    return result


@pytest.mark.asyncio
async def test_assay_methods_use_measurement_technique_when_single_rna_seq():
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=_mock_sql_result(
            [
                ("RNA sequencing", "RNA Panel A"),
                ("Olink", "Inflammation"),
            ]
        )
    )

    assays = await _get_study_assay_methods(session, "SDY1000")

    assert assays == ["RNA sequencing", "Olink"]


@pytest.mark.asyncio
async def test_assay_methods_use_name_when_multiple_rna_seq_rows():
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=_mock_sql_result(
            [
                ("RNA sequencing", "Bulk RNA-seq"),
                ("RNA sequencing", "scRNA-seq"),
                ("Olink", "Inflammation"),
            ]
        )
    )

    assays = await _get_study_assay_methods(session, "SDY2000")

    assert assays == ["Bulk RNA-seq", "scRNA-seq", "Olink"]

