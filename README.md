# AI System Debugger

A production-grade reliability layer for LLM systems — monitoring pipelines in real time, diagnosing failures with semantic precision, and autonomously applying validated fixes.

## Overview

AI systems fail differently from traditional software. An LLM can return something that looks correct, sounds fluent, and is completely wrong — while standard monitoring tools have no idea. This system is built for that gap.

**Key capabilities:**
- **Instrumentation** — Captures every AI call as a structured trace with full context
- **Semantic Monitoring** — Tracks output consistency, context utilization, confidence, and inter-turn coherence
- **Failure Detection** — Ensemble evaluation (LLM-as-judge + embedding similarity + rule-based validators) with majority agreement
- **Root Cause Analysis** — Diagnoses whether failures originate from retrieval, prompt design, model limitations, or missing context
- **Self-Healing** — Applies targeted fixes (prompt repair, retrieval correction, model rerouting) with guardrails and regression testing
- **Meta-Evaluation** — Measures the reliability of the evaluator itself against human-labeled ground truth

## Architecture

### Hybrid Model Routing
- **High-reasoning tasks** (evaluation, RCA, prompt repair) → OpenAI GPT-4o
- **Lightweight tasks** (preprocessing, filtering, drift aggregation) → Llama 3.2 (local)
- Task-aware routing with complexity scoring and automatic fallback

### Tech Stack

| Layer | Technologies |
|---|---|
| Backend | Python, FastAPI |
| Instrumentation | OpenTelemetry, custom middleware |
| LLM (reasoning) | OpenAI GPT-4o |
| LLM (lightweight) | Llama 3.2 (local) |
| Evaluation | LLM-as-judge, sentence-transformers, rule engine |
| Self-Healing | LangGraph, FAISS |
| Storage | PostgreSQL, Redis |
| Experiment Tracking | Weights & Biases |
| Frontend | React, Tailwind CSS, Recharts |

## Project Structure

```
ai-system-debugger/
├── backend/
│   ├── api/              # FastAPI routes
│   ├── core/             # Config, settings, dependencies
│   ├── models/           # Pydantic models and schemas
│   ├── services/         # Business logic
│   │   ├── instrumentation/   # Trace capture
│   │   ├── monitoring/        # Real-time metrics
│   │   ├── evaluation/        # Failure detection engine
│   │   ├── rca/               # Root cause analysis
│   │   ├── healing/           # Self-healing engine
│   │   └── routing/           # Model routing logic
│   ├── storage/          # Database and cache layers
│   └── main.py           # Application entry point
├── frontend/             # React dashboard
├── tests/                # Test suite
├── data/                 # Sample traces and evaluation datasets
└── docs/                 # Documentation
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/trace` | POST | Submit an AI interaction trace |
| `/analyze` | POST | Analyze a trace for failures |
| `/fix` | POST | Apply self-healing fix |
| `/compare` | POST | Compare original vs repaired output |
| `/metrics` | GET | Pipeline metrics over time range |
| `/evaluator-health` | GET | Evaluator reliability metrics |

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+
- Redis 7+

### Installation

```bash
# Clone the repository
git clone https://github.com/Adeliyio/ai-system-debugger.git
cd ai-system-debugger

# Backend setup
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Frontend setup
cd frontend
npm install
```

### Running

```bash
# Start backend
uvicorn backend.main:app --reload

# Start frontend (in another terminal)
cd frontend
npm start
```

## License

MIT
