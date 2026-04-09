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
from urllib.parse import quote_plus, urlparse

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

_QUERYABLE_SITE_RULES: list[dict[str, str]] = [
    {
        "domain": "apps.fas.usda.gov",
        "path_prefix": "/gats",
        "title": "USDA GATS query results",
        "source": "USDA FAS GATS",
    },
    {
        "domain": "fas.usda.gov",
        "path_prefix": "/",
        "title": "USDA FAS site search results",
        "source": "USDA FAS",
    },
]


def _query_mentions_usda_gats(query: str) -> bool:
    q = (query or "").lower()
    return any(token in q for token in ["usda", "fas", "gats", "global agricultural trade system"])


def _get_arango_connection_params() -> dict:
    """Extract ArangoDB connection parameters from environment."""
    arango_url = os.getenv("ARANGO_URL", "").rstrip("/")
    if not arango_url:
        arango_host = os.getenv("ARANGO_HOST", "host.docker.internal")
        arango_port = os.getenv("ARANGO_PORT", "8529")
        arango_url = f"http://{arango_host}:{arango_port}"
    
    return {
        "url": arango_url,
        "db": os.getenv("ARANGO_DB", "agri_dao"),
        "user": os.getenv("ARANGO_USER", "system"),
        "password": os.getenv("ARANGO_ROOT_PASSWORD") or os.getenv("ARANGO_PASSWORD", ""),
        "timeout": float(os.getenv("ARANGO_TIMEOUT", "10")),
    }


async def _ensure_site_rules_collection() -> None:
    """Ensure queryable_site_rules collection exists with default rules on startup."""
    params = _get_arango_connection_params()
    endpoint = f"{params['url']}/_db/{params['db']}/_api/collection"
    collection_name = "queryable_site_rules"
    
    try:
        async with httpx.AsyncClient(timeout=params["timeout"]) as client:
            # Check if collection exists
            resp = await client.get(
                f"{params['url']}/_db/{params['db']}/_api/collection/{collection_name}",
                auth=(params["user"], params["password"]),
            )
            
            if resp.status_code == 404:
                # Create collection
                await client.post(
                    endpoint,
                    json={"name": collection_name, "type": 2},
                    auth=(params["user"], params["password"]),
                )
            
            # Upsert default rules (replace any existing ones)
            for i, rule in enumerate(_QUERYABLE_SITE_RULES):
                rule_doc = {
                    "_key": f"rule_{i}",
                    **rule,
                }
                insert_endpoint = f"{params['url']}/_db/{params['db']}/_api/document/{collection_name}"
                await client.post(
                    insert_endpoint,
                    json=rule_doc,
                    params={"overwrite": "true"},
                    auth=(params["user"], params["password"]),
                )
    except Exception as e:
        # Non-fatal: fallback to defaults will be used
        pass


async def _get_queryable_site_rules() -> list[dict]:
    """Fetch queryable site rules from ArangoDB, fallback to defaults on error."""
    params = _get_arango_connection_params()
    endpoint = f"{params['url']}/_db/{params['db']}/_api/cursor"
    
    aql = "FOR doc IN queryable_site_rules RETURN doc"
    payload = {"query": aql}
    
    try:
        async with httpx.AsyncClient(timeout=params["timeout"]) as client:
            resp = await client.post(
                endpoint,
                json=payload,
                auth=(params["user"], params["password"]),
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            rules = data.get("result", [])
            if rules:
                # Remove ArangoDB internal fields
                return [
                    {k: v for k, v in rule.items() if not k.startswith("_")}
                    for rule in rules
                ]
    except Exception:
        pass
    
    # Fallback to defaults
    return _QUERYABLE_SITE_RULES

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
    params = _get_arango_connection_params()

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
    endpoint = f"{params['url']}/_db/{params['db']}/_api/cursor"

    try:
        async with httpx.AsyncClient(timeout=params["timeout"]) as client:
            resp = await client.post(
                endpoint,
                json=payload,
                auth=(params["user"], params["password"]),
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("result", [])
    except Exception:
        return []


async def _build_site_query_resources(resources: list[dict], query: str) -> list[dict]:
    if not query:
        return []

    site_rules = await _get_queryable_site_rules()
    queryable: list[dict] = []
    seen_urls: set[str] = set()

    for resource in resources:
        url = str(resource.get("url") or "").strip()
        if not url:
            continue

        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        path = parsed.path or "/"

        for rule in site_rules:
            if rule["domain"] not in host:
                continue
            if not path.startswith(rule["path_prefix"]):
                continue

            site_scope = f"site:{rule['domain']}{rule['path_prefix']}"
            site_query_url = f"https://search.brave.com/ask?q={quote_plus(site_scope + ' ' + query)}"
            if site_query_url in seen_urls:
                continue

            seen_urls.add(site_query_url)
            queryable.append({
                "title": f"{rule['title']} ({query})",
                "url": site_query_url,
                "description": (
                    f"Domain-scoped query results for '{query}' against {rule['domain']}{rule['path_prefix']}."
                ),
                "source": rule["source"],
                "source_type": "web_search",
                "topic": resource.get("topic", "pricing"),
                "tags": ["site_query", "usda", "gats"],
                "visibility": "public",
            })

    return queryable


async def _build_direct_site_query_resources(query: str) -> list[dict]:
    if not _query_mentions_usda_gats(query):
        return []

    site_rules = await _get_queryable_site_rules()
    resources: list[dict] = []
    seen_urls: set[str] = set()
    for rule in site_rules:
        site_scope = f"site:{rule['domain']}{rule['path_prefix']}"
        site_query_url = f"https://search.brave.com/ask?q={quote_plus(site_scope + ' ' + query)}"
        if site_query_url in seen_urls:
            continue
        seen_urls.add(site_query_url)
        resources.append({
            "title": f"{rule['title']} ({query})",
            "url": site_query_url,
            "description": (
                f"Domain-scoped query results for '{query}' against {rule['domain']}{rule['path_prefix']}."
            ),
            "source": rule["source"],
            "source_type": "web_search",
            "topic": "pricing",
            "tags": ["site_query", "usda", "gats"],
            "visibility": "public",
        })
    return resources


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
    # Prefer query-inferred geography when present; caller region can be stale UI state.
    inferred_region = infer_region_from_query(query) or region_id
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

    if not resources:
        # Relax region filter but keep topical+tier intent.
        resources = await search_resources(
            query=query,
            tier=tier,
            region_id=None,
            trusted=trusted,
            topic_filters=inferred_topics or None,
            require_url=True,
            limit_override=max_urls,
        )

    if not resources:
        # Last resort: broad URL references across all regions/topics.
        resources = await search_resources(
            query=query,
            tier="broad",
            region_id=None,
            trusted=trusted,
            topic_filters=None,
            require_url=True,
            limit_override=max_urls,
        )

    if resources:
        site_query_resources = await _build_site_query_resources(resources, query)
        if site_query_resources:
            resources = [*resources, *site_query_resources][:max_urls]

    if not resources:
        direct_site_query = await _build_direct_site_query_resources(query)
        if direct_site_query:
            resources = direct_site_query[:max_urls]

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
