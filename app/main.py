import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Literal, Optional

from app.chains.rag import query_rag
from app.checkpointer.arango_cp import load_session
from app.services.langsmith_config import initialize_langsmith, langsmith_settings

try:
    from app.services.jira_mock_couch import (
        create_mock_jira_issue,
        enqueue_mock_jira_issue_job,
        get_mock_jira_issue_job,
    )
except Exception:
    create_mock_jira_issue = None
    enqueue_mock_jira_issue_job = None
    get_mock_jira_issue_job = None

try:
    from app.services.reference_lookup_couch import (
        enqueue_reference_lookup_job,
        get_reference_lookup_job,
    )
except Exception:
    enqueue_reference_lookup_job = None
    get_reference_lookup_job = None

app = FastAPI()
LANGSMITH_STATE = langsmith_settings()
JIRA_ENABLED = (os.getenv("ENABLE_JIRA", "false").strip().lower() == "true")


class RagRequest(BaseModel):
    query: str
    tier: Optional[Literal["broad", "compliance", "fulfillment", "pricing"]] = "broad"
    region_id: Optional[str] = None     # e.g. "north_america", "gulf_cooperation_council"
    trusted: bool = False               # True = verified DAO account (sees system resources)
    force_escalate: bool = False        # True = user manually overrides and requests Jira escalation
    session_id: Optional[str] = None   # Resume an existing conversation; omit to start a new session
    query_id: Optional[str] = None      # Optional external query id for fetched-content persistence
    reference_lookup: bool = False      # True = enqueue/consume async URL reference lookup worker
    reference_job_id: Optional[str] = None


class JiraMockIssueRequest(BaseModel):
    summary: str
    description: str
    priority: Optional[Literal["low", "medium", "high", "critical"]] = "medium"
    reporter: Optional[str] = "public_user"
    component: Optional[str] = "support"
    labels: list[str] = Field(default_factory=list)
    category: Optional[Literal["marketplace", "export", "payment", "compliance", "pricing"]] = None
    region_id: Optional[str] = None
    session_id: Optional[str] = None
    escalation_reason: Optional[str] = None


class ReferenceLookupRequest(BaseModel):
    query: str
    tier: Optional[Literal["broad", "compliance", "fulfillment", "pricing"]] = "broad"
    region_id: Optional[str] = None
    trusted: bool = False
    max_urls: int = Field(default=6, ge=1, le=20)
    max_extract_chars: int = Field(default=1200, ge=200, le=6000)


@app.get("/")
async def root():
    endpoints = [
        "POST /rag/query",
        "POST /reference/enqueue",
        "GET /reference/job/{job_id}",
        "GET /session/{session_id}",
    ]
    if JIRA_ENABLED:
        endpoints.extend([
            "POST /jira/mock",
            "POST /jira/enqueue",
            "GET /jira/job/{job_id}",
        ])

    return {
        "name": "compose_langchain",
        "status": "ok",
        "docs": "/docs",
        "endpoints": endpoints,
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "langsmith": {
            "enabled": LANGSMITH_STATE["enabled"],
            "project": LANGSMITH_STATE["project"],
        },
    }


@app.on_event("startup")
async def startup_event():
    global LANGSMITH_STATE
    try:
        LANGSMITH_STATE = initialize_langsmith()
        if LANGSMITH_STATE["enabled"] and LANGSMITH_STATE["api_key_present"]:
            print(f"LangSmith tracing enabled for project '{LANGSMITH_STATE['project']}'")
        else:
            print("LangSmith tracing disabled or API key missing")
    except Exception as exc:
        LANGSMITH_STATE = langsmith_settings()
        print(f"LangSmith initialization failed: {exc}")


@app.post("/rag/query")
async def rag_query(payload: RagRequest):
    return await query_rag(
        payload.query,
        tier=payload.tier,
        region_id=payload.region_id,
        trusted=payload.trusted,
        force_escalate=payload.force_escalate,
        session_id=payload.session_id,
        query_id=payload.query_id,
        reference_lookup=payload.reference_lookup,
        reference_job_id=payload.reference_job_id,
    )


@app.post("/jira/mock")
async def jira_mock_create(payload: JiraMockIssueRequest):
    if not JIRA_ENABLED:
        raise HTTPException(status_code=503, detail="Jira support disabled")
    if not create_mock_jira_issue:
        raise HTTPException(status_code=503, detail="Jira mock service unavailable")
    result = await create_mock_jira_issue(payload.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@app.post("/jira/enqueue", status_code=202)
async def jira_mock_enqueue(payload: JiraMockIssueRequest):
    if not JIRA_ENABLED:
        raise HTTPException(status_code=503, detail="Jira support disabled")
    if not enqueue_mock_jira_issue_job:
        raise HTTPException(status_code=503, detail="Jira mock service unavailable")
    result = await enqueue_mock_jira_issue_job(payload.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@app.get("/jira/job/{job_id}")
async def jira_mock_job_status(job_id: str):
    if not JIRA_ENABLED:
        raise HTTPException(status_code=503, detail="Jira support disabled")
    if not get_mock_jira_issue_job:
        raise HTTPException(status_code=503, detail="Jira mock service unavailable")
    result = await get_mock_jira_issue_job(job_id)
    if not result.get("ok") and result.get("error") == "job_not_found":
        raise HTTPException(status_code=404, detail=result)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@app.post("/reference/enqueue", status_code=202)
async def reference_lookup_enqueue(payload: ReferenceLookupRequest):
    if not enqueue_reference_lookup_job:
        raise HTTPException(status_code=503, detail="Reference lookup service unavailable")
    result = await enqueue_reference_lookup_job(payload.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@app.get("/reference/job/{job_id}")
async def reference_lookup_job_status(job_id: str):
    if not get_reference_lookup_job:
        raise HTTPException(status_code=503, detail="Reference lookup service unavailable")
    result = await get_reference_lookup_job(job_id)
    if not result.get("ok") and result.get("error") == "job_not_found":
        raise HTTPException(status_code=404, detail=result)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """Return the full conversation history for a session."""
    session = await load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return {
        "session_id": session.get("session_id"),
        "region_id": session.get("region_id"),
        "tier": session.get("tier"),
        "created_at": session.get("created_at"),
        "last_active": session.get("last_active"),
        "expires_at": session.get("expires_at"),
        "turns": session.get("turns", []),
    }


