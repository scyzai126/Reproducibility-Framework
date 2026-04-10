from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.query_builder import _llm_resolve, resolve_arm_accession, _ARM_CONFIG


@pytest.fixture
def mock_session():
    """Create a mock AsyncSession that returns configurable query results."""
    session = AsyncMock()
    return session


def _make_result(rows, columns=("arm_accession", "name", "description")):
    """Create a mock SQLAlchemy result object."""
    mock_result = MagicMock()
    mock_result.keys.return_value = list(columns)
    mock_result.fetchall.return_value = [tuple(r.values()) for r in rows]
    return mock_result


@pytest.mark.asyncio
async def test_resolve_returns_none_for_empty_cohort(mock_session):
    result = await resolve_arm_accession(mock_session, "", "SDY1669")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_returns_none_for_empty_study(mock_session):
    result = await resolve_arm_accession(mock_session, "Atlanta", "")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_single_sql_match(mock_session):
    """When SQL finds exactly 1 match, return it directly without LLM."""
    rows = [{"arm_accession": "ARM5346", "name": "Emory cohort", "description": "Atlanta, GA"}]
    mock_session.execute = AsyncMock(return_value=_make_result(rows))

    result = await resolve_arm_accession(mock_session, "Atlanta", "SDY1669")
    assert result == ("ARM5346", "SQL")


@pytest.mark.asyncio
async def test_resolve_no_sql_match_falls_back_to_llm(mock_session):
    """When SQL finds 0 matches, fall back to LLM with all arms."""
    # First call: keyword search returns 0 rows
    empty_result = _make_result([])
    # Second call: fetch all arms returns candidates
    all_arms = [
        {"arm_accession": "ARM5346", "name": "Emory cohort", "description": "Samples from Atlanta"},
        {"arm_accession": "ARM5347", "name": "Stanford cohort", "description": "Samples from Palo Alto"},
    ]
    all_arms_result = _make_result(all_arms)
    mock_session.execute = AsyncMock(side_effect=[empty_result, all_arms_result])

    with patch("app.agent.query_builder._llm_resolve", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "ARM5346"
        result = await resolve_arm_accession(mock_session, "Emory", "SDY1669")

    assert result == ("ARM5346", "LLM")
    mock_llm.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_multiple_sql_matches_falls_back_to_llm(mock_session):
    """When SQL finds 2+ matches, fall back to LLM."""
    two_rows = [
        {"arm_accession": "ARM5346", "name": "Atlanta cohort A", "description": "Atlanta"},
        {"arm_accession": "ARM5347", "name": "Atlanta cohort B", "description": "Atlanta"},
    ]
    two_result = _make_result(two_rows)
    all_arms_result = _make_result(two_rows)
    mock_session.execute = AsyncMock(side_effect=[two_result, all_arms_result])

    with patch("app.agent.query_builder._llm_resolve", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "ARM5346"
        result = await resolve_arm_accession(mock_session, "Atlanta", "SDY1669")

    assert result == ("ARM5346", "LLM")


@pytest.mark.asyncio
async def test_resolve_no_arms_in_study(mock_session):
    """When study has no arms at all, return None."""
    empty_result = _make_result([])
    mock_session.execute = AsyncMock(return_value=empty_result)

    result = await resolve_arm_accession(mock_session, "Atlanta", "SDY1669")
    assert result is None


@pytest.mark.asyncio
async def test_llm_resolve_returns_valid_arm():
    """LLM returns a valid arm_accession."""
    arms = [
        {"arm_accession": "ARM5346", "name": "Emory cohort", "description": "Atlanta"},
        {"arm_accession": "ARM5347", "name": "Stanford cohort", "description": "Palo Alto"},
    ]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ARM5346"

    with patch("app.agent.query_builder.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await _llm_resolve("Atlanta", arms, _ARM_CONFIG)

    assert result == "ARM5346"


@pytest.mark.asyncio
async def test_llm_resolve_returns_none_when_no_match():
    """LLM says NONE when no arm matches."""
    arms = [{"arm_accession": "ARM5347", "name": "Stanford", "description": "Palo Alto"}]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "NONE"

    with patch("app.agent.query_builder.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await _llm_resolve("Atlanta", arms, _ARM_CONFIG)

    assert result is None


@pytest.mark.asyncio
async def test_llm_resolve_extracts_arm_from_verbose_response():
    """LLM returns something like 'The best match is ARM5346' — we extract it."""
    arms = [
        {"arm_accession": "ARM5346", "name": "Emory cohort", "description": "Atlanta"},
    ]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "The best match is ARM5346."

    with patch("app.agent.query_builder.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await _llm_resolve("Atlanta", arms, _ARM_CONFIG)

    assert result == "ARM5346"
