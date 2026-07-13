# EvaluationClaw 项目结构

当前代码库按“少量顶层入口 + 领域子系统”组织。历史兼容 shim 已经从 `evalclaw/` 根目录删除，仓库内部代码、测试、脚本都应导入真实实现路径。

## 顶层入口

`evalclaw/` 根目录只保留这些 Python 文件：

- `__init__.py`：包声明。
- `cli.py`：命令行入口，负责解析参数并调用 pipeline。
- `pipeline.py`：端到端编排入口，串联 planning、generation、QC、环境 preflight、runner 和 reporting。
- `types.py`：全项目共享的数据模型和配置 schema。

不要再新增 `evalclaw.runner`、`evalclaw.generator`、`evalclaw.qc` 这类顶层兼容模块。新代码必须放入对应子包，并通过真实路径导入。

## 核心子包

- `evalclaw/core/`：跨子系统共享的小型工具，目前包含规模预算和任务内容摘要。
- `evalclaw/models/`：模型调用、JSON 提取、provider 默认配置和目标模型解析。
- `evalclaw/sources/`：外部数据源发现和导入，目前包含 HuggingFace 数据集发现/导入。
- `evalclaw/planning/`：自然语言需求到结构化 eval spec，以及 planner-loop/human-review 逻辑。
- `evalclaw/generation/`：按 spec 生成、搜索或导入评测 item，包含程序化 fallback。
- `evalclaw/quality/`：静态 QC、数据集覆盖 QC、LLM QC 和 Loop 3 改进。
- `evalclaw/execution/`：runner、隔离容器、Docker、VM、桌面桥与通用环境 preflight。
- `evalclaw/runners/`：具体题型 runner，例如 agent、pairwise、target prompt、credential 检查。
- `evalclaw/protocols/`：任务协议、工具调用协议、多模态、science metadata、agent task package。
- `evalclaw/agent/`：agent benchmark 的维度规划、blueprint 路由、资源选择、任务构建和打包。
- `evalclaw/research/`：deep research 流程和搜索 backend。
- `evalclaw/reporting/`：Markdown/HTML 报告、artifact manifest 和报告前端模板。
- `evalclaw/prompts/`：planner、generator、QC、research、agent benchmark 等 prompt。

## Agent 子系统

`evalclaw/agent/` 内部按规划、规则、构题、打包拆分：

- `planning.py`：agent benchmark 规划入口，负责调用 LLM planner、解析返回、选择 fallback。
- `dimensions.py`：agent 维度解析和本地 fallback 维度规则。
- `blueprints.py`：按维度内容选择默认 agent task blueprint。
- `goal_detection.py`：从自然语言需求中识别 GUI、VM、工业软件和运行环境等执行需求。
- `resources.py`：source-backed 资源选择和去重。
- `suite.py`：调用 task-builder 或 fallback 构建 `AgentTaskSuite`。
- `packaging.py`：把 `AgentTaskSuite` 打包成 runner 可执行的 `BenchmarkDataset`。
- `validation.py`：task-builder 产物进入 QC 前的结构校验。
- `task_builders/`：按执行环境和基础实现拆分的本地 fallback 构题器。
- `task_builders/gui_variants.py`：GUI/桌面任务的大块模板数据。

## Quality 子系统

`evalclaw/quality/` 按 QC 类型拆分：

- `qc.py`：QC gate 汇总入口，对外提供 `run_qc_gate`。
- `common.py`：QC issue 构造、来源判断等共享小工具。
- `static_checks.py`：单题结构、评分、metadata 的静态检查。
- `dataset_checks.py`：重复题、维度覆盖、大规模 batch 计划检查。
- `llm_checks.py`：LLM QC 的抽样、上下文压缩和 issue 稳定化。
- `improver.py`：Loop 3 改进逻辑。

## Reporting 子系统

`evalclaw/reporting/` 按输出层和报告片段拆分：

- `reporter.py`：Markdown 报告最终组装入口。
- `markdown.py`：Markdown 表格、截断、代码块等基础格式化工具。
- `run_sections.py`：运行来源、数据集、QC、Judge audit、逐题详情等通用报告片段。
- `safety.py`：安全评测风险 overlay 和 safety audit。
- `viewer.py`：HTML viewer 的数据 payload 和入口函数。
- `viewer_template.py`：HTML/CSS/JavaScript 模板。
- `artifacts.py`：artifact manifest 和相关导出。

## 导入路径建议

常用真实路径：

- `evalclaw.generation.generator`
- `evalclaw.models.llm`
- `evalclaw.models.providers`
- `evalclaw.sources.hf_ingest`
- `evalclaw.core.scaling`
- `evalclaw.quality.qc`
- `evalclaw.reporting.viewer`
- `evalclaw.execution.runner`
- `evalclaw.agent.planning`

如果某个旧脚本仍依赖被删除的顶层路径，应直接迁移脚本导入，而不是恢复兼容 shim。
