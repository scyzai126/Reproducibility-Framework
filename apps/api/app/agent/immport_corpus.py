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

from app.agent import assay_service
from app.agent.jats_fetcher import validate_identifiers
from app.agent.paper_resolver import normalize_row_pmid

#: Where the corpus lists live: an external drive, so the script refuses to run when it is not
#: mounted rather than writing a list somewhere nobody will look for it.
PAPERS_DIR = Path("/Volumes/Extreme SSD/HIPC papers")

PAPERS_ALL_NAME = "papers_all.csv"
PAPERS_UNUSABLE_NAME = "papers_unusable.csv"
#: Step 2 splits papers_all into these two: every PMID lands in exactly one of them.
PAPERS_XML_NAME = "papers_xml.csv"
PAPERS_NO_XML_NAME = "papers_no_xml.csv"
#: One folder for every full text, named the way the assay pipeline reads them.
XML_DIR_NAME = "xml"

#: Where the assay registries go: one `<pmid>_<SDY>/` per paper, beside a logs/ folder and the
#: per-paper run record.
RESULT_DIR = Path("/Volumes/Extreme SSD/HIPC result")
RESULT_LOG_DIR_NAME = "logs"
RUNS_NAME = "assay_runs.csv"
RUN_COLUMNS = ("pmid", "primary_sdy", "study_accessions", "status", "registry_dir", "calls",
               "usd", "seconds", "flags", "error", "finished_at")

#: What one paper costs when the ledger has nothing to say yet (measured $0.36-0.40 on two
#: papers, 2026-11-04) and how long it takes run alone.
DEFAULT_USD_PER_PAPER = 0.40
DEFAULT_SECONDS_PER_PAPER = 180

#: The line prefixes report_result prints that CLAUDE.md says must be reported, not summarised.
#: Longest first, so `OBI FAILED` is not read as nothing and `DROPPED ALIAS` counts as DROPPED.
REPORT_PREFIXES = ("CORRECT REFUSED", "CORRECT FAILED", "OBI FAILED", "WARNING", "REVIEW",
                   "JUDGED", "REJECT", "DROPPED", "MINORITY", "VOTE", "MERGED", "UNMAPPED",
                   "ERROR")

PAPER_COLUMNS = ("pmid", "study_accessions", "primary_sdy", "n_studies")
UNUSABLE_COLUMNS = ("study_accession", "raw_value", "reason")
XML_COLUMNS = ("pmid", "study_accessions", "primary_sdy", "pmcid", "file", "bytes")
NO_XML_COLUMNS = ("pmid", "study_accessions", "primary_sdy", "pmcid", "reason")

#: NCBI's ID converter takes up to 200 ids in one request; ncbi_utils.pmid_to_pmc_url asks one
#: at a time with a process-local cache, which is the right shape for a UI and the wrong one
#: for 1,300 papers.
IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
IDCONV_BATCH = 200

#: Outcome a paper gets when the ID converter has no PMC record for it.
NO_PMC_REASON = "no open-access PubMed Central record"
#: Outcomes that are a fact about the paper, not about the network: a resumed run does not ask
#: again unless told to. A transport failure ("request failed: ...") is never in this set.
PERMANENT_REASON_PREFIXES = (
    NO_PMC_REASON,
    "PubMed Central does not carry it as open access",
    "the publisher does not allow",
    "PubMed Central has only the abstract",
    "PubMed Central returned no article",
)

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


def read_csv(path: Path) -> list[dict]:
    """Every row of a list this module wrote; an absent file is an empty list."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_papers(path: Path) -> list[dict]:
    """`papers_all.csv` rows, each with `studies` split back into a list."""
    rows = read_csv(path)
    for row in rows:
        row["studies"] = [s for s in row.get("study_accessions", "").split(STUDY_SEP) if s]
    return rows


def xml_name(primary_sdy: str, pmid: str) -> str:
    """`<SDY>_<pmid>.xml`, the one name assay_service.locate_paper_xml tries first.

    validate_identifiers first: a stem whose halves cannot be told apart by the SDY prefix reads
    back inverted, and the paper is unfindable under the ids it was fetched with.
    """
    pmid, sdy = validate_identifiers(pmid, primary_sdy)
    return f"{sdy}_{pmid}.xml"


def existing_xml(xml_dir: Path) -> dict[str, Path]:
    """`{pmid: path}` for every paper already in the folder.

    The ExFAT drive grows a `._<name>` AppleDouble twin beside every file macOS writes; those
    are not papers and are skipped by name.
    """
    found: dict[str, Path] = {}
    if not xml_dir.is_dir():
        return found
    for path in sorted(xml_dir.glob("*.xml")):
        if path.name.startswith("._"):
            continue
        split = assay_service.split_stem(path.stem)
        if split is not None:
            found[split[0]] = path
    return found


def parse_idconv(payload: dict) -> dict[str, str | None]:
    """`{pmid: pmcid or None}` from one ID-converter reply.

    The converter echoes the pmid as an int on some records and as a string on others, and
    reports an unknown id as a record with `status: "error"` rather than leaving it out.
    """
    out: dict[str, str | None] = {}
    for record in payload.get("records", []) or []:
        pmid = record.get("pmid")
        if pmid is None:
            continue
        pmid = str(pmid).strip()
        pmcid = record.get("pmcid")
        bad = record.get("status") == "error" or "errmsg" in record
        out[pmid] = str(pmcid) if pmcid and not bad else None
    return out


def benchmark_xml(pmid: str, studies: list[str], xml_root: Path | None = None) -> Path | None:
    """The paper's XML already in the curated corpus, under any of its studies.

    The benchmark filed a paper under whichever study the curators were working on, which need
    not be its primary one; so every study is tried. A copy of this file, not a refetch, keeps
    the sentence numbering that the paper's existing registry cites.
    """
    root = xml_root if xml_root is not None else assay_service.XML_ROOT
    for sdy in studies:
        for stem in (f"{sdy}_{pmid}", f"{pmid}_{sdy}"):
            path = root / f"{stem}.xml"
            if path.exists():
                return path
    return None


def read_xml_papers(papers_dir: Path) -> list[dict]:
    """`papers_xml.csv` rows -- the papers the assay run can read -- with `studies` split."""
    rows = read_csv(papers_dir / PAPERS_XML_NAME)
    for row in rows:
        row["studies"] = [s for s in row.get("study_accessions", "").split(STUDY_SEP) if s]
    return rows


def done_marker(result_dir: Path, pmid: str, sdy: str) -> Path:
    """The file whose presence means the paper finished: the pipeline writes it last."""
    return result_dir / f"{pmid}_{sdy}" / "assays_benchmark.json"


def benchmark_registry(pmid: str, studies: list[str], version_root: Path) -> Path | None:
    """A finished, XML-based registry for this paper in a benchmark version folder, under any
    of its studies. `_pdf` folders are passed over: a registry built from a PDF carries no
    sentence ids, and the corpus is XML."""
    for sdy in studies:
        folder = version_root / f"{pmid}_{sdy}"
        if (folder / "assays_benchmark.json").exists():
            return folder
    return None


def count_report_lines(text: str) -> dict[str, int]:
    """How many lines of a captured report_result carry each REPORT_PREFIXES prefix."""
    counts: dict[str, int] = {}
    for line in text.splitlines():
        stripped = line.lstrip()
        for prefix in REPORT_PREFIXES:
            if stripped.startswith(prefix):
                counts[prefix] = counts.get(prefix, 0) + 1
                break
    return counts


def format_flags(counts: dict[str, int]) -> str:
    """`REVIEW=2;VOTE=1` -- one CSV cell, in REPORT_PREFIXES order; empty when clean."""
    return STUDY_SEP.join(f"{p}={counts[p]}" for p in REPORT_PREFIXES if counts.get(p))


def _under(row_dir: str, root: Path) -> bool:
    try:
        return Path(row_dir).resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def cost_per_paper(ledger_rows: list[dict], under: Path | None = None) -> dict:
    """`{median, max, n}` dollars per paper from the ledger.

    Rows under `under` (the corpus result folder) first, because benchmark papers are a biased
    sample; every priced row when there are none there; the dated default with n=0 when the
    ledger is empty, so a projection never silently rests on nothing.
    """
    priced = [r for r in ledger_rows if r.get("usd") is not None]
    chosen = [r for r in priced if under is not None and _under(r.get("registry_dir", ""), under)]
    if not chosen:
        chosen = priced
    if not chosen:
        return {"median": DEFAULT_USD_PER_PAPER, "max": DEFAULT_USD_PER_PAPER, "n": 0}
    values = sorted(r["usd"] for r in chosen)
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    return {"median": median, "max": values[-1], "n": len(values)}


def seconds_per_paper(run_rows: list[dict]) -> float:
    """Median wall-clock of finished papers, or the default when none has run."""
    values = sorted(float(r["seconds"]) for r in run_rows
                    if r.get("status") == "done" and r.get("seconds"))
    if not values:
        return float(DEFAULT_SECONDS_PER_PAPER)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def summarize_runs(run_rows: list[dict]) -> dict:
    """Counts by status plus the flag totals, for `status` and the tranche summary."""
    by_status: dict[str, int] = {}
    flags: dict[str, int] = {}
    for row in run_rows:
        by_status[row.get("status", "")] = by_status.get(row.get("status", ""), 0) + 1
        for item in (row.get("flags") or "").split(STUDY_SEP):
            if "=" in item:
                name, _, n = item.partition("=")
                flags[name] = flags.get(name, 0) + int(n or 0)
    return {"by_status": by_status, "flags": flags}


def is_permanent(reason: str) -> bool:
    """True for a reason that will not change by asking NCBI again."""
    return any(reason.startswith(prefix) for prefix in PERMANENT_REASON_PREFIXES)


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
