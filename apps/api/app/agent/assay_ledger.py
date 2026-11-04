"""One line per paid assay run, every paper, one file: the corpus-wide usage ledger.

`assays_raw.json` keeps every call of one run beside that paper's registry, with its tokens.
That is the right place to diagnose a paper and the wrong place to answer "what did this month
cost": an ImmPort-wide extraction is thousands of registry folders, and nobody sums thousands
of files to read one number. So every run that recorded usage also appends one row here --
tokens and a dollar figure, nothing per call -- and a month is a sum over rows.

The dollar column is the list price *at the time of the run* (assay_trace.LIST_PRICE_USD_PER_MTOK,
with its date in `price_date`), because that is what the run cost. The token columns are kept so
a row can be re-priced later if the table changes. CSV rather than JSON so the file opens in a
spreadsheet as it is.

A run whose calls carried no usage (a fake client, an SDK path that returns none) writes no row:
a row of zeros would read as a free paper.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from app.agent import assay_trace

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]

#: Patchable: tests point it at a temp file (tests/conftest.py).
LEDGER_PATH = _REPO_ROOT / "data" / "assay_usage_ledger.csv"

COLUMNS = (
    "date", "pubmed_id", "study_accession", "registry_dir", "rounds", "model",
    "calls", "prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens",
    "usd", "price_date",
)

_TOKEN_COLUMNS = ("prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens")


def _display(path: Path | str) -> str:
    try:
        return str(Path(path).relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def build_row(pubmed_id: str, study_accession: str, registry_dir: Path | str, grouped: dict,
              model: str, when: datetime | None = None) -> dict | None:
    """The ledger row for one run's grouped trace, or None when no call carried usage."""
    summary = assay_trace.usage_summary(grouped)
    total = summary["total"]
    if not any(total[f] for f in assay_trace.USAGE_FIELDS):
        return None
    usd = assay_trace.estimate_usd(total, model)
    return {
        "date": (when or datetime.now()).replace(microsecond=0).isoformat(),
        "pubmed_id": pubmed_id,
        "study_accession": study_accession,
        "registry_dir": _display(registry_dir),
        "rounds": "+".join(summary["by_round"]),
        "model": model,
        "calls": total["calls"],
        "prompt_tokens": total["prompt"],
        "cached_tokens": total["cached"],
        "completion_tokens": total["completion"],
        "reasoning_tokens": total["reasoning"],
        "usd": f"{usd:.4f}" if usd is not None else "",
        "price_date": assay_trace.LIST_PRICE_DATE if usd is not None else "",
    }


def append_row(row: dict, path: Path | None = None) -> None:
    """Append one row, writing the header first when the file does not exist yet."""
    path = Path(path or LEDGER_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow({c: row.get(c, "") for c in COLUMNS})


def record_run(pubmed_id: str, study_accession: str, registry_dir: Path | str, grouped: dict,
               model: str, path: Path | None = None) -> dict | None:
    """Append the run to the ledger and return its row; None (and no write) without usage.

    Never raises: the registry is already on disk when this is called, and a ledger that
    cannot be written must not turn a finished run into a failure.
    """
    try:
        row = build_row(pubmed_id, study_accession, registry_dir, grouped, model)
        if row is not None:
            append_row(row, path)
        return row
    except Exception as exc:  # noqa: BLE001 - bookkeeping must not fail the run
        logger.warning("usage ledger not written: %s: %s", type(exc).__name__, exc)
        return None


def read_rows(path: Path | None = None) -> list[dict]:
    """Every row, with the numeric columns as numbers. An absent file is an empty ledger."""
    path = Path(path or LEDGER_PATH)
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            row = dict(raw)
            row["calls"] = int(row.get("calls") or 0)
            for c in _TOKEN_COLUMNS:
                row[c] = int(row.get(c) or 0)
            row["usd"] = float(row["usd"]) if row.get("usd") else None
            rows.append(row)
    return rows


def monthly_summary(rows: list[dict]) -> list[dict]:
    """One line per calendar month: runs, calls, tokens and dollars, oldest first.

    `usd` sums the rows that have a price; `unpriced` counts the ones that do not, so a month
    whose model was missing from the price table is not read as cheap.
    """
    months: dict[str, dict] = {}
    for row in rows:
        month = (row.get("date") or "")[:7]
        m = months.setdefault(month, {"month": month, "runs": 0, "papers": set(), "calls": 0,
                                      **{c: 0 for c in _TOKEN_COLUMNS}, "usd": 0.0,
                                      "unpriced": 0})
        m["runs"] += 1
        m["papers"].add((row.get("pubmed_id"), row.get("study_accession")))
        m["calls"] += row["calls"]
        for c in _TOKEN_COLUMNS:
            m[c] += row[c]
        if row.get("usd") is None:
            m["unpriced"] += 1
        else:
            m["usd"] += row["usd"]
    out = []
    for month in sorted(months):
        m = months[month]
        m["papers"] = len(m["papers"])
        out.append(m)
    return out


def backfill(registry_root: Path, path: Path | None = None) -> list[dict]:
    """Add a row for every registry under `registry_root` whose assays_raw.json carries usage
    and is not yet in the ledger (same registry_dir). Dated by the raw file's mtime -- the run
    wrote that file last, so it is the run's end time. Returns the rows added.
    """
    import json

    have = {r["registry_dir"] for r in read_rows(path)}
    added: list[dict] = []
    for raw_path in sorted(Path(registry_root).glob(f"*/{assay_trace.RAW_FILE}")):
        registry_dir = raw_path.parent
        if _display(registry_dir) in have:
            continue
        try:
            grouped = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = registry_dir.name.removesuffix("_pdf")
        pmid, _, sdy = name.partition("_")
        from app.config import settings
        row = build_row(pmid, sdy, registry_dir, grouped, settings.OPENAI_MODEL,
                        when=datetime.fromtimestamp(raw_path.stat().st_mtime))
        if row is None:
            continue
        append_row(row, path)
        added.append(row)
    return added
