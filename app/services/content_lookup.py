"""
Lookup service for query_content rows stored in ArangoDB.

Keeps read-path logic separate from fetch/store logic so the answer worker
has an explicit content lookup dependency.
"""
import os

import httpx


QUERY_CONTENT_COLLECTION = os.getenv("ARANGO_QUERY_CONTENT_COLLECTION", "query_content")


def _arango_base() -> str:
    url = os.getenv("ARANGO_URL", "http://10.0.0.1:8529").rstrip("/")
    db = os.getenv("ARANGO_DB", "agri_dao")
    return f"{url}/_db/{db}"


def _auth() -> tuple[str, str]:
    return (
        os.getenv("ARANGO_USER", "system"),
        os.getenv("ARANGO_PASSWORD") or os.getenv("ARANGO_ROOT_PASSWORD", ""),
    )


async def load_content_for_query_id(query_id: str) -> dict[str, str]:
    """Return resource_key -> stripped content for a query id from query_content."""
    if not query_id:
        return {}

    aql = """
    FOR d IN @@collection
    FILTER d.query_id == @query_id
    RETURN {
      resource_key: d.resource_key,
      content: d.content
    }
    """

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{_arango_base()}/_api/cursor",
                json={
                    "query": aql,
                    "bindVars": {
                        "@collection": QUERY_CONTENT_COLLECTION,
                        "query_id": query_id,
                    },
                },
                auth=_auth(),
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        rows = data.get("result", [])
        return {
            row.get("resource_key", ""): row.get("content", "")
            for row in rows
            if row.get("resource_key") and row.get("content")
        }
    except Exception:
        return {}
