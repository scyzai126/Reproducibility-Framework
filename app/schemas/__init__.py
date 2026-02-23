from pydantic import BaseModel


class AgentRequest(BaseModel):
    file_path: str


class AgentResponse(BaseModel):
    study_accession: str = ""
    subject_results: list[dict] = []
