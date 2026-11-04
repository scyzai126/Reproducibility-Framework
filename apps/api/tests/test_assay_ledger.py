"""The corpus-wide usage ledger: one row per paid run, a month is a sum over rows."""

import json
from datetime import datetime

import pytest

from app.agent import assay_ledger, assay_trace


def _grouped(prompt=10_000, cached=6_000, completion=500):
    return {"extract": {"run1": {"reply": "{}", "usage": {
                "prompt": prompt, "cached": cached, "completion": completion, "reasoning": 0}}},
            "obi": {"ELISA": {"reply": "1 exact"}}}


def test_a_row_carries_totals_and_the_price_at_run_time(tmp_path):
    when = datetime(2026, 11, 4, 13, 10, 29)
    row = assay_ledger.build_row("111", "SDY1", tmp_path / "111_SDY1", _grouped(), "gpt-5.4",
                                 when=when)

    assert row["date"] == "2026-11-04T13:10:29"
    assert (row["pubmed_id"], row["study_accession"]) == ("111", "SDY1")
    assert row["rounds"] == "extract+obi"
    assert row["calls"] == 2
    assert (row["prompt_tokens"], row["cached_tokens"], row["completion_tokens"]) == (10_000, 6_000, 500)
    expected = assay_trace.estimate_usd({"prompt": 10_000, "cached": 6_000, "completion": 500},
                                        "gpt-5.4")
    assert float(row["usd"]) == pytest.approx(expected, abs=1e-4)
    assert row["price_date"] == assay_trace.LIST_PRICE_DATE


def test_a_run_without_usage_writes_no_row(tmp_path):
    """A fake client records no tokens; a row of zeros would read as a free paper."""
    grouped = {"extract": {"reply": "{}"}, "verify": {"ELISA": {"reply": "{}"}}}
    ledger = tmp_path / "ledger.csv"

    assert assay_ledger.record_run("111", "SDY1", tmp_path, grouped, "gpt-5.4", path=ledger) is None
    assert not ledger.exists()


def test_an_unpriced_model_keeps_its_tokens_and_blanks_the_price(tmp_path):
    row = assay_ledger.build_row("111", "SDY1", tmp_path, _grouped(), "not-priced")
    assert row["usd"] == "" and row["price_date"] == ""
    assert row["prompt_tokens"] == 10_000


def test_rows_append_under_one_header_and_read_back_as_numbers(tmp_path):
    ledger = tmp_path / "ledger.csv"
    assay_ledger.record_run("111", "SDY1", tmp_path / "a", _grouped(), "gpt-5.4", path=ledger)
    assay_ledger.record_run("222", "SDY2", tmp_path / "b", _grouped(prompt=20_000), "gpt-5.4",
                            path=ledger)

    text = ledger.read_text(encoding="utf-8")
    assert text.count("date,pubmed_id") == 1
    rows = assay_ledger.read_rows(ledger)
    assert [r["pubmed_id"] for r in rows] == ["111", "222"]
    assert rows[1]["prompt_tokens"] == 20_000 and isinstance(rows[1]["usd"], float)


def test_the_real_ledger_path_is_isolated_in_tests(tmp_path):
    """conftest points LEDGER_PATH into tmp; a record_run with no path lands there."""
    assay_ledger.record_run("111", "SDY1", tmp_path, _grouped(), "gpt-5.4")
    assert assay_ledger.LEDGER_PATH.exists()
    assert str(assay_ledger.LEDGER_PATH).startswith(str(tmp_path.parent))


def test_monthly_summary_groups_runs_and_distinct_papers():
    rows = [
        {"date": "2026-11-04T10:00:00", "pubmed_id": "1", "study_accession": "S1", "calls": 20,
         "prompt_tokens": 100, "cached_tokens": 50, "completion_tokens": 10,
         "reasoning_tokens": 0, "usd": 0.30},
        {"date": "2026-11-20T10:00:00", "pubmed_id": "1", "study_accession": "S1", "calls": 20,
         "prompt_tokens": 100, "cached_tokens": 50, "completion_tokens": 10,
         "reasoning_tokens": 0, "usd": 0.30},
        {"date": "2026-12-01T10:00:00", "pubmed_id": "2", "study_accession": "S2", "calls": 5,
         "prompt_tokens": 10, "cached_tokens": 0, "completion_tokens": 1,
         "reasoning_tokens": 0, "usd": None},
    ]
    months = assay_ledger.monthly_summary(rows)

    assert [m["month"] for m in months] == ["2026-11", "2026-12"]
    nov, dec = months
    assert (nov["runs"], nov["papers"], nov["calls"]) == (2, 1, 40)
    assert nov["prompt_tokens"] == 200 and nov["usd"] == pytest.approx(0.60)
    assert nov["unpriced"] == 0
    assert (dec["runs"], dec["unpriced"], dec["usd"]) == (1, 1, 0.0)


def test_backfill_adds_each_registry_once_dated_by_its_raw_file(tmp_path):
    root = tmp_path / "assay_result_v4"
    for name, grouped in (("111_SDY1", _grouped()), ("222_SDY2_pdf", _grouped(prompt=5000)),
                          ("333_SDY3", {"extract": {"reply": "{}"}})):
        (root / name).mkdir(parents=True)
        (root / name / assay_trace.RAW_FILE).write_text(json.dumps(grouped), encoding="utf-8")
    ledger = tmp_path / "ledger.csv"

    added = assay_ledger.backfill(root, path=ledger)

    assert [(r["pubmed_id"], r["study_accession"]) for r in added] == [("111", "SDY1"), ("222", "SDY2")]
    assert added[0]["date"][:4] == str(datetime.now().year)
    # A second backfill finds nothing new; the one without usage is never a row.
    assert assay_ledger.backfill(root, path=ledger) == []
    assert len(assay_ledger.read_rows(ledger)) == 2


@pytest.mark.asyncio
async def test_a_pipeline_run_with_usage_lands_in_the_ledger(tmp_path, monkeypatch):
    """The service appends after the run; the suite's fake clients carry no usage, so the
    hook is exercised through record_run with a usage-bearing trace instead."""
    ledger = tmp_path / "ledger.csv"
    monkeypatch.setattr(assay_ledger, "LEDGER_PATH", ledger)

    row = assay_ledger.record_run("111", "SDY1", tmp_path / "111_SDY1", _grouped(), "gpt-5.4")

    assert row is not None
    assert assay_ledger.read_rows()[0]["registry_dir"].endswith("111_SDY1")
