from pydantic import BaseModel


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


class ParsePaperRequest(BaseModel):
    study_accession: str


class ParsePaperResponse(BaseModel):
    study_accession: str
    assay_methods: list[str] = []
    claims_sentence: dict = {}
    claims_group: dict = {}


class AgentResponse(BaseModel):
    study_accession: str = ""
    # Populated for claims-based JSON (new format)
    claims: list[ClaimResult] = []
    # Populated for PDF + question mode: step-1 claim sentences from the paper
    paper_claims: list[dict] = []
    # Populated for legacy signature / plain-text / question input
    subject_results: list[dict] = []
