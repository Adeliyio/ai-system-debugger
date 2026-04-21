from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


# --- Enums ---

class TraceStatus(str, Enum):
    pending = "pending"
    analyzed = "analyzed"
    failed = "failed"
    healed = "healed"


class FailureSource(str, Enum):
    retrieval = "retrieval"
    prompt = "prompt"
    model = "model"
    context = "context"
    unknown = "unknown"


class HealingStrategy(str, Enum):
    prompt_repair = "prompt_repair"
    retrieval_correction = "retrieval_correction"
    model_reroute = "model_reroute"
    context_enrichment = "context_enrichment"


class EvaluatorType(str, Enum):
    llm_judge = "llm_judge"
    embedding_similarity = "embedding_similarity"
    rule_based = "rule_based"


class SeverityLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


# --- Trace Models ---

class TraceCreate(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    prompt: str = Field(..., description="Input prompt sent to the LLM")
    response: str = Field(..., description="LLM-generated response")
    model_used: str = Field(..., description="Model that generated the response")
    context_documents: list[str] = Field(default_factory=list, description="Retrieved context documents")
    latency_ms: float = Field(..., ge=0, description="Response latency in milliseconds")
    token_count_input: int = Field(..., ge=0, description="Input token count")
    token_count_output: int = Field(..., ge=0, description="Output token count")
    metadata: dict = Field(default_factory=dict, description="Additional trace metadata")


class TraceResponse(BaseModel):
    id: str
    session_id: str
    prompt: str
    response: str
    model_used: str
    context_documents: list[str]
    latency_ms: float
    token_count_input: int
    token_count_output: int
    status: TraceStatus
    metadata: dict
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Evaluation Models ---

class EvaluatorVerdict(BaseModel):
    evaluator_type: EvaluatorType
    passed: bool
    score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str


class EvaluationRequest(BaseModel):
    trace_id: str = Field(..., description="ID of the trace to evaluate")
    reference_response: Optional[str] = Field(None, description="Ground truth response for comparison")


class EvaluationResponse(BaseModel):
    id: str
    trace_id: str
    passed: bool
    overall_score: float
    verdicts: list[EvaluatorVerdict]
    agreement_count: int = Field(..., description="Number of evaluators that agree on the verdict")
    failure_detected: bool
    severity: SeverityLevel
    created_at: datetime

    model_config = {"from_attributes": True}


# --- RCA Models ---

class RCARequest(BaseModel):
    trace_id: str
    evaluation_id: str


class RCAFinding(BaseModel):
    source: FailureSource
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str
    suggested_action: str


class RCAResponse(BaseModel):
    id: str
    trace_id: str
    evaluation_id: str
    primary_source: FailureSource
    findings: list[RCAFinding]
    analysis_summary: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Self-Healing Models ---

class HealingRequest(BaseModel):
    trace_id: str
    rca_id: str
    strategy: Optional[HealingStrategy] = Field(None, description="Override automatic strategy selection")


class RegressionResult(BaseModel):
    test_case_id: str
    passed: bool
    original_score: float
    repaired_score: float
    degradation: float


class HealingResponse(BaseModel):
    id: str
    trace_id: str
    rca_id: str
    strategy: HealingStrategy
    original_response: str
    repaired_response: str
    repair_prompt: Optional[str]
    attempt_number: int
    regression_passed: bool
    regression_results: list[RegressionResult]
    improvement_score: float
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Comparison Models ---

class ComparisonRequest(BaseModel):
    trace_id: str
    healing_id: str


class ComparisonResponse(BaseModel):
    trace_id: str
    original_response: str
    repaired_response: str
    original_score: float
    repaired_score: float
    improvement: float
    strategy_used: HealingStrategy
    side_by_side: dict


# --- Metrics Models ---

class MetricsQuery(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    window_hours: int = Field(default=24, ge=1, le=720)


class PipelineMetrics(BaseModel):
    total_traces: int
    failure_rate: float
    mean_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    healing_success_rate: float
    top_failure_sources: dict[FailureSource, int]
    model_usage: dict[str, int]
    traces_by_status: dict[TraceStatus, int]
    period_start: datetime
    period_end: datetime


class EvaluatorHealthResponse(BaseModel):
    evaluator_type: EvaluatorType
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    agreement_rate: float
    total_evaluations: int
    last_calibrated: Optional[datetime]


class DriftMetrics(BaseModel):
    metric_name: str
    current_value: float
    baseline_value: float
    drift_magnitude: float
    is_drifting: bool
    window_days: int
