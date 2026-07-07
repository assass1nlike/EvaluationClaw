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
    pairwise_preference = "pairwise_preference"


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
    win_rate = "win_rate"


class ScaleBudget(str, Enum):
    low = "low"
    mid = "mid"
    high = "high"
    large = "large"
    xlarge = "xlarge"


class SourceKind(str, Enum):
    self_generated = "self_generated"
    web = "web"
    hf_dataset = "hf_dataset"
    lm_eval = "lm_eval"
    imported = "imported"


class BenchmarkMode(str, Enum):
    auto = "auto"
    static = "static"
    agent = "agent"


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
    target_difficulty: Difficulty = Difficulty.L4
    needs_research: bool = False
    research_queries: list[str] = Field(default_factory=list)
    target_item_count: Optional[int] = None
    target_source_backed_count: int = 0
    target_generated_count: Optional[int] = None
    task_types: list[TaskType] = Field(default_factory=list)
    item_requirements: list[str] = Field(default_factory=list)
    # Deprecated compatibility field. New specs should use target_difficulty.
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


class AgentTaskFamily(str, Enum):
    workspace_navigation = "workspace_navigation"
    code_repair = "code_repair"
    repo_issue = "repo_issue"
    shell_debugging = "shell_debugging"
    api_tool_use = "api_tool_use"
    web_research = "web_research"
    data_analysis = "data_analysis"
    multi_turn_delegation = "multi_turn_delegation"
    safety_tool_use = "safety_tool_use"
    custom = "custom"


class AgentEnvironmentType(str, Enum):
    dialogue = "dialogue"
    workspace = "workspace"
    code_sandbox = "code_sandbox"
    docker_workspace = "docker_workspace"


class AgentResource(BaseModel):
    id: str
    kind: str = "web"
    uri: str = ""
    title: str = ""
    license: str = ""
    content_summary: str = ""
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTaskBlueprint(BaseModel):
    id: str
    dimension_id: str
    title: str
    description: str = ""
    task_family: AgentTaskFamily = AgentTaskFamily.custom
    environment_type: AgentEnvironmentType = AgentEnvironmentType.workspace
    expected_task_count: int = 1
    resource_queries: list[str] = Field(default_factory=list)
    source_strategy: str = ""
    tool_requirements: list[str] = Field(default_factory=list)
    construction_requirements: list[str] = Field(default_factory=list)
    scoring_strategy: str = ""


class AgentEnvironmentSpec(BaseModel):
    type: AgentEnvironmentType = AgentEnvironmentType.workspace
    tools: list[dict[str, Any]] = Field(default_factory=list)
    visible_files: dict[str, str] = Field(default_factory=dict)
    hidden_files: dict[str, str] = Field(default_factory=dict)
    image: str = ""
    setup_commands: list[str] = Field(default_factory=list)
    test_command: str = ""
    max_steps: int = 8
    timeout: int = 20
    network: str = "none"
    resource_limits: dict[str, Any] = Field(default_factory=dict)
    workspace: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class AgentScoringSpec(BaseModel):
    method: str = "deterministic"
    instructions: str = ""
    pass_criteria: str = ""
    partial_criteria: str = ""
    fail_criteria: str = ""
    score_levels: dict[str, str] = Field(default_factory=dict)
    oracle_notes: str = ""


class AgentTask(BaseModel):
    id: str
    dimension_id: str
    title: str
    description: str = ""
    task_family: AgentTaskFamily = AgentTaskFamily.custom
    prompt: str
    system_prompt: str = ""
    resource_ids: list[str] = Field(default_factory=list)
    environment: AgentEnvironmentSpec = Field(default_factory=AgentEnvironmentSpec)
    interaction: dict[str, Any] = Field(default_factory=dict)
    scoring: AgentScoringSpec = Field(default_factory=AgentScoringSpec)
    difficulty: Difficulty = Difficulty.L4
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTaskSuite(BaseModel):
    id: str = "agent_task_suite"
    objective: str
    dimensions: list[EvalDimension] = Field(default_factory=list)
    blueprints: list[AgentTaskBlueprint] = Field(default_factory=list)
    resources: list[AgentResource] = Field(default_factory=list)
    tasks: list[AgentTask] = Field(default_factory=list)
    construction_notes: str = ""
    created_at: str = Field(default_factory=utc_now)


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


class BenchmarkBatch(BaseModel):
    id: str
    dimension_id: str
    description: str = ""
    planned_item_count: int = 0
    materialized_item_count: int = 0
    source_backed_target: int = 0
    generated_target: int = 0
    task_types: list[TaskType] = Field(default_factory=list)
    source_strategy: str = ""
    qc_sample_size: int = 0
    notes: str = ""


class BenchmarkDataset(BaseModel):
    spec: EvalSpec
    items: list[BenchmarkItem]
    sources: list[BenchmarkSource] = Field(default_factory=list)
    batches: list[BenchmarkBatch] = Field(default_factory=list)
    agent_task_suite: Optional[AgentTaskSuite] = None
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


class ResearchTaxonomyEntry(BaseModel):
    """A subfield or capability identified during deep research."""

    name: str
    description: str = ""


class ResearchBenchmarkNote(BaseModel):
    """An existing benchmark surfaced during deep research."""

    name: str
    url: str = ""
    known_weaknesses: list[str] = Field(default_factory=list)


class ResearchSeedSource(BaseModel):
    """A groundable document/data URL for the generator."""

    title: str
    url: str = ""
    why_useful: str = ""


class ResearchExemplarItem(BaseModel):
    """A representative example item for the researched domain."""

    prompt: str
    answer: str = ""
    notes: str = ""


class ResearchCitation(BaseModel):
    """A claim-to-source mapping backing brief conclusions."""

    claim: str
    url: str = ""


class ResearchBrief(BaseModel):
    """Structured output of the deep-research loop.

    All fields are optional with defaults so partial briefs validate.
    """

    field_overview: str = ""
    taxonomy: list[ResearchTaxonomyEntry] = Field(default_factory=list)
    existing_benchmarks: list[ResearchBenchmarkNote] = Field(default_factory=list)
    seed_sources: list[ResearchSeedSource] = Field(default_factory=list)
    exemplar_items: list[ResearchExemplarItem] = Field(default_factory=list)
    difficulty_anchors: dict[str, str] = Field(default_factory=dict)  # L1-L5 -> meaning
    citations: list[ResearchCitation] = Field(default_factory=list)
    research_notes: str = ""
    created_at: str = Field(default_factory=utc_now)


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
    research_brief: Optional[ResearchBrief] = None
    created_at: str = Field(default_factory=utc_now)


class BenchmarkConfig(BaseModel):
    benchmark_mode: BenchmarkMode = BenchmarkMode.auto
    orchestrator_model: str = "claude-opus-4-6"
    orchestrator_api_key: Optional[str] = None
    orchestrator_base_url: Optional[str] = None
    task_agent_model: Optional[str] = None
    task_agent_api_key: Optional[str] = None
    task_agent_base_url: Optional[str] = None
    targets: list[TargetModelConfig] = Field(default_factory=list)
    reference_model: Optional[TargetModelConfig] = None
    scale_budget: ScaleBudget = ScaleBudget.mid
    questions_per_dimension: int = 5
    max_planner_iterations: int = 5
    max_qc_iterations: int = 3
    max_research_sources: int = 3
    max_hf_records_per_dimension: int = 1
    large_scale_generated_item_cap_per_dimension: int = 50
    large_scale_min_source_backed_ratio: float = 0.8
    large_scale_llm_qc_sample_size: int = 120
    output_dir: str = "./benchmark-output"
    run_targets: bool = True
    use_web_research: bool = True
    search_backend: str = "auto"  # auto | gemini | keyless | none
    use_deep_research: bool = False
    max_research_iterations: int = 3
    research_brief: Optional[ResearchBrief] = None
    use_hf_discovery: bool = True
    judge_double_pass: bool = True
    llm_backend: str = "auto"  # auto | litellm | legacy
    runner: str = "direct"  # direct | lm-eval | auto
    environment_claw: bool = True
    environment_claw_auto_configure: bool = True
    human_review: bool = False
    improve_iterations: int = 0
    loop3_diagnosis: str = "llm"  # llm | local
    loop3_diagnosis_timeout_s: int = 90
    loop3_max_actions: int = 4
    swebench_use_wsl: bool = False
    swebench_wsl_distro: Optional[str] = None
    swebench_wsl_python_executable: str = ".venv-swebench-wsl/bin/python"
    swebench_wsl_docker_host: str = "unix:///mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.proxy.sock"
    swebench_wsl_docker_cli_dir: str = "/mnt/wsl/docker-desktop/cli-tools/usr/bin"
    swebench_wsl_http_proxy: Optional[str] = None
    swebench_python_executable: str = "python"
    swebench_docker_executable: str = "docker"
    swebench_dataset_name: str = "princeton-nlp/SWE-bench_Lite"
    swebench_split: str = "test"
    swebench_predictions_path: str = "gold"


# Backwards-compatible aliases for older scripts that import these names.
QuestionType = TaskType
Complexity = Difficulty
Question = BenchmarkItem
TestDimension = EvalDimension
ModelResponse = ItemResult
