"""
Content fetching and extraction for resource URLs.

Fetches HTML from URLs and extracts relevant text content to store in ArangoDB.
Handles errors gracefully - partial failures don't block the RAG chain.
"""
import asyncio
import hashlib
import os
from datetime import timedelta
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup


QUERY_CONTENT_COLLECTION = os.getenv("ARANGO_QUERY_CONTENT_COLLECTION", "query_content")
QUERY_CONTENT_TTL_HOURS = int(os.getenv("ARANGO_QUERY_CONTENT_TTL_HOURS", "24"))
# 0 means unlimited storage (bounded only by Arango document size limits).
QUERY_CONTENT_MAX_CHARS = int(os.getenv("ARANGO_QUERY_CONTENT_MAX_CHARS", "0"))


def _resource_lookup_key(resource: dict) -> str:
    key = str(resource.get("_key") or "").strip()
    if key:
        return key

    url = str(resource.get("url") or "").strip().lower()
    if not url:
        return ""

    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"url_{digest}"


def _arango_base() -> str:
    url = os.getenv("ARANGO_URL", "http://10.0.0.1:8529").rstrip("/")
    db = os.getenv("ARANGO_DB", "agri_dao")
    return f"{url}/_db/{db}"


def _auth() -> tuple[str, str]:
    return (
        os.getenv("ARANGO_USER", "system"),
        os.getenv("ARANGO_PASSWORD") or os.getenv("ARANGO_ROOT_PASSWORD", ""),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_at(hours: int = QUERY_CONTENT_TTL_HOURS) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


async def _ensure_query_content_collection(client: httpx.AsyncClient) -> None:
    try:
        resp = await client.post(
            f"{_arango_base()}/_api/collection",
            json={"name": QUERY_CONTENT_COLLECTION, "type": 2},
            auth=_auth(),
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 201, 202, 409):
            resp.raise_for_status()
    except Exception:
        # Non-fatal: the chain can still proceed with in-memory content.
        return

    # Ensure TTL index so rows auto-expire (daily refresh by default).
    try:
        idx_resp = await client.post(
            f"{_arango_base()}/_api/index?collection={QUERY_CONTENT_COLLECTION}",
            json={
                "type": "ttl",
                "fields": ["expires_at"],
                "expireAfter": 0,
                "name": "ttl_expires_at",
            },
            auth=_auth(),
            headers={"Content-Type": "application/json"},
        )
        if idx_resp.status_code not in (200, 201, 202, 409):
            idx_resp.raise_for_status()
    except Exception:
        # Non-fatal: keep serving requests even if index creation fails.
        return


async def fetch_and_extract(url: str, timeout_s: float = 10.0) -> Optional[str]:
    """
    Fetch URL and extract main text content using BeautifulSoup.
    Returns extracted text or None on any error.
    """
    if not url or not isinstance(url, str):
        return None

    try:
        timeout = httpx.Timeout(timeout=timeout_s, connect=min(5.0, timeout_s))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                url,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "html.parser")

        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer"]):
            script.decompose()

        # Get text
        text = soup.get_text(separator="\n", strip=True)

        # Clean up whitespace
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        content = "\n".join(lines)
        return content if content else None
    except Exception:
        return None


def _prepare_content_for_storage(content: str) -> str:
    if not content:
        return ""
    if QUERY_CONTENT_MAX_CHARS <= 0:
        return content
    return content[:QUERY_CONTENT_MAX_CHARS]


async def store_content_in_arango(
    *,
    query_id: str,
    query: str,
    session_id: str,
    resource: dict,
    content: str,
) -> bool:
    """
    Store fetched content as a field on the resource document in Arango via HTTP.
    Returns True if successful, False otherwise.
    """
    if not query_id or not content:
        return False

    resource_key = resource.get("_key", "")
    source_url = resource.get("url", "")
    if not resource_key:
        return False

    doc_key = f"{query_id}_{resource_key}"[:254]
    payload = {
        "_key": doc_key,
        "query_id": query_id,
        "query": query,
        "session_id": session_id,
        "resource_key": resource_key,
        "resource_title": resource.get("title", ""),
        "resource_url": source_url,
        "source_type": resource.get("source_type", ""),
        "content": content,
        "created_at": _now(),
        "expires_at": _expires_at(),
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await _ensure_query_content_collection(client)
            resp = await client.post(
                f"{_arango_base()}/_api/document/{QUERY_CONTENT_COLLECTION}",
                json=payload,
                auth=_auth(),
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code not in (200, 201, 202, 409):
                resp.raise_for_status()
        return True
    except Exception:
        return False


async def fetch_resources_content(
    *,
    query_id: str,
    query: str,
    session_id: str,
    resources: list[dict],
    timeout_s: float = 10.0,
) -> dict[str, Optional[str]]:
    """
    Asynchronously fetch content for multiple resources.
    Returns dict mapping resource _key -> extracted content (or None if fetch failed).

    Fetches up to 6 resources in parallel. Stores content in Arango if successful.
    """
    if not resources:
        return {}

    # Limit to first 6 resources to avoid hammering servers
    tasks = []
    resource_map = {}

    for resource in resources[:6]:
        url = resource.get("url")
        key = _resource_lookup_key(resource)
        if url and key:
            resource_with_key = resource if resource.get("_key") else {**resource, "_key": key}
            resource_map[key] = (url, resource_with_key)
            tasks.append(fetch_and_extract(url, timeout_s=timeout_s))

    if not tasks:
        return {}

    # Fetch all URLs in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Store results in Arango and build return dict
    content_map: dict[str, Optional[str]] = {}
    store_tasks: list[asyncio.Task] = []
    for (key, (url, resource)), result in zip(resource_map.items(), results):
        if isinstance(result, str) and result:
            content_map[key] = _prepare_content_for_storage(result)
            # Persist and wait so immediate read-by-query_id can see the rows.
            store_tasks.append(asyncio.create_task(
                store_content_in_arango(
                    query_id=query_id,
                    query=query,
                    session_id=session_id,
                    resource=resource,
                    content=content_map[key],
                )
            ))
        else:
            content_map[key] = None

    if store_tasks:
        await asyncio.gather(*store_tasks, return_exceptions=True)

    return content_map


def inject_content_into_resources(
    resources: list[dict],
    content_map: dict[str, Optional[str]],
) -> list[dict]:
    """
    Inject fetched content into resource dicts for passing to the LLM.
    """
    enhanced = []
    for resource in resources:
        key = _resource_lookup_key(resource)
        content = content_map.get(key) if content_map else resource.get("fetched_content")
        if content:
            enhanced.append({**resource, "fetched_content": content})
        else:
            enhanced.append(resource)
    return enhanced


async def load_content_for_query_id(query_id: str) -> dict[str, str]:
    """Load fetched content from query_content collection for a query id."""
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
            await _ensure_query_content_collection(client)
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


async def cleanup_fetched_content_for_session(session_id: str) -> int:
    """
    Clean up fetched_content fields from all resources via ArangoDB AQL.
    Removes temporary extracted content to free space after session ends.
    Returns number of resources updated.
    """
    if not session_id:
        return 0

    aql = """
    FOR doc IN @@collection
    FILTER doc.session_id == @session_id
    REMOVE doc IN @@collection
    RETURN 1
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await _ensure_query_content_collection(client)
            resp = await client.post(
                f"{_arango_base()}/_api/cursor",
                json={
                    "query": aql,
                    "bindVars": {
                        "@collection": QUERY_CONTENT_COLLECTION,
                        "session_id": session_id,
                    },
                },
                auth=_auth(),
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        return len(data.get("result", []))
    except Exception:
        return 0
