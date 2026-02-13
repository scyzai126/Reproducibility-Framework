from pydantic import BaseModel


class AgentRequest(BaseModel):
    file_path: str


class AgentResponse(BaseModel):
    sql: str
    query_results: list[dict]
    enrichments: dict
    summary: str
