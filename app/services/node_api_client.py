import os
from typing import Any

import httpx


def node_api_base_url() -> str:
    return os.getenv("NODE_API_URL", "http://host.docker.internal:3000").rstrip("/")


def node_api_timeout_seconds() -> float:
    return float(os.getenv("NODE_API_TIMEOUT", "12"))


async def get_solana_account_balance(address: str) -> dict[str, Any]:
    url = f"{node_api_base_url()}/solana/{address}"
    timeout = httpx.Timeout(timeout=node_api_timeout_seconds(), connect=3.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
