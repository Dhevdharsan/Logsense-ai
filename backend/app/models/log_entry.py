from sqlalchemy import BigInteger, String, Text, Boolean, Float, DateTime, Integer, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.database import Base
import datetime

class LogEntry(Base):
    __tablename__ = "log_entries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    template: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list | None] = mapped_column(Vector(384), nullable=True)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("clusters.id"), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cluster: Mapped["Cluster"] = relationship("Cluster", back_populates="log_entries")

    __table_args__ = (
        Index("idx_logs_level_timestamp", "level", "timestamp"),
        Index("idx_logs_service_timestamp", "service", "timestamp"),
        Index("idx_logs_anomalies_only", "is_anomaly", postgresql_where="is_anomaly = TRUE"),
    )
