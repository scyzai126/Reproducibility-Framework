from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.query_builder import (
    _llm_resolve,
    resolve_experiment_accession,
    _EXPERIMENT_CONFIG,
)


@pytest.fixture
def mock_session():
    """Create a mock AsyncSession that returns configurable query results."""
    session = AsyncMock()
    return session


def _make_result(rows, columns=("experiment_accession", "name", "measurement_technique")):
    """Create a mock SQLAlchemy result object."""
    mock_result = MagicMock()
    mock_result.keys.return_value = list(columns)
    mock_result.fetchall.return_value = [tuple(r.values()) for r in rows]
    return mock_result


@pytest.mark.asyncio
async def test_resolve_returns_none_for_empty_assay_method(mock_session):
    result = await resolve_experiment_accession(mock_session, "", "SDY1669")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_returns_none_for_empty_study(mock_session):
    result = await resolve_experiment_accession(mock_session, "Olink", "")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_single_sql_match(mock_session):
    """When SQL finds exactly 1 match, return it directly without LLM."""
    rows = [
        {
            "experiment_accession": "EXP12345",
            "name": "Olink inflammation panel",
            "measurement_technique": "Olink",
        }
    ]
    mock_session.execute = AsyncMock(return_value=_make_result(rows))

    result = await resolve_experiment_accession(mock_session, "Olink", "SDY1669")
    assert result == ("EXP12345", "SQL")


@pytest.mark.asyncio
async def test_resolve_no_sql_match_falls_back_to_llm(mock_session):
    """When SQL finds 0 matches, fall back to LLM with all experiments."""
    empty_result = _make_result([])
    all_experiments = [
        {
            "experiment_accession": "EXP12345",
            "name": "Olink inflammation panel",
            "measurement_technique": "Olink",
        },
        {
            "experiment_accession": "EXP12346",
            "name": "CITE-seq profiling",
            "measurement_technique": "CITE-seq",
        },
    ]
    all_experiments_result = _make_result(all_experiments)
    mock_session.execute = AsyncMock(
        side_effect=[empty_result, all_experiments_result]
    )

    with patch(
        "app.agent.query_builder._llm_resolve",
        new_callable=AsyncMock,
    ) as mock_llm:
        mock_llm.return_value = "EXP12345"
        result = await resolve_experiment_accession(
            mock_session, "multiplex inflammation", "SDY1669"
        )

    assert result == ("EXP12345", "LLM")
    mock_llm.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_multiple_sql_matches_falls_back_to_llm(mock_session):
    """When SQL finds 2+ matches, fall back to LLM."""
    two_rows = [
        {
            "experiment_accession": "EXP12345",
            "name": "Olink panel A",
            "measurement_technique": "Olink",
        },
        {
            "experiment_accession": "EXP12346",
            "name": "Olink panel B",
            "measurement_technique": "Olink",
        },
    ]
    two_result = _make_result(two_rows)
    all_experiments_result = _make_result(two_rows)
    mock_session.execute = AsyncMock(
        side_effect=[two_result, all_experiments_result]
    )

    with patch(
        "app.agent.query_builder._llm_resolve",
        new_callable=AsyncMock,
    ) as mock_llm:
        mock_llm.return_value = "EXP12345"
        result = await resolve_experiment_accession(
            mock_session, "Olink", "SDY1669"
        )

    assert result == ("EXP12345", "LLM")


@pytest.mark.asyncio
async def test_resolve_no_experiments_in_study(mock_session):
    """When study has no experiments at all, return None."""
    empty_result = _make_result([])
    mock_session.execute = AsyncMock(return_value=empty_result)

    result = await resolve_experiment_accession(mock_session, "Olink", "SDY1669")
    assert result is None


@pytest.mark.asyncio
async def test_llm_resolve_returns_valid_experiment():
    """LLM returns a valid experiment_accession."""
    experiments = [
        {
            "experiment_accession": "EXP12345",
            "name": "Olink inflammation panel",
            "measurement_technique": "Olink",
        },
        {
            "experiment_accession": "EXP12346",
            "name": "CITE-seq profiling",
            "measurement_technique": "CITE-seq",
        },
    ]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "EXP12345"

    with patch("app.agent.query_builder.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        result = await _llm_resolve("Olink inflammation", experiments, _EXPERIMENT_CONFIG)

    assert result == "EXP12345"


@pytest.mark.asyncio
async def test_llm_resolve_returns_none_when_no_match():
    """LLM says NONE when no experiment matches."""
    experiments = [
        {
            "experiment_accession": "EXP12346",
            "name": "CITE-seq profiling",
            "measurement_technique": "CITE-seq",
        }
    ]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "NONE"

    with patch("app.agent.query_builder.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        result = await _llm_resolve("flow cytometry", experiments, _EXPERIMENT_CONFIG)

    assert result is None


@pytest.mark.asyncio
async def test_llm_resolve_extracts_experiment_from_verbose_response():
    """LLM returns something like 'The best match is EXP12345' — we extract it."""
    experiments = [
        {
            "experiment_accession": "EXP12345",
            "name": "Olink inflammation panel",
            "measurement_technique": "Olink",
        },
    ]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "The best match is EXP12345."

    with patch("app.agent.query_builder.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        result = await _llm_resolve("Olink", experiments, _EXPERIMENT_CONFIG)

    assert result == "EXP12345"
