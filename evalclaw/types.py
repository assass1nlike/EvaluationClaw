"""EvaluationClaw shared data models.

The models describe the product architecture from the design doc:
natural-language goal -> structured eval spec -> benchmark dataset -> QC gate
-> multi-model run -> report package.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class TaskType(str, Enum):
    yes_no = "yes_no"
    multiple_choice = "multiple_choice"
    short_answer = "short_answer"
    open_generation = "open_generation"
    code_execution = "code_execution"
    multi_turn = "multi_turn"
    agent_interaction = "agent_interaction"


class Difficulty(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class Metric(str, Enum):
    accuracy = "accuracy"
    exact_match = "exact_match"
    judge_score = "judge_score"
    pass_at_1 = "pass@1"


class ScaleBudget(str, Enum):
    low = "low"
    mid = "mid"
    high = "high"


class SourceKind(str, Enum):
    self_generated = "self_generated"
    web = "web"
    hf_dataset = "hf_dataset"
    lm_eval = "lm_eval"
    imported = "imported"


class QcSeverity(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"


class QcCategory(str, Enum):
    schema = "schema"
    duplicate = "duplicate"
    scoring = "scoring"
    clarity = "clarity"
    coverage = "coverage"
    difficulty = "difficulty"


class Message(BaseModel):
    role: str
    content: str


class PlannerChecklist(BaseModel):
    objective: bool = False
    subjects: bool = False
    format: bool = False
    content: bool = False
    scale: bool = False
    metrics: bool = False


class PlannerCritique(BaseModel):
    checklist: PlannerChecklist = Field(default_factory=PlannerChecklist)
    score: float = 0.0
    missing_items: list[str] = Field(default_factory=list)
    notes: str = ""

    @property
    def passed(self) -> bool:
        checks = self.checklist.model_dump().values()
        return all(checks) and self.score >= 4.0


class EvalDimension(BaseModel):
    id: str
    name: str
    description: str
    approach: str
    weight: float = 1.0
    needs_research: bool = False
    research_queries: list[str] = Field(default_factory=list)
    difficulty_distribution: dict[Difficulty, float] = Field(default_factory=dict)


class EvalSpec(BaseModel):
    id: str = "evalclaw_spec"
    objective: str
    subjects: list[str] = Field(default_factory=list)
    task_types: list[TaskType] = Field(default_factory=lambda: [TaskType.open_generation])
    dimensions: list[EvalDimension] = Field(default_factory=list)
    scale_budget: ScaleBudget = ScaleBudget.mid
    scale: int = 20
    metrics: list[Metric] = Field(default_factory=lambda: [Metric.judge_score])
    constraints: list[str] = Field(default_factory=list)
    planner_notes: str = ""
    critique: PlannerCritique = Field(default_factory=PlannerCritique)


class BenchmarkSource(BaseModel):
    kind: SourceKind
    uri: str = ""
    title: str = ""
    notes: str = ""


class BenchmarkItem(BaseModel):
    id: str
    dimension_id: str
    task_type: TaskType
    prompt: str
    choices: list[str] = Field(default_factory=list)
    answer: Optional[str] = None
    rubric: Optional[str] = None
    test_code: Optional[str] = None
    difficulty: Difficulty = Difficulty.L3
    source: BenchmarkSource = Field(
        default_factory=lambda: BenchmarkSource(kind=SourceKind.self_generated)
    )
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BenchmarkDataset(BaseModel):
    spec: EvalSpec
    items: list[BenchmarkItem]
    sources: list[BenchmarkSource] = Field(default_factory=list)
    generation_notes: str = ""
    created_at: str = Field(default_factory=utc_now)


class QcIssue(BaseModel):
    item_id: Optional[str] = None
    severity: QcSeverity
    category: QcCategory
    message: str
    suggested_action: str = ""


class QcReport(BaseModel):
    issues: list[QcIssue] = Field(default_factory=list)
    passed_item_ids: list[str] = Field(default_factory=list)
    rejected_item_ids: list[str] = Field(default_factory=list)
    quality_score: float = 1.0
    summary: str = ""

    @property
    def is_acceptable(self) -> bool:
        hard_failures = [i for i in self.issues if i.severity == QcSeverity.error]
        return not hard_failures and self.quality_score >= 0.8


class TargetModelConfig(BaseModel):
    id: str = ""
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None

    @model_validator(mode="after")
    def fill_default_id(self) -> "TargetModelConfig":
        if not self.id:
            self.id = self.model.replace("/", "_").replace(":", "_")
        return self


class ItemResult(BaseModel):
    item_id: str
    target_id: str
    raw_response: str = ""
    score: float = 0.0
    judge_reasoning: Optional[str] = None
    error: Optional[str] = None
    latency_ms: Optional[int] = None


class TargetSummary(BaseModel):
    target_id: str
    model: str
    average_score: float = 0.0
    score_by_dimension: dict[str, float] = Field(default_factory=dict)
    score_by_task_type: dict[str, float] = Field(default_factory=dict)
    total_items: int = 0
    errors: int = 0


class EvalRun(BaseModel):
    dataset: BenchmarkDataset
    qc_report: QcReport
    results: list[ItemResult] = Field(default_factory=list)
    summaries: list[TargetSummary] = Field(default_factory=list)
    runner_artifacts: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class ImprovementAction(BaseModel):
    action_type: str
    dimension_id: Optional[str] = None
    item_id: Optional[str] = None
    reason: str
    guidance: str


class ImprovementIteration(BaseModel):
    iteration: int
    actions: list[ImprovementAction] = Field(default_factory=list)
    dataset: Optional[BenchmarkDataset] = None
    qc_report: Optional[QcReport] = None
    run: Optional[EvalRun] = None
    notes: str = ""


class EvalReport(BaseModel):
    title: str
    markdown: str
    summaries: list[TargetSummary]
    recommendations: list[str] = Field(default_factory=list)


class BenchmarkPackage(BaseModel):
    goal: str
    spec: EvalSpec
    dataset: BenchmarkDataset
    qc_report: QcReport
    run: EvalRun
    improvements: list[ImprovementIteration] = Field(default_factory=list)
    report: EvalReport
    created_at: str = Field(default_factory=utc_now)


class BenchmarkConfig(BaseModel):
    orchestrator_model: str = "claude-opus-4-6"
    orchestrator_api_key: Optional[str] = None
    orchestrator_base_url: Optional[str] = None
    targets: list[TargetModelConfig] = Field(default_factory=list)
    scale_budget: ScaleBudget = ScaleBudget.mid
    questions_per_dimension: int = 5
    max_planner_iterations: int = 5
    max_qc_iterations: int = 3
    max_research_sources: int = 3
    max_hf_records_per_dimension: int = 1
    output_dir: str = "./benchmark-output"
    run_targets: bool = True
    use_web_research: bool = True
    use_hf_discovery: bool = True
    judge_double_pass: bool = True
    llm_backend: str = "auto"  # auto | litellm | legacy
    runner: str = "direct"  # direct | lm-eval | auto
    improve_iterations: int = 0
    loop3_diagnosis: str = "llm"  # llm | local
    loop3_diagnosis_timeout_s: int = 90
    loop3_max_actions: int = 4


# Backwards-compatible aliases for older scripts that import these names.
QuestionType = TaskType
Complexity = Difficulty
Question = BenchmarkItem
TestDimension = EvalDimension
ModelResponse = ItemResult
