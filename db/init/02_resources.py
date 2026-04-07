"""
Seed script: regions + knowledge-base resources for the AgriDAO support agent.

Collections written:
  region          – one document per supported market region
  resource        – curated external/internal reference links
  region_resource – edges connecting region → resource (graph)

Run after 01_init.py.
"""

import os
import socket
import json
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

print(f"[seed] ARANGO_URL={ARANGO_URL}", flush=True)
print(f"[seed] ARANGO_DB={ARANGO_DB}, ARANGO_USER={ARANGO_USER}", flush=True)
_preflight_tcp(ARANGO_URL)

print("[seed] using curl IPv4 Arango REST calls", flush=True)


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

NOW = datetime.now(timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def upsert(collection: str, docs: list[dict]) -> None:
    """Insert documents; skip silently if _key already exists."""
    for doc in docs:
        query = "UPSERT { _key: @key } INSERT @doc UPDATE @doc IN @@collection"
        bind_vars = {
            "@collection": collection,
            "key": doc["_key"],
            "doc": doc,
        }
        _api_call("POST", ARANGO_DB, "/_api/cursor", {"query": query, "bindVars": bind_vars})
        print(f"  upserted {collection}/{doc['_key']}")


def upsert_edge(from_key: str, to_key: str) -> None:
    """Insert a region → resource edge if it does not already exist."""
    _from = f"region/{from_key}"
    _to = f"resource/{to_key}"
    query = (
        "UPSERT { _from: @f, _to: @t } "
        "INSERT { _from: @f, _to: @t, created_at: @created_at } "
        "UPDATE {} IN region_resource"
    )
    bind_vars = {"f": _from, "t": _to, "created_at": NOW}
    _api_call("POST", ARANGO_DB, "/_api/cursor", {"query": query, "bindVars": bind_vars})
    print(f"  upserted edge {_from} → {_to}")


# ---------------------------------------------------------------------------
# 1. Regions  (mirrors jurisdiction.ts)
# ---------------------------------------------------------------------------

REGIONS = [
    {
        "_key": "africa",
        "name": "Africa",
        "description": "African markets and regulatory framework",
        "enabled": True,
        "created_at": NOW,
    },
    {
        "_key": "caribbean",
        "name": "Caribbean",
        "description": "Caribbean islands regulatory zone",
        "enabled": True,
        "created_at": NOW,
    },
    {
        "_key": "central_america",
        "name": "Central America",
        "description": "Central American agricultural markets",
        "enabled": True,
        "created_at": NOW,
    },
    {
        "_key": "east_asia",
        "name": "East Asia",
        "description": "East Asian regulatory framework",
        "enabled": True,
        "created_at": NOW,
    },
    {
        "_key": "european_union",
        "name": "European Union (EU27)",
        "description": "All 27 EU member states agricultural and trading regulations",
        "enabled": True,
        "created_at": NOW,
    },
    {
        "_key": "gulf_cooperation_council",
        "name": "Gulf Cooperation Council (GCC)",
        "description": "UAE, Saudi Arabia, Kuwait, Qatar, Bahrain, Oman trading framework",
        "enabled": True,
        "created_at": NOW,
    },
    {
        "_key": "nordic_market",
        "name": "Nordic Countries",
        "description": "Denmark, Finland, Iceland, Norway, Sweden regulatory zone",
        "enabled": True,
        "created_at": NOW,
    },
    {
        "_key": "north_america",
        "name": "Canada",
        "description": "Canadian agricultural markets and regulations",
        "enabled": True,
        "created_at": NOW,
    },
    {
        "_key": "south_america",
        "name": "South America",
        "description": "South American agricultural framework",
        "enabled": True,
        "created_at": NOW,
    },
    {
        "_key": "southeast_asia",
        "name": "Southeast Asia",
        "description": "Southeast Asian trading regulations",
        "enabled": True,
        "created_at": NOW,
    },
    {
        "_key": "australia",
        "name": "Australia",
        "description": "Australian agricultural markets and regulatory framework",
        "enabled": True,
        "created_at": NOW,
    },
]

# ---------------------------------------------------------------------------
# 2. Resources
# Each entry also carries a `region_ids` list used to build graph edges below.
# source_type values: market_guide | regulation_summary | trade_portal |
#                     trade_fair | directory | logistics_hub | certification | faq |
#                     policy | runbook | product_doc
# visibility values:  public | system
# ---------------------------------------------------------------------------

RESOURCES = [

    # ── European Union ───────────────────────────────────────────────────────

    {
        "_key": "cbi_eu_fresh_produce",
        "title": "CBI – Exporting Fresh Fruit and Vegetables to Europe",
        "url": "https://www.cbi.eu/market-information/fresh-fruit-vegetables/become-a-supplier-to-europe",
        "description": (
            "Comprehensive guides on exporting fresh fruit and vegetables to Europe, "
            "including tips on finding buyers, market trends, and regulatory requirements. "
            "Also provides access to webinars and value-chain analyses."
        ),
        "source": "CBI (Centre for the Promotion of Imports from developing countries)",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["fresh_produce", "export", "regulations", "buyers", "eu_market"],
        "region_ids": ["european_union"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "ipd_eu_market_access",
        "title": "Import Promotion Desk (IPD) – European Market Access",
        "url": "https://www.importpromotiondesk.com",
        "description": (
            "Supports producers from partner countries entering the European market. "
            "Offers training, buyer matchmaking, and guidance on EU corporate social "
            "responsibility and new EU regulations."
        ),
        "source": "Import Promotion Desk (IPD)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["eu_market", "market_access", "buyer_matchmaking", "csr", "regulations"],
        "region_ids": ["european_union"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "freshfel_europe",
        "title": "Freshfel Europe – European Fresh Produce Association",
        "url": "https://www.freshfel.org",
        "description": (
            "European fresh produce association representing the entire supply chain. "
            "Member lists and resources help connect importers, traders, and retailers "
            "across Europe."
        ),
        "source": "Freshfel Europe",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["fresh_produce", "eu_trade", "supply_chain", "importers", "retailers"],
        "region_ids": ["european_union"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_agri_market_observatory",
        "title": "EU Agricultural Markets Observatory",
        "url": "https://agridata.ec.europa.eu/extensions/AgriMarketObservatory/AgriMarketObservatory.html",
        "description": (
            "European Commission portal tracking price trends, supply/demand balances, "
            "and trade flows for key agricultural commodities across EU27 member states."
        ),
        "source": "European Commission – DG AGRI",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["eu_market", "price_trends", "trade_flows", "commodities"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_customs_taric",
        "title": "EU TARIC – Integrated Tariff of the EU",
        "url": "https://taxation-customs.ec.europa.eu/customs-4/calculation-customs-duties/customs-tariff/eu-customs-tariff-taric_en",
        "description": (
            "Official EU customs tariff database. Look up import duties, tariff codes, "
            "and trade-policy measures for agricultural goods entering the EU."
        ),
        "source": "European Commission – Taxation and Customs Union",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["tariff", "customs", "import_duties", "eu_trade"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_gdpr_agriculture",
        "title": "EU GDPR Compliance for Agricultural Platforms",
        "url": "https://gdpr.eu/what-is-gdpr/",
        "description": (
            "Overview of GDPR obligations relevant to digital agricultural trading "
            "platforms operating in or serving users within the EU, including data "
            "subject rights, consent, and cross-border transfer rules."
        ),
        "source": "GDPR.eu",
        "source_type": "policy",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["gdpr", "privacy", "data_protection", "eu_compliance"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "admin",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_trade_helpdesk_produce",
        "title": "EU Trade Helpdesk – Tariffs and Import Rules for Produce",
        "url": "https://trade.ec.europa.eu/access-to-markets/en/home",
        "description": (
            "EU trade portal for checking tariffs, taxes, rules of origin, and import "
            "requirements for fruits and vegetables entering the European Union."
        ),
        "source": "European Commission",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["eu", "trade_helpdesk", "tariffs", "rules_of_origin", "produce_import"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_customs_union_guidance",
        "title": "EU Customs Union – Import Procedures and Compliance",
        "url": "https://taxation-customs.ec.europa.eu/customs-4_en",
        "description": (
            "Official EU customs guidance with procedures, documentation references, and "
            "links to national customs authorities and tariff tools."
        ),
        "source": "European Commission – Taxation and Customs Union",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["eu", "customs_union", "procedures", "compliance", "documentation"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "access2markets_produce_guides",
        "title": "Access2Markets – Fresh Produce Import and Export Guides",
        "url": "https://trade.ec.europa.eu/access-to-markets/en/home",
        "description": (
            "Step-by-step EU guidance for trade barriers, customs procedures, rules of origin, "
            "and phytosanitary requirements for produce shipments."
        ),
        "source": "European Commission",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["access2markets", "eu", "customs", "rules_of_origin", "phytosanitary"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_plant_health_regulation",
        "title": "EU Plant Health Regulation – Produce Import Requirements",
        "url": "https://food.ec.europa.eu/plants/plant-health-and-biosecurity_en",
        "description": (
            "EU plant health framework for importing plants and plant products, including "
            "phytosanitary certification obligations for most fresh produce."
        ),
        "source": "European Commission – Food Safety",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["eu", "plant_health", "biosecurity", "phytosanitary_certificate", "produce"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_rasff_portal",
        "title": "EU RASFF – Food and Feed Rapid Alert Portal",
        "url": "https://webgate.ec.europa.eu/rasff-window/screen/search",
        "description": (
            "Rapid Alert System for Food and Feed (RASFF) portal for rejected, detained, "
            "or non-compliant food and produce consignments in EU markets."
        ),
        "source": "European Commission",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["eu", "rasff", "food_safety", "shipment_rejections", "compliance_alerts"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "dutch_customs_douane",
        "title": "Dutch Customs (Douane) – Import Procedures",
        "url": "https://www.belastingdienst.nl/wps/wcm/connect/en/customs/customs",
        "description": (
            "Netherlands customs authority reference for import declarations, checks, "
            "and customs procedures at a major EU produce entry hub."
        ),
        "source": "Dutch Customs (Douane)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["netherlands", "douane", "import_declaration", "rotterdam", "produce_hub"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": ["nl"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "german_customs_zoll",
        "title": "German Customs (Zoll) – Produce Import Guidance",
        "url": "https://www.zoll.de/EN/Home/home_node.html",
        "description": (
            "Germany customs authority resources for import requirements, customs clearance, "
            "and tariff handling for produce shipments."
        ),
        "source": "German Customs (Zoll)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["germany", "zoll", "customs", "import_requirements", "tariff"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": ["de"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "spanish_customs_agencia_tributaria",
        "title": "Spanish Customs (Agencia Tributaria) – Import and Trade Controls",
        "url": "https://sede.agenciatributaria.gob.es",
        "description": (
            "Spain customs authority tools and guidance for declarations, controls, "
            "and customs processing for imported produce."
        ),
        "source": "Agencia Tributaria",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["spain", "customs", "agencia_tributaria", "declarations", "produce_import"],
        "region_ids": ["european_union"],
        "country_codes": ["es"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "french_customs_douanes",
        "title": "French Customs (Douanes) – Import and Border Procedures",
        "url": "https://www.douane.gouv.fr",
        "description": (
            "France customs authority portal for import procedures, border documentation, "
            "and controls relevant to produce consignments."
        ),
        "source": "French Customs (Douanes)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["france", "douanes", "customs", "border_procedures", "produce"],
        "region_ids": ["european_union"],
        "country_codes": ["fr"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_produce_import_workflow",
        "title": "EU Produce Import Workflow – Classification to Clearance",
        "url": "https://trade.ec.europa.eu/access-to-markets/en/home",
        "description": (
            "Workflow checklist for importing produce into the EU: classify HS/TARIC code, "
            "check SPS and labeling requirements, prepare documents, and complete customs clearance."
        ),
        "source": "European Commission",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["eu", "workflow", "taric", "sps", "customs_clearance", "produce_import"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "fruit_logistica_berlin",
        "title": "FRUIT LOGISTICA – Berlin",
        "url": "https://www.fruitlogistica.com",
        "description": (
            "Leading international trade fair for fresh produce held annually in Berlin. "
            "Useful for meeting major traders and tracking European produce market trends."
        ),
        "source": "FRUIT LOGISTICA",
        "source_type": "trade_fair",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["trade_fair", "berlin", "fresh_produce", "networking", "eu_market"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": ["de"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "fruit_attraction_madrid",
        "title": "Fruit Attraction – Madrid",
        "url": "https://www.ifema.es/en/fruit-attraction",
        "description": (
            "Major produce trade event in Madrid for networking with European buyers "
            "and exploring fresh produce market opportunities."
        ),
        "source": "IFEMA MADRID",
        "source_type": "trade_fair",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["trade_fair", "madrid", "buyers", "fresh_produce", "eu_market"],
        "region_ids": ["european_union"],
        "country_codes": ["es"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "best_food_importers_directory",
        "title": "Best Food Importers Directory",
        "url": "https://bestfoodimporters.com",
        "description": (
            "Global database of active food importers with company profiles and contact "
            "details. Useful for identifying buyers and building sourcing partnerships."
        ),
        "source": "Best Food Importers",
        "source_type": "directory",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["directory", "importers", "buyers", "contacts", "b2b"],
        "region_ids": ["european_union", "north_america", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "befresh_europe_distribution",
        "title": "BeFresh – Premium Fresh Produce Distribution",
        "url": "https://www.befreshcorp.net",
        "description": (
            "Specialized distributor focused on premium fresh produce with strong "
            "partnership coverage across European markets."
        ),
        "source": "BeFresh",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["distributor", "fresh_produce", "premium", "europe", "partnerships"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "jem_fruits_uk_importer",
        "title": "JEM Fruits – UK Produce Import Programmes",
        "url": "https://www.jemfruits.com",
        "description": (
            "UK-based importer with fixed contracts and produce programs including "
            "citrus, apples, and grapes."
        ),
        "source": "JEM Fruits",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["uk", "importer", "contracts", "citrus", "apples", "grapes"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": ["gb"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eurotrade_concept_network",
        "title": "Eurotrade Concept – Importers and Distributors Network",
        "url": "https://www.eurotradeconcept.eu",
        "description": (
            "European network of importers and distributors offering a wide assortment "
            "of food products and regional contact details."
        ),
        "source": "Eurotrade Concept",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["network", "importers", "distributors", "europe", "contacts"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cbi_northern_europe_buyers",
        "title": "CBI – Finding Buyers in Northern Europe",
        "url": "https://www.cbi.eu",
        "description": (
            "CBI guidance for exporters targeting Northern Europe, including buyer discovery "
            "strategies and use of sourcing/data platforms such as Tridge and Global Buyers Online."
        ),
        "source": "CBI (Centre for the Promotion of Imports from developing countries)",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["northern_europe", "buyers", "tridge", "trade_data", "market_entry"],
        "region_ids": ["nordic_market", "european_union"],
        "country_codes": ["nl", "de", "dk", "fi", "se", "no", "is"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "northern_europe_netherlands_hub",
        "title": "Northern Europe Insight – Netherlands as Produce Trade Hub",
        "url": "https://bestfoodimporters.com",
        "description": (
            "Market insight on the Netherlands as a major Northern European fresh produce hub "
            "with advanced logistics and re-export flows to neighboring markets."
        ),
        "source": "Best Food Importers",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["northern_europe", "netherlands", "trade_hub", "re_export", "logistics"],
        "region_ids": ["nordic_market", "european_union"],
        "country_codes": ["nl"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "northern_europe_demand_trends",
        "title": "Northern Europe Demand Trends – Organic, Exotic, Off-Season",
        "url": "https://www.importpromotiondesk.com",
        "description": (
            "Demand profile for Northern Europe (Netherlands, Germany, Scandinavia): strong demand "
            "for organic, exotic, and off-season produce with strict consistency and sustainability expectations."
        ),
        "source": "Import Promotion Desk (IPD)",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["northern_europe", "organic", "exotic", "off_season", "demand_trends"],
        "region_ids": ["nordic_market", "european_union"],
        "country_codes": ["nl", "de", "dk", "fi", "se", "no", "is"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "hortim_importer_netherlands",
        "title": "Hortim – Dutch Fresh Produce Importer",
        "url": "https://hortim.com",
        "description": (
            "Dutch importer/distributor with broad global sourcing and a focus on citrus, salads, "
            "and tropical fruits for European buyers."
        ),
        "source": "Hortim",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["hortim", "netherlands", "importer", "citrus", "tropical_fruit"],
        "region_ids": ["nordic_market", "european_union"],
        "country_codes": ["nl"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "northern_europe_quality_certifications",
        "title": "Northern Europe Quality and Certification Requirements",
        "url": "https://www.cbi.eu",
        "description": (
            "Guidance on quality expectations and certification requirements for Northern Europe, "
            "including GLOBALG.A.P. and Fairtrade."
        ),
        "source": "CBI (Centre for the Promotion of Imports from developing countries)",
        "source_type": "certification",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["northern_europe", "quality", "globalgap", "fairtrade", "certification"],
        "region_ids": ["nordic_market", "european_union"],
        "country_codes": ["nl", "de", "dk", "fi", "se", "no", "is"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "northern_europe_cold_chain_logistics",
        "title": "Northern Europe Cold Chain and Post-Harvest Logistics",
        "url": "https://www.cbi.eu",
        "description": (
            "Operational guidance on post-harvest handling, packaging, and cold-chain execution "
            "required to succeed in Northern European produce markets."
        ),
        "source": "CBI (Centre for the Promotion of Imports from developing countries)",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["northern_europe", "cold_chain", "post_harvest", "packaging", "logistics"],
        "region_ids": ["nordic_market", "european_union"],
        "country_codes": ["nl", "de", "dk", "fi", "se", "no", "is"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── Nordic Market ────────────────────────────────────────────────────────

    {
        "_key": "nordic_ecolabel_food",
        "title": "Nordic Ecolabel – Food and Agriculture Standards",
        "url": "https://www.nordic-ecolabel.org",
        "description": (
            "Official Nordic Swan ecolabel certification standards covering sustainability, "
            "traceability, and environmental reporting requirements for food products "
            "traded in Denmark, Finland, Iceland, Norway, and Sweden."
        ),
        "source": "Nordic Ecolabel",
        "source_type": "certification",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["ecolabel", "sustainability", "traceability", "certification", "nordic"],
        "region_ids": ["nordic_market"],
        "country_codes": ["dk", "fi", "is", "no", "se"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── Gulf Cooperation Council ──────────────────────────────────────────────

    {
        "_key": "gcc_customs_union",
        "title": "GCC Customs Union – Trade and Tariff Information",
        "url": "https://www.gcccustomsunion.net",
        "description": (
            "Official portal for GCC customs union rules covering UAE, Saudi Arabia, "
            "Kuwait, Qatar, Bahrain, and Oman. Includes tariff schedules, import "
            "certificate requirements, and halal certification guidance."
        ),
        "source": "GCC Customs Union Secretariat",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["gcc", "customs", "tariff", "halal", "import_certificate"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "kw", "qa", "bh", "om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "saber_saudi_product_registration",
        "title": "SABER – Saudi Product Safety and Conformity Platform",
        "url": "https://saber.sa",
        "description": (
            "Saudi Arabia's mandatory product registration and conformity assessment "
            "platform. Covers certificate of conformity requirements for agricultural "
            "and food products entering the Saudi market."
        ),
        "source": "Saudi Standards, Metrology and Quality Organization (SASO)",
        "source_type": "certification",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["saudi_arabia", "conformity", "registration", "food_safety"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["sa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "jebel_ali_port_dubai",
        "title": "Jebel Ali Port (Dubai) – Perishables and Cold Chain Hub",
        "url": "https://www.dpworld.com/jebel-ali-port",
        "description": (
            "Largest port in the Middle East with major container throughput and "
            "cold-chain handling infrastructure relevant to fresh produce logistics."
        ),
        "source": "DP World",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["middle_east", "port", "jebel_ali", "dubai", "cold_chain", "perishables"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "khalifa_port_abu_dhabi",
        "title": "Khalifa Port (Abu Dhabi) – Refrigerated Logistics Infrastructure",
        "url": "https://www.adportsgroup.com/en/ports/khalifa-port",
        "description": (
            "Modern UAE port with advanced terminal operations and refrigerated logistics "
            "capacity for agricultural and food imports."
        ),
        "source": "AD Ports Group",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["middle_east", "port", "khalifa_port", "abu_dhabi", "refrigeration"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "dubai_airport_dxb_cargo",
        "title": "Dubai International Airport (DXB) – Air Cargo Hub",
        "url": "https://www.dubaiairports.ae/corporate/cargo",
        "description": (
            "Major regional air cargo gateway used for air-freighted produce and "
            "time-sensitive food shipments across GCC and global markets."
        ),
        "source": "Dubai Airports",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["middle_east", "air_cargo", "dxb", "dubai", "perishables"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "dubai_world_central_dwc_cargo",
        "title": "Dubai World Central (DWC) – Dedicated Cargo Airport",
        "url": "https://www.dubaisouth.ae/en/explore/districts/aviation-district",
        "description": (
            "Dedicated cargo-focused aviation zone (Al Maktoum area) supporting high-volume "
            "air freight and cold-chain operations in the UAE."
        ),
        "source": "Dubai South",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["middle_east", "air_cargo", "dwc", "al_maktoum", "cold_chain"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "gcc_cold_chain_providers_overview",
        "title": "GCC Cold Chain Providers – Market Overview",
        "url": "https://www.logisticsmiddleeast.com",
        "description": (
            "Regional reference point for identifying cold-chain operators and logistics "
            "service trends across GCC produce supply chains."
        ),
        "source": "Logistics Middle East",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["gcc", "cold_chain", "logistics_providers", "warehousing", "distribution"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "kw", "qa", "bh", "om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "best_food_importers_middle_east",
        "title": "Best Food Importers – Middle East Importer Database",
        "url": "https://bestfoodimporters.com",
        "description": (
            "Middle East-focused importer discovery and market-intelligence use cases, "
            "including UAE/Dubai buyer discovery and halal-aligned demand signals."
        ),
        "source": "Best Food Importers",
        "source_type": "directory",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["middle_east", "directory", "importers", "buyers", "halal", "uae"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "kw", "qa", "bh", "om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "yellow_pages_uae_importers",
        "title": "Yellow Pages UAE – Fruits and Vegetables Importers & Wholesalers",
        "url": "https://www.yellowpages-uae.com/uae/fruits-vegetables-importers-wholesalers",
        "description": (
            "Directory of UAE produce importers and wholesalers with contact details and "
            "product focus, useful for identifying local channel partners."
        ),
        "source": "Yellow Pages UAE",
        "source_type": "directory",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["uae", "directory", "wholesalers", "importers", "dubai"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "jrj_associates_middle_east",
        "title": "JRJ Associates – Fresh Produce Import and Distribution",
        "url": "https://www.jrjworld.com",
        "description": (
            "Middle East fresh produce importer/distributor with operations in Muscat and "
            "UAE, covering sourcing, quality control, and logistics."
        ),
        "source": "JRJ Associates",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["middle_east", "importer", "distributor", "muscat", "uae", "fresh_produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "all_about_fresh_uae",
        "title": "All About Fresh – UAE Produce Import and Distribution",
        "url": "https://allaboutfresh.co",
        "description": (
            "UAE produce importer/distributor focused on quality sourcing from global markets."
        ),
        "source": "All About Fresh",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["uae", "importer", "fresh_produce", "distribution", "global_sourcing"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "nrtc_group_uae_saudi",
        "title": "NRTC Group – Large-Scale Produce Import and Cold Chain",
        "url": "https://www.nrtcgroup.com",
        "description": (
            "Major fresh produce importer in UAE and Saudi Arabia with high-volume handling "
            "and advanced cold-chain and logistics infrastructure."
        ),
        "source": "NRTC Group",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["uae", "saudi_arabia", "importer", "cold_chain", "high_volume"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "green_belt_group_middle_east",
        "title": "Green Belt Group – Fresh Produce Trade Network",
        "url": "https://greenbeltfoodstuff.com",
        "description": (
            "Fresh fruit and vegetable importer/exporter across Middle East, Africa, and Asia "
            "with a broad supplier network."
        ),
        "source": "Green Belt Group",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["middle_east", "import_export", "distributor", "network", "fresh_produce"],
        "region_ids": ["gulf_cooperation_council", "africa"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "ajmeer_general_trading_uae",
        "title": "Ajmeer General Trading – UAE Produce Distribution",
        "url": "https://ajmeer.ae",
        "description": (
            "UAE distributor supplying wholesalers, retailers, hotels, and restaurants with "
            "locally and internationally sourced produce."
        ),
        "source": "Ajmeer General Trading",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["uae", "distributor", "horeca", "retail", "fresh_produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "kuhne_heitz_iqf_middle_east",
        "title": "Kuhne + Heitz – IQF Frozen Vegetables for Middle East",
        "url": "https://www.kuhneheitz.com",
        "description": (
            "Importer/exporter specialized in IQF frozen vegetables serving industry, wholesale, "
            "and retail channels across the Middle East."
        ),
        "source": "Kuhne + Heitz",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["middle_east", "frozen", "iqf", "vegetables", "wholesale", "retail"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "middle_east_market_growth_insights",
        "title": "Middle East Produce Import Market Growth and Demand Insights",
        "url": "https://bestfoodimporters.com",
        "description": (
            "Overview of market growth drivers in the Middle East: limited local production, "
            "population growth, hospitality demand, and halal/wellness preferences."
        ),
        "source": "Best Food Importers",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["middle_east", "market_growth", "halal", "hospitality", "demand_trends"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "kw", "qa", "bh", "om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "middle_east_key_channels",
        "title": "Middle East Entry Channels – HORECA, Catering, and Retail",
        "url": "https://bestfoodimporters.com",
        "description": (
            "Guidance on key market-entry channels in the region, highlighting hotels, "
            "catering, and retail chains and the importance of local importer partnerships."
        ),
        "source": "Best Food Importers",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["middle_east", "horeca", "catering", "retail", "market_entry"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "kw", "qa", "bh", "om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "middle_east_halal_quality_requirements",
        "title": "Middle East Halal and Quality Compliance Requirements",
        "url": "https://www.gso.org.sa",
        "description": (
            "Compliance primer for halal and quality standards relevant to produce imports "
            "in GCC markets."
        ),
        "source": "Gulf Standards Organization (GSO)",
        "source_type": "certification",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["middle_east", "halal", "quality", "compliance", "gcc"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "kw", "qa", "bh", "om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "dubai_customs_import_portal",
        "title": "Dubai Customs – Import Procedures and Tariff Services",
        "url": "https://www.dubaicustoms.gov.ae",
        "description": (
            "Official Dubai Customs portal for import procedures, tariff references, and "
            "documentation workflows relevant to produce consignments."
        ),
        "source": "Dubai Customs",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["uae", "dubai_customs", "import_procedures", "tariffs", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "dubai_trade_declaration_platform",
        "title": "Dubai Trade Portal – Shipment Declarations and Tracking",
        "url": "https://www.dubaitrade.ae",
        "description": (
            "Electronic trade platform for filing import declarations and tracking cargo "
            "movements through Dubai logistics channels."
        ),
        "source": "Dubai Trade",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["uae", "dubai_trade", "declarations", "shipment_tracking", "customs_clearance"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "moccae_phytosanitary_rules",
        "title": "UAE MOCCAE – Phytosanitary and Food Safety Rules",
        "url": "https://www.moccae.gov.ae",
        "description": (
            "UAE authority guidance on phytosanitary controls, food safety requirements, "
            "and restricted or prohibited produce imports."
        ),
        "source": "UAE Ministry of Climate Change and Environment (MOCCAE)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["uae", "moccae", "phytosanitary", "food_safety", "restricted_items"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "zatca_customs_clearance",
        "title": "Saudi ZATCA – Customs and Import Clearance",
        "url": "https://zatca.gov.sa/en/Pages/default.aspx",
        "description": (
            "Saudi customs and tax authority portal for import procedures, duties, "
            "and electronic clearance requirements."
        ),
        "source": "Zakat, Tax and Customs Authority (ZATCA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["saudi_arabia", "zatca", "customs", "import_clearance", "duties"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["sa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "fasah_saudi_eclearance",
        "title": "Fasah – Saudi Electronic Customs Clearance Platform",
        "url": "https://www.fasah.sa",
        "description": (
            "Saudi electronic platform used for customs transaction submission, "
            "document exchange, and cargo clearance coordination."
        ),
        "source": "Fasah",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["saudi_arabia", "fasah", "electronic_clearance", "customs", "documentation"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["sa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "sfda_food_safety_imports",
        "title": "SFDA – Food Safety Standards for Imported Produce",
        "url": "https://www.sfda.gov.sa/en",
        "description": (
            "Saudi Food and Drug Authority standards and controls for imported food products, "
            "including produce safety and compliance checks."
        ),
        "source": "Saudi Food and Drug Authority (SFDA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["saudi_arabia", "sfda", "food_safety", "produce", "compliance"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["sa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "qatar_customs_portal",
        "title": "Qatar Customs – Import Regulations and Tariff Guidance",
        "url": "https://www.customs.gov.qa",
        "description": (
            "Qatar customs portal for import requirements, tariff handling, and "
            "documentation procedures relevant to fresh produce."
        ),
        "source": "Qatar Customs",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["qatar", "customs", "tariffs", "import_requirements", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "kuwait_customs_portal",
        "title": "Kuwait Customs – Import Duties and Procedures",
        "url": "https://www.customs.gov.kw",
        "description": (
            "Kuwait customs authority references for import procedures, duty rules, "
            "and cargo documentation requirements."
        ),
        "source": "Kuwait Customs",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["kuwait", "customs", "duties", "procedures", "produce_import"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["kw"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "oman_customs_portal",
        "title": "Oman Customs – Fresh Produce Import Controls",
        "url": "https://www.customs.gov.om",
        "description": (
            "Oman customs portal with import procedures, tariff references, and "
            "required documentation for produce shipments."
        ),
        "source": "Oman Customs",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["oman", "customs", "tariffs", "documentation", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "bahrain_customs_portal",
        "title": "Bahrain Customs – Clearance and Tariff Services",
        "url": "https://www.bahraincustoms.gov.bh",
        "description": (
            "Bahrain customs portal covering import clearance procedures and tariff services "
            "for food and produce consignments."
        ),
        "source": "Bahrain Customs",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["bahrain", "customs", "clearance", "tariffs", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["bh"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "gso_labeling_standard_9_2013",
        "title": "GSO 9/2013 – Labeling of Pre-packaged Foods",
        "url": "https://www.gso.org.sa",
        "description": (
            "GCC labeling standard reference for pre-packaged foods, widely used as a baseline "
            "for import labeling compliance in regional markets."
        ),
        "source": "Gulf Standards Organization (GSO)",
        "source_type": "policy",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["gcc", "gso", "labeling", "prepackaged_food", "compliance"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "kw", "qa", "bh", "om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "gcc_trade_agreements_overview",
        "title": "GCC Trade Agreements – Tariff Preference Overview",
        "url": "https://www.gcc-sg.org",
        "description": (
            "Reference for GCC-level trade agreements and external economic partnerships "
            "that can affect produce tariff treatment."
        ),
        "source": "GCC Secretariat",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["gcc", "trade_agreements", "tariff_preferences", "produce_trade", "fta"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "kw", "qa", "bh", "om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "uae_india_cepa_trade",
        "title": "UAE-India CEPA – Produce Trade Facilitation Context",
        "url": "https://www.moec.gov.ae",
        "description": (
            "Bilateral trade agreement context supporting tariff and customs facilitation "
            "for goods flows between UAE and India, relevant to produce channels."
        ),
        "source": "UAE Ministry of Economy",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["uae", "india", "cepa", "bilateral_trade", "produce"],
        "region_ids": ["gulf_cooperation_council", "southeast_asia"],
        "country_codes": ["ae", "in"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "king_abdullah_port_saudi",
        "title": "King Abdullah Port – Saudi Produce Logistics Hub",
        "url": "https://www.kingabdullahport.com.sa",
        "description": (
            "Major Saudi port with container and cold-chain capabilities relevant to produce "
            "imports and regional distribution."
        ),
        "source": "King Abdullah Port",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["saudi_arabia", "king_abdullah_port", "cold_chain", "containers", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["sa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "jeddah_islamic_port_saudi",
        "title": "Jeddah Islamic Port – Import Gateway for Food and Produce",
        "url": "https://mawani.gov.sa/en-us/ports/jeddah",
        "description": (
            "Key Saudi maritime gateway supporting high-volume import operations "
            "for food and produce shipments."
        ),
        "source": "Saudi Ports Authority (Mawani)",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["saudi_arabia", "jeddah", "port", "food_import", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["sa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "hamad_port_qatar",
        "title": "Hamad Port – Qatar Container and Food Logistics",
        "url": "https://www.mwani.com.qa",
        "description": (
            "Qatar's primary port for containerized imports, supporting food and produce "
            "supply chain operations and regional distribution."
        ),
        "source": "Mwani Qatar",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["qatar", "hamad_port", "containers", "food_logistics", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "sohar_port_oman",
        "title": "Sohar Port – Oman Trade and Reefer Operations",
        "url": "https://www.soharportandfreezone.com",
        "description": (
            "Oman maritime and free-zone logistics hub with facilities relevant for reefer "
            "cargo and produce distribution."
        ),
        "source": "Sohar Port and Freezone",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["oman", "sohar", "reefer", "freezone", "produce_logistics"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["om"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "doha_hamad_airport_cargo",
        "title": "Hamad International Airport (DOH) – Air Cargo for Perishables",
        "url": "https://dohahamadairport.com",
        "description": (
            "Major Qatar air cargo hub supporting time-sensitive and perishable "
            "produce shipments within and beyond GCC markets."
        ),
        "source": "Hamad International Airport",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["qatar", "doh", "air_cargo", "perishables", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "dmcc_agri_trade_services",
        "title": "DMCC – Trade Facilitation Services for Agri Commodities",
        "url": "https://www.dmcc.ae",
        "description": (
            "Dubai Multi Commodities Centre services and ecosystem support for commodity "
            "trade participants, including agri and food sectors."
        ),
        "source": "Dubai Multi Commodities Centre (DMCC)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["dmcc", "dubai", "trade_facilitation", "agri_commodities", "food_trade"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "dubai_chamber_trade_support",
        "title": "Dubai Chamber – Market Insights and Trade Support",
        "url": "https://www.dubaichamber.com",
        "description": (
            "Trade support resources and market intelligence for companies importing or "
            "exporting produce through Dubai and GCC channels."
        ),
        "source": "Dubai Chamber",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["dubai", "chamber_of_commerce", "market_insights", "trade_support", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "gulfood_trade_show",
        "title": "Gulfood – Middle East Food and Agriculture Trade Show",
        "url": "https://www.gulfood.com",
        "description": (
            "Major annual industry event for sourcing, networking, and buyer discovery "
            "across Middle East food and produce markets."
        ),
        "source": "Gulfood",
        "source_type": "trade_fair",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["middle_east", "trade_show", "networking", "buyers", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "uae_gso_2055_2_labeling_standard",
        "title": "UAE.S GSO 2055-2 – Food Labeling Requirements",
        "url": "https://www.moiat.gov.ae/en/services/standardization",
        "description": (
            "Reference for UAE/GCC-aligned food labeling requirements applicable to imported produce "
            "and food products in commercial channels."
        ),
        "source": "UAE Ministry of Industry and Advanced Technology (MoIAT)",
        "source_type": "policy",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["uae", "gso_2055_2", "labeling", "food_compliance", "produce_import"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "uae_prepackaged_food_labeling_9_2013",
        "title": "UAE.S 9/2013 – Pre-packaged Food Labeling",
        "url": "https://www.gso.org.sa",
        "description": (
            "Labeling rule reference for pre-packaged foods in GCC markets, commonly used in "
            "UAE import compliance checks for packaged produce products."
        ),
        "source": "Gulf Standards Organization (GSO)",
        "source_type": "policy",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["uae", "gso_9_2013", "prepackaged", "labeling", "gcc"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "uae_logistics_dp_world_services",
        "title": "DP World UAE – Cold Chain and Port Logistics Services",
        "url": "https://www.dpworld.com",
        "description": (
            "DP World service references for cold-chain handling, container logistics, and "
            "produce distribution through UAE maritime gateways."
        ),
        "source": "DP World",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["uae", "dp_world", "cold_chain", "port_logistics", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "uae_logistics_agility",
        "title": "Agility Logistics – GCC Temperature-Controlled Transport",
        "url": "https://www.agility.com",
        "description": (
            "Regional logistics provider reference for refrigerated transport, warehousing, "
            "and customs-coordinated import operations in GCC markets."
        ),
        "source": "Agility Logistics",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["gcc", "agility", "refrigerated_transport", "warehousing", "customs_support"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "saudi_air_cargo_riyadh_jeddah",
        "title": "Saudi Air Cargo Gateways – Riyadh and Jeddah",
        "url": "https://www.saudia-cargo.com",
        "description": (
            "Air-cargo routing reference for produce imports through Riyadh and Jeddah airport "
            "hubs, including perishable handling capabilities."
        ),
        "source": "Saudia Cargo",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["saudi_arabia", "air_cargo", "riyadh", "jeddah", "perishables"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["sa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "saudi_logistics_bahri_maersk_dhl",
        "title": "Saudi Produce Logistics Providers – Bahri, Maersk, DHL",
        "url": "https://www.bahri.sa",
        "description": (
            "Provider landscape reference for ocean and multimodal cold-chain logistics used "
            "for produce imports into Saudi Arabia."
        ),
        "source": "Bahri Logistics",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["saudi_arabia", "bahri", "maersk", "dhl", "cold_chain", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["sa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "qatar_customs_single_window",
        "title": "Qatar Customs Single Window – Electronic Import Clearance",
        "url": "https://www.customs.gov.qa/english/pages/single-window.aspx",
        "description": (
            "Qatar single-window customs workflow for electronic submission of import "
            "documents and produce clearance processing."
        ),
        "source": "Qatar Customs",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["qatar", "single_window", "customs", "electronic_submission", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "qatar_mme_import_requirements",
        "title": "Qatar MME – Fresh Produce Import Requirements",
        "url": "https://www.mme.gov.qa",
        "description": (
            "Qatar Ministry of Municipality and Environment requirements for produce admissibility, "
            "phytosanitary documents, and food safety checks."
        ),
        "source": "Qatar Ministry of Municipality and Environment (MME)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["qatar", "mme", "phytosanitary", "food_safety", "produce_import"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "qatar_cold_chain_providers",
        "title": "Qatar Cold Chain Providers – Qatar Airways Cargo, DHL, GWC",
        "url": "https://www.qrcargo.com",
        "description": (
            "Reference for refrigerated logistics providers supporting import, storage, and "
            "distribution of perishable produce in Qatar."
        ),
        "source": "Qatar Airways Cargo",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["qatar", "qatar_airways_cargo", "dhl", "gwc", "cold_chain", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "gcc_common_market_produce_trade",
        "title": "GCC Common Market – Duty Treatment for Intra-GCC Produce Trade",
        "url": "https://www.gcc-sg.org/en-us/Pages/default.aspx",
        "description": (
            "Reference on GCC common market and customs alignment relevant to tariff treatment "
            "for produce traded within GCC member states."
        ),
        "source": "GCC Secretariat",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["gcc", "common_market", "intra_gcc", "duty_treatment", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "qa", "kw", "om", "bh"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "middle_east_certification_iso_haccp",
        "title": "Middle East Produce Certification – ISO 22000 and HACCP Guidance",
        "url": "https://www.iso.org",
        "description": (
            "Certification guidance for voluntary food safety management systems often requested "
            "by importers and retail channels in GCC produce supply chains."
        ),
        "source": "International Organization for Standardization (ISO)",
        "source_type": "certification",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["gcc", "iso_22000", "haccp", "food_safety", "certification", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── Africa ───────────────────────────────────────────────────────────────

    {
        "_key": "afcfta_trade_portal",
        "title": "African Continental Free Trade Area (AfCFTA) – Trade Portal",
        "url": "https://www.afcfta.au.int",
        "description": (
            "Official AfCFTA portal covering the continent-wide free trade agreement "
            "tariff schedules, rules of origin, and sector-specific protocols for "
            "agricultural goods."
        ),
        "source": "African Union – AfCFTA Secretariat",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["africa", "afcfta", "free_trade", "tariff", "rules_of_origin"],
        "region_ids": ["africa"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cbi_africa_export",
        "title": "CBI – Exporting Agricultural Products from Africa",
        "url": "https://www.cbi.eu/market-information/fresh-fruit-vegetables/africa",
        "description": (
            "CBI guides specifically for African producers covering export requirements, "
            "phytosanitary standards, and buyer connections to European and Middle Eastern "
            "markets."
        ),
        "source": "CBI (Centre for the Promotion of Imports from developing countries)",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["africa", "export", "phytosanitary", "fresh_produce"],
        "region_ids": ["africa"],
        "country_codes": ["dz", "eg", "gh"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "afcfta_secretariat_portal",
        "title": "AfCFTA Secretariat – Tariffs, Rules of Origin, and Trade Facilitation",
        "url": "https://www.africancfta.org",
        "description": (
            "Official AfCFTA portal with schedules and frameworks for tariff reduction, "
            "rules of origin, and customs simplification across African markets."
        ),
        "source": "AfCFTA Secretariat",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["afcfta", "africa", "tariffs", "rules_of_origin", "trade_facilitation"],
        "region_ids": ["africa"],
        "country_codes": ["za", "ke", "ng", "eg", "et", "gh"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "ecowas_trade_portal",
        "title": "ECOWAS Trade Portal – ETLS and Customs Guidance",
        "url": "https://www.ecowas.int",
        "description": (
            "ECOWAS resources on common external tariffs, ETLS duty-free treatment, and "
            "harmonized customs processes for West African trade."
        ),
        "source": "ECOWAS",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["ecowas", "etls", "west_africa", "customs_union", "duty_free"],
        "region_ids": ["africa"],
        "country_codes": ["ng", "gh"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eac_customs_union_portal",
        "title": "EAC Customs Union – CET and Single Customs Territory",
        "url": "https://www.eac.int/customs",
        "description": (
            "EAC customs union guidance on common external tariff, rules of origin, and "
            "single customs territory procedures for East African cross-border trade."
        ),
        "source": "East African Community (EAC)",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["eac", "cet", "rules_of_origin", "single_customs_territory", "east_africa"],
        "region_ids": ["africa"],
        "country_codes": ["ke", "ug", "tz", "rw", "bi", "ss"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "sadc_trade_portal",
        "title": "SADC Trade Portal – Intra-Regional Tariffs and Customs Procedures",
        "url": "https://www.sadc.int",
        "description": (
            "SADC trade facilitation references for tariff treatment and harmonized customs "
            "documentation in Southern Africa."
        ),
        "source": "Southern African Development Community (SADC)",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["sadc", "southern_africa", "trade_facilitation", "customs_docs", "tariffs"],
        "region_ids": ["africa"],
        "country_codes": ["za"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "comesa_trade_portal",
        "title": "COMESA Trade Portal – Free Trade Area and Customs Cooperation",
        "url": "https://www.comesa.int",
        "description": (
            "COMESA references for free-trade eligibility, customs policy harmonization, "
            "and regional market access for agricultural goods."
        ),
        "source": "COMESA",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["comesa", "free_trade_area", "customs_union", "market_access", "agriculture"],
        "region_ids": ["africa"],
        "country_codes": ["ke", "eg", "et"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "sars_customs_south_africa",
        "title": "SARS Customs – South Africa Import and Export Procedures",
        "url": "https://www.sars.gov.za/customs-and-excise/",
        "description": (
            "South African customs authority portal for tariff treatment, import/export "
            "documentation, and electronic customs processes."
        ),
        "source": "South African Revenue Service (SARS)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["south_africa", "sars", "customs", "tariffs", "import_export"],
        "region_ids": ["africa"],
        "country_codes": ["za"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "dalrrd_phytosanitary_south_africa",
        "title": "DALRRD – South Africa Phytosanitary and Produce Import Rules",
        "url": "https://www.dalrrd.gov.za",
        "description": (
            "South Africa agriculture authority references for phytosanitary controls and "
            "produce import requirements."
        ),
        "source": "Department of Agriculture, Land Reform and Rural Development (DALRRD)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["south_africa", "phytosanitary", "dalrrd", "produce", "import_requirements"],
        "region_ids": ["africa"],
        "country_codes": ["za"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "kra_customs_kenya",
        "title": "Kenya Revenue Authority Customs – iCustoms and Tariff Procedures",
        "url": "https://www.kra.go.ke/customs",
        "description": (
            "Kenya customs procedures and iCustoms workflows for import declarations, "
            "tariff handling, and clearance operations."
        ),
        "source": "Kenya Revenue Authority (KRA)",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["kenya", "kra", "icustoms", "tariffs", "clearance"],
        "region_ids": ["africa"],
        "country_codes": ["ke"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "hcd_kenya_horticulture_controls",
        "title": "Kenya Horticultural Crops Directorate – Import/Export Controls",
        "url": "https://www.agricultureauthority.go.ke/hcd/",
        "description": (
            "Kenya horticulture regulator for compliance and controls related to fruits, "
            "vegetables, and floriculture trade flows."
        ),
        "source": "Horticultural Crops Directorate (HCD)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["kenya", "hcd", "horticulture", "fruits", "vegetables", "compliance"],
        "region_ids": ["africa"],
        "country_codes": ["ke"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "nigeria_customs_nicis",
        "title": "Nigeria Customs Service – NICIS and Import Procedures",
        "url": "https://customs.gov.ng",
        "description": (
            "Nigeria Customs portal with electronic NICIS processing, import procedures, "
            "and tariff/duty compliance references."
        ),
        "source": "Nigeria Customs Service",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["nigeria", "customs", "nicis", "import_procedures", "duties"],
        "region_ids": ["africa"],
        "country_codes": ["ng"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "nafdac_food_labeling_nigeria",
        "title": "NAFDAC – Food Safety and Labeling Standards",
        "url": "https://www.nafdac.gov.ng",
        "description": (
            "Nigeria food and drug authority guidance on food safety, labeling, and product "
            "registration requirements relevant to imported produce."
        ),
        "source": "National Agency for Food and Drug Administration and Control (NAFDAC)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["nigeria", "nafdac", "food_safety", "labeling", "produce"],
        "region_ids": ["africa"],
        "country_codes": ["ng"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "egypt_customs_nafeza",
        "title": "Egyptian Customs and NAFEZA Single Window",
        "url": "https://www.nafeza.gov.eg",
        "description": (
            "Egypt single-window customs platform for electronic documentation and import "
            "clearance workflows."
        ),
        "source": "Egyptian Customs Authority",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["egypt", "nafeza", "single_window", "customs", "clearance"],
        "region_ids": ["africa"],
        "country_codes": ["eg"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "ethiopian_customs_commission",
        "title": "Ethiopian Customs Commission – Import and Export Tariff Procedures",
        "url": "https://www.ecc.gov.et",
        "description": (
            "Ethiopia customs authority guidance on tariff procedures and import/export "
            "clearance requirements for traded goods including produce."
        ),
        "source": "Ethiopian Customs Commission",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["ethiopia", "customs", "tariffs", "clearance", "import_export"],
        "region_ids": ["africa"],
        "country_codes": ["et"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "ghana_gra_customs",
        "title": "GRA Customs – Ghana Import and Tariff Procedures",
        "url": "https://gra.gov.gh/customs/",
        "description": (
            "Ghana customs procedures and tariff references for imported goods, including "
            "fresh produce compliance pathways."
        ),
        "source": "Ghana Revenue Authority (GRA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["ghana", "gra", "customs", "tariffs", "produce_import"],
        "region_ids": ["africa"],
        "country_codes": ["gh"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "pprsd_ghana_phytosanitary",
        "title": "Ghana PPRSD – Phytosanitary Import Controls",
        "url": "https://mofa.gov.gh/site/directorates/plant-protection-and-regulatory-services-directorate",
        "description": (
            "Ghana phytosanitary authority guidance on plant protection and produce "
            "import compliance requirements."
        ),
        "source": "Plant Protection and Regulatory Services Directorate (PPRSD)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["ghana", "pprsd", "phytosanitary", "plant_protection", "produce"],
        "region_ids": ["africa"],
        "country_codes": ["gh"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "africa_major_ports_produce",
        "title": "Africa Produce Ports and Air Cargo Hubs",
        "url": "https://www.porttechnology.org",
        "description": (
            "Operational reference for major African produce gateways including Durban, Cape Town, "
            "Mombasa, Lagos, Alexandria, Port Said, Tema, Takoradi, and key air cargo hubs."
        ),
        "source": "Port and Logistics Industry References",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["africa", "ports", "air_cargo", "cold_chain", "produce_logistics"],
        "region_ids": ["africa"],
        "country_codes": ["za", "ke", "ng", "eg", "gh", "et"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "africa_produce_import_checklist",
        "title": "Africa Produce Import Checklist – Admissibility to Clearance",
        "url": "https://www.intracen.org/market-information-tools",
        "description": (
            "Checklist for produce imports into African markets covering admissibility checks, "
            "phytosanitary certificates, origin proof, permits, HS code classification, and clearance."
        ),
        "source": "International Trade Centre (ITC)",
        "source_type": "faq",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["africa", "checklist", "phytosanitary", "certificate_of_origin", "hs_code", "customs"],
        "region_ids": ["africa"],
        "country_codes": ["za", "ke", "ng", "eg", "et", "gh"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "africa_trade_policy_centre",
        "title": "African Trade Policy Centre (ATPC) – Market and Policy Insights",
        "url": "https://www.uneca.org/atpc",
        "description": (
            "ATPC resources for African trade policy analysis, market insights, and support "
            "materials relevant to agri-trade planning."
        ),
        "source": "African Trade Policy Centre (ATPC)",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["africa", "atpc", "policy_analysis", "market_insights", "trade"],
        "region_ids": ["africa"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "itc_market_access_map_africa",
        "title": "ITC Market Access Map – African Tariffs and Trade Barriers",
        "url": "https://www.macmap.org",
        "description": (
            "Tariff and trade-barrier intelligence tool to evaluate produce market access "
            "conditions across African destination countries."
        ),
        "source": "International Trade Centre (ITC)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["itc", "market_access", "tariffs", "trade_barriers", "africa"],
        "region_ids": ["africa"],
        "country_codes": ["za", "ke", "ng", "eg", "et", "gh"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "afdb_trade_finance_support",
        "title": "AfDB Trade Finance – Support for Importers and Exporters",
        "url": "https://www.afdb.org/en/topics-and-sectors/initiatives-partnerships/trade-finance",
        "description": (
            "African Development Bank trade-finance programs supporting cross-border commerce, "
            "including financing and risk-mitigation instruments relevant to produce trade."
        ),
        "source": "African Development Bank (AfDB)",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["afdb", "trade_finance", "risk_mitigation", "africa", "import_export"],
        "region_ids": ["africa"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── South America ─────────────────────────────────────────────────────────

    {
        "_key": "mercosur_trade_agri",
        "title": "MERCOSUR – Agricultural Trade Rules and Protocols",
        "url": "https://www.mercosur.int",
        "description": (
            "Official MERCOSUR portal for trade agreements, tariff schedules, and "
            "sanitary and phytosanitary (SPS) protocols applicable to agricultural "
            "exports from Argentina, Brazil, Chile, Colombia, and Uruguay."
        ),
        "source": "MERCOSUR Secretariat",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["mercosur", "south_america", "tariff", "sps", "trade_agreement"],
        "region_ids": ["south_america"],
        "country_codes": ["ar", "br", "cl", "co"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "producepay_marketplace_latam",
        "title": "ProducePay Marketplace – Verified Grower and Buyer Network",
        "url": "https://producepay.com",
        "description": (
            "Digital marketplace connecting verified growers and buyers across Latin America, "
            "the US, and Canada, with tools to streamline produce trade workflows."
        ),
        "source": "ProducePay",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["latin_america", "buyers", "growers", "marketplace", "b2b"],
        "region_ids": ["south_america", "central_america", "north_america"],
        "country_codes": ["mx", "br", "co", "pe", "cl", "ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "latin_america_sourcing_b2b",
        "title": "Latin America Sourcing – Verified B2B Supplier Platform",
        "url": "https://latinamericasourcing.com",
        "description": (
            "B2B sourcing platform linking international buyers with verified Latin American "
            "suppliers for fresh produce and agricultural goods."
        ),
        "source": "Latin America Sourcing",
        "source_type": "directory",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["latin_america", "b2b", "suppliers", "quotes", "buyer_discovery"],
        "region_ids": ["south_america", "central_america", "caribbean"],
        "country_codes": ["ec", "co", "pe", "cl", "br"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "well_pack_latam_exports",
        "title": "Well Pack – Latin America Fresh and Organic Export Services",
        "url": "https://wellpack.org",
        "description": (
            "Exporter specializing in fresh and organic fruits and vegetables from Latin America, "
            "with emphasis on packaging quality and logistics execution."
        ),
        "source": "Well Pack",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["latin_america", "organic", "export", "packaging", "logistics"],
        "region_ids": ["south_america", "central_america"],
        "country_codes": ["ec", "co", "pe"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "latam_export_top_products",
        "title": "Latin America Export Profile – Top Produce Categories",
        "url": "https://hco.com",
        "description": (
            "Market profile summarizing major Latin American exports including bananas, avocados, "
            "berries, grapes, mangoes, coffee, and grains, with destination demand in US/EU/Asia."
        ),
        "source": "HCO",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["latin_america", "export_profile", "fruits", "vegetables", "demand"],
        "region_ids": ["south_america", "central_america", "caribbean"],
        "country_codes": ["mx", "br", "co", "pe", "cl"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "latam_export_growth_2024",
        "title": "Latin America Agricultural Export Growth and Nearshoring Trends",
        "url": "https://hco.com",
        "description": (
            "Insight on export value growth, nearshoring momentum, and stronger North America "
            "flows supported by trade agreements and evolving buyer demand."
        ),
        "source": "HCO",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["latin_america", "growth", "nearshoring", "usmca", "trade_agreements"],
        "region_ids": ["south_america", "central_america", "north_america"],
        "country_codes": ["mx", "br", "co", "pe", "cl", "ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "latam_certification_globalgap_fairtrade",
        "title": "Latin America Certification Pathways – GLOBALG.A.P. and Fairtrade",
        "url": "https://autorfoods.com",
        "description": (
            "Guidance on using certification schemes such as GLOBALG.A.P. and Fairtrade to "
            "access premium export channels for Latin American produce."
        ),
        "source": "Autor Foods",
        "source_type": "certification",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["latin_america", "globalgap", "fairtrade", "sustainability", "premium_markets"],
        "region_ids": ["south_america", "central_america", "caribbean"],
        "country_codes": ["mx", "br", "co", "pe", "cl", "ec"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "aduana_news_trade_logistics",
        "title": "Aduana News – Latin America Customs and Trade Logistics Updates",
        "url": "https://www.aduananews.com",
        "description": (
            "Regional news portal covering customs, transport, foreign trade regulation changes, "
            "and logistics opportunities relevant to produce exporters."
        ),
        "source": "Aduana News",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["latin_america", "customs", "transport", "trade_news", "logistics"],
        "region_ids": ["south_america", "central_america", "caribbean"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "biz_latin_hub_trade_insights",
        "title": "Biz Latin Hub – Trade and Regulatory Insights",
        "url": "https://www.bizlatinhub.com",
        "description": (
            "Business and trade analysis on regulatory shifts, investment conditions, and "
            "market-entry opportunities in major Latin American economies."
        ),
        "source": "Biz Latin Hub",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["latin_america", "regulatory_updates", "market_entry", "investment", "trade_trends"],
        "region_ids": ["south_america", "central_america", "caribbean"],
        "country_codes": ["mx", "br", "co", "pe", "cl", "ar"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "latam_cold_chain_export_playbook",
        "title": "Latin America Cold Chain and Perishable Export Playbook",
        "url": "https://producepay.com",
        "description": (
            "Practical guidance on cold-chain integrity, shipment quality protection, and "
            "logistics risk management for perishable exports from Latin America."
        ),
        "source": "ProducePay",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["latin_america", "cold_chain", "perishables", "quality", "logistics_risk"],
        "region_ids": ["south_america", "central_america"],
        "country_codes": ["mx", "br", "co", "pe", "cl", "ec"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "latam_buyer_network_strategy",
        "title": "Latin America Buyer Network Strategy – US, EU, and Asia",
        "url": "https://latinamericasourcing.com",
        "description": (
            "Exporter-focused strategy reference for building importer relationships in US, EU, "
            "and Asia where demand for Latin American produce is strongest."
        ),
        "source": "Latin America Sourcing",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["latin_america", "buyers", "importers", "eu", "asia", "north_america"],
        "region_ids": ["south_america", "central_america", "north_america", "european_union", "east_asia"],
        "country_codes": ["mx", "br", "co", "pe", "cl"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "usmca_produce_trade_framework",
        "title": "USMCA – Produce Trade Framework for North America",
        "url": "https://producepay.com",
        "description": (
            "USMCA reference for tariff-free or reduced-tariff fresh produce trade flows "
            "between Mexico, the United States, and Canada, including streamlined customs pathways."
        ),
        "source": "ProducePay",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["usmca", "north_america", "mexico", "canada", "fresh_produce", "tariff_free"],
        "region_ids": ["north_america", "central_america", "south_america"],
        "country_codes": ["mx", "ca", "us"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_mercosur_trade_agreement_pending",
        "title": "EU-MERCOSUR Agreement – Produce Access Outlook (Pending Ratification)",
        "url": "https://www.bizlatinhub.com",
        "description": (
            "Agreement outlook covering expected tariff reductions for MERCOSUR agricultural "
            "exports into the EU, with implications for fruits and vegetables."
        ),
        "source": "Biz Latin Hub",
        "source_type": "policy",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["eu_mercosur", "south_america", "europe", "tariffs", "market_access"],
        "region_ids": ["south_america", "european_union", "nordic_market"],
        "country_codes": ["ar", "br", "py", "uy"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "pacific_alliance_produce_trade",
        "title": "Pacific Alliance – Produce Trade Liberalization",
        "url": "https://www.bizlatinhub.com",
        "description": (
            "Trade framework for Chile, Colombia, Mexico, and Peru supporting reduced barriers "
            "and harmonized standards for produce exports to key global markets."
        ),
        "source": "Biz Latin Hub",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["pacific_alliance", "chile", "colombia", "mexico", "peru", "produce_trade"],
        "region_ids": ["south_america", "central_america", "southeast_asia", "east_asia"],
        "country_codes": ["cl", "co", "mx", "pe"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cptpp_produce_market_access",
        "title": "CPTPP – Produce Market Access Across Pacific Economies",
        "url": "https://www.bizlatinhub.com",
        "description": (
            "CPTPP guidance for produce exporters on tariff reduction and market access among "
            "Pacific Rim members, including Canada, Mexico, Peru, Chile, Australia, and New Zealand."
        ),
        "source": "Biz Latin Hub",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["cptpp", "pacific_rim", "tariff_reduction", "produce", "market_access"],
        "region_ids": ["north_america", "south_america", "southeast_asia", "east_asia"],
        "country_codes": ["ca", "mx", "pe", "cl", "au", "nz"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_latam_bilateral_produce_agreements",
        "title": "EU-Latin America Bilateral Produce Trade Agreements",
        "url": "https://www.bizlatinhub.com",
        "description": (
            "Reference for EU agreements with Colombia/Peru/Ecuador, Central America, and Mexico "
            "that improve tariff preferences for fresh produce exports into Europe."
        ),
        "source": "Biz Latin Hub",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["eu", "latin_america", "bilateral", "tariff_preferences", "fresh_produce"],
        "region_ids": ["european_union", "nordic_market", "south_america", "central_america"],
        "country_codes": ["co", "pe", "ec", "mx"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "gcc_latam_bilateral_trade",
        "title": "GCC-Latin America Bilateral Produce Trade Pathways",
        "url": "https://bestfoodimporters.com",
        "description": (
            "Practical view of bilateral GCC-Latin America channels that can reduce friction "
            "for produce imports into UAE and neighboring Gulf markets."
        ),
        "source": "Best Food Importers",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["gcc", "latin_america", "bilateral_trade", "uae", "produce_imports"],
        "region_ids": ["gulf_cooperation_council", "south_america", "central_america"],
        "country_codes": ["ae", "sa", "qa", "kw", "om", "bh", "pe", "mx"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "jafza_produce_reexport_hub",
        "title": "Jebel Ali Free Zone (JAFZA) – Produce Re-export Hub",
        "url": "https://www.jafza.ae",
        "description": (
            "Free-zone operating model enabling duty-efficient import, storage, and re-export "
            "of produce across Middle East distribution networks."
        ),
        "source": "JAFZA",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["jafza", "jebel_ali", "free_zone", "re_export", "middle_east", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "pafta_australia_peru_produce",
        "title": "PAFTA – Australia-Peru Produce Trade Agreement",
        "url": "https://www.bizlatinhub.com",
        "description": (
            "Australia-Peru FTA context for reduced agricultural tariffs and expanded produce "
            "trade opportunities between Peru and Australia."
        ),
        "source": "Biz Latin Hub",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["pafta", "australia", "peru", "fta", "produce_trade"],
        "region_ids": ["southeast_asia", "south_america"],
        "country_codes": ["au", "pe"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── Central America ───────────────────────────────────────────────────────

    {
        "_key": "cafta_dr_trade",
        "title": "CAFTA-DR – Central America–Dominican Republic Free Trade Agreement",
        "url": "https://ustr.gov/trade-agreements/free-trade-agreements/cafta-dr-dominican-republic-central-america-fta",
        "description": (
            "USTR overview of CAFTA-DR covering tariff elimination schedules, rules of "
            "origin, and import/export procedures for Guatemala, Costa Rica, and other "
            "Central American signatory countries."
        ),
        "source": "Office of the United States Trade Representative (USTR)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["cafta", "central_america", "tariff", "rules_of_origin", "trade_agreement"],
        "region_ids": ["central_america", "caribbean"],
        "country_codes": ["cr", "gt", "do"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "sieca_trade_portal",
        "title": "SIECA Trade Intelligence and Regional Integration Portal",
        "url": "https://www.sieca.int",
        "description": (
            "Regional trade integration and facilitation resources for Central America, "
            "including customs modernization references and market access coordination."
        ),
        "source": "Secretariat for Central American Economic Integration (SIECA)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["central_america", "sieca", "integration", "trade_facilitation", "customs"],
        "region_ids": ["central_america"],
        "country_codes": ["gt", "sv", "hn", "ni", "cr", "pa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "oirsa_sps_guidelines",
        "title": "OIRSA SPS and Phytosanitary Coordination for Mesoamerica",
        "url": "https://www.oirsa.org",
        "description": (
            "Regional cooperation resources on sanitary and phytosanitary controls "
            "for agricultural trade flows in Central America."
        ),
        "source": "OIRSA",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["central_america", "oirsa", "sps", "phytosanitary", "agri_trade"],
        "region_ids": ["central_america"],
        "country_codes": ["gt", "sv", "hn", "ni", "cr", "pa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "guatemala_sat_customs",
        "title": "Guatemala SAT Customs Import and Export Procedures",
        "url": "https://portal.sat.gob.gt/portal/aduanas/",
        "description": (
            "Guatemala customs authority references for declarations, tariff processing, "
            "and import-export documentation requirements."
        ),
        "source": "Superintendencia de Administracion Tributaria (SAT)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["guatemala", "sat", "customs", "declarations", "tariff"],
        "region_ids": ["central_america"],
        "country_codes": ["gt"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "costa_rica_tica_customs",
        "title": "Costa Rica TICA Customs and Declaration System",
        "url": "https://www.hacienda.go.cr",
        "description": (
            "Costa Rica customs and declaration workflow references for import-export "
            "processing and compliance submissions."
        ),
        "source": "Ministerio de Hacienda de Costa Rica",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["costa_rica", "tica", "customs", "declaration", "compliance"],
        "region_ids": ["central_america"],
        "country_codes": ["cr"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "panama_aduanas_import_guide",
        "title": "Panama National Customs Authority Import Guidance",
        "url": "https://www.ana.gob.pa",
        "description": (
            "Panama customs references for import clearance, tariff treatment, "
            "and required trade documentation."
        ),
        "source": "Autoridad Nacional de Aduanas de Panama",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["panama", "customs", "import_guide", "tariff", "documentation"],
        "region_ids": ["central_america"],
        "country_codes": ["pa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "honduras_senasa_plant_health",
        "title": "Honduras SENASA Plant Health and Produce Import Controls",
        "url": "https://www.senasa.gob.hn",
        "description": (
            "Plant health and produce admissibility references covering phytosanitary "
            "obligations and inspection requirements in Honduras."
        ),
        "source": "SENASA Honduras",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["honduras", "senasa", "plant_health", "phytosanitary", "produce"],
        "region_ids": ["central_america"],
        "country_codes": ["hn"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "el_salvador_mh_customs",
        "title": "El Salvador Customs and Tariff Procedures",
        "url": "https://www.mh.gob.sv",
        "description": (
            "El Salvador customs procedures for declarations, tariff handling, "
            "and produce import/export documentation."
        ),
        "source": "Ministerio de Hacienda de El Salvador",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["el_salvador", "customs", "tariff", "declarations", "produce_trade"],
        "region_ids": ["central_america"],
        "country_codes": ["sv"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "nicaragua_dga_customs",
        "title": "Nicaragua DGA Customs Documentation and Clearance",
        "url": "https://www.dga.gob.ni",
        "description": (
            "Nicaragua customs references for documentation workflows, declarations, "
            "and border clearance procedures."
        ),
        "source": "Direccion General de Servicios Aduaneros (DGA)",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["nicaragua", "dga", "customs", "clearance", "documentation"],
        "region_ids": ["central_america"],
        "country_codes": ["ni"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "puerto_cortes_logistics_hub",
        "title": "Puerto Cortes Logistics and Reefer Operations",
        "url": "https://enp.hn",
        "description": (
            "Honduras port logistics reference with cold-chain and reefer handling "
            "relevance for produce imports and exports."
        ),
        "source": "Empresa Nacional Portuaria (Honduras)",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["honduras", "puerto_cortes", "reefer", "cold_chain", "logistics"],
        "region_ids": ["central_america"],
        "country_codes": ["hn"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "panama_pacifico_logistics_platform",
        "title": "Panama Pacifico and Canal-Area Logistics for Perishables",
        "url": "https://www.panamapacifico.com",
        "description": (
            "Logistics platform references for multimodal handling and distribution of "
            "perishable produce moving through Panama trade corridors."
        ),
        "source": "Panama Pacifico",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["panama", "logistics", "canal", "perishables", "multimodal"],
        "region_ids": ["central_america"],
        "country_codes": ["pa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── Caribbean ─────────────────────────────────────────────────────────────

    {
        "_key": "caricom_agri_trade",
        "title": "CARICOM – Agricultural Trade and Single Market Rules",
        "url": "https://www.caricom.org/subjects/agriculture",
        "description": (
            "CARICOM secretariat resources covering the CARICOM Single Market and "
            "Economy (CSME) agricultural trade rules, food security protocols, and "
            "import/export facilitation for Caribbean island states."
        ),
        "source": "Caribbean Community (CARICOM) Secretariat",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["caricom", "caribbean", "single_market", "food_security", "trade"],
        "region_ids": ["caribbean"],
        "country_codes": ["do"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "caricom_trade_support_portal",
        "title": "CARICOM Trade Support and Market Integration Resources",
        "url": "https://www.caricom.org",
        "description": (
            "Regional references on CARICOM market integration, trade policy alignment, "
            "and support channels for produce commerce."
        ),
        "source": "Caribbean Community (CARICOM) Secretariat",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["caribbean", "caricom", "integration", "trade_policy", "produce_trade"],
        "region_ids": ["caribbean"],
        "country_codes": ["bb", "tt", "jm", "gy", "bs", "do"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "crosq_food_standards",
        "title": "CROSQ Regional Food Standards and SPS Alignment",
        "url": "https://www.crosq.org",
        "description": (
            "Regional standards references supporting food safety alignment, SPS practices, "
            "and quality frameworks used across Caribbean markets."
        ),
        "source": "CARICOM Regional Organisation for Standards and Quality (CROSQ)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["caribbean", "crosq", "sps", "food_safety", "standards"],
        "region_ids": ["caribbean"],
        "country_codes": ["bb", "tt", "jm"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "oecs_trade_policy_resources",
        "title": "OECS Trade Policy and Customs Coordination",
        "url": "https://www.oecs.org",
        "description": (
            "OECS references on customs coordination and trade policy for smaller island "
            "economies participating in regional produce trade."
        ),
        "source": "Organisation of Eastern Caribbean States (OECS)",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["oecs", "caribbean", "trade_policy", "customs", "island_states"],
        "region_ids": ["caribbean"],
        "country_codes": ["ag", "lc", "gd", "dm", "kn", "vc"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "jamaica_customs_agency_portal",
        "title": "Jamaica Customs Agency Import and Clearance Portal",
        "url": "https://www.jacustoms.gov.jm",
        "description": (
            "Jamaica customs references for import declarations, valuation, and "
            "clearance workflows for food and produce consignments."
        ),
        "source": "Jamaica Customs Agency",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["jamaica", "customs", "clearance", "declarations", "produce"],
        "region_ids": ["caribbean"],
        "country_codes": ["jm"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "trinidad_customs_import_rules",
        "title": "Trinidad and Tobago Customs Import Rules and Tariffs",
        "url": "https://www.customs.gov.tt",
        "description": (
            "Trinidad and Tobago customs authority guidance for tariff schedules, "
            "documentation, and produce import compliance."
        ),
        "source": "Customs and Excise Division of Trinidad and Tobago",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["trinidad", "tobago", "customs", "tariffs", "import_rules"],
        "region_ids": ["caribbean"],
        "country_codes": ["tt"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "dominican_republic_dga_customs",
        "title": "Dominican Republic DGA Customs and Trade Procedures",
        "url": "https://www.aduanas.gob.do",
        "description": (
            "Dominican Republic customs guidance for import/export declarations, "
            "tariff handling, and clearance processing."
        ),
        "source": "Direccion General de Aduanas (DGA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["dominican_republic", "dga", "customs", "trade_procedures", "tariff"],
        "region_ids": ["caribbean"],
        "country_codes": ["do"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "barbados_customs_trade_info",
        "title": "Barbados Customs and Excise Trade Information",
        "url": "https://www.barbadoscustoms.gov.bb",
        "description": (
            "Barbados customs references for tariff classification, declarations, "
            "and import clearance procedures."
        ),
        "source": "Barbados Customs and Excise Department",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["barbados", "customs", "trade_info", "tariff", "clearance"],
        "region_ids": ["caribbean"],
        "country_codes": ["bb"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "jamaica_moa_phytosanitary",
        "title": "Jamaica Plant Quarantine and Produce Import Controls",
        "url": "https://moa.gov.jm",
        "description": (
            "Plant quarantine and phytosanitary references supporting produce import "
            "admissibility and inspection readiness in Jamaica."
        ),
        "source": "Ministry of Agriculture, Fisheries and Mining (Jamaica)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["jamaica", "phytosanitary", "plant_quarantine", "produce", "inspection"],
        "region_ids": ["caribbean"],
        "country_codes": ["jm"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "point_lisas_port_cold_chain",
        "title": "Point Lisas and Trinidad Port Cold-Chain Handling",
        "url": "https://www.plipdeco.com",
        "description": (
            "Port logistics reference for cold-chain and container handling relevant "
            "to produce imports in Trinidad and Tobago."
        ),
        "source": "Point Lisas Industrial Port Development Corporation",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["trinidad", "point_lisas", "cold_chain", "reefer", "port_logistics"],
        "region_ids": ["caribbean"],
        "country_codes": ["tt"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "caucedo_port_dominican_logistics",
        "title": "Port of Caucedo Produce Import and Reefer Logistics",
        "url": "https://www.dpworld.com/caucedo",
        "description": (
            "Dominican Republic port logistics reference for reefer handling and produce "
            "distribution operations in Caribbean trade lanes."
        ),
        "source": "DP World Caucedo",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["dominican_republic", "caucedo", "reefer", "port", "distribution"],
        "region_ids": ["caribbean"],
        "country_codes": ["do"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── East Asia ─────────────────────────────────────────────────────────────

    {
        "_key": "china_customs_gacc",
        "title": "GACC – General Administration of Customs of China",
        "url": "http://english.customs.gov.cn",
        "description": (
            "China's customs authority portal covering import registration for overseas "
            "food producers (CIFER system), phytosanitary inspection, and labelling "
            "requirements for agricultural products entering China."
        ),
        "source": "General Administration of Customs of China (GACC)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["china", "customs", "cifer", "food_import", "phytosanitary"],
        "region_ids": ["east_asia"],
        "country_codes": ["cn"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "rcep_trade_agreement",
        "title": "RCEP – Regional Comprehensive Economic Partnership",
        "url": "https://rcepsec.org",
        "description": (
            "Official RCEP secretariat site covering the world's largest free trade "
            "agreement, including tariff schedules and rules of origin for agricultural "
            "goods between ASEAN, China, Japan, South Korea, Australia, and New Zealand."
        ),
        "source": "RCEP Secretariat",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["rcep", "east_asia", "southeast_asia", "tariff", "trade_agreement"],
        "region_ids": ["east_asia", "southeast_asia"],
        "country_codes": ["cn", "id"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "china_mara_wholesale_price_index",
        "title": "China MARA Agricultural Product Wholesale Price Index",
        "url": "http://english.moa.gov.cn",
        "description": (
            "Official Chinese agriculture ministry reference for wholesale agricultural and produce "
            "price trend indicators used in market monitoring."
        ),
        "source": "Ministry of Agriculture and Rural Affairs (China)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "china", "mara", "wholesale_index", "produce"],
        "region_ids": ["east_asia"],
        "country_codes": ["cn"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "beijing_xinfadi_daily_prices",
        "title": "Beijing Xinfadi Market Daily Produce Prices",
        "url": "http://www.xinfadi.com.cn",
        "description": (
            "Major Beijing wholesale market reference for day-to-day fruit and vegetable "
            "spot prices and market movement signals."
        ),
        "source": "Beijing Xinfadi Wholesale Market",
        "source_type": "directory",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "china", "xinfadi", "daily_prices", "wholesale_market"],
        "region_ids": ["east_asia"],
        "country_codes": ["cn"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "korea_kamis_produce_prices",
        "title": "KAMIS Korea Produce Price Information",
        "url": "https://www.kamis.or.kr/customer/main/main.do",
        "description": (
            "Korea Agro-Fisheries and Food Trade Information Service pricing dashboard for "
            "agricultural products, including produce market indicators."
        ),
        "source": "Korea Agro-Fisheries and Food Trade Corporation (aT)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "south_korea", "kamis", "market_prices", "produce"],
        "region_ids": ["east_asia"],
        "country_codes": ["kr"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "japan_maff_plant_protection_station",
        "title": "Japan MAFF Plant Protection Station Import Rules",
        "url": "https://www.maff.go.jp/pps/j/",
        "description": (
            "Plant protection and phytosanitary import guidance for plants and produce entering "
            "Japan, including inspection procedures and restricted items."
        ),
        "source": "Ministry of Agriculture, Forestry and Fisheries (Japan)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["japan", "maff", "plant_protection", "phytosanitary", "import_rules"],
        "region_ids": ["east_asia"],
        "country_codes": ["jp"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "korea_mfds_import_food_rules",
        "title": "Korea MFDS Imported Food Safety and Clearance Rules",
        "url": "https://www.mfds.go.kr/eng/",
        "description": (
            "South Korea food safety authority guidance for imported food and produce, including "
            "documentation and compliance obligations."
        ),
        "source": "Ministry of Food and Drug Safety (Korea)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["south_korea", "mfds", "import_food", "compliance", "produce"],
        "region_ids": ["east_asia"],
        "country_codes": ["kr"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "hong_kong_ced_trade_declarations",
        "title": "Hong Kong C&ED Trade Declaration and Import Procedures",
        "url": "https://www.customs.gov.hk/en/trade_facilitation/index.html",
        "description": (
            "Hong Kong customs and excise guidance for trade declarations, import/export procedures, "
            "and commodity handling references."
        ),
        "source": "Hong Kong Customs and Excise Department",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["hong_kong", "customs", "trade_declaration", "import_export", "procedures"],
        "region_ids": ["east_asia"],
        "country_codes": ["hk"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── Southeast Asia ────────────────────────────────────────────────────────

    {
        "_key": "asean_agri_trade",
        "title": "ASEAN – Agricultural Trade and AEC Integration",
        "url": "https://asean.org/asean-economic-community/",
        "description": (
            "ASEAN Economic Community (AEC) portal covering tariff reductions, "
            "non-tariff measures, and sanitary and phytosanitary standards for "
            "agricultural goods among ASEAN member states."
        ),
        "source": "ASEAN Secretariat",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["asean", "southeast_asia", "aec", "tariff", "sps"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["id"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "asean_afsis_price_monitor",
        "title": "AFSIS ASEAN Agricultural Price and Market Monitor",
        "url": "https://www.aptfsis.org",
        "description": (
            "ASEAN Food Security Information System references for regional agricultural indicators "
            "and market monitoring across member states."
        ),
        "source": "ASEAN Food Security Information System (AFSIS)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "asean", "afsis", "market_monitoring", "agriculture"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["id", "th", "vn", "my", "sg", "ph"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "thailand_talad_thai_prices",
        "title": "Talad Thai Wholesale Market Produce Prices",
        "url": "https://taladthai.com",
        "description": (
            "Thailand wholesale market pricing reference for fruits and vegetables with daily "
            "spot signals used by domestic and regional traders."
        ),
        "source": "Talad Thai",
        "source_type": "directory",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "thailand", "talad_thai", "wholesale", "produce"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["th"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "indonesia_pihps_wholesale_prices",
        "title": "Indonesia PIHPS Food and Produce Price Dashboard",
        "url": "https://www.bi.go.id/hargapangan",
        "description": (
            "Indonesia strategic food price dashboard with market-level indicators relevant to "
            "produce and wholesale planning."
        ),
        "source": "Bank Indonesia / PIHPS",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "indonesia", "pihps", "food_prices", "market_dashboard"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["id"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "singapore_pasir_panjang_prices",
        "title": "Singapore Pasir Panjang Produce Market Pricing References",
        "url": "https://www.sfa.gov.sg",
        "description": (
            "Singapore produce gateway references for import-oriented market price signals and "
            "supply-chain monitoring context."
        ),
        "source": "Singapore Food Agency (SFA)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "singapore", "pasir_panjang", "import_hub", "produce"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["sg"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "vietnam_agrotrade_market_bulletins",
        "title": "Vietnam Agrotrade Market Bulletins for Produce",
        "url": "https://agro.gov.vn",
        "description": (
            "Vietnam market intelligence bulletins and trade updates covering produce flow, "
            "import-export context, and demand trends."
        ),
        "source": "Vietnam Agrotrade",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["vietnam", "agrotrade", "market_bulletin", "produce", "trade_updates"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["vn"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "malaysia_fama_produce_market",
        "title": "Malaysia FAMA Produce Market and Distribution Guidance",
        "url": "https://www.fama.gov.my",
        "description": (
            "Malaysia FAMA references for domestic and export produce marketing channels, "
            "distribution, and market access support."
        ),
        "source": "Federal Agricultural Marketing Authority (FAMA)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["malaysia", "fama", "market_access", "distribution", "produce"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["my"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "philippines_bpi_plant_quarantine",
        "title": "Philippines BPI Plant Quarantine and Produce Import Rules",
        "url": "https://www.bpi.gov.ph",
        "description": (
            "Plant Industry references for phytosanitary permits, quarantine procedures, and "
            "produce import compliance in the Philippines."
        ),
        "source": "Bureau of Plant Industry (Philippines)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["philippines", "bpi", "plant_quarantine", "phytosanitary", "produce"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["ph"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── Australia and Pacific (APAC) ────────────────────────────────────────

    {
        "_key": "daff_bicon_import_conditions",
        "title": "DAFF BICON – Australia Import Conditions Database",
        "url": "https://bicon.agriculture.gov.au/BiconWeb4.0",
        "description": (
            "Official Australian Biosecurity Import Conditions (BICON) system to verify "
            "produce admissibility, treatment requirements, permits, and documentation."
        ),
        "source": "Australian Government – Department of Agriculture, Fisheries and Forestry (DAFF)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["australia", "bicon", "biosecurity", "permits", "import_conditions"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "daff_importing_food_plants",
        "title": "DAFF – Importing Food and Plant Products into Australia",
        "url": "https://www.agriculture.gov.au/biosecurity-trade/import",
        "description": (
            "DAFF guidance on Australia import permits, phytosanitary requirements, "
            "labeling expectations, and biosecurity controls for commercial produce imports."
        ),
        "source": "Australian Government – Department of Agriculture, Fisheries and Forestry (DAFF)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["australia", "biosecurity", "phytosanitary", "labeling", "fresh_produce"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "australian_border_force_imports",
        "title": "Australian Border Force – Import and Customs Requirements",
        "url": "https://www.abf.gov.au/importing-exporting-and-manufacturing/importing/how-to-import",
        "description": (
            "Border and customs reference for importing goods into Australia, including "
            "customs declarations, duties, and documentation requirements."
        ),
        "source": "Australian Border Force",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["australia", "customs", "duties", "import_docs", "border"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "bgp_fresh_solutions_australia",
        "title": "BGP International and Fresh Solutions Group",
        "url": "https://www.horticulturetrade.com.au",
        "description": (
            "Importer/exporter network focused on premium fresh fruit and vegetables, "
            "with operating coverage in Queensland and Western Australia."
        ),
        "source": "BGP International / Fresh Solutions Group",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["australia", "importer", "distributor", "queensland", "western_australia"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "perfection_fresh_australia",
        "title": "Perfection Fresh Australia",
        "url": "https://www.perfection.com.au",
        "description": (
            "Major Australian supplier/exporter of fresh produce with strong food-safety "
            "and quality-control standards for domestic and international channels."
        ),
        "source": "Perfection Fresh Australia",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["australia", "fresh_produce", "supplier", "exporter", "food_safety"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "produce_a_la_carte_apac",
        "title": "Produce A La Carte – APAC Wholesale and Export Logistics",
        "url": "https://producealacarte.com.au",
        "description": (
            "Large APAC fruit and vegetable wholesaler with established export "
            "operations and door-to-door logistics capabilities."
        ),
        "source": "Produce A La Carte",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["apac", "wholesaler", "export", "door_to_door", "logistics"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "hudson_food_group_australia",
        "title": "Hudson Food Group – Imported Produce Distribution",
        "url": "https://hudsonfoodgroup.com.au",
        "description": (
            "Importer and distributor of Mediterranean and international fresh produce, "
            "serving Victoria hospitality and retail channels."
        ),
        "source": "Hudson Food Group",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["australia", "importer", "distributor", "victoria", "hospitality"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "basile_imports_australia",
        "title": "Basile Imports – National Produce Distribution",
        "url": "https://www.basileimports.com.au",
        "description": (
            "National importer/distributor with temperature-controlled storage and "
            "supply coverage for supermarkets, greengrocers, and health-food stores."
        ),
        "source": "Basile Imports",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["australia", "cold_chain", "distribution", "supermarkets", "greengrocers"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "daff_pacific_export_to_australia",
        "title": "DAFF – Exporting to Australia from the Pacific",
        "url": "https://www.agriculture.gov.au/biosecurity-trade/export/controlled-goods/plants-plant-products/pacific",
        "description": (
            "Guidance pathway for Pacific exporters to access the Australian market, "
            "including biosecurity, labeling, and market-entry requirements."
        ),
        "source": "Australian Government – Department of Agriculture, Fisheries and Forestry (DAFF)",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["pacific", "australia", "export_guidance", "biosecurity", "market_access"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au", "fj", "pg"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "australia_market_demand_quality",
        "title": "Australia Produce Demand Signals – Quality, Variety, and Off-Season",
        "url": "https://www.horticulturetrade.com.au",
        "description": (
            "Market insight highlighting Australian buyer preference for high-quality, "
            "fresh, organic, exotic, and off-season fruit and vegetable supply."
        ),
        "source": "Horticulture Trade",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["australia", "demand_trends", "quality", "organic", "off_season"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "australia_cold_chain_import_logistics",
        "title": "Australia Produce Import Logistics and Cold Chain Priorities",
        "url": "https://www.perfection.com.au",
        "description": (
            "Operational insight on cold-chain reliability, port checks, and compliance-aware "
            "distribution needed for importing produce into Australia."
        ),
        "source": "Perfection Fresh Australia",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["australia", "cold_chain", "ports", "biosecurity_checks", "distribution"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "aussie_food_export_network",
        "title": "Aussie Food Export – Produce Export and Buyer Support",
        "url": "https://aussiefoodexport.com",
        "description": (
            "Export support and sourcing channel for Australian food and produce, "
            "useful for buyers seeking Australian suppliers and trade coordination."
        ),
        "source": "Aussie Food Export",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["australia", "exporter", "buyer_support", "sourcing", "produce"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "daff_fresh_produce_import_guide",
        "title": "DAFF – Fresh Produce Import Guide",
        "url": "https://www.agriculture.gov.au/biosecurity-trade/import/goods/food/fresh-produce",
        "description": (
            "Official Australia guide for importing fresh produce, including biosecurity controls, "
            "permit pathways, inspections, and phytosanitary requirements."
        ),
        "source": "Australian Government – Department of Agriculture, Fisheries and Forestry (DAFF)",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["australia", "daff", "fresh_produce", "biosecurity", "import_guide"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "abf_import_goods_customs",
        "title": "Australian Border Force – Importing Goods and Customs Clearance",
        "url": "https://www.abf.gov.au/importing-exporting-and-manufacturing/importing",
        "description": (
            "ABF customs and border reference covering import declarations, duties, GST, "
            "tariff classification, and broker-assisted clearance."
        ),
        "source": "Australian Border Force",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["australia", "abf", "customs", "duty", "gst", "import_declarations"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "fsanz_imported_food_labeling",
        "title": "FSANZ – Imported Food Safety and Labeling Standards",
        "url": "https://www.foodstandards.gov.au/industry/importedfood",
        "description": (
            "Food safety and labeling standards for imported produce in Australia and New Zealand, "
            "including allergen and nutrition labeling obligations."
        ),
        "source": "Food Standards Australia New Zealand (FSANZ)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["fsanz", "imported_food", "labeling", "allergens", "food_safety"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au", "nz"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "dfat_fta_tariff_preferences",
        "title": "DFAT – Australia Free Trade Agreements and Tariff Preferences",
        "url": "https://www.dfat.gov.au/trade/agreements",
        "description": (
            "Australia FTA portal covering CPTPP, PAFTA, and RCEP with guidance on preferential "
            "tariff eligibility and rules of origin for produce trade."
        ),
        "source": "Australian Department of Foreign Affairs and Trade (DFAT)",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["australia", "fta", "dfat", "cptpp", "pafta", "rcep", "rules_of_origin"],
        "region_ids": ["southeast_asia", "east_asia", "south_america", "north_america"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "australia_ports_produce_imports",
        "title": "Australia Produce Entry Ports – Melbourne, Sydney, Brisbane, Fremantle",
        "url": "https://www.infrastructure.gov.au",
        "description": (
            "Reference for key Australian produce entry ports and cold-chain handling considerations "
            "for perishable imports."
        ),
        "source": "Australian Government Infrastructure References",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["australia", "ports", "melbourne", "sydney", "brisbane", "fremantle", "cold_chain"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── North America (Canada) ────────────────────────────────────────────────

    {
        "_key": "cfia_import_canada",
        "title": "CFIA – Canadian Food Inspection Agency Import Requirements",
        "url": "https://inspection.canada.ca/importing-food-plants-or-animals/food/eng/1327149296553/1327149368975",
        "description": (
            "Official CFIA portal covering Canadian import requirements for fresh "
            "produce, inspection procedures, phytosanitary certificates, and licensing "
            "under the Safe Food for Canadians Act (SFCA)."
        ),
        "source": "Canadian Food Inspection Agency (CFIA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["canada", "cfia", "import", "phytosanitary", "food_safety", "sfca"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "gacc_food_safety_import_export",
        "title": "GACC – Import and Export Food Safety Requirements",
        "url": "http://english.customs.gov.cn",
        "description": (
            "China customs and food safety requirements for imported produce, including inspection, "
            "quarantine, and clearance obligations."
        ),
        "source": "General Administration of Customs of China (GACC)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["china", "gacc", "food_safety", "quarantine", "produce_import"],
        "region_ids": ["east_asia"],
        "country_codes": ["cn"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "japan_customs_produce_imports",
        "title": "Japan Customs – Produce Import Procedures and Tariffs",
        "url": "https://www.customs.go.jp/english/",
        "description": (
            "Japan customs portal for import procedures, tariff guidance, and clearance rules "
            "for fruits and vegetables."
        ),
        "source": "Japan Customs",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["japan", "customs", "tariffs", "produce", "import_procedures"],
        "region_ids": ["east_asia"],
        "country_codes": ["jp"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "maff_plant_quarantine_japan",
        "title": "MAFF Japan – Plant Quarantine Requirements",
        "url": "https://www.maff.go.jp/e/",
        "description": (
            "Japan MAFF plant quarantine requirements for produce consignments, including phytosanitary "
            "controls and prohibited pest-risk materials."
        ),
        "source": "Ministry of Agriculture, Forestry and Fisheries (Japan)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["japan", "maff", "plant_quarantine", "phytosanitary", "produce_import"],
        "region_ids": ["east_asia"],
        "country_codes": ["jp"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "india_customs_agri_imports",
        "title": "India Customs – Agricultural Import Rules",
        "url": "https://www.cbic.gov.in",
        "description": (
            "India customs framework for tariffs, duties, and restrictions relevant to importing "
            "agricultural products including produce."
        ),
        "source": "Central Board of Indirect Taxes and Customs (India)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["india", "customs", "agricultural_imports", "duties", "restrictions"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["in"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "apeda_produce_trade_support",
        "title": "APEDA – Produce Trade and Compliance Support",
        "url": "https://apeda.gov.in",
        "description": (
            "India APEDA guidance on agricultural and processed food trade, including produce-related "
            "standards and export/import facilitation references."
        ),
        "source": "APEDA",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["india", "apeda", "produce_trade", "standards", "market_access"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["in"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "korea_customs_service_produce",
        "title": "Korea Customs Service – Produce Import Clearance",
        "url": "https://www.customs.go.kr/english/main.do",
        "description": (
            "South Korea customs portal for tariff lookup, customs procedures, and clearance "
            "requirements for imported produce."
        ),
        "source": "Korea Customs Service",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["south_korea", "customs", "tariff", "clearance", "produce_import"],
        "region_ids": ["east_asia"],
        "country_codes": ["kr"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "asean_trade_repository",
        "title": "ASEAN Trade Repository – Tariffs and Rules of Origin",
        "url": "https://atr.asean.org",
        "description": (
            "ASEAN-wide tariff and origin-rule database for agricultural products across member states, "
            "including ATIGA preferential frameworks."
        ),
        "source": "ASEAN",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["asean", "trade_repository", "rules_of_origin", "atiga", "tariffs"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["id", "th", "vn", "my", "sg"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "asean_food_safety_standards",
        "title": "ASEAN Food Safety Standards for Produce Trade",
        "url": "https://asean.org/our-communities/economic-community/",
        "description": (
            "Regional food safety references and harmonization initiatives relevant to produce "
            "trade within ASEAN markets."
        ),
        "source": "ASEAN Secretariat",
        "source_type": "policy",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["asean", "food_safety", "standards", "harmonization", "produce"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["id", "th", "vn", "my", "sg"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "asia_major_ports_produce_trade",
        "title": "Asia Produce Trade Ports – China, Japan, India, ASEAN",
        "url": "https://www.worldshipping.org",
        "description": (
            "Logistics hub reference for Shanghai, Ningbo, Guangzhou, Tokyo, Yokohama, Osaka, "
            "Mumbai, Chennai, Kolkata, Singapore, Laem Chabang, and Tanjung Priok."
        ),
        "source": "Shipping Industry References",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["asia", "ports", "logistics", "cold_chain", "produce_trade"],
        "region_ids": ["east_asia", "southeast_asia"],
        "country_codes": ["cn", "jp", "in", "sg", "th", "id"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "canada_cbsa_tariff",
        "title": "CBSA – Canadian Customs Tariff and Trade Data",
        "url": "https://www.cbsa-asfc.gc.ca/trade-commerce/tariff-tarif/menu-eng.html",
        "description": (
            "Canada Border Services Agency tariff schedule and automated trade data "
            "lookup tool for agricultural commodity codes, import duties, and "
            "preferential tariff rates under CUSMA/CETA."
        ),
        "source": "Canada Border Services Agency (CBSA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["canada", "cbsa", "tariff", "customs", "cusma", "ceta"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cfia_airs_canada",
        "title": "CFIA Automated Import Reference System (AIRS)",
        "url": "https://inspection.canada.ca/importing-food-plants-or-animals/plant-and-plant-product-imports/airs/eng/1326512904269/1326513001478",
        "description": (
            "Official CFIA AIRS tool to check admissibility, import requirements, "
            "and grade standards for produce entering Canada."
        ),
        "source": "Canadian Food Inspection Agency (CFIA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["canada", "cfia", "airs", "admissibility", "grade_standards", "compliance"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "pacific_customs_brokers_produce",
        "title": "Pacific Customs Brokers – Produce Import Compliance Guides",
        "url": "https://www.pcb.ca",
        "description": (
            "Guidance on importing produce into Canada, including licensing, labeling, "
            "and Safe Food for Canadians Regulations (SFCR) compliance."
        ),
        "source": "Pacific Customs Brokers (PCB)",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["canada", "sfcr", "licensing", "labeling", "import_compliance"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "gov_canada_food_plant_animal",
        "title": "Government of Canada – Bringing Food, Plant and Animal Products into Canada",
        "url": "https://inspection.canada.ca/importing-food-plants-or-animals/eng/1326604024807/1326604238518",
        "description": (
            "Government guidance on restrictions, permits, and border requirements for "
            "bringing food and plant products into Canada."
        ),
        "source": "Government of Canada",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["canada", "permits", "restrictions", "border_requirements", "food_import"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "orbit_brokers_sfcr",
        "title": "Orbit Brokers – SFCA and SFCR Licensing Insights",
        "url": "https://orbitbrokers.ca",
        "description": (
            "Importer-focused guidance on Safe Food for Canadians Act (SFCA) and SFCR "
            "licensing obligations for produce importers in Canada."
        ),
        "source": "Orbit Brokers",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["canada", "sfca", "sfcr", "licensing", "importer_of_record"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "gambles_produce_canada",
        "title": "Gambles Produce – Ontario Fresh Produce Supplier",
        "url": "https://www.goproduce.com",
        "description": (
            "Ontario-based produce supplier and distributor with broad domestic and imported "
            "produce coverage and market intelligence."
        ),
        "source": "Gambles Produce",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["canada", "ontario", "distributor", "fresh_produce", "market_reports"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "green_grocer_canada_importer",
        "title": "Green Grocer – Canadian Produce Importer",
        "url": "https://greengrocerinc.ca",
        "description": (
            "Canadian importer of high-quality produce sourced from Central and South America, "
            "the Caribbean, Europe, Africa, and the Middle East; includes packaging and private label services."
        ),
        "source": "Green Grocer",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["canada", "importer", "private_label", "packaging", "produce_distribution"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "fresh_direct_produce_canada",
        "title": "Fresh Direct Produce – Premium and Organic Produce",
        "url": "https://www.freshdirectproduce.com",
        "description": (
            "Canadian premium and organic produce distributor recognized for customer service "
            "and market expertise."
        ),
        "source": "Fresh Direct Produce",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["canada", "organic", "premium", "distributor", "produce"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cbsa_importing_commercial_goods",
        "title": "CBSA – Importing Commercial Goods into Canada",
        "url": "https://www.cbsa-asfc.gc.ca/import/menu-eng.html",
        "description": (
            "Primary CBSA portal for commercial import processes, customs declarations, duties, "
            "restricted goods checks, and importer compliance responsibilities."
        ),
        "source": "Canada Border Services Agency (CBSA)",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["canada", "cbsa", "commercial_import", "duties", "customs_procedures"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cfia_import_food_plant_products",
        "title": "CFIA – Importing Food and Plant Products",
        "url": "https://inspection.canada.ca/importing-food-plants-or-animals/eng/1326604024807/1326604238518",
        "description": (
            "CFIA import guidance for food and plant products with admissibility criteria, "
            "inspection triggers, and documentation expectations for fresh produce."
        ),
        "source": "Canadian Food Inspection Agency (CFIA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["canada", "cfia", "food_import", "plant_products", "inspection"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cfia_fresh_fruit_veg_requirements",
        "title": "CFIA – Fresh Fruit and Vegetable Import Requirements",
        "url": "https://inspection.canada.ca/food-safety-for-industry/importing-food/food-specific-requirements/fresh-fruits-and-vegetables/eng/1542745848183/1542745848425",
        "description": (
            "CFIA produce-specific import requirements including grade standards, pest and disease "
            "controls, and product-condition compliance for fruits and vegetables."
        ),
        "source": "Canadian Food Inspection Agency (CFIA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["canada", "cfia", "fresh_produce", "grade_standards", "pest_control"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "sfcr_importer_licensing_compliance",
        "title": "SFCR – Importer Licensing, Traceability, and Record-Keeping",
        "url": "https://inspection.canada.ca/food-licences/food-business-activities/eng/1524074697160/1524074697425",
        "description": (
            "Safe Food for Canadians Regulations guidance on importer licensing, traceability, and "
            "record-keeping obligations for commercial produce importers."
        ),
        "source": "Canadian Food Inspection Agency (CFIA)",
        "source_type": "policy",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["canada", "sfcr", "license", "traceability", "record_keeping"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "canada_tariff_finder_tool",
        "title": "Canada Tariff Finder – HS Code Duty Lookup",
        "url": "https://www.tariffinder.ca/en/",
        "description": (
            "HS-code based tariff lookup tool for determining applicable duties and preferential "
            "rates for produce imports into Canada."
        ),
        "source": "Government of Canada",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["canada", "tariff_finder", "hs_code", "duties", "preferential_rates"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "canada_free_trade_agreements_produce",
        "title": "Canada Free Trade Agreements – Produce Tariff Preferences",
        "url": "https://www.international.gc.ca/trade-commerce/trade-agreements-accords-commerciaux/index.aspx",
        "description": (
            "Canada trade agreements portal covering CUSMA/USMCA, CPTPP, and CETA to evaluate "
            "preferential tariff eligibility for produce imports and exports."
        ),
        "source": "Global Affairs Canada",
        "source_type": "policy",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["canada", "trade_agreements", "cusma", "cptpp", "ceta", "tariff_preferences"],
        "region_ids": ["north_america", "south_america", "european_union", "southeast_asia"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "canada_produce_ports_logistics",
        "title": "Canada Produce Logistics Hubs – Vancouver, Montreal, Toronto",
        "url": "https://www.portvancouver.com",
        "description": (
            "Logistics reference for major Canadian produce gateways and inland distribution hubs, "
            "with emphasis on reefer handling and cold-chain throughput."
        ),
        "source": "Port of Vancouver",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["canada", "vancouver", "montreal", "toronto", "cold_chain", "reefer"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "canada_customs_clearance_broker_workflow",
        "title": "Canada Customs Clearance Workflow for Produce Importers",
        "url": "https://www.cbsa-asfc.gc.ca/import/guide-eng.html",
        "description": (
            "Operational workflow for customs broker coordination, documentation submission, "
            "duty payment, and release sequencing for produce consignments entering Canada."
        ),
        "source": "Canada Border Services Agency (CBSA)",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["canada", "customs_broker", "clearance", "duty_payment", "produce_import"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cfia_labeling_bilingual_requirements",
        "title": "CFIA Labeling Requirements – Bilingual and Product Disclosures",
        "url": "https://inspection.canada.ca/food-labels/labelling/eng/1383607266489/1383607344939",
        "description": (
            "Canadian labeling requirements for food products, including bilingual obligations "
            "and mandatory product declarations relevant to produce imports."
        ),
        "source": "Canadian Food Inspection Agency (CFIA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["canada", "cfia", "labeling", "bilingual", "compliance"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    # ── Cross-region / system resources ──────────────────────────────────────

    {
        "_key": "usda_terminal_market_reports",
        "title": "USDA Specialty Crops Terminal Markets Standard Reports",
        "url": "https://www.ams.usda.gov/market-news/fruit-and-vegetable-terminal-markets-standard-reports",
        "description": (
            "USDA Agricultural Marketing Service terminal market price reports for fruits and "
            "vegetables, widely used as a reference for current wholesale produce pricing."
        ),
        "source": "USDA Agricultural Marketing Service (AMS)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "usda", "terminal_markets", "wholesale", "produce"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia",
            "european_union", "gulf_cooperation_council", "nordic_market",
            "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": ["us"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "usda_ers_fruit_vegetable_prices",
        "title": "USDA ERS Fruit and Vegetable Prices",
        "url": "https://www.ers.usda.gov/data-products/fruit-and-vegetable-prices",
        "description": (
            "USDA Economic Research Service data product with historical and current fruit "
            "and vegetable price series for market analysis and benchmarking."
        ),
        "source": "USDA Economic Research Service (ERS)",
        "source_type": "product_doc",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "usda", "ers", "price_series", "market_analysis"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia",
            "european_union", "gulf_cooperation_council", "nordic_market",
            "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": ["us"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "produceiq_price_index",
        "title": "ProduceIQ Fresh Produce Price Index",
        "url": "https://www.produceiq.com/index",
        "description": (
            "Commodity-level produce price index and movement trends derived from USDA-linked "
            "market data, useful for rapid price intelligence."
        ),
        "source": "ProduceIQ",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "produceiq", "price_index", "commodities", "market_trends"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia",
            "european_union", "gulf_cooperation_council", "nordic_market",
            "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "freshfruitportal_usda_prices",
        "title": "FreshFruitPortal USDA Prices and Market Updates",
        "url": "https://www.freshfruitportal.com/usda-prices/",
        "description": (
            "Daily produce pricing snapshots and commentary based on USDA market data, "
            "covering major fruit and vegetable categories."
        ),
        "source": "FreshFruitPortal",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "freshfruitportal", "usda_prices", "daily_updates", "produce"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia",
            "european_union", "gulf_cooperation_council", "nordic_market",
            "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "park_slope_food_coop_prices",
        "title": "Park Slope Food Coop Produce Price List",
        "url": "https://www.foodcoop.com/produce/",
        "description": (
            "Local cooperative produce price list with product origin references, useful as a "
            "retail-facing benchmark for spot checks and category comparisons."
        ),
        "source": "Park Slope Food Coop",
        "source_type": "directory",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "food_coop", "retail_benchmark", "local_market", "produce"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia",
            "european_union", "gulf_cooperation_council", "nordic_market",
            "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": ["us"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "usfoods_farmers_report",
        "title": "US Foods Farmer's Report – Weekly Produce Price Trends",
        "url": "https://www.usfoods.com/our-services/business-trends/farmers-report.html",
        "description": (
            "Weekly produce market trend and price direction report used by foodservice operators "
            "to anticipate short-term supply and cost shifts."
        ),
        "source": "US Foods",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "usfoods", "farmers_report", "weekly_trends", "foodservice"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia",
            "european_union", "gulf_cooperation_council", "nordic_market",
            "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": ["us"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_agrifood_data_portal_prices",
        "title": "European Commission Agri-food Data Portal – Produce Prices",
        "url": "https://agridata.ec.europa.eu/extensions/DataPortal/prices.html",
        "description": (
            "Official EU weekly agri-food and produce pricing data across member states, "
            "including downloadable datasets for historical and comparative analysis."
        ),
        "source": "European Commission",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "eu", "agri_food_data", "weekly_prices", "produce"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": ["eu"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "uk_wholesale_fruit_veg_prices",
        "title": "UK Weekly Wholesale Fruit and Vegetable Prices",
        "url": "https://www.gov.uk/government/statistical-data-sets/wholesale-fruit-and-vegetable-prices-weekly-average",
        "description": (
            "UK government weekly average wholesale horticulture prices for England and Wales, "
            "used for produce market benchmarking."
        ),
        "source": "UK Government",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "uk", "wholesale", "fruit", "vegetables", "weekly"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": ["gb"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "fresh_market_europe_prices",
        "title": "Fresh-Market.info European Wholesale Produce Prices",
        "url": "https://www.fresh-market.info/",
        "description": (
            "Wholesale produce price updates and market intelligence focused on Poland "
            "and other European countries."
        ),
        "source": "Fresh-Market.info",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "europe", "fresh_market", "wholesale", "market_updates"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": ["pl"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "soil_association_uk_organic_prices",
        "title": "Soil Association UK Organic Horticulture Price Data",
        "url": "https://www.soilassociation.org/farmers-growers/market-information/price-data/horticultural-produce-price-data/",
        "description": (
            "Current price data for UK organic horticultural produce, including fruit and vegetables "
            "for organic-channel pricing reference."
        ),
        "source": "Soil Association",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "uk", "organic", "soil_association", "horticulture"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": ["gb"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "doha_central_market_pricing_reference",
        "title": "Doha Central Market Produce Pricing Reference",
        "url": "https://www.visitqatar.com/en-en/plan-your-trip/markets/doha-central-market",
        "description": (
            "Qatar wholesale market reference for fruit and vegetable pricing signals used by "
            "regional buyers and distributors."
        ),
        "source": "Qatar Market References",
        "source_type": "directory",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "qatar", "doha_central_market", "wholesale", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "al_mazrouah_market_pricing_reference",
        "title": "Al Mazrouah Farmers Market Pricing Reference (UAE)",
        "url": "https://www.visitdubai.com/en/places-to-visit/farmers-markets",
        "description": (
            "UAE market reference for fresh produce pricing and local supply conditions in "
            "seasonal wholesale and semi-wholesale channels."
        ),
        "source": "UAE Market References",
        "source_type": "directory",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "uae", "al_mazrouah", "farmers_market", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "al_shamal_market_pricing_reference",
        "title": "Al Shamal Market Pricing Reference (Qatar)",
        "url": "https://www.iloveqatar.net/guide/living/farmers-markets-in-qatar",
        "description": (
            "Qatar produce market reference used for local price discovery in fresh fruit and "
            "vegetable trade channels."
        ),
        "source": "Qatar Market References",
        "source_type": "directory",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "qatar", "al_shamal", "market_prices", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "usda_fas_mena_produce_reports",
        "title": "USDA FAS MENA Produce Market and Price Reports",
        "url": "https://www.fas.usda.gov/data?regions=mena",
        "description": (
            "USDA Foreign Agricultural Service reports covering wholesale and retail produce "
            "market dynamics in Middle East and North Africa."
        ),
        "source": "USDA Foreign Agricultural Service (FAS)",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "usda_fas", "mena", "market_reports", "gcc"],
        "region_ids": ["gulf_cooperation_council", "africa"],
        "country_codes": ["sa", "ae", "qa", "eg", "ma"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "mordor_gcc_produce_market_analysis",
        "title": "GCC Fruit and Vegetable Market Analysis (Mordor Intelligence)",
        "url": "https://www.mordorintelligence.com/industry-reports/gcc-fruits-and-vegetables-market",
        "description": (
            "Market analysis source for GCC produce pricing trends, supply dynamics, and "
            "forecast outlooks."
        ),
        "source": "Mordor Intelligence",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "gcc", "market_analysis", "forecast", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "qa", "kw", "om", "bh"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "tridge_middle_east_produce_prices",
        "title": "Tridge Middle East Produce Price Intelligence",
        "url": "https://www.tridge.com",
        "description": (
            "Trade platform providing produce price signals, buyer/seller network data, "
            "and market intelligence across Middle East channels."
        ),
        "source": "Tridge",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "tridge", "middle_east", "trade_data", "market_intelligence"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "sydney_produce_market_prices",
        "title": "Sydney Produce Market Pricing Benchmark",
        "url": "https://www.sydneymarkets.com/markets/produce-market/product-market-overview.html",
        "description": (
            "Sydney Produce Market benchmark information used as a key Australian wholesale "
            "fresh produce price reference."
        ),
        "source": "Sydney Markets",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "australia", "sydney_markets", "wholesale", "benchmark"],
        "region_ids": ["australia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "brisbane_markets_price_report",
        "title": "Brisbane Markets Price Report",
        "url": "https://brisbanemarketspricereport.com.au/",
        "description": (
            "Dedicated Brisbane wholesale produce pricing platform with current market values "
            "and trend visibility for Australian supply chains."
        ),
        "source": "Brisbane Markets",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "australia", "brisbane", "wholesale", "price_report"],
        "region_ids": ["australia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "daff_weekly_horticulture_prices",
        "title": "Australian DAFF Weekly Horticulture Price Updates",
        "url": "https://www.agriculture.gov.au/abares/data/weekly-commodity-price-update/australian-horticulture-prices",
        "description": (
            "Australian government weekly horticulture pricing updates with charted trends "
            "for selected produce categories."
        ),
        "source": "Australian Government – DAFF/ABARES",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "australia", "daff", "abares", "weekly_update"],
        "region_ids": ["australia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "freshlogic_wholesale_price_analysis",
        "title": "Freshlogic Australian Wholesale Produce Price Analysis",
        "url": "https://freshlogic.com.au/articles/australian-fruit-and-vegetable/",
        "description": (
            "In-depth Australian wholesale produce price movement analysis and seasonal "
            "market commentary."
        ),
        "source": "Freshlogic",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "australia", "freshlogic", "analysis", "seasonality"],
        "region_ids": ["australia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "hort_innovation_wholesale_reports",
        "title": "Hort Innovation Vegetable Wholesale Market Price Reports",
        "url": "https://www.horticulture.com.au/growers/container-page/vegetable-fund/resources/vegetable-wholesale-market-price-reports/",
        "description": (
            "Historical wholesale vegetable market reporting from Hort Innovation, useful "
            "for trend baselines and comparative analysis."
        ),
        "source": "Hort Innovation",
        "source_type": "product_doc",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "australia", "hort_innovation", "historical", "vegetables"],
        "region_ids": ["australia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "tokyo_toyosu_market_prices",
        "title": "Tokyo Metropolitan Central Wholesale Market (Toyosu) Prices",
        "url": "https://www.shijou.metro.tokyo.lg.jp/english/",
        "description": (
            "Tokyo central wholesale market references with daily produce price signals "
            "for East Asia market tracking."
        ),
        "source": "Tokyo Metropolitan Government",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "japan", "toyosu", "wholesale_market", "daily_prices"],
        "region_ids": ["east_asia"],
        "country_codes": ["jp"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "korea_at_market_prices",
        "title": "Korea Agro-Fisheries and Food Trade Corp (aT) Market Prices",
        "url": "https://www.at.or.kr/home/apko000000/index.action",
        "description": (
            "South Korea agricultural market price references from aT, including produce "
            "pricing indicators and market bulletins."
        ),
        "source": "Korea Agro-Fisheries and Food Trade Corporation (aT)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "south_korea", "aT", "market_prices", "produce"],
        "region_ids": ["east_asia"],
        "country_codes": ["kr"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "india_nhb_apmc_market_prices",
        "title": "India NHB and APMC Wholesale Produce Prices",
        "url": "https://nhb.gov.in",
        "description": (
            "India horticulture and market-board pricing references for daily and periodic "
            "wholesale produce prices across major markets."
        ),
        "source": "National Horticulture Board (India)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "india", "nhb", "apmc", "wholesale"],
        "region_ids": ["east_asia", "southeast_asia"],
        "country_codes": ["in"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "china_mara_xinfadi_price_indices",
        "title": "China MARA and Xinfadi Produce Price Indices",
        "url": "http://english.moa.gov.cn",
        "description": (
            "China agriculture and major wholesale market pricing references for produce "
            "categories and trend tracking."
        ),
        "source": "Ministry of Agriculture and Rural Affairs (China)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "china", "mara", "xinfadi", "price_index"],
        "region_ids": ["east_asia"],
        "country_codes": ["cn"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "tridge_asia_produce_prices",
        "title": "Tridge Asia Produce Price Intelligence",
        "url": "https://www.tridge.com",
        "description": (
            "Trade intelligence platform for produce pricing trends, supplier signals, and "
            "cross-border market movements across Asian markets."
        ),
        "source": "Tridge",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "tridge", "asia", "market_intelligence", "produce"],
        "region_ids": ["east_asia", "southeast_asia"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "indexbox_asia_produce_prices",
        "title": "IndexBox Asia Fruit and Vegetable Price Trends",
        "url": "https://www.indexbox.io",
        "description": (
            "Market analytics and pricing trend references for fruit and vegetable sectors "
            "across Asian economies."
        ),
        "source": "IndexBox",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "indexbox", "asia", "analytics", "forecast"],
        "region_ids": ["east_asia", "southeast_asia"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "freshplaza_asia_market_updates",
        "title": "FreshPlaza Asia Produce Market Updates",
        "url": "https://www.freshplaza.com/asia/",
        "description": (
            "Asia-focused produce market updates, including pricing commentary and trade "
            "trend reporting across major sourcing and destination markets."
        ),
        "source": "FreshPlaza",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "freshplaza", "asia", "market_updates", "trade_trends"],
        "region_ids": ["east_asia", "southeast_asia"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "asia_fruit_logistica_market_insights",
        "title": "Asia Fruit Logistica Market Insights",
        "url": "https://www.asiafruitlogistica.com",
        "description": (
            "Industry event and publication insights covering produce trade and pricing "
            "signals in Asian fresh produce markets."
        ),
        "source": "Asia Fruit Logistica",
        "source_type": "market_guide",
        "visibility": "public",
        "topic": "pricing",
        "tags": ["pricing", "asia_fruit_logistica", "industry_insights", "asia", "produce"],
        "region_ids": ["east_asia", "southeast_asia"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },

    {
        "_key": "wto_sps_agreement",
        "title": "WTO Agreement on Sanitary and Phytosanitary Measures (SPS)",
        "url": "https://www.wto.org/english/tratop_e/sps_e/spsagr_e.htm",
        "description": (
            "WTO SPS Agreement establishing the framework under which countries may "
            "apply food safety and animal/plant health regulations. Relevant baseline "
            "reference for all regions supported by AgriDAO."
        ),
        "source": "World Trade Organization (WTO)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["wto", "sps", "food_safety", "phytosanitary", "multilateral"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia",
            "european_union", "gulf_cooperation_council", "nordic_market",
            "north_america", "south_america", "southeast_asia",
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "ippc_phytosanitary",
        "title": "IPPC – International Plant Protection Convention",
        "url": "https://www.ippc.int",
        "description": (
            "IPPC portal for international phytosanitary standards (ISPMs), country "
            "pest reports, and official contact points. Required reading for any "
            "cross-border fresh produce shipment across all AgriDAO markets."
        ),
        "source": "International Plant Protection Convention (IPPC) – FAO",
        "source_type": "certification",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["ippc", "phytosanitary", "ispm", "plant_health", "multilateral"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia",
            "european_union", "gulf_cooperation_council", "nordic_market",
            "north_america", "south_america", "southeast_asia",
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "global_produce_shipping_methods",
        "title": "Produce Shipping Modes Guide – Air, Sea, and Land",
        "url": "https://producepay.com",
        "description": (
            "Operational guide comparing air freight, sea freight, and land transport for "
            "fresh produce by perishability profile, volume, transit time, and cost."
        ),
        "source": "ProducePay",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["air_freight", "sea_freight", "land_transport", "perishables", "transit_time"],
        "region_ids": [
            "south_america", "central_america", "north_america", "european_union",
            "nordic_market", "gulf_cooperation_council", "southeast_asia", "east_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "global_packaging_labeling_requirements",
        "title": "Produce Packaging and Labeling Baseline Requirements",
        "url": "https://www.agriculture.gov.au",
        "description": (
            "Baseline packaging and labeling checklist for produce shipments, including product "
            "identity, origin, net weight, exporter/importer details, and certification disclosures."
        ),
        "source": "Australian Government – DAFF",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["packaging", "labeling", "origin", "net_weight", "globalgap", "fairtrade"],
        "region_ids": [
            "south_america", "central_america", "north_america", "european_union",
            "nordic_market", "gulf_cooperation_council", "southeast_asia", "east_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "produce_export_documentation_checklist",
        "title": "Produce Export Documentation Checklist",
        "url": "https://www.agriculture.gov.au",
        "description": (
            "Shipment documentation reference covering commercial invoice, packing list, bill of lading, "
            "phytosanitary certificate, certificate of origin, and import permit dependencies."
        ),
        "source": "Australian Government – DAFF",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["commercial_invoice", "packing_list", "bill_of_lading", "phytosanitary", "certificate_of_origin"],
        "region_ids": [
            "south_america", "central_america", "north_america", "european_union",
            "nordic_market", "gulf_cooperation_council", "southeast_asia", "east_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cold_chain_handling_playbook",
        "title": "Fresh Produce Cold Chain and Handling Playbook",
        "url": "https://wellpack.org",
        "description": (
            "Cold-chain and handling playbook for reefer sea containers, refrigerated trucking, "
            "airport handling, and spoilage-risk controls for perishable produce."
        ),
        "source": "Well Pack",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["cold_chain", "reefer", "refrigerated_trucks", "airport_cargo", "spoilage_prevention"],
        "region_ids": [
            "south_america", "central_america", "north_america", "european_union",
            "nordic_market", "gulf_cooperation_council", "southeast_asia", "east_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "global_produce_hubs_reference",
        "title": "Major Produce Port and Airport Hubs by Region",
        "url": "https://nrtcgroup.com",
        "description": (
            "Reference list of key logistics hubs used for produce flows, including Santos, Manzanillo, "
            "Callao, Los Angeles, Vancouver, Rotterdam, Algeciras, Jebel Ali, Melbourne, and Auckland."
        ),
        "source": "NRTC Group",
        "source_type": "logistics_hub",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["ports", "airports", "logistics_hubs", "regional_routing", "produce_trade"],
        "region_ids": [
            "south_america", "central_america", "north_america", "european_union",
            "nordic_market", "gulf_cooperation_council", "southeast_asia", "east_asia"
        ],
        "country_codes": ["br", "mx", "pe", "us", "ca", "nl", "es", "ae", "au", "nz"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "customs_biosecurity_prearrival_checks",
        "title": "Customs and Biosecurity Pre-Arrival Inspection Requirements",
        "url": "https://www.agriculture.gov.au",
        "description": (
            "Pre-arrival and inspection readiness guide for produce shipments into strict-control "
            "markets, with emphasis on biosecurity clearance risk reduction."
        ),
        "source": "Australian Government – DAFF",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["pre_arrival", "biosecurity", "inspection", "customs_clearance", "risk_reduction"],
        "region_ids": ["north_america", "european_union", "nordic_market", "southeast_asia", "gulf_cooperation_council"],
        "country_codes": ["au", "ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "bicon_import_conditions_tool",
        "title": "Australia BICON – Biosecurity Import Conditions Tool",
        "url": "https://bicon.agriculture.gov.au/BiconWeb4.0",
        "description": (
            "Official lookup for Australian produce admissibility, import conditions, required treatments, "
            "and permit triggers before shipment."
        ),
        "source": "Australian Government – DAFF",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["bicon", "australia", "import_conditions", "biosecurity", "permits"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cfia_airs_import_tool",
        "title": "Canada CFIA AIRS – Produce Import Admissibility Tool",
        "url": "https://inspection.canada.ca/importing-food-plants-or-animals/plant-and-plant-product-imports/airs/eng/1326512904269/1326513001478",
        "description": (
            "Official AIRS reference for Canada import admissibility, documentation, and compliance steps "
            "for plant and produce consignments."
        ),
        "source": "Canadian Food Inspection Agency (CFIA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["cfia", "airs", "canada", "admissibility", "produce_import"],
        "region_ids": ["north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_access2markets_produce",
        "title": "EU Access2Markets – Produce Import and Tariff Requirements",
        "url": "https://trade.ec.europa.eu/access-to-markets/en/home",
        "description": (
            "EU trade helpdesk replacement portal to check tariffs, customs procedures, rules of origin, "
            "and documentation requirements for produce entering the EU."
        ),
        "source": "European Commission",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["eu", "access2markets", "tariffs", "rules_of_origin", "import_procedures"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "shipment_preflight_compliance_checklist",
        "title": "Shipment Preflight Checklist for Fresh Produce",
        "url": "https://latinamericasourcing.com",
        "description": (
            "Pre-shipment checklist for exporters to validate routing, partner readiness, labeling, "
            "documentation completeness, and destination-specific compliance constraints."
        ),
        "source": "Latin America Sourcing",
        "source_type": "faq",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["shipment_preflight", "compliance", "labeling", "documents", "freight_forwarder"],
        "region_ids": [
            "south_america", "central_america", "north_america", "european_union",
            "nordic_market", "gulf_cooperation_council", "southeast_asia", "east_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "hs_code_classification_runbook",
        "title": "HS Code Classification Runbook for Fresh Produce",
        "url": "https://www.wcoomd.org",
        "description": (
            "Step-by-step workflow to classify produce using HS chapters 7 and 8, verify local tariff-line "
            "extensions, and apply codes in invoices, packing lists, and customs declarations."
        ),
        "source": "World Customs Organization (WCO)",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["hs_code", "classification", "chapter_7", "chapter_8", "customs_declaration"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "hs_code_reference_fruits_vegetables",
        "title": "Fresh Produce HS Code Reference (Global Baseline)",
        "url": "https://www.wcoomd.org/en/topics/nomenclature/overview/what-is-the-harmonized-system.aspx",
        "description": (
            "Common baseline codes for search and planning: apples 0808.10, bananas 0803.00, oranges 0805.10, "
            "grapes 0806.10, avocados 0804.40, mangoes 0804.50, strawberries 0810.10, tomatoes 0702.00, "
            "lemons/limes 0805.50, potatoes 0701.90, onions 0703.10, carrots 0706.10, lettuce 0705.11, "
            "cucumbers 0707.00, peppers 0709.60, garlic 0703.20."
        ),
        "source": "World Customs Organization (WCO)",
        "source_type": "product_doc",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["hs_code", "fruits", "vegetables", "tariff_classification", "reference_table"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "wco_hs_search_tool",
        "title": "WCO HS Search and Nomenclature Guidance",
        "url": "https://www.wcoomd.org",
        "description": (
            "Global harmonized system resource for nomenclature structure, updates, and classification references "
            "used by customs authorities."
        ),
        "source": "World Customs Organization (WCO)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["wco", "hs_search", "nomenclature", "classification", "customs"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "usitc_hs_reference_tool",
        "title": "USITC HTS Search Tool (Reference)",
        "url": "https://hts.usitc.gov",
        "description": (
            "Searchable tariff schedule useful as a reference point for product classification and "
            "cross-checking produce code selection."
        ),
        "source": "U.S. International Trade Commission (USITC)",
        "source_type": "trade_portal",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["usitc", "hts", "hs_code", "classification", "reference"],
        "region_ids": ["north_america", "south_america", "central_america"],
        "country_codes": ["us", "ca", "mx"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "uae_hs_tariff_search",
        "title": "UAE HS Tariff Search and Code Extension Guide",
        "url": "https://www.fca.gov.ae/en-us/Pages/CustomsTariff.aspx",
        "description": (
            "UAE customs tariff lookup for local HS extensions (additional digits), duty rates, and "
            "produce import code verification."
        ),
        "source": "UAE Federal Customs Authority",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["uae", "hs_code", "tariff_search", "customs", "duty_rate"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "saudi_hs_tariff_search",
        "title": "Saudi ZATCA Tariff Search for Produce HS Codes",
        "url": "https://zatca.gov.sa/en/RulesRegulations/Taxes/Pages/Customs-Tariff.aspx",
        "description": (
            "Saudi tariff lookup reference for HS classification, duty rates, and code validation "
            "before filing through customs systems."
        ),
        "source": "Zakat, Tax and Customs Authority (ZATCA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["saudi_arabia", "hs_code", "zatca", "tariff", "classification"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["sa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "qatar_hs_tariff_search",
        "title": "Qatar Customs Tariff Search for Fresh Produce",
        "url": "https://www.customs.gov.qa/english/pages/default.aspx",
        "description": (
            "Qatar customs tariff tools for HS code lookup, duty determination, and produce import "
            "classification checks."
        ),
        "source": "Qatar Customs",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["qatar", "hs_code", "customs_tariff", "duty", "produce"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eu_taric_hs_classification",
        "title": "EU TARIC HS Classification and Duty Lookup",
        "url": "https://taxation-customs.ec.europa.eu/customs-4/calculation-customs-duties/customs-tariff/eu-customs-tariff-taric_en",
        "description": (
            "Official EU tariff and classification system for validating HS/TARIC codes, customs measures, "
            "and produce duty treatment."
        ),
        "source": "European Commission – Taxation and Customs Union",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["eu", "taric", "hs_code", "classification", "duty_lookup"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "australia_customs_tariff_hs",
        "title": "Australia Customs Tariff HS Classification",
        "url": "https://www.abf.gov.au/importing-exporting-and-manufacturing/tariff-classification",
        "description": (
            "Australian tariff-classification resources for determining produce HS lines, "
            "duty treatment, and declaration accuracy."
        ),
        "source": "Australian Border Force",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["australia", "hs_code", "tariff_classification", "abf", "declarations"],
        "region_ids": ["southeast_asia"],
        "country_codes": ["au"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "hs_code_verification_checklist",
        "title": "HS Code Verification Checklist (Approved Before Filing)",
        "url": "https://www.intracen.org",
        "description": (
            "Pre-filing verification checklist: validate commodity description, confirm destination-country tariff line, "
            "cross-check supporting certificates, and get broker approval to reduce misclassification risk."
        ),
        "source": "International Trade Centre (ITC)",
        "source_type": "faq",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["hs_code", "verification", "broker_approval", "misclassification", "compliance"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "hs_code_country_examples_gcc",
        "title": "HS Code Country Examples for UAE, Saudi Arabia, and Qatar",
        "url": "https://www.dubaitrade.ae",
        "description": (
            "Applied examples for produce classification in GCC markets: strawberries 0810.10, oranges 0805.10, "
            "tomatoes 0702.00, and use of local code extensions for customs filing."
        ),
        "source": "Dubai Trade / ZATCA / Qatar Customs",
        "source_type": "product_doc",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["hs_code", "gcc", "uae", "saudi_arabia", "qatar", "examples"],
        "region_ids": ["gulf_cooperation_council"],
        "country_codes": ["ae", "sa", "qa"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "eori_eu_trade_identifier",
        "title": "EORI Number – EU Economic Operator Registration",
        "url": "https://taxation-customs.ec.europa.eu/customs/customs-security/import-and-export-rules/economic-operators-registration-and-identification-eori-number_en",
        "description": (
            "EU importer/exporter identifier required for customs interactions involving EU markets. "
            "Use before filing declarations or customs security submissions."
        ),
        "source": "European Commission – Customs",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["eori", "eu", "customs_identifier", "import_export", "registration"],
        "region_ids": ["european_union", "nordic_market"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "duns_business_verification",
        "title": "D-U-N-S Number – Global Business Verification",
        "url": "https://www.dnb.com/duns-number.html",
        "description": (
            "Global 9-digit business identifier used for credit checks and supply-chain onboarding, "
            "especially for institutional buyers and large retailers."
        ),
        "source": "Dun and Bradstreet",
        "source_type": "product_doc",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["duns", "business_verification", "supply_chain", "retail_onboarding", "credit"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "phytosanitary_certificate_reference_codes",
        "title": "Phytosanitary Certificate Reference and Validation",
        "url": "https://www.ippc.int/en/ephyto/",
        "description": (
            "Reference for phytosanitary certificate issuance and validation practices, including "
            "shipment-linked certificate numbers and NPPO responsibilities."
        ),
        "source": "International Plant Protection Convention (IPPC)",
        "source_type": "certification",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["phytosanitary", "certificate", "nppo", "ephyto", "plant_health"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "certificate_of_origin_formats",
        "title": "Certificate of Origin Formats – Form A, EUR.1, and FTA Claims",
        "url": "https://iccwbo.org/business-solutions/trade-facilitation/rules-of-origin/",
        "description": (
            "Guidance on COO formats used for preferential tariff claims under trade agreements, "
            "including common documentary patterns across destinations."
        ),
        "source": "International Chamber of Commerce (ICC)",
        "source_type": "product_doc",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["certificate_of_origin", "form_a", "eur1", "fta", "preferential_tariff"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "globalgap_ggn_certification",
        "title": "GlobalG.A.P. Certification and GGN Verification",
        "url": "https://www.globalgap.org",
        "description": (
            "Good agricultural practice certification framework and GlobalG.A.P. Number (GGN) "
            "verification references for produce supply chains."
        ),
        "source": "GlobalG.A.P.",
        "source_type": "certification",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["globalgap", "ggn", "certification", "food_safety", "sustainability"],
        "region_ids": ["european_union", "nordic_market", "gulf_cooperation_council", "north_america", "southeast_asia"],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "fairtrade_license_code_reference",
        "title": "Fairtrade Certification and License Code Guidance",
        "url": "https://www.fairtrade.net",
        "description": (
            "Fairtrade compliance and labeling references for ethically sourced produce, "
            "including license code usage in commercial channels."
        ),
        "source": "Fairtrade International",
        "source_type": "certification",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["fairtrade", "license_code", "ethical_sourcing", "certification", "produce"],
        "region_ids": ["european_union", "nordic_market", "north_america"],
        "country_codes": ["ca"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "organic_certification_codes_global",
        "title": "Organic Certification Codes – USDA, EU Organic, JAS",
        "url": "https://www.ifoam.bio",
        "description": (
            "Cross-market reference for organic certification systems and identifier usage for "
            "produce sold as organic in major destination markets."
        ),
        "source": "IFOAM Organics International",
        "source_type": "certification",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["organic", "usda_organic", "eu_organic", "jas", "certification_code"],
        "region_ids": ["european_union", "north_america", "east_asia", "southeast_asia"],
        "country_codes": ["us", "jp"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "gs1_gtin_upc_ean_barcodes",
        "title": "GS1 GTIN/UPC/EAN Barcode Assignment for Produce",
        "url": "https://www.gs1.org/standards/id-keys/gtin",
        "description": (
            "Retail barcode assignment guidance for produce packaging and inventory traceability, "
            "including GTIN, UPC, and EAN structures."
        ),
        "source": "GS1",
        "source_type": "product_doc",
        "visibility": "public",
        "topic": "marketplace-listing",
        "tags": ["gs1", "gtin", "upc", "ean", "barcodes", "retail"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "incoterms_2020_reference",
        "title": "Incoterms 2020 – FOB, CIF, DAP for Produce Trade",
        "url": "https://iccwbo.org/business-solutions/incoterms-rules/",
        "description": (
            "International Commercial Terms reference for contract responsibilities, risk transfer, "
            "and logistics cost allocation in produce shipments."
        ),
        "source": "International Chamber of Commerce (ICC)",
        "source_type": "runbook",
        "visibility": "public",
        "topic": "shipping-logistics",
        "tags": ["incoterms", "fob", "cif", "dap", "contracts", "risk_transfer"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "ata_carnet_temporary_imports",
        "title": "ATA Carnet – Temporary Duty-Free Import for Trade Samples",
        "url": "https://iccwbo.org/business-solutions/trade-facilitation/ata-carnet/",
        "description": (
            "Carnet framework for temporary import of goods such as produce samples for exhibitions, "
            "demonstrations, or buyer events."
        ),
        "source": "International Chamber of Commerce (ICC)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["ata_carnet", "temporary_import", "trade_samples", "trade_fair", "duty_free"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "cites_permit_exotic_plants",
        "title": "CITES Permit Guidance for Endangered Plant Species",
        "url": "https://cites.org",
        "description": (
            "Permit requirements for trade in endangered plant species; generally rare for mainstream "
            "produce but critical for exotic or protected varieties."
        ),
        "source": "CITES Secretariat",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["cites", "permit", "endangered_species", "exotic_plants", "compliance"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "fda_food_facility_registration",
        "title": "USA FDA Food Facility Registration for Exporters",
        "url": "https://www.fda.gov/food/guidance-regulation-food-and-dietary-supplements/registration-food-facilities-and-other-submissions",
        "description": (
            "Registration requirements for facilities exporting food products to the US market, "
            "including compliance prerequisites for importer acceptance."
        ),
        "source": "U.S. Food and Drug Administration (FDA)",
        "source_type": "regulation_summary",
        "visibility": "public",
        "topic": "compliance-region",
        "tags": ["usa", "fda", "facility_registration", "food_exports", "compliance"],
        "region_ids": ["north_america"],
        "country_codes": ["us"],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
    {
        "_key": "trade_code_compliance_matrix",
        "title": "Produce Trade Code Compliance Matrix",
        "url": "https://www.intracen.org",
        "description": (
            "Quick reference matrix mapping HS code, COO, phytosanitary, certifications, barcodes, and "
            "market-specific approvals by destination region."
        ),
        "source": "International Trade Centre (ITC)",
        "source_type": "product_doc",
        "visibility": "public",
        "topic": "export-documents",
        "tags": ["compliance_matrix", "hs_code", "certificate_of_origin", "phytosanitary", "certification"],
        "region_ids": [
            "africa", "caribbean", "central_america", "east_asia", "european_union",
            "gulf_cooperation_council", "north_america", "south_america", "southeast_asia"
        ],
        "country_codes": [],
        "audience": "user",
        "last_reviewed": NOW,
        "created_at": NOW,
    },
]


def normalize_region_mappings(resources: list[dict]) -> None:
    """Keep Nordic market aligned with EU-scoped support resources."""
    for resource in resources:
        region_ids = resource.get("region_ids", [])
        if "european_union" in region_ids and "nordic_market" not in region_ids:
            region_ids.append("nordic_market")
        resource["region_ids"] = list(dict.fromkeys(region_ids))


normalize_region_mappings(RESOURCES)

# ---------------------------------------------------------------------------
# 3. Seed data
# ---------------------------------------------------------------------------

print("Seeding regions …")
upsert("region", REGIONS)
print(f"[seed] processed {len(REGIONS)} regions", flush=True)

print("Seeding resources …")
upsert("resource", RESOURCES)
print(f"[seed] processed {len(RESOURCES)} resources", flush=True)

print("Building region → resource edges …")
for res in RESOURCES:
    for region_key in res.get("region_ids", []):
        upsert_edge(region_key, res["_key"])

print("[seed] done.", flush=True)
