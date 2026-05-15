![Tommy's System Debugger](docs/images/hero-banner.png)

# Tommy's System Debugger

**A production-grade reliability layer for LLM systems that monitors pipelines in real time, classifies failures with semantic precision using an ensemble evaluator, performs root-cause analysis, and autonomously applies validated repairs with safety boundaries. Includes Bayesian strategy selection, persistent fix reuse, and a full human-in-the-loop review pipeline.**

## The Problem

Standard observability tools tell you the system is running. They don't tell you the system is *working*. When an LLM pipeline hallucinates, retrieves the wrong documents, or silently degrades, traditional monitoring sees healthy HTTP 200s while users receive confidently wrong answers. Teams discover failures reactively, through support tickets and customer complaints, not through their dashboards.

The core engineering question is not "can we detect that the LLM failed?" but rather "can we detect *how* it failed, *why* it failed, and *fix it automatically* while keeping humans in the loop for high-stakes decisions?"

### What This Project Does

1. **Captures every LLM call as a structured trace**, with itemised cost, latency breakdown, retrieved-document objects (with similarity scores), task type, and routing metadata
2. **Runs an ensemble failure detector** combining three independent evaluators (LLM-as-judge, embedding similarity, rule-based) with majority voting, producing a fine-grained failure taxonomy: `hallucination`, `retrieval_failure`, `context_loss`, `reasoning_failure`, `prompt_failure`
3. **Performs root-cause analysis** using heuristic signal detection plus LLM analysis, mapped to specific repair strategies
4. **Self-heals failures autonomously** via a LangGraph pipeline with two-stage prompt repair (Llama draft then GPT-4o escalation), retrieval correction, model rerouting, and context enrichment, validating every fix by re-running the ensemble evaluator
5. **Selects repair strategies with Bayesian learning**, each `(failure_source, strategy)` pair maintains Beta-distribution counts; the strategy with the highest posterior mean is tried first, learning from every healing outcome
6. **Embeds successful fixes into a FAISS index** for similarity-based reuse on future traces, building an institutional memory of repairs
7. **Enforces safety boundaries**, traces tagged `risk_tier in {financial, legal, medical}` are never auto-healed; they're routed to a human review queue
8. **Tracks evaluator health** with precision/recall/F1/agreement computed from human labels, surfacing known biases on the dashboard

### Business Impact

| Metric | Before | After |
|--------|--------|-------|
| Failure detection | Support tickets and complaints | Ensemble evaluator catches failures in real time |
| Root cause analysis | Manual log review | Automated RCA with failure taxonomy and repair mapping |
| Time to fix | Hours of engineering investigation | Seconds (autonomous repair with validation) |
| Repair strategy selection | Trial and error | Bayesian posterior, learns from every attempt |
| High-risk decision handling | Same pipeline as everything else | Safety boundaries route to human review queue |
| Evaluator calibration | "Seems to work" | Precision/recall/F1 from human-labeled ground truth |
| Cost visibility | Aggregate monthly bills | Per-trace, per-model, per-component cost breakdown |

## Application Screenshots

### Pipeline Dashboard

The main dashboard shows real-time pipeline health: total traces processed, failure rate, healing success rate, and drift indicators. Summary cards display active alerts, recent failures, and evaluator agreement rates at a glance.

![Pipeline Dashboard](docs/images/pipeline-dashboard.png)

### Trace Explorer

The trace explorer lists all captured traces with status badges (passed, failed, healed, pending review). Each row shows the model used, task type, latency, cost, and failure type if detected. Clicking a trace opens the full detail view with prompt, response, retrieved documents, and evaluation verdicts.

![Trace Explorer](docs/images/trace-explorer.png)

### Ensemble Evaluation Detail

The evaluation detail view shows how each of the three evaluators voted on a trace: LLM judge verdict, embedding similarity score, and rule-based check results. The majority agreement count and final failure classification are displayed with the full failure taxonomy.

![Ensemble Evaluation](docs/images/ensemble-evaluation.png)

### Self-Healing Pipeline

The healing view displays the repair workflow: root cause identification, strategy selection (with Bayesian posterior scores), repair attempt (Llama draft vs GPT-4o escalation), and validation result. Successful repairs show the before/after comparison with improvement scores.

![Self-Healing Pipeline](docs/images/self-healing-pipeline.png)

### Cost and Latency Analytics

Itemised cost dashboards break down spending by model, by evaluation, and per-trace. Latency charts show P50/P90/P99 per component (LLM call, retrieval, evaluation, healing). Drift detection overlays highlight shifts vs the prior window.

![Cost and Latency](docs/images/cost-latency.png)

### Evaluator Health and Calibration

The evaluator health page shows precision, recall, F1, and agreement rate for each evaluator computed against human-labeled ground truth. Systematic biases (e.g., rule-based evaluator over-flags short responses) are surfaced with calibration charts.

![Evaluator Health](docs/images/evaluator-health.png)

### Human Review Queue

Traces routed for human review (high-risk tier or low evaluator confidence) appear in the review queue with the reason for escalation. Reviewers submit ground-truth labels that feed back into evaluator calibration, closing the feedback loop.

![Human Review Queue](docs/images/human-review-queue.png)

### Drift Detection

The drift dashboard compares failure rate, latency, and healing success rate against a prior time window. Statistically significant shifts are flagged, and structural failures (recurring patterns of the same failure type + source + prompt fingerprint) are surfaced for engineering attention.

![Drift Detection](docs/images/drift-detection.png)

### Admin Console

The admin page provides system controls: trigger evaluator recalibration, run the full evaluation pipeline on sample data, view structural failure clusters, and manage the fix repository.

![Admin Console](docs/images/admin-console.png)

## Architecture

### System Overview

```
                                 +---------------------+
                                 |   React Frontend    |
                                 | Dashboard | Review  |
                                 +---------+-----------+
                                           |
                                 +---------v-----------+
                                 |   FastAPI Backend    |
                                 | /trace  /analyze     |
                                 | /fix    /metrics     |
                                 +---------+-----------+
                                           |
                  +------------------------+------------------------+
                  |                        |                        |
         +--------v--------+    +----------v----------+   +---------v---------+
         |  LangGraph       |    |  Ensemble Evaluator |   |  Monitoring       |
         |  Healing Pipeline|    |  3 Independent      |   |  Pipeline         |
         |                  |    |  Evaluators          |   |                   |
         |  Prompt Repair   |    |  LLM Judge          |   |  Cost Tracking    |
         |  Retrieval Fix   |    |  Embedding Sim      |   |  Latency P50/P99  |
         |  Model Reroute   |    |  Rule-Based         |   |  Drift Detection  |
         |  Context Enrich  |    +----------+----------+   |  Structural       |
         +---------+--------+               |              |  Failures         |
                   |             +----------v----------+   +---------+---------+
                   |             |                     |             |
                   |             | PostgreSQL  Redis   |             |
                   |             | (traces)    (cache) |             |
                   |             +---------------------+             |
                   |                                                 |
                   +---> OpenAI GPT-4o + Llama 3.2 (Ollama) <------+
                              Hybrid Model Routing
```

### Self-Healing Pipeline (LangGraph)

```
Trace with Detected Failure
  |
  v
+-----------+     +-----------+     +---------------+     +----------+     +-----------+
| Root Cause| --> | Strategy  | --> | Repair        | --> | Validate | --> | Accept /  |
| Analysis  |     | Selector  |     | Execution     |     | (Re-run  |     | Escalate  |
|           |     |           |     |               |     | Ensemble)|     |           |
| Heuristic |     | Bayesian  |     | Llama draft   |     | Pass?    |     | Update    |
| + LLM     |     | posterior |     | GPT-4o escal. |     |          |     | Bayesian  |
| signals   |     | selection |     | + retrieval   |     |          |     | priors    |
+-----------+     +-----------+     | + reroute     |     +-----+----+     +-----------+
                                    | + context     |           |
                                    +---------------+     Failed (max 2x)?
                                                               |
                                                         +-----v--------+
                                                         | FAISS Index  |
                                                         | (store fix)  |
                                                         +--------------+
```

| Component | Role | Key Decision |
|-----------|------|-------------|
| **Ensemble Evaluator** | Three independent evaluators with majority voting (2/3 agreement) | Whether a trace has failed and which failure type applies |
| **Root Cause Analyzer** | Heuristic signal detection + LLM analysis | Maps failure to repair strategy (prompt, retrieval, model, context) |
| **Bayesian Selector** | Beta-distribution posteriors per (source, strategy) pair | Which repair strategy to try first based on historical success |
| **Two-Stage Repair** | Llama 3.2 drafts locally (fast, free), escalates to GPT-4o if rejected | Saves ~35% on repair costs while maintaining quality |
| **Fix Repository** | FAISS index of successful repairs, searched by similarity | Reuse proven fixes for similar future failures |
| **Safety Boundaries** | Risk-tier check before any auto-healing | Financial/legal/medical traces always go to human review |

### Ensemble Failure Detection

```
                    +------> LLM Judge -------+
                    |        (semantic         |
Trace ------------>+------> Embedding Sim ----+----> Majority Vote (2/3) ----> Failure Type
                    |        (cosine score)    |      + Agreement Count         + Severity
                    +------> Rule Engine -----+
                             (pattern match)

Failure Taxonomy: hallucination | retrieval_failure | context_loss | reasoning_failure | prompt_failure
Severity Levels:  low | medium | high | critical
```

## Key Technical Decisions

### Ensemble Evaluation Over Single-Model Judging

A single LLM judge produces confident but uncalibrated verdicts. The system uses three independent evaluators (LLM-as-judge, embedding similarity, rule-based pattern matching) with majority voting. A failure is only flagged when 2 of 3 evaluators agree, reducing false positives from any single evaluator's systematic bias. Each evaluator's precision/recall/F1 is tracked against human labels, so drift in any individual evaluator is caught and surfaced.

### Two-Stage Self-Healing Over Direct GPT-4o

Sending every repair to GPT-4o is expensive and slow. The system first drafts a repair using Llama 3.2 locally (fast, free), then validates it with the ensemble evaluator. Only if the draft fails validation does it escalate to GPT-4o with the failed attempt as additional context. This saves approximately 35% on repair costs while maintaining repair quality, because many failures (prompt reformulation, context enrichment) don't require frontier-model reasoning.

### Bayesian Strategy Selection Over Fixed Priority

A fixed repair order (e.g., always try prompt repair first) ignores the system's accumulated experience. Each `(failure_source, strategy)` pair maintains Beta-distribution counts updated after every healing attempt. The strategy with the highest posterior mean is selected first, so the system learns which strategies work for which failure types. Early in operation, the selector explores broadly; as evidence accumulates, it converges on the most effective strategy per failure source.

### Safety Boundaries Over Universal Auto-Healing

Auto-healing is powerful but dangerous for high-stakes domains. Traces tagged with `risk_tier in {financial, legal, medical}` are never auto-healed regardless of evaluator confidence. They're routed directly to the human review queue, because the cost of an incorrect auto-repair in these domains far exceeds the latency cost of human review.

### Hybrid Model Routing Over Single-Model Architecture

The system uses task-aware routing: OpenAI GPT-4o for reasoning-critical tasks (evaluation, RCA, escalated repairs) and Llama 3.2 via Ollama for lightweight tasks (initial repair drafts, simple classifications). This balances quality, latency, and cost rather than routing everything through a single model. Routing decisions and fallbacks are logged for every trace.

### Evaluation as a First-Class Concern

Quality is measured, not assumed:

**Evaluator Health** (tracked per evaluator against human labels):

| Metric | What It Measures |
|--------|-----------------|
| Precision | Fraction of flagged failures that are actual failures |
| Recall | Fraction of actual failures that are flagged |
| F1 | Harmonic mean of precision and recall |
| Agreement Rate | How often this evaluator agrees with the majority |

**Pipeline Metrics** (computed over configurable time windows):

| Metric | What It Measures |
|--------|-----------------|
| Failure rate | Fraction of traces with detected failures |
| Healing success rate | Fraction of repair attempts that pass validation |
| Cost per trace | Total cost breakdown by model and evaluation |
| Latency P50/P90/P99 | Per-component latency percentiles |
| Drift indicators | Statistical shift vs prior window |

## Technology Stack

| Category | Technology | Rationale |
|----------|-----------|-----------|
| Language | Python 3.11+ | Type hints, async, ML ecosystem |
| Backend API | FastAPI | Async-native, Pydantic validation, auto OpenAPI docs |
| Agent Orchestration | LangGraph | Stateful healing pipeline with conditional routing |
| LLM (Reasoning) | OpenAI GPT-4o | High-quality evaluation, RCA, and escalated repair |
| LLM (Lightweight) | Llama 3.2 via Ollama | Fast local inference for draft repairs |
| Evaluation | sentence-transformers | Embedding similarity for ensemble evaluator |
| Fix Repository | FAISS | Persistent vector index for repair similarity search |
| ORM / Migrations | SQLAlchemy 2.0 (async) + Alembic | Type-safe async ORM with versioned migrations |
| Database | PostgreSQL 15 | JSONB metadata, async via asyncpg, battle-tested |
| Cache | Redis 7 | Metric caching, rate limiting, trace caching |
| Frontend | React 18 + Vite | Fast HMR, component composition, Tailwind CSS |
| Charting | Recharts | Declarative charts for metrics, latency, drift |
| Observability | OpenTelemetry + structlog | Structured tracing with per-component instrumentation |
| Deployment | Docker Compose | Single-command orchestration of all services |

## Project Structure

```
aisystemdebugger/
|
+-- docker-compose.yml              # Postgres + Redis + Backend + Frontend
+-- .env.example                     # Environment variable template
+-- requirements.txt                 # Python dependencies
|
+-- backend/
|   +-- main.py                      # FastAPI app with lifespan management
|   +-- Dockerfile
|   +-- entrypoint.sh                # Postgres wait + Alembic migrations + uvicorn
|   +-- core/
|   |   +-- config.py                # Pydantic settings (ASD_* env vars)
|   |   +-- dependencies.py          # FastAPI dependency injection
|   +-- models/
|   |   +-- schemas.py               # 30+ Pydantic request/response models
|   +-- api/
|   |   +-- traces.py                # POST /trace, GET /trace/{id}
|   |   +-- analysis.py              # POST /analyze (ensemble evaluation)
|   |   +-- healing.py               # POST /fix, /rca, /compare
|   |   +-- metrics.py               # GET /metrics, /cost, /latency, /drift
|   |   +-- review.py                # GET /review/queue, POST /review/{id}/label
|   +-- services/
|   |   +-- instrumentation/
|   |   |   +-- tracer.py            # Trace capture + OpenTelemetry integration
|   |   +-- evaluation/
|   |   |   +-- evaluator.py         # 3-evaluator ensemble with majority voting
|   |   |   +-- calibration.py       # Evaluator meta-evaluation from human labels
|   |   +-- rca/
|   |   |   +-- analyzer.py          # Heuristic + LLM root cause analysis
|   |   +-- healing/
|   |   |   +-- engine.py            # LangGraph pipeline + FAISS repo + Bayesian selector
|   |   +-- routing/
|   |   |   +-- router.py            # Task-aware model routing with complexity scoring
|   |   +-- monitoring/
|   |       +-- metrics.py           # Pipeline stats, cost, latency, drift, structural failures
|   +-- storage/
|       +-- database.py              # Async SQLAlchemy engine + session factory
|       +-- models.py                # ORM: traces, evaluations, rcas, healing_actions, reviews
|       +-- cache.py                 # Redis cache service with TTLs
|
+-- frontend/
|   +-- Dockerfile                   # Multi-stage Node build -> nginx
|   +-- nginx.conf                   # SPA routing + /api proxy to backend
|   +-- package.json
|   +-- vite.config.js               # Dev server + /api proxy
|   +-- tailwind.config.js
|   +-- src/
|       +-- App.jsx                  # React router (9 pages)
|       +-- api.js                   # Centralized API client
|       +-- pages/
|       |   +-- Dashboard.jsx        # Pipeline health overview
|       |   +-- Traces.jsx           # Trace explorer with filtering
|       |   +-- Healing.jsx          # Self-healing results
|       |   +-- EvaluatorHealth.jsx  # Evaluator calibration metrics
|       |   +-- Drift.jsx            # Drift detection dashboard
|       |   +-- Costs.jsx            # Cost breakdown analytics
|       |   +-- Latency.jsx          # Per-component latency charts
|       |   +-- Review.jsx           # Human review queue
|       |   +-- Admin.jsx            # System administration
|       +-- components/
|           +-- Sidebar.jsx          # Navigation sidebar
|           +-- MetricCard.jsx       # Summary metric display
|           +-- StatusBadge.jsx      # Color-coded status indicator
|           +-- PageHeader.jsx       # Consistent page headers
|
+-- alembic/
|   +-- versions/
|       +-- 001_initial_schema.py
|       +-- 002_enriched_trace_schema.py
|
+-- data/                            # Sample traces (15 scenarios)
|   +-- sample_traces.json
|   +-- sample_evaluations.json
|   +-- sample_healing_scenarios.json
|
+-- scripts/
|   +-- load_sample_data.py          # Seed script: drives full pipeline via API
|
+-- tests/
|   +-- conftest.py                  # Hermetic fixtures (mocked dependencies)
|   +-- unit/
|   |   +-- test_evaluation.py       # Ensemble evaluator tests
|   |   +-- test_instrumentation.py  # Trace capture tests
|   |   +-- test_rca.py              # Root cause analysis tests
|   |   +-- test_routing.py          # Model routing tests
|   |   +-- test_schemas.py          # Pydantic schema validation tests
|   +-- integration/
|       +-- test_api_analysis.py     # /analyze endpoint tests
|       +-- test_api_health.py       # /health endpoint tests
|       +-- test_api_metrics.py      # /metrics endpoint tests
|       +-- test_api_traces.py       # /trace endpoint tests
|       +-- test_pipeline_e2e.py     # Full pipeline: trace -> analyze -> rca -> fix
|
+-- docs/images/                     # Application screenshots
```

## Getting Started

### Prerequisites

- **Python 3.11+**
- **Node 20+**
- **OpenAI API key** (for GPT-4o evaluation, RCA, and escalated repairs)
- **Ollama** ([ollama.com/download](https://ollama.com/download)) — optional, for local Llama 3.2 repairs
- **PostgreSQL 15+** and **Redis 7+** (or use Docker Compose)

### Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/Adeliyio/ai-system-debugger.git
cd aisystemdebugger

# 2. Copy environment config
cp .env.example .env
# Edit .env and set ASD_OPENAI_API_KEY=sk-...

# 3. Install Python dependencies
python -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 4. Start Postgres + Redis (via Docker)
docker-compose up postgres redis -d

# 5. Run database migrations
alembic upgrade head

# 6. Start the backend
uvicorn backend.main:app --reload --port 8000

# 7. Start the frontend (separate terminal)
cd frontend
npm install
npm run dev

# 8. Open the app
#    Dashboard:  http://localhost:3000
#    API docs:   http://localhost:8000/docs
```

### Docker Compose (all services)

```bash
docker-compose up --build
# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
```

### Seed Demo Data

After the backend is running:

```bash
python scripts/load_sample_data.py --base-url http://localhost:8000
```

This walks 15 sample traces through the full pipeline (`/trace` -> `/analyze` -> `/rca` -> `/fix`), populating every dashboard page with realistic data. Includes:
- Correct responses (should pass evaluation)
- Hallucinations (fabricated facts not in context)
- Empty/refusal responses (prompt failures)
- Medical and financial risk-tier traces (routed to human review queue)
- Local model (Llama) routing examples

Use `--skip-fix` to skip the self-healing step (useful without an OpenAI key or Ollama).

### Running Tests

```bash
pytest -q
```

All tests are hermetic; external services are mocked via `tests/conftest.py`.

## API Reference

### Traces

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/trace` | POST | Submit a trace with cost, latency, retrieved docs, and risk tier |
| `/trace/{id}` | GET | Fetch a stored trace with full metadata |

### Analysis

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyze` | POST | Run ensemble evaluation (3 evaluators + majority vote) |
| `/rca` | POST | Root cause analysis with strategy mapping |
| `/fix` | POST | Apply self-healing or route to human review |
| `/compare` | POST | Original vs repaired comparison via real evaluator |

### Metrics

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/metrics` | GET | Pipeline aggregates over a configurable window |
| `/metrics/cost` | GET | Cost breakdown: total, per-model, per-evaluation, per-trace |
| `/metrics/latency` | GET | Per-component P50/P90/P99 latency |
| `/metrics/structural-failures` | GET | Recurring failure clusters requiring engineering attention |

### Evaluator Health

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/evaluator-health` | GET | Precision/recall/F1/agreement per evaluator |
| `/evaluator-health/recalibrate` | POST | Recompute evaluator metrics from human labels |

### Human Review

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/review/queue` | GET | Pending reviews (high-risk + low-confidence traces) |
| `/review/{id}/label` | POST | Submit ground-truth label for evaluator calibration |
| `/drift` | GET | Drift across failure-rate, latency, healing-success |

### Infrastructure

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness probe with version info |

Full interactive API docs at `http://localhost:8000/docs` (Swagger UI).

## Database Schema

### PostgreSQL

```
traces           -- Structured LLM call records with cost, latency, retrieved docs, risk tier
evaluations      -- Ensemble verdicts: 3 evaluator results, agreement count, failure type, severity
rcas             -- Root cause analysis: primary source, findings, analysis summary
healing_actions  -- Repair attempts: strategy, escalation flag, regression result, improvement score
human_reviews    -- Review queue: reason for escalation, reviewer label, timestamps
evaluator_metrics -- Per-evaluator calibration: precision, recall, F1, agreement rate
```

### Redis

```
metrics:pipeline:{window}    -- Cached pipeline aggregates (TTL: 60s)
trace:{id}                   -- Cached trace data (TTL: 600s)
metrics:evaluator_health     -- Cached evaluator calibration (TTL: 120s)
```

## What I Would Change for Production

| Current (Portfolio) | Production Alternative | Why |
|---|---|---|
| OpenAI GPT-4o for evaluation/RCA | Fine-tuned evaluation model + GPT-4o for escalation | Reduce per-trace evaluation cost while maintaining accuracy |
| Llama 3.2 via Ollama (single node) | vLLM cluster with load balancing | Horizontal scaling for high-throughput healing |
| FAISS (in-process) | Qdrant or Pinecone cluster | Distributed fix repository with replication |
| Single PostgreSQL | Read replicas + PgBouncer connection pooling | Handle concurrent trace ingestion at scale |
| Redis cache (single instance) | Redis Sentinel or Cluster | High availability for metric caching |
| Synchronous healing pipeline | Celery/RQ async queue with dead-letter | Non-blocking repair with retry and observability |
| 15 sample traces for demo | Continuous evaluation with production traffic sampling | Catch regressions from real-world failure distribution |
| React SPA | Next.js with SSR | Faster initial load for operational dashboards |

## Skills Demonstrated

### AI Engineering
- Multi-evaluator ensemble with majority voting: LLM judge, embedding similarity, and rule-based engine with fine-grained failure taxonomy
- LangGraph self-healing pipeline with two-stage repair (local Llama draft then GPT-4o escalation), retrieval correction, model rerouting, and context enrichment
- Bayesian strategy selection using Beta-distribution posteriors updated after every healing attempt
- Persistent fix repository via FAISS for similarity-based repair reuse across traces
- Evaluator meta-evaluation: precision/recall/F1 computed from human-labeled ground truth with recalibration endpoint
- Hybrid model routing with task-aware complexity scoring and graceful fallback logging

### Full-Stack Engineering
- FastAPI backend with 30+ Pydantic schemas, async SQLAlchemy ORM, Alembic migrations, and Redis caching
- React dashboard with 9 pages: pipeline health, trace explorer, healing results, evaluator calibration, drift detection, cost/latency analytics, review queue, and admin
- Docker multi-service orchestration (PostgreSQL + Redis + Backend + Frontend) with health checks and entrypoint scripting
- Vite build tooling with API proxy for development and nginx reverse proxy for production

### Systems Thinking
- Safety boundaries: risk-tier traces (financial, legal, medical) are never auto-healed, always routed to human review
- Closed feedback loop: human reviewer labels feed evaluator calibration, improving detection accuracy over time
- Structural failure detection: recurring patterns (>= 3 occurrences of same failure type + source + prompt fingerprint) surfaced for engineering attention
- Drift detection: statistical comparison of failure rate, latency, and healing success vs prior window

### Reliability Engineering
- Ensemble agreement prevents single-evaluator false positives from triggering unnecessary repairs
- Two-stage healing with validation: repairs are only accepted after passing the same ensemble evaluator that detected the original failure
- Bayesian exploration-exploitation: early operation explores strategies broadly, then converges on proven approaches per failure source
- Per-component cost and latency tracking with P50/P90/P99 percentiles for operational visibility

## License

This project is for portfolio and educational purposes. The codebase is authored by **Tommy** and available under the MIT License.

*Built by **Tommy**: production-grade AI engineering combining ensemble evaluation, autonomous self-healing, Bayesian learning, and human-in-the-loop safety. This system doesn't just detect LLM failures; it classifies them, fixes them, validates the fixes, and learns which fixes work best.*
