"""
services/llm_service.py — Handles all LLM interactions.

Simple flow:
1. Check Redis cache — if summary exists and is fresh, return it immediately
2. If not cached, build a prompt from cluster's sample messages
3. Send prompt to Ollama (local LLM running on your Mac)
4. Parse the JSON response
5. Save to PostgreSQL + cache in Redis
6. Return the summary

Why cache?
LLM calls take 5-30 seconds even locally.
If 10 users open the dashboard, we don't want 10 LLM calls.
Redis cache means: first call = slow (LLM runs), every call after = instant.
"""
import json
import httpx
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update, select
from app.models.cluster import Cluster
from app.config import settings
from loguru import logger

# This is the prompt template.
# It tells the LLM exactly what role to play and what format to respond in.
SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE).
You analyze software log messages and identify probable root causes.
Rules:
- Only reason from the log messages provided. Do not invent information.
- If you cannot determine root cause, say so honestly.
- Be concise. Maximum 2 sentences per field.
- Respond ONLY with valid JSON. No markdown, no explanation outside JSON."""

USER_PROMPT_TEMPLATE = """Analyze these related log messages from service cluster '{label}':

SAMPLE MESSAGES:
{messages}

CLUSTER SIZE: {size} total log entries

Respond ONLY in this exact JSON format:
{{
  "probable_root_cause": "1-2 sentence diagnosis of what is likely wrong",
  "confidence": "high or medium or low",
  "recommended_actions": ["action 1", "action 2", "action 3"],
  "related_components": ["component 1", "component 2"]
}}"""


async def is_cache_stale(cluster: Cluster) -> bool:
    """
    Returns True if we should regenerate the LLM summary.
    Cache is stale if:
    - No summary exists yet, OR
    - Summary is older than 6 hours
    """
    if cluster.llm_summary is None:
        return True
    if cluster.summary_cached_at is None:
        return True
    age = datetime.now(timezone.utc) - cluster.summary_cached_at.replace(tzinfo=timezone.utc)
    return age > timedelta(seconds=settings.llm_cache_ttl_seconds)


async def get_cached_summary(cluster_id: int) -> dict | None:
    """Check Redis for a cached summary. Returns None if not found."""
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(settings.redis_url)
        data = await r.get(f"llm:cluster:{cluster_id}")
        await r.aclose()
        if data:
            logger.info(f"Cache HIT for cluster {cluster_id}")
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Redis cache check failed: {e}")
    return None


async def cache_summary(cluster_id: int, summary: dict):
    """Save summary to Redis with TTL."""
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(settings.redis_url)
        await r.setex(
            f"llm:cluster:{cluster_id}",
            settings.llm_cache_ttl_seconds,
            json.dumps(summary)
        )
        await r.aclose()
        logger.info(f"Cached summary for cluster {cluster_id}")
    except Exception as e:
        logger.warning(f"Redis cache save failed: {e}")


async def call_ollama(prompt: str) -> str:
    """
    Send a prompt to Ollama and get the response.
    Ollama runs locally on your Mac at port 11434.
    The backend Docker container reaches it via host.docker.internal.
    """
    async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
        response = await client.post(
            f"{settings.ollama_url}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": f"{SYSTEM_PROMPT}\n\n{prompt}",
                "stream": False,   # Wait for complete response
                "format": "json",  # Tell Ollama to return JSON
            }
        )
        response.raise_for_status()
        result = response.json()
        return result.get("response", "")


def parse_llm_response(raw: str) -> dict:
    """
    Safely parse LLM JSON response.
    If parsing fails, return a safe fallback instead of crashing.
    """
    try:
        # Strip any markdown code fences the LLM might add
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1])
        parsed = json.loads(clean)
        # Validate required fields exist
        return {
            "probable_root_cause": parsed.get("probable_root_cause", "Unable to determine"),
            "confidence": parsed.get("confidence", "low"),
            "recommended_actions": parsed.get("recommended_actions", []),
            "related_components": parsed.get("related_components", []),
        }
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to parse LLM response: {e}")
        return {
            "probable_root_cause": "LLM response could not be parsed",
            "confidence": "low",
            "recommended_actions": ["Review logs manually"],
            "related_components": [],
        }


async def summarize_cluster(
    db: AsyncSession,
    cluster_id: int,
    force_refresh: bool = False
) -> dict:
    """
    Main function — get or generate LLM summary for a cluster.

    1. Load cluster from DB
    2. Check Redis cache
    3. If cache hit → return immediately
    4. If cache miss → call Ollama → save result → return
    """
    # Load cluster
    result = await db.execute(select(Cluster).where(Cluster.id == cluster_id))
    cluster = result.scalar_one_or_none()
    if not cluster:
        raise ValueError(f"Cluster {cluster_id} not found")

    # Check cache first (unless force refresh requested)
    if not force_refresh:
        cached = await get_cached_summary(cluster_id)
        if cached:
            return {**cached, "from_cache": True}

    # Check if DB cache is still fresh
    if not force_refresh and not await is_cache_stale(cluster):
        return {
            "probable_root_cause": cluster.llm_summary,
            "confidence": cluster.llm_confidence or "medium",
            "recommended_actions": [],
            "related_components": [],
            "from_cache": True,
        }

    # Cache miss — call Ollama
    logger.info(f"Generating LLM summary for cluster {cluster_id}: {cluster.label}")

    sample_messages = cluster.sample_messages or []
    if not sample_messages:
        return {
            "probable_root_cause": "No sample messages available for this cluster",
            "confidence": "low",
            "recommended_actions": [],
            "related_components": [],
            "from_cache": False,
        }

    # Build the prompt
    messages_text = "\n".join(f"- {m}" for m in sample_messages[:settings.llm_max_sample_logs])
    prompt = USER_PROMPT_TEMPLATE.format(
        label=cluster.label or f"cluster-{cluster_id}",
        messages=messages_text,
        size=cluster.size,
    )

    try:
        raw_response = await call_ollama(prompt)
        summary = parse_llm_response(raw_response)
    except httpx.ConnectError:
        logger.error("Cannot connect to Ollama — is it running? Run: ollama serve")
        return {
            "probable_root_cause": "LLM unavailable — Ollama is not running. Start it with: ollama serve",
            "confidence": "low",
            "recommended_actions": ["Start Ollama: ollama serve", "Then pull model: ollama pull llama3"],
            "related_components": [],
            "from_cache": False,
        }
    except Exception as e:
        logger.error(f"Ollama call failed: {e}")
        return {
            "probable_root_cause": f"LLM call failed: {str(e)}",
            "confidence": "low",
            "recommended_actions": [],
            "related_components": [],
            "from_cache": False,
        }

    # Save to PostgreSQL
    await db.execute(
        update(Cluster)
        .where(Cluster.id == cluster_id)
        .values(
            llm_summary=summary["probable_root_cause"],
            llm_confidence=summary["confidence"],
            summary_cached_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    # Save to Redis cache
    await cache_summary(cluster_id, summary)

    logger.info(f"Summary generated for cluster {cluster_id} — confidence: {summary['confidence']}")
    return {**summary, "from_cache": False}
