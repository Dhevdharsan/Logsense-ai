"""
Persistence for the fitted TF-IDF vectorizer.

The clustering/anomaly pipeline fits a fresh TfidfVectorizer on every run and
throws it away when the run ends. That is fine for clustering (it only needs the
vectors once) but it makes query-time retrieval impossible: to search the stored
`log_entries.embedding` vectors you must embed the incoming question into the
*same* vocabulary space, which means keeping the exact vectorizer that produced
those stored vectors.

So the pipeline now persists the fitted `LogPreprocessor` here, and the RAG
retrieval path loads it back. They are only ever consistent if the vectorizer on
disk is the one from the run that wrote the current embeddings -- which is why we
save it in the same step that writes the embeddings.

The artifact lives under backend/ (bind-mounted into the container in
docker-compose), so it survives container restarts. If it is ever lost, re-run
the analysis pipeline (POST /api/v1/analyze/run) to regenerate it.
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path

from loguru import logger

EMBED_DIM = 384  # must match Vector(384) on log_entries.embedding

ARTIFACT_DIR = Path(
    os.getenv("LOGSENSE_ARTIFACT_DIR", str(Path(__file__).parent / "artifacts"))
)
VECTORIZER_PATH = ARTIFACT_DIR / "tfidf_preprocessor.pkl"

# Small in-process cache so we don't unpickle on every single query. Keyed on the
# file's mtime so a fresh pipeline run is picked up automatically.
_cache: dict = {"mtime": None, "obj": None}


def pad_to_dim(vec, dim: int = EMBED_DIM) -> list[float]:
    """Force a TF-IDF row to exactly `dim` floats.

    TfidfVectorizer emits len(vocabulary_) columns, which is min(max_features,
    actual_vocab) and can be < 384 on small corpora. The pgvector column is a
    fixed Vector(384), so a short row would fail to insert. Zero-padding the tail
    is safe for cosine similarity (the padded dimensions contribute nothing), and
    because indexing and querying both pad the same way, column i keeps meaning
    the same term on both sides.
    """
    v = [float(x) for x in vec]
    if len(v) >= dim:
        return v[:dim]
    v.extend([0.0] * (dim - len(v)))
    return v


def save_preprocessor(preprocessor) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = VECTORIZER_PATH.with_suffix(".pkl.tmp")
    with tmp.open("wb") as f:
        pickle.dump(preprocessor, f)
    os.replace(tmp, VECTORIZER_PATH)  # atomic swap so a reader never sees a half-file
    _cache["mtime"] = VECTORIZER_PATH.stat().st_mtime
    _cache["obj"] = preprocessor
    logger.info(f"Persisted fitted TF-IDF preprocessor to {VECTORIZER_PATH}")


def load_preprocessor():
    """Return the fitted LogPreprocessor, cached by file mtime.

    Raises FileNotFoundError with an actionable message if no pipeline has run
    yet, so the query endpoint can turn it into a clean 503 instead of a 500.
    """
    if not VECTORIZER_PATH.exists():
        raise FileNotFoundError(
            f"No fitted TF-IDF vectorizer at {VECTORIZER_PATH}. Retrieval shares "
            "the embedding space of the stored log vectors, so run the analysis "
            "pipeline first: POST /api/v1/analyze/run"
        )
    mtime = VECTORIZER_PATH.stat().st_mtime
    if _cache["obj"] is None or _cache["mtime"] != mtime:
        with VECTORIZER_PATH.open("rb") as f:
            _cache["obj"] = pickle.load(f)
        _cache["mtime"] = mtime
        logger.info(f"Loaded TF-IDF vectorizer from {VECTORIZER_PATH}")
    return _cache["obj"]
