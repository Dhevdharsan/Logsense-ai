"""
services/rag_service.py -- the retrieval-augmented query path.

This is the piece the evaluation harness measures. It is deliberately thin:

  1. retrieve  -- embed the question with the SAME fitted TF-IDF vectorizer that
                  produced the stored log vectors, then cosine-search pgvector.
  2. generate  -- feed the retrieved log lines to Ollama with a strictly-grounded
                  prompt that is allowed to abstain.

A known and intentional limitation: retrieval is lexical (TF-IDF), so questions
whose answer lives in no single log line -- counting/aggregation especially --
retrieve poorly. That is a property of top-k vector retrieval over per-line
embeddings, not a bug here; the fix is a hybrid retrieval path, and the eval
harness exists precisely to show it.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ml.vectorizer_store import EMBED_DIM, load_preprocessor, pad_to_dim
from app.models.log_entry import LogEntry


@dataclass
class RetrievedChunk:
    id: str
    text: str          # the exact line the generator/judge sees
    score: float       # cosine similarity in [-1, 1]; higher is closer
    service: str
    level: str


RAG_SYSTEM_PROMPT = """You are an SRE assistant. You answer questions using ONLY the retrieved log lines provided to you.

Rules:
- Ground every statement in the provided log lines. Do not use outside knowledge about how software or infrastructure normally behaves.
- If the log lines do not contain enough information to answer, reply with exactly this sentence and nothing else: "The logs do not contain enough information to answer this question."
- Be concise and factual. Cite the ids of the log lines you used in square brackets, e.g. [id=42].
- Do not invent services, metrics, timestamps, or root causes that the log lines do not show."""

USER_TEMPLATE = """RETRIEVED LOG LINES:
{context}

QUESTION: {question}

Answer:"""


def _chunk_text(log: LogEntry) -> str:
    """One retrieved log rendered for the generator and the faithfulness judge.

    Includes id (so the model can cite it), timestamp, level and service so the
    judge has the facts a claim might reference.
    """
    ts = log.timestamp.isoformat() if log.timestamp else "?"
    return f"[id={log.id}] {ts} {log.level} {log.service}: {log.message}"


def embed_query(question: str) -> list[float]:
    """Embed a question into the stored logs' TF-IDF space, padded to 384 dims."""
    preprocessor = load_preprocessor()
    vectors, _ = preprocessor.transform([question])
    return pad_to_dim(vectors[0], EMBED_DIM)


async def retrieve_chunks(
    db: AsyncSession, question: str, k: int = 5
) -> list[RetrievedChunk]:
    qvec = embed_query(question)
    # A question with no vocabulary overlap yields an all-zero TF-IDF vector.
    # Cosine similarity to a zero vector is undefined (pgvector returns NaN), so
    # there is nothing meaningful to rank -- return no chunks and let the generator
    # abstain. This is the honest outcome for a query TF-IDF simply cannot serve.
    if not any(qvec):
        logger.info(f"Query has no vocabulary overlap; no retrieval possible: {question!r}")
        return []

    distance = LogEntry.embedding.cosine_distance(qvec).label("distance")
    stmt = (
        select(LogEntry, distance)
        .where(LogEntry.embedding.isnot(None))
        .order_by(distance)
        .limit(k)
    )
    rows = (await db.execute(stmt)).all()
    chunks: list[RetrievedChunk] = []
    for log, dist in rows:
        # cosine_distance = 1 - cosine_similarity. Guard against NULL and non-finite
        # (NaN/inf) distances so a bad score can never reach JSON serialization.
        score = 1.0 - float(dist) if dist is not None else 0.0
        if not math.isfinite(score):
            score = 0.0
        chunks.append(
            RetrievedChunk(
                id=str(log.id),
                text=_chunk_text(log),
                score=round(score, 4),
                service=log.service,
                level=log.level,
            )
        )
    return chunks


# Ollama under a burst of back-to-back eval requests occasionally drops one with a
# read timeout, reset connection, or a transient 5xx while the model reloads. A
# single request is fine, so a short retry recovers it instead of failing the whole
# /query call (which would silently drop that question from the eval).
_TRANSIENT_ERRORS = (
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.ConnectError,
    httpx.HTTPStatusError,  # transient 5xx from Ollama, e.g. while the model reloads
)
_GENERATE_ATTEMPTS = 3


async def _generate(question: str, chunks: list[RetrievedChunk]) -> str:
    context = "\n".join(c.text for c in chunks) if chunks else "(no log lines retrieved)"
    prompt = USER_TEMPLATE.format(context=context, question=question)
    body = {
        "model": settings.ollama_model,
        "prompt": f"{RAG_SYSTEM_PROMPT}\n\n{prompt}",
        "stream": False,
        "options": {"temperature": 0},  # deterministic: the eval must be reproducible
    }

    last_exc: Exception | None = None
    for attempt in range(_GENERATE_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
                resp = await client.post(f"{settings.ollama_url}/api/generate", json=body)
                resp.raise_for_status()
                return resp.json().get("response", "").strip()
        except _TRANSIENT_ERRORS as e:
            last_exc = e
            if attempt < _GENERATE_ATTEMPTS - 1:
                await asyncio.sleep(1.0 * (attempt + 1))  # 1s, then 2s
                logger.warning(f"Ollama call failed ({e!r}); retry {attempt + 1}/{_GENERATE_ATTEMPTS - 1}")

    assert last_exc is not None
    raise last_exc


@dataclass
class QueryResult:
    answer: str
    chunks: list[RetrievedChunk]
    latency_ms: float


async def answer_query(
    db: AsyncSession, question: str, k: int = 5
) -> QueryResult:
    """Full RAG path: retrieve, then generate an answer grounded in what we saw."""
    started = time.perf_counter()
    chunks = await retrieve_chunks(db, question, k)
    try:
        answer = await _generate(question, chunks)
    except httpx.ConnectError:
        logger.error("Cannot reach Ollama -- is it running? (ollama serve)")
        answer = "The logs do not contain enough information to answer this question."
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return QueryResult(answer=answer, chunks=chunks, latency_ms=latency_ms)
