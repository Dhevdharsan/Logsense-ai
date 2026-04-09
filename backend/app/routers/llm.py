from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.llm_service import summarize_cluster
from app.schemas.cluster_schema import LLMSummarizeResponse
from loguru import logger

router = APIRouter(prefix="/api/v1/llm", tags=["LLM"])


@router.post("/summarize/{cluster_id}", response_model=LLMSummarizeResponse)
async def get_cluster_summary(
    cluster_id: int,
    force_refresh: bool = Query(default=False, description="Force regenerate even if cached"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get or generate an LLM root cause summary for a cluster.

    - First call: slow (Ollama generates the summary, ~5-30 seconds)
    - Subsequent calls: instant (returned from Redis cache)
    - force_refresh=true: regenerate even if cached
    """
    try:
        summary = await summarize_cluster(db, cluster_id, force_refresh=force_refresh)
        return LLMSummarizeResponse(
            cluster_id=cluster_id,
            probable_root_cause=summary["probable_root_cause"],
            confidence=summary["confidence"],
            recommended_actions=summary.get("recommended_actions", []),
            related_components=summary.get("related_components", []),
            from_cache=summary.get("from_cache", False),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Summary failed for cluster {cluster_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/summarize-all")
async def summarize_all_clusters(db: AsyncSession = Depends(get_db)):
    """
    Generate summaries for ALL clusters that don't have one yet.
    Runs sequentially to avoid overwhelming Ollama.
    """
    from sqlalchemy import select
    from app.models.cluster import Cluster

    result = await db.execute(
        select(Cluster).where(Cluster.llm_summary == None)
    )
    clusters = result.scalars().all()

    if not clusters:
        return {"message": "All clusters already have summaries", "processed": 0}

    logger.info(f"Generating summaries for {len(clusters)} clusters")
    processed = 0
    failed = 0

    for cluster in clusters:
        try:
            await summarize_cluster(db, cluster.id)
            processed += 1
            logger.info(f"Summarized cluster {cluster.id} ({processed}/{len(clusters)})")
        except Exception as e:
            logger.error(f"Failed cluster {cluster.id}: {e}")
            failed += 1

    return {
        "message": f"Summarization complete",
        "processed": processed,
        "failed": failed,
        "total": len(clusters),
    }
