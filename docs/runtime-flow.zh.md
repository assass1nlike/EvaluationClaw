# EvaluationClaw 当前运行流程

本文描述当前代码库里的 EvaluationClaw 运行流程。它以用户输入的自然语言评估需求为起点，自动规划评估维度、生成或搜索题目、进行题集自检和修复、运行目标模型，并输出报告。

## 1. 总览

当前主流程入口在 [evalclaw/pipeline.py](../evalclaw/pipeline.py)。

整体链路是：

```text
自然语言需求 goal
  -> 输入规范化 / 非英文翻译
  -> Planner 生成 EvalSpec
  -> Planner / Generator / QC pre-run 自检循环
      -> 按维度生成或导入题目
      -> QC 检查单题质量、重复、答案、rubric、覆盖等问题
      -> Planner 审视整体题集和维度结构
      -> 删除 / 移动 / 合并 / 拆分 / 补题
      -> 再 QC，直到没有明显不合理或达到迭代上限
  -> 可选 Human-in-the-loop 审阅
      -> 用户批准，或给出维度/题目修改意见
      -> Planner 按用户意见修改维度和题目
      -> 如需新题，继续生成/获取并再次 QC
  -> Runner 执行 QC 通过的题目
  -> 可选 Loop 3 基于运行结果继续改进
  -> Reporter 生成 Markdown / JSON / HTML / lm-eval 互操作产物
```

旧的“一次性 `Planner -> Generator -> QC -> Runner`”已经升级为“`Planner -> 生成-自检循环 -> Runner`”。也就是说，正式测试目标模型之前，框架会先尝试把题集修到一个较合理的状态。

## 2. CLI 入口

主要 CLI 在 [evalclaw/cli.py](../evalclaw/cli.py)。

常用命令：

```bash
evalclaw generate --goal "Evaluate strict JSON format following"
```

关键参数包括：

```text
--goal                     自然语言评估需求
--model                    主目标模型
--compare                  额外对比模型，可重复
--orchestrator-model       用于规划、生成、QC、judge 的模型
--scale-budget             low / mid / high
--qpd                      默认每维度题目数量
--max-qc-iterations        pre-run 生成/QC 自检循环最大迭代数
--max-hf-records           每个维度最多导入多少 HF 记录
--no-run                   只生成和 QC，不运行目标模型
--no-research              关闭 web research
--no-hf-discovery          关闭 Hugging Face discovery
--runner                   direct / lm-eval / auto
--human-review             在 Runner 前暂停，允许人工批准或提出修改意见
--improve-iterations       Loop 3 运行后改进迭代次数
--loop3-diagnosis          llm / local
```

CLI 会把这些参数组装成 `BenchmarkConfig`，然后调用 `run_pipeline(...)`。

## 3. 输入规范化

Pipeline 开始后先调用 [evalclaw/planner.py](../evalclaw/planner.py) 中的：

```python
translate_goal_to_english(goal, config)
```

如果输入里包含 CJK 字符，系统会尝试用 orchestrator 模型把评估需求翻译和规范化成英文。这样做是为了让后续 Planner 和 Generator 使用统一的内部语言，同时保留用户原始技术意图。

如果没有 orchestrator key 或翻译失败，会直接使用原始 goal。

## 4. Planner：生成 EvalSpec

Planner 入口是：

```python
plan_eval_spec(goal, config)
```

它负责把自然语言需求变成结构化 `EvalSpec`。

`EvalSpec` 包括：

```text
id                      评估规格 ID
objective               评估目标
subjects                被评估对象
task_types              计划使用的题型
scale_budget            low / mid / high
scale                   估计规模
metrics                 指标，例如 accuracy / judge_score / pass@1
constraints             约束
planner_notes           planner 说明
dimensions              评估维度列表
critique                planner 自检结果
```

每个 `EvalDimension` 当前不仅包含名称、描述和方法，还可以包含更具体的题目规划：

```text
id
name
description
approach
weight
target_difficulty
needs_research
research_queries
target_item_count
target_source_backed_count
target_generated_count
task_types
item_requirements
```

其中新增的几个字段用于指导后续生成：

```text
target_item_count             该维度期望最终保留多少题
target_source_backed_count    期望其中多少题来自已有来源或 source-backed 生成
target_generated_count        期望其中多少题由模型自生成
task_types                    该维度适合的题型
item_requirements             交给生成 worker 的具体要求
```

### 4.1 预算机制

`scale_budget` 不是硬性的题量配额，而是一个全局的粗粒度锚点。当前实现里，
`low / mid / high` 大致可以理解为：

- `low`：约 2-3 个维度，约 12 道题，适合烟雾测试或很轻量的验证。
- `mid`：约 3-5 个维度，约 30 道题，适合常规评测。
- `high`：约 4-7 个维度，约 60 道题，适合更深入的覆盖。

这些只是基线。planner 仍然可以根据评测目标自由调整维度数量和题量，只要整体上不严重偏离预算的粗粒度预期即可。不同题型的工作量也不一样：

- `multiple_choice`、`open_generation` 通常更轻。
- `multi_turn`、`agent_interaction`、`code_sandbox` 通常更重。

因此，一个复杂的多轮或 agent 题，可能在预算上相当于若干道简单题；而一个面向简单能力的任务，也不需要为了“凑数”去硬上复杂题型。planner 应优先选择最能测试目标能力的题型组合，然后再在预算范围内做适当增减。

如果没有 orchestrator key，Planner 会走本地 fallback，生成三个默认维度：

```text
core_capability
robustness
calibration
```

## 5. 生成/QC 自检循环

正式进入 Runner 之前，Pipeline 会调用 [evalclaw/planning_loop.py](../evalclaw/planning_loop.py)：

```python
generate_dataset_with_qc_loop(spec, config, log=log)
```

这个函数是当前 `Planner -> Generator -> QC` 重构后的核心。

它返回：

```python
tuple[EvalSpec, BenchmarkDataset, QcReport]
```

也就是说，pre-run 自检循环可能会修改：

```text
EvalSpec            例如合并、拆分、更新维度
BenchmarkDataset    例如删除、移动、补充题目
QcReport            最终题集的 QC 结果
```

### 5.1 初始生成

自检循环第一步调用 [evalclaw/generator.py](../evalclaw/generator.py)：

```python
generate_dataset_with_progress(spec, config, log=log)
```

它会逐个维度生成题目。

每个维度的目标题量通过：

```python
target_count_for_dimension(dimension, config)
```

决定。优先使用 `dimension.target_item_count`，否则回退到 CLI 的 `--qpd`。

### 5.2 每维度题目生成

每个维度调用：

```python
generate_dimension_items(spec, dimension, count, config)
```

它会综合使用：

```text
维度描述
维度 approach
item_requirements
task_types
target_source_backed_count
target_generated_count
research_queries
scale_budget
外部 source context
```

生成题目。

题目可以是：

```text
yes_no
multiple_choice
short_answer
open_generation
code_execution
multi_turn
agent_interaction
```

生成器仍然保留原有能力：

```text
自生成题目
Hugging Face dataset discovery / ingest
web research
source-backed synthesis
code execution test_code
multi-turn metadata.turns
agent_interaction metadata.agent_env
```

### 5.3 外部来源搜索与共享

Generator 会按维度决定是否需要 research。

对于需要 source-backed 题目的维度，可能调用：

```text
Hugging Face discovery
Hugging Face ingest
web_search
fetch_url_text
```

当前代码里还有一个轻量的 research source 共享机制：如果两个维度的 research tokens 很相近，它们会复用同一批 external sources。这样可以减少相近维度各自搜索到重复或冲突来源的问题。

### 5.4 QC Gate

初始生成后，进入 [evalclaw/qc.py](../evalclaw/qc.py)：

```python
run_qc_gate(dataset, config)
```

QC 分为静态检查和可选 LLM 检查。

静态检查包括：

```text
prompt 是否为空或过短
multiple-choice 选项和答案是否一致
yes/no 答案是否合法
open_generation / multi_turn / agent_interaction 是否有 rubric
short_answer 是否有 answer 或 rubric
code_execution 是否有 test_code
agent_interaction 的 agent_env 是否有效
重复题检测
维度覆盖检测
计划题型覆盖检测
难度检测
source-backed 覆盖检测
```

如果配置了 orchestrator key，QC 还会让 LLM 检查：

```text
维度是否匹配目标
题目是否偏题
题型和评分方式是否合适
是否有明显遗漏
是否有 content drift
是否过度依赖 judge
source 选择是否合理
```

QC 输出 `QcReport`：

```text
issues
passed_item_ids
rejected_item_ids
quality_score
summary
```

被标记为 `severity=error` 且绑定了 `item_id` 的题目，会进入 `rejected_item_ids`。

## 6. Pre-Run Planner Review

QC 之后，`planning_loop.py` 会进入 pre-run planner review。

如果没有 orchestrator key，本地模式会跳过 LLM review，只做静态 repair 和补题。

如果有 orchestrator key，会调用 Planner review prompt，让模型整体审视题集：

```text
1. 看所有题目是否属于当前维度
2. 明显不属于的题目：删除或移动
3. 维度题量太少：补题
4. 维度过窄或与其它维度高度重叠：合并
5. 维度过宽：拆分
6. 如果整体已经合理，不要追求完美，不要无限迭代
```

Planner review 可以返回这些动作：

```text
delete_item_ids
move_items
dimension_updates
merge_dimensions
split_dimensions
needs_more_items
done
notes
```

这些动作会被 `_apply_review(...)` 应用到当前 dataset 和 spec 上。

## 7. 删除、移动、合并、拆分、补题

Pre-run 循环当前可以做这些操作。

### 7.1 删除题目

有两类删除：

```text
QC rejected items
Planner review delete_item_ids
```

这些题会在 Runner 之前从当前 dataset 中移除，不再进入正式测试。

### 7.2 移动题目

如果某题更适合另一个已有维度，Planner review 可以返回：

```json
{"item_id": "...", "dimension_id": "..."}
```

系统会更新该题的 `dimension_id`。

### 7.3 合并维度

如果多个维度明显重叠，Planner review 可以返回 `merge_dimensions`。

系统会：

```text
删除旧维度
创建新合并维度
把旧维度下的题全部移到新维度
```

### 7.4 拆分维度

如果某个维度太宽，Planner review 可以返回 `split_dimensions`。

系统会：

```text
删除旧维度
创建多个新维度
根据 item_assignments 分配已有题目
未指定分配的题目进入第一个新维度
```

### 7.5 补题

系统会检查每个维度当前题量是否达到目标：

```python
target_count_for_dimension(dimension, config)
```

如果不足，会再次调用：

```python
generate_dimension_items(...)
```

为该维度补题。

补题会避免与已有题目高度重复。

## 8. 自检循环停止条件

自检循环最多运行：

```text
config.max_qc_iterations
```

也就是 CLI 的：

```text
--max-qc-iterations
```

循环会在以下情况提前停止：

```text
没有 QC rejected items
没有维度题量缺口
Planner review 认为 done=true
没有新的删除、移动、合并、拆分、补题动作
```

如果达到最大迭代次数还没完全理想，也会停止，避免无限循环。

## 9. 可选 Human-in-the-loop 审阅

Human-in-the-loop 默认关闭。

如果 CLI 指定：

```text
--human-review
```

并且当前不是 `--no-interactive`，Pipeline 会在 Runner 之前暂停，把当前已经通过 pre-run 自检循环的题集概览展示给用户。

这个位置在：

```text
Planner / Generator / QC pre-run loop 之后
Runner 之前
```

也就是说，用户看到的是“已经准备好运行”的版本。

展示内容包括：

```text
评估目标
维度数量
生成题目数量
QC accepted / rejected 数量
QC quality
每个维度的名称、描述、目标题量、当前题量、题型、item_requirements
前若干个 QC issues
```

用户可以：

```text
直接回车 / 输入 ok / 输入 approve
```

表示批准，继续进入 Runner。

也可以输入修改意见，例如：

```text
Split dimension X into A and B.
Delete item Y.
Add 2 code-sandbox items to dimension Z.
Make dimension A focus on multi-turn escalation.
Add a new dimension for adversarial recovery.
```

收到用户修改意见后，系统会调用同一套 Planner review 机制，让 Planner 把自然语言反馈转成结构化动作：

```text
delete_item_ids
move_items
dimension_updates
add_dimensions
merge_dimensions
split_dimensions
needs_more_items
```

然后继续执行：

```text
应用维度/题目修改
检查各维度题量缺口
如需新题，调用 generate_dimension_items
重新 QC
删除 QC-rejected items
必要时继续补题
```

Human review 最多会给用户 3 轮确认机会。每轮修改后都会重新展示更新后的题集概览，用户可以继续修改或批准。

如果没有 orchestrator key，系统无法可靠地把自由文本修改意见转换成结构化维度/题目操作，因此 human review 在这种情况下主要适合批准当前题集；复杂修改需要配置 orchestrator 模型。

## 10. Runner：执行最终题集

Runner 在 [evalclaw/runner.py](../evalclaw/runner.py)。

Pipeline 会把最终 dataset 和最终 qc_report 传给：

```python
run_eval(dataset, qc_report, config)
```

Runner 只执行：

```text
qc_report.passed_item_ids
```

对应的题目。

不同题型的执行方式：

```text
yes_no              直接 yes/no 评分
multiple_choice    抽取选项并规则评分
short_answer       简单字符串 / 数学式归一化评分
open_generation    LLM judge 评分
code_execution     运行 test_code sandbox
multi_turn         多轮对话后 judge 整体 transcript
agent_interaction  在 deterministic agent environment 中 action/observation loop
```

Runner 会输出 `EvalRun`：

```text
dataset
qc_report
results
summaries
runner_artifacts
created_at
```

## 11. Agent 和 Code Sandbox

Agent 环境在 [evalclaw/agent_envs.py](../evalclaw/agent_envs.py)。

当前支持：

```text
workspace
code_sandbox
```

`workspace` 是简单的房间 / 物品 / 背包 / 目标环境，用于测试状态跟踪和行动规划。

`code_sandbox` 是一个临时目录里的轻量代码环境，支持：

```json
{"action": "list_files", "args": {}}
{"action": "read_file", "args": {"path": "solution.py"}}
{"action": "write_file", "args": {"path": "solution.py", "content": "..."}}
{"action": "run_tests", "args": {}}
{"action": "final", "args": {"answer": "..."}}
```

注意：这是轻量本地 sandbox，不是强安全隔离容器。

## 12. lm-eval 互操作

EvaluationClaw 会在报告产物里写出 lm-eval 互操作文件，相关代码在：

```text
evalclaw/artifacts.py
evalclaw/lm_eval_runner.py
```

通常输出：

```text
lm-eval/*.jsonl
lm-eval/*.yaml
lm-eval/*.metadata.json
```

如果 `--runner lm-eval` 或 `--runner auto`，并且环境里安装了 `lm-eval`，还可以尝试调用 lm-eval harness。

不过当前 direct runner 仍是 EvaluationClaw 的主路径，尤其对于 open_generation、multi_turn、agent_interaction 这类需要 rubric 或环境评分的题型。

## 13. Loop 3：运行后的改进

Pre-run 自检循环解决的是“题集本身是否合理，是否覆盖目标维度”。

Loop 3 解决的是“模型跑完以后，是否要根据低分或错误继续深挖弱点”。

Loop 3 在 [evalclaw/improver.py](../evalclaw/improver.py)。

如果设置：

```text
--improve-iterations 1
```

Pipeline 会在第一次 run 之后调用：

```python
run_loop3_improvement(dataset, qc_report, run, config)
```

Loop 3 可做：

```text
regenerate_item
expand_weak_dimension
```

它会生成 improved dataset，再跑 QC，再跑 Runner。

所以当前有三层人工/自动改进机会：

```text
pre-run generation/QC loop    正式测试前修题集
human-in-the-loop review      可选人工批准或修改题集
Loop 3 improvement            正式测试后基于模型表现深挖弱点
```

## 14. Reporter 和产物

报告生成在：

```text
evalclaw/reporter.py
evalclaw/report_viewer.py
evalclaw/artifacts.py
```

Pipeline 最后会生成：

```text
evalclaw_<timestamp>.json     完整 BenchmarkPackage
evalclaw_<timestamp>.md       Markdown 报告
evalclaw_<timestamp>.html     自包含浏览器报告
manifest.json                 产物索引
lm-eval/*.jsonl               lm-eval 数据导出
lm-eval/*.yaml                lm-eval task 配置
lm-eval/*.metadata.json       EvaluationClaw metadata
```

完整包是 `BenchmarkPackage`，包含：

```text
goal
spec
dataset
qc_report
run
improvements
report
created_at
```

## 15. 当前流程中的关键设计取舍

### 14.1 Planner 不应无限追求完美

Pre-run review prompt 明确要求：

```text
不要追求完美。
只有明显偏题、明显重叠、明显过宽、明显题量不足时才修改。
```

这是为了避免 Planner 在合并 / 拆分维度上无穷迭代。

### 14.2 删除题目和审计信息

QC rejected 的题目会在 pre-run repair 中从当前 dataset 删除，避免进入 Runner。

不过生成 notes 和报告仍会保留 QC 统计与问题信息，便于审计为什么题集被改动。

### 14.3 子代理是架构语义，不是当前本地并发进程

代码里的“dimension item-generation worker”和“planner review worker”目前是 LLM prompt 角色，不是 Python 进程级或工具级 subagent。

也就是说：

```text
每个维度由独立 prompt 生成
相近 research 维度复用来源
生成后进入局部 QC 和整体 planner review
```

但它们不是操作系统级的并行 worker。以后可以继续把这些 prompt role 映射成真正的并发 subagent 或任务队列。

### 14.4 旧能力尽量保留

这次流程调整没有移除旧能力：

```text
HF discovery / ingest
web research
source-backed generation
LLM QC
static QC
multi_turn
agent_interaction
code_sandbox
Loop 3
lm-eval export
HTML report viewer
```

主要变化是把“正式运行前修题集”显式做成了核心流程。
