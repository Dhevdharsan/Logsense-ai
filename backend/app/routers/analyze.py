import uuid
import json
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.ml_service import run_pipeline
from app.schemas.cluster_schema import JobStatusResponse, ClusterResponse, ClusterListResponse
from app.models.cluster import Cluster
from app.models.log_entry import LogEntry
from sqlalchemy import select, func, case
from app.config import settings
from loguru import logger

router = APIRouter(prefix="/api/v1", tags=["Analysis"])


@router.post("/analyze/run")
async def trigger_analysis(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    logger.info(f"Analysis triggered — job_id={job_id}")
    background_tasks.add_task(run_pipeline, log_ids=None, job_id=job_id)
    return {
        "job_id": job_id,
        "status": "started",
        "message": "ML pipeline running in background"
    }


@router.get("/analyze/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(settings.redis_url)
        data = await r.get(f"job:{job_id}")
        await r.aclose()
        if data:
            status = json.loads(data)
            return JobStatusResponse(**status)
    except Exception as e:
        logger.warning(f"Redis read failed: {e}")

    from datetime import datetime, timezone
    return JobStatusResponse(
        job_id=job_id,
        status="unknown",
        progress_pct=0,
        logs_processed=0,
        anomalies_found=0,
        clusters_found=0,
        error="Status unavailable",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
    )


@router.get("/clusters", response_model=ClusterListResponse)
async def list_clusters(db: AsyncSession = Depends(get_db)):
    anomaly_sq = (
        select(
            LogEntry.cluster_id,
            func.count(LogEntry.id).label("total"),
            func.sum(case((LogEntry.is_anomaly == True, 1), else_=0)).label("anomaly_count"),
        )
        .where(LogEntry.cluster_id.isnot(None))
        .group_by(LogEntry.cluster_id)
        .subquery()
    )
    result = await db.execute(
        select(Cluster, anomaly_sq.c.anomaly_count, anomaly_sq.c.total)
        .outerjoin(anomaly_sq, Cluster.id == anomaly_sq.c.cluster_id)
        .order_by(Cluster.size.desc())
    )
    rows = result.all()
    items = []
    for cluster, anomaly_count, total in rows:
        anom_count = int(anomaly_count or 0)
        anom_total = int(total or 0)
        anom_pct = round((anom_count / anom_total * 100) if anom_total > 0 else 0.0, 1)
        items.append(ClusterResponse(
            id=cluster.id,
            label=cluster.label,
            size=cluster.size,
            sample_messages=cluster.sample_messages,
            llm_summary=cluster.llm_summary,
            llm_confidence=cluster.llm_confidence,
            summary_cached_at=cluster.summary_cached_at,
            created_at=cluster.created_at,
            anomaly_count=anom_count,
            anomaly_pct=anom_pct,
        ))
    return ClusterListResponse(items=items, total=len(items))
