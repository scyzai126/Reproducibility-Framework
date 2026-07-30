"""Tests for the `ranking` block on structured claims.

A superlative ("the maximum expression change occurred on day 1") is an
assertion about a whole set of candidates, which a pairwise `contrast` cannot
express.  `ranking` carries it separately.  Its `over`/`winner` are references —
into `comparison` when scope is "contrast", into `group_id`s when scope is
"group" — so an entry with a dangling reference is worse than no entry at all
and is dropped rather than passed downstream.
"""

import logging

import pytest

from app.agent.claim_parser import _validate_ranking


def _claim(ranking, n_contrasts=3, group_ids=(0, 1, 2, 3), claim_text="a claim"):
    return {
        "claim": claim_text,
        "groups": [{"group_id": gid} for gid in group_ids],
        "comparison": [
            {"contrast": [0, i + 1], "finding": f"f{i}"} for i in range(n_contrasts)
        ],
        "ranking": ranking,
    }


def _entry(**overrides):
    entry = {
        "type": "argmax",
        "scope": "contrast",
        "metric": "magnitude of change vs baseline",
        "over": [0, 1, 2],
        "winner": 0,
        "finding": "the maximum change occurred on day 1",
    }
    entry.update(overrides)
    return entry


# ── entries that must survive ────────────────────────────────────────────────

def test_well_formed_contrast_entry_is_kept():
    val = _claim([_entry()])
    _validate_ranking("claim_1", val)
    assert val["ranking"] == [_entry()]


def test_group_scope_validates_against_group_ids_not_comparison_length():
    """group_id 3 is out of range for a 3-entry `comparison` but is a real group."""
    val = _claim(
        [_entry(scope="group", over=[1, 2, 3], winner=3)],
        n_contrasts=3,
        group_ids=(0, 1, 2, 3),
    )
    _validate_ranking("claim_1", val)
    assert len(val["ranking"]) == 1
    assert val["ranking"][0]["winner"] == 3


def test_argmin_is_accepted():
    val = _claim([_entry(type="argmin", winner=2)])
    _validate_ranking("claim_1", val)
    assert len(val["ranking"]) == 1


def test_absent_ranking_on_a_plain_claim_is_left_alone():
    val = {"claim": "titers rose by day 14", "groups": [], "comparison": []}
    _validate_ranking("claim_1", val)
    assert "ranking" not in val


# ── entries that must be dropped ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "entry, reason",
    [
        (_entry(over=[0, 1, 5]), "contrast index 5 does not exist"),
        (_entry(scope="group", over=[0, 1, 99], winner=0), "group_id 99 does not exist"),
        (_entry(winner=7), "winner is not among `over`"),
        (_entry(over=[0]), "a ranking over one candidate ranks nothing"),
        (_entry(over="0,1,2"), "`over` is not a list"),
        (_entry(scope="timepoint"), "unknown scope"),
        (_entry(type="biggest"), "unknown type"),
        ("not an object", "entry is not an object"),
    ],
)
def test_malformed_entries_are_dropped(entry, reason):
    val = _claim([entry])
    _validate_ranking("claim_1", val)
    assert "ranking" not in val, f"should have dropped: {reason}"


def test_valid_entries_survive_alongside_dropped_ones():
    val = _claim([_entry(), _entry(over=[0, 1, 5])])
    _validate_ranking("claim_1", val)
    assert val["ranking"] == [_entry()]


def test_non_list_ranking_is_dropped():
    val = _claim({"type": "argmax"})
    _validate_ranking("claim_1", val)
    assert "ranking" not in val


# ── observability ────────────────────────────────────────────────────────────

def test_superlative_claim_without_ranking_warns(caplog):
    val = {
        "claim": "Microarray analysis ... showed that the maximum gene expression "
                 "change occurred on day 1 compared to baseline (day 0).",
        "groups": [{"group_id": i} for i in range(4)],
        "comparison": [{"contrast": [0, 1], "finding": "f"}],
    }
    with caplog.at_level(logging.WARNING, logger="app.agent.claim_parser"):
        _validate_ranking("claim_1", val)
    assert "superlative" in caplog.text
    assert "ranking" not in val


def test_plain_claim_without_ranking_does_not_warn(caplog):
    val = {
        "claim": "HAI titers generally plateaued after day 14.",
        "groups": [{"group_id": i} for i in range(3)],
        "comparison": [{"contrast": [1, 2], "finding": "f"}],
    }
    with caplog.at_level(logging.WARNING, logger="app.agent.claim_parser"):
        _validate_ranking("claim_1", val)
    assert caplog.text == ""
