"""
RAG query endpoints, consumed by the evaluation harness (eval/adapters.py).

Paths are deliberately mounted under /api (not /api/v1) to match the stable
contract the harness expects:
  POST /api/retrieve  -> chunk ids only        (retrieval metrics, no LLM cost)
  POST /api/query     -> answer (+ context)    (generation / faithfulness metrics)
"""
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.query_schema import (
    ContextChunk,
    QueryRequest,
    QueryResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from app.services.rag_service import answer_query, retrieve_chunks

router = APIRouter(prefix="/api", tags=["RAG Query"])


def _as_context(chunks) -> list[ContextChunk]:
    return [
        ContextChunk(id=c.id, text=c.text, score=c.score, service=c.service, level=c.level)
        for c in chunks
    ]


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(payload: RetrieveRequest, db: AsyncSession = Depends(get_db)):
    """Top-k chunk ids for a question. No LLM call -- free and deterministic."""
    try:
        chunks = await retrieve_chunks(db, payload.query, k=payload.top_k)
    except FileNotFoundError as e:
        # No pipeline has run yet, so there is no shared embedding space to search.
        raise HTTPException(status_code=503, detail=str(e))
    return RetrieveResponse(chunks=_as_context(chunks))


@router.post("/query", response_model=QueryResponse)
async def query(payload: QueryRequest, db: AsyncSession = Depends(get_db)):
    """Full RAG answer. Set include_context=true to get the exact context used."""
    try:
        result = await answer_query(db, payload.query, k=payload.top_k)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return QueryResponse(
        answer=result.answer,
        retrieved_ids=[c.id for c in result.chunks],
        latency_ms=result.latency_ms,
        context=_as_context(result.chunks) if payload.include_context else None,
    )
