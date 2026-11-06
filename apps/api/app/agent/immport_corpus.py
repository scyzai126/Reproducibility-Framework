"""The ImmPort paper corpus: every PubMed ID the `study_pubmed` table links to a study.

The table is many-to-many in both directions -- SDY212 has six papers, PubMed ID 26682988
belongs to five studies -- and its `pubmed_id` column is not reliably a PubMed ID (28 of 1,562
rows hold "TBD", "Not Applicable", a PMC id or a "PMID:" label). So the corpus is built in two
moves: `paper_resolver.normalize_row_pmid` says whether a row names a paper at all, and
`group_papers` folds the usable rows into **one record per PubMed ID** carrying every study it
belongs to. A paper is parsed once, however many studies cite it; the studies travel with it.

`primary_sdy` is the lowest-numbered study, decided from the table alone, so the name a paper's
files take (`<SDY>_<pmid>.xml`, `<pmid>_<SDY>/`) is the same on every machine and every run.

Pure functions over rows, dicts and paths. The database query takes a caller-supplied session
rather than importing `app.database`, which builds an engine at import -- the same reason
paper_resolver does it that way.
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.paper_resolver import normalize_row_pmid

#: Where the corpus lists live: an external drive, so the script refuses to run when it is not
#: mounted rather than writing a list somewhere nobody will look for it.
PAPERS_DIR = Path("/Volumes/Extreme SSD/HIPC papers")

PAPERS_ALL_NAME = "papers_all.csv"
PAPERS_UNUSABLE_NAME = "papers_unusable.csv"

PAPER_COLUMNS = ("pmid", "study_accessions", "primary_sdy", "n_studies")
UNUSABLE_COLUMNS = ("study_accession", "raw_value", "reason")

#: Studies are listed inside one CSV cell; `;` because a study accession never contains one and
#: a spreadsheet leaves it alone, where `,` would split the cell.
STUDY_SEP = ";"

_STUDY_PUBMED = text("SELECT study_accession, pubmed_id FROM study_pubmed")
_SDY_NUM_RE = re.compile(r"(\d+)")


async def study_pubmed_rows(session: AsyncSession) -> list[tuple[str, str]]:
    """Every `(study_accession, pubmed_id)` row, as stored. No LIMIT, no cleaning."""
    result = await session.execute(_STUDY_PUBMED)
    return [(str(sdy or "").strip(), raw) for sdy, raw in result.all()]


def group_papers(rows: list[tuple[str, str]]) -> tuple[dict[str, list[str]], list[dict]]:
    """`({pmid: sorted studies}, unusable rows)`.

    Usable rows fold into one entry per PubMed ID; the same (study, pmid) pair listed twice
    counts once. Unusable rows are kept with the reason normalize_row_pmid gives, so the list
    on disk can say what the table held rather than silently being 28 rows short.
    """
    grouped: dict[str, set[str]] = {}
    unusable: list[dict] = []
    for sdy, raw in rows:
        pmid, reason = normalize_row_pmid(raw)
        if reason:
            unusable.append({"study_accession": sdy, "raw_value": pmid, "reason": reason})
            continue
        grouped.setdefault(pmid, set()).add(sdy)
    return {pmid: sorted(studies, key=sdy_key) for pmid, studies in grouped.items()}, unusable


def sdy_key(study_accession: str) -> tuple[int, str]:
    """Numeric order: SDY80 before SDY1119. The string breaks ties for anything unnumbered."""
    match = _SDY_NUM_RE.search(study_accession or "")
    return (int(match.group(1)) if match else -1, study_accession or "")


def primary_sdy(studies: list[str]) -> str:
    """The study a paper's files are named after: the lowest-numbered one."""
    if not studies:
        raise ValueError("a paper must belong to at least one study")
    return min(studies, key=sdy_key)


def paper_rows(grouped: dict[str, list[str]]) -> list[dict]:
    """One CSV row per PubMed ID, in PMID order, with every study it belongs to."""
    rows = []
    for pmid in sorted(grouped, key=int):
        studies = sorted(grouped[pmid], key=sdy_key)
        rows.append({
            "pmid": pmid,
            "study_accessions": STUDY_SEP.join(studies),
            "primary_sdy": primary_sdy(studies),
            "n_studies": len(studies),
        })
    return rows


def write_csv(path: Path, rows: list[dict], columns: tuple[str, ...]) -> None:
    """Write the rows to `path` through a sibling temp file, so a failure mid-write leaves the
    previous list intact rather than a truncated one."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(columns))
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in columns})
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def summary(rows: list[tuple[str, str]], grouped: dict[str, list[str]],
            unusable: list[dict]) -> dict:
    """The counts the script prints."""
    return {
        "rows": len(rows),
        "usable_pmids": len(grouped),
        "shared_pmids": sum(1 for studies in grouped.values() if len(studies) > 1),
        "max_studies_per_pmid": max((len(s) for s in grouped.values()), default=0),
        "studies": len({sdy for studies in grouped.values() for sdy in studies}),
        "unusable_rows": len(unusable),
    }
