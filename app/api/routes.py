import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.orchestrator import run_agent, run_agent_from_text
from app.database import get_session
from app.schemas import AgentRequest, AgentResponse, TextRequest

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run", response_model=AgentResponse)
async def agent_run(
    request: AgentRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await run_agent(request.file_path, session)
        return AgentResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/run-upload", response_model=AgentResponse)
async def agent_run_upload(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    suffix = Path(file.filename or "upload.json").suffix or ".json"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    try:
        result = await run_agent(tmp_path, session)
        return AgentResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/run-text", response_model=AgentResponse)
async def agent_run_text(
    request: TextRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await run_agent_from_text(request.message, session)
        return AgentResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/log", response_class=PlainTextResponse)
async def get_log():
    log_file = Path(__file__).resolve().parent.parent.parent / "logs" / "agent_run.log"
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")
