from pydantic import BaseModel
from datetime import datetime

class ClusterResponse(BaseModel):
    id: int
    label: str | None
    size: int
    sample_messages: list[str] | None
    llm_summary: str | None
    llm_confidence: str | None
    summary_cached_at: datetime | None
    created_at: datetime
    model_config = {"from_attributes": True}

class ClusterListResponse(BaseModel):
    items: list[ClusterResponse]
    total: int

class ServiceErrorCount(BaseModel):
    service: str
    error_count: int

class LogsOverTime(BaseModel):
    hour: datetime
    count: int
    anomalies: int

class DashboardSummary(BaseModel):
    total_logs: int
    anomaly_count: int
    anomaly_rate_pct: float
    cluster_count: int
    top_services: list[ServiceErrorCount]
    logs_over_time: list[LogsOverTime]
    last_analysis_at: datetime | None

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress_pct: int
    logs_processed: int
    anomalies_found: int
    clusters_found: int
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
