# AI System Debugger

A production-grade reliability layer for LLM systems — monitors pipelines in real time, classifies failures with semantic precision, and autonomously applies validated fixes (with safety boundaries).

## Overview

Standard observability tools tell you the system is running. They don't tell you the system is *working*. AI System Debugger captures every LLM call as a structured trace, runs an ensemble evaluator to classify failures, performs root-cause analysis, applies targeted repairs (prompt rewrite, retrieval correction, model rerouting, context enrichment), and validates each repair before accepting it.

### Key capabilities
- **Instrumentation** — structured traces with itemised cost, latency breakdown, retrieved-doc objects (with similarity scores), task type and routing metadata.
- **Hybrid model routing** — task-aware routing between OpenAI GPT-4o and a local Llama (Ollama). Falls back gracefully and logs every escalation.
- **Ensemble failure detection** — LLM-as-judge + embedding similarity + rule-based, majority agreement, with a fine-grained failure taxonomy (`hallucination`, `retrieval_failure`, `context_loss`, `reasoning_failure`, `prompt_failure`).
- **Root cause analysis** — heuristic signal detection + LLM analysis, mapped to repair strategies.
- **Self-healing** — LangGraph pipeline with two-stage prompt repair (Llama draft → GPT-4o escalation), retrieval correction, model rerouting, context enrichment. Fixes are validated by re-running the ensemble evaluator on the repaired output.
- **Bayesian strategy selection** — `(failure_source, strategy)` priors are updated after every healing attempt; the strategy with the highest posterior mean is selected first.
- **Persistent fix repository** — successful repairs are embedded into a FAISS index on disk for similarity-based reuse on future traces.
- **Safety boundaries** — traces tagged `risk_tier ∈ {financial, legal, medical}` are never auto-healed; they're routed to a human review queue.
- **Human-in-the-loop** — low-confidence (<0.6) and high-risk traces are auto-enqueued; reviewer labels feed the evaluator calibration job.
- **Evaluator calibration** — precision/recall/F1/agreement-rate of each evaluator are recomputed from human labels and surfaced on the dashboard.
- **Structural failure detection** — recurring patterns (>= 3 occurrences of the same failure_type + source + prompt fingerprint) are surfaced as structural failures requiring engineering attention.
- **Drift detection** — failure rate, latency, healing success vs prior window.
- **Cost + latency dashboards** — itemised cost, cost per trace, per-component P50/P90/P99 latency.

## API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/trace` | POST | Submit a trace with cost/latency/retrieved-doc/risk-tier fields |
| `/trace/{id}` | GET | Fetch a stored trace |
| `/analyze` | POST | Run the ensemble evaluator |
| `/rca` | POST | Root cause analysis |
| `/fix` | POST | Apply self-healing (or route high-risk traces to manual review) |
| `/compare` | POST | Real evaluator-based original vs repaired comparison |
| `/metrics` | GET | Pipeline aggregates over a window |
| `/metrics/cost` | GET | Aggregate cost (total / model / evaluation / per-trace / by-model) |
| `/metrics/latency` | GET | Per-component P50/P90/P99 latency |
| `/metrics/structural-failures` | GET | Recurring failure clusters |
| `/evaluator-health` | GET | Evaluator precision/recall/F1/agreement |
| `/evaluator-health/recalibrate` | POST | Recompute evaluator metrics from human labels |
| `/drift` | GET | Drift across failure-rate, latency, healing-success |
| `/review/queue` | GET | Human review queue |
| `/review/{id}/label` | POST | Submit a ground-truth label |
| `/health` | GET | Liveness probe |

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11+, FastAPI |
| ORM / migrations | SQLAlchemy async, Alembic |
| LLM (reasoning) | OpenAI GPT-4o |
| LLM (lightweight) | Llama 3.2 via Ollama |
| Evaluation | sentence-transformers, custom rule engine |
| Self-healing | LangGraph, FAISS (persistent fix index) |
| Storage | PostgreSQL 15, Redis 7 |
| Frontend | React 18, Vite, Tailwind CSS, Recharts |

## Project structure

```
ai-system-debugger/
├── backend/
│   ├── api/                # FastAPI routers (trace, analyze, healing, metrics, review)
│   ├── core/               # Settings (pydantic-settings) + dependency injection
│   ├── models/             # Pydantic schemas (30+ request/response models)
│   ├── services/
│   │   ├── instrumentation/  # Trace capture + OpenTelemetry integration
│   │   ├── monitoring/       # Pipeline metrics, cost, latency, drift detection
│   │   ├── evaluation/       # 3-evaluator ensemble + calibration from human labels
│   │   ├── rca/              # Heuristic + LLM root cause analysis
│   │   ├── healing/          # LangGraph pipeline + FAISS repo + Bayesian selector
│   │   └── routing/          # Task-aware ModelRouter with complexity scoring
│   ├── storage/            # Async SQLAlchemy ORM + Redis cache
│   ├── Dockerfile
│   ├── entrypoint.sh       # Waits for Postgres, runs Alembic, starts uvicorn
│   └── main.py
├── frontend/
│   ├── src/
│   │   ├── pages/          # 9 pages: Dashboard, Traces, Healing, Evaluators,
│   │   │                   #   Drift, Costs, Latency, Review Queue, Admin
│   │   ├── components/     # Sidebar, MetricCard, StatusBadge, PageHeader
│   │   └── api.js          # Centralized API client
│   ├── Dockerfile          # Multi-stage Node build → nginx
│   └── nginx.conf          # SPA routing + /api proxy to backend
├── alembic/versions/       # 001_initial_schema, 002_enriched_trace_schema
├── data/                   # Sample traces (15 scenarios)
├── scripts/
│   └── load_sample_data.py # Seed script: drives full pipeline via API
├── tests/
│   ├── unit/               # Routing, evaluation, RCA, instrumentation, schemas
│   └── integration/        # API endpoints + E2E pipeline test
├── docker-compose.yml      # Postgres + Redis + backend + frontend
├── requirements.txt
└── .env.example
```

## Getting started

### Quick start (Docker)

```bash
git clone https://github.com/Adeliyio/ai-system-debugger.git
cd ai-system-debugger

# Copy env file (only ASD_OPENAI_API_KEY is required for full functionality)
cp .env.example .env
# Edit .env and set ASD_OPENAI_API_KEY=sk-...

# Start all services
docker-compose up --build
```

The dashboard is at **http://localhost:3000**. The API is at **http://localhost:8000**.

### Seed demo data

After the backend is running:

```bash
python scripts/load_sample_data.py --base-url http://localhost:8000
```

This walks 15 sample traces through the full pipeline (`/trace` → `/analyze` → `/rca` → `/fix`), populating every dashboard page with realistic data. Includes:
- Correct responses (should pass evaluation)
- Hallucinations (fabricated facts not in context)
- Empty/refusal responses (prompt failures)
- Medical and financial risk-tier traces (routed to human review queue)
- Local model (Llama) routing examples

Use `--skip-fix` to skip the self-healing step (useful without an OpenAI key or Ollama).

### Local development (without Docker)

**Prerequisites:** Python 3.11+, Node.js 18+, PostgreSQL 15+, Redis 7+

```bash
# Backend
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

**Configuration:** Copy `.env.example` to `.env` and set at minimum:

| Variable | Required | Description |
|---|---|---|
| `ASD_OPENAI_API_KEY` | Yes (for full pipeline) | OpenAI API key for GPT-4o evaluation/RCA/healing |
| `ASD_DATABASE_URL` | Yes | PostgreSQL connection string (asyncpg dialect) |
| `ASD_REDIS_URL` | Yes | Redis connection string |
| `ASD_LOCAL_MODEL_ENDPOINT` | No | Ollama endpoint (default: `http://localhost:11434`) |
| `ASD_DEBUG` | No | Enable debug logging (default: `false`) |

See `.env.example` for the full list of configuration options.

**Run:**

```bash
# Start Postgres + Redis (or use Docker for just these)
docker-compose up postgres redis -d

# Run database migrations
alembic upgrade head

# Start backend
uvicorn backend.main:app --reload

# Start frontend (separate terminal)
cd frontend && npm run dev
```

Dashboard: **http://localhost:3000** (Vite proxies `/api/*` to the backend on port 8000).

### Running tests

```bash
python -m pytest tests/ -v
```

Tests use mock dependencies and run without external services (no DB, Redis, or API keys needed).

## Architecture highlights

- **Ensemble evaluation with majority voting** — 3 independent evaluators (LLM judge, embedding similarity, rule-based) must agree by majority (2/3) before flagging a failure. Single-evaluator dissent is logged but not acted on.

- **Two-stage self-healing** — Llama 3.2 drafts a repair locally (fast, free). If the ensemble evaluator rejects the draft, it escalates to GPT-4o with the failed attempt as additional context. Saves ~35% on repair costs.

- **Bayesian fix-strategy selector** — Each `(failure_source, strategy)` pair maintains Beta-distribution counts. The strategy with the highest posterior mean is tried first, learning from every healing outcome.

- **Safety boundaries** — Traces in `financial`, `legal`, or `medical` risk tiers are never auto-healed. They're routed to the human review queue regardless of evaluator confidence.

- **Evaluator meta-evaluation** — The `/evaluator-health` endpoint tracks precision/recall/F1 for each evaluator against human-labeled ground truth. Known systematic biases are surfaced on the dashboard.

## License

MIT
