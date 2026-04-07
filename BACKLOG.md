# AgriDAO LangChain Agent — Backlog

## ✅ Completed

### Data / Seeding
- [x] Defined 10 core regions: `africa`, `caribbean`, `central_america`, `east_asia`, `european_union`, `gulf_cooperation_council`, `nordic_market`, `north_america`, `south_america`, `southeast_asia`
- [x] Defined resource schema: `_key`, `title`, `url`, `description`, `source`, `source_type`, `visibility`, `topic`, `tags`, `region_ids`, `country_codes`, `audience`, `last_reviewed`, `created_at`
- [x] Seeded 205 trade/compliance resources across all regions into ArangoDB `resource` collection
  - Canada (9 resources)
  - Australia + Asia (14 resources)
  - Middle East / GCC baseline (21 resources)
  - Africa (20 resources)
  - UAE / Saudi Arabia / Qatar detail (11 resources)
  - HS Code taxonomy pack (11 resources)
  - Trade certification codes — EORI, DUNS, COO, GTIN, Incoterms, ATA Carnet, CITES, FDA registration, compliance matrix (13 resources)
- [x] Built region → resource edge collection
- [x] Added `normalize_region_mappings()` — automatically adds `nordic_market` to any `european_union` resource
- [x] Confirmed AQL `RETURN LENGTH(resource)` = 205

### Resource Access Control
- [x] Defined two-tier visibility model: `public` (anonymous) and `system` (verified trusted accounts)
- [x] All 205 seeded resources set to `visibility: "public"`
- [x] Documented visibility model and retrieval rules in CLAUDE.md Phase 1

### Retrieval Layer (`app/services/resource_search.py`)
- [x] Created tiered keyword search service against ArangoDB
- [x] Defined three search tiers:
  - `broad` — all sources, no restriction (limit 10)
  - `compliance` — `regulation_summary`, `policy`, `certification`, `product_doc`; topics: `export-documents`, `compliance-region` (limit 8)
  - `fulfillment` — `logistics_hub`, `trade_portal`, `runbook`, `market_guide`, `trade_fair`; topics: `shipping-logistics`, `marketplace-listing` (limit 8)
- [x] Keyword extraction with stopword stripping (LIKE-based AQL filter on title, description, tags)
- [x] Optional `region_id` scoping per query
- [x] Visibility enforcement: `trusted=False` → only `public` resources; `trusted=True` → all resources
- [x] `format_resources_as_context()` — formats matched resources into LLM prompt context block

### RAG Chain (`app/chains/rag.py`)
- [x] Wired ArangoDB resource retrieval into Ollama prompt
- [x] Injected matched resources as grounding context before LLM call
- [x] Response now returns `sources` list (title, url, source_type) alongside answer
- [x] `tier`, `region_id`, and `trusted` threaded through chain
- [x] Added deterministic degraded fallback payload when Ollama is unavailable
- [x] Added explicit contract fields on responses: `status`, `verified`, `verification_status`, `llm_available`, `should_retry`, `error`
- [x] Reduced Ollama timeout pressure with faster fail behavior to avoid long worker blocking

### API (`app/main.py`)
- [x] `POST /rag/query` upgraded to typed `RagRequest` Pydantic model
- [x] Exposes `query`, `tier`, `region_id`, `trusted`, `force_escalate`, `session_id` as request fields
- [x] `GET /session/{session_id}` endpoint returns full conversation history
- [x] Removed dead Oracle service file and references
- [x] `/health` now exposes LangSmith tracing status

### Observability (LangSmith)
- [x] Enabled LangSmith tracing env wiring in compose (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`)
- [x] Added startup validation for LangSmith client initialization
- [x] Added trace instrumentation for RAG chain and LangGraph workflow runs

### Node API (`node-api/index.js`)
- [x] Added upstream RAG timeout handling (`RAG_TIMEOUT_MS`) and non-2xx fallback handling
- [x] Added normalized fallback payload with unverified/degraded status fields
- [x] Added response normalization so success and fallback share one contract

### Jira Mock Escalation (`app/services/jira_mock_couch.py`, `app/workers/jira_worker.py`)
- [x] Added synchronous mock issue creation endpoint (`POST /jira/mock`)
- [x] Added async enqueue endpoint (`POST /jira/enqueue`) returning `job_id`
- [x] Added job status endpoint (`GET /jira/job/{job_id}`)
- [x] Implemented CouchDB job queue document model (`jira_issue_job`)
- [x] Implemented background worker loop (`jira-worker`) to process pending jobs
- [x] Added retry and failure states for worker processing (`pending`, `processing`, `created`, `failed`)

### Conversation Checkpointing (`app/checkpointer/arango_cp.py`)
- [x] Replaced empty `oracle_cp.py` with ArangoDB-backed checkpointer
- [x] `session` collection auto-created on first write (lazy bootstrap, no init script dependency)
- [x] `save_turn()` — appends turn to existing session or creates new session document
- [x] `load_session()` — fetches session by `session_id`; returns None on miss or error
- [x] `is_duplicate_turn()` — detects network-retry: same query as last turn returns cached answer without re-calling LLM
- [x] Session TTL configurable via `SESSION_TTL_HOURS` env var (default 24h)
- [x] Checkpoint failure is non-fatal — RAG response is returned even if ArangoDB write fails
- [x] Every response now includes `session_id` and `resumed` flag
- [x] Client resumes session by passing `session_id` in next `POST /rag/query` request

### LangGraph Workflow Checkpointing (`app/checkpointer/langgraph_arango.py`)
- [x] Implemented `ArangoCheckpointer` extending LangGraph `BaseCheckpointSaver`
- [x] Writes/reads native JSON checkpoints to `langgraph_checkpoints` collection
- [x] Implemented generate -> Pydantic validate -> loop/advance validation graph (`app/graph/validation_loop.py`)
- [x] Added FastAPI run/resume endpoints by `thread_id` (`POST /workflow/run/{thread_id}`, `POST /workflow/resume/{thread_id}`)

---

## 🔲 Up Next — Phase 1 Completion

- [x] Define supported issue categories (public user scope)
  - `marketplace`: listing, discovery, product posting, buyer/seller workflow
  - `export`: shipping docs, customs workflow, port/trade process
  - `payment`: invoicing, payout timing, settlement process (non-wallet)
  - `compliance`: certification, regulatory checks, country/region policy guidance
  - `pricing`: produce pricing references, market price context, trend interpretation
- [x] Define out-of-scope rejection list and rejection response format
  - Out-of-scope (login-required/system-only): `wallet`, `DAO membership`, `Solana/node issues`, governance admin actions, internal credentials/access requests
  - Out-of-scope response contract:
    - `status: "out_of_scope"`
    - `verified: false`
    - `verification_status: "unverified"`
    - `escalate: true`
    - `escalation_reason: "requires_login_or_authenticated_internal_support"`
    - `user_can_escalate: true`
    - `allowed_categories: ["marketplace", "export", "payment", "compliance", "pricing"]`
    - `next_step: "route_to_human_support"`
- [x] Define Human-in-the-Loop (HITL) gate for public user scenario
  - UI must require category selection from allowed public categories before submit
  - UI must allow optional region filter to constrain retrieval scope
  - System routes to human support when request is out-of-scope, low-confidence, or degraded fallback
  - No autonomous actions for out-of-scope requests; they require login/authenticated internal support flow
- [x] Define what counts as a satisfactory answer (criteria for no-escalation)
  - Implemented in `app/services/confidence.py` — `score_answer(query, answer, resources) → {confidence, label, escalate, escalation_reason}`
  - Three signals: retrieval coverage (40%), source quality rank (35%), model hedge-phrase penalty (25%)
  - Thresholds: `>= 0.70` satisfactory · `0.40–0.69` borderline · `< 0.40` auto-escalate
  - Hard overrides: zero resources returned · LLM failure · high-severity query keyword (sanctions, fraud, dispute, etc.)
  - `escalate: true` in the API response triggers Jira ticket creation (Phase 7)
- [x] Define Jira ticket required fields: summary, description, priority, reporter, component, labels
  - Standardized in mock Jira payload (`POST /jira/mock`)
  - Backed by CouchDB document write in `app/services/jira_mock_couch.py`
  - Additional tracked fields: `category`, `region_id`, `session_id`, `escalation_reason`, `ticket_key`, `status`, timestamps
- [ ] Decide user identity model: anonymous vs authenticated vs internal-only at MVP

---



### Phase 6 — LLM Integration Started
- [ ] Support-answer chain separate from generic generation
- [ ] Consistent response format for UI
- [ ] Log model failures and latency
- [x] Safe fallback when Ollama is unavailable
- [ ] Isolate Ollama runtime behavior (ReadTimeout) outside RAG: run direct Ollama benchmark with tiny prompts, single-worker mode, and no retrieval context to determine root cause (model runtime vs host resource contention vs transport timeout)


### Phase 2 — UX & Application Flow
- [ ] Simple web UI with support-only prompt box
- [ ] Issue category selector to improve routing
- [ ] Show answer, confidence score, and source citations
- [ ] Wire UI to LangGraph workflow endpoints (`POST /workflow/run/{thread_id}`, `POST /workflow/resume/{thread_id}`) with persisted `thread_id`
- [ ] "Create Jira ticket" action when answer is insufficient
- [ ] User confirmation step before ticket submission
- [ ] Display ticket key and next steps post-escalation


### Phase 9 — Data Model & Persistence
- [ ] Decide what interactions to store
- [ ] Store question, answer, confidence, escalation decision, ticket key (Check if question was prompt within past 24 hrs before fetching content to arangoDB)
- [ ] Store user feedback on whether answer solved the issue

## 🔲 Upcoming Phases (started)



### Phase 3 — Backend API Design
- [ ] Auth gate: only verified trusted accounts can set `trusted=True` on `/rag/query`
- [ ] Endpoint for retrieving suggested answer + confidence score
- [ ] Endpoint for Jira escalation
- [ ] Endpoint for ticket status check
- [ ] Request/response schema validation (Pydantic)
- [ ] Structured error handling for LLM, retrieval, and Jira failures

### Phase 4 — Prompt Guardrails
- [ ] System prompt restricting assistant to platform support topics
- [ ] Out-of-scope rejection / redirect behavior
- [ ] Prevent model from inventing policies or unsupported steps
- [ ] Explicit escalation instruction when confidence is low
- [ ] Prompt tests for in-scope and out-of-scope requests

### Phase 5 — Knowledge & Retrieval
- [ ] Index internal product support docs (onboarding, wallet, DAO, marketplace, export)
- [ ] Index admin runbooks and support FAQs
- [ ] Index resolved Jira tickets by issue category
- [ ] Add vector/semantic search alongside current keyword search
- [ ] Add confidence heuristic based on retrieval quality
- [ ] Fallback when no relevant context is found
- [ ] Add `system`-visibility resources for internal runbooks and escalation playbooks


### Phase 7 — Jira Integration
- [ ] Choose Jira Cloud vs Server target
- [ ] Auth method: API token, OAuth, or service account
- [ ] Implement Jira client wrapper in service layer
- [ ] Map support issue fields to Jira issue payloads
- [ ] Return ticket key, URL, and creation result to UI
- [ ] Handle duplicate/repeated ticket submissions safely

### Phase 8 — Escalation Logic
- [ ] Low-confidence threshold triggers
- [ ] Escalate when retrieval returns weak or no evidence
- [ ] Escalate when user confirms answer did not help
- [ ] Auto-escalate high-severity categories
- [ ] Summary generator for Jira ticket descriptions
- [ ] Include user prompt, attempted answer, and context in ticket body



---

## Technical Reference

| Item | Value |
|---|---|
| ArangoDB URL | `http://10.0.0.1:8529` |
| Database | `agri_dao` |
| Collections | `resource`, `region`, region→resource edges |
| Resource count | 205 |
| Python venv | `/Users/ericferrier/Documents/GitHub/agri-dao-app/.venv/bin/python` |
| Seed script | `db/init/02_resources.py` |
| LLM | Ollama / Mistral (via `OLLAMA_URL`) |
| Search tiers | `broad` → `compliance` → `fulfillment` |
| Visibility values | `public`, `system` |
