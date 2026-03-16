import uuid
import json
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.ml_service import run_pipeline
from app.schemas.cluster_schema import JobStatusResponse, ClusterResponse, ClusterListResponse
from app.models.cluster import Cluster
from sqlalchemy import select
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
    result = await db.execute(
        select(Cluster).order_by(Cluster.size.desc())
    )
    clusters = result.scalars().all()
    return ClusterListResponse(
        items=[ClusterResponse.model_validate(c) for c in clusters],
        total=len(clusters)
    )
