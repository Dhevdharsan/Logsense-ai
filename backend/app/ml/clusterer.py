import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import normalize
from sqlalchemy import update, insert
from app.models.log_entry import LogEntry
from app.models.cluster import Cluster
from app.config import settings
from loguru import logger

class LogClusterer:
    def __init__(self):
        self.eps = settings.dbscan_eps
        self.min_samples = settings.dbscan_min_samples

    def fit_predict(self, vectors: np.ndarray) -> np.ndarray:
        logger.info(f"Running DBSCAN on {len(vectors)} vectors")
        normalized = normalize(vectors, norm="l2")
        db = DBSCAN(
            eps=self.eps,
            min_samples=self.min_samples,
            metric="cosine",
            n_jobs=-1,
        )
        cluster_labels = db.fit_predict(normalized)
        n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
        n_noise = (cluster_labels == -1).sum()
        logger.info(f"Found {n_clusters} clusters, {n_noise} noise points")
        return cluster_labels


async def save_clusters(db, log_ids, messages, vectors, cluster_labels):
    unique_labels = set(cluster_labels)
    unique_labels.discard(-1)

    if not unique_labels:
        logger.warning("No clusters found")
        return 0

    clusters_created = 0
    for label in sorted(unique_labels):
        member_indices = np.where(cluster_labels == label)[0]
        member_log_ids = [log_ids[i] for i in member_indices]
        member_messages = [messages[i] for i in member_indices]
        member_vectors = vectors[member_indices]

        # Convert centroid to plain Python list for pgvector
        centroid = member_vectors.mean(axis=0).astype(float).tolist()

        # Pick up to 5 unique sample messages
        seen = set()
        sample_messages = []
        for m in member_messages:
            if m not in seen:
                seen.add(m)
                sample_messages.append(m)
            if len(sample_messages) == 5:
                break

        # Build auto label from top 3 most frequent meaningful words
        all_words = " ".join(member_messages).lower().split()
        stopwords = {"the", "a", "an", "at", "in", "on", "for", "to", "of",
                     "is", "was", "get", "usr", "req", "api", "http"}
        meaningful = [w for w in all_words if w not in stopwords and len(w) > 3]
        freq = {}
        for w in meaningful:
            freq[w] = freq.get(w, 0) + 1
        top_words = sorted(freq, key=freq.get, reverse=True)[:3]
        auto_label = " + ".join(top_words) if top_words else f"cluster-{label}"

        # Insert cluster — no centroid for now to avoid pgvector type issues
        result = await db.execute(
            insert(Cluster).values(
                label=auto_label,
                centroid=None,
                size=len(member_log_ids),
                sample_messages=sample_messages,
                llm_summary=None,
            ).returning(Cluster.id)
        )
        cluster_db_id = result.scalar_one()

        # Update all member logs with this cluster_id
        for log_id in member_log_ids:
            await db.execute(
                update(LogEntry)
                .where(LogEntry.id == log_id)
                .values(cluster_id=cluster_db_id)
            )

        clusters_created += 1
        logger.info(f"Cluster {cluster_db_id}: '{auto_label}' size={len(member_log_ids)}")

    await db.commit()
    logger.info(f"Saved {clusters_created} clusters")
    return clusters_created
