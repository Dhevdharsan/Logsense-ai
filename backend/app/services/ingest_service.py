from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert, select, func
from app.models.log_entry import LogEntry
from app.schemas.log_schema import LogEntryRequest
from loguru import logger

async def bulk_insert_logs(db: AsyncSession, logs: list[LogEntryRequest]) -> list[int]:
    if not logs:
        return []
    rows = []
    for log in logs:
        raw = {
            "timestamp": log.timestamp.isoformat(),
            "level": log.level,
            "service": log.service,
            "message": log.message,
            "metadata": log.metadata or {},
        }
        rows.append({
            "timestamp": log.timestamp,
            "level": log.level,
            "service": log.service,
            "message": log.message,
            "raw_data": raw,
            "template": None,
            "embedding": None,
            "is_anomaly": False,
            "anomaly_score": None,
            "cluster_id": None,
        })
    result = await db.execute(insert(LogEntry).returning(LogEntry.id), rows)
    inserted_ids = [row[0] for row in result.fetchall()]
    logger.info(f"Bulk inserted {len(inserted_ids)} log entries")
    return inserted_ids

async def get_logs_paginated(db, page=1, page_size=50, level=None, service=None, anomalies_only=False):
    query = select(LogEntry)
    count_query = select(func.count(LogEntry.id))
    if level:
        query = query.where(LogEntry.level == level.upper())
        count_query = count_query.where(LogEntry.level == level.upper())
    if service:
        query = query.where(LogEntry.service == service.lower())
        count_query = count_query.where(LogEntry.service == service.lower())
    if anomalies_only:
        query = query.where(LogEntry.is_anomaly == True)
        count_query = count_query.where(LogEntry.is_anomaly == True)
    query = query.order_by(LogEntry.timestamp.desc())
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    count_result = await db.execute(count_query)
    return list(result.scalars().all()), count_result.scalar_one()
