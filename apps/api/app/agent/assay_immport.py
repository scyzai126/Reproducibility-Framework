"""Does ImmPort actually record this assay as an experiment for this study?

An extracted registry says what a paper reports doing. ImmPort's `experiment` table says what was
registered for the study. The two routinely disagree -- SDY1264's paper describes nine assays and
ImmPort holds two experiments for it, and three studies in the corpus have no experiment rows at
all -- so the gap is worth reporting rather than assuming.

The matching is not reimplemented here. `query_builder.resolve_experiment_accession` is the
function that resolves an assay to an `experiment_accession` when a claim is turned into SQL, and
it is the one used here, so an assay this module calls present is one the query builder would
find. All this module adds is which search terms to hand it, and the arithmetic over a whole
corpus.

**The sweep is free.** `use_llm=False` stops each lookup after the SQL step, so a caller can ask
about 171 rows without paying for one model call, and then spend only on the entries that did not
resolve. Answering "is it in ImmPort?" for a study with no experiments at all costs nothing and
should never reach a model.
"""

import logging
import re
from collections.abc import Iterable, Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.assay_service import split_stem
from app.agent.query_builder import (
    get_assay_method_for_experiment,
    resolve_experiment_accession,
)

logger = logging.getLogger(__name__)

#: Statuses a row can end in. `no_experiments` is kept apart from `absent` because they are
#: different facts: ImmPort registered nothing at all for the study, versus it registered
#: experiments and this assay is not recognisably one of them. Only the second is worth paying a
#: model call to look at again.
MATCHED = "matched"
ABSENT = "absent"
NO_EXPERIMENTS = "no_experiments"
UNKNOWN_STUDY = "unknown_study"

#: OBI labels end in "assay" or "analysis"; ImmPort's `measurement_technique` column does not, so
#: `%flow cytometry assay%` misses a row reading "Flow Cytometry". Stripping the suffix is free
#: and, across the stored corpus, is most of the difference between 22 and 41 rows resolving
#: without a model call.
_SUFFIX_RE = re.compile(r"\s+(assay|analysis|analyses)$", re.IGNORECASE)

#: Below this a LIKE pattern matches most of the table. "PCR" is a real assay name and only three
#: characters, but `%PCR%` against a study's experiments is noise, not a resolution.
_MIN_TERM = 4


def search_terms(
    assay: str = "",
    normalized_name: str = "",
    obi_label: str = "",
    aliases: Iterable[str] = (),
) -> list[str]:
    """Every wording worth trying against ImmPort's `name` and `measurement_technique`.

    Ordered by how likely each is to be ImmPort's own vocabulary rather than the paper's:
    `normalized_name` is the extractor's judgement of the technique and is what ImmPort's column
    holds ("Luminex xMAP"), so it goes first; the paper's own wording goes last because it is the
    most idiosyncratic. Suffix-stripped variants follow their originals.

    Deduplicated case-insensitively and filtered by length, because the caller pays a query per
    term and a two-character term resolves nothing.
    """
    ordered = [normalized_name, assay, obi_label, *aliases]
    widened: list[str] = []
    for term in ordered:
        widened.append(term)
        stripped = _SUFFIX_RE.sub("", term or "")
        if stripped != term:
            widened.append(stripped)

    seen: set[str] = set()
    out: list[str] = []
    for term in widened:
        cleaned = (term or "").strip()
        key = cleaned.lower()
        if len(cleaned) >= _MIN_TERM and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


async def _experiment_counts(session: AsyncSession, studies: Iterable[str]) -> dict[str, int]:
    """How many experiments ImmPort holds per study. One query, not one per row.

    Read before any resolution so a study with nothing registered short-circuits every one of its
    rows without a lookup -- that is the cheapest true answer the sweep can give.
    """
    wanted = sorted({s for s in studies if s})
    if not wanted:
        return {}
    result = await session.execute(
        text("SELECT study_accession, COUNT(*) FROM experiment "
             "WHERE study_accession IN :studies GROUP BY study_accession")
        .bindparams(bindparam("studies", expanding=True)),
        {"studies": wanted},
    )
    counts = {row[0]: row[1] for row in result.fetchall()}
    return {study: counts.get(study, 0) for study in wanted}


def study_accession_of(row: dict) -> str:
    """The SDY half of a corpus row's `study`, which is spelled `<pmid>_<SDY>`."""
    raw = str(row.get("study") or "").strip()
    if raw.upper().startswith("SDY") and "_" not in raw:
        return raw.upper()
    split = split_stem(raw)
    return split[1] if split else ""


async def check_rows(
    session: AsyncSession,
    rows: Sequence[dict],
    *,
    use_llm: bool = False,
) -> dict:
    """Resolve every row against ImmPort's experiments. Free unless `use_llm` is set.

    Returns `{"rows": [...], "stats": {...}}` -- keyed "rows" to match AssayImmportResponse,
    because a name that disagrees with the schema is silently dropped by the response model
    rather than raising. Each row carries the status, the
    `experiment_accession` when one was found, how it was found ("SQL" or "LLM"), and how many
    experiments the study has at all -- which is what tells "not registered" apart from "nothing
    registered for this study".
    """
    counts = await _experiment_counts(session, (study_accession_of(r) for r in rows))

    results: list[dict] = []
    for row in rows:
        study = study_accession_of(row)
        entry = {
            "study": row.get("study", ""),
            "study_accession": study,
            "assay": row.get("assay", ""),
            "experiment_accession": None,
            "measurement_technique": None,
            "method": None,
            "status": UNKNOWN_STUDY,
            "study_experiments": counts.get(study, 0),
        }

        if not study:
            results.append(entry)
            continue
        if counts.get(study, 0) == 0:
            # Certain, and free: there is nothing in ImmPort for this study to match against.
            entry["status"] = NO_EXPERIMENTS
            results.append(entry)
            continue

        terms = search_terms(
            assay=row.get("assay") or "",
            normalized_name=row.get("normalized_name") or "",
            obi_label=row.get("obi_label") or "",
            aliases=row.get("aliases") or (),
        )
        resolved = None
        if terms:
            resolved = await resolve_experiment_accession(
                session,
                terms[0],
                study,
                original_name=terms[1] if len(terms) > 1 else "",
                readouts=row.get("readouts") or "",
                platform=row.get("platform") or "",
                extra_terms=terms[2:],
                use_llm=use_llm,
            )

        if resolved:
            entry["experiment_accession"], entry["method"] = resolved
            entry["status"] = MATCHED
            # The technique ImmPort filed it under, which is what says *what* it matched rather
            # than merely that it did. One query per match, and only for matches.
            entry["measurement_technique"] = await get_assay_method_for_experiment(
                session, entry["experiment_accession"])
        else:
            entry["status"] = ABSENT
        results.append(entry)

    return {"rows": results, "stats": summarize(results)}


def summarize(results: Sequence[dict]) -> dict:
    """Counts, plus the studies ImmPort holds nothing for.

    The unresolved total is what a caller would pay to look at again with a model, so it is
    reported as its own number rather than left to be derived.
    """
    by_status: dict[str, int] = {}
    for entry in results:
        by_status[entry["status"]] = by_status.get(entry["status"], 0) + 1
    return {
        "total": len(results),
        "matched": by_status.get(MATCHED, 0),
        "absent": by_status.get(ABSENT, 0),
        "no_experiments": by_status.get(NO_EXPERIMENTS, 0),
        "unknown_study": by_status.get(UNKNOWN_STUDY, 0),
        # Only `absent` is worth a model call: the others are already answered.
        "resolvable": by_status.get(ABSENT, 0),
        "studies_without_experiments": sorted(
            {e["study_accession"] for e in results if e["status"] == NO_EXPERIMENTS}),
    }
