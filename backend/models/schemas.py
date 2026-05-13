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
    awaiting_review = "awaiting_review"


class FailureSource(str, Enum):
    retrieval = "retrieval"
    prompt = "prompt"
    model = "model"
    context = "context"
    unknown = "unknown"


class FailureType(str, Enum):
    """Fine-grained failure type emitted by the ensemble evaluator."""
    none = "none"
    hallucination = "hallucination"
    retrieval_failure = "retrieval_failure"
    context_loss = "context_loss"
    reasoning_failure = "reasoning_failure"
    prompt_failure = "prompt_failure"


class RiskTier(str, Enum):
    """Risk classification used to gate self-healing automation."""
    general = "general"
    financial = "financial"
    legal = "legal"
    medical = "medical"


class HealingStrategy(str, Enum):
    prompt_repair = "prompt_repair"
    retrieval_correction = "retrieval_correction"
    model_reroute = "model_reroute"
    context_enrichment = "context_enrichment"
    manual_review = "manual_review"


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

class RetrievedDocument(BaseModel):
    """Single retrieved document with similarity score."""
    id: str
    content: str
    similarity_score: float = Field(0.0, ge=0.0, le=1.0)


class LatencyBreakdown(BaseModel):
    """Per-component latency breakdown for a trace (milliseconds)."""
    preprocessing_ms: float = 0.0
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    evaluation_ms: float = 0.0


class CostBreakdown(BaseModel):
    """Itemized cost per trace (USD)."""
    model_config = {"protected_namespaces": ()}
    input_tokens: int = 0
    output_tokens: int = 0
    model_cost_usd: float = 0.0
    evaluation_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


class TraceCreate(BaseModel):
    model_config = {"protected_namespaces": ()}

    session_id: str = Field(..., description="Unique session identifier")
    prompt: str = Field(..., description="Input prompt sent to the LLM")
    response: str = Field(..., description="LLM-generated response")
    model_used: str = Field(..., description="Model that generated the response")
    context_documents: list[str] = Field(
        default_factory=list,
        description="Retrieved context documents (legacy flat shape; prefer retrieved_docs)",
    )
    retrieved_docs: Optional[list[RetrievedDocument]] = Field(
        None,
        description="Retrieved documents with similarity scores. If absent, derived from context_documents.",
    )
    latency_ms: float = Field(..., ge=0, description="Response latency in milliseconds")
    latency_breakdown: Optional[LatencyBreakdown] = Field(
        None, description="Per-component latency breakdown"
    )
    token_count_input: int = Field(..., ge=0, description="Input token count")
    token_count_output: int = Field(..., ge=0, description="Output token count")
    cost: Optional[CostBreakdown] = Field(None, description="Itemized cost (USD)")
    task_type: Optional[str] = Field(None, description="Routing task type (evaluation, rca, ...)")
    complexity_score: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Routing complexity score"
    )
    routing_fallback: bool = Field(
        False, description="True if model fell back from primary to local model"
    )
    risk_tier: RiskTier = Field(
        RiskTier.general,
        description="Risk classification. Non-general tiers disable automated healing.",
    )
    metadata: dict = Field(default_factory=dict, description="Additional trace metadata")


class TraceResponse(BaseModel):
    model_config = {"from_attributes": True, "protected_namespaces": ()}

    id: str
    session_id: str
    prompt: str
    response: str
    model_used: str
    context_documents: list[str]
    retrieved_docs: list[RetrievedDocument] = Field(default_factory=list)
    latency_ms: float
    latency_breakdown: Optional[LatencyBreakdown] = None
    token_count_input: int
    token_count_output: int
    cost: Optional[CostBreakdown] = None
    task_type: Optional[str] = None
    complexity_score: Optional[float] = None
    routing_fallback: bool = False
    risk_tier: RiskTier = RiskTier.general
    status: TraceStatus
    metadata: dict
    created_at: datetime


# --- Evaluation Models ---

class EvaluatorVerdict(BaseModel):
    evaluator_type: EvaluatorType
    passed: bool
    score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    failure_type: FailureType = FailureType.none


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
    failure_type: FailureType = FailureType.none
    severity: SeverityLevel
    low_confidence: bool = False
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
    escalated_to_openai: bool = False
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
    model_config = {"protected_namespaces": ()}

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


class CostMetrics(BaseModel):
    """Aggregate cost metrics over a window."""
    model_config = {"protected_namespaces": ()}
    total_cost_usd: float
    model_cost_usd: float
    evaluation_cost_usd: float
    cost_per_trace: float
    cost_by_model: dict[str, float]
    period_start: datetime
    period_end: datetime


class LatencyComponentMetric(BaseModel):
    """Per-component latency percentiles."""
    component: str  # preprocessing | retrieval | generation | evaluation
    p50_ms: float
    p90_ms: float
    p99_ms: float
    sample_count: int


class LatencyMetricsResponse(BaseModel):
    components: list[LatencyComponentMetric]
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


# --- Human-in-the-loop ---

class HumanReviewItem(BaseModel):
    id: str
    trace_id: str
    evaluation_id: Optional[str]
    reason: str  # "low_confidence" | "high_risk" | "structural_failure"
    severity: SeverityLevel
    risk_tier: RiskTier
    created_at: datetime
    label: Optional[FailureType] = None
    resolved_at: Optional[datetime] = None
    notes: Optional[str] = None

    model_config = {"from_attributes": True}


class HumanReviewLabel(BaseModel):
    label: FailureType
    notes: Optional[str] = None
    reviewer: Optional[str] = None


# --- Structural failure ---

class StructuralFailureCluster(BaseModel):
    id: str
    failure_type: FailureType
    primary_source: FailureSource
    prompt_fingerprint: str
    occurrence_count: int
    last_seen: datetime
    sample_prompt: str

    model_config = {"from_attributes": True}
