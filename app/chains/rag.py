import os
from typing import Any

import httpx


async def query_rag(query: str) -> dict[str, Any]:
    """Generate an answer with Ollama (Mistral by default)."""
    ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "mistral:latest")
    timeout_s = float(os.getenv("OLLAMA_TIMEOUT", "120"))

    prompt = (
        "You are a concise assistant. Answer the user question directly. "
        "If context is missing, say what is missing.\n\n"
        f"Question: {query}"
    )

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                f"{ollama_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            data = response.json()

        answer = data.get("response", "").strip() or "No response generated."
        return {
            "query": query,
            "answer": answer,
            "sources": [],
            "model": model,
        }
    except Exception as exc:
        return {
            "query": query,
            "answer": "Unable to generate an answer from Ollama.",
            "sources": [],
            "error": str(exc),
            "model": model,
        }
