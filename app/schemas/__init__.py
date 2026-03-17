from pydantic import BaseModel


class AgentRequest(BaseModel):
    file_path: str


class TextRequest(BaseModel):
    message: str


class SubjectResult(BaseModel):
    group_id: int = 0
    resolvers: dict = {}
    comparison: list = []
    subjects: list[dict] = []
    error: str | None = None


class ClaimResult(BaseModel):
    claim_id: int
    claim_text: str = ""
    source: dict = {}
    study_design: str | None = None
    subject_results: list[SubjectResult] = []


class AgentResponse(BaseModel):
    study_accession: str = ""
    # Populated for claims-based JSON (new format)
    claims: list[ClaimResult] = []
    # Populated for legacy signature / plain-text input
    subject_results: list[dict] = []
