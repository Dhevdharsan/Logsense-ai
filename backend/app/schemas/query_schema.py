from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    include_context: bool = Field(
        default=False,
        description="Return the retrieved log lines the generator actually saw. "
        "The eval harness needs this to score faithfulness against real context.",
    )


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class ContextChunk(BaseModel):
    id: str
    text: str
    score: float
    service: str
    level: str


class QueryResponse(BaseModel):
    answer: str
    retrieved_ids: list[str]
    latency_ms: float
    context: list[ContextChunk] | None = None


class RetrieveResponse(BaseModel):
    chunks: list[ContextChunk]
