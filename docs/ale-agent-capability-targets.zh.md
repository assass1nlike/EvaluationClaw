# ALE Agent 任务能力考点与 EvalClaw 对齐记录

本文记录从 Agents' Last Exam 官网与公开任务列表抽象出的 agent benchmark 能力考点，以及本次在 EvalClaw 中的验证和改动。

## ALE 任务形态

ALE 的核心不是静态问答，而是让 agent 在真实或近似真实的机器环境里完成长流程专业工作。典型任务包含：

- 可见任务输入：说明、项目文件、数据、文档、GUI 初始状态。
- 运行环境：Linux/Windows VM、Docker 子集、GUI/CLI CUA bridge、专业软件。
- 隐藏参考：参考文件、答案、truth set、评分脚本或评价标准，agent 完成后才进入评分侧。
- 输出契约：文件、视频、渲染图、JSON/CSV、报告、GUI/page state、数值结果。
- 评分：确定性脚本、artifact/state check、数值 tolerance、必要时 VLM/LLM judge。
- 轨迹：命令、工具调用、截图、日志、产物统一保存，支持回放审计。

## 抽象能力考点

本次从 ALE 示例任务中抽象出以下 EvalClaw 应能接收的自然语言能力描述：

| ALE 任务族 | 抽象测评目标 |
| --- | --- |
| Motion/VFX、视频编辑 | 测 agent 使用桌面专业软件完成多步 GUI 编辑、导出视频/项目 artifact，并与隐藏参考比较的能力。 |
| Blender/Unreal/3D 建模 | 测 agent 在 VM 桌面软件中创建/修改 3D 场景、保存工程和渲染图，并通过对象/材质/相机/图像检查评分的能力。 |
| CAD/BIM/CAE/CAM | 测 agent 根据图纸或工程约束在专业软件中构建模型、运行模拟或导出工程 artifact 的能力。 |
| 科学计算 pipeline | 测 agent 检查数据/脚本/环境、运行命令、修复执行问题、输出数值结果并通过隐藏 tolerance 检查的能力。 |
| 生信/医学数据 workflow | 测 agent 使用 staged 数据和说明完成 variant/cell/clinical imaging 等流程，并与隐藏 truth set 比较的能力。 |
| 金融/企业文档 workflow | 测 agent 从 SEC filing、ERP/业务文档等材料中抽取、重构结构化结果，并通过 schema/一致性 oracle 检查的能力。 |
| SRE/云/安全诊断 | 测 agent 基于日志、配置、PCAP、反编译线索等资源做诊断、运行命令、产出 grounded RCA/IOC，并通过隐藏检查评分的能力。 |

## 本次 EvalClaw 改动

- 新增 `metadata.agent_task_package` 协议，schema 为 `evalclaw.agent_task_package.v1`。
- 新增文档：[agent-task-package-spec.schema.json](agent-task-package-spec.schema.json)。
- Planner、generator、agent benchmark builder、planner review prompt 都会要求 ALE-like / VM / GUI / Docker / 长流程任务带任务包。
- QC 会对 GUI、VM、Docker、ALE-style agent 任务检查任务包字段；缺少任务包会阻塞 run。
- VM materializer 会把公开任务包写到 public manifest，把完整任务包和隐藏参考写入 root-only private 路径。
- 本地 fallback 增强：
  - GUI/desktop 任务按视频、CAD/BIM、Blender、办公软件分流。
  - runtime pipeline 任务按 Docker workspace 生成，不再退回玩具 workspace。
  - data-analysis、SRE/security shell debugging、desktop GUI 模板增加多变体，避免同质化重复。

## Smoke 结果

运行结果保存在：

- `benchmark-output/ale-evalclaw-analysis/ale_evalclaw_smoke_results.md`
- `benchmark-output/ale-evalclaw-analysis/ale_evalclaw_smoke_results.json`

本地无 orchestrator API 模式下，8 个 ALE 抽象能力 case 均生成到 run 前并通过 QC：

- desktop video compositing：3 个 `gui_desktop` agent 任务。
- CAD/BIM modeling：3 个 `gui_desktop` agent 任务。
- scientific climate pipeline：3 个 `docker_workspace` agent 任务。
- bioinformatics variant analysis：3 个 `docker_workspace` agent 任务。
- financial statement reconstruction：3 个 `docker_workspace` agent 任务。
- Kubernetes incident RCA：3 个 `docker_workspace` agent 任务。
- PCAP/malware triage：3 个 `docker_workspace` agent 任务。
- Blender scene task：3 个 `gui_desktop` agent 任务。

每个生成 item 都带 `metadata.task_agent`、`metadata.agent_env`、`metadata.agent_task_package`，并包含 visible inputs、hidden references、output contract、execution/evaluation、artifact collection、trajectory requirements。

## 当前边界

- 本地 fallback 只能生成 compact fixture，质量上主要验证框架结构和运行契约；真正对标 ALE 的行业级任务仍应由强 orchestrator 结合真实资源构建。
- 当前 OpenAI 环境变量中的 key 无法通过鉴权，未进行真实 LLM planner/builder 大规模调用。
- 专业软件镜像、许可证、实际 bridge evaluator 仍依赖 VM provider / 镜像准备；EvalClaw 已能表达并 materialize 任务包，但具体软件运行还需要对应后端环境。
