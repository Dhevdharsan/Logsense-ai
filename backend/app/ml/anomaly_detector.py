import numpy as np
from sklearn.ensemble import IsolationForest
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

    def fit_predict(self, vectors: np.ndarray):
        logger.info(f"Running Isolation Forest on {len(vectors)} vectors (scores only)")
        self.model.fit(vectors)
        scores = -self.model.decision_function(vectors)
        return scores


def flag_by_rarity(cluster_labels: np.ndarray, total_logs: int, rarity_pct: float) -> np.ndarray:
    """
    Returns a boolean array (True = anomalous) based on cluster frequency.

    A log is anomalous when:
    - DBSCAN marked it as noise (label == -1) — it didn't fit any cluster, OR
    - Its cluster appears fewer than `absolute_floor` times (genuine one-offs), OR
    - Its cluster is both small in absolute terms AND rare relative to the dataset

    Using a pure percentage breaks down on large datasets: 2% of 5000 logs = 100,
    which ends up larger than every ERROR cluster even when those clusters have
    80+ copies of the same message. The floor caps the threshold so that a cluster
    with 87 identical errors is never flagged just because INFO logs dominate.
    """
    is_anomaly = np.zeros(len(cluster_labels), dtype=bool)

    # Noise points: DBSCAN couldn't find neighbours — always anomalous
    is_anomaly[cluster_labels == -1] = True

    pct_threshold = (rarity_pct / 100.0) * total_logs
    # Cap at absolute_floor so a large INFO-heavy dataset doesn't push the
    # threshold above clusters that are clearly recurring known patterns.
    absolute_floor = settings.anomaly_absolute_floor
    threshold = min(pct_threshold, absolute_floor)

    flagged_clusters = 0
    for label in set(cluster_labels) - {-1}:
        mask = cluster_labels == label
        if mask.sum() < threshold:
            is_anomaly[mask] = True
            flagged_clusters += 1

    anomaly_count = int(is_anomaly.sum())
    logger.info(
        f"Frequency-based flagging: {anomaly_count}/{total_logs} anomalous "
        f"({flagged_clusters} rare clusters, threshold: <{threshold:.1f} logs "
        f"[min of {pct_threshold:.1f} pct-based, {absolute_floor} floor])"
    )
    return is_anomaly


async def run_anomaly_detection(db, log_ids, is_anomaly_flags: np.ndarray, scores: np.ndarray):
    anomaly_count = 0
    for i, log_id in enumerate(log_ids):
        is_anomaly = bool(is_anomaly_flags[i])
        if is_anomaly:
            anomaly_count += 1
        await db.execute(
            update(LogEntry)
            .where(LogEntry.id == log_id)
            .values(is_anomaly=is_anomaly, anomaly_score=float(scores[i]))
        )
    await db.commit()
    logger.info(f"Updated {len(log_ids)} logs with anomaly flags")
    return anomaly_count
