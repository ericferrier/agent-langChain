"""
ArangoDB-backed conversation checkpointer.

Each conversation is a `session` document in ArangoDB.
  - session_id: UUID (client-visible, returned on first turn)
  - turns: ordered list of {query, answer, sources, confidence, escalate, timestamp}
  - created_at, last_active, expires_at (TTL-driven expiry)

Resumption: client passes session_id on subsequent requests.
  - If the last turn has the same query (network retry), the saved answer is
    returned immediately without calling the LLM again (deduplication).

Collection bootstrap: `ensure_collection()` is called lazily on first write
so the service starts without requiring 01_init.py to have run.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
COLLECTION = "session"


def _arango_base() -> str:
    url = os.getenv("ARANGO_URL", "http://host.docker.internal:8529").rstrip("/")
    db = os.getenv("ARANGO_DB", "agri_dao")
    return f"{url}/_db/{db}"


def _auth() -> tuple[str, str]:
    return (
        os.getenv("ARANGO_USER", "system"),
        os.getenv("ARANGO_ROOT_PASSWORD", ""),
    )


def _timeout() -> float:
    return float(os.getenv("ARANGO_TIMEOUT", "10"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)).isoformat()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
async def _post(client: httpx.AsyncClient, path: str, body: dict) -> dict:
    resp = await client.post(
        f"{_arango_base()}{path}",
        json=body,
        auth=_auth(),
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()


async def _get(client: httpx.AsyncClient, path: str) -> dict:
    resp = await client.get(
        f"{_arango_base()}{path}",
        auth=_auth(),
    )
    resp.raise_for_status()
    return resp.json()


async def _ensure_collection(client: httpx.AsyncClient) -> None:
    """Create the session collection if it does not already exist."""
    try:
        await _post(client, "/_api/collection", {"name": COLLECTION, "type": 2})
    except httpx.HTTPStatusError as exc:
        # 409 = already exists, safe to ignore
        if exc.response.status_code != 409:
            raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def load_session(session_id: str) -> Optional[dict]:
    """
    Fetch a session document by session_id.
    Returns None if not found or on any error.
    """
    aql = (
        "FOR s IN session "
        "FILTER s.session_id == @sid "
        "LIMIT 1 RETURN s"
    )
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            data = await _post(client, "/_api/cursor", {"query": aql, "bindVars": {"sid": session_id}})
        results = data.get("result", [])
        return results[0] if results else None
    except Exception:
        return None


async def save_turn(
    session_id: str,
    turn: dict[str, Any],
    region_id: Optional[str] = None,
    tier: Optional[str] = None,
    trusted: bool = False,
) -> bool:
    """
    Append a turn to an existing session, or create a new session document.
    Returns True on success, False on any error (caller degrades gracefully).
    """
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            await _ensure_collection(client)

            existing = await load_session(session_id)

            if existing:
                # Append turn and refresh last_active / expires_at
                doc_key = existing["_key"]
                turns = existing.get("turns", [])
                turns.append(turn)
                patch = {
                    "turns": turns,
                    "last_active": _now(),
                    "expires_at": _expires(),
                }
                resp = await client.patch(
                    f"{_arango_base()}/_api/document/{COLLECTION}/{doc_key}",
                    json=patch,
                    auth=_auth(),
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
            else:
                # New session
                doc = {
                    "_key": session_id.replace("-", ""),  # ArangoDB key: no hyphens
                    "session_id": session_id,
                    "region_id": region_id,
                    "tier": tier,
                    "trusted": trusted,
                    "turns": [turn],
                    "created_at": _now(),
                    "last_active": _now(),
                    "expires_at": _expires(),
                }
                await _post(client, f"/_api/document/{COLLECTION}", doc)

        return True
    except Exception:
        return False


def is_duplicate_turn(session: Optional[dict], query: str) -> Optional[dict]:
    """
    If the last turn in the session has the same query (case-insensitive),
    return that turn's saved result so the LLM is not called again.
    Returns None if not a duplicate.
    """
    if not session:
        return None
    turns = session.get("turns", [])
    if not turns:
        return None
    last = turns[-1]
    if last.get("query", "").strip().lower() == query.strip().lower():
        return last
    return None


def make_turn(query: str, result: dict[str, Any]) -> dict[str, Any]:
    """Package a RAG result as a storable turn."""
    return {
        "query": query,
        "answer": result.get("answer"),
        "sources": result.get("sources", []),
        "confidence": result.get("confidence"),
        "confidence_label": result.get("confidence_label"),
        "escalate": result.get("escalate"),
        "escalation_reason": result.get("escalation_reason"),
        "tier": result.get("tier"),
        "status": result.get("status"),
        "verification_status": result.get("verification_status"),
        "llm_available": result.get("llm_available"),
        "timestamp": _now(),
    }
