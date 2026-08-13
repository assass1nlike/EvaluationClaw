# EvaluationClaw 项目结构

当前代码库按“少量顶层编排入口 + 领域子系统”组织。构题阶段只有一条通用路线：`用户需求 -> BenchmarkPlan（维度 + 自适应 TaskBlueprint）-> TaskBuilder -> TaskSuite -> BenchmarkDataset`。题型差异通过 Blueprint 的题型分配和任务实际字段表达，不再保留 static/agent 两套 planner 或 materializer。

## 顶层入口

- `evalclaw/cli.py`：命令行入口，解析参数并调用 pipeline。
- `evalclaw/pipeline.py`：端到端编排，串联预处理、统一构题、QC、环境准备、runner、Loop 3 和 reporting。
- `evalclaw/benchmark.py`：统一 blueprint 构建、TaskBuilder 调用、QC 定点 repair 和 fail-closed。
- `evalclaw/types.py`：全项目共享的数据模型和配置 schema。

不要新增旧模块的兼容 shim，也不要重新引入按 static/agent 选择构题路线的入口。

## 核心子包

- `evalclaw/core/`：跨子系统共享的小型工具，包括规模预算和任务内容摘要。
- `evalclaw/models/`：模型调用、JSON 提取、provider/protocol 选择、重试和截断恢复；`roles.py` 解析 Planner、TaskBuilder、QC、Judge、Research 和 Loop 3 的独立模型连接并回退到默认 orchestrator。
- `evalclaw/planning/`：自然语言需求到维度纲要，再由 Planner Skill 生成并审计完整 `BenchmarkPlan` 和自适应 `TaskBlueprint`。
- `evalclaw/construction/`：唯一的构题实现，负责 Blueprint 资源选择、每 Blueprint 一次 Builder 调用、多题结构校验和 dataset 包装。
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

- `blueprints.py`：Planner 不可用时，为离线 smoke test 生成保守的本地 Blueprint fallback。
- `suite.py`：每个 Blueprint 形成一次 Builder 调用；严格校验其题量和混合题型分配，并处理 Blueprint 并发、结构 repair、截断恢复和进度日志。QC repair 时只返回有问题的题并按题目 ID 合并。
- `builders.py`：通用本地 fallback 分派。无环境任务复用程序化 item fallback；有环境任务调用对应交互环境实现。
- `resources.py`：仅在 dimension 明确 `needs_research=true` 时选择外部来源，并做资源归一化与去重。
- `research.py`：source-backed 或 E3 初次构题可使用有界研究工具循环；QC repair 不重复研究。
- `validation.py`：在全局 QC 前校验题型字段、challenge effort 自检和可选执行环境契约。
- `packaging.py`：把统一 `TaskSuite` 转成 `BenchmarkDataset`。只有 task 带 `environment` 时才生成 `agent_env`、`task_agent` 和 `agent_task_package` metadata。

## Planning 子系统

- `planner.py`：目标翻译、维度纲要 prompt、纲要解析和本地 fallback；维度阶段也读取当前 Planner Skill。
- `task_planner.py`：唯一 benchmark planner 入口。加载 `planning/skills/design-benchmark-blueprints/SKILL.md`，让 Planner 自主决定 Blueprint 边界、题量、混合题型和 `family`/`archetype`/`per_task` 粒度，再执行题量、归属和工作量审计。
- `skill_loader.py`：以 UTF-8 读取 Planner Skill，并把它注入维度和 Blueprint 规划调用。
- `skills/design-benchmark-blueprints/SKILL.md`：需求、研究结果、维度和 Builder 工作量到完整 Blueprint 计划的规范。
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
- `quality/improver.py`：Loop 3 诊断后，仍通过 Planner Blueprint 和通用 TaskBuilder 重新生成目标内容。
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
