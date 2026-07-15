# EvaluationClaw 项目结构

当前代码库按“少量顶层编排入口 + 领域子系统”组织。构题阶段只有一条通用路线：`EvalSpec -> TaskBlueprint -> TaskBuilder -> TaskSuite -> BenchmarkDataset`。题型差异通过字段是否存在表达，不再保留 static/agent 两套 planner 或 materializer。

## 顶层入口

- `evalclaw/cli.py`：命令行入口，解析参数并调用 pipeline。
- `evalclaw/pipeline.py`：端到端编排，串联预处理、统一构题、QC、环境准备、runner、Loop 3 和 reporting。
- `evalclaw/benchmark.py`：统一 blueprint 构建、TaskBuilder 调用、QC 定点 repair 和 fail-closed。
- `evalclaw/types.py`：全项目共享的数据模型和配置 schema。

不要新增旧模块的兼容 shim，也不要重新引入按 static/agent 选择构题路线的入口。

## 核心子包

- `evalclaw/core/`：跨子系统共享的小型工具，包括规模预算和任务内容摘要。
- `evalclaw/models/`：模型调用、JSON 提取、provider/protocol 选择、重试和截断恢复；`roles.py` 解析 Planner、TaskBuilder、QC、Judge、Research 和 Loop 3 的独立模型连接并回退到默认 orchestrator。
- `evalclaw/planning/`：自然语言需求到 `EvalSpec`，以及从 spec 生成通用 `TaskBlueprint`。
- `evalclaw/construction/`：唯一的构题实现，负责 blueprint、资源选择、单题 builder 调用、结构校验和 dataset 包装。
- `evalclaw/generation/`：通用构题路线使用的程序化静态题 fallback 与底层 item 生成能力；不是独立顶层路线。
- `evalclaw/sources/`：外部数据源发现和导入，包括 HuggingFace 支持。
- `evalclaw/quality/`：逐题/数据集/LLM QC 和 Loop 3 改进。
- `evalclaw/execution/`：执行计划、隔离容器、Docker、VM、桌面桥和 EnvironmentClaw preflight。
- `evalclaw/runners/`：按 `task_type` 和实际字段执行、评分的 runner 实现。
- `evalclaw/protocols/`：任务代理、工具调用、多模态、science metadata 和可执行任务包协议。
- `evalclaw/agent/`：仅保留可选交互环境的识别规则和本地 fallback 实现，不是构题主路线。
- `evalclaw/research/`：deep research 和搜索 backend。
- `evalclaw/reporting/`：Markdown/HTML 报告、artifact manifest 和前端模板。
- `evalclaw/prompts/`：planner、通用 task builder、QC、research 和改进 prompt。

## Construction 子系统

- `blueprints.py`：根据单一 task type 和能力描述选择默认可选执行能力。
- `suite.py`：把每个 blueprint 拆为单题 slot；每个远程 builder 调用只生成一道题；处理并发、结构 repair、截断恢复和进度日志。
- `builders.py`：通用本地 fallback 分派。无环境任务复用程序化 item fallback；有环境任务调用对应交互环境实现。
- `resources.py`：仅在 dimension 明确 `needs_research=true` 时选择外部来源，并做资源归一化与去重。
- `research.py`：E4 初次构题可使用的有界研究工具循环；QC repair 不重复研究。
- `validation.py`：在全局 QC 前校验题型字段、challenge effort 自检和可选执行环境契约。
- `packaging.py`：把统一 `TaskSuite` 转成 `BenchmarkDataset`。只有 task 带 `environment` 时才生成 `agent_env`、`task_agent` 和 `agent_task_package` metadata。

## Planning 子系统

- `planner.py`：目标翻译、planner prompt、`EvalSpec` 解析和 fallback。
- `task_planner.py`：唯一 benchmark planner 入口。一次调用得到一个 `EvalSpec`，再按 task type 生成同构的 `TaskBlueprint`；同一 dimension 可拥有多种题型，但每个 blueprint slot 的字段要求是明确的。
- `loop.py`：人工 review 的摘要、review action 解析和 spec 更新。更新后的 spec 重新进入通用 blueprint/builder/QC 路线。

## Agent 子系统

`evalclaw/agent/` 不再拥有 planner、suite、packaging 或 QC loop。当前保留内容：

- `goal_detection.py`：识别 browser、GUI、VM、工业软件、代码沙盒等可选执行需求。
- `task_builders/`：workspace、code sandbox、Docker、dialogue、GUI 等交互环境的本地 fallback 实现。

## Quality 与执行

- `quality/qc.py`：统一 QC gate。
- `quality/static_checks.py`：这里的 static 表示不调用 LLM 的程序化检查，不代表一条静态题构建路线。
- `quality/dataset_checks.py`：重复、覆盖和 batch 检查。
- `quality/llm_checks.py`：LLM QC 抽样、上下文压缩和 issue 稳定化。
- `quality/improver.py`：Loop 3 诊断后，仍通过通用 TaskBuilder 重新生成目标 slot。
- `execution/plan.py`：只把 QC accepted items 交给 runner。
- `execution/runner.py`：按 `task_type` 与实际 metadata/字段分派执行和评分。这是运行时分派，不是构题路线分流。

## 推荐导入路径

- `evalclaw.benchmark.build_benchmark_dataset_with_qc_loop`
- `evalclaw.planning.task_planner.plan_benchmark`
- `evalclaw.construction.suite.build_task_suite`
- `evalclaw.construction.packaging.task_suite_to_dataset`
- `evalclaw.construction.validation.task_structure_issues`
- `evalclaw.quality.qc.run_qc_gate`
- `evalclaw.execution.runner.run_eval`
- `evalclaw.reporting.viewer.build_report_viewer_html`

旧脚本如果仍依赖已删除的 agent planner/suite/packaging 或旧顶层兼容路径，应直接迁移到以上真实路径，不要恢复 shim。
