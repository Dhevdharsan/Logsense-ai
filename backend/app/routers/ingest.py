import uuid
from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.log_schema import LogBatchRequest, IngestResponse, LogListResponse, LogEntryResponse
from app.services.ingest_service import bulk_insert_logs, get_logs_paginated
from loguru import logger

router = APIRouter(prefix="/api/v1/logs", tags=["Log Ingestion"])

@router.post("/ingest", response_model=IngestResponse, status_code=202)
async def ingest_logs(payload: LogBatchRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    logger.info(f"Ingest request: {len(payload.logs)} logs, job_id={job_id}")
    inserted_ids = await bulk_insert_logs(db, payload.logs)
    background_tasks.add_task(_store_job_status, job_id, len(inserted_ids))
    return IngestResponse(status="accepted", ingested_count=len(inserted_ids), job_id=job_id, message=f"Accepted {len(inserted_ids)} logs.")

@router.get("", response_model=LogListResponse)
async def list_logs(db: AsyncSession = Depends(get_db), page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=500), level: str | None = None, service: str | None = None, anomalies_only: bool = False):
    logs, total = await get_logs_paginated(db, page=page, page_size=page_size, level=level, service=service, anomalies_only=anomalies_only)
    return LogListResponse(items=[LogEntryResponse.model_validate(log) for log in logs], total=total, page=page, page_size=page_size, has_next=(page * page_size) < total)

async def _store_job_status(job_id: str, log_count: int):
    try:
        import redis.asyncio as aioredis
        from app.config import settings
        import json
        from datetime import datetime, timezone
        r = await aioredis.from_url(settings.redis_url)
        status = {"job_id": job_id, "status": "pending", "progress_pct": 0, "logs_processed": 0, "anomalies_found": 0, "clusters_found": 0, "error": None, "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None}
        await r.setex(f"job:{job_id}", 3600, json.dumps(status))
        await r.aclose()
    except Exception as e:
        logger.error(f"Failed to store job status: {e}")
