"""
Deterministic retrieval metrics for the LogSense RAG pipeline.

No LLM is involved here. Given a golden set that maps each question to the set
of chunk IDs that genuinely answer it, these numbers are fully reproducible.
They are the metrics an interviewer will trust most, because nothing about
them depends on a model's opinion.

Conventions used (state these when you publish numbers, because different
papers define them differently):
  * Duplicate chunk IDs in a retrieval result are collapsed before scoring.
  * precision@k divides by the number of chunks actually returned (capped at
    k), not by k itself, so a system that returns 3 chunks when k=5 is not
    penalised for the two it did not return.
  * nDCG uses binary relevance, since the golden set records relevant / not
    relevant rather than graded relevance.
  * Metrics that are undefined for a question (e.g. recall when the question
    is intentionally unanswerable and has no relevant chunks) return None and
    are excluded from the aggregate rather than counted as zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence


def _dedupe(items: Sequence[str]) -> list[str]:
    """Collapse duplicates while preserving rank order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float | None:
    """Fraction of the relevant chunks that appear in the top k.

    Returns None when the question has no relevant chunks (unanswerable), where
    recall is mathematically undefined.
    """
    rel = set(relevant)
    if not rel:
        return None
    top = set(_dedupe(retrieved)[:k])
    return len(top & rel) / len(rel)


def precision_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float | None:
    """Fraction of the returned top-k chunks that are relevant."""
    rel = set(relevant)
    if not rel:
        return None
    top = _dedupe(retrieved)[:k]
    if not top:
        return 0.0
    return len(set(top) & rel) / len(top)


def hit_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float | None:
    """1.0 if at least one relevant chunk made it into the top k."""
    rel = set(relevant)
    if not rel:
        return None
    return 1.0 if set(_dedupe(retrieved)[:k]) & rel else 0.0


def reciprocal_rank(retrieved: Sequence[str], relevant: Iterable[str]) -> float | None:
    """1 / rank of the first relevant chunk. Averaged across questions this is MRR.

    This is the metric that tells you whether your reranking is working: recall
    can be high while the right chunk sits at position 9 and the generator never
    effectively uses it.
    """
    rel = set(relevant)
    if not rel:
        return None
    for rank, chunk_id in enumerate(_dedupe(retrieved), start=1):
        if chunk_id in rel:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float | None:
    """Normalised discounted cumulative gain with binary relevance.

    Rewards putting relevant chunks near the top, unlike recall which treats
    position 1 and position 10 identically.
    """
    rel = set(relevant)
    if not rel:
        return None
    top = _dedupe(retrieved)[:k]
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(top, start=1)
        if chunk_id in rel
    )
    ideal_hits = min(len(rel), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


@dataclass
class RetrievalScores:
    """Per-question retrieval scores. None means 'undefined, exclude from mean'."""

    question_id: str
    recall: float | None
    precision: float | None
    hit: float | None
    rr: float | None
    ndcg: float | None
    k: int
    n_retrieved: int
    n_relevant: int


def score_retrieval(
    question_id: str,
    retrieved: Sequence[str],
    relevant: Iterable[str],
    k: int = 5,
) -> RetrievalScores:
    rel = list(relevant)
    return RetrievalScores(
        question_id=question_id,
        recall=recall_at_k(retrieved, rel, k),
        precision=precision_at_k(retrieved, rel, k),
        hit=hit_at_k(retrieved, rel, k),
        rr=reciprocal_rank(retrieved, rel),
        ndcg=ndcg_at_k(retrieved, rel, k),
        k=k,
        n_retrieved=len(_dedupe(retrieved)),
        n_relevant=len(set(rel)),
    )


def _mean(values: Iterable[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    if not kept:
        return None
    return sum(kept) / len(kept)


@dataclass
class RetrievalSummary:
    k: int
    n_questions_scored: int
    recall_at_k: float | None
    precision_at_k: float | None
    hit_rate_at_k: float | None
    mrr: float | None
    ndcg_at_k: float | None
    per_question: list[RetrievalScores] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "k": self.k,
            "n_questions_scored": self.n_questions_scored,
            f"recall@{self.k}": self.recall_at_k,
            f"precision@{self.k}": self.precision_at_k,
            f"hit_rate@{self.k}": self.hit_rate_at_k,
            "mrr": self.mrr,
            f"ndcg@{self.k}": self.ndcg_at_k,
        }


def summarise_retrieval(scores: Sequence[RetrievalScores], k: int) -> RetrievalSummary:
    scored = [s for s in scores if s.recall is not None]
    return RetrievalSummary(
        k=k,
        n_questions_scored=len(scored),
        recall_at_k=_mean(s.recall for s in scores),
        precision_at_k=_mean(s.precision for s in scores),
        hit_rate_at_k=_mean(s.hit for s in scores),
        mrr=_mean(s.rr for s in scores),
        ndcg_at_k=_mean(s.ndcg for s in scores),
        per_question=list(scores),
    )
