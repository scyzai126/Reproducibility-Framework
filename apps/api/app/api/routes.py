from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.claim_parser import get_assay_methods, get_paper_url, parse_paper_claims
from app.agent.orchestrator import run_agent_from_paper, run_agent_from_pdf_vision, run_agent_from_pubmed_id, run_agent_from_text
from app.database import get_session
from app.schemas import AgentResponse, ParsePaperRequest, ParsePaperResponse, TextRequest

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
