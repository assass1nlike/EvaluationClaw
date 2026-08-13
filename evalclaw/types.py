"""EvaluationClaw shared data models.

The models describe the product architecture from the design doc:
natural-language goal -> skill-driven benchmark plan -> benchmark dataset ->
QC gate -> optional multi-model run -> report package.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class TaskType(str, Enum):
    choice = "choice"
    fill_blank = "fill_blank"
    generation = "generation"
    multi_turn = "multi_turn"
    agent = "agent"


JUDGE_TOOL_NAMES = frozenset({"python_tests"})


class ChallengeEffort(str, Enum):
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"


def safe_challenge_effort(value: object, fallback: ChallengeEffort = ChallengeEffort.E3) -> ChallengeEffort:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return ChallengeEffort(text.upper())
    except ValueError:
        return fallback


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
    challenge_effort = "challenge_effort"


class Message(BaseModel):
    role: str
    content: str


class PlannerChecklist(BaseModel):
    objective: bool = False
    subjects: bool = False
    format: bool = False
    content: bool = False
    scale: bool = False


class PlannerCritique(BaseModel):
    checklist: PlannerChecklist = Field(default_factory=PlannerChecklist)
    score: float = 0.0
    missing_items: list[str] = Field(default_factory=list)
    notes: str = ""

    @property
    def passed(self) -> bool:
        checks = self.checklist.model_dump().values()
        return all(checks) and self.score >= 4.0


class TaskTypeAllocation(BaseModel):
    task_type: TaskType
    count: int = Field(ge=1)


class EvalDimension(BaseModel):
    id: str
    name: str
    measurement_target: str = ""
    boundary: str = ""
    description: str
    approach: str
    weight: float = 1.0
    challenge_effort: ChallengeEffort = ChallengeEffort.E3
    needs_research: bool = False
    research_queries: list[str] = Field(default_factory=list)
    target_item_count: Optional[int] = None
    target_source_backed_count: int = 0
    target_generated_count: Optional[int] = None
    task_types: list[TaskType] = Field(default_factory=list)
    task_type_allocation: list[TaskTypeAllocation] = Field(default_factory=list)
    item_requirements: list[str] = Field(default_factory=list)
    challenge_effort_distribution: dict[ChallengeEffort, float] = Field(default_factory=dict)


class EvalSpec(BaseModel):
    id: str = "evalclaw_spec"
    objective: str
    subjects: list[str] = Field(default_factory=list)
    task_types: list[TaskType] = Field(default_factory=lambda: [TaskType.generation])
    dimensions: list[EvalDimension] = Field(default_factory=list)
    scale_budget: ScaleBudget = ScaleBudget.mid
    scale: int = 20
    constraints: list[str] = Field(default_factory=list)
    planner_notes: str = ""
    critique: PlannerCritique = Field(default_factory=PlannerCritique)


class BenchmarkSource(BaseModel):
    kind: SourceKind
    uri: str = ""
    title: str = ""
    notes: str = ""


class AgentEnvironmentType(str, Enum):
    workspace = "workspace"
    code_sandbox = "code_sandbox"
    docker_workspace = "docker_workspace"
    gui_desktop = "gui_desktop"


class TaskResource(BaseModel):
    id: str
    kind: str = "web"
    uri: str = ""
    title: str = ""
    license: str = ""
    content_summary: str = ""
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChoiceOption(BaseModel):
    id: str
    text: str


class JudgeToolRef(BaseModel):
    tool: str
    config: dict[str, Any] = Field(default_factory=dict)


class BlueprintSourcePlan(BaseModel):
    strategy: str = "self_contained"
    search_queries: list[str] = Field(default_factory=list)
    suggested_urls: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)


class TaskDesign(BaseModel):
    """Planner-authored design for one task or a group of similar tasks."""

    model_config = ConfigDict(extra="forbid")

    id: str
    task_type: TaskType
    task_count: int = Field(ge=1)
    challenge_effort: ChallengeEffort = ChallengeEffort.E3
    content_design: dict[str, Any] = Field(default_factory=dict)
    input_requirements: dict[str, Any] = Field(default_factory=dict)
    interaction_requirements: dict[str, Any] = Field(default_factory=dict)
    environment_requirements: dict[str, Any] = Field(default_factory=dict)
    output_requirements: dict[str, Any] = Field(default_factory=dict)
    scoring_contract: dict[str, Any] = Field(default_factory=dict)
    source_plan: dict[str, Any] = Field(default_factory=dict)
    construction_requirements: list[str] = Field(default_factory=list)
    type_specific_requirements: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def description(self) -> str:
        return str(
            self.content_design.get("description")
            or self.content_design.get("purpose")
            or ""
        )


class TaskBlueprint(BaseModel):
    """Compatibility record for one framework-derived Task Builder job.

    New plans create exactly one record per TaskDesign. The legacy name and
    grouping fields remain only for loading existing datasets.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    dimension_id: str = ""
    title: str
    task_design_ids: list[str] = Field(default_factory=list)
    task_designs: list[TaskDesign] = Field(default_factory=list)
    grouping_rationale: str = ""
    workload_reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def planned_task_count(self) -> int:
        return sum(design.task_count for design in self.task_designs)

    @property
    def task_type_allocation(self) -> list[TaskTypeAllocation]:
        counts: dict[TaskType, int] = {}
        for design in self.task_designs:
            counts[design.task_type] = counts.get(design.task_type, 0) + design.task_count
        return [
            TaskTypeAllocation(task_type=task_type, count=count)
            for task_type, count in counts.items()
        ]

    @property
    def description(self) -> str:
        return "; ".join(design.description for design in self.task_designs if design.description)

    @property
    def source_plan(self) -> BlueprintSourcePlan:
        strategies: list[str] = []
        queries: list[str] = []
        urls: list[str] = []
        requirements: list[str] = []
        for design in self.task_designs:
            source = design.source_plan
            strategy = str(source.get("strategy") or "").strip()
            if strategy:
                strategies.append(strategy)
            queries.extend(str(item) for item in source.get("search_queries", []) if item)
            urls.extend(str(item) for item in source.get("suggested_urls", []) if item)
            requirements.extend(str(item) for item in source.get("requirements", []) if item)
        unique_strategies = list(dict.fromkeys(strategies))
        return BlueprintSourcePlan(
            strategy=(unique_strategies[0] if len(unique_strategies) == 1 else "mixed"),
            search_queries=list(dict.fromkeys(queries)),
            suggested_urls=list(dict.fromkeys(urls)),
            requirements=list(dict.fromkeys(requirements)),
        )

    @property
    def construction_requirements(self) -> list[str]:
        return list(
            dict.fromkeys(
                requirement
                for design in self.task_designs
                for requirement in design.construction_requirements
            )
        )

    @property
    def scoring_strategy(self) -> str:
        contracts = [design.scoring_contract for design in self.task_designs if design.scoring_contract]
        return json.dumps(contracts, ensure_ascii=False) if contracts else ""

    @property
    def environment_type(self) -> Optional[AgentEnvironmentType]:
        aliases = {
            "workspace": AgentEnvironmentType.workspace,
            "code_sandbox": AgentEnvironmentType.code_sandbox,
            "code sandbox": AgentEnvironmentType.code_sandbox,
            "container": AgentEnvironmentType.docker_workspace,
            "docker_workspace": AgentEnvironmentType.docker_workspace,
            "browser": AgentEnvironmentType.gui_desktop,
            "desktop": AgentEnvironmentType.gui_desktop,
            "gui_desktop": AgentEnvironmentType.gui_desktop,
        }
        categories = {
            aliases[str(design.environment_requirements.get("category") or "").strip().lower()]
            for design in self.task_designs
            if str(design.environment_requirements.get("category") or "").strip().lower()
            in aliases
        }
        return next(iter(categories)) if len(categories) == 1 else None

    @property
    def requires_environment(self) -> bool:
        return any(design.environment_requirements for design in self.task_designs)

    @property
    def environment_requirements(self) -> dict[str, Any]:
        environments = [
            design.environment_requirements
            for design in self.task_designs
            if design.environment_requirements
        ]
        return environments[0] if len(environments) == 1 else {}

    @property
    def tool_requirements(self) -> list[str]:
        return list(
            dict.fromkeys(
                str(tool)
                for design in self.task_designs
                for tool in design.interaction_requirements.get(
                    "allowed_action_or_tool_categories", []
                )
                if tool
            )
        )

    @property
    def resource_queries(self) -> list[str]:
        return self.source_plan.search_queries

    @property
    def source_strategy(self) -> str:
        return self.source_plan.strategy


class BenchmarkPlanAudit(BaseModel):
    passed: bool = False
    issues: list[str] = Field(default_factory=list)
    coverage_summary: str = ""
    workload_summary: str = ""


class BenchmarkPlanDimension(BaseModel):
    """One Planner-owned measurement dimension and its task designs."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    measurement_target: str
    boundary: str
    approach: str
    task_designs: list[TaskDesign] = Field(default_factory=list)


class BenchmarkPlan(BaseModel):
    """Planner output containing suite-wide intent and TaskDesigns."""

    model_config = ConfigDict(extra="forbid")

    id: str = "evalclaw_plan"
    objective: str
    constraints: list[str] = Field(default_factory=list)
    planner_notes: str = ""
    dimensions: list[BenchmarkPlanDimension] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list, exclude=True)
    scale_budget: ScaleBudget = Field(default=ScaleBudget.mid, exclude=True)
    audit: BenchmarkPlanAudit = Field(default_factory=BenchmarkPlanAudit, exclude=True)

    @property
    def builder_jobs(self) -> list[TaskBlueprint]:
        """Derive one Task Builder call per Planner-authored TaskDesign."""
        jobs: list[TaskBlueprint] = []
        for dimension in self.dimensions:
            for design in dimension.task_designs:
                jobs.append(
                    TaskBlueprint(
                        id=f"{dimension.id}__{design.id}",
                        dimension_id=dimension.id,
                        title=design.description or design.id,
                        task_design_ids=[design.id],
                        task_designs=[design],
                        metadata={"derived_from_task_design": True},
                    )
                )
        return jobs

    @property
    def blueprints(self) -> list[TaskBlueprint]:
        """Backward-compatible alias for framework-derived builder jobs."""
        return self.builder_jobs

    def to_eval_spec(self) -> EvalSpec:
        """Derive the dataset-level evaluation metadata used after planning."""
        dimensions: list[EvalDimension] = []
        all_task_types: list[TaskType] = []
        for dimension in self.dimensions:
            allocations: dict[TaskType, int] = {}
            queries: list[str] = []
            source_backed_count = 0
            efforts: dict[ChallengeEffort, int] = {}
            for design in dimension.task_designs:
                allocations[design.task_type] = allocations.get(design.task_type, 0) + design.task_count
                efforts[design.challenge_effort] = efforts.get(design.challenge_effort, 0) + design.task_count
                queries.extend(
                    str(item) for item in design.source_plan.get("search_queries", []) if item
                )
                if str(design.source_plan.get("strategy") or "") in {
                    "source_backed",
                    "imported_dataset",
                    "mixed",
                }:
                    source_backed_count += design.task_count
            task_types = list(allocations)
            all_task_types.extend(task_types)
            count = sum(allocations.values())
            highest_effort = max(efforts, key=lambda effort: int(effort.value[1:]))
            dimensions.append(
                EvalDimension(
                    id=dimension.id,
                    name=dimension.name,
                    measurement_target=dimension.measurement_target,
                    boundary=dimension.boundary,
                    description=dimension.measurement_target,
                    approach=dimension.approach,
                    challenge_effort=highest_effort,
                    needs_research=bool(queries or source_backed_count),
                    research_queries=list(dict.fromkeys(queries)),
                    target_item_count=count,
                    target_source_backed_count=source_backed_count,
                    target_generated_count=count - source_backed_count,
                    task_types=task_types,
                    task_type_allocation=[
                        TaskTypeAllocation(task_type=task_type, count=task_count)
                        for task_type, task_count in allocations.items()
                    ],
                    challenge_effort_distribution={
                        effort: effort_count / count for effort, effort_count in efforts.items()
                    },
                )
            )
        return EvalSpec(
            id=self.id,
            objective=self.objective,
            subjects=self.subjects,
            task_types=list(dict.fromkeys(all_task_types)),
            dimensions=dimensions,
            scale_budget=self.scale_budget,
            scale=sum(design.task_count for dim in self.dimensions for design in dim.task_designs),
            constraints=self.constraints,
            planner_notes=self.planner_notes,
        )


class AgentEnvironmentSpec(BaseModel):
    type: AgentEnvironmentType = AgentEnvironmentType.workspace
    tools: list[dict[str, Any]] = Field(default_factory=list)
    visible_files: dict[str, str] = Field(default_factory=dict)
    runtime_files: dict[str, str] = Field(default_factory=dict)
    hidden_files: dict[str, str] = Field(default_factory=dict)
    image: str = ""
    auto_select_image: bool = True
    image_selection: dict[str, Any] = Field(default_factory=dict)
    image_build: dict[str, Any] = Field(default_factory=dict)
    pull_image: bool = True
    pull_timeout: int = 300
    setup_commands: list[str] = Field(default_factory=list)
    test_command: str = ""
    max_steps: int = 8
    timeout: int = 20
    network: str = "none"
    resource_limits: dict[str, Any] = Field(default_factory=dict)
    workdir: str = "/workspace"
    workspace: dict[str, Any] = Field(default_factory=dict)
    browser: dict[str, Any] = Field(default_factory=dict)
    bridge_url: str = ""
    bridge_api_key: Optional[str] = None
    requires_vm: bool = False
    vm_provider_url: str = ""
    vm_provider_api_key: Optional[str] = None
    vm: dict[str, Any] = Field(default_factory=dict)
    vm_materialization: dict[str, Any] = Field(default_factory=dict)
    vm_provisioning: dict[str, Any] = Field(default_factory=dict)
    session: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class TaskScoringSpec(BaseModel):
    method: str = "deterministic"
    instructions: str = ""
    pass_criteria: str = ""
    partial_criteria: str = ""
    fail_criteria: str = ""
    score_levels: dict[str, str] = Field(default_factory=dict)
    oracle_notes: str = ""


class TaskDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dimension_id: str
    task_type: TaskType
    title: str
    content_summary: str = ""
    description: str = ""
    prompt: str
    choices: list[ChoiceOption] = Field(default_factory=list)
    correct_choice_ids: list[str] = Field(default_factory=list)
    expected_text: Optional[str] = None
    rubric: Optional[str] = None
    judge_tools: list[JudgeToolRef] = Field(default_factory=list)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str = ""
    resource_ids: list[str] = Field(default_factory=list)
    environment: Optional[AgentEnvironmentSpec] = None
    interaction: dict[str, Any] = Field(default_factory=dict)
    scoring: TaskScoringSpec = Field(default_factory=TaskScoringSpec)
    challenge_effort: ChallengeEffort = ChallengeEffort.E3
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)



class TaskSuite(BaseModel):
    id: str = "task_suite"
    objective: str
    dimensions: list[EvalDimension] = Field(default_factory=list)
    blueprints: list[TaskBlueprint] = Field(default_factory=list)
    resources: list[TaskResource] = Field(default_factory=list)
    tasks: list[TaskDefinition] = Field(default_factory=list)
    construction_notes: str = ""
    created_at: str = Field(default_factory=utc_now)

    @property
    def builder_jobs(self) -> list[TaskBlueprint]:
        return self.blueprints


class BenchmarkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dimension_id: str
    task_type: TaskType
    prompt: str
    choices: list[ChoiceOption] = Field(default_factory=list)
    correct_choice_ids: list[str] = Field(default_factory=list)
    expected_text: Optional[str] = None
    rubric: Optional[str] = None
    judge_tools: list[JudgeToolRef] = Field(default_factory=list)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    challenge_effort: ChallengeEffort = ChallengeEffort.E2
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
    plan: Optional[BenchmarkPlan] = Field(default=None, exclude=True)
    items: list[BenchmarkItem]
    blueprints: list[TaskBlueprint] = Field(default_factory=list)
    sources: list[BenchmarkSource] = Field(default_factory=list)
    batches: list[BenchmarkBatch] = Field(default_factory=list)
    task_suite: Optional[TaskSuite] = None
    generation_notes: str = ""
    created_at: str = Field(default_factory=utc_now)

    @property
    def builder_jobs(self) -> list[TaskBlueprint]:
        return self.blueprints


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
        return not hard_failures and not self.rejected_item_ids


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


class ResearchSourceMaterial(BaseModel):
    """Readable source text retained from deep research for later task construction."""

    title: str = ""
    url: str
    query: str = ""
    content: str


class ResearchBrief(BaseModel):
    """Structured output of the deep-research loop.

    All fields are optional with defaults so partial briefs validate.
    """

    field_overview: str = ""
    taxonomy: list[ResearchTaxonomyEntry] = Field(default_factory=list)
    existing_benchmarks: list[ResearchBenchmarkNote] = Field(default_factory=list)
    seed_sources: list[ResearchSeedSource] = Field(default_factory=list)
    exemplar_items: list[ResearchExemplarItem] = Field(default_factory=list)
    challenge_effort_anchors: dict[ChallengeEffort, str] = Field(default_factory=dict)
    citations: list[ResearchCitation] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    source_materials: list[ResearchSourceMaterial] = Field(default_factory=list)
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
    dataset: BenchmarkDataset = Field(exclude=True)
    qc_report: QcReport = Field(exclude=True)
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
    plan: Optional[BenchmarkPlan] = None
    dataset: BenchmarkDataset
    qc_report: QcReport
    run: EvalRun
    improvements: list[ImprovementIteration] = Field(default_factory=list)
    report: EvalReport
    research_brief: Optional[ResearchBrief] = None
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def hydrate_run_context(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        run = value.get("run")
        if isinstance(run, dict):
            hydrated = dict(run)
            hydrated.setdefault("dataset", value.get("dataset"))
            hydrated.setdefault("qc_report", value.get("qc_report"))
            value = {**value, "run": hydrated}
        return value


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planner_model: Optional[str] = None
    planner_provider: Optional[str] = None
    planner_api_key: Optional[str] = None
    planner_base_url: Optional[str] = None
    task_builder_model: Optional[str] = None
    task_builder_provider: Optional[str] = None
    task_builder_api_key: Optional[str] = None
    task_builder_base_url: Optional[str] = None
    qc_model: Optional[str] = None
    qc_provider: Optional[str] = None
    qc_api_key: Optional[str] = None
    qc_base_url: Optional[str] = None
    judge_models: list[TargetModelConfig] = Field(default_factory=list)
    research_model: Optional[str] = None
    research_provider: Optional[str] = None
    research_api_key: Optional[str] = None
    research_base_url: Optional[str] = None
    loop3_model: Optional[str] = None
    loop3_provider: Optional[str] = None
    loop3_api_key: Optional[str] = None
    loop3_base_url: Optional[str] = None
    task_agent_models: list[TargetModelConfig] = Field(default_factory=list)
    targets: list[TargetModelConfig] = Field(default_factory=list)
    scale_budget: ScaleBudget = ScaleBudget.mid
    max_planner_iterations: int = 5
    max_qc_iterations: int = 3
    max_research_sources: int = 3
    max_hf_records_per_dimension: int = 1
    large_scale_generated_item_cap_per_dimension: int = 50
    source_backed_ratio: Optional[float] = None
    large_scale_llm_qc_sample_size: int = 120
    output_dir: str = "./benchmark-output"
    task_builder_debug_dir: Optional[str] = None
    run_targets: bool = True
    use_web_research: bool = True
    search_backend: str = "auto"  # auto | gemini | keyless | none
    use_deep_research: bool = False
    max_research_iterations: int = 3
    research_brief: Optional[ResearchBrief] = None
    use_hf_discovery: bool = True
    task_builder_max_workers: int = 4
    task_builder_repair_attempts: int = 2
    task_builder_research_max_calls: int = 6
    task_builder_research_max_chars: int = 50_000
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
    docker_auto_select_image: bool = True
    docker_pull_timeout_s: int = 300
    docker_executable: str = "docker"
    container_sandbox_image: str = "python:3.11-slim"
    environment_preflight: bool = True
    allow_incomplete_benchmark: bool = False
    viewer_item_limit: int = 1000
    viewer_result_limit: int = 2000
    gui_bridge_url: Optional[str] = None
    gui_bridge_api_key: Optional[str] = None
    gui_bridge_timeout_s: int = 30
    vm_provider_url: Optional[str] = None
    vm_provider_api_key: Optional[str] = None
    vm_provider_timeout_s: int = 600
    vm_provider_destroy_on_cleanup: bool = True
