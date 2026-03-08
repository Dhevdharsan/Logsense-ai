from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from app.database import get_db
from app.models.log_entry import LogEntry
from app.models.cluster import Cluster, AnomalyRun
from app.schemas.cluster_schema import DashboardSummary, ServiceErrorCount, LogsOverTime

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])

@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    total_logs = (await db.execute(select(func.count(LogEntry.id)))).scalar_one() or 0
    anomaly_count = (await db.execute(select(func.count(LogEntry.id)).where(LogEntry.is_anomaly == True))).scalar_one() or 0
    cluster_count = (await db.execute(select(func.count(Cluster.id)))).scalar_one() or 0
    top_services_result = await db.execute(
        select(LogEntry.service, func.count(LogEntry.id).label("error_count"))
        .where(LogEntry.level == "ERROR").group_by(LogEntry.service)
        .order_by(func.count(LogEntry.id).desc()).limit(5)
    )
    top_services = [ServiceErrorCount(service=r.service, error_count=r.error_count) for r in top_services_result.fetchall()]
    timeline_result = await db.execute(text("""
        SELECT date_trunc('hour', timestamp) as hour, COUNT(*) as count,
               SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END) as anomalies
        FROM log_entries WHERE timestamp > NOW() - INTERVAL '24 hours'
        GROUP BY hour ORDER BY hour ASC
    """))
    logs_over_time = [LogsOverTime(hour=r.hour, count=r.count, anomalies=r.anomalies or 0) for r in timeline_result.fetchall()]
    last_run = (await db.execute(select(AnomalyRun.run_at).where(AnomalyRun.status == "completed").order_by(AnomalyRun.run_at.desc()).limit(1))).scalar_one_or_none()
    return DashboardSummary(
        total_logs=total_logs, anomaly_count=anomaly_count,
        anomaly_rate_pct=round((anomaly_count / total_logs * 100), 2) if total_logs > 0 else 0.0,
        cluster_count=cluster_count, top_services=top_services,
        logs_over_time=logs_over_time, last_analysis_at=last_run,
    )
