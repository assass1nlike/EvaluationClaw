"""File-oriented authoring format. Optional interfaces compose independently."""
from typing import Any, Literal

from pydantic import Field, model_validator

from ..protocols.task_definition import (
    ContentBlock,
    Contract,
    MetricDefinition,
    Participant,
    ScalarSelection,
    TaskBudget,
    TaskMessage,
)


class Message(TaskMessage):
    content: str | list[ContentBlock] | None = None
    file: str | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (self.content is None) == (self.file is None):
            raise ValueError("Provide exactly one of content or file")
        return self


class File(Contract):
    id: str
    path: str
    audience: list[str] = Field(default_factory=lambda: ["judge"])
    mount: str = ""
    media_type: str = ""


class Program(Contract):
    image: str
    pull_image: bool = True
    files: list[str] = Field(min_length=1)
    command: list[str] = Field(min_length=1)
    version: str = "1"
    config: dict[str, Any] = Field(default_factory=dict)
    assets: list[str] = Field(default_factory=list)
    model_roles: list[str] = Field(default_factory=list)
    network: bool = False
    timeout_seconds: float = Field(default=300, gt=0)


class Workspace(Contract):
    image: str = ""
    pull_image: bool = True
    dockerfile: str | None = None
    context: str = "."
    setup: list[str] = Field(default_factory=list)
    network: str = "none"
    workdir: str = "/workspace"
    command_timeout: int = Field(default=120, gt=0)
    max_steps: int = Field(default=500, gt=0)
    # A local workspace evaluator receives all episode evidence at /evalclaw-evidence.
    score_command: str = ""
    private_files: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def source(self):
        if bool(self.image) == (self.dockerfile is not None):
            raise ValueError("Provide exactly one of image or dockerfile")
        return self


class Interaction(Contract):
    turns: list[Message] = Field(default_factory=list)
    reset_between_turns: bool = False
    driver: Program | None = None
    instructions: str = ""
    model_role: str = "actor"
    actions: list[str] = Field(default_factory=list)
    participants: list[Participant] = Field(default_factory=list)
    budget: TaskBudget = Field(default_factory=TaskBudget)
    observations: list[str] = Field(default_factory=lambda: ["target", "task", "runtime"])
    actor_contact_tool: str = ""

    @model_validator(mode="after")
    def mode(self):
        if sum((bool(self.turns), self.driver is not None, bool(self.instructions))) > 1:
            raise ValueError("Choose scripted turns, a driver, or model instructions")
        if self.reset_between_turns and not self.turns:
            raise ValueError("reset_between_turns requires turns")
        return self


class Grade(Contract):
    method: Literal["exact", "json", "judge", "agent", "program", "environment", "aggregate"]
    name: str = "score"
    answer: Any = None
    answer_file: str | None = None
    answer_format: Literal["text", "json"] = "text"
    reference_kind: Literal["answer", "labels", "trajectory", "tests", "state", "rubric"] = "answer"
    reference_is: Literal["example", "exhaustive", "criterion"] | None = None
    instructions: str = ""
    rubric: str | None = None
    program: Program | None = None
    metrics: list[MetricDefinition] | None = None
    strip: bool = False
    case_sensitive: bool = True
    response_view: Literal["generated", "completed_message"] = "generated"
    weights: dict[str, float] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistency(self):
        if self.answer is not None and self.answer_file is not None:
            raise ValueError("Use answer or answer_file, not both")
        if self.instructions and self.rubric is not None:
            raise ValueError("Use instructions or rubric, not both")
        if (self.program is not None) != (self.method == "program"):
            raise ValueError("program is required only for method=program")
        if (self.weights or self.depends_on) and self.method != "aggregate":
            raise ValueError("weights and depends_on require method=aggregate")
        if self.reference_is not in {None, "exhaustive"} and self.method in {"exact", "json"}:
            raise ValueError("Exact/JSON comparison requires an exhaustive reference")
        if (self.instructions or self.rubric is not None) and self.method not in {"judge", "agent"}:
            raise ValueError("instructions/rubric require judge or agent grading; program rules belong in its code")
        if (self.strip or not self.case_sensitive) and self.method != "exact":
            raise ValueError("strip/case_sensitive only apply to exact text comparison")
        if self.answer_format != "text" and self.answer_file is None:
            raise ValueError("answer_format requires answer_file")
        return self


class Task(Contract):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    title: str = ""
    prompt: str | None = None
    messages: list[Message] = Field(default_factory=list)
    files: list[File] = Field(default_factory=list)
    workspace: Workspace | None = None
    service: Program | None = None
    service_capabilities: list[Literal["checkpoint", "inspect"]] = Field(default_factory=list)
    initial_state: Any = None
    interaction: Interaction = Field(default_factory=Interaction)
    grading: Grade | list[Grade]
    primary: ScalarSelection | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    stop: list[str] = Field(default_factory=list)
    operation: Literal["generate", "continuation_likelihood"] = "generate"
    continuations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    labels: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistency(self):
        if (self.prompt is not None) == bool(self.messages):
            raise ValueError("Provide exactly one of prompt or messages")
        if self.workspace is not None and self.service is not None:
            raise ValueError("Choose workspace or service")
        if self.service is None and (self.service_capabilities or self.initial_state is not None):
            raise ValueError("service_capabilities and initial_state require service")
        if len({f.id for f in self.files}) != len(self.files):
            raise ValueError("File IDs must be unique")
        if isinstance(self.grading, list) and not self.grading:
            raise ValueError("At least one grading rule is required")
        return self


class Aggregation(Contract):
    id: str
    metric: str
    aggregation: Literal["mean", "sum", "micro", "program"] = "mean"
    group_by: list[str] = Field(default_factory=list)
    numerator: str = ""
    denominator: str = ""
    program: Program | None = None

    @model_validator(mode="after")
    def consistency(self):
        if (self.program is not None) != (self.aggregation == "program"):
            raise ValueError("A suite program is required only for aggregation=program")
        if self.program and self.program.model_roles:
            raise ValueError("Suite aggregation currently has no auxiliary-model callback binding")
        return self


class ImageDependency(Contract):
    image: str = Field(min_length=1)
    source: str | None = None
    dockerfile: str | None = None
    context: str = "."

    @model_validator(mode="after")
    def source_kind(self):
        if bool(self.source) == bool(self.dockerfile):
            raise ValueError("Declare exactly one source image or Dockerfile for an image dependency")
        return self


class Benchmark(Contract):
    format: Literal["benchmark-package/v1"]
    objective: str = Field(min_length=1)
    tasks: list[str] = Field(min_length=1)
    aggregation: list[Aggregation] = Field(default_factory=list)
    images: list[ImageDependency] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_images(self):
        if len({image.image for image in self.images}) != len(self.images):
            raise ValueError("Image dependency names must be unique")
        return self
