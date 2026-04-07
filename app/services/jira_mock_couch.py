from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_priority(priority: str) -> str:
    allowed = {"low", "medium", "high", "critical"}
    p = (priority or "medium").strip().lower()
    return p if p in allowed else "medium"


def _couch_config() -> dict[str, str]:
    return {
        "base_url": os.getenv("COUCHDB_BASE_URL", "").rstrip("/"),
        "username": os.getenv("COUCHDB_USER", ""),
        "password": os.getenv("COUCHDB_PASSWORD", ""),
        "database": os.getenv("COUCHDB_DATABASE", "jira_issue"),
    }


def _couch_config_error(cfg: dict[str, str]) -> dict[str, Any] | None:
    if not cfg["base_url"] or not cfg["username"] or not cfg["password"]:
        return {
            "ok": False,
            "error": "couchdb_config_missing",
            "message": "COUCHDB_BASE_URL, COUCHDB_USER, or COUCHDB_PASSWORD is missing",
        }
    return None


async def _ensure_database(client: httpx.AsyncClient, db_url: str) -> None:
    db_check = await client.get(db_url)
    if db_check.status_code == 404:
        await client.put(db_url)


def _build_issue_doc(payload: dict[str, Any]) -> dict[str, Any]:
    ticket_key = f"MOCK-{uuid.uuid4().hex[:8].upper()}"
    now = _utc_now_iso()
    return {
        "doc_type": "jira_issue_mock",
        "ticket_key": ticket_key,
        "status": "open",
        "summary": payload["summary"],
        "description": payload["description"],
        "priority": _normalize_priority(payload.get("priority", "medium")),
        "reporter": payload.get("reporter", "public_user"),
        "component": payload.get("component", "support"),
        "labels": payload.get("labels", []),
        "category": payload.get("category"),
        "region_id": payload.get("region_id"),
        "source_session_id": payload.get("session_id"),
        "escalation_reason": payload.get("escalation_reason"),
        "created_at": now,
        "updated_at": now,
    }


async def create_mock_jira_issue(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = _couch_config()
    config_error = _couch_config_error(cfg)
    if config_error:
        return config_error

    doc = _build_issue_doc(payload)
    auth = httpx.BasicAuth(username=cfg["username"], password=cfg["password"])
    url = f"{cfg['base_url']}/{cfg['database']}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), auth=auth) as client:
            await _ensure_database(client, url)

            response = await client.post(url, json=doc)
            response.raise_for_status()
            data = response.json()

        return {
            "ok": True,
            "provider": "couchdb-mock-jira",
            "ticket_key": doc["ticket_key"],
            "db": cfg["database"],
            "doc_id": data.get("id"),
            "doc_rev": data.get("rev"),
            "status": "created",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "couchdb_write_failed",
            "message": str(exc),
        }


async def enqueue_mock_jira_issue_job(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = _couch_config()
    config_error = _couch_config_error(cfg)
    if config_error:
        return config_error

    job_id = f"jira-job-{uuid.uuid4().hex}"
    now = _utc_now_iso()
    doc = {
        "_id": job_id,
        "doc_type": "jira_issue_job",
        "status": "pending",
        "retry_count": 0,
        "last_error": "",
        "created_at": now,
        "updated_at": now,
        "payload": payload,
    }

    auth = httpx.BasicAuth(username=cfg["username"], password=cfg["password"])
    url = f"{cfg['base_url']}/{cfg['database']}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), auth=auth) as client:
            await _ensure_database(client, url)
            response = await client.post(url, json=doc)
            response.raise_for_status()
            data = response.json()

        return {
            "ok": True,
            "job_id": job_id,
            "status": "pending",
            "db": cfg["database"],
            "doc_id": data.get("id"),
            "doc_rev": data.get("rev"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "couchdb_enqueue_failed",
            "message": str(exc),
        }


async def get_mock_jira_issue_job(job_id: str) -> dict[str, Any]:
    cfg = _couch_config()
    config_error = _couch_config_error(cfg)
    if config_error:
        return config_error

    auth = httpx.BasicAuth(username=cfg["username"], password=cfg["password"])
    url = f"{cfg['base_url']}/{cfg['database']}/{job_id}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), auth=auth) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return {"ok": False, "error": "job_not_found", "job_id": job_id}
            response.raise_for_status()
            data = response.json()

        return {
            "ok": True,
            "job_id": data.get("_id"),
            "status": data.get("status"),
            "retry_count": data.get("retry_count", 0),
            "last_error": data.get("last_error", ""),
            "ticket_key": data.get("result", {}).get("ticket_key"),
            "result": data.get("result"),
            "updated_at": data.get("updated_at"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "couchdb_job_lookup_failed",
            "message": str(exc),
            "job_id": job_id,
        }


async def process_next_jira_job() -> dict[str, Any]:
    cfg = _couch_config()
    config_error = _couch_config_error(cfg)
    if config_error:
        return config_error

    auth = httpx.BasicAuth(username=cfg["username"], password=cfg["password"])
    db_url = f"{cfg['base_url']}/{cfg['database']}"
    find_url = f"{db_url}/_find"
    max_retries = int(os.getenv("JIRA_WORKER_MAX_RETRIES", "3"))

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0), auth=auth) as client:
            await _ensure_database(client, db_url)

            find_resp = await client.post(
                find_url,
                json={
                    "selector": {"doc_type": "jira_issue_job", "status": "pending"},
                    "limit": 1,
                },
            )
            find_resp.raise_for_status()
            docs = find_resp.json().get("docs", [])
            if not docs:
                return {"ok": True, "processed": False, "status": "idle"}

            job = docs[0]
            job_id = job["_id"]
            now = _utc_now_iso()

            # Best-effort claim: mark processing.
            job["status"] = "processing"
            job["updated_at"] = now
            claim_resp = await client.put(f"{db_url}/{job_id}", json=job)
            claim_resp.raise_for_status()
            claim_data = claim_resp.json()
            job["_rev"] = claim_data.get("rev", job.get("_rev"))

            result = await create_mock_jira_issue(job.get("payload", {}))

            job["updated_at"] = _utc_now_iso()
            if result.get("ok"):
                job["status"] = "created"
                job["result"] = result
            else:
                job["retry_count"] = int(job.get("retry_count", 0)) + 1
                job["last_error"] = result.get("message", result.get("error", "unknown"))
                job["status"] = "failed" if job["retry_count"] >= max_retries else "pending"

            finalize_resp = await client.put(f"{db_url}/{job_id}", json=job)
            finalize_resp.raise_for_status()

            return {
                "ok": True,
                "processed": True,
                "job_id": job_id,
                "status": job["status"],
                "ticket_key": result.get("ticket_key"),
            }
    except Exception as exc:
        return {
            "ok": False,
            "error": "jira_worker_processing_failed",
            "message": str(exc),
        }


async def run_jira_worker_loop() -> None:
    interval_s = float(os.getenv("JIRA_WORKER_POLL_SECONDS", "2.0"))
    while True:
        result = await process_next_jira_job()
        if not result.get("ok"):
            print(f"[jira-worker] error: {result.get('message', result.get('error'))}")
        await asyncio.sleep(interval_s)