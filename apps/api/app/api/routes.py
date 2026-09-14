import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import assay_immport, assay_jobs, paper_resolver
from app.agent.assay_extractor import AssayExtractionError
from app.agent.jats_fetcher import (
    PaperFetchError,
    PaperNotInPMCError,
    PaperUnavailableError,
    fetch_jats,
)
from app.agent.assay_service import (
    NothingToDoError,
    PaperNotFoundError,
    assay_report,
    available_papers,
    estimate_run,
    stored_registry,
)
from app.agent.claim_parser import _get_client, get_paper_url, parse_paper_claims
from app.agent.orchestrator import run_agent_from_paper, run_agent_from_pdf_vision, run_agent_from_pubmed_id, run_agent_from_text
from app.database import get_session
from app.schemas import (
    AgentResponse,
    AssayEstimateResponse,
    AssayImmportCheckRequest,
    AssayImmportResolveRequest,
    AssayImmportResponse,
    AssayJobResponse,
    AssayPaperAddRequest,
    AssayPaperAddResponse,
    AssayPaperListResponse,
    AssayPaperRequest,
    AssayRegistryResponse,
    AssayRequest,
    AssayResolveRequest,
    AssayResolveResponse,
    AssayResponse,
    AssayRunRequest,
    ParsePaperRequest,
    ParsePaperResponse,
    TextRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run-paper", response_model=AgentResponse)
async def agent_run_paper(
    file: UploadFile | None = File(None),
    question: str | None = Form(None),
    pubmed_id: str | None = Form(None),
    use_vision: bool = Form(False),
    session: AsyncSession = Depends(get_session),
):
    """Upload a PDF paper and run claim extraction, or pass just a PubMed ID.

    - `pubmed_id`: PubMed ID of the paper. Required when no file is uploaded;
      optional when a file is uploaded (falls back to parsing the filename).
    - `use_vision`: when true, renders PDF pages as images and uses GPT-4o vision for
      step-1 claim extraction instead of plain-text extraction. Requires a file.
    - `question`: optional free-text question; if omitted, full claim analysis runs.
    """
    try:
        if file is None:
            if not pubmed_id:
                raise ValueError("Provide either a PDF file or a pubmed_id.")
            result = await run_agent_from_pubmed_id(pubmed_id, session, question=question or None)
        else:
            pdf_bytes = await file.read()
            if use_vision:
                if not pubmed_id:
                    from app.agent.paper_reader import extract_pubmed_id_from_filename
                    pubmed_id = extract_pubmed_id_from_filename(file.filename or "")
                if not pubmed_id:
                    raise ValueError(
                        "pubmed_id is required for the vision pipeline. "
                        "Pass it as a form field or embed it in the filename (e.g. 36656789.pdf)."
                    )
                result = await run_agent_from_pdf_vision(pdf_bytes, pubmed_id, session, question=question or None)
            else:
                result = await run_agent_from_paper(
                    pdf_bytes, file.filename or "", session,
                    question=question or None,
                    pubmed_id=pubmed_id or None,
                )
        return AgentResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        import traceback
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")


@router.post("/chat", response_model=AgentResponse)
async def agent_chat(
    request: TextRequest,
    session: AsyncSession = Depends(get_session),
):
    """Send a free-text question or paste JSON directly."""
    try:
        result = await run_agent_from_text(request.message, session)
        return AgentResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        import traceback
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")


@router.post("/parse-paper", response_model=ParsePaperResponse)
async def agent_parse_paper(
    request: ParsePaperRequest,
):
    try:
        paper_url = get_paper_url(request.study_accession)
        step1, step2 = await parse_paper_claims(paper_url, request.study_accession)
        return ParsePaperResponse(
            study_accession=request.study_accession,
            claims_sentence=step1,
            claims_group=step2,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/assays", response_model=AssayResponse)
async def agent_assays(request: AssayRequest):
    """What assays did this paper use? Extract, verify, correct — and return the accurate set.

    Three rounds in one call:
      1. prompts/extract_assays.txt builds the registry            (1 call)
      2. prompts/verify_assays.txt judges every entry              (1 call per assay)
      3. prompts/correct_assay_field.txt repairs what round 2       (1 call per flagged field)
         refused to support, and sets aside rejected assays

    `assays` in the response is the corrected registry, and it is what assays.json now holds.
    All three rounds run on every request -- asking again about the same paper pays again --
    so this is not an endpoint to put behind a page load. `rounds` reports what each round did
    and what it cost.
    """
    if not (request.study_accession.strip() or request.pubmed_id.strip()):
        raise HTTPException(
            status_code=400,
            detail="Provide study_accession, pubmed_id, or both.",
        )
    try:
        result = await assay_report(
            request.pubmed_id, request.study_accession, _get_client(),
            verify=request.verify, correct=request.correct,
        )
    except PaperNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except AssayExtractionError as exc:
        raise HTTPException(status_code=502, detail=f"assay extraction failed: {exc}")
    return AssayResponse(**result)


# ── the assay workspace: everything here is free ──────────────────────────────
# Declared before any path-parameter route under /assays so a static segment is never swallowed
# by one. None of these three calls a model; the only endpoint on this page that spends is the
# run itself, and that is the whole point of separating them.


def _identifiers(request: AssayPaperRequest) -> tuple[str, str]:
    """The pair, or a 400. Same guard as POST /agent/assays."""
    pubmed_id, study_accession = request.pubmed_id.strip(), request.study_accession.strip()
    if not (pubmed_id or study_accession):
        raise HTTPException(status_code=400,
                            detail="Provide study_accession, pubmed_id, or both.")
    return pubmed_id, study_accession


@router.get("/assay-papers", response_model=AssayPaperListResponse)
async def agent_assay_papers():
    """Every paper the assay pipeline can run on. Free.

    The JATS XML is the gate -- assay_report reads nothing else to find a paper -- so a study
    without one is not offered rather than offered and then failed at.
    """
    return AssayPaperListResponse(papers=available_papers())


@router.post("/assay-papers", response_model=AssayPaperAddResponse)
async def agent_assay_paper_add(request: AssayPaperAddRequest):
    """Add a paper to the corpus by PubMed ID. Free -- two NCBI requests, no model calls.

    The JATS XML is the only thing the assay chain reads to find a paper, and until now the only
    writer into that directory was a batch script. This is the single-paper route.

    The status codes distinguish failures a caller has to act on differently:
      400  the identifiers cannot be filed under their own name (checked before any request)
      404  the PubMed ID has no open-access PMC record at all
      422  the paper is in PMC but not as usable full text -- abstract-only, or the publisher
           restricts download. A large minority of papers land here; it is a normal outcome.
      502  NCBI could not be reached, which unlike the above is worth retrying.

    A paper already on disk comes back 200 with `created: false` and costs no request: asking
    twice is idempotent, and re-downloading would renumber the sentences a stored registry cites.
    """
    try:
        result = await fetch_jats(
            request.pubmed_id, request.study_accession, force=request.force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PaperUnavailableError as exc:
        # "No such open-access paper" and "the paper is there but PMC will not serve its body"
        # send a reader to different next steps, so they are not the same status. Decided by
        # type, not by a substring of the message -- rewording one sentence should not move a
        # status code, and once did.
        status = 404 if isinstance(exc, PaperNotInPMCError) else 422
        raise HTTPException(status_code=status, detail=str(exc))
    except PaperFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # Looked up rather than synthesised, so the caller gets exactly the row the picker lists and
    # can select it without re-fetching the whole list.
    summary = next(
        (p for p in available_papers()
         if (p["pubmed_id"], p["study_accession"]) == (result["pubmed_id"],
                                                       result["study_accession"])),
        None,
    )
    if summary is None:
        raise HTTPException(
            status_code=500,
            detail=f"{result['filename']} was written but is not being offered; "
                   "the corpus directory may have moved mid-request",
        )

    return AssayPaperAddResponse(
        created=result["created"],
        paper=summary,
        message=(f"Fetched {result['pmcid']} into {result['filename']}."
                 if result["created"]
                 else f"{result['filename']} was already in the corpus; nothing was fetched."),
    )


@router.post("/assays/estimate", response_model=AssayEstimateResponse)
async def agent_assay_estimate(request: AssayPaperRequest):
    """What a run would cost, without calling anything. Free.

    The same count `scripts/run_assay_pipeline.py --dry-run` prints, from the same function --
    CLAUDE.md requires the estimate be reported before a paid run, and a gate that disagreed
    with the CLI would mean two different things in two places.
    """
    pubmed_id, study_accession = _identifiers(request)
    try:
        return AssayEstimateResponse(**estimate_run(pubmed_id, study_accession))
    except PaperNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/assays/resolve", response_model=AssayResolveResponse)
async def agent_assay_resolve(
    request: AssayResolveRequest,
    session: AsyncSession = Depends(get_session),
):
    """One identifier -> every (pubmed_id, study_accession) pair it could mean. Free.

    Returns a list and never picks. The mapping is many-to-many in both directions -- SDY212 has
    six papers, PubMed ID 26682988 belongs to five studies -- so a resolver that chose would be
    wrong for roughly a tenth of identifiers and would say nothing about it. Getting it wrong
    does not produce a bad extraction; it produces a correct, verified registry filed under a
    study it does not describe.

    400 only for a string that is not an identifier at all. Everything else is a 200, including
    no matches and a database that could not be reached: for a chat turn, "nothing matched, here
    is what I checked" is more useful than an exception.
    """
    try:
        resolution = await paper_resolver.resolve(request.query, session)
    except paper_resolver.UnrecognizedQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AssayResolveResponse(**resolution)


@router.get("/assays/registry", response_model=AssayRegistryResponse)
async def agent_assay_registry(study_accession: str = "", pubmed_id: str = ""):
    """What a previous run left on disk, with the free checks recomputed. Free.

    The counterpart to POST /agent/assays, which never serves a stored run. This one only
    serves stored runs, so a page can show what is already known without a page load costing
    anything -- and so a result survives the backend restarting mid-run, which is the normal
    case under `uvicorn --reload`.
    """
    pubmed_id, study_accession = _identifiers(
        AssayPaperRequest(pubmed_id=pubmed_id, study_accession=study_accession))
    try:
        return AssayRegistryResponse(**stored_registry(pubmed_id, study_accession))
    except NothingToDoError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── the assay workspace: the one endpoint that spends ─────────────────────────


async def _run_job(job_id: str, pubmed_id: str, study_accession: str,
                   verify: bool, correct: bool) -> None:
    """Drive one run to a terminal state. Never raises into the task's caller.

    Every failure becomes a recorded state rather than a traceback nobody sees: the request
    that started this returned long ago, so an exception here would otherwise vanish into the
    event loop with the job stuck on "running" forever.
    """
    try:
        result = await assay_report(
            pubmed_id, study_accession, _get_client(), verify=verify, correct=correct,
            on_progress=lambda event: assay_jobs.record_progress(job_id, event),
        )
    except asyncio.CancelledError:
        # Terminal, and not a refund: the calls already sent are already billed, and every file
        # the run wrote before this point stays on disk.
        assay_jobs.mark_cancelled(job_id)
        raise
    except PaperNotFoundError as exc:
        assay_jobs.fail(job_id, f"paper not found: {exc}")
    except AssayExtractionError as exc:
        assay_jobs.fail(job_id, f"assay extraction failed: {exc}")
    except Exception as exc:
        assay_jobs.fail(job_id, f"{type(exc).__name__}: {exc}")
    else:
        assay_jobs.finish(job_id, result)


@router.post("/assays/runs", response_model=AssayJobResponse, status_code=202)
async def agent_assay_run(request: AssayRunRequest):
    """Start a run and return its id. **This spends money.**

    Every guard below runs before a single call is made, in the order a mistake is cheapest to
    catch: no identifier, then no acknowledged estimate, then no paper, then a run already under
    way for this paper. That last one is the only failure on this page that costs rather than
    annoys -- two tabs or a double-click would otherwise buy the same answer twice -- so it is
    a refusal carrying the existing job's id, which a caller should adopt rather than retry.

    The estimate is recomputed and stored with the job. When it disagrees with what the caller
    acknowledged the run still starts, and the difference is recorded: rounds 2 and 3 are sized
    from the previous run's output, so they were always approximate, and refusing over a moved
    approximation would block the paper it is most useful on.
    """
    pubmed_id, study_accession = _identifiers(
        AssayPaperRequest(pubmed_id=request.pubmed_id, study_accession=request.study_accession))

    if request.acknowledged_calls is None and not request.acknowledged_unknown:
        raise HTTPException(
            status_code=400,
            detail=("run not confirmed: POST /agent/assays/estimate first and send back its "
                    "total_calls as acknowledged_calls (or acknowledged_unknown when the "
                    "estimate could not size the run)"),
        )

    try:
        estimate = estimate_run(pubmed_id, study_accession)
    except PaperNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    running = assay_jobs.active_for(pubmed_id, study_accession)
    if running is not None:
        raise HTTPException(
            status_code=409,
            detail=f"a run is already under way for this paper (job {running.id}); "
                   "adopt it rather than starting a second one",
        )

    drift = None
    if request.acknowledged_calls is not None \
            and request.acknowledged_calls != estimate["total_calls"]:
        drift = {"acknowledged": request.acknowledged_calls,
                 "estimated": estimate["total_calls"]}

    job = assay_jobs.create(pubmed_id, study_accession, estimate=estimate,
                            acknowledged_calls=request.acknowledged_calls, estimate_drift=drift)
    task = asyncio.create_task(
        _run_job(job.id, pubmed_id, study_accession, request.verify, request.correct))
    assay_jobs.start(job.id, task)
    return AssayJobResponse(**assay_jobs.snapshot(job.id))


@router.get("/assays/runs/{job_id}", response_model=AssayJobResponse)
async def agent_assay_run_status(job_id: str):
    """Where a run has got to, and its result once it is done. Free.

    A 404 here means the backend restarted, which under `uvicorn --reload` happens on every
    edit. It is not an error to recover from by re-running: the files the run wrote are on
    disk, and GET /agent/assays/registry reads them back for nothing.
    """
    snapshot = assay_jobs.snapshot(job_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"no run {job_id!r}; it finished before a restart, or never existed. "
                   "Anything it wrote is still in the registry directory.",
        )
    return AssayJobResponse(**snapshot)


@router.post("/assays/runs/{job_id}/cancel", response_model=AssayJobResponse)
async def agent_assay_run_cancel(job_id: str):
    """Stop a run. Free to ask; what it already spent stays spent."""
    if assay_jobs.get(job_id) is None:
        raise HTTPException(status_code=404, detail=f"no run {job_id!r}")
    if not assay_jobs.request_cancel(job_id):
        raise HTTPException(status_code=409, detail=f"run {job_id!r} has already finished")
    return AssayJobResponse(**assay_jobs.snapshot(job_id))


@router.post("/cache/clear")
async def clear_cache():
    """No-op: in-memory cache has been removed; disk cache is managed manually."""
    return {"cleared": True}


@router.get("/log", response_class=PlainTextResponse)
async def get_log():
    log_file = Path(__file__).resolve().parent.parent.parent / "logs" / "agent_run.log"
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


@router.get("/completeness-report")
async def get_completeness_report():
    """Return the completeness report from the most recent agent run."""
    report_file = Path(__file__).resolve().parent.parent.parent / "logs" / "completeness_report.json"
    if not report_file.exists():
        raise HTTPException(status_code=404, detail="No completeness report found. Run an analysis first.")
    import json
    return JSONResponse(content=json.loads(report_file.read_text(encoding="utf-8")))


# ── is the corpus's assays registered in ImmPort? ─────────────────────────────


def _corpus_rows() -> list[dict]:
    """The same rows GET /agent/assay-obi serves, so the two tables line up row for row."""
    if not _ASSAY_OBI_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="No assay/OBI table found at data/claims/all_assays_full_OBI.json.",
        )
    import json

    return json.loads(_ASSAY_OBI_PATH.read_text(encoding="utf-8"))


@router.get("/assay-immport", response_model=AssayImmportResponse)
async def agent_assay_immport(session: AsyncSession = Depends(get_session)):
    """For every corpus assay, does ImmPort record an experiment for that study? Free.

    The SQL half of the same resolver the query builder uses, so an assay called present here is
    one a claim query would find. No model call: `use_llm=False` stops each lookup after the
    free step, and the rows it could not place are reported as such rather than resolved at a
    call apiece.

    A database that is down degrades to empty rather than 500 -- the corpus table is readable
    without ImmPort, it simply cannot say anything about coverage.
    """
    rows = _corpus_rows()
    try:
        report = await assay_immport.check_rows(session, rows, use_llm=False)
    except Exception as exc:
        logger.warning("ImmPort coverage sweep failed: %s", exc)
        return AssayImmportResponse(
            degraded=True,
            warning="The ImmPort database could not be reached, so no coverage could be "
                    "checked. The assay table itself is unaffected.",
        )
    return AssayImmportResponse(**report)


@router.post("/assay-immport/check", response_model=AssayImmportResponse)
async def agent_assay_immport_check(
    request: AssayImmportCheckRequest,
    session: AsyncSession = Depends(get_session),
):
    """Does ImmPort register experiments for these specific assays? Free.

    The same free SQL pass GET /agent/assay-immport runs over the whole corpus, pointed at the
    rows for one paper -- so a "yes" here and a "yes" in the corpus table mean the same thing,
    because they are the same function with `use_llm=False`.

    Takes no acknowledgement because it cannot spend: that is what separates it from
    /assay-immport/resolve, which asks a model about the rows this one could not place.
    """
    if not request.rows:
        return AssayImmportResponse()
    try:
        report = await assay_immport.check_rows(session, request.rows, use_llm=False)
    except Exception as exc:
        logger.warning("ImmPort coverage check failed: %s", exc)
        return AssayImmportResponse(
            degraded=True,
            warning="The ImmPort database could not be reached, so coverage could not be "
                    "checked. The extracted registry itself is unaffected.",
        )
    return AssayImmportResponse(**report)


@router.post("/assay-immport/resolve", response_model=AssayImmportResponse)
async def agent_assay_immport_resolve(
    request: AssayImmportResolveRequest,
    session: AsyncSession = Depends(get_session),
):
    """Ask the resolver about rows the free pass could not place. **This spends.**

    One model call per row, using the same LLM fallback the query builder uses when it cannot
    match an assay by SQL. Refused without `acknowledged_calls`, for the same reason the run
    endpoint is: a caller must have been shown the bill before it can run one up.
    """
    if not request.rows:
        raise HTTPException(status_code=400, detail="No rows to resolve.")
    if request.acknowledged_calls is None:
        raise HTTPException(
            status_code=400,
            detail=(f"run not confirmed: this resolves {len(request.rows)} row(s) at one model "
                    "call each; send that number back as acknowledged_calls"),
        )
    report = await assay_immport.check_rows(session, request.rows, use_llm=True)
    return AssayImmportResponse(**report)


# ── Assay → OBI registry ──────────────────────────────────────────────────────

# Fixed display order, so the UI's colours never shift when the data changes. Cheapest to
# most expensive, which is also free-to-paid: the two exact tiers cost nothing, the two
# embedding tiers cost two calls each. "exact_normalized" is the retired lexical round, kept
# because 40 stored rows still carry it; "exact_normalized_llm" is the live one.
_RESOURCE_ORDER = ["exact_original", "exact_normalized", "exact_normalized_llm",
                   "embedding_llm", "embedding_llm_normalized", "unresolved"]

_ASSAY_OBI_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "claims" / "all_assays_full_OBI.json"
)


def _assay_obi_stats(rows: list[dict]) -> dict:
    """Summary counts for the assay registry table.

    Computed here rather than in the browser so the arithmetic is testable and the
    frontend stays a renderer.
    """
    by_resource = {resource: 0 for resource in _RESOURCE_ORDER}
    for row in rows:
        resource = row.get("resource") or "unresolved"
        by_resource[resource] = by_resource.get(resource, 0) + 1

    mapped_rows = sum(1 for row in rows if row.get("obi_id"))
    unresolved_names = sorted({row["assay"] for row in rows if not row.get("obi_id")})

    return {
        "total_rows": len(rows),
        "papers": len({row.get("study") for row in rows}),
        "obi_terms": len({row["obi_id"] for row in rows if row.get("obi_id")}),
        "mapped_rows": mapped_rows,
        "coverage_pct": round(100 * mapped_rows / len(rows), 1) if rows else 0.0,
        # Ordered list, not a dict — the bar segments must render in a stable order.
        "by_resource": [
            {"resource": resource, "count": by_resource[resource]}
            for resource in _RESOURCE_ORDER
            if by_resource.get(resource)
        ],
        "unresolved_names": unresolved_names,
    }


@router.get("/assay-obi")
async def get_assay_obi():
    """Return the assay registry with its OBI mappings, plus summary statistics."""
    if not _ASSAY_OBI_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No assay/OBI table found at data/claims/all_assays_full_OBI.json."
            ),
        )
    import json

    rows = json.loads(_ASSAY_OBI_PATH.read_text(encoding="utf-8"))
    return JSONResponse(content={"rows": rows, "stats": _assay_obi_stats(rows)})
