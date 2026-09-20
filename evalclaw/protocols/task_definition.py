"""Composable task contracts; independent of construction and model providers."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .tool import ToolCall, ToolSpec


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContentBlock(Contract):
    type: Literal["text", "json", "asset", "image"] = "text"
    text: str = ""
    data: Any = None
    asset_id: str = ""
    presentation: Literal["text", "image", "json"] = "text"
    media_type: str = ""


class TaskMessage(Contract):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[ContentBlock]
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    origin: Literal["task", "seeded_context", "prefill"] = "task"

    @model_validator(mode="after")
    def validate_role(self):
        if self.tool_calls and self.role != "assistant":
            raise ValueError("Only assistant messages may contain tool_calls")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("Tool messages require tool_call_id")
        return self


class TaskContent(Contract):
    messages: list[TaskMessage] = Field(min_length=1)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    stop: list[str] = Field(default_factory=list)
    operation: Literal["generate", "continuation_likelihood"] = "generate"
    continuations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_operation(self):
        from .submission import validate_output_contract
        validate_output_contract(self.output_contract)
        if self.operation == "continuation_likelihood" and not self.continuations:
            raise ValueError("continuation_likelihood requires continuations")
        if any(m.origin == "prefill" for m in self.messages[:-1]):
            raise ValueError("prefill is only valid as the last input message")
        if self.messages[-1].origin == "prefill" and self.messages[-1].role != "assistant":
            raise ValueError("prefill must be an assistant message")
        return self


class ComponentSpec(Contract):
    """A versioned JSON-lines service, isolated from target tools and credentials."""

    status: Literal["available", "missing", "not_provided"] = "available"
    unavailable_reason: str = ""
    image: str = ""
    pull_image: bool = True
    command: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    version: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    assets: list[str] = Field(default_factory=list)
    network: bool = False
    timeout_seconds: float = Field(default=300, gt=0)
    model_roles: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_availability(self):
        if self.status == "available" and (not self.image or not self.command or not self.version):
            raise ValueError("An available component requires image, command and version")
        if self.status != "available" and not self.unavailable_reason:
            raise ValueError("Unavailable component must state what is missing")
        return self


class ServiceEnvironment(Contract):
    type: Literal["tool_service"] = "tool_service"
    service: ComponentSpec
    tools: list[ToolSpec] = Field(default_factory=list)
    capabilities: list[Literal["checkpoint", "inspect"]] = Field(default_factory=list)
    initial_state: Any = None


class Participant(Contract):
    id: str
    role: Literal["target", "actor", "controller", "simulator"]
    system_prompt: str = ""
    tools: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    visible_assets: list[str] = Field(default_factory=list)
    history_scope: Literal["session", "episode"] = "episode"
    model_role: str = "actor"


class TaskBudget(Contract):
    target_calls: int | None = Field(default=None, gt=0, description="Logical target requests, including failed requests; transport retries are infrastructure attempts of that request.")
    tool_calls: int | None = Field(default=None, ge=0, description="Target tool invocations, including invalid arguments and failed tools; excludes actor/controller/reviewer tools.")
    target_tokens: int | None = Field(default=None, gt=0, description="Provider-reported target input plus output tokens. Checked after responses; remaining budget also caps output generation. Unreported retry usage is not inferred.")
    wall_time_seconds: float | None = Field(default=None, gt=0, description="Elapsed task time after prepare, including actors/controllers; excludes finalize and scoring.")
    controller_calls: int | None = Field(default=None, gt=0)
    actor_calls: int | None = Field(default=None, gt=0)
    branches: int | None = Field(default=None, ge=0)
    # Failed requests remain in the ledger; only an explicit native policy can
    # interpret them differently for scoring. Rollback never resets spending.


CONTROL_ACTIONS = (
    "message", "target", "tool_result", "tool_call", "register_tools",
    "reset_session", "checkpoint", "restore", "branch", "actor", "end",
)


class InteractionProtocol(Contract):
    protocol: Literal["response", "dialogue", "tool_loop", "program", "model"] = "response"
    participants: list[Participant] = Field(default_factory=list)
    turns: list[TaskMessage] = Field(default_factory=list)
    reset_between_turns: bool = False
    controller: ComponentSpec | None = None
    controller_prompt: str = ""
    controller_model_role: str = "actor"
    controller_actions: list[Literal[CONTROL_ACTIONS]] = Field(default_factory=list)
    budget: TaskBudget = Field(default_factory=TaskBudget)
    actor_contact_tool: str = ""
    controller_observations: list[str] = Field(default_factory=lambda: ["target", "task", "runtime"])

    @model_validator(mode="after")
    def check_controller(self):
        if self.protocol == "program" and self.controller is None:
            raise ValueError("program interaction requires a controller component")
        if self.protocol == "model" and not self.controller_prompt:
            raise ValueError("model interaction requires controller_prompt")
        if self.controller is not None and self.protocol != "program":
            raise ValueError("controller component requires program protocol")
        if self.controller_prompt and self.protocol != "model":
            raise ValueError("controller_prompt requires model protocol")
        if self.turns and self.protocol != "dialogue":
            raise ValueError("turns requires dialogue protocol")
        if self.reset_between_turns and self.protocol != "dialogue":
            raise ValueError("reset_between_turns requires dialogue protocol")
        if self.controller_actions and self.protocol not in {"model", "program"}:
            raise ValueError("controller_actions requires a controller protocol")
        ids = [p.id for p in self.participants]
        if len(ids) != len(set(ids)):
            raise ValueError("participant ids must be unique")
        reserved = {"target", "trial_target", "reviewer", "task", "runtime", "environment", "judge", "controller", "controller_simulation", "controller_prefill"}
        if any(p.id in reserved for p in self.participants if p.role == "actor"):
            raise ValueError("Actor id collides with a reserved event origin")
        return self


class Reference(Contract):
    id: str
    kind: Literal["answer", "labels", "trajectory", "tests", "state", "rubric"]
    value: Any = None
    asset_ids: list[str] = Field(default_factory=list)
    semantics: Literal["exhaustive", "example", "criterion"] = "criterion"


class MetricDefinition(Contract):
    id: str
    description: str = ""
    value_type: Literal["number", "boolean", "string", "array", "object"] = "number"
    minimum: float | None = None
    maximum: float | None = None
    direction: Literal["higher", "lower", "descriptive"] = "higher"
    unit: str = "item"


class ScorerSpec(Contract):
    id: str
    kind: Literal["exact", "json", "component", "llm", "agent", "environment", "aggregate"]
    metrics: list[str] = Field(min_length=1)
    references: list[str] = Field(default_factory=list)
    component: ComponentSpec | None = None
    instructions: str = ""
    case_sensitive: bool = True
    strip: bool = False
    depends_on: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    response_view: Literal["generated", "completed_message"] = "generated"

    @model_validator(mode="after")
    def component_required(self):
        if self.kind == "component" and self.component is None:
            raise ValueError("component scorer requires a component")
        if self.kind != "component" and self.component is not None:
            raise ValueError("Only a component scorer may declare component")
        if self.kind in {"exact", "json"} and not self.references:
            raise ValueError("Exact and JSON scorers require at least one reference")
        if self.kind in {"llm", "agent"} and not self.instructions.strip():
            raise ValueError("Model scorers require explicit scoring instructions")
        if self.kind == "aggregate" and (not self.weights or set(self.weights) != set(self.depends_on) or len(self.metrics) != 1):
            raise ValueError("aggregate scorer requires one output metric and a weight for every declared dependency")
        return self


class ScalarSelection(Contract):
    metric: str
    minimum: float
    maximum: float
    direction: Literal["higher", "lower"] = "higher"

    @model_validator(mode="after")
    def nonzero_scale(self):
        if self.maximum <= self.minimum:
            raise ValueError("scalar maximum must exceed minimum")
        return self


class TrialResponse(Contract):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)


class VerificationCase(Contract):
    id: str
    responses: list[TrialResponse] = Field(min_length=1)
    expected_metrics: dict[str, tuple[float, float]] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_ranges(self):
        if any(low > high for low, high in self.expected_metrics.values()):
            raise ValueError("Verification metric minimum must not exceed maximum")
        return self


class EvaluationSpec(Contract):
    references: list[Reference] = Field(default_factory=list)
    metrics: list[MetricDefinition] = Field(min_length=1)
    scorers: list[ScorerSpec] = Field(min_length=1)
    scalar: ScalarSelection | None = None
    verification_cases: list[VerificationCase] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_links(self):
        metrics = [m.id for m in self.metrics]
        refs = [r.id for r in self.references]
        scorer_ids = [s.id for s in self.scorers]
        for name, ids in (("metric", metrics), ("reference", refs), ("scorer", scorer_ids)):
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} ids must be unique")
        assigned = []
        for scorer in self.scorers:
            if set(scorer.references) - set(refs):
                raise ValueError(f"unknown references in scorer {scorer.id}")
            if scorer.kind in {"exact", "json"}:
                selected = [r for r in self.references if r.id in scorer.references]
                if any(r.value is None or r.asset_ids for r in selected):
                    raise ValueError("Exact/JSON references require inline values; use a component for asset-based scoring")
            if set(scorer.depends_on) - set(assigned):
                raise ValueError("Scorer dependencies must be metrics produced by earlier scorers")
            assigned.extend(scorer.metrics)
        if sorted(assigned) != sorted(metrics):
            raise ValueError("every metric must have exactly one scorer")
        if self.scalar and self.scalar.metric not in metrics:
            raise ValueError("unknown scalar metric")
        if self.scalar and next(m for m in self.metrics if m.id == self.scalar.metric).value_type not in {"number", "boolean"}:
            raise ValueError("Analyzer scalar must select a numeric or boolean metric")
        if len({case.id for case in self.verification_cases}) != len(self.verification_cases):
            raise ValueError("Verification case ids must be unique")
        for case in self.verification_cases:
            if set(case.expected_metrics) - set(metrics):
                raise ValueError("Verification case references unknown metrics")
        return self


class MetricResult(Contract):
    metric: str
    value: Any = None
    status: Literal["valid", "error", "not_applicable"] = "valid"
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    raw: Any = None


class EpisodeEvent(Contract):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    index: int
    kind: str
    origin: str
    session: str = "main"
    branch: str = "main"
    call_id: str | None = None
    parent_id: str | None = None
    timestamp: str
    data: Any = None


class EpisodeRecord(Contract):
    schema_version: Literal[2] = 2
    task_id: str
    task_digest: str
    bindings: dict[str, Any] = Field(default_factory=dict)
    events: list[EpisodeEvent] = Field(default_factory=list)
    initial_state: Any = None
    final_state: Any = None
    outputs: list[Any] = Field(default_factory=list)
    final_messages: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, float] = Field(default_factory=dict)
    termination: str = "pending"
    metrics: list[MetricResult] = Field(default_factory=list)
    native_evidence: list[str] = Field(default_factory=list)


class SuiteMetric(Contract):
    id: str
    metric: str
    aggregation: Literal["mean", "sum", "micro", "component"] = "mean"
    group_by: list[str] = Field(default_factory=list)
    numerator: str = ""
    denominator: str = ""
    component: ComponentSpec | None = None

    @model_validator(mode="after")
    def check_aggregation(self):
        if self.aggregation == "micro" and (not self.numerator or not self.denominator):
            raise ValueError("micro aggregation needs explicit numerator and denominator metrics")
        if self.aggregation == "component" and self.component is None:
            raise ValueError("component aggregation needs a component")
        return self
