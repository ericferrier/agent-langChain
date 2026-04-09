"""
Jira reference lookup job service.

This provides async enqueue/status APIs and a worker loop used by
app.main and app.workers.reference_worker.

Implementation is intentionally lightweight and resilient: this is a
Jira-style lookup mock backed by CouchDB in development. If the backing
store is unavailable, callers get deterministic error payloads instead of
crashes.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.resource_search import search_reference_urls


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_base_url() -> str:
    return (os.getenv("COUCHDB_BASE_URL") or "").rstrip("/")


def _store_auth() -> tuple[str, str]:
    return (
        os.getenv("COUCHDB_USER", ""),
        os.getenv("COUCHDB_PASSWORD", ""),
    )


def _lookup_db_name() -> str:
    return os.getenv("COUCHDB_DATABASE", "jira_issue")


def _jobs_db_name() -> str:
    return os.getenv("REFERENCE_LOOKUP_DB", "reference_lookup_job")


async def _ensure_db(client: httpx.AsyncClient, db_name: str) -> None:
    resp = await client.put(f"{_store_base_url()}/{db_name}", auth=_store_auth())
    if resp.status_code not in (200, 201, 202, 412):
        resp.raise_for_status()


async def _create_job_doc(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    doc = {
        "_id": job_id,
        "type": "reference_lookup_job",
        "status": "pending",
        "attempts": 0,
        "created_at": _now(),
        "updated_at": _now(),
        "payload": payload,
        "result": None,
        "error": None,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        await _ensure_db(client, _jobs_db_name())
        resp = await client.put(
            f"{_store_base_url()}/{_jobs_db_name()}/{job_id}",
            auth=_store_auth(),
            json=doc,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

    return {"ok": True, "job_id": job_id, "status": "pending"}


async def enqueue_reference_lookup_job(payload: dict[str, Any]) -> dict[str, Any]:
    if not _store_base_url():
        return {"ok": False, "error": "couchdb_not_configured"}
    try:
        return await _create_job_doc(payload)
    except Exception as exc:
        return {"ok": False, "error": f"enqueue_failed: {exc}"}


async def get_reference_lookup_job(job_id: str) -> dict[str, Any]:
    if not _store_base_url():
        return {"ok": False, "error": "couchdb_not_configured"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_store_base_url()}/{_jobs_db_name()}/{job_id}",
                auth=_store_auth(),
            )
            if resp.status_code == 404:
                return {"ok": False, "error": "job_not_found", "job_id": job_id}
            resp.raise_for_status()
            doc = resp.json()

        return {
            "ok": True,
            "job_id": job_id,
            "status": doc.get("status", "unknown"),
            "attempts": doc.get("attempts", 0),
            "result": doc.get("result"),
            "error": doc.get("error"),
            "updated_at": doc.get("updated_at"),
        }
    except Exception as exc:
        return {"ok": False, "error": f"status_failed: {exc}", "job_id": job_id}


async def _fetch_pending_jobs(client: httpx.AsyncClient, limit: int = 5) -> list[dict[str, Any]]:
    query = {
        "selector": {"type": "reference_lookup_job", "status": "pending"},
        "sort": [{"created_at": "asc"}],
        "limit": limit,
    }
    resp = await client.post(
        f"{_store_base_url()}/{_jobs_db_name()}/_find",
        auth=_store_auth(),
        json=query,
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return resp.json().get("docs", [])


async def _update_job(client: httpx.AsyncClient, doc: dict[str, Any]) -> None:
    doc["updated_at"] = _now()
    resp = await client.put(
        f"{_store_base_url()}/{_jobs_db_name()}/{doc['_id']}",
        auth=_store_auth(),
        json=doc,
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()


async def run_reference_worker_loop() -> None:
    poll_s = float(os.getenv("REFERENCE_WORKER_POLL_SECONDS", "3.0"))
    max_retries = int(os.getenv("REFERENCE_WORKER_MAX_RETRIES", "3"))

    if not _store_base_url():
        while True:
            await asyncio.sleep(max(1.0, poll_s))

    while True:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                await _ensure_db(client, _jobs_db_name())
                jobs = await _fetch_pending_jobs(client)
                for doc in jobs:
                    payload = doc.get("payload") or {}
                    try:
                        doc["status"] = "processing"
                        await _update_job(client, doc)

                        result = await search_reference_urls(
                            query=str(payload.get("query", "")),
                            tier=str(payload.get("tier", "broad")),
                            region_id=payload.get("region_id"),
                            trusted=bool(payload.get("trusted", False)),
                            max_urls=int(payload.get("max_urls", 6)),
                        )

                        doc["status"] = "completed"
                        doc["result"] = result
                        doc["error"] = None
                        await _update_job(client, doc)
                    except Exception as exc:
                        doc["attempts"] = int(doc.get("attempts", 0)) + 1
                        doc["error"] = str(exc)
                        doc["status"] = "failed" if doc["attempts"] >= max_retries else "pending"
                        await _update_job(client, doc)
        except Exception:
            pass

        await asyncio.sleep(max(1.0, poll_s))
