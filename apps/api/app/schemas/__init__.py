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
    comparison: list = []
    subject_results: list[SubjectResult] = []


class ParsePaperRequest(BaseModel):
    study_accession: str


class ParsePaperResponse(BaseModel):
    study_accession: str
    assay_methods: list[str] = []
    claims: dict = {}
    groups: dict = {}


class RunClaimsRequest(BaseModel):
    study_accession: str


class RunClaimsGroupResult(BaseModel):
    group_id: str
    input_filters: dict = {}
    resolved_params: dict = {}
    subjects: list[str] = []
    experiment_count: int = 0
    subject_count: int = 0
    error: str | None = None


class RunClaimsClaimResult(BaseModel):
    claim: str = ""
    comparison_strategy: str = ""
    comparison: list = []
    groups: list[RunClaimsGroupResult] = []


class RunClaimsResponse(BaseModel):
    study_accession: str
    output_path: str
    results: list[RunClaimsClaimResult] = []


class AgentResponse(BaseModel):
    study_accession: str = ""
    # Populated for claims-based JSON (new format)
    claims: list[ClaimResult] = []
    # Populated for PDF + question mode: step-1 claim sentences from the paper
    paper_claims: list[dict] = []
    # Populated for legacy signature / plain-text / question input
    subject_results: list[dict] = []
    # Populated when the backend needs more information from the user
    type: str | None = None
    question: str | None = None
