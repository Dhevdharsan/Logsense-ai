import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from app.models.log_entry import LogEntry
from app.config import settings
from loguru import logger

class AnomalyDetector:
    def __init__(self):
        self.model = IsolationForest(
            contamination=settings.anomaly_contamination,
            random_state=42,
            n_estimators=100,
            max_samples="auto",
        )
        self.is_fitted = False

    def fit_predict(self, vectors: np.ndarray):
        logger.info(f"Running Isolation Forest on {len(vectors)} vectors")
        labels = self.model.fit_predict(vectors)
        scores = -self.model.decision_function(vectors)
        self.is_fitted = True
        anomaly_count = (labels == -1).sum()
        logger.info(f"Found {anomaly_count} anomalies ({anomaly_count/len(vectors)*100:.1f}%)")
        return labels, scores

async def run_anomaly_detection(db, log_ids, vectors, labels, scores):
    anomaly_count = 0
    for i, log_id in enumerate(log_ids):
        is_anomaly = bool(labels[i] == -1)
        if is_anomaly:
            anomaly_count += 1
        await db.execute(
            update(LogEntry)
            .where(LogEntry.id == log_id)
            .values(is_anomaly=is_anomaly, anomaly_score=float(scores[i]))
        )
    await db.commit()
    logger.info(f"Updated {len(log_ids)} logs with anomaly scores")
    return anomaly_count
