import time
import json
from datetime import datetime, timezone
from sqlalchemy import select, insert, delete, update
from app.database import AsyncSessionLocal
from app.models.log_entry import LogEntry
from app.models.cluster import Cluster, AnomalyRun
from app.ml.preprocessor import LogPreprocessor
from app.ml.anomaly_detector import AnomalyDetector, run_anomaly_detection
from app.ml.clusterer import LogClusterer, save_clusters
from app.config import settings
from loguru import logger

async def update_job_status(job_id: str, update_data: dict):
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(settings.redis_url)
        existing = await r.get(f"job:{job_id}")
        if existing:
            status = json.loads(existing)
            status.update(update_data)
            await r.setex(f"job:{job_id}", 3600, json.dumps(status))
        else:
            await r.setex(f"job:{job_id}", 3600, json.dumps(update_data))
        await r.aclose()
    except Exception as e:
        logger.warning(f"Redis update failed: {e}")

async def run_pipeline(log_ids=None, job_id="manual"):
    start_time = time.time()
    logger.info(f"ML pipeline starting — job_id={job_id}")
    await update_job_status(job_id, {"status": "processing", "progress_pct": 5})

    async with AsyncSessionLocal() as db:
        if log_ids:
            result = await db.execute(select(LogEntry).where(LogEntry.id.in_(log_ids)))
        else:
            result = await db.execute(select(LogEntry))

        logs = result.scalars().all()

        if len(logs) < 10:
            logger.warning(f"Only {len(logs)} logs — need at least 10")
            await update_job_status(job_id, {"status": "failed", "error": "Not enough logs"})
            return

        logger.info(f"Processing {len(logs)} logs")
        messages = [log.message for log in logs]
        db_log_ids = [log.id for log in logs]

        await update_job_status(job_id, {"progress_pct": 20, "logs_processed": len(logs)})

        # Step 1: Preprocess
        preprocessor = LogPreprocessor(max_features=settings.tfidf_max_features)
        vectors, templates = preprocessor.fit_transform(messages)
        for i, log in enumerate(logs):
            log.template = templates[i]
        await db.commit()

        await update_job_status(job_id, {"progress_pct": 40})

        # Step 2: Anomaly detection
        detector = AnomalyDetector()
        labels, scores = detector.fit_predict(vectors)
        anomaly_count = await run_anomaly_detection(db, db_log_ids, vectors, labels, scores)

        await update_job_status(job_id, {"progress_pct": 70, "anomalies_found": anomaly_count})

        # Step 3: Clustering — clear old clusters first
        # Must clear foreign key references in log_entries BEFORE deleting clusters
        await db.execute(update(LogEntry).values(cluster_id=None))
        await db.commit()
        await db.execute(delete(Cluster))
        await db.commit()

        clusterer = LogClusterer()
        cluster_labels = clusterer.fit_predict(vectors)
        clusters_created = await save_clusters(db, db_log_ids, templates, vectors, cluster_labels)

        await update_job_status(job_id, {"progress_pct": 90, "clusters_found": clusters_created})

        # Step 4: Record the run
        duration = time.time() - start_time
        await db.execute(
            insert(AnomalyRun).values(
                logs_processed=len(logs),
                anomalies_found=anomaly_count,
                clusters_found=clusters_created,
                status="completed",
                duration_seconds=round(duration, 2),

            )
        )
        await db.commit()

        await update_job_status(job_id, {
            "status": "completed",
            "progress_pct": 100,
            "completed_at": datetime.now(timezone.utc).isoformat()
        })

        logger.info(f"Pipeline done in {duration:.1f}s — {anomaly_count} anomalies, {clusters_created} clusters")
        return {"anomalies": anomaly_count, "clusters": clusters_created}

async def run_scheduled_pipeline():
    await run_pipeline(log_ids=None, job_id="scheduled")
