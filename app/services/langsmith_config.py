import os
from typing import Any

from langsmith import Client


def langsmith_settings() -> dict[str, Any]:
    return {
        "enabled": os.getenv("LANGSMITH_TRACING", "false").lower() == "true",
        "api_key_present": bool(os.getenv("LANGSMITH_API_KEY")),
        "project": os.getenv("LANGSMITH_PROJECT", "agri-dao-rag"),
        "endpoint": os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
    }


def initialize_langsmith() -> dict[str, Any]:
    settings = langsmith_settings()
    if not settings["enabled"] or not settings["api_key_present"]:
        return settings

    client = Client(
        api_key=os.getenv("LANGSMITH_API_KEY"),
        api_url=settings["endpoint"],
    )
    next(client.list_projects(limit=1), None)
    return settings