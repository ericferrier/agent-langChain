# CLAUDE.md

## Goal

Build a small support application where a human user asks a support-focused question through a web interface. The system should:

- accept only in-scope support questions for our platform
- attempt to answer using the internal support knowledge base and application logic
- detect when the answer is insufficient or confidence is low
- escalate by creating a Jira support ticket
- give the user the ticket reference and current status

## Product Scope

- Support requests only
- No general chat assistant behavior
- No unrelated brainstorming, coding help, or open-ended LLM usage
- Clear escalation path to Jira when no reliable answer is found

## Phase 1: Requirements And Scope ← CURRENT PHASE

- Define the exact support scope the assistant is allowed to handle
- List supported issue categories
- Define out-of-scope categories and rejection behavior
- Define what counts as a satisfactory answer
- Define escalation triggers for Jira ticket creation
- Define required metadata for a ticket: summary, description, priority, reporter, component, labels
- Decide whether users are anonymous, authenticated, or internal-only

### Resource Visibility Model

Every resource in the `resource` collection carries a `visibility` field that controls access at the retrieval layer.

| Value | Who can access | Description |
|---|---|---|
| `public` | Anyone (anonymous or logged-in) | General trade, customs, and compliance references. All 267 seeded resources are `public`. |
| `system` | Verified trusted accounts only | Privileged runbooks, internal pricing data, escalation playbooks, admin procedures, or any resource that requires an authenticated and DAO-verified identity before exposure. |

**Current state:** all seeded resources are `public`.

**Adding `system` resources:** set `"visibility": "system"` in the resource entry in `db/init/02_resources.py`. The retrieval layer in `app/services/resource_search.py` must filter on `visibility` based on the caller's trust level before returning results.

**Retrieval rule (to implement in Phase 3):**
- Anonymous / unauthenticated callers → `FILTER r.visibility == "public"`
- Verified trusted account callers → no visibility filter (sees `public` + `system`)

## Phase 2: UX And Application Flow

- Design a simple web UI with a support-only prompt box
- Add copy that tells users the assistant is limited to platform support
- Add issue category selection to improve routing
- Add an optional field for user email or name
- Show answer, confidence, and source references when available
- Add a clear "Create Jira ticket" action when answer is not sufficient
- Add a user confirmation step before ticket submission
- Show created ticket key and next steps after escalation

## Phase 3: Backend API Design

- Define endpoint for asking a support question
- Define endpoint for retrieving suggested answer and confidence
- Define endpoint for escalating to Jira
- Define endpoint for checking ticket status if needed
- Define request and response schemas with validation
- Add structured error handling for LLM, retrieval, and Jira failures

## Phase 4: Prompt Guardrails

- Create a system prompt that restricts the assistant to platform support topics
- Reject or redirect out-of-scope questions
- Prevent the model from inventing policies, fixes, or unsupported steps
- Require the answer to say when information is missing
- Add explicit escalation behavior when confidence is low
- Add prompt tests for in-scope and out-of-scope requests

## Phase 5: Knowledge And Retrieval

- Identify support documentation sources to index
- Normalize source documents into chunks suitable for retrieval
- Choose retrieval backend: local FAISS, Chroma, or database-backed retrieval
- Store source metadata for citations and auditability
- Implement retrieval for support answers
- Add a fallback when no relevant context is found
- Define a confidence heuristic based on retrieval quality and answer completeness

### Concrete Support Source Inventory For AgriguildDAO

#### Internal Product Support Sources

- User onboarding and account access guides
- Wallet connection, signature, and session troubleshooting guides
- DAO membership, role, and permissions documentation
- Proposal creation, voting, quorum, and execution help articles
- Marketplace listing, trade posting, and transaction workflow guides
- Export workflow support documents tied to platform actions
- Payment, settlement, escrow, and token usage documentation
- Admin support runbooks for account recovery, role changes, and incident response
- Release notes and known issues logs

#### Internal Operational Sources

- Support FAQ content
- Resolved Jira support tickets grouped by issue category
- Customer support macros and canned responses
- Incident postmortems and outage communications
- Smart contract deployment/version notes relevant to support
- RPC endpoint/network troubleshooting procedures
- KYC/KYB verification workflow documentation
- Internal escalation policies for compliance, fraud, and operational issues

#### Region-Specific Support Sources

- Region eligibility and activation rules based on supported `regions` configuration
- Export/import workflow guidance by region
- Commodity and agricultural trade restrictions by region
- Customs, certification, and document requirements by region
- Payments, settlement, and currency constraints by region
- Data privacy and user-consent obligations by region
- Sanctions, restricted-market, and marketplace availability rules by region
- Region-specific user messaging and escalation requirements

#### Region Packs To Maintain

- `africa`: agricultural market access, export requirements, payment/FX constraints, local compliance notes
- `australia`: wholesale pricing benchmarks, horticulture market reporting, export documentation, and regulatory guidance
- `caribbean`: island-specific shipping, customs, and trade corridor support notes
- `central_america`: producer verification, cross-border trade, and export documentation support
- `east_asia`: licensing, trade documentation, translation, and jurisdiction-specific restrictions
- `european_union`: EU27 trade rules, GDPR/privacy obligations, traceability requirements, VAT-related support guidance
- `gulf_cooperation_council`: GCC trade rules, customs workflows, certification requirements, settlement constraints
- `nordic_market`: sustainability, traceability, privacy, and reporting expectations
- `north_america`: Canada-specific agricultural market rules, onboarding constraints, and support responses
- `south_america`: export controls, producer docs, customs support, and settlement guidance
- `southeast_asia`: trade regulations, logistics/port workflow support, and country-specific restrictions

#### External Reference Sources To Curate

- Government agriculture and export portals
- Customs and border authority guidance
- Regional trade bloc guidance and regulatory summaries
- Privacy and data protection authority references
- Sanctions and restricted-party screening references
- Payment and settlement compliance references where relevant to the platform

#### Recommended Metadata For Each Source

- `source_id`
- `title`
- `source_type`: faq, runbook, policy, ticket, product_doc, regulation_summary
- `region_id`
- `country_codes`
- `topic`
- `workflow`
- `audience`
- `owner`
- `version`
- `last_reviewed`
- `escalation_required`

#### Retrieval Topics For MVP

- wallet-access
- identity-verification
- dao-membership
- proposal-voting
- marketplace-listing
- export-documents
- shipping-logistics
- pricing
- payment-settlement
- compliance-region
- account-access
- transaction-failure
- smart-contract-status
- dispute-resolution

#### MVP Source Loading Order

- Internal FAQ and onboarding docs
- Admin/support runbooks
- Resolved Jira tickets for top recurring issue types
- Product workflow docs for wallet, DAO, marketplace, and export actions
- Region packs for `european_union`, `africa`, and `north_america`
- Curated external regulatory summaries written or reviewed by the team

## Phase 6: LLM Integration

- Reuse the current Ollama + Mistral setup for first implementation
- Add configurable model, timeout, and base URL settings
- Create a support-answer chain separate from generic generation
- Format responses consistently for the UI
- Log model failures and latency
- Add safe fallback responses when the model is unavailable

## Phase 7: Jira Integration

- Choose Jira Cloud vs Jira Server target
- Decide authentication method: API token, OAuth, or service account
- Store Jira credentials in environment variables or secret manager
- Implement Jira client wrapper in the service layer
- Map support issue fields into Jira issue payloads
- Create a ticket only after user confirmation or explicit escalation rule
- Return Jira ticket key, URL, and creation result to the UI
- Handle duplicate or repeated ticket submissions safely

## Phase 8: Business Logic For Escalation

- Define low-confidence thresholds for escalation
- Escalate when retrieval returns weak or no support evidence
- Escalate when the user says the answer did not solve the problem
- Escalate automatically for high-severity categories if desired
- Add a summary generator for Jira ticket descriptions
- Include user prompt, attempted answer, and relevant context in the ticket

## Phase 9: Data Model And Persistence

- Decide what interactions to persist
- Store question, answer, confidence, escalation decision, and ticket key
- Store user feedback on whether the answer solved the issue
- Add audit logs for ticket creation actions
- Decide whether ArangoDB will hold conversations, tickets, and knowledge metadata

### ArangoDB Access Convention

**All ArangoDB access in this project uses `curl -4` HTTP REST calls, not the `python-arango` client library.**

ArangoDB is accessed over a **WireGuard VPN tunnel** at `http://10.0.0.1:8529`. The `-4` flag is required to force IPv4 and route correctly through the WireGuard interface.

`python-arango` has a known connectivity failure in this environment (exits with code 1) — its internal connection pool/resolver does not route through the WireGuard interface reliably. `curl -4` and `httpx` both use the OS network stack directly, which respects WireGuard routing and work correctly.

Every service file that reads or writes ArangoDB must use `httpx` (async services) or `curl -4` (seed scripts).

| Layer | Method | Example |
|---|---|---|
| Seed scripts (`db/init/`) | `curl -4` via `subprocess` or shell | `02_resources.py` |
| Service layer (`app/services/`, `app/checkpointer/`) | `httpx.AsyncClient` | `resource_search.py`, `arango_cp.py` |
| One-off queries / debugging | `curl -4 -u system:PASSWORD` | Terminal |

**Do not add `python-arango` calls anywhere.** If a new service needs ArangoDB access, follow the `httpx` pattern in `app/services/resource_search.py`.

## Phase 10: Security And Access Control

- Restrict the app to internal users if required
- Sanitize user input before logging or sending to Jira
- Prevent prompt injection from attached support documents
- Avoid leaking internal secrets or configuration through answers
- Protect Jira credentials and model endpoints
- Add rate limits to reduce abuse

## Phase 11: Frontend Implementation

- Build a minimal support page in the web app
- Add a prompt input form with validation
- Add answer display with cited sources
- Add answer feedback buttons: solved / not solved
- Add escalation form fields for Jira ticket creation
- Display loading, error, and success states clearly
- Keep the flow simple and support-oriented

## Phase 12: Testing

- Add unit tests for prompt filtering and scope checks
- Add unit tests for escalation decision logic
- Add integration tests for Ollama responses
- Add integration tests for Jira client with mocks
- Add API tests for ask and escalate endpoints
- Add regression tests for out-of-scope prompt rejection

## Phase 13: Deployment And Operations

- Add required environment variables to compose and deployment config
- Verify container can reach Ollama and Jira endpoints
- Add health checks for API and model dependency behavior
- Add logging for answer generation and escalation actions
- Add monitoring for ticket creation failures
- Document local setup and production setup

## Initial Build Order

- Implement a strict support-only ask endpoint
- Add retrieval from a small internal support knowledge base
- Return answer plus confidence and citations
- Add user feedback: solved / not solved
- Add Jira escalation endpoint
- Add simple frontend page for the full flow
- Add tests and operational logging

## Open Questions

- What support domains are allowed in version 1?
- Should escalation require explicit user approval every time?
- What Jira project key should be used?
- What fields are mandatory in the Jira workflow?
- Should tickets include conversation transcript and retrieved sources?
- Do we need authentication before allowing ticket creation?

## Definition Of Done For MVP

- User can submit a support question in the web UI
- System answers only in-scope support questions
- System cites internal support context when answering
- User can mark the answer as not sufficient
- System creates a Jira ticket with the relevant summary and context
- User receives the Jira ticket key and confirmation in the UI
- Basic tests cover prompt scope, answer flow, and escalation flow