from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Any
from app.config import settings

class LogEntryRequest(BaseModel):
    timestamp: datetime
    level: str
    service: str
    message: str
    metadata: dict[str, Any] | None = None

    @field_validator("level")
    @classmethod
    def validate_level(cls, v):
        allowed = {"ERROR", "WARN", "WARNING", "INFO", "DEBUG"}
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"level must be one of {allowed}")
        return v_upper

    @field_validator("message")
    @classmethod
    def validate_message_length(cls, v):
        if len(v) > settings.max_message_length:
            raise ValueError(f"message too long: {len(v)} chars")
        return v.strip()

    @field_validator("service")
    @classmethod
    def validate_service(cls, v):
        if not v.strip():
            raise ValueError("service name cannot be empty")
        return v.strip().lower()

class LogBatchRequest(BaseModel):
    logs: list[LogEntryRequest] = Field(..., min_length=1, max_length=10000)

class IngestResponse(BaseModel):
    status: str
    ingested_count: int
    job_id: str
    message: str

class LogEntryResponse(BaseModel):
    id: int
    timestamp: datetime
    level: str
    service: str
    message: str
    is_anomaly: bool
    anomaly_score: float | None
    cluster_id: int | None
    created_at: datetime
    model_config = {"from_attributes": True}

class LogListResponse(BaseModel):
    items: list[LogEntryResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
