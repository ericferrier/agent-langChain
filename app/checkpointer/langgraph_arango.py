from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterator, Sequence

import httpx
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    WRITES_IDX_MAP,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langchain_core.runnables import RunnableConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class ArangoCheckpointer(BaseCheckpointSaver[str]):
    """LangGraph checkpointer backed by ArangoDB JSON documents."""

    collection = "langgraph_checkpoints"

    async def _ensure_collection(self, client: httpx.AsyncClient) -> None:
        try:
            await client.post(
                f"{_arango_base()}/_api/collection",
                json={"name": self.collection, "type": 2},
                auth=_auth(),
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise

    async def _aql(self, query: str, bind_vars: dict[str, Any]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            await self._ensure_collection(client)
            resp = await client.post(
                f"{_arango_base()}/_api/cursor",
                json={"query": query, "bindVars": bind_vars},
                auth=_auth(),
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            payload = resp.json()
            return payload.get("result", [])

    def _checkpoint_ns(self, config: RunnableConfig) -> str:
        return config.get("configurable", {}).get("checkpoint_ns", "")

    def _base_doc(
        self,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
        parent_checkpoint_id: str | None,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
    ) -> dict[str, Any]:
        return {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": parent_checkpoint_id,
            "checkpoint": checkpoint,
            "metadata": metadata,
            "pending_writes": [],
            "updated_at": _now(),
            "created_at": _now(),
        }

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = self._checkpoint_ns(config)
        checkpoint_id = get_checkpoint_id(config)

        query = (
            "FOR c IN @@collection "
            "FILTER c.thread_id == @thread_id "
            "AND c.checkpoint_ns == @checkpoint_ns "
            "AND (@checkpoint_id == null OR c.checkpoint_id == @checkpoint_id) "
            "SORT c.created_at DESC LIMIT 1 RETURN c"
        )
        rows = await self._aql(
            query,
            {
                "@collection": self.collection,
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            },
        )
        if not rows:
            return None

        doc = rows[0]
        parent_config = None
        if doc.get("parent_checkpoint_id"):
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": doc.get("parent_checkpoint_id"),
                }
            }

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": doc["checkpoint_id"],
                }
            },
            checkpoint=doc["checkpoint"],
            metadata=doc.get("metadata", {}),
            parent_config=parent_config,
            pending_writes=[
                (w["task_id"], w["channel"], w.get("value"))
                for w in doc.get("pending_writes", [])
            ],
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        import asyncio

        return asyncio.run(self.aget_tuple(config))

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        thread_id = None
        checkpoint_ns = None
        if config:
            thread_id = config.get("configurable", {}).get("thread_id")
            checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        before_checkpoint_id = get_checkpoint_id(before) if before else None
        limit = limit or 50

        query = (
            "FOR c IN @@collection "
            "FILTER (@thread_id == null OR c.thread_id == @thread_id) "
            "AND (@checkpoint_ns == null OR c.checkpoint_ns == @checkpoint_ns) "
            "AND (@before_checkpoint_id == null OR c.checkpoint_id < @before_checkpoint_id) "
            "SORT c.created_at DESC LIMIT @limit RETURN c"
        )

        rows = await self._aql(
            query,
            {
                "@collection": self.collection,
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "before_checkpoint_id": before_checkpoint_id,
                "limit": limit,
            },
        )

        for doc in rows:
            metadata = doc.get("metadata", {})
            if filter and not all(metadata.get(k) == v for k, v in filter.items()):
                continue

            parent_config = None
            if doc.get("parent_checkpoint_id"):
                parent_config = {
                    "configurable": {
                        "thread_id": doc["thread_id"],
                        "checkpoint_ns": doc["checkpoint_ns"],
                        "checkpoint_id": doc.get("parent_checkpoint_id"),
                    }
                }

            yield CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": doc["thread_id"],
                        "checkpoint_ns": doc["checkpoint_ns"],
                        "checkpoint_id": doc["checkpoint_id"],
                    }
                },
                checkpoint=doc["checkpoint"],
                metadata=metadata,
                parent_config=parent_config,
                pending_writes=[
                    (w["task_id"], w["channel"], w.get("value"))
                    for w in doc.get("pending_writes", [])
                ],
            )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        import asyncio

        async def _collect() -> list[CheckpointTuple]:
            return [item async for item in self.alist(config, filter=filter, before=before, limit=limit)]

        for item in asyncio.run(_collect()):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        del new_versions  # Versions are preserved inside native checkpoint payload.

        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = self._checkpoint_ns(config)
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

        doc = self._base_doc(
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
            checkpoint_id=checkpoint_id,
            parent_checkpoint_id=parent_checkpoint_id,
            checkpoint=checkpoint,
            metadata=get_checkpoint_metadata(config, metadata),
        )

        query = (
            "UPSERT { thread_id: @thread_id, checkpoint_ns: @checkpoint_ns, checkpoint_id: @checkpoint_id } "
            "INSERT @doc "
            "UPDATE MERGE(OLD, @doc, { created_at: OLD.created_at, pending_writes: OLD.pending_writes }) "
            "IN @@collection"
        )

        await self._aql(
            query,
            {
                "@collection": self.collection,
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "doc": doc,
            },
        )

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        import asyncio

        return asyncio.run(self.aput(config, checkpoint, metadata, new_versions))

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = self._checkpoint_ns(config)
        checkpoint_id = config["configurable"]["checkpoint_id"]

        normalized_writes = []
        for idx, (channel, value) in enumerate(writes):
            normalized_writes.append(
                {
                    "task_id": task_id,
                    "task_path": task_path,
                    "channel": channel,
                    "index": WRITES_IDX_MAP.get(channel, idx),
                    "value": value,
                    "created_at": _now(),
                }
            )

        query = (
            "FOR c IN @@collection "
            "FILTER c.thread_id == @thread_id "
            "AND c.checkpoint_ns == @checkpoint_ns "
            "AND c.checkpoint_id == @checkpoint_id "
            "UPDATE c WITH { pending_writes: APPEND(c.pending_writes, @writes, true), updated_at: @updated_at } IN @@collection"
        )

        await self._aql(
            query,
            {
                "@collection": self.collection,
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "writes": normalized_writes,
                "updated_at": _now(),
            },
        )

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        import asyncio

        asyncio.run(self.aput_writes(config, writes, task_id, task_path))
