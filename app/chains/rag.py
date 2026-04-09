import asyncio
import os
import uuid
from typing import Any, Optional
import re
from urllib.parse import quote_plus

import httpx
from langsmith import traceable

from app.checkpointer.arango_cp import is_duplicate_turn, load_session, make_turn, save_turn
from app.services.confidence import score_answer
from app.services.content_fetch import (
    fetch_resources_content,
    inject_content_into_resources,
)
from app.services.content_lookup import load_content_for_query_id
from app.services.resource_search import (
    format_resources_as_context,
    infer_region_from_query,
    search_reference_urls,
    search_resources,
)

# Search tier applied when none is specified by the caller.
# Progression: broad → compliance → fulfillment → pricing
DEFAULT_TIER = "broad"

_NON_GROUNDED_PATTERNS = [
    "as an ai",
    "i am an ai",
    "i'm an ai",
    "deepseek",
    "programming assistant",
    "computer science",
    "don't have real-time",
    "do not have real-time",
    "no real-time access",
    "cannot access the internet",
    "can't assist",
    "cannot assist",
    "i'm sorry",
    "sorry i",
    "unable to help",
    "not able to help",
    "cannot help",
    "i'm unable",
    "unable to provide",
    "i cannot",
    "i can't",
    "as a programming",
    "as a coding",
    "outside my expertise",
]

_BRAVE_ASK_BASE = "https://search.brave.com/ask"


def _is_fast_scope_query(query: str) -> bool:
    q = (query or "").lower()
    return any(token in q for token in ["usda", "fas", "gats", "global agricultural trade system"])


def _budget_limit() -> int:
    """Hard per-session budget, clamped to 10-15 as requested."""
    raw = int(os.getenv("QUALITY_BUDGET_LIMIT", "15"))
    return max(10, min(15, raw))


def _base_cost_for_tier(tier: str) -> int:
    return {
        "broad": 1,
        "compliance": 2,
        "fulfillment": 2,
        "pricing": 2,
    }.get((tier or "broad").strip().lower(), 2)


def _turn_cost(turn: dict[str, Any]) -> int:
    """Quality-aware turn cost; lower quality burns budget faster."""
    cost = _base_cost_for_tier(turn.get("tier", DEFAULT_TIER))

    status = (turn.get("status") or "").strip().lower()
    if status == "degraded_fallback":
        cost += 2
    if status == "out_of_scope":
        cost += 3

    confidence_label = (turn.get("confidence_label") or "").strip().lower()
    if confidence_label == "low":
        cost += 2
    elif confidence_label == "medium":
        cost += 1

    if bool(turn.get("escalate")):
        cost += 1

    return max(1, cost)


def _session_spent_budget(session: Optional[dict]) -> int:
    if not session:
        return 0
    turns = session.get("turns", [])
    return sum(_turn_cost(t) for t in turns)


def _estimate_next_cost(tier: str) -> int:
    # Best-case estimate for next answer cost at this tier.
    return _base_cost_for_tier(tier)


def _attach_budget_meta(result: dict[str, Any], *, used: int, limit: int, estimated_next_cost: int) -> dict[str, Any]:
    return {
        **result,
        "usage_budget": {
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "next_cost_estimate": estimated_next_cost,
        },
    }


def _build_quota_exhausted_response(
    *,
    query: str,
    query_id: str,
    tier: str,
    region_id: Optional[str],
    session_id: str,
    model: str,
    used: int,
    limit: int,
    estimated_next_cost: int,
) -> dict[str, Any]:
    result = {
        "query": query,
        "query_id": query_id,
        "answer": "Anonymous usage limit reached. Please log in to continue with additional support requests.",
        "sources": [],
        "confidence": 0.0,
        "confidence_label": "low",
        "escalate": False,
        "escalation_reason": "anonymous_quality_budget_exhausted (manual escalation available)",
        "user_can_escalate": True,
        "session_id": session_id,
        "resumed": False,
        "tier": tier,
        "region_id": region_id,
        "model": model,
        "status": "limit_reached",
        "verified": False,
        "verification_status": "unverified",
        "llm_available": True,
        "should_retry": False,
        "error": "",
        "next_step": "prompt_login",
    }
    return _attach_budget_meta(result, used=used, limit=limit, estimated_next_cost=estimated_next_cost)


def _build_unverified_fallback(
    *,
    query: str,
    tier: str,
    region_id: Optional[str],
    session_id: str,
    model: str,
    reason: str,
) -> dict[str, Any]:
    """Return a deterministic degraded response when LLM inference is unavailable."""
    return {
        "query": query,
        "answer": "Unable to generate an answer from Ollama.",
        "sources": [],
        "confidence": 0.0,
        "confidence_label": "low",
        "escalate": False,
        "escalation_reason": f"{reason} (manual escalation available)",
        "user_can_escalate": True,
        "session_id": session_id,
        "resumed": False,
        "tier": tier,
        "region_id": region_id,
        "model": model,
        "status": "degraded_fallback",
        "verified": False,
        "verification_status": "unverified",
        "llm_available": False,
        "should_retry": True,
        "error": reason,
    }


def _normalize_success_result(result: dict[str, Any]) -> dict[str, Any]:
    """Ensure successful responses expose the same contract as fallback responses."""
    confidence = float(result.get("confidence") or 0.0)
    confidence_label = str(result.get("confidence_label") or "").strip().lower()
    is_verified = confidence >= 0.70 and confidence_label == "satisfactory"
    return {
        **result,
        "status": "ok",
        "verified": is_verified,
        "verification_status": "verified" if is_verified else "unverified",
        "llm_available": True,
        "should_retry": False,
        "error": "",
    }


def _build_grounded_reference_answer(query: str, resources: list[dict[str, Any]]) -> str:
    if not resources:
        return (
            "No supporting knowledge-base resources were found for this query. "
            f"Please cross-reference on {_brave_ask_url(query)}."
        )

    # Extract summaries and build a grounded narrative from available resources
    lines = [
        f"Based on available trade and compliance resources, here's what I found regarding '{query}':"
    ]
    
    # Add summaries from first few resources if available
    for resource in resources[:3]:
        title = resource.get("title", "Resource")
        url = resource.get("url", "")
        desc = (resource.get("description") or "").strip()
        source_type = resource.get("source_type", "reference")
        
        if desc:
            lines.append(f"\n**{title}** ({source_type}):")
            lines.append(f"{desc[:300]}")
        else:
            lines.append(f"\n**{title}** ({source_type}): {url}")
    
    # Add a list of all available sources
    lines.append("\n\nFull resource list:")
    for resource in resources:
        title = resource.get("title", "Untitled")
        url = resource.get("url", "")
        source_type = resource.get("source_type", "reference")
        lines.append(f"- [{source_type}] {title}: {url}")
    
    return "\n".join(lines)


def _ensure_grounded_answer(answer: str, query: str, resources: list[dict[str, Any]]) -> str:
    if not resources:
        return answer
    lower = answer.lower()
    if any(pattern in lower for pattern in _NON_GROUNDED_PATTERNS) or _contains_unapproved_urls(answer, resources):
        return _build_grounded_reference_answer(query, resources)
    return answer


def _contains_unapproved_urls(answer: str, resources: list[dict[str, Any]]) -> bool:
    # Keep answers grounded to returned resources by rejecting off-list links in model text.
    found_urls = re.findall(r"https?://[^\s)\]>\"]+", answer or "")
    if not found_urls:
        return False

    allowed_urls = {
        str(resource.get("url") or "").rstrip("/ ").lower()
        for resource in resources
        if resource.get("url")
    }

    for url in found_urls:
        cleaned = url.rstrip("/.,);:!?]>").lower()
        if cleaned and cleaned not in allowed_urls:
            return True
    return False


def _brave_ask_url(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return _BRAVE_ASK_BASE
    return f"{_BRAVE_ASK_BASE}?q={quote_plus(q)}"


def _build_sources(resources: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    sources = [
        {"title": r.get("title"), "url": r.get("url"), "source_type": r.get("source_type")}
        for r in resources
    ]

    brave_source = {
        "title": "Brave Ask cross-reference",
        "url": _brave_ask_url(query),
        "source_type": "web_search",
    }

    if not sources:
        return [brave_source]

    already_has_brave = any(_BRAVE_ASK_BASE in str(src.get("url") or "") for src in sources)
    if not already_has_brave:
        sources.append(brave_source)

    return sources


def _format_reference_resource_context(resources: list[dict[str, Any]]) -> str:
    if not resources:
        return ""
    lines = ["Filtered references from knowledge base:"]
    for resource in resources[:6]:
        title = resource.get("title", "Untitled")
        url = resource.get("url", "")
        desc = (resource.get("description") or "").strip()
        lines.append(f"- {title} ({url})")
        if desc:
            lines.append(f"  Summary: {desc[:400]}")
    return "\n".join(lines)


def _short_retry_prompt(query: str, resources: list[dict[str, Any]]) -> str:
    lines = [
        "You are a trade and agricultural compliance assistant.",
        "Provide a concise answer grounded in the resources below.",
        "If exact pricing is unavailable, say so and cite best available sources.",
        "",
        "Resources:",
    ]
    for r in resources[:2]:
        title = r.get("title", "")
        url = r.get("url", "")
        source_type = r.get("source_type", "")
        raw = (r.get("fetched_content") or r.get("description") or "")
        snippet = _best_query_snippet(raw, query, max_chars=320)
        lines.append(f"- [{source_type}] {title}")
        if url:
            lines.append(f"  URL: {url}")
        if snippet:
            lines.append(f"  Snippet: {snippet}")
    lines.append("")
    lines.append(f"Question: {query}")
    return "\n".join(lines)


def _query_terms(query: str) -> list[str]:
    terms = [t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 2]
    return terms[:12]


def _best_query_snippet(content: str, query: str, max_chars: int = 700) -> str:
    if not content:
        return ""

    text = " ".join(content.split())
    if len(text) <= max_chars:
        return text

    terms = _query_terms(query)
    lower = text.lower()
    positions = [lower.find(term) for term in terms if term and lower.find(term) >= 0]
    if not positions:
        return text[:max_chars]

    start = max(0, min(positions) - (max_chars // 3))
    end = min(len(text), start + max_chars)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def _resource_relevance(resource: dict[str, Any], query: str) -> int:
    terms = _query_terms(query)
    if not terms:
        return 0

    haystack = " ".join([
        str(resource.get("title", "")),
        str(resource.get("description", "")),
        str(resource.get("url", "")),
        str(resource.get("_key", "")),
        str(resource.get("resource_key", "")),
    ]).lower()

    score = 0
    for term in terms:
        if term in haystack:
            score += 1
    if resource.get("fetched_content"):
        score += 2
    return score


def _prioritize_resources_for_context(resources: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    return sorted(
        resources,
        key=lambda r: (
            _resource_relevance(r, query),
            len(str(r.get("fetched_content", ""))),
            len(str(r.get("description", ""))),
        ),
        reverse=True,
    )


async def _worker_match_resources(
    *,
    query: str,
    tier: str,
    region_id: Optional[str],
    trusted: bool,
) -> list[dict[str, Any]]:
    resources = await search_resources(query, tier=tier, region_id=region_id, trusted=trusted)
    if not resources:
        resources = await search_resources("", tier=tier, region_id=region_id, trusted=trusted)
    if not resources:
        # Relax region scope to recover globally relevant references.
        resources = await search_resources(query, tier=tier, region_id=None, trusted=trusted)
    if not resources and tier != "broad":
        # Last resort for sparse datasets.
        resources = await search_resources(query, tier="broad", region_id=None, trusted=trusted)
    return resources


async def _worker_strip_store_content(
    *,
    query_id: str,
    query: str,
    session_id: str,
    resources: list[dict[str, Any]],
    timeout_s: float = 5.0,
) -> dict[str, Optional[str]]:
    if not resources:
        return {}
    return await fetch_resources_content(
        query_id=query_id,
        query=query,
        session_id=session_id,
        resources=resources,
        timeout_s=timeout_s,
    )


async def _worker_read_stored_content(
    *,
    query_id: str,
    query: str,
    resources: list[dict[str, Any]],
    fetched_content_map: dict[str, Optional[str]],
) -> list[dict[str, Any]]:
    stored_content_map = await load_content_for_query_id(query_id)
    hydrated = inject_content_into_resources(resources, stored_content_map or fetched_content_map)
    return _prioritize_resources_for_context(hydrated, query)


@traceable(run_type="llm", name="ollama_generate")
async def _ollama_generate(
    *,
    ollama_url: str,
    model: str,
    prompt: str,
    timeout_s: float,
    read_timeout_s: Optional[float],
    num_predict: int,
) -> dict[str, Any]:
    timeout = httpx.Timeout(
        connect=min(5.0, timeout_s),
        write=timeout_s,
        pool=timeout_s,
        # None disables read timeout, useful for slow local Ollama responses.
        read=read_timeout_s,
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{ollama_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": num_predict,
                    "temperature": 0.2,
                },
            },
        )
        response.raise_for_status()
        return response.json()


async def _resolve_reference_lookup(
    *,
    query: str,
    tier: str,
    region_id: Optional[str],
    trusted: bool,
    reference_lookup: bool,
    reference_job_id: Optional[str],
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    if not reference_lookup and not reference_job_id:
        return {"enabled": False, "status": "disabled"}, "", []

    lookup = await search_reference_urls(
        query=query,
        tier=tier,
        region_id=region_id,
        trusted=trusted,
        max_urls=6,
    )
    resources = lookup.get("resources", [])
    return {
        "enabled": True,
        "status": "direct_arango",
        "matches": len(resources),
        "filters": lookup.get("filters", {}),
    }, _format_reference_resource_context(resources), resources


def _merge_resources(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for resource in [*(primary or []), *(secondary or [])]:
        url = str(resource.get("url") or "").strip()
        title = str(resource.get("title") or "").strip()
        key = (url or title).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(resource)

    return merged


@traceable(run_type="chain", name="query_rag")
async def query_rag(
    query: str,
    tier: str = DEFAULT_TIER,
    region_id: Optional[str] = None,
    trusted: bool = False,
    force_escalate: bool = False,
    session_id: Optional[str] = None,
    query_id: Optional[str] = None,
    reference_lookup: bool = False,
    reference_job_id: Optional[str] = None,
) -> dict[str, Any]:
    """Generate an answer with Ollama (Mistral by default).

    1. Resolves or creates a session_id for conversation persistence.
    2. If the same query was already answered in this session (network retry), returns cached result.
    3. Fetches relevant resources from ArangoDB using the requested tier filter.
    4. Injects those resources as grounding context into the LLM prompt.
    5. Scores the answer and applies escalation logic.
    6. Persists the turn to ArangoDB (fire-and-forget; failure is non-fatal).
    7. Returns the answer alongside sources, confidence, and session_id.
    """
    # --- Session resolution
    sid = session_id or str(uuid.uuid4())
    qid = query_id or str(uuid.uuid4())
    effective_region_id = infer_region_from_query(query) or region_id
    fast_scope = _is_fast_scope_query(query)
    session = await load_session(sid) if session_id else None
    limit = _budget_limit()
    spent = _session_spent_budget(session)
    estimated_next_cost = _estimate_next_cost(tier)

    # --- Deduplication: same query retried after network failure
    cached = is_duplicate_turn(session, query)
    if cached and not reference_lookup and not reference_job_id:
        return _attach_budget_meta(_normalize_success_result(
            {
                **cached,
                "session_id": sid,
                "query_id": qid,
                "resumed": True,
                "user_can_escalate": True,
            }
        ), used=spent, limit=limit, estimated_next_cost=estimated_next_cost)

    # --- Hard anonymous budget gate
    if spent + estimated_next_cost > limit:
        return _build_quota_exhausted_response(
            query=query,
            query_id=qid,
            tier=tier,
            region_id=effective_region_id,
            session_id=sid,
            model=os.getenv("OLLAMA_MODEL", "mistral:latest"),
            used=spent,
            limit=limit,
            estimated_next_cost=estimated_next_cost,
        )

    ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "mistral:latest")
    timeout_s = float(os.getenv("OLLAMA_TIMEOUT", "45"))
    ollama_read_timeout_s = float(os.getenv("OLLAMA_READ_TIMEOUT", "600"))
    if ollama_read_timeout_s <= 0:
        ollama_read_timeout: Optional[float] = None
    else:
        ollama_read_timeout = ollama_read_timeout_s
    num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", "220"))
    retry_timeout_s = float(os.getenv("OLLAMA_RETRY_TIMEOUT", "180"))
    ollama_retry_read_timeout_s = float(os.getenv("OLLAMA_RETRY_READ_TIMEOUT", "900"))
    if ollama_retry_read_timeout_s <= 0:
        ollama_retry_read_timeout: Optional[float] = None
    else:
        ollama_retry_read_timeout = ollama_retry_read_timeout_s
    retry_num_predict = int(os.getenv("OLLAMA_RETRY_NUM_PREDICT", "120"))

    # Fast-scope mode for USDA/GATS style requests: keep latency predictable.
    if fast_scope:
        timeout_s = min(timeout_s, float(os.getenv("FAST_SCOPE_OLLAMA_TIMEOUT", "12")))
        if ollama_read_timeout is None:
            ollama_read_timeout = float(os.getenv("FAST_SCOPE_OLLAMA_READ_TIMEOUT", "20"))
        else:
            ollama_read_timeout = min(ollama_read_timeout, float(os.getenv("FAST_SCOPE_OLLAMA_READ_TIMEOUT", "20")))
        num_predict = min(num_predict, int(os.getenv("FAST_SCOPE_OLLAMA_NUM_PREDICT", "96")))
        retry_timeout_s = min(retry_timeout_s, float(os.getenv("FAST_SCOPE_RETRY_TIMEOUT", "16")))
        if ollama_retry_read_timeout is None:
            ollama_retry_read_timeout = float(os.getenv("FAST_SCOPE_RETRY_READ_TIMEOUT", "24"))
        else:
            ollama_retry_read_timeout = min(
                ollama_retry_read_timeout,
                float(os.getenv("FAST_SCOPE_RETRY_READ_TIMEOUT", "24")),
            )
        retry_num_predict = min(retry_num_predict, int(os.getenv("FAST_SCOPE_RETRY_NUM_PREDICT", "72")))

    lookup_task_timeout = float(os.getenv("FAST_SCOPE_LOOKUP_TIMEOUT", "8")) if fast_scope else float(os.getenv("LOOKUP_TIMEOUT", "25"))
    resource_match_timeout = float(os.getenv("FAST_SCOPE_RESOURCE_MATCH_TIMEOUT", "8")) if fast_scope else float(os.getenv("RESOURCE_MATCH_TIMEOUT", "25"))
    fetch_timeout = float(os.getenv("FAST_SCOPE_FETCH_TIMEOUT", "4")) if fast_scope else float(os.getenv("REFERENCE_FETCH_TIMEOUT", "5"))

    # --- Run independent lookups in parallel to reduce end-to-end latency.
    reference_lookup_task = asyncio.create_task(
        _resolve_reference_lookup(
            query=query,
            tier=tier,
            region_id=effective_region_id,
            trusted=trusted,
            reference_lookup=reference_lookup,
            reference_job_id=reference_job_id,
        )
    )

    # --- Worker 1: retrieve scoped resources
    try:
        resources = await asyncio.wait_for(
            _worker_match_resources(
                query=query,
                tier=tier,
                region_id=effective_region_id,
                trusted=trusted,
            ),
            timeout=resource_match_timeout,
        )
    except asyncio.TimeoutError:
        resources = []

    # --- Worker 2: strip/extract URL content and store in ArangoDB
    fetched_content_map: dict[str, Optional[str]] = {}
    if resources:
        fetched_content_map = await _worker_strip_store_content(
            query_id=qid,
            query=query,
            session_id=sid,
            resources=resources,
            timeout_s=fetch_timeout,
        )

    # --- Worker 3: read from ArangoDB, hydrate resources, prioritize context
    if resources:
        resources = await _worker_read_stored_content(
            query_id=qid,
            query=query,
            resources=resources,
            fetched_content_map=fetched_content_map,
        )
    
    context_block = format_resources_as_context(resources, query=query)
    try:
        reference_meta, web_excerpt_context, lookup_resources = await asyncio.wait_for(
            reference_lookup_task,
            timeout=lookup_task_timeout,
        )
    except asyncio.TimeoutError:
        reference_meta, web_excerpt_context, lookup_resources = (
            {"enabled": True, "status": "timeout", "matches": 0, "filters": {}},
            "",
            [],
        )
    all_resources = _merge_resources(resources, lookup_resources)

    if fast_scope:
        # Deterministic fast response path avoids LLM stalls for site-scoped discovery queries.
        answer = _build_grounded_reference_answer(query, all_resources)
        confidence = score_answer(query, answer, all_resources)
        if force_escalate and not confidence["escalate"]:
            confidence["escalate"] = True
            confidence["escalation_reason"] = "User requested manual escalation"

        result = {
            "query": query,
            "query_id": qid,
            "answer": answer,
            "sources": _build_sources(all_resources, query),
            "reference_lookup": reference_meta,
            "confidence": confidence["confidence"],
            "confidence_label": confidence["label"],
            "escalate": confidence["escalate"],
            "escalation_reason": confidence["escalation_reason"],
            "user_can_escalate": True,
            "session_id": sid,
            "resumed": False,
            "tier": tier,
            "region_id": effective_region_id,
            "model": model,
        }
        result = _normalize_success_result(result)
        spent_after = spent + _turn_cost(result)
        result = _attach_budget_meta(
            result,
            used=spent_after,
            limit=limit,
            estimated_next_cost=_estimate_next_cost(tier),
        )
        await save_turn(sid, make_turn(query, result), region_id=effective_region_id, tier=tier, trusted=trusted)
        return result

    # --- Step 2: build grounded prompt
    if context_block or web_excerpt_context:
        merged_context = "\n\n".join(part for part in [context_block, web_excerpt_context] if part)
        system_note = (
            "You are a trade and agricultural compliance assistant. "
            "Answer the user question using ONLY the provided resources where possible. "
            "Cite the resource title and URL when relevant. "
            "Do not cite or mention any URL that is not present in the provided resources. "
            "If exact numeric values are missing, state that clearly and provide the best next sources from context. "
            "Do NOT mention model identity, AI limitations, coding focus, or inability to access the internet. "
            "Stay grounded to the provided references and respond as a support analyst.\n\n"
            f"{merged_context}\n\n"
        )
    else:
        system_note = (
            "You are a concise trade and agricultural compliance assistant. "
            "Answer the user question directly. "
            "If context is missing, say what is missing.\n\n"
        )

    prompt = f"{system_note}Question: {query}"

    sources = _build_sources(all_resources, query)

    try:
        data = await _ollama_generate(
            ollama_url=ollama_url,
            model=model,
            prompt=prompt,
            timeout_s=timeout_s,
            read_timeout_s=ollama_read_timeout,
            num_predict=num_predict,
        )

        answer = data.get("response", "").strip() or "No response generated."
        answer = _ensure_grounded_answer(answer, query, all_resources)
        confidence = score_answer(query, answer, all_resources)

        # User manual override: escalate regardless of computed score
        if force_escalate and not confidence["escalate"]:
            confidence["escalate"] = True
            confidence["escalation_reason"] = "User requested manual escalation"

        result = {
            "query": query,
            "query_id": qid,
            "answer": answer,
            "sources": sources,
            "reference_lookup": reference_meta,
            "confidence": confidence["confidence"],
            "confidence_label": confidence["label"],
            "escalate": confidence["escalate"],
            "escalation_reason": confidence["escalation_reason"],
            "user_can_escalate": True,
            "session_id": sid,
            "resumed": False,
            "tier": tier,
            "region_id": effective_region_id,
            "model": model,
        }
        result = _normalize_success_result(result)
        spent_after = spent + _turn_cost(result)
        result = _attach_budget_meta(
            result,
            used=spent_after,
            limit=limit,
            estimated_next_cost=_estimate_next_cost(tier),
        )

        # Persist turn (non-fatal — checkpoint failure must not break the response)
        await save_turn(sid, make_turn(query, result), region_id=effective_region_id, tier=tier, trusted=trusted)

        return result
    except httpx.TimeoutException:
        # Retry once with a compact prompt and stricter token budget.
        retry_prompt = _short_retry_prompt(query, resources)
        try:
            retry_data = await _ollama_generate(
                ollama_url=ollama_url,
                model=model,
                prompt=retry_prompt,
                timeout_s=retry_timeout_s,
                read_timeout_s=ollama_retry_read_timeout,
                num_predict=retry_num_predict,
            )

            answer = retry_data.get("response", "").strip() or "No response generated."
            answer = _ensure_grounded_answer(answer, query, all_resources)
            confidence = score_answer(query, answer, all_resources)

            if force_escalate and not confidence["escalate"]:
                confidence["escalate"] = True
                confidence["escalation_reason"] = "User requested manual escalation"

            result = {
                "query": query,
                "query_id": qid,
                "answer": answer,
                "sources": sources,
                "reference_lookup": reference_meta,
                "confidence": confidence["confidence"],
                "confidence_label": confidence["label"],
                "escalate": confidence["escalate"],
                "escalation_reason": confidence["escalation_reason"],
                "user_can_escalate": True,
                "session_id": sid,
                "resumed": False,
                "tier": tier,
                "region_id": effective_region_id,
                "model": model,
            }
            result = _normalize_success_result(result)
            spent_after = spent + _turn_cost(result)
            result = _attach_budget_meta(
                result,
                used=spent_after,
                limit=limit,
                estimated_next_cost=_estimate_next_cost(tier),
            )
            await save_turn(sid, make_turn(query, result), region_id=effective_region_id, tier=tier, trusted=trusted)
            return result
        except httpx.TimeoutException:
            grounded_fallback_answer = _build_grounded_reference_answer(query, all_resources)
            fallback = _build_unverified_fallback(
                query=query,
                tier=tier,
                region_id=effective_region_id,
                session_id=sid,
                model=model,
                reason="LLM unavailable: timeout",
            )
            fallback["query_id"] = qid
            fallback["answer"] = grounded_fallback_answer
            fallback["sources"] = sources
            fallback["reference_lookup"] = reference_meta
            spent_after = spent + _turn_cost(fallback)
            return _attach_budget_meta(
                fallback,
                used=spent_after,
                limit=limit,
                estimated_next_cost=_estimate_next_cost(tier),
            )
    except Exception as exc:
        reason = f"LLM unavailable: {exc}" if str(exc) else "LLM unavailable: unknown error"
        grounded_fallback_answer = _build_grounded_reference_answer(query, all_resources)
        fallback = _build_unverified_fallback(
            query=query,
            tier=tier,
            region_id=effective_region_id,
            session_id=sid,
            model=model,
            reason=reason,
        )
        fallback["query_id"] = qid
        fallback["answer"] = grounded_fallback_answer
        fallback["sources"] = _build_sources(all_resources, query)
        fallback["reference_lookup"] = reference_meta
        spent_after = spent + _turn_cost(fallback)
        return _attach_budget_meta(
            fallback,
            used=spent_after,
            limit=limit,
            estimated_next_cost=_estimate_next_cost(tier),
        )
