from __future__ import annotations

from typing import Any, Literal, Optional

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, ValidationError, model_validator
from typing_extensions import TypedDict

from app.chains.rag import query_rag
from app.checkpointer.langgraph_arango import ArangoCheckpointer


class ValidationState(TypedDict, total=False):
    thread_id: str
    query: str
    tier: str
    region_id: Optional[str]
    trusted: bool
    max_attempts: int
    attempt: int
    answer: str
    sources: list[dict[str, Any]]
    validation_errors: list[str]
    valid: bool
    status: str


class SourceRef(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None


class GeneratedAnswer(BaseModel):
    answer: str = Field(min_length=10)
    sources: list[SourceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_sources(self) -> "GeneratedAnswer":
        if not self.sources:
            raise ValueError("At least one source is required")
        return self


async def generate_step(state: ValidationState) -> ValidationState:
    attempt = state.get("attempt", 0) + 1
    rag = await query_rag(
        state["query"],
        tier=state.get("tier", "broad"),
        region_id=state.get("region_id"),
        trusted=state.get("trusted", False),
        session_id=state.get("thread_id"),
    )

    return {
        **state,
        "attempt": attempt,
        "answer": rag.get("answer", ""),
        "sources": rag.get("sources", []),
        "status": "generated",
    }


def validate_step(state: ValidationState) -> ValidationState:
    try:
        GeneratedAnswer(
            answer=state.get("answer", ""),
            sources=state.get("sources", []),
        )
        return {
            **state,
            "valid": True,
            "validation_errors": [],
            "status": "validated",
        }
    except ValidationError as exc:
        return {
            **state,
            "valid": False,
            "validation_errors": [err.get("msg", "validation error") for err in exc.errors()],
            "status": "retry_required",
        }


def route_after_validation(state: ValidationState) -> Literal["generate", "persist"]:
    if state.get("valid"):
        return "persist"
    if state.get("attempt", 0) >= state.get("max_attempts", 3):
        return "persist"
    return "generate"


def persist_step(state: ValidationState) -> ValidationState:
    return {
        **state,
        "status": "completed",
    }


def build_validation_graph():
    builder = StateGraph(ValidationState)
    builder.add_node("generate", generate_step)
    builder.add_node("validate", validate_step)
    builder.add_node("persist", persist_step)

    builder.add_edge(START, "generate")
    builder.add_edge("generate", "validate")
    builder.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "generate": "generate",
            "persist": "persist",
        },
    )
    builder.add_edge("persist", END)

    return builder.compile(checkpointer=ArangoCheckpointer())


VALIDATION_GRAPH = build_validation_graph()


async def run_validation_workflow(
    *,
    thread_id: str,
    query: str,
    tier: str = "broad",
    region_id: Optional[str] = None,
    trusted: bool = False,
    max_attempts: int = 3,
    checkpoint_id: Optional[str] = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
        },
        "run_name": "validation_workflow",
        "tags": ["workflow", "validation", tier],
        "metadata": {
            "thread_id": thread_id,
            "region_id": region_id,
            "trusted": trusted,
            "max_attempts": max_attempts,
        },
    }
    if checkpoint_id:
        config["configurable"]["checkpoint_id"] = checkpoint_id

    initial_state: ValidationState = {
        "thread_id": thread_id,
        "query": query,
        "tier": tier,
        "region_id": region_id,
        "trusted": trusted,
        "max_attempts": max_attempts,
        "attempt": 0,
        "status": "started",
    }

    final_state = await VALIDATION_GRAPH.ainvoke(initial_state, config=config)
    latest = await VALIDATION_GRAPH.aget_state(config)

    return {
        "thread_id": thread_id,
        "checkpoint_id": latest.config.get("configurable", {}).get("checkpoint_id"),
        "status": final_state.get("status"),
        "attempt": final_state.get("attempt", 0),
        "valid": final_state.get("valid", False),
        "validation_errors": final_state.get("validation_errors", []),
        "answer": final_state.get("answer"),
        "sources": final_state.get("sources", []),
    }


async def resume_validation_workflow(
    *,
    thread_id: str,
    query: str,
    tier: str = "broad",
    region_id: Optional[str] = None,
    trusted: bool = False,
    max_attempts: int = 3,
) -> dict[str, Any]:
    # Resuming by thread_id reads the latest checkpoint in this namespace.
    return await run_validation_workflow(
        thread_id=thread_id,
        query=query,
        tier=tier,
        region_id=region_id,
        trusted=trusted,
        max_attempts=max_attempts,
    )
