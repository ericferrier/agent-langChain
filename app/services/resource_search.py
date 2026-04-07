"""
Tiered resource search against ArangoDB `resource` collection.

Search tiers (applied in order by the RAG chain):
  broad      – all resources, keyword match only
  compliance – regulatory, policy, certification, product_doc sources
  fulfillment – logistics, trade portal, runbook, market_guide sources
    pricing    – produce price and market trend resources
"""
import json
import os
import re
from typing import Optional

import httpx

REGION_KEYWORDS: dict[str, list[str]] = {
    "africa": ["africa", "nigeria", "kenya", "ghana", "south africa", "ethiopia"],
    "caribbean": ["caribbean", "jamaica", "barbados", "trinidad", "dominican"],
    "central_america": ["central america", "guatemala", "panama", "costa rica", "honduras"],
    "east_asia": ["east asia", "china", "japan", "korea", "taiwan", "hong kong"],
    "european_union": ["eu", "european union", "europe", "schengen"],
    "gulf_cooperation_council": ["gcc", "gulf", "uae", "saudi", "qatar", "oman", "bahrain", "kuwait"],
    "nordic_market": ["nordic", "sweden", "norway", "finland", "denmark", "iceland"],
    "north_america": ["north america", "united states", "usa", "canada", "mexico", "us"],
    "south_america": ["south america", "brazil", "argentina", "chile", "peru", "colombia"],
    "southeast_asia": ["southeast asia", "asean", "singapore", "thailand", "vietnam", "malaysia", "indonesia", "philippines"],
}

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "export-documents": ["export", "documents", "customs", "clearance", "certificate", "coo", "hs code", "incoterm"],
    "compliance-region": ["compliance", "regulation", "policy", "restriction", "license", "permit"],
    "shipping-logistics": ["shipping", "freight", "logistics", "port", "vessel", "carrier", "incoterms"],
    "marketplace-listing": ["marketplace", "listing", "catalog", "buyer", "seller", "product posting"],
    "pricing": ["price", "pricing", "market rate", "index", "trend", "quotation"],
}

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------
SEARCH_TIERS: dict[str, dict] = {
    "broad": {
        "description": "All resources; no source_type or topic restriction",
        "source_types": [],  # empty = no filter
        "topics": [],
        "limit": 10,
    },
    "compliance": {
        "description": "Regulatory, certification, and policy documents",
        "source_types": [
            "regulation_summary",
            "policy",
            "certification",
            "product_doc",
        ],
        "topics": ["export-documents", "compliance-region"],
        "limit": 8,
    },
    "fulfillment": {
        "description": "Shipping, logistics, and marketplace listing resources",
        "source_types": [
            "logistics_hub",
            "trade_portal",
            "runbook",
            "market_guide",
            "trade_fair",
        ],
        "topics": ["shipping-logistics", "marketplace-listing"],
        "limit": 8,
    },
    "pricing": {
        "description": "Produce pricing feeds, indices, and market trend references",
        "source_types": [
            "trade_portal",
            "market_guide",
            "product_doc",
            "directory",
            "runbook",
        ],
        "topics": ["pricing"],
        "limit": 8,
    },
}

# Common words to strip before building keyword filters
_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "in", "on", "at", "to", "of",
    "is", "are", "was", "how", "what", "where", "do", "i", "my", "me",
    "with", "from", "about", "this", "that", "it", "be", "can",
}


def _extract_keywords(query: str, max_kw: int = 3) -> list[str]:
    tokens = query.lower().split()
    keywords = [t.strip(".,?!;:\"'") for t in tokens if t not in _STOPWORDS and len(t) > 2]
    return keywords[:max_kw]


def infer_region_from_query(query: str) -> Optional[str]:
    q = query.lower()
    best_region: Optional[str] = None
    best_score = 0
    for region_id, aliases in REGION_KEYWORDS.items():
        score = sum(1 for alias in aliases if alias in q)
        if score > best_score:
            best_region = region_id
            best_score = score
    return best_region if best_score > 0 else None


def infer_topics_from_query(query: str) -> list[str]:
    q = query.lower()
    topics: list[str] = []
    for topic, aliases in TOPIC_KEYWORDS.items():
        if any(alias in q for alias in aliases):
            topics.append(topic)
    return topics


def _query_terms(query: str, limit: int = 8) -> list[str]:
    terms = [t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 2]
    return terms[:limit]


def _best_content_snippet(content: str, query: str, max_chars: int = 700) -> str:
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


def _build_aql(
    keywords: list[str],
    tier: str,
    region_id: Optional[str],
    trusted: bool = False,
    topic_filters: Optional[list[str]] = None,
    require_url: bool = False,
    limit_override: Optional[int] = None,
) -> tuple[str, dict]:
    cfg = SEARCH_TIERS.get(tier, SEARCH_TIERS["broad"])
    collection = os.getenv("ARANGO_REFERENCE_COLLECTION", "resource").strip() or "resource"
    bind_vars: dict = {"limit": int(limit_override or cfg["limit"]), "@collection": collection}
    filters: list[str] = []

    # --- keyword filter (title OR description OR any tag)
    if keywords:
        kw_clauses: list[str] = []
        for i, kw in enumerate(keywords):
            key = f"kw{i}"
            bind_vars[key] = f"%{kw}%"
            kw_clauses.append(
                f"(LOWER(r.title) LIKE @{key} "
                f"OR LOWER(r.description) LIKE @{key} "
                f"OR LENGTH(r.tags[* FILTER LOWER(CURRENT) LIKE @{key}]) > 0)"
            )
        filters.append(f"({' OR '.join(kw_clauses)})")

    # --- source_type tier filter
    if cfg["source_types"]:
        bind_vars["source_types"] = cfg["source_types"]
        filters.append("r.source_type IN @source_types")

    # --- topic tier filter
    selected_topics = topic_filters if topic_filters else cfg["topics"]
    if selected_topics:
        bind_vars["topics"] = selected_topics
        filters.append("r.topic IN @topics")

    # --- visibility: anonymous callers see public only; trusted accounts see all
    if not trusted:
        filters.append("r.visibility == 'public'")

    # --- optional region scope
    if region_id:
        bind_vars["region_id"] = region_id
        filters.append("@region_id IN r.region_ids")

    if require_url:
        filters.append("HAS(r, 'url') AND r.url != null AND LENGTH(TRIM(r.url)) > 0")

    where = ("FILTER " + "\n  FILTER ".join(filters)) if filters else ""

    aql = (
        "FOR r IN @@collection\n"
        f"  {where}\n"
        "  SORT r.title ASC\n"
        "  LIMIT @limit\n"
        "  RETURN KEEP(r, ['_key','title','url','description','source_type','topic','tags'])"
    )
    return aql, bind_vars


async def search_resources(
    query: str,
    tier: str = "broad",
    region_id: Optional[str] = None,
    trusted: bool = False,
    topic_filters: Optional[list[str]] = None,
    require_url: bool = False,
    limit_override: Optional[int] = None,
) -> list[dict]:
    """
    Run a tiered keyword search against ArangoDB and return matching resources.

    trusted=False  → only resources with visibility="public" are returned.
    trusted=True   → resources with any visibility are returned (verified accounts).

    Returns an empty list on any error so the RAG chain degrades gracefully.
    """
    arango_url = os.getenv("ARANGO_URL", "").rstrip("/")
    if not arango_url:
        arango_host = os.getenv("ARANGO_HOST", "host.docker.internal")
        arango_port = os.getenv("ARANGO_PORT", "8529")
        arango_url = f"http://{arango_host}:{arango_port}"
    arango_db = os.getenv("ARANGO_DB", "agri_dao")
    arango_user = os.getenv("ARANGO_USER", "system")
    arango_pass = os.getenv("ARANGO_ROOT_PASSWORD") or os.getenv("ARANGO_PASSWORD", "")
    timeout_s = float(os.getenv("ARANGO_TIMEOUT", "10"))

    keywords = _extract_keywords(query)
    aql, bind_vars = _build_aql(
        keywords,
        tier,
        region_id,
        trusted=trusted,
        topic_filters=topic_filters,
        require_url=require_url,
        limit_override=limit_override,
    )

    payload = {"query": aql, "bindVars": bind_vars}
    endpoint = f"{arango_url}/_db/{arango_db}/_api/cursor"

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                endpoint,
                json=payload,
                auth=(arango_user, arango_pass),
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("result", [])
    except Exception:
        return []


async def search_reference_urls(
    query: str,
    tier: str = "broad",
    region_id: Optional[str] = None,
    trusted: bool = False,
    max_urls: int = 6,
) -> dict:
    """
    Search URL-backed references scoped by query-inferred region and topic.

    Returns metadata with inferred filters for observability and debugging.
    """
    inferred_region = region_id or infer_region_from_query(query)
    inferred_topics = infer_topics_from_query(query)

    resources = await search_resources(
        query=query,
        tier=tier,
        region_id=inferred_region,
        trusted=trusted,
        topic_filters=inferred_topics or None,
        require_url=True,
        limit_override=max_urls,
    )

    if not resources:
        # Relax keyword requirement and keep tier/topic/region filters.
        resources = await search_resources(
            query="",
            tier=tier,
            region_id=inferred_region,
            trusted=trusted,
            topic_filters=inferred_topics or None,
            require_url=True,
            limit_override=max_urls,
        )

    return {
        "resources": resources,
        "filters": {
            "region_id": inferred_region,
            "topics": inferred_topics,
            "tier": tier,
        },
    }


def format_resources_as_context(resources: list[dict], query: str = "") -> str:
    """Format a resource list into a compact context block for the LLM prompt.
    
    Includes fetched_content if available, otherwise uses description.
    """
    if not resources:
        return ""
    lines = ["Relevant trade/compliance resources:"]
    content_blocks = 0
    for r in resources:
        title = r.get("title", "")
        url = r.get("url", "")
        source_type = r.get("source_type", "")
        
        # Prefer fetched content over description
        content = r.get("fetched_content")
        if content and content_blocks < 5:
            lines.append(f"\n- [{source_type}] {title}")
            if url:
                lines.append(f"  URL: {url}")
            # Keep per-resource snippet compact to reduce LLM timeout risk.
            lines.append(f"  Content: {_best_content_snippet(content, query, max_chars=700)}")
            content_blocks += 1
        else:
            desc = r.get("description", "")[:200]
            lines.append(f"\n- [{source_type}] {title}")
            if desc:
                lines.append(f"  {desc}")
            if url:
                lines.append(f"  URL: {url}")
    return "\n".join(lines)
