# LangChain-docker

## TODO:
Creating a Hugging Face account

ARANGO_URL=http://10.0.0.1:8529 ARANGO_USER=system ARANGO_ROOT_PASSWORD=oDfRxtaGnzr20 ARANGO_DB=agri_dao \
  /Users/ericferrier/Documents/GitHub/agri-dao-app/.venv/bin/python -u db/init/01_init.py && \
  ARANGO_URL=http://10.0.0.1:8529 ARANGO_USER=system ARANGO_ROOT_PASSWORD=oDfRxtaGnzr20 ARANGO_DB=agri_dao \
  /Users/ericferrier/Documents/GitHub/agri-dao-app/.venv/bin/python -u db/init/02_resources.py


## 1. Install & 
```bash
brew install ollama
ollama pull mistral

> Keep `ollama serve` running in a separate terminal tab.
ollama serve
```

## Start Ollama
> Keep `ollama serve` running in a separate terminal tab.
```bash
ollama serve
```

## Start stack
 Start app/workers stack:
cd /Users/ericferrier/Documents/GitHub/agri-dao-app/agent-langChain
docker compose up -d --build

Start node stack:
cd /Users/ericferrier/Documents/GitHub/agri-dao-app/node-api
docker compose up -d --build

Re-run smoke probe:
cd /Users/ericferrier/Documents/GitHub/agri-dao-app/agent-langChain
./scripts/smoke-timeouts.sh


## Start separated stacks

Start Python app/workers stack:

```bash
docker compose up -d --build
```

Start Node API stack in a separate compose project:

```bash
cd ../node-api
docker compose up -d --build
```

## Verify container
 docker compose -f docker-compose.prod.yml ps

 ## End Points
 http://localhost:8000
http://localhost:3000


curl -sS http://localhost:11434/api/tags

### Mock Jira endpoint (CouchDB)

- `POST /jira/mock`
- Purpose: create a standardized mock Jira issue document in CouchDB
- Env vars used:
  - `COUCHDB_BASE_URL`
  - `COUCHDB_USER`
  - `COUCHDB_PASSWORD`
  - `COUCHDB_DATABASE` (optional, defaults to `jira_issue`)

Example request:

```bash
curl -X POST http://localhost:8000/jira/mock \
  -H "Content-Type: application/json" \
  -d '{
    "summary": "Low confidence compliance response",
    "description": "Escalating from public support flow",
    "priority": "high",
    "reporter": "public_user",
    "component": "support",
    "labels": ["escalation", "compliance"],
    "category": "compliance",
    "region_id": "north_america",
    "session_id": "example-session-id",
    "escalation_reason": "requires_login_or_authenticated_internal_support"
  }'
```

### Async Jira workflow (recommended)

- `POST /jira/enqueue`
  - enqueues Jira mock issue job and returns `202` with `job_id`
- `GET /jira/job/{job_id}`
  - returns job status (`pending`, `processing`, `created`, `failed`)
- `jira-worker` service
  - polls pending jobs and writes finalized issue documents to CouchDB

Example enqueue request:

```bash
curl -X POST http://localhost:8000/jira/enqueue \
  -H "Content-Type: application/json" \
  -d '{
    "summary": "Low confidence compliance response",
    "description": "Escalating from public support flow",
    "priority": "high",
    "reporter": "public_user",
    "component": "support",
    "labels": ["escalation", "compliance"],
    "category": "compliance",
    "region_id": "north_america",
    "session_id": "example-session-id",
    "escalation_reason": "requires_login_or_authenticated_internal_support"
  }'
```

Example status check:

```bash
curl -sS http://localhost:8000/jira/job/<job_id>
```


## LangSmith tracing

- The Python app is configured to send LangChain and LangGraph traces to LangSmith.
- Required `.env` values:
  - `LANGSMITH_API_KEY`
  - `LANGSMITH_TRACING=true`
  - `LANGSMITH_PROJECT=agri-dao-rag` (or your preferred project name)
- After changing tracing settings, rebuild and restart the app service:

```bash
docker compose -f docker-compose.prod.yml build app
docker compose -f docker-compose.prod.yml up -d app
docker compose -f docker-compose.prod.yml logs -f app
```

- Verify locally:
  - `http://localhost:8000/health`
- Verify in LangSmith:
  - `https://smith.langchain.com`

## Response Contract (RAG)

The RAG response now uses a consistent shape for both success and fallback paths.

Core fields:

- `status`: `ok` or `degraded_fallback`
- `verified`: boolean
- `verification_status`: `verified` or `unverified`
- `llm_available`: boolean
- `should_retry`: boolean
- `confidence`: number (0.0 to 1.0)
- `confidence_label`: `low`, `medium`, or `high`
- `escalate`: boolean
- `escalation_reason`: string
- `error`: empty string on success, populated on fallback

Fallback behavior when Ollama is unavailable:

- returns `status=degraded_fallback`
- returns `verified=false`
- returns `verification_status=unverified`
- returns `llm_available=false`
- returns `should_retry=true`
- preserves request context fields (`query`, `tier`, `region_id`, `session_id` when available)

This prevents worker lock-ups and gives frontend/backend a deterministic branch for retry/escalation.

## Troubleshooting

If you see `Unable to generate an answer from Ollama`:

1. Confirm Ollama server is running on host:
  - `curl -sS http://localhost:11434/api/tags`
2. Confirm app health and tracing flags:
  - `curl -sS http://localhost:8000/health`
3. Rebuild and restart containers after code/config changes:

```bash
docker compose build app
docker compose up -d app jira-worker reference-worker
docker compose logs -f app jira-worker reference-worker

cd ../node-api
docker compose build node-api
docker compose up -d node-api
docker compose logs -f node-api
```

4. Run timeout smoke probe:

```bash
./scripts/smoke-timeouts.sh
```

Faster troubleshooting mode (shorter max times + live per-step progress):

```bash
QUICK_MODE=1 ./scripts/smoke-timeouts.sh
```

Optional end-to-end verify probe with a known batch id:

```bash
BATCH_ID=<existing-batch-id> ./scripts/smoke-timeouts.sh
```


## 3. Build & Run
```bash

find . -name '._*' -type f -delete

DOCKER_BUILDKIT=1 docker compose -f docker-compose.prod.yml build --no-cache
```

App will be available at:
```
http://localhost:8000
```

API docs at:
```
http://localhost:8000/docs
```

---

## Run App

 To call main.py from the terminal inside the Docker container:

  Option 1: Direct Python execution

  docker compose exec app python app/main.py

  Option 2: Using uvicorn (as defined in Dockerfile)

  docker compose exec app uvicorn app.main:app --host 0.0.0.1 --port 8000

  Option 3: Get into container shell first, then run

  docker compose exec app bash
  # Inside container:
  python app/main.py
  # or
  uvicorn app.main:app --host 0.0.0.0 --port 8000


## 4. Stopping the App
```bash
docker compose down
```

---

## 5. Useful Commands

  What happens when you visit http://localhost:8000:
  - You'll see a web page in your browser
  - FastAPI typically shows an automatic API documentation interface
  - You can interact with your API endpoints through the web UI

  This is different from a terminal because:
  - Terminal: Command-line interface where you type commands
  - Web interface: Graphical interface you access through a web browser

  If you want a terminal inside the container:
  docker compose exec app bash

  If you want to run Python scripts:
  docker compose exec app python app/main.py

  The FastAPI web interface at localhost:8000 lets you:
  - View API documentation
  - Test API endpoints
  - See your application's web responses

  So when your build finishes, you'll have both:
  1. A running web service at http://localhost:8000 (browser)
  2. The ability to get a terminal with docker compose exec app bash
  

| Command | Description |
|---|---|
| `docker compose up --build` | Build and start |
| `docker compose up` | Start without rebuilding |
| `docker compose down` | Stop and remove containers |
| `docker compose logs -f` | Tail live logs |
| `docker compose exec app bash` | Shell into the container |
| `ollama list` | See downloaded models |
| `ollama pull mistral` | Download Mistral model |


## Reading Notes


💡 One thing to watch (important)

LangChain + Mistral integration is still evolving.

If you hit issues:
 • fallback to direct Mistral SDK calls inside LangChain tools
 • or wrap Mistral in a custom LLM class

⸻

If you want next step, I can give you:
 • a main.py FastAPI + LangChain + Mistral example
 • or a DAO proposal analyzer agent wired to Oracle

Just tell me 👍



Short answer: use a hybrid stack—don’t pick just one.

If you’re building DAO governance on Solana, the cleanest and most scalable approach is:

⸻

🧠 Recommended Architecture (Battle-tested)

1. On-chain logic → Rust + Anchor
 • Use Rust with Anchor
 • This is where your DAO actually lives:
 • proposals
 • voting
 • treasury logic
 • governance rules

👉 Why:
 • Native performance (Solana is built for Rust)
 • Security + auditability
 • Anchor simplifies dev massively (IDLs, accounts, validation)

⸻

2. Backend / API layer → Node.js
 • Use Node.js
 • Connect via Helius RPC

👉 Responsibilities:
 • Index blockchain data
 • Serve your frontend
 • Handle wallet interactions
 • Cache governance state
 • Trigger off-chain workflows

👉 Why Node:
 • Best ecosystem for Solana tooling (@solana/web3.js)
 • Easier wallet + frontend integration
 • Faster iteration than Rust for APIs

⸻

3. AI / automation layer → Python + LangChain (optional)
 • Use Python with LangChain

👉 Use cases:
 • Proposal summarization
 • Governance insights
 • AI voting assistants
 • Risk analysis of proposals

👉 Why Python:
 • AI ecosystem >> Node/Rust
 • LangChain integrates easily with vector DBs, agents

⸻

4. Infra → Docker (good choice)
 • Containerize everything:
 • Node API
 • Python AI services
 • Indexers / workers

👉 Why:
 • Clean deployment
 • Scales easily
 • Matches your modular DAO vision

⸻

⚖️ What NOT to do (common mistakes)

❌ Pure Node.js governance logic
 • You cannot run real DAO governance off-chain securely
 • Only good for UI / helpers

❌ Pure Python backend
 • Weak Solana ecosystem
 • Slower + less maintained tooling

❌ Rust for everything
 • Overkill for APIs
 • Slows development drastically

⸻

🧩 Stack Summary

Layer Best Choice
Smart contracts Rust + Anchor
Backend/API Node.js + Helius RPC
AI layer Python + LangChain
Infra Docker


⸻

🚀 Bonus (advanced, relevant to your project)

Given you’re building traceability + DAO (TerraDAO), consider:
 • Store metadata off-chain (IPFS / S3 like your Hetzner setup)
 • Anchor program stores:
 • hashes
 • proposal state
 • voting records
 • Use Helius for:
 • webhooks (proposal created, vote cast)
 • indexing (fast UI)

⸻

💡 My blunt recommendation

If you want speed + scalability:

👉 Rust (Anchor) + Node (Helius) is non-negotiable core
👉 Add Python (LangChain) only when you actually need AI

⸻

If you want, I can map this into:
 • a full repo structure (monorepo with Docker)
 • DAO governance contract schema (Anchor)
 • or a voting flow diagram (wallet → proposal → execution)

Just tell me 👍