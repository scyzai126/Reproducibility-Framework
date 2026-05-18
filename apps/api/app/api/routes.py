import json
import sys
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.claim_parser import get_assay_methods, get_paper_url, parse_paper_claims
from app.agent.orchestrator import run_agent_from_text, _paper_step1_cache, _paper_claims_cache
from app.database import async_session, get_session
from app.schemas import (
    AgentResponse, ParsePaperRequest, ParsePaperResponse, TextRequest,
    RunClaimsRequest, RunClaimsResponse,
)

_VALIDATED_CLAIMS_DIR = Path(__file__).resolve().parents[4] / "data" / "claims" / "validated_claims"
_OUTPUT_IDS_DIR = Path(__file__).resolve().parents[4] / "data" / "generated" / "outputIDs"

# Ensure run_claim.py (at apps/api/) is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run-claims", response_model=RunClaimsResponse)
async def run_claims(
    study_accession: str = Form(...),
    claims_file: UploadFile | None = File(None),
):
    """Run a validated claims JSON through the query pipeline and return subject IDs.

    Two modes:
    - Upload a claims JSON file via `claims_file` + `study_accession` form fields.
    - Omit `claims_file` to auto-discover the file from the server's validated_claims directory.
    """
    from run_claim import run as _run_claims

    # Resolve the claims file path
    if claims_file is not None:
        content = await claims_file.read()
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.write(content)
        tmp.flush()
        claim_path = Path(tmp.name)
    else:
        matches = sorted(_VALIDATED_CLAIMS_DIR.glob(f"claims_LLM_{study_accession}*.json"))
        if not matches:
            raise HTTPException(
                status_code=404,
                detail=f"No claims file found for study '{study_accession}' in validated_claims/.",
            )
        claim_path = matches[0]

    output_path = _OUTPUT_IDS_DIR / f"{study_accession}_subject_ids.json"

    try:
        await _run_claims(claim_path, study_accession, output_path, session_factory=async_session)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
    finally:
        if claims_file is not None:
            Path(tmp.name).unlink(missing_ok=True)

    output = json.loads(output_path.read_text(encoding="utf-8"))
    return RunClaimsResponse(
        study_accession=output["study_accession"],
        output_path=str(output_path),
        results=output.get("results", []),
    )


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
