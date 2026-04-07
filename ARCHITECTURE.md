# Architecture (Mode A Now, Kubernetes Later)

## Current deployment mode

- Runtime model: Mode A (single Docker image on Hetzner VPS)
- Inside container: Node.js API + Web3 service (public API surface)
- Inside container: Python LangChain RAG service (internal only)
- Frontend: Vercel Hydrogen / Remix

## Canonical topology

Frontend (Hydrogen/Remix)
        -> HTTPS
Node.js API + Web3 (same container)
        -> internal HTTP/gRPC
Python LangChain RAG (same container)
        -> ArangoDB
Node.js API + Web3
        -> Solana RPC / programs

## Data responsibilities

- ArangoDB is the source for business entities (orders, batches, shipment, disputes).
- ArangoDB is the source for vector embeddings and retrieval collections.
- Solana is the source for proofs/hashes and on-chain metadata.
- Solana is the source for program/account state required for trust and verification.

## Service boundaries and tool ownership

- Node.js service owns all external APIs (REST/GraphQL, CORS).
- Node.js Web3 layer is the only on-chain gateway.
- Solana interactions use Node tooling (@solana/web3.js and related Node/Anchor client utilities).
- Python RAG service does not submit Solana transactions directly.
- Python RAG focuses on retrieval, reasoning, and recommendation outputs for Node to approve/execute.

## Request flows

### 1) Business read flow

1. Frontend calls Node endpoint, for example GET /orders?batch=123.
2. Node queries ArangoDB (business collections).
3. Node returns JSON response to frontend.

### 2) RAG-assisted verification/proposal flow

1. Frontend submits a verification or proposal review request to Node.
2. Node calls Python RAG with request context.
3. Python retrieves from ArangoDB vectors + supporting documents.
4. Python returns recommendation/proposed evidence package to Node.
5. Node validates policy and business rules.
6. If approved, Node writes proof/hash/metadata to Solana.
7. Node persists related app state in ArangoDB and returns response.

## LangChain proposal review policy

- Treat LangChain outputs as advisory, not authoritative.
- Node applies deterministic validation before any on-chain write.
- Validation includes schema checks, confidence thresholds, and business rule checks.
- Add optional human approval for high-risk actions.
- Persist proposal, decision, and rationale in ArangoDB for auditability.

## Operational notes

- Keep Python service private to the container network/process boundary.
- Enforce timeouts/retries/circuit-breaker from Node -> Python calls.
- Because of current environment constraints, Arango access from Python services should use httpx/curl patterns instead of python-arango.

## Kubernetes migration path (target)

- Start with one image now (Mode A) to keep deployment simple.
- When scaling, split into independent workloads: node-api-web3, python-rag, and stateful/managed ArangoDB.
- Introduce HPA on Node and RAG deployments.
- Introduce internal service-to-service auth.
- Introduce centralized tracing/logging.
- Introduce a queue/event layer for long-running RAG tasks.

