# Defect Reporting System (Proof of Concept)

A web-based defect reporting application covering the full defect lifecycle:

**User Reporting → Triage → Fix & Verify → Close Loop**

Built as microservices: Python FastAPI backends + React frontend, one shared
PostgreSQL database with a real schema per service (`reporting`, `triage`,
`fixverify`, `notification`) and `pg_trgm` fuzzy text search, AI features
powered by a self-hosted OpenAI-compatible vLLM endpoint.

## Architecture at a glance

| Component | Port | Responsibility |
|---|---|---|
| `services/gateway` | 8000 | API gateway (routes `/api/*` to services) + webhook event fan-out |
| `services/reporting` | 8001 | Issue intake, smart categorization, ETA estimation, issue lifecycle (source of truth) |
| `services/triage` | 8002 | Severity/urgency suggestion, duplicate detection, systemic-fault analytics, MTBF/MTTR |
| `services/fixverify` | 8003 | Work orders, proof-of-work upload, AI relevance verification, human verification |
| `services/notification` | 8004 | In-app notification inbox, driven by events |
| `frontend` | 5173 | React dashboard (report, track, triage board, fix & verify, notifications) |

See `docs/` for the full design documentation:

- [00 — Design Overview](docs/00-design-overview.md)
- [01 — Architecture](docs/01-architecture.md)
- [02 — Data Model](docs/02-data-model.md)
- [03 — API Contracts](docs/03-api-contracts.md)
- [04 — AI Integration](docs/04-ai-integration.md)
- [05 — Triage & Analytics](docs/05-triage-analytics.md)

## Quickstart

### Prerequisites
- Python 3.11+, Node 20+
- An OpenAI-compatible vLLM endpoint (see `.env.example`)

### Option A: docker compose

```bash
cp .env.example .env   # fill in VLLM_* values
docker compose up --build
```

### Option B: run locally

```bash
cp .env.example .env
docker compose up -d postgres   # the DB still comes from compose
# In separate terminals (or use a process manager):
for svc in reporting triage fixverify notification gateway; do
  (cd services/$svc && pip install -r requirements.txt && uvicorn app.main:app --port $PORT)
done
cd frontend && npm install && npm run dev
```

Ports: gateway 8000, reporting 8001, triage 8002, fixverify 8003, notification 8004.

Open http://localhost:5173. Pick a role (Reporter / Maintenance / Admin) from the
role picker — this is a proof of concept, there is no real authentication.

## Repository layout

```
docs/                  Design documentation
services/
  gateway/             FastAPI gateway + event bus
  reporting/           Issue intake & lifecycle
  triage/              Triage & analytics
  fixverify/           Work orders & proof verification
  notification/        In-app notifications
frontend/              React (Vite) app
docker-compose.yml
.env.example
```
