"""
Seed script: produce tier model and product factors.

Collection written:
  produce_model - produce support model payloads

Run after 01_init.py.
"""

import json
import os
import socket
import subprocess
from datetime import datetime, timezone
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


print(f"[produce] ARANGO_URL={ARANGO_URL}", flush=True)
print(f"[produce] ARANGO_DB={ARANGO_DB}, ARANGO_USER={ARANGO_USER}", flush=True)
_preflight_tcp(ARANGO_URL)

print("[produce] using curl IPv4 Arango REST calls", flush=True)


NOW = datetime.now(timezone.utc).isoformat()


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


def upsert(docs: list[dict]) -> None:
    for doc in docs:
        query = "UPSERT { _key: @key } INSERT @doc UPDATE @doc IN produce_model"
        bind_vars = {
            "key": doc["_key"],
            "doc": doc,
        }
        _api_call("POST", ARANGO_DB, "/_api/cursor", {"query": query, "bindVars": bind_vars})
        print(f"  upserted produce_model/{doc['_key']}")


tiers = [
    {
        "tier": "Tier A",
        "label": "Specialty Fresh Produce (High Volatility)",
        "baskets": [
            {
                "id": "A_1",
                "name": "Tropical & Exotic Fruits",
                "products": [
                    "Avocados (fresh)",
                    "Passionfruit (fresh)",
                    "Dragonfruit (fresh)",
                    "Jackfruit (fresh)",
                    "Mangosteen (fresh)",
                    "Starfruit (fresh)",
                ],
                "centroid": {"beta": 1.30, "alpha": 0.055},
                "forecast": {
                    30: {"low": 1.05, "high": 1.35},
                    60: {"low": 1.15, "high": 1.45},
                    90: {"low": 1.25, "high": 1.55},
                    120: {"low": 1.30, "high": 1.60},
                },
            },
            {
                "id": "A_2",
                "name": "Fresh Roots, Tubers & Greens",
                "products": [
                    "Cassava (fresh)",
                    "Taro (fresh)",
                    "Malanga (fresh)",
                    "Okra (fresh)",
                    "Nopal (fresh)",
                    "Aloe Vera Leaves (fresh)",
                ],
                "centroid": {"beta": 1.10, "alpha": 0.038},
                "forecast": {
                    30: {"low": 1.02, "high": 1.28},
                    60: {"low": 1.12, "high": 1.38},
                    90: {"low": 1.22, "high": 1.48},
                    120: {"low": 1.27, "high": 1.53},
                },
            },
        ],
    },
    {
        "tier": "Tier B",
        "label": "Core Fresh Produce (High Liquidity)",
        "baskets": [
            {
                "id": "B_1",
                "name": "Fresh Vegetables Basket",
                "products": [
                    "Tomatoes",
                    "Bell Peppers",
                    "Cucumbers",
                    "Onions (fresh)",
                    "Carrots",
                    "Lettuce",
                    "Cabbage",
                    "Zucchini / Squash",
                    "Eggplant",
                ],
                "centroid": {"beta": 0.95, "alpha": 0.020},
                "forecast": {
                    30: {"low": 1.00, "high": 1.18},
                    60: {"low": 1.05, "high": 1.23},
                    90: {"low": 1.10, "high": 1.28},
                    120: {"low": 1.14, "high": 1.32},
                },
            },
            {
                "id": "B_2",
                "name": "Fresh Fruit Staples",
                "products": [
                    "Apples",
                    "Oranges",
                    "Bananas",
                    "Grapes",
                    "Pears",
                    "Mangoes",
                    "Pineapples",
                    "Papaya",
                ],
                "centroid": {"beta": 0.88, "alpha": 0.018},
                "forecast": {
                    30: {"low": 0.98, "high": 1.15},
                    60: {"low": 1.03, "high": 1.20},
                    90: {"low": 1.08, "high": 1.25},
                    120: {"low": 1.12, "high": 1.30},
                },
            },
        ],
    },
    {
        "tier": "Tier C",
        "label": "Storable Crops (Inventory-Driven)",
        "baskets": [
            {
                "id": "C_1",
                "name": "Root & Storage Crops",
                "products": [
                    "Potatoes",
                    "Sweet Potatoes",
                    "Dry Onions",
                    "Garlic",
                    "Beets",
                    "Turnips",
                    "Winter Squash",
                    "Yams",
                ],
                "centroid": {"beta": 0.70, "alpha": 0.012},
                "forecast": {
                    30: {"low": 0.96, "high": 1.10},
                    60: {"low": 1.00, "high": 1.14},
                    90: {"low": 1.04, "high": 1.18},
                    120: {"low": 1.08, "high": 1.22},
                },
            }
        ],
    },
    {
        "tier": "Tier D",
        "label": "Shelf-Stable & Processed Agri-Goods",
        "baskets": [
            {
                "id": "D_1",
                "name": "Dried Legumes & Grains",
                "products": [
                    "Black Beans (dried)",
                    "Chickpeas (dried)",
                    "Quinoa (raw)",
                    "Lentils (dried)",
                    "Red Beans (dried)",
                ],
                "centroid": {"beta": 0.72, "alpha": 0.012},
                "forecast": {
                    30: {"low": 0.94, "high": 1.08},
                    60: {"low": 0.98, "high": 1.12},
                    90: {"low": 1.02, "high": 1.16},
                    120: {"low": 1.06, "high": 1.20},
                },
            },
            {
                "id": "D_2",
                "name": "Spices, Dried Fruits & Sweeteners",
                "products": [
                    "Ceylon Cinnamon (powder)",
                    "Turmeric (dried)",
                    "Cardamom (whole)",
                    "Dried Mango",
                    "Dried Banana",
                    "Açaí Powder (freeze-dried)",
                    "Coconut Sugar (granules)",
                    "Agave Syrup (liquid)",
                    "Maple Syrup (liquid)",
                ],
                "centroid": {"beta": 0.90, "alpha": 0.028},
                "forecast": {
                    30: {"low": 0.92, "high": 1.10},
                    60: {"low": 0.98, "high": 1.16},
                    90: {"low": 1.03, "high": 1.21},
                    120: {"low": 1.08, "high": 1.26},
                },
            },
        ],
    },
]

product_factors = [
    {"product": "Avocados (fresh)", "tier": "Tier A", "basket": "A_1", "beta": 1.45, "alpha": 0.062},
    {"product": "Passionfruit (fresh)", "tier": "Tier A", "basket": "A_1", "beta": 1.38, "alpha": 0.058},
    {"product": "Dragonfruit (fresh)", "tier": "Tier A", "basket": "A_1", "beta": 1.22, "alpha": 0.052},
    {"product": "Jackfruit (fresh)", "tier": "Tier A", "basket": "A_1", "beta": 1.25, "alpha": 0.054},
    {"product": "Mangosteen (fresh)", "tier": "Tier A", "basket": "A_1", "beta": 1.18, "alpha": 0.049},
    {"product": "Starfruit (fresh)", "tier": "Tier A", "basket": "A_1", "beta": 1.20, "alpha": 0.051},
    {"product": "Cassava (fresh)", "tier": "Tier A", "basket": "A_2", "beta": 1.05, "alpha": 0.030},
    {"product": "Taro (fresh)", "tier": "Tier A", "basket": "A_2", "beta": 0.98, "alpha": 0.028},
    {"product": "Malanga (fresh)", "tier": "Tier A", "basket": "A_2", "beta": 1.02, "alpha": 0.029},
    {"product": "Okra (fresh)", "tier": "Tier A", "basket": "A_2", "beta": 1.10, "alpha": 0.035},
    {"product": "Nopal (fresh)", "tier": "Tier A", "basket": "A_2", "beta": 1.08, "alpha": 0.033},
    {"product": "Aloe Vera Leaves (fresh)", "tier": "Tier A", "basket": "A_2", "beta": 1.12, "alpha": 0.038},
    {"product": "Tomatoes", "tier": "Tier B", "basket": "B_1", "beta": 1.00, "alpha": 0.021},
    {"product": "Bell Peppers", "tier": "Tier B", "basket": "B_1", "beta": 0.98, "alpha": 0.020},
    {"product": "Cucumbers", "tier": "Tier B", "basket": "B_1", "beta": 0.95, "alpha": 0.019},
    {"product": "Onions (fresh)", "tier": "Tier B", "basket": "B_1", "beta": 0.85, "alpha": 0.018},
    {"product": "Carrots", "tier": "Tier B", "basket": "B_1", "beta": 0.88, "alpha": 0.018},
    {"product": "Lettuce", "tier": "Tier B", "basket": "B_1", "beta": 0.90, "alpha": 0.019},
    {"product": "Cabbage", "tier": "Tier B", "basket": "B_1", "beta": 0.87, "alpha": 0.017},
    {"product": "Zucchini / Squash", "tier": "Tier B", "basket": "B_1", "beta": 0.89, "alpha": 0.018},
    {"product": "Eggplant", "tier": "Tier B", "basket": "B_1", "beta": 0.86, "alpha": 0.017},
    {"product": "Apples", "tier": "Tier B", "basket": "B_2", "beta": 0.82, "alpha": 0.017},
    {"product": "Oranges", "tier": "Tier B", "basket": "B_2", "beta": 0.84, "alpha": 0.018},
    {"product": "Bananas", "tier": "Tier B", "basket": "B_2", "beta": 0.90, "alpha": 0.019},
    {"product": "Grapes", "tier": "Tier B", "basket": "B_2", "beta": 0.85, "alpha": 0.018},
    {"product": "Pears", "tier": "Tier B", "basket": "B_2", "beta": 0.80, "alpha": 0.016},
    {"product": "Mangoes", "tier": "Tier B", "basket": "B_2", "beta": 0.88, "alpha": 0.017},
    {"product": "Pineapples", "tier": "Tier B", "basket": "B_2", "beta": 0.86, "alpha": 0.017},
    {"product": "Papaya", "tier": "Tier B", "basket": "B_2", "beta": 0.87, "alpha": 0.017},
    {"product": "Potatoes", "tier": "Tier C", "basket": "C_1", "beta": 0.65, "alpha": 0.011},
    {"product": "Sweet Potatoes", "tier": "Tier C", "basket": "C_1", "beta": 0.68, "alpha": 0.012},
    {"product": "Dry Onions", "tier": "Tier C", "basket": "C_1", "beta": 0.66, "alpha": 0.011},
    {"product": "Garlic", "tier": "Tier C", "basket": "C_1", "beta": 0.67, "alpha": 0.012},
    {"product": "Beets", "tier": "Tier C", "basket": "C_1", "beta": 0.64, "alpha": 0.010},
    {"product": "Turnips", "tier": "Tier C", "basket": "C_1", "beta": 0.63, "alpha": 0.010},
    {"product": "Winter Squash", "tier": "Tier C", "basket": "C_1", "beta": 0.66, "alpha": 0.011},
    {"product": "Yams", "tier": "Tier C", "basket": "C_1", "beta": 0.65, "alpha": 0.011},
    {"product": "Black Beans (dried)", "tier": "Tier D", "basket": "D_1", "beta": 0.70, "alpha": 0.012},
    {"product": "Chickpeas (dried)", "tier": "Tier D", "basket": "D_1", "beta": 0.71, "alpha": 0.012},
    {"product": "Quinoa (raw)", "tier": "Tier D", "basket": "D_1", "beta": 0.75, "alpha": 0.014},
    {"product": "Lentils (dried)", "tier": "Tier D", "basket": "D_1", "beta": 0.73, "alpha": 0.013},
    {"product": "Red Beans (dried)", "tier": "Tier D", "basket": "D_1", "beta": 0.72, "alpha": 0.012},
    {"product": "Ceylon Cinnamon (powder)", "tier": "Tier D", "basket": "D_2", "beta": 0.95, "alpha": 0.030},
    {"product": "Turmeric (dried)", "tier": "Tier D", "basket": "D_2", "beta": 0.96, "alpha": 0.029},
    {"product": "Cardamom (whole)", "tier": "Tier D", "basket": "D_2", "beta": 0.94, "alpha": 0.028},
    {"product": "Dried Mango", "tier": "Tier D", "basket": "D_2", "beta": 0.88, "alpha": 0.026},
    {"product": "Dried Banana", "tier": "Tier D", "basket": "D_2", "beta": 0.87, "alpha": 0.025},
    {"product": "Açaí Powder (freeze-dried)", "tier": "Tier D", "basket": "D_2", "beta": 0.89, "alpha": 0.027},
    {"product": "Coconut Sugar (granules)", "tier": "Tier D", "basket": "D_2", "beta": 0.91, "alpha": 0.028},
    {"product": "Agave Syrup (liquid)", "tier": "Tier D", "basket": "D_2", "beta": 0.92, "alpha": 0.029},
    {"product": "Maple Syrup (liquid)", "tier": "Tier D", "basket": "D_2", "beta": 0.93, "alpha": 0.030},
]


docs = [
    {
        "_key": "produce_tiers_v1",
        "model_type": "tiers",
        "region_specific": False,
        "source": "client-agri-dao/app/mock-data/data/produceTiers.ts",
        "tiers": tiers,
        "created_at": NOW,
        "updated_at": NOW,
    },
    {
        "_key": "produce_product_factors_v1",
        "model_type": "product_factors",
        "region_specific": False,
        "source": "client-agri-dao/app/mock-data/data/produceTiers.ts",
        "product_factors": product_factors,
        "created_at": NOW,
        "updated_at": NOW,
    },
]

print("Seeding produce model ...", flush=True)
upsert(docs)
print(f"[produce] processed {len(docs)} documents", flush=True)
print("[produce] done.", flush=True)
