# Owns Qdrant vector-memory connection and query helper logic.

from __future__ import annotations

import threading

from backend.config.settings import (
    AI_UPDATES_EMBED_SIZE,
    AI_UPDATES_MEMORY_ENABLED,
    AI_UPDATES_QDRANT_API_KEY,
    AI_UPDATES_QDRANT_COLLECTION,
    AI_UPDATES_QDRANT_URL,
    QDRANT_DB_DIR,
)

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams
except Exception:
    QdrantClient = None
    Distance = None
    FieldCondition = None
    Filter = None
    MatchValue = None
    PointStruct = None
    VectorParams = None

_QDRANT_LOCK = threading.Lock()
_QDRANT_LOCK_WARNING_SHOWN = False


# Creates the configured Qdrant collection if it does not exist.
def ensure_qdrant_collection(qdrant) -> bool:
    if qdrant is None:
        return False
    try:
        names = [collection.name for collection in qdrant.get_collections().collections]
        if AI_UPDATES_QDRANT_COLLECTION not in names and VectorParams is not None:
            qdrant.create_collection(
                collection_name=AI_UPDATES_QDRANT_COLLECTION,
                vectors_config=VectorParams(size=AI_UPDATES_EMBED_SIZE, distance=Distance.COSINE),
            )
        return True
    except Exception:
        return False


# Opens the configured Qdrant memory when vector memory is enabled.
def open_qdrant_memory():
    global _QDRANT_LOCK_WARNING_SHOWN
    if not AI_UPDATES_MEMORY_ENABLED or QdrantClient is None:
        return None
    try:
        if AI_UPDATES_QDRANT_URL:
            client_kwargs = {"url": AI_UPDATES_QDRANT_URL}
            if AI_UPDATES_QDRANT_API_KEY:
                client_kwargs["api_key"] = AI_UPDATES_QDRANT_API_KEY
            qdrant = QdrantClient(**client_kwargs)
        else:
            QDRANT_DB_DIR.mkdir(parents=True, exist_ok=True)
            qdrant = QdrantClient(path=str(QDRANT_DB_DIR))
        ensure_qdrant_collection(qdrant)
        return qdrant
    except Exception as exc:
        if not _QDRANT_LOCK_WARNING_SHOWN:
            print(f"[AI Updates] Qdrant memory skipped: {exc}", flush=True)
            _QDRANT_LOCK_WARNING_SHOWN = True
        return None


# Closes a Qdrant client without failing the pipeline.
def close_qdrant_memory(qdrant) -> None:
    try:
        if qdrant is not None:
            qdrant.close()
    except Exception:
        pass


# Builds the Qdrant payload filter for one content type.
def qdrant_type_filter(content_type: str = "news"):
    if Filter is None or FieldCondition is None or MatchValue is None:
        return None
    return Filter(must=[FieldCondition(key="type", match=MatchValue(value=content_type))])


# Returns the PointStruct class used when saving semantic-memory points.
def point_struct_class():
    return PointStruct


# Runs a function while holding the shared Qdrant write lock.
def with_qdrant_lock(callback):
    with _QDRANT_LOCK:
        return callback()

