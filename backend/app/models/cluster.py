from sqlalchemy import String, Text, Integer, DateTime, Float, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.database import Base
import datetime

class Cluster(Base):
    __tablename__ = "clusters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    centroid: Mapped[list | None] = mapped_column(Vector(384), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    sample_messages: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    summary_cached_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    log_entries: Mapped[list["LogEntry"]] = relationship("LogEntry", back_populates="cluster")

class AnomalyRun(Base):
    __tablename__ = "anomaly_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    logs_processed: Mapped[int] = mapped_column(Integer, default=0)
    anomalies_found: Mapped[int] = mapped_column(Integer, default=0)
    clusters_found: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
