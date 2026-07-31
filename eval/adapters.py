"""
THIS IS THE ONLY FILE YOU NEED TO EDIT to wire the harness into LogSense.

Everything else in eval/ is pipeline-agnostic. Fill in the two functions below
so they call your real FastAPI service (or import your retrieval/generation
code directly, if you would rather skip the HTTP hop).

Two rules that matter for the credibility of your numbers:

1. `retrieve` must return chunk IDs from the SAME id space the golden set uses.
   Whatever primary key your pgvector table exposes is the natural choice.
   If your API does not currently return chunk IDs alongside the answer, add
   that -- it is a small change and without it retrieval is unmeasurable.

2. `answer` must return the exact context that was fed to the generator, not a
   fresh retrieval. Faithfulness asks "is this answer grounded in what the
   model actually saw", so re-retrieving here would silently measure the wrong
   thing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

LOGSENSE_BASE_URL = os.getenv("LOGSENSE_BASE_URL", "http://localhost:8000")
REQUEST_TIMEOUT = float(os.getenv("LOGSENSE_TIMEOUT", "60"))


@dataclass
class RagResponse:
    """What the harness needs back from one end-to-end RAG call."""

    answer: str
    context_chunks: list[str]      # the chunk TEXT the generator actually saw
    context_ids: list[str]         # the chunk IDs, in rank order
    latency_ms: float | None = None


def retrieve(question: str, k: int = 5) -> list[str]:
    """Return the top-k chunk IDs for a question, in rank order.

    Replace the body with your real call. Example shape shown below assumes an
    endpoint that returns {"chunks": [{"id": "...", "text": "...", "score": ...}]}.
    """
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        resp = client.post(
            f"{LOGSENSE_BASE_URL}/api/retrieve",
            json={"query": question, "top_k": k},
        )
        resp.raise_for_status()
        payload = resp.json()

    return [str(chunk["id"]) for chunk in payload["chunks"]]


def answer(question: str, k: int = 5) -> RagResponse:
    """Run the full RAG path and return the answer plus the context used.

    Replace the body with your real call. If your current /query endpoint does
    not return the retrieved context, extend it to do so (behind a debug flag
    if you do not want it in the normal response payload).
    """
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        resp = client.post(
            f"{LOGSENSE_BASE_URL}/api/query",
            json={"query": question, "top_k": k, "include_context": True},
        )
        resp.raise_for_status()
        payload = resp.json()

    chunks = payload.get("context", [])
    return RagResponse(
        answer=payload["answer"],
        context_chunks=[c["text"] for c in chunks],
        context_ids=[str(c["id"]) for c in chunks],
        latency_ms=payload.get("latency_ms"),
    )


def health_check() -> bool:
    """Fail fast with a clear message instead of 80 confusing timeouts."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{LOGSENSE_BASE_URL}/health")
            return resp.status_code == 200
    except Exception:
        return False
