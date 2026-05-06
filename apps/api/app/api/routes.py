from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.claim_parser import get_assay_methods, get_paper_url, parse_paper_claims
from app.agent.orchestrator import run_agent_from_text, _paper_step1_cache, _paper_claims_cache
from app.database import get_session
from app.schemas import AgentResponse, ParsePaperRequest, ParsePaperResponse, TextRequest

router = APIRouter(prefix="/agent", tags=["agent"])


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
            claims=step1,
            groups=step2,
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
