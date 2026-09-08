from pydantic import BaseModel


class TextRequest(BaseModel):
    message: str


class FailedFieldCount(BaseModel):
    field: str
    count: int


class CompletnessSummary(BaseModel):
    total_claims: int = 0
    claims_with_failures: int = 0
    failed_groups: int = 0
    failed_fields: list[FailedFieldCount] = []


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
    # Populated when the backend needs more information from the user
    type: str | None = None
    question: str | None = None
    # ImmPort field resolution completeness summary
    completeness: CompletnessSummary | None = None


class AssayRequest(BaseModel):
    """Ask what assays a paper used. At least one identifier is required.

    `verify` and `correct` default on: the point of the endpoint is to return the accurate
    registry, and an unverified one cannot be told apart from a verified one by the reader --
    a `platform` inferred from what a technique usually runs on looks exactly like one copied
    from Methods. Turn them off only to inspect an intermediate round.

    Every request runs all three rounds and costs 1 + N + F model calls; nothing is served
    from a previous run.
    """

    study_accession: str = ""
    pubmed_id: str = ""
    verify: bool = True
    correct: bool = True


class AssayResponse(BaseModel):
    study_accession: str = ""
    pubmed_id: str = ""
    paper_title: str = ""
    paper_source: str = ""
    #: name_in_paper -> the seven-field entry: the CORRECTED registry, as assays.json holds it.
    assays: dict = {}
    #: The free verbatim-quote check. Always present.
    quote_check: dict = {}
    #: build_report() output, or null when verify was false or the paper has no assays.
    verification: dict | None = None
    #: assay id -> {entry, reason} for assays round 3 set aside as never performed.
    dropped: dict = {}
    #: What each of the three rounds did, and what it cost.
    rounds: dict = {}
    #: Entries that broke the extraction contract; report these, do not skim them.
    contract_warnings: list[str] = []
    #: Where the registry and report came from, and what the request actually cost.
    meta: dict = {}

