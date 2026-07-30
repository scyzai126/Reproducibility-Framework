"""Tests for day-range parsing of `time_point` strings.

`classify_groups.txt` emits time points in the bare absolute form ("day 0",
"day 1", "day 14").  That form has to reach the numeric day columns
(`planned_visit.min_start_day`, `biosample.study_time_collected`) — if it does
not, a bare day falls through to name-LIKE/LLM matching only, and when those
miss, `_resolve_group` builds the query with no time filter at all.  Every
timepoint group then returns the same subjects and the whole claim is dropped
as "groups collapsed".
"""

import pytest

from app.agent.query_builder import _parse_day_range


@pytest.mark.parametrize(
    "time_point, expected",
    [
        ("day 0", (0.0, 0.0)),
        ("day 1", (1.0, 1.0)),
        ("day 14", (14.0, 14.0)),
        ("Day 7", (7.0, 7.0)),
        ("days 3", (3.0, 3.0)),
        ("  day 21  ", (21.0, 21.0)),
        # SDY80 samples a pre-vaccination visit at day -7.
        ("day -7", (-7.0, -7.0)),
    ],
)
def test_bare_single_day(time_point, expected):
    assert _parse_day_range(time_point) == expected


@pytest.mark.parametrize(
    "time_point, expected",
    [
        ("4-7 days post fever onset", (4.0, 7.0)),
        ("day 4-7", (4.0, 7.0)),
        ("8+ days", (8.0, 9999.0)),
        (">= 8 days", (8.0, 9999.0)),
        ("< 14 days", (0.0, 14.0)),
        ("within 10 days", (0.0, 10.0)),
        ("3 or more days", (3.0, 9999.0)),
    ],
)
def test_existing_range_forms_unchanged(time_point, expected):
    """The single-day pattern is checked last and must not shadow any range."""
    assert _parse_day_range(time_point) == expected


@pytest.mark.parametrize(
    "time_point",
    [
        "",
        "baseline",
        "pre-vaccination",
        "post-vaccination",
        # A day embedded in prose is not an anchored single day — leave it to
        # LIKE/LLM rather than guessing a numeric window from it.
        "day 7 after the second dose",
    ],
)
def test_non_day_strings_return_none(time_point):
    assert _parse_day_range(time_point) is None
