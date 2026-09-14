"""One typed identifier in, every paper it could mean out.

A user types `SDY2189`, `34252919` or `PMC8761119`; the assay pipeline needs both halves of the
pair, because the XML is filed as `<SDY>_<pmid>.xml` and the registry as `<pmid>_<SDY>`. This
module supplies the missing half from the `study_pubmed` table -- and, crucially, **never picks
one**.

The mapping is many-to-many in both directions. SDY212 has six papers; PubMed ID 26682988 belongs
to five studies. `orchestrator.py` asks this question with `LIMIT 1` in seven places and so
silently answers one of those five; the whole point of this module is to return the list and let
a human choose. Picking would be wrong for roughly a tenth of identifiers and would say nothing
about it -- and a wrong study accession does not produce a wrong extraction, it produces a
correct, verified registry filed under a study it does not describe.

Free: one indexed database read, plus one cached NCBI id-converter call when the input is a PMC
id. No model calls, nothing fetched, nothing written.

**It is not in assay_service on purpose.** `app.database` builds its engine at import time, and
assay_service is imported by every CLI script and by test modules that touch nothing but
tmp_path; a query there would drag SQLAlchemy into all of them. Every public function in that
module is also synchronous filesystem-in/dict-out, and this one is async and needs a
caller-supplied session. The dependency arrow stays one way: this module imports assay_service,
never the reverse.
"""

import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import assay_jobs, assay_service
from app.agent.jats_fetcher import PMID_RE, SDY_RE
from app.agent.ncbi_utils import pmc_to_pmid

logger = logging.getLogger(__name__)


class UnrecognizedQueryError(ValueError):
    """The string is not one of the identifier shapes this page accepts.

    Distinct from "that identifier matched nothing": the first is a 400 and a typo, the second is
    a 200 carrying a reason. Conflating them would turn "SDY9999 is not in ImmPort" -- a real
    answer -- into an error.
    """


_PMC_RE = re.compile(r"PMC\d+", re.IGNORECASE)
_PMC_URL_RE = re.compile(r"pmc\.ncbi\.nlm\.nih\.gov/articles/(PMC\d+)", re.IGNORECASE)
_PUBMED_URL_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", re.IGNORECASE)
#: "PMID:34252919", "pubmed 34252919" -- a label a user pastes along with the number.
_LABEL_RE = re.compile(r"^(pmid|pubmed|pmc\s*id)\s*[:#]?\s*", re.IGNORECASE)

#: Explicit columns rather than SELECT *, bound parameters, a stable ORDER BY so two resolves of
#: the same id do not shuffle the choices -- and deliberately **no LIMIT**. A test asserts that
#: last part, because the LIMIT 1 in orchestrator.py is exactly the bug this module exists to
#: avoid repeating.
_COLUMNS = "study_accession, pubmed_id, title, journal, year, authors, doi"

_BY_PMID = text(
    f"SELECT {_COLUMNS} FROM study_pubmed WHERE pubmed_id = :pubmed_id "
    "ORDER BY study_accession"
)
_BY_SDY = text(
    f"SELECT {_COLUMNS} FROM study_pubmed WHERE study_accession = :study_accession "
    "ORDER BY pubmed_id"
)


def classify(query: str) -> tuple[str, str]:
    """`('pubmed_id' | 'study_accession' | 'pmc_id', normalized)`, or raise.

    Most specific first: the two NCBI URL forms, then an SDY accession, then a PMC id, then bare
    digits. URLs are accepted because the chat page already advertises a PMC URL on one of its
    example cards, so someone will paste one here.

    **Bare digits are a PubMed ID**, matching what jats_fetcher.validate_identifiers will accept
    later. `8761119` is also a plausible PMC number, and that ambiguity cannot be resolved from
    the string -- so it is decided one way and the zero-candidate message names the `PMC...`
    spelling rather than the code guessing.
    """
    raw = (query or "").strip()
    if not raw:
        raise UnrecognizedQueryError(
            "Type a PubMed ID (34252919), a study accession (SDY2189) or a PMC id (PMC8761119)."
        )

    url_pmc = _PMC_URL_RE.search(raw)
    if url_pmc:
        return "pmc_id", url_pmc.group(1).upper()
    url_pubmed = _PUBMED_URL_RE.search(raw)
    if url_pubmed:
        return "pubmed_id", url_pubmed.group(1)

    stripped = _LABEL_RE.sub("", raw).strip()
    if SDY_RE.fullmatch(stripped):
        return "study_accession", stripped.upper()
    if _PMC_RE.fullmatch(stripped):
        return "pmc_id", stripped.upper()
    if PMID_RE.fullmatch(stripped):
        return "pubmed_id", stripped

    raise UnrecognizedQueryError(
        f"{query!r} is not an identifier this page understands. Expected a PubMed ID "
        "(34252919), a study accession (SDY2189) or a PMC id (PMC8761119)."
    )


def normalize_row_pmid(value: object) -> tuple[str, str | None]:
    """`(pubmed_id, unusable_reason)` for one `study_pubmed.pubmed_id` value.

    The column is not reliably a PubMed ID. Of 1,562 rows, 28 hold things like "TBD",
    "Not Applicable" or a PMC id, and one carries a "PMID: " label. A row like that cannot name
    a file -- `<SDY>_TBD.xml` is not a paper -- so it is reported as unusable rather than handed
    on to be refused later by validate_identifiers with a 400 that says nothing about why.

    A row holding a PMC id gets a reason that names the way forward: this page accepts PMC ids
    typed directly.
    """
    raw = str(value or "").strip()
    stripped = _LABEL_RE.sub("", raw).strip()
    if PMID_RE.fullmatch(stripped):
        return stripped, None
    if _PMC_RE.fullmatch(stripped):
        return raw, (f"ImmPort records {raw} for this study, which is a PMC id rather than a "
                     f"PubMed ID. Type {stripped} into the box to use it.")
    return raw, (f"ImmPort records {raw!r} as this study's paper, which is not a PubMed ID, so "
                 "there is nothing to fetch.")


async def _db_rows(
    session: AsyncSession | None,
    *,
    pubmed_id: str = "",
    study_accession: str = "",
) -> tuple[list[dict], str | None]:
    """Every `study_pubmed` row matching the half we know. `(rows, warning)`.

    Never raises. A database that is down returns no rows and a warning, because this page works
    perfectly well without it for the papers already on disk -- the local set is a strict subset
    of the table and agrees with it. Turning a dead database into a 500 would take the whole
    feature down to lose only the ability to discover papers not yet fetched.
    """
    if session is None:
        return [], None
    statement = _BY_PMID if pubmed_id else _BY_SDY
    params = {"pubmed_id": pubmed_id} if pubmed_id else {"study_accession": study_accession}
    try:
        result = await session.execute(statement, params)
        return [dict(row) for row in result.mappings().all()], None
    except Exception as exc:
        logger.warning("study_pubmed lookup failed (%s); falling back to what is on disk", exc)
        return [], (
            "The ImmPort database could not be reached, so only papers already downloaded are "
            "listed here, without their titles. A paper you have not fetched before will not "
            "appear."
        )


def _local_state() -> dict[tuple[str, str], dict]:
    """Every (pubmed_id, study_accession) pair on disk, and what state it is in.

    `available_papers()` already answers this for the XML corpus -- with titles memoised by mtime
    -- so it is reused rather than re-walked, which is what keeps this resolver and the corpus
    picker from ever disagreeing about which papers exist. Registry directories are then folded
    in, so a paper whose XML was deleted but whose extracted registry survives is still offered.
    """
    state: dict[tuple[str, str], dict] = {}
    for paper in assay_service.available_papers():
        state[(paper["pubmed_id"], paper["study_accession"])] = paper

    root = assay_service.REGISTRY_ROOT
    if root.exists():
        for directory in sorted(root.glob("*_*")):
            if not (directory / "assays.json").exists():
                continue
            split = assay_service.split_stem(directory.name)
            if split is None or split in state:
                continue
            pubmed_id, study_accession = split
            state[split] = {
                "pubmed_id": pubmed_id,
                "study_accession": study_accession,
                "paper_source": "",
                "paper_title": None,
                "has_registry": True,
                "assays": None,
                "updated_at": None,
            }
    return state


def _decorate(
    pubmed_id: str,
    study_accession: str,
    row: dict | None,
    local: dict,
) -> dict:
    """One candidate: what tells it apart, and what says where a run would start.

    `title` (from study_pubmed) and `paper_title` (parsed from the XML) are kept apart on
    purpose. They differ, the database one is what a disambiguation list should show, and it is
    the only one that exists for a paper whose XML has not been fetched yet.
    """
    year = (row or {}).get("year")
    if isinstance(year, str):
        year = int(year) if year.strip().isdigit() else None

    unusable = None
    if row is not None:
        pubmed_id, unusable = normalize_row_pmid(pubmed_id)

    return {
        "pubmed_id": pubmed_id,
        "study_accession": study_accession,
        # A row whose paper cannot be named is still shown -- the study exists, and hiding it
        # would read as "no such study" -- but it is not offered as something to run.
        "usable": unusable is None,
        "unusable_reason": unusable,
        "title": (row or {}).get("title"),
        "journal": (row or {}).get("journal"),
        "year": year,
        "authors": (row or {}).get("authors"),
        "doi": (row or {}).get("doi"),
        "in_db": row is not None,
        "has_xml": bool(local.get("paper_source")),
        "paper_source": local.get("paper_source") or "",
        "paper_title": local.get("paper_title"),
        "has_registry": bool(local.get("has_registry")),
        "assays": local.get("assays"),
        "updated_at": local.get("updated_at"),
        # A free in-memory lookup, and it is what lets a caller adopt a run already under way
        # instead of discovering the 409 by paying for a POST.
        "active_job_id": getattr(
            assay_jobs.active_for(pubmed_id, study_accession), "id", None),
    }


async def resolve(query: str, session: AsyncSession | None = None) -> dict:
    """Every (pubmed_id, study_accession) pair the query could mean. Free.

    Returns a list and never picks -- see the module docstring. Raises UnrecognizedQueryError
    when the string is not an identifier at all; an identifier that matches nothing comes back
    as a 200 with an empty list and a `reason`, because that is an answer rather than a failure.
    """
    shape, normalized = classify(query)

    pmc_id = None
    pubmed_id = study_accession = ""
    if shape == "pmc_id":
        pmc_id = normalized
        converted = await pmc_to_pmid(normalized)
        if not converted:
            return {
                "query": query, "shape": shape, "normalized": normalized, "pmc_id": pmc_id,
                "pubmed_id": "", "study_accession": "", "candidates": [], "total": 0,
                "source": "none", "degraded": False, "warning": None, "resolved_via": "pmc",
                # pmc_to_pmid swallows its own errors and returns None either way, so this
                # cannot claim the paper does not exist.
                "reason": f"NCBI's id converter returned no PubMed ID for {normalized}. It may "
                          "be a PMC-only deposit, or NCBI may be unreachable — the converter "
                          "does not distinguish the two.",
            }
        # str(): the id converter returns the pmid as a JSON number for some records and as a
        # string for others, and every identifier downstream of here is a string.
        pubmed_id = str(converted)
    elif shape == "pubmed_id":
        pubmed_id = normalized
    else:
        study_accession = normalized

    rows, warning = await _db_rows(
        session, pubmed_id=pubmed_id, study_accession=study_accession)

    # A PMC query, again by the PMC id itself. Twenty-eight rows record a PMC id in the
    # pubmed_id column, so a study whose only record is one of those is invisible to a lookup by
    # the converted PubMed ID -- which is exactly the study the "type the PMC id" hint sends
    # people to. Rows found this way carry the converted PubMed ID instead of the PMC string, so
    # they come back runnable rather than as the dead end they are on disk.
    if pmc_id and not rows:
        by_pmc, pmc_warning = await _db_rows(session, pubmed_id=pmc_id)
        rows = [{**row, "pubmed_id": pubmed_id} for row in by_pmc]
        warning = warning or pmc_warning
        if rows:
            warning = warning or (
                f"ImmPort records this study's paper as {pmc_id} rather than as a PubMed ID; "
                f"{pubmed_id} came from NCBI's id converter."
            )

    degraded = warning is not None
    local = _local_state()

    candidates, seen = [], set()
    for row in rows:
        pair = (str(row["pubmed_id"]), str(row["study_accession"]))
        seen.add(pair)
        candidates.append(_decorate(pair[0], pair[1], row, local.get(pair, {})))

    # The union, not a fallback branch: a pair on disk that the database does not know about is
    # still a paper this pipeline can run, and it appears whether the database answered or not.
    known_index = 0 if pubmed_id else 1
    known_value = pubmed_id or study_accession
    local_only = [
        pair for pair in sorted(local)
        if pair[known_index] == known_value and pair not in seen
    ]
    for pair in local_only:
        candidates.append(_decorate(pair[0], pair[1], None, local[pair]))

    if local_only and not degraded:
        warning = warning or (
            f"{len(local_only)} of these are on disk but have no row in study_pubmed, so their "
            "study accession came from a filename rather than from ImmPort."
        )

    # Runnable first, original order preserved within each group: a list whose top entry cannot
    # be clicked reads as a broken page rather than as a data-quality problem.
    candidates.sort(key=lambda c: not c["usable"])
    unusable = [c for c in candidates if not c["usable"]]
    if unusable and not warning:
        warning = (
            f"{len(unusable)} of these have no usable PubMed ID in ImmPort and cannot be run."
        )

    source = "db+local" if rows and local_only else "db" if rows else (
        "local" if local_only else "none")

    reason = None
    if not candidates:
        reason = (
            f"Nothing matches {normalized}. "
            + ("The ImmPort database could not be reached, so only papers already on disk could "
               "be checked." if degraded
               else "It is not in study_pubmed and no paper with that identifier has been "
                    "fetched.")
            + (f" If {normalized} was meant as a PMC id, type it as PMC{normalized}."
               if shape == "pubmed_id" else "")
        )

    return {
        "query": query,
        "shape": shape,
        "normalized": normalized,
        "pmc_id": pmc_id,
        "pubmed_id": pubmed_id,
        "study_accession": study_accession,
        "candidates": candidates,
        "total": len(candidates),
        "source": source,
        "degraded": degraded,
        "warning": warning,
        "resolved_via": "pmc" if pmc_id else shape,
        "reason": reason,
    }
