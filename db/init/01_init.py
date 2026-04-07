import os
import socket
import json
import subprocess
from urllib.parse import urlparse


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _preflight_tcp(url: str, timeout_seconds: float = 3.0) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 8529
    if not host:
        raise RuntimeError(f"Invalid ARANGO_URL '{url}' (no host)")

    print(f"[preflight] checking TCP connectivity to {host}:{port} ...", flush=True)
    with socket.create_connection((host, port), timeout=timeout_seconds):
        pass
    print("[preflight] connectivity OK", flush=True)


ARANGO_URL = _required_env("ARANGO_URL")
ARANGO_USER = _required_env("ARANGO_USER")
ARANGO_PASSWORD = _required_env("ARANGO_ROOT_PASSWORD")
ARANGO_DB = _required_env("ARANGO_DB")


def _api_call(method: str, db_name: str, path: str, payload: dict | None = None, allow_statuses: set[int] | None = None) -> tuple[int, dict]:
    if allow_statuses is None:
        allow_statuses = {200, 201, 202}

    url = f"{ARANGO_URL}/_db/{db_name}{path}"
    cmd = [
        "curl",
        "-4",
        "-sS",
        "--connect-timeout",
        "3",
        "--max-time",
        "15",
        "-u",
        f"{ARANGO_USER}:{ARANGO_PASSWORD}",
        "-X",
        method,
        "-H",
        "Content-Type: application/json",
    ]

    if payload is not None:
        cmd.extend(["--data-binary", json.dumps(payload)])

    cmd.extend([url, "-w", "\n__STATUS__:%{http_code}"])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = proc.stdout
    marker = "\n__STATUS__:"
    if marker not in output:
        raise RuntimeError(f"Unexpected curl output for {method} {url}: {proc.stderr or output}")

    body_str, status_str = output.rsplit(marker, 1)
    status = int(status_str.strip())
    body_str = body_str.strip()
    body = json.loads(body_str) if body_str else {}

    if status not in allow_statuses:
        raise RuntimeError(f"Arango API {method} {path} failed (status {status}): {body}")

    return status, body

print(f"[init] ARANGO_URL={ARANGO_URL}", flush=True)
print(f"[init] ARANGO_DB={ARANGO_DB}, ARANGO_USER={ARANGO_USER}", flush=True)

_preflight_tcp(ARANGO_URL)

print("[init] using curl IPv4 Arango REST calls", flush=True)

# Create app database if it doesn't exist
print("[init] ensuring application database exists", flush=True)
_, db_list_response = _api_call("GET", "_system", "/_api/database")
existing_dbs = set(db_list_response.get("result", []))
if ARANGO_DB not in existing_dbs:
    _api_call("POST", "_system", "/_api/database", {"name": ARANGO_DB})
    print(f"[init] created database '{ARANGO_DB}'", flush=True)
else:
    print(f"[init] database '{ARANGO_DB}' already exists", flush=True)

print(f"[init] targeting '{ARANGO_DB}'", flush=True)

# ---------------------------------------------------------------------------
# RAG: document_chunks + search view
# ---------------------------------------------------------------------------

# Create document_chunks collection
status, _ = _api_call("GET", ARANGO_DB, "/_api/collection/document_chunks", allow_statuses={200, 404})
if status == 404:
    _api_call("POST", ARANGO_DB, "/_api/collection", {"name": "document_chunks"})
    print("[init] created collection 'document_chunks'", flush=True)
else:
    print("[init] collection 'document_chunks' already exists", flush=True)

# Create ArangoSearch view with vector index for similarity search
status, _ = _api_call("GET", ARANGO_DB, "/_api/view/chunks_view", allow_statuses={200, 404})
if status == 404:
    _api_call(
        "POST",
        ARANGO_DB,
        "/_api/view",
        {
            "name": "chunks_view",
            "type": "arangosearch",
            "properties": {
                "links": {
                    "document_chunks": {
                        "fields": {
                            "embedding": {
                                "analyzers": ["identity"],
                                "cache": True,
                            }
                        }
                    }
                }
            },
        },
    )
    print("[init] created view 'chunks_view'", flush=True)
else:
    print("[init] view 'chunks_view' already exists", flush=True)

# ---------------------------------------------------------------------------
# Knowledge graph: region → resource
# ---------------------------------------------------------------------------

# Document collections
status, _ = _api_call("GET", ARANGO_DB, "/_api/collection/region", allow_statuses={200, 404})
if status == 404:
    _api_call("POST", ARANGO_DB, "/_api/collection", {"name": "region"})
    print("[init] created collection 'region'", flush=True)
else:
    print("[init] collection 'region' already exists", flush=True)

status, _ = _api_call("GET", ARANGO_DB, "/_api/collection/resource", allow_statuses={200, 404})
if status == 404:
    _api_call("POST", ARANGO_DB, "/_api/collection", {"name": "resource"})
    print("[init] created collection 'resource'", flush=True)
else:
    print("[init] collection 'resource' already exists", flush=True)

status, _ = _api_call("GET", ARANGO_DB, "/_api/collection/produce_model", allow_statuses={200, 404})
if status == 404:
    _api_call("POST", ARANGO_DB, "/_api/collection", {"name": "produce_model"})
    print("[init] created collection 'produce_model'", flush=True)
else:
    print("[init] collection 'produce_model' already exists", flush=True)

status, _ = _api_call("GET", ARANGO_DB, "/_api/collection/langgraph_checkpoints", allow_statuses={200, 404})
if status == 404:
    _api_call("POST", ARANGO_DB, "/_api/collection", {"name": "langgraph_checkpoints"})
    print("[init] created collection 'langgraph_checkpoints'", flush=True)
else:
    print("[init] collection 'langgraph_checkpoints' already exists", flush=True)

# Edge collection linking regions to resources
status, _ = _api_call("GET", ARANGO_DB, "/_api/collection/region_resource", allow_statuses={200, 404})
if status == 404:
    _api_call("POST", ARANGO_DB, "/_api/collection", {"name": "region_resource", "type": 3})
    print("[init] created edge collection 'region_resource'", flush=True)
else:
    print("[init] edge collection 'region_resource' already exists", flush=True)

# Named graph for traversal queries
status, _ = _api_call("GET", ARANGO_DB, "/_api/gharial/knowledge_graph", allow_statuses={200, 404})
if status == 404:
    _api_call(
        "POST",
        ARANGO_DB,
        "/_api/gharial",
        {
            "name": "knowledge_graph",
            "edgeDefinitions": [
                {
                    "collection": "region_resource",
                    "from": ["region"],
                    "to": ["resource"],
                }
            ],
        },
    )
    print("[init] created graph 'knowledge_graph'", flush=True)
else:
    print("[init] graph 'knowledge_graph' already exists", flush=True)

# ArangoSearch view over resource collection for full-text + field queries
status, _ = _api_call("GET", ARANGO_DB, "/_api/view/resource_view", allow_statuses={200, 404})
if status == 404:
    _api_call(
        "POST",
        ARANGO_DB,
        "/_api/view",
        {
            "name": "resource_view",
            "type": "arangosearch",
            "properties": {
                "links": {
                    "resource": {
                        "fields": {
                            "title": {"analyzers": ["text_en"]},
                            "description": {"analyzers": ["text_en"]},
                            "tags": {"analyzers": ["text_en"]},
                            "source_type": {"analyzers": ["identity"]},
                            "visibility": {"analyzers": ["identity"]},
                            "topic": {"analyzers": ["identity"]},
                        }
                    }
                }
            },
        },
    )
    print("[init] created view 'resource_view'", flush=True)
else:
    print("[init] view 'resource_view' already exists", flush=True)

print("[init] database initialisation complete.", flush=True)