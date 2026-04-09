"""
Confidence scoring for RAG answers.

Score range: 0.0 – 1.0
  >= 0.70  → satisfactory, no escalation needed
    0.40–0.69 → borderline, offer user "was this helpful?" with manual escalation option
    < 0.40   → low confidence, manual escalation available

Score is derived from three independent signals:
  1. Retrieval coverage  – how many resources were returned, and how good are they
  2. Source quality      – rank of the best source_type among returned resources
  3. Model uncertainty   – hedge phrases detected in the LLM answer text

Hard overrides (force low confidence regardless of score):
  - Zero resources returned from ArangoDB
  - Query contains a high-severity keyword (sanctions, fraud, dispute, legal)
  - LLM answer is empty or contains a failure message
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
SATISFACTORY = 0.70
BORDERLINE_LOW = 0.40

# ---------------------------------------------------------------------------
# Signal 1: source_type quality rank (higher = better evidence)
# ---------------------------------------------------------------------------
_SOURCE_TYPE_RANK: dict[str, float] = {
    "regulation_summary": 1.0,
    "policy": 0.9,
    "certification": 0.85,
    "product_doc": 0.75,
    "runbook": 0.70,
    "faq": 0.60,
    "trade_portal": 0.55,
    "logistics_hub": 0.50,
    "market_guide": 0.45,
    "trade_fair": 0.35,
}

# ---------------------------------------------------------------------------
# Signal 3: hedge phrases that indicate the model is uncertain
# ---------------------------------------------------------------------------
_HEDGE_PHRASES = [
    "i don't know",
    "i do not know",
    "i'm not sure",
    "i am not sure",
    "i cannot confirm",
    "i can not confirm",
    "unable to confirm",
    "unable to provide",
    "no information available",
    "no relevant information",
    "consult a",
    "consult an",
    "please contact",
    "seek professional",
    "seek legal",
    "not covered",
    "outside my knowledge",
    "i lack",
    "cannot answer",
    "can't answer",
]

# ---------------------------------------------------------------------------
# Hard-escalation keywords in the user query
# ---------------------------------------------------------------------------
_HIGH_SEVERITY_KEYWORDS = [
    "sanction",
    "embargo",
    "fraud",
    "dispute",
    "legal action",
    "lawsuit",
    "criminal",
    "money laundering",
    "terrorist",
    "restricted party",
]


def _retrieval_score(resources: list[dict]) -> float:
    """Score based on number of resources returned (capped at 5 for full score)."""
    n = len(resources)
    if n == 0:
        return 0.0
    # 1 resource = 0.4, 3 = 0.7, 5+ = 1.0
    return min(1.0, 0.2 + (n * 0.16))


def _source_quality_score(resources: list[dict]) -> float:
    """Best source_type rank among returned resources."""
    if not resources:
        return 0.0
    ranks = [_SOURCE_TYPE_RANK.get(r.get("source_type", ""), 0.3) for r in resources]
    return max(ranks)


def _uncertainty_penalty(answer: str) -> float:
    """
    Returns a penalty (0.0–1.0) based on hedge phrase density.
    0.0 = no hedging detected, 1.0 = strong uncertainty.
    """
    lower = answer.lower()
    hits = sum(1 for phrase in _HEDGE_PHRASES if phrase in lower)
    # Each hit adds 0.25 penalty, capped at 1.0
    return min(1.0, hits * 0.25)


def score_answer(
    query: str,
    answer: str,
    resources: list[dict],
) -> dict:
    """
    Compute a confidence score and escalation decision for a RAG answer.

    Returns:
        {
            "confidence": float,          # 0.0–1.0
            "escalate": bool,             # False by default; Jira escalation is user-triggered
            "escalation_reason": str,     # human-readable guidance/reason
            "label": str,                 # "satisfactory" | "borderline" | "low"
        }
    """
    answer_lower = answer.lower()

    # --- Hard override: no resources at all (low confidence, manual escalation only)
    if not resources:
        return _decision(
            0.2,
            False,
            "No supporting resources found in knowledge base; use Brave Ask cross-reference and escalate manually if needed",
        )

    # --- Hard override: LLM failure message (manual escalation only)
    if "unable to generate" in answer_lower or not answer.strip():
        return _decision(0.1, False, "LLM failed to produce a reliable answer; manual escalation recommended")

    # --- Hard override: high-severity query keyword (manual escalation only)
    query_lower = query.lower()
    for kw in _HIGH_SEVERITY_KEYWORDS:
        if kw in query_lower:
            return _decision(0.35, False, f"High-severity topic detected: '{kw}' — manual escalation recommended")

    # --- Compute composite score
    r_score = _retrieval_score(resources)       # weight 0.40
    q_score = _source_quality_score(resources)  # weight 0.35
    penalty = _uncertainty_penalty(answer)       # weight 0.25 (subtracted)

    raw = (r_score * 0.40) + (q_score * 0.35) + ((1.0 - penalty) * 0.25)
    confidence = round(max(0.0, min(1.0, raw)), 3)

    if confidence >= SATISFACTORY:
        return _decision(confidence, False, "")
    elif confidence >= BORDERLINE_LOW:
        return _decision(confidence, False, "borderline — offer user manual escalation option")
    else:
        return _decision(confidence, False, "Low confidence: insufficient evidence or high uncertainty; manual escalation available")


def _decision(confidence: float, escalate: bool, reason: str) -> dict:
    if confidence >= SATISFACTORY:
        label = "satisfactory"
    elif confidence >= BORDERLINE_LOW:
        label = "borderline"
    else:
        label = "low"

    return {
        "confidence": confidence,
        "escalate": escalate,
        "escalation_reason": reason,
        "label": label,
    }
