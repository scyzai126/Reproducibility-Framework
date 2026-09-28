"""One paper's data-availability run, shared by scripts/run_data_availability.py and the web app.

app.agent.data_availability holds the steps; this module sequences them for one paper -- load,
one LLM call, repository validation, combine, locate -- and writes the two files the CLI has
always written to data/benchmark_assay/data_availability/:

  <SDY>_<PMID>_llm.json  before validation: every ID, its sentences, DA membership, the LLM's roles
  <SDY>_<PMID>.json      the final answer: `data_repositories` and `unconfirmed`

so a run from the Extract tab and a run from the command line leave exactly the same files. Every
REVIEW / DROPPED / WARNING / NOTE line comes back in the result rather than being printed, and the
caller decides how to show it.

**Cost:** one LLM call per paper, and none when the paper names no accession outside its
references. Validation and locating are free network lookups (plus the local ImmPort database).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.agent import assay_service
from app.agent.data_availability import (
    DEPOSITED,
    ROLES,
    DataAvailabilityError,
    add_linked_datasets,
    apply_validation,
    build_record,
    classify_candidates,
    group_mentions,
    llm_candidates,
    load_paper,
    repository_record,
    settle_drops,
)
from app.config import settings

logger = logging.getLogger(__name__)

OUT_DIR = Path(__file__).resolve().parents[4] / "data" / "benchmark_assay" / "data_availability"


def stem_for(pubmed_id: str, study_accession: str) -> str:
    """The files are named `<SDY>_<PMID>`, the paper-file spelling, not the registry's."""
    return f"{study_accession}_{pubmed_id}"


def paper_path(pubmed_id: str, study_accession: str) -> Optional[Path]:
    """The paper to read: its JATS XML when there is one, else its PDF -- as the assay chain does."""
    return (assay_service.locate_paper_xml(pubmed_id, study_accession)
            or assay_service.locate_paper_pdf(pubmed_id, study_accession))


def load(path: Path) -> dict:
    """The paper, with its regex candidates grouped into one entry per accession. Free."""
    paper = load_paper(path)
    paper["entries"] = group_mentions(paper["mentions"])
    return paper


def estimate(pubmed_id: str, study_accession: str) -> dict:
    """What the data step would cost, in the shape of an assay estimate round. Free.

    Exact: the step makes one call when the paper names any accession, and none otherwise.
    """
    path = paper_path(pubmed_id, study_accession)
    if path is None:
        return {"round": 6, "name": "data_availability", "calls": 0, "exact": True,
                "basis": "no paper file", "entries": 0}
    paper = load(path)
    candidates = len(llm_candidates(paper["entries"]))
    return {"round": 6, "name": "data_availability", "calls": 1 if candidates else 0,
            "exact": True, "basis": "one call per paper naming an accession",
            "entries": len(paper["entries"])}


def out_dir_for(pubmed_id: str, study_accession: str) -> Path:
    """Where this paper's two files go: beside its assay registry in the cache for a paper
    outside the benchmark, else the benchmark's OUT_DIR (which the corpus table reads)."""
    if assay_service.is_cached(pubmed_id, study_accession):
        return assay_service.registry_dir(pubmed_id, study_accession)
    return OUT_DIR


def stored(pubmed_id: str, study_accession: str) -> Optional[dict]:
    """The final record a previous run wrote, or None. Free.

    A record without `data_repositories` is the single-file format written before the two-file
    split; it does not answer "where is the data", so it reads as never run, as in stored_all.
    """
    path = out_dir_for(pubmed_id, study_accession) / f"{stem_for(pubmed_id, study_accession)}.json"
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("unreadable data-availability record %s: %s", path, exc)
        return None
    return record if isinstance(record, dict) and "data_repositories" in record else None


def stored_all() -> dict[str, dict]:
    """Every paper's final record, keyed `<PMID>_<SDY>` -- the corpus table's spelling. Free.

    The `_llm.json` files and any record without `data_repositories` (the single-file format
    written before the two-file split) are skipped: they do not answer "where is the data".
    """
    papers: dict[str, dict] = {}
    if not OUT_DIR.is_dir():
        return papers
    for path in sorted(OUT_DIR.glob("*.json")):
        if path.stem.endswith("_llm"):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("unreadable data-availability record %s: %s", path, exc)
            continue
        if not isinstance(record, dict) or "data_repositories" not in record:
            continue
        study, _, pmid = path.stem.partition("_")
        papers[f"{record.get('pmid') or pmid}_{record.get('study') or study}"] = record
    return papers


async def immport_lookup_factory(on_warning=None):
    """An ImmPort lookup over the local database, plus a closer. (None, None) if unavailable."""
    try:
        from sqlalchemy import text

        from app.agent.paper_resolver import _db_rows, normalize_row_pmid
        from app.database import async_session, engine
    except Exception as exc:  # noqa: BLE001 -- any import/config failure means "no database"
        if on_warning:
            on_warning(f"ImmPort database unavailable ({exc}); SDY accessions stay unchecked")
        return None, None

    async def lookup(sdy: str):
        try:
            async with async_session() as session:
                found = await session.execute(
                    text("SELECT 1 FROM study WHERE study_accession = :a LIMIT 1"), {"a": sdy})
                exists = found.first() is not None
                rows, warning = await _db_rows(session, study_accession=sdy)
            if warning:
                return None
            pmids = [p for p, bad in (normalize_row_pmid(r.get("pubmed_id")) for r in rows) if not bad]
            return exists, pmids
        except Exception:  # noqa: BLE001 -- a dead database is UNCHECKED, never NOT_FOUND
            return None

    async def title(sdy: str):
        try:
            async with async_session() as session:
                row = (await session.execute(
                    text("SELECT brief_title FROM study WHERE study_accession = :a LIMIT 1"),
                    {"a": sdy})).first()
            return row[0] if row else None
        except Exception:  # noqa: BLE001 -- the title is a nicety; the location stands without it
            return None

    lookup.title = title
    return lookup, engine.dispose


async def run_paper(stem: str, path: Path, *, client, http, ncbi, immport_lookup=None,
                    validate: bool = True, locate_data: bool = True,
                    cache: Optional[dict] = None, locate_cache: Optional[dict] = None,
                    out_dir: Path = OUT_DIR) -> dict:
    """Run one paper end to end and write its two files.

    Returns `{"record", "final", "paper", "llm_model", "llm_calls", "notes", "located",
    "located_of", "llm_path", "final_path"}`. `record` carries every role plus the reviews,
    dropped and warnings lines; `final` is what `<stem>.json` holds.
    """
    from app.agent.accession_validator import (
        NO_PUBLIC_LOOKUP,
        UNCHECKED,
        datasets_linked_to_paper,
        validate_accessions,
    )
    from app.agent.data_locator import LOCATABLE, locate

    cache = {} if cache is None else cache
    locate_cache = {} if locate_cache is None else locate_cache
    out_dir.mkdir(parents=True, exist_ok=True)

    paper = load(path)
    entries, pmid = paper["entries"], paper["pmid"]
    warnings: list[str] = []
    notes: list[str] = []
    llm_model = None
    llm_calls = 0

    # Step 2: the model judges every text-named ID before any repository is asked.
    if llm_candidates(entries):
        llm_calls = 1
        try:
            warnings += await classify_candidates(paper["title"] or "", pmid, paper["text"],
                                                  entries, client)
            llm_model = settings.OPENAI_MODEL
        except DataAvailabilityError as exc:
            warnings.append(f"LLM call failed: {exc}; every ID stays unclear")

    # Before validation: what the paper and the model say, on its own.
    dropped = settle_drops(entries)
    llm_record = build_record(pmid, paper["study"], paper["title"], paper["statement"],
                              entries, warnings=warnings, dropped=dropped,
                              source_format=paper["format"], llm_model=llm_model,
                              statement_source=paper["statement_source"], validated=False)
    llm_path = out_dir / f"{stem}_llm.json"
    llm_path.write_text(json.dumps(llm_record, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    # Step 3: the repositories check the model's answer.
    if validate:
        add_linked_datasets(entries, await datasets_linked_to_paper(pmid, ncbi))
        validations = await validate_accessions(
            [(e["accession"], e["repository"]) for e in entries.values()],
            http, immport_lookup=immport_lookup, cache=cache, ncbi=ncbi)
        apply_validation(entries, validations, pmid)
        for acc, v in validations.items():
            if v["status"] != UNCHECKED:
                continue
            if v["detail"].startswith(NO_PUBLIC_LOOKUP):
                notes.append(f"{acc} cannot be checked: {v['detail']}")
            else:
                warnings.append(f"{acc} left unchecked: {v['detail']}")
        # An ID the model never answered for, that the repository has no record of.
        dropped += settle_drops(entries)

    record = build_record(pmid, paper["study"], paper["title"], paper["statement"], entries,
                          warnings=warnings, dropped=dropped, source_format=paper["format"],
                          llm_model=llm_model, statement_source=paper["statement_source"])
    located = located_of = 0
    if locate_data:
        title_lookup = getattr(immport_lookup, "title", None)
        for item in record[DEPOSITED]:
            if item["kind"] != "data" or item["repository"] not in LOCATABLE:
                continue
            if item["status"] not in ("verified", "private"):
                continue
            located_of += 1
            location = await locate(item["accession"], item["repository"], http, ncbi,
                                    status=item["status"], title_lookup=title_lookup,
                                    cache=locate_cache)
            if location is None:
                continue
            location["landing_page"] = location["landing_page"] or item["url"]
            item["location"] = location
            if location["error"]:
                record["warnings"].append(f"locating {item['accession']}: {location['error']}")
            else:
                located += 1

    final = repository_record(record)
    final_path = out_dir / f"{stem}.json"
    final_path.write_text(json.dumps(final, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"record": record, "final": final, "paper": paper, "llm_model": llm_model,
            "llm_calls": llm_calls, "notes": notes, "located": located, "located_of": located_of,
            "llm_path": llm_path, "final_path": final_path}


def findings(run: dict) -> dict:
    """The lines a reader must see, grouped, plus role counts -- JSON-safe, for the web app."""
    record = run["record"]
    return {
        "reviews": list(record.get("reviews") or []),
        "dropped": list(record.get("dropped") or []),
        "warnings": list(record.get("warnings") or []),
        "notes": list(run.get("notes") or []),
        "roles": {role: len(record.get(role) or []) for role in ROLES},
    }


async def run_for_paper(pubmed_id: str, study_accession: str, client) -> dict:
    """The web app's entry point: find the paper, run it, and return a JSON-safe summary.

    Opens its own HTTP client and ImmPort lookup and closes both, so a job can call it alongside
    the assay chain without sharing anything with it.
    """
    import httpx

    from app.agent.accession_validator import _Ncbi

    path = paper_path(pubmed_id, study_accession)
    if path is None:
        raise assay_service.PaperNotFoundError(
            f"no JATS XML or PDF on disk for {study_accession} / {pubmed_id}")
    setup_warnings: list[str] = []
    immport_lookup, close_db = await immport_lookup_factory(setup_warnings.append)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            run = await run_paper(stem_for(pubmed_id, study_accession), path, client=client,
                                  http=http, ncbi=_Ncbi(http), immport_lookup=immport_lookup,
                                  out_dir=out_dir_for(pubmed_id, study_accession))
    finally:
        if close_db is not None:
            await close_db()
    summary = findings(run)
    summary["warnings"] = setup_warnings + summary["warnings"]
    return {
        **run["final"],
        **summary,
        "llm_calls": run["llm_calls"],
        "llm_model": run["llm_model"],
        "statement_source": run["paper"].get("statement_source"),
        "located": run["located"],
        "located_of": run["located_of"],
        "files": {"final": assay_service._display_path(run["final_path"]),
                  "llm": assay_service._display_path(run["llm_path"])},
    }
