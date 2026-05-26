from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.claim_parser import get_assay_methods, get_paper_url, parse_paper_claims
from app.agent.orchestrator import run_agent_from_paper, run_agent_from_text, _paper_step1_cache, _paper_claims_cache
from app.database import get_session
from app.schemas import AgentResponse, ParsePaperRequest, ParsePaperResponse, TextRequest

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run-paper", response_model=AgentResponse)
async def agent_run_paper(
    file: UploadFile = File(...),
    question: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    """Upload a PDF paper. The filename must contain the PubMed/PMC ID
    (e.g. PMC9924941.pdf). Optionally include a question to answer against
    the study instead of running full claim extraction.
    """
    pdf_bytes = await file.read()
    try:
        result = await run_agent_from_paper(pdf_bytes, file.filename or "", session, question=question or None)
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
        assay_methods = get_assay_methods(request.study_accession)
        step1, step2 = await parse_paper_claims(paper_url, request.study_accession, assay_methods)
        return ParsePaperResponse(
            study_accession=request.study_accession,
            assay_methods=assay_methods,
            claims_sentence=step1,
            claims_group=step2,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/cache/clear")
async def clear_cache():
    """Clear the in-memory paper claims cache."""
    _paper_step1_cache.clear()
    _paper_claims_cache.clear()
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
