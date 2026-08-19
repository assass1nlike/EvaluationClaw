用户提出测评需求
    → 框架进行可选的深度研究，收集背景资料
    → Planner 设计完整的测评方案，定义维度与任务设计
    → 每个任务设计派生一个构题任务
    → TaskBuilder 构造具体题目
    → 系统将题目转换为 run-ready 格式
    → 全局 QC 检查题目质量并定向修复问题
    → 输出正式、可执行的 benchmark

源码发生变化后，应同步更新本文。

  ## 一、输入

**1. 用户目标(goal)**

它用自然语言描述“想测什么”。

如果判断 goal 为非英文，框架会调用一次 Planner 模型将其翻译为英文。这是其[系统提示词](#appendix-b-translation)和[ prompt 结构](#appendix-a)。

**2. 运行配置(BenchmarkConfig)**

定义 benchmark 的一些配置，例如：

  - Planner、TaskBuilder 所使用的模型
  - 题目数量、难度分布

这是其[完整字段](#appendix-g)。

  ## 二、可选的 Deep Research

若启用了 `--deep-research`，框架在规划前先围绕目标做研究，产出结构化简报 **ResearchBrief**（完整字段契约见[附录 H](#appendix-h)；四类 R1–R4 调用的执行过程与搜索后端边界见[附录 A.0](#appendix-a)）。

ResearchBrief 是 Benchmark Design Research 的中间产物，只保留会改变当前 benchmark 设计的证据：

- **dimensions**：有证据支持的可测量候选维度及其边界；
- **difficulty_factors**：可观察、可评分的任务困难因素及其构题影响；
- **task_patterns**：适合当前目标的任务形态、题型和评分方向；
- **source_recommendations**：可用于 source-backed 构题的已验证文档或数据集；
- **evidence**：外部观察、直接设计影响和来源 URL；
- **source_materials**：框架归档并保留正文的来源，供 TaskBuilder 经 `read_research_source(url)` 按需读取；
- **challenge_effort_anchors**：当前目标下 E1–E3 构题投入的具体含义。

它不是通用领域综述，不为了填充字段而搜索学术 gap、市场背景或与构题无关的观点。

Planner 只收到这份 brief 的紧凑索引（候选维度、设计证据、来源 URL、正文长度等），不收到来源全文——可见范围见[附录 C.1](#appendix-c)。需要来源细节的 TaskBuilder 可调用 `read_research_source(url)` 从本次归档读取正文，不必再次联网。

  ## 三、Planner 设计完整 BenchmarkPlan

  ### Planner 的输入

Planner 收到：用户目标、题量指导、支持的题型与执行环境、可选 Deep Research 紧凑结果。

Planner 收到的完整 prompt 结构见[附录 C](#appendix-c)；固定 prompt、完整 Planner Skill 和 JSON reference 见[附录 B.3](#appendix-b-planner)。

可用执行环境是 `workspace`、`code_sandbox`、`docker_workspace`、`gui_desktop`，各自能力边界见 Planner Skill 的「Choose the environment category」一节（[附录 B.3](#appendix-b-planner)）和各题型字段契约（[附录 D.3](#appendix-d-task-types)）。

  ### Planner 的输出：BenchmarkPlan

含两个设计层级，**Dimension** 定义互不重叠的测评维度，**TaskDesign** 定义某类具体任务的题型、题量、内容等。二者共同的完整字段见 `universal_format.json`（[附录 B.3](#appendix-b-planner)），各字段的精确语义（含 `task_count`、`scoring_contract` 等）见[附录 I.3](#appendix-i)。

  ## 四、按 TaskDesign 构造具体任务

每个 Planner 产出的 TaskDesign 派生一个独立 Builder job，全部 job 走同一套构题流程：收集来源 → 组装 payload 调用 TaskBuilder → 生成 TaskDefinition → 结构修复 → 整合出 run-ready TaskSuite。

  ### 1. 收集来源资源

为当前 TaskDesign 收集候选来源：来自 Planner 显式提供的 URL、TaskDesign 研究查询的网页搜索结果（它没有时，再考虑使用 Dimension 研究查询）；
来源不足且维度需研究时，框架会展开一个独立的构题前来源搜索阶段（触发条件与判定细节见[附录 D.0](#appendix-d)；TaskBuilder 在产出阶段自行返回的新资源随后也会并入 suite 的 resources）。

每个来源标准化为 `TaskResource`（完整字段见[附录 I.1](#appendix-i)）；如何呈现给 TaskBuilder 见 payload 的 `resources.context`（[附录 D.1](#appendix-d-payload)）。

  ### 2. 构造 TaskBuilder payload 并调用

组装一次完整模型调用：system prompt（base prompt、可选环境 Skill、可选构题研究 prompt，见[附录 B.4](#appendix-b-task-builder)）+ user message（即 payload，含 benchmark 上下文、当前 TaskDesign、题量/题型契约、可用来源、各题型字段契约、可用任务模型池、修复调用时的旧题与 QC 问题，逐字段见[附录 D.1](#appendix-d-payload)）。

若当前 TaskDesign 需来源研究（或允许网页研究的 E3 任务）且不是 QC 修复，调用在同一次对话里展开为工具循环：TaskBuilder 可调用 `read_research_source`、`search_web`、`fetch_url` 三个工具边搜边写，框架把工具结果追加进消息历史继续对话，直到 TaskBuilder 不再调用工具（工具 schema、预算与收尾见[附录 D.2](#appendix-d-tools)）。

无论是否启用研究工具，TaskBuilder 最终在同一次对话的末条回复里返回完整构题结果 `{"construction_notes":"...","resources":[],"tasks":[]}`，其中 `tasks` 每项都是一个完整 `TaskDefinition`。

  ### 3. 生成 TaskDefinition

每道题生成完整的执行前定义（`TaskDefinition`，字段概览见[附录 D.3](#appendix-d-task-types)）。评分指标属单题契约：choice/fill_blank 用确定性答案键，generation/multi_turn 用 rubric 与可选 Judge 证据，agent 用环境 evaluator、检查或任务特定 rubric；完整字段与各题型分支见[附录 D.3](#appendix-d-task-types)。

  ### 4. 构题阶段的结构修复

TaskBuilder 返回后立即做纯代码结构检查，按题型分支校验各种字段契约（完整清单见[附录 I.7](#appendix-i)，注意它与全局 QC 的静态检查[附录 I.4](#appendix-i)是两层）。发现错误后，把结构错误和上次返回内容交回 TaskBuilder，要求重新返回完整 JSON（repair 输入见[附录 D.4](#appendix-d-repair)）。

  ### 5. 构题整合出 run-ready TaskSuite

全部 Builder job 完成后，`build_task_suite`（`evalclaw/construction/suite.py`）按维度顺序把各 job 的 TaskDefinition 合并，并把每个 TaskDefinition 就地转换为 run-ready 的 `BenchmarkItem`（转换规则见[附录 I.8](#appendix-i)），同时检查全局任务 ID 唯一性、去重规范化资源、汇总 construction notes。

这一步就是构题阶段的**返回值**——`build_task_suite` 是第 1-4 步所在的构题主体，打包派生也被内化于此，所以整个构题流程只打包一次，QC 直接在 TaskSuite 上运行。产出的 `TaskSuite` 是 run-ready 的正式容器（完整字段见[附录 I.2](#appendix-i)），贯穿 QC、执行、报告全程；每个 `BenchmarkItem` 保留原始 `TaskDefinition` 到 `item.source_definition`（序列化时排除）供 QC repair 取回。`metadata.builder_job_id` 是任务到 Builder job 的唯一关联，`item.builder_job_id` / `item.task_design_id` 是其便捷属性。

  ## 五、全局 QC Gate 与修复

QC 分三层，由 `run_qc_gate` 串联：单题静态检查、数据集级检查、可选 LLM QC。

  ### 1. 单题静态检查（不调用 LLM）

逐题程序化检查 prompt 空/过短、choice 选项与答案一致、fill_blank 的 expected_text、generation/multi-turn 的 rubric、judge tool 受支持、agent 评分器/evaluator，以及多模态/science/task-agent/environment 等按 metadata 是否出现而进入的专项检查。这些专项检查不是对基础字段的通用校验，而是只有在题目带有对应 metadata 时才触发（例如只有 `metadata.multimodal` 存在才去验它的 schema_version/assets）；完整清单见[附录 I.6](#appendix-i)。

  ### 2. 数据集级检查（不调用 LLM）

检查重复 ID、完全/近似重复题、Dimension 是否有题、是否引用未知 Dimension、计划题型是否真正出现、source-backed 覆盖是否达标。完整检查清单见[附录 I.5](#appendix-i)。

  ### 3. 可选 LLM QC

若配置了 QC 模型，把题目、TaskDesign、Dimension 和必要 metadata 交给 LLM 审核。抽样、prompt 截断标记、metadata 压缩方式和完整用户 JSON 见[附录 E](#appendix-e)；固定 QC prompt 见[附录 B.5](#appendix-b-qc)。普通规模最多约 50 题；大规模按 `dimension_id` 分组轮转抽样（规则见[附录 E](#appendix-e)）。

  ### QC 输出

产出 `QcReport`（`issues`、`passed_item_ids`、`rejected_item_ids` 等，完整字段见[附录 I.6](#appendix-i)）。规则：`error` 是阻塞问题、题目进入 rejected；`warning` 允许通过但记录风险；`info` 仅记录；没有 error 且 rejected 为空时 `is_acceptable=True`。`issues` 中 `item_id` 为空的项是数据集级问题，不计入逐题通过/拒绝。

### 4. QC 定向修复循环

这和前面的“构题结构修复”是第二套独立循环。每一轮严格按以下顺序执行：

  1. **定位问题**：从 QC 报告里收集所有 `severity=error` 的 issue。
  2. **归因 Builder job**：对每条 error，用 `item_id` 在 TaskSuite 里找到题目，再取其 `builder_job_id` 得到所属 TaskDesign job。`item_id` 为空的 error 是数据集级问题，归因到全部 job（见下）。
  3. **组 revision**：对每个受影响的 job，只收集它自己的 error issues 和它自己的旧题目（从 `item.source_definition` 还原 `revision_context`），加一条「只替换列出的题、保留各自 id」的指令，见[附录 D.4](#appendix-d-repair)。
  4. **只重build这些 job**：调用普通 TaskBuilder，但 payload 带 `revision`，JobContext 里只有失败题，通过题不进入输入、不被修改。
  5. **合并候选**：把返回的 replacement 题按原 id 并入当前 TaskSuite（`_merge_repaired_suite`，replace 时同步更新 `source_definition`）。
  6. **重新跑完整 QC**：对合并后的整个 TaskSuite 重跑三层 QC。

判定与收敛：新候选只有在「阻塞 error 数量**严格减少**」时才会替换当前最佳版本；没有改善的修复被丢弃，下一轮仍从当前最佳版本继续。通过 QC 的题不会重新生成。最多运行 `max_qc_iterations` 轮。

修复结束后：如果能接受，benchmark 正式完成；仍有阻塞则默认抛异常拒绝产出 runner-ready benchmark；只有显式设置 `allow_incomplete_benchmark=true` 才保留不完整草稿。

  ## 六、可选人工审核

人工审核发生在**构题 + QC 循环之后、目标模型执行之前**：此时基准已通过 QC、可执行，但还没跑分。启用 `human_review` 时，用户可以在此处最多审核三轮，批准则进入 runner，否则提交修改意见重新构题。

review 的工作方式是：**保留未被触碰的题，只改该改的**。用户反馈先被解析成一个 Planner-role review 调用（`_planner_review`），再落到 `_apply_review` 解析成一个明确的构建计划——未受影响的题原样保留，单题操作精准落地，只有缺失的题才重新生成。因此可表达的修改意见有：

- **维度/数据集层**：拆分或新增 Dimension、调整能力边界与目标题数、合并维度、修改题型、改变多轮/环境要求、请求某维度补题（`needs_more_items`）。
- **单题归属层**：把某道题移到别的维度（`move_items`）、删除偏题（`delete_item_ids`）。
- **单题内容层**：改写某道具体题的 prompt/rubric/选项/答案/环境（`update_items`）——这是 review 提供的**单题级文本改写通道**，用户写明想改哪个 id、改成什么，TaskBuilder 以定向 revision 重写该题并保留其 id。

被删除、被改写、或其所在维度被结构性改变（合并/拆分/改动测量目标或边界/新增）的题不保留，交由定向构建补齐：改写题用 Builder 的 revision 机制就地重写，缺失题按各维度目标 `target_item_count` 补足。其余题原样保留，不做重复构题。

经过 review 后**不会全量重做已有题目**：

  评审后仅定向构建：
    -> 改写 `update_items` 命中的题（保留 id）
    -> 按 spec 目标补齐缺失的题
    -> 与保留的题合并成新的 run-ready TaskSuite
    -> 重新跑一遍 QC

人工反馈先进入一次 Planner-role dataset review 调用；`_apply_review` 把 review action 解析为保留/改写/补题计划，随后定向构建 + 重跑 QC。两次调用的消息组成见 [附录 F](#appendix-f)，review system prompt 见 [附录 B.6](#appendix-b-review)。

  ## 七、benchmark 完成时拥有什么

在进入执行阶段前，核心产物是：

   产物                含义

   ResearchBrief       可选的 Benchmark Design Research 设计证据
   BenchmarkPlan       Planner 的完整设计决策
   EvalSpec            benchmark 的总体规格
   TaskSuite           run-ready 的任务容器（含全部 BenchmarkItem 与 executor 所需规格）
   QcReport            哪些题通过、哪些题拒绝以及原因

其中 TaskSuite.tasks 包含全部构造结果，而 QcReport.passed_item_ids 明确规定哪些题可以执行。

执行阶段随后才会：

    1. 根据 QC 构造只含 passed items 的 ExecutionPlan。
    2. 探测 Docker、VM、GUI bridge 和多模态兼容性。
    3. 调用目标模型。
    4. 评分、汇总、Loop 3 改进和生成最终报告。

有环境的题在 benchmark 完成时已经包含环境规格、文件、工具和 evaluator，但真正创建容器、物化 VM 或连接桌面是在执行准备阶段。

最后一个实现上的细节是：当前 _persist_package() 位于运行与报告阶段之后。因此“benchmark 在内存中完成”和“完整 JSON/Markdown/HTML 文件落盘”不是同一时点。使用 --no-run 时不会调用目标模型，但仍会创建空的 EvalRun 和报告，再把整个 package 写入磁盘。

---

<a id="appendix-a"></a>
## 附录 A：执行前 LLM 调用总表

这里的“一次调用”指一次独立模型请求。除 TaskBuilder 工具循环会持续扩展 `messages` 外，
其余调用不会继承上一请求的对话历史。

| ID | 时机 | 角色 | System | User/后续消息 | Tools | 输出 |
|---|---|---|---|---|---|---|
| T1 | pipeline 开始 | Planner | `TRANSLATION_SYSTEM_PROMPT` | 原始 goal 字符串 | 无 | `{"english_goal":"..."}` |
| R1 | Deep Research 开始 | Research | query prompt | `{"goal","max_queries":4}` | 无 | 查询数组 |
| R2 | 每轮取得材料后 | Research | compress prompt | `{"goal","material"}` | 无 | evidence |
| R3 | 每轮压缩后 | Research | reflect prompt | `{"goal","evidence","round","max_rounds"}` | 无 | done/gaps/follow-up |
| R4 | 研究循环结束 | Research | synthesis prompt | `{"goal","evidence","known_sources"}` | 无 | ResearchBrief 主体 |
| P1 | 初次规划 | Planner | base + Planner Skill + format reference | `<PLANNER_RESOURCES>` | 无 | 完整 plan JSON |
| P2 | 计划解析/审计失败 | Planner | 与 P1 相同 | P1 输入 + repair file | 无 | 完整替换 plan |
| B1 | 每个 TaskDesign | TaskBuilder | base + 可选环境 Skill + 可选研究补充 | TaskBuilder payload JSON | 可选 | resources/tasks |
| B2 | 构题研究 | TaskBuilder | 与 B1 相同 | user + assistant tool call + tool result | 3 个研究工具 | 最终完整 JSON |
| B3 | Builder 输出截断 | TaskBuilder | 与 B1 相同，关闭研究 | payload + truncation recovery | 无 | 紧凑替换 JSON |
| B4 | Builder 结构不合法 | TaskBuilder | 与 B1 相同 | payload + repair | 依条件 | 完整替换 JSON |
| Q1 | 配置 QC 模型 | QC | `QC_SYSTEM_PROMPT` | 抽样数据集 JSON | 无 | issues/summary |
| B5 | QC 拒绝具体题 | TaskBuilder | 普通 Builder system | 仅失败题的 revision payload | 无研究工具 | 保持 ID 的替换题 |
| H1 | 人工反馈 | Planner | review prompt + 可选反馈说明 | 数据集摘要/QC/item excerpts | 无 | review actions |
| H2 | 改写/补题 | TaskBuilder | 普通 Builder system | 定向 revision（update_items）或按缺失量裁剪 spec 生成的 payload | 视情况 | 保持 ID 的改写题 / 补齐题 |

### A.0 Deep Research 执行过程

Deep Research 由四类独立 LLM 调用串成，不是一次长对话；搜索与抓取发生在调用之间（非 LLM）：

1. **R1 初始查询**：Research 角色 LLM 收到 `{"goal", "max_queries"}`，生成首批搜索查询。
2. **搜索与抓取（非 LLM）**：`web_search`、`fetch_url_text` 与 HuggingFace discovery 按查询取回原始材料。
3. **R2 材料压缩**：Research 角色 LLM 把本轮材料压缩成带设计影响和来源 URL 的 evidence。
4. **R3 缺口反思**：Research 角色 LLM 判断是否还有关键缺口；有则生成下一轮查询，否则结束循环。
5. **R4 最终综合**：Research 角色 LLM 把累计 evidence 综合成 ResearchBrief 的设计字段。

四类调用的精确 `system`/`user` 组成见上方「执行前 LLM 调用总表」的 `R1-R4` 行与附录 B.2；`web_search`、`fetch_url_text` 和 HuggingFace discovery 是搜索后端而非角色 LLM 调用，其边界见下方「边界说明」。

边界说明：

- `web_search()`、`fetch_url_text()`、HuggingFace discovery 不是 EvaluationClaw 角色 LLM 调用。
- `search_backend=gemini` 时，搜索后端内部可能调用带 grounding 的 Gemini；它仍属于搜索后端，不是 R1-R4。
- provider/model/API key/base URL/token 上限/reasoning effort 是调用参数，不是模型可见文本。
- Python 对象只有在序列化、拼入 system 或作为工具结果追加后，模型才看得到。
- Planner 不看到 target models；模型返回后框架才写入 `BenchmarkPlan.subjects`。
- Planner 只看到紧凑 ResearchBrief，不看到 `source_materials[].content` 全文。

### A.1 T1：Goal 英文标准化

模型看到：

~~~text
system = TRANSLATION_SYSTEM_PROMPT
messages = [
  {"role": "user", "content": 原始 goal 原文}
]
tools = 无
~~~

user message 不是 JSON，也不包含 BenchmarkConfig。模型应返回：

~~~json
{"english_goal": "完整保留意图、专有名词、范围、约束和精确数量的英文目标"}
~~~

框架用 `extract_json()` 解析并要求 `english_goal` 非空。JSON 不合法或结果为空时直接报错。

这一步只是调用 Planner 的模型来翻译，内容不会作为历史消息后续传给 Planner.

### A.2 R1-R4：Deep Research 的四类独立输入

#### R1 初始查询

~~~json
{
  "goal": "T1 产出的英文 goal",
  "max_queries": 4
}
~~~

若调用或 JSON 解析失败，框架本地回退为 `goal`、`goal + benchmark dataset`、
`goal + evaluation examples` 三条查询。

#### 搜索与抓取，非 LLM

每轮最多处理 4 条查询。每条搜索结果给 R2 的 material 形式为：

~~~json
{"query": "原查询", "content": "搜索后端 synthesis，最多 3000 字符"}
~~~

本轮收集 citation 后最多抓取 3 个尚未抓取的 URL；抓取成功的 material 形式为：

~~~json
{"url": "https://...", "title": "...", "content": "可读正文，最多 50000 字符"}
~~~

这些步骤不把搜索结果自动塞进 R1/R3/R4，只在下面明确的 JSON 字段中传入。

#### R2 材料压缩

~~~json
{
  "goal": "英文 goal",
  "material": [
    {"query": "...", "content": "..."},
    {"url": "https://...", "title": "...", "content": "..."}
  ]
}
~~~

每个研究轮次单独调用一次。期望输出 `{"evidence":[...]}`，每项包含外部观察、直接设计影响和
已知来源 URL。失败时框架保留每个 material 的前 400 字符作为需要进一步核验的设计线索，而不是
把它包装成未经验证的领域结论。

#### R3 缺口反思

~~~json
{
  "goal": "英文 goal",
  "evidence": [
    {"observation": "...", "design_implication": "...", "source_urls": ["..."]}
  ],
  "round": 1,
  "max_rounds": "config.max_research_iterations，至少 1"
}
~~~

输出：

~~~json
{
  "done": false,
  "gaps": ["..."],
  "follow_up_queries": ["最多 4 条"]
}
~~~

反思失败时本地结果为 `done=true`，避免盲目继续循环。

#### R4 最终综合

~~~json
{
  "goal": "英文 goal",
  "evidence": [
    {"observation": "...", "design_implication": "...", "source_urls": ["..."]}
  ],
  "known_sources": [
    {"title": "最多 20 个 citation 的标题", "url": "..."},
    {"title": "最多 5 个 HF 候选的标题", "url": "..."}
  ]
}
~~~

R4 最多用同一 payload 尝试两次。模型输出当前 Benchmark Design Research Brief 的设计字段；若两次都
失败，Python 从累计 evidence、搜索 citations 和 HuggingFace 候选构造最小 fallback brief。无论模型
综合是否成功，`source_materials` 都由框架覆盖写入：它只包含搜索阶段真实抓取并按 URL 去重后保留的正文，
不是 R4 模型生成内容。

<a id="appendix-b"></a>
## 附录 B：固定 prompt 与动态 `system` 组成

以下代码块保留当前源码原文。模型实际收到的是相应字符串常量的值，不包括模块注释、import 和
`__all__`。动态 Skill/reference 按本附录给出的拼接公式处理。

> 折叠块维护约束：为兼容 Typora 的严格 Markdown 解析，`<details>`、`<summary>`、
> `<pre><code>` 和 `</details>` 必须保持在同一个连续 raw-HTML 块中，内部不能插入物理空行。
> 源码原有空行使用不可见的 `<!-- -->` 占位；不要把这些占位符删除或重新排版，否则 Typora
> 可能只渲染折叠三角，而把后续源码拆到可折叠节点之外。

<a id="appendix-b-translation"></a>

### B.1 Goal 翻译与 Planner base
<details><summary>完整源码：<code>evalclaw/prompts/planner.py</code></summary><pre><code class="language-text">TRANSLATION_SYSTEM_PROMPT:
<!-- -->
You translate and normalize evaluation requests for EvaluationClaw.
Return JSON only: {&quot;english_goal&quot;: &quot;...&quot;}.
<!-- -->
If the request is already English, return it unchanged. Otherwise translate it
into concise, precise English before it is used by the planner. Preserve all
technical intent, scope, constraints,
model names, budget words, benchmark names, domain terms, and every explicit
quantity. Render task counts unambiguously: for example, a singular quantity
that constrains the requested count must become &quot;exactly one task&quot;, not merely
&quot;a task&quot;. If the user is asking to evaluate a non-English capability, describe
that requirement in English rather than replacing it with an English-only task.
<!-- -->
BENCHMARK_PLANNER_SYSTEM_PROMPT:
<!-- -->
You are an EvaluationClaw planning agent. Follow the active Planner Skill
exactly. Read the supplied resources by their declared paths and treat their
contents as authoritative. Use any tools explicitly made available by the
runtime when they are relevant. Do not construct final benchmark tasks.</code></pre></details>


<a id="appendix-b-research"></a>

### B.2 Deep Research 四个 prompt
<details><summary>完整源码：<code>evalclaw/prompts/research.py</code></summary><pre><code class="language-text">RESEARCH_QUERY_SYSTEM_PROMPT:
<!-- -->
You generate initial web-search queries for EvaluationClaw's Benchmark Design
Research stage. Research only what can change the construction of a benchmark
for the stated evaluation goal.
<!-- -->
Input JSON: {"goal": "...", "max_queries": N}
<!-- -->
Return pure JSON only: {"queries": ["...", "..."]}
<!-- -->
Rules:
- Emit at most max_queries self-contained, specific queries.
- Cover measurable capability boundaries, observable failure modes and
  difficulty factors, useful task/scoring patterns, and authoritative sources
  that can ground concrete tasks.
- Do not search broad field history, academic novelty, market context, or
  generic benchmark gaps unless the result changes a design choice.
<!-- -->
RESEARCH_COMPRESS_SYSTEM_PROMPT:
<!-- -->
You compress raw research material into evidence for EvaluationClaw's
Benchmark Design Research stage.
<!-- -->
Input JSON: {"goal": "...", "material": [{"query"|"url": ..., "content": "..."}]}
<!-- -->
Return pure JSON only:
{"evidence": [{"observation": "...", "design_implication": "...", "source_urls": ["..."]}]}
<!-- -->
Rules:
- Pair each external observation with a concrete consequence for a dimension,
  task input, environment, interaction, scoring rule, or source choice.
- Use only URLs present in the supplied material.
- Drop broad field commentary, unsupported opinions, marketing fluff, and
  observations with no design consequence.
- Emit at most 12 evidence entries per call.
<!-- -->
RESEARCH_REFLECT_SYSTEM_PROMPT:
<!-- -->
You review accumulated evidence for EvaluationClaw's Benchmark Design Research
stage and decide whether more research is needed.
<!-- -->
Research is sufficient when it supports candidate measurable dimensions and
boundaries, observable difficulty factors, useful task/scoring patterns, and
sources for source-backed construction. Do not search merely to fill a field
or produce a generic account of the domain.
<!-- -->
Input JSON: {"goal": "...", "evidence": [{"observation": "...", "design_implication": "...", "source_urls": ["..."]}], "round": N, "max_rounds": M}
<!-- -->
Return pure JSON only:
{"done": true|false, "gaps": ["missing design area", ...], "follow_up_queries": ["...", ...]}
<!-- -->
Rules:
- done=true when additional research is unlikely to change dimensions, task
  patterns, difficulty factors, or source choices.
- When done=false, list only design-relevant gaps and emit up to 4 targeted
  follow-up queries. Do not repeat answered questions.
<!-- -->
RESEARCH_SYNTHESIS_SYSTEM_PROMPT:
<!-- -->
You synthesize the final ResearchBrief from accumulated evidence. This is a
Benchmark Design Research artifact, not a general field survey or literature
review. Every entry must help the Planner or Task Builder make a concrete design
decision.
<!-- -->
Input JSON: {"goal": "...", "evidence": [{"observation", "design_implication", "source_urls"}], "known_sources": [{"title", "url"}]}
<!-- -->
Return pure JSON only, exactly this shape (omit unsupported sections; never
invent URLs):
{
  "dimensions": [{"name": "...", "measurement_target": "...", "boundary": "...", "task_shapes": ["..."]}],
  "difficulty_factors": [{"factor": "...", "observable_signal": "...", "design_implication": "..."}],
  "task_patterns": [{"name": "...", "description": "...", "suitable_task_types": ["..."], "scoring_direction": "..."}],
  "source_recommendations": [{"title": "...", "url": "...", "why_useful": "..."}],
  "evidence": [{"observation": "...", "design_implication": "...", "source_urls": ["..."]}],
  "challenge_effort_anchors": {"E1": "...", "E2": "...", "E3": "..."},
  "research_notes": "uncertainty, open design questions, and coverage limits"
}
<!-- -->
Rules:
- Dimensions must be non-overlapping, measurable candidates for this goal, not
  an exhaustive survey of the field.
- Difficulty factors need observable signals; task patterns need scoring direction.
- Source recommendation URLs and evidence source_urls must appear in known_sources.
- Challenge-effort anchors describe construction effort for this goal.</code></pre></details>


<a id="appendix-b-planner"></a>
### B.3 Planner Skill 和输出 reference

运行时 `system` 的精确结构：

~~~text
BENCHMARK_PLANNER_SYSTEM_PROMPT.rstrip()
+ "\n\n<ACTIVE_EVALCLAW_PLANNER_SKILL>\n"
+ 完整 SKILL.md
+ "\n</ACTIVE_EVALCLAW_PLANNER_SKILL>\n\n"
+ "<REFERENCE_FILE path=\"reference/universal_format.json\">\n"
+ 完整 universal_format.json
+ "\n</REFERENCE_FILE>"
~~~
<details><summary>Planner Skill：<code>evalclaw/planning/skills/design-benchmark-blueprints/SKILL.md</code></summary><pre><code class="language-markdown">You are the Planner of the Evalclaw framework. Evalclaw is an automated evaluation framework that can automatically create benchmark tasks and then run evaluations after a user provides an evaluation request in natural language.
<!-- -->
As the Planner, your task is to transform the user&#39;s natural-language evaluation request into a complete benchmark content design. You must specify the evaluation dimensions corresponding to the request and the concrete TaskDesigns within each dimension, including task types, task counts, scoring methods, and all construction requirements. The framework sends every TaskDesign to one independent Task Builder call; you do not group, batch, split, or allocate TaskDesigns into Builder work packages. Detailed requirements follow.
<!-- -->
# Design Benchmark Content and TaskDesigns
<!-- -->
## Core Responsibilities
<!-- -->
First design the benchmark itself from the request: specify what should be measured and what should not be measured, establish dimensions that do not overlap and that sufficiently cover the request, and decide the content, task types, task counts, scoring methods, and so on that each dimension will actually assess.
<!-- -->
Bring the content design to a level of detail suitable for guiding task construction. For simple, homogeneous batches of tasks, plan the content scope, coverage distribution, variation requirements, and so on for the task group. For a small number of complex tasks, provide a concrete concept for each task. Do not provide only dimension names and task counts, but also do not write every complete task on the Builder&#39;s behalf.
<!-- -->
Ultimately output the dimensions and their TaskDesigns. Each TaskDesign is already the complete instruction for one Task Builder call. If two requested task groups differ in content design, task type, scoring, environment, source strategy, or another substantive construction contract, represent them as two TaskDesigns. Do not perform any additional scheduling or workload allocation.
<!-- -->
## Inputs
<!-- -->
Use the following information together:
<!-- -->
- The user&#39;s natural-language evaluation request; see `resources/instruction.md`.
- Constraints such as the total task count specified by the user and the available task types; also see `resources/instruction.md`.
- An optional pre-generated deep-research brief; see `resources/deepresearch`. It is the result returned after calling the DeepResearch tool:
  - It searches comprehensive information and gives you richer references and supplements for dimension planning.
  - It can supplement your own knowledge when you do not know enough about the relevant domain.
  - Its links and similar materials can serve as content sources when concrete tasks are constructed and can be placed in the relevant TaskDesign&#39;s `source_plan` for the Task Builder to use.
<!-- -->
## Workflow
<!-- -->
### Step One: Understand the Evaluation Goal
<!-- -->
Understand the natural-language request provided by the user and identify:
<!-- -->
- The capabilities or behaviors to measure.
- Adjacent capabilities that should not be measured.
- What testing content and methods should be used to achieve the evaluation goal.
<!-- -->
If the request is genuinely ambiguous, make the smallest explainable completion. Do not introduce common dimensions unrelated to the user&#39;s goal on your own, and do not add off-topic complexity.
<!-- -->
### Step Two: Design the Dimension System
<!-- -->
Divide dimensions according to the measurement goal so that different dimensions do not obviously overlap and the resulting whole provides good coverage of the evaluation request. For each dimension, explain:
<!-- -->
- What capability this dimension measures independently.
- Its main content.
- What forms of task construction and scoring are suitable.
<!-- -->
### Step Three: Specify the Actual Tasks Within Each Dimension
<!-- -->
Further design the substantive content that makes up each dimension. Determine:
<!-- -->
- All included task types and their respective counts.
- The content design of each task group.
<!-- -->
Use only these task types:
<!-- -->
- `choice`: two or more candidate choices and one or more correct choice ids; two choices can express a binary judgment, and multiple correct ids express multi-select.
- `fill_blank`: one uniquely formatted expected text, scored by exact text match after trimming surrounding whitespace.
- `generation`: an open response scored by a Judge against a rubric. When useful, the Judge may use registered external-verification tools such as Python tests.
- `multi_turn`: a scripted or response-adaptive dialogue scored over the complete transcript.
- `agent`: a task in which the target acts through tools in an executable, resettable environment and is scored from the resulting state, artifacts, answer, or trajectory.
<!-- -->
This says &quot;each task group&quot; rather than &quot;each task&quot; because one description may either describe one task relatively concretely or cover multiple similar tasks as a whole. For example, it may describe one complex and difficult agent task in some detail, or it may require ten multiple-choice questions about a certain knowledge point. Ultimately, every task must belong to a &quot;group&quot; described at a level of detail suitable for guiding construction according to the task&#39;s complexity.
<!-- -->
Make the sum of the task counts across all dimensions equal the user&#39;s target task count. Allocate task counts according to coverage value and measurement importance; do not divide them evenly by default.
<!-- -->
Use only these `challenge_effort` levels:
<!-- -->
- `E1`: simple, direct construction with minimal planning.
- `E2`: moderate planning with meaningful edge cases.
- `E3`: maximum construction effort, with deep planning, source use when helpful, difficult content, and robust evaluation design.
<!-- -->
The framework has exactly these three effort levels.
<!-- -->
Use `environment_requirements` only for `agent` tasks, choosing the environment category that provides the required tools or state. `multi_turn` tasks express their dialogue behavior through `interaction_requirements` and do not use an execution environment. Leave `environment_requirements` empty for `choice`, `fill_blank`, `generation`, and `multi_turn`; if executable interaction is essential, design an `agent` task instead.
<!-- -->
Choose the environment category according to its actual runtime capabilities:
<!-- -->
- `workspace` is only the built-in room, inventory, item inspection, and outgoing-bin runtime. It cannot edit files, run commands or validators, browse, or add custom tools.
- `code_sandbox` supports reading and writing files and running tests in a standard code workspace.
- `docker_workspace` supports task-specific packages, services, shell commands, browser automation, and executable validators in a container.
- `gui_desktop` supports mouse/keyboard desktop interaction and may request a locally or remotely provisioned VM when a specific operating system or application state is required.
<!-- -->
If a task requires editable artifacts, scripts, schemas, hashes, tests, or other executable validation, do not select `workspace`; select `code_sandbox` or `docker_workspace` according to the required software and services.
<!-- -->
For every `multi_turn` TaskDesign, set `interaction_requirements.followup_mode` to exactly `adaptive` or `scripted`. Use `adaptive` when later turns must respond to the target&#39;s actual replies, and `scripted` only when predetermined follow-up turns are substantively appropriate. Preserve any explicit user requirement about this choice.
<!-- -->
At the end of this step, determine the JSON for every task group and express all information in your design through JSON fields. The complete field set for one task-group JSON object is `plan.dimensions[].task_designs` in `reference/universal_format.json`. This field specification is shared by all tasks, so an individual task does not necessarily need—and usually will not need—to fill every field.
<!-- -->
### Step Four: Perform a Global Audit
<!-- -->
After designing all tasks, check that:
<!-- -->
- The complete content design **fully covers the user&#39;s evaluation goal and satisfies the request**.
- Every task in every dimension has a relatively concrete content design, suited to its complexity and capable of guiding construction, so that the information in `plan.dimensions[].task_designs` approximately communicates the requirements for the tasks instead of remaining overly general.
- Every JSON field follows the format requirements, task counts match, and so on.
<!-- -->
If you find that your design does not satisfy these requirements, revise it.
<!-- -->
### Step Five: Output the Complete Planning File
<!-- -->
Return one complete JSON object that strictly follows `reference/universal_format.json`. Include the complete benchmark-level plan, every dimension, and every TaskDesign produced in Step Three. Do not add Blueprint, batch, job-allocation, grouping-rationale, or workload-partition fields; the framework deterministically creates one concurrent Builder job for each TaskDesign after planning.
<!-- -->
Your entire final response must be the contents of the planning JSON file. Return pure JSON only, without Markdown fences, commentary, an audit narrative, or any text before or after the JSON.</code></pre></details>


<details><summary>Planner JSON reference：<code>evalclaw/planning/skills/design-benchmark-blueprints/reference/universal_format.json</code></summary><pre><code class="language-json">{
  &quot;plan&quot;: {
    &quot;id&quot;: &quot;benchmark_plan_id&quot;,
    &quot;objective&quot;: &quot;What the benchmark as a whole measures.&quot;,
    &quot;constraints&quot;: [&quot;Benchmark-wide requirements and exclusions.&quot;],
    &quot;planner_notes&quot;: &quot;Optional decisions that apply across the plan.&quot;,
    &quot;dimensions&quot;: [
      {
        &quot;id&quot;: &quot;dimension_id&quot;,
        &quot;name&quot;: &quot;Pick a concise, descriptive name for this dimension.&quot;,
        &quot;measurement_target&quot;: &quot;The capability or behavior measured independently by this dimension, including all content that tasks in the dimension must cover.&quot;,
        &quot;boundary&quot;: &quot;The dimension&#39;s scope boundary, including excluded content, adjacent capabilities, confounds, and forbidden drift.&quot;,
        &quot;approach&quot;: &quot;How tasks in this dimension should elicit and measure the target capability.&quot;,
        &quot;task_designs&quot;: [
          {
            &quot;id&quot;: &quot;task_design_id&quot;,
            &quot;task_type&quot;: &quot;&lt;one of: choice | fill_blank | generation | multi_turn | agent; the task type this design will produce concrete tasks as&gt;&quot;,
            &quot;task_count&quot;: &quot;The total number of concrete tasks this single TaskDesign must generate.&quot;,
            &quot;challenge_effort&quot;: &quot;&lt;one of: E1 | E2 | E3; the intended construction effort: E1=simple direct, E2=moderate with edge cases, E3=max effort with deep planning and source use&gt;&quot;,
            &quot;content_design&quot;: {
              &quot;purpose&quot;: &quot;What the covered task or tasks measure within the dimension.&quot;,
              &quot;description&quot;: &quot;A concrete concept for one complex task, or a shared content description for multiple simpler tasks.&quot;,
              &quot;coverage_requirements&quot;: [&quot;Required content coverage within these tasks.&quot;],
              &quot;variation_requirements&quot;: [&quot;How multiple tasks using this description must differ.&quot;],
              &quot;task_relationships&quot;: [&quot;Optional relationships or dependencies among the covered tasks.&quot;],
              &quot;exclusions&quot;: [&quot;Content, shortcuts, or confounds these tasks must avoid.&quot;]
            },
            &quot;input_requirements&quot;: {
              &quot;description&quot;: &quot;What information or materials the covered tasks receive.&quot;,
              &quot;modalities&quot;: [&quot;text&quot;, &quot;image&quot;, &quot;audio&quot;, &quot;video&quot;, &quot;table&quot;, &quot;files&quot;],
              &quot;format_or_schema&quot;: &quot;Required input format, structure, or schema.&quot;,
              &quot;shared_inputs&quot;: [&quot;Inputs shared by the covered tasks.&quot;],
              &quot;per_task_variation&quot;: &quot;How inputs should vary among concrete tasks.&quot;,
              &quot;asset_requirements&quot;: [
                {
                  &quot;id&quot;: &quot;input_asset_id&quot;,
                  &quot;kind&quot;: &quot;dataset&quot;,
                  &quot;role&quot;: &quot;Why the asset is needed by the task.&quot;,
                  &quot;visibility&quot;: &quot;task_visible or runner_private&quot;,
                  &quot;properties&quot;: {
                    &quot;domain_specific_property&quot;: &quot;Required value&quot;
                  }
                }
              ]
            },
            &quot;interaction_requirements&quot;: {
              &quot;mode&quot;: &quot;single_turn, multi_turn, tool_use, environment_interaction, or mixed&quot;,
              &quot;followup_mode&quot;: &quot;For multi_turn only: adaptive or scripted.&quot;,
              &quot;roles&quot;: [&quot;Roles participating in the interaction.&quot;],
              &quot;statefulness&quot;: &quot;What state persists and how it may change.&quot;,
              &quot;turn_or_step_policy&quot;: &quot;Expected turn structure, step policy, or interaction horizon.&quot;,
              &quot;allowed_action_or_tool_categories&quot;: [&quot;Capabilities the evaluated subject may use.&quot;],
              &quot;observation_model&quot;: &quot;What feedback or observations actions should produce.&quot;,
              &quot;completion_condition&quot;: &quot;How the interaction reaches a successful or terminal state.&quot;,
              &quot;trajectory_requirements&quot;: [&quot;Required, forbidden, or score-relevant process behavior.&quot;]
            },
            &quot;environment_requirements&quot;: {
              &quot;category&quot;: &quot;workspace, code_sandbox, docker_workspace, or gui_desktop; agent tasks only&quot;,
              &quot;purpose&quot;: &quot;Why an execution environment is necessary.&quot;,
              &quot;initial_state&quot;: &quot;The high-level state in which each task must begin.&quot;,
              &quot;required_capabilities&quot;: [&quot;Capabilities the environment must expose.&quot;],
              &quot;required_software_or_services&quot;: [&quot;Software or services needed to make the task possible.&quot;],
              &quot;network_requirements&quot;: &quot;Whether and why network access is needed.&quot;,
              &quot;fixture_asset_ids&quot;: [&quot;input_asset_id&quot;],
              &quot;constraints&quot;: [&quot;Environment properties the Builder must preserve or avoid.&quot;]
            },
            &quot;output_requirements&quot;: {
              &quot;response_modes&quot;: [&quot;choice&quot;, &quot;text&quot;, &quot;structured_data&quot;, &quot;code&quot;, &quot;artifact&quot;, &quot;state_change&quot;, &quot;trajectory&quot;],
              &quot;description&quot;: &quot;What a successful response or completed task should produce.&quot;,
              &quot;format_or_schema&quot;: &quot;Required output format, schema, or interface.&quot;,
              &quot;required_components&quot;: [&quot;Required parts of the response or result.&quot;],
              &quot;artifacts&quot;: [
                {
                  &quot;kind&quot;: &quot;file, dataset, report, media, repository change, or another deliverable&quot;,
                  &quot;description&quot;: &quot;What the artifact must contain or accomplish.&quot;,
                  &quot;format&quot;: &quot;Required format or extension.&quot;,
                  &quot;required&quot;: true
                }
              ],
              &quot;constraints&quot;: [&quot;Output properties, limits, or forbidden shortcuts.&quot;]
            },
            &quot;scoring_contract&quot;: {
              &quot;components&quot;: [
                {
                  &quot;method&quot;: &quot;exact answer, rubric, executable test, artifact inspection, final-state check, trajectory check, comparison, or another method&quot;,
                  &quot;oracle_type&quot;: &quot;The kind of reference, evaluator, invariant, or expected state used as the oracle.&quot;,
                  &quot;criteria&quot;: [&quot;The substantive criteria that determine correctness or quality.&quot;],
                  &quot;partial_credit&quot;: &quot;Whether partial credit is allowed and what it should represent.&quot;,
                  &quot;required_evidence&quot;: [&quot;Evidence the evaluator must inspect.&quot;],
                  &quot;verification_direction&quot;: &quot;How the Builder should make scoring deterministic or reproducible.&quot;
                }
              ],
              &quot;aggregation&quot;: &quot;How multiple checks, turns, artifacts, trials, or sub-scores combine.&quot;,
              &quot;trial_policy&quot;: &quot;Optional repetition, sampling, or stochastic-evaluation requirements.&quot;,
              &quot;failure_conditions&quot;: [&quot;Conditions that must result in task failure.&quot;]
            },
            &quot;source_plan&quot;: {
              &quot;strategy&quot;: &quot;self_contained, generated, source_backed, imported_dataset, or mixed&quot;,
              &quot;search_queries&quot;: [&quot;Queries the Builder may use to find suitable material.&quot;],
              &quot;suggested_urls&quot;: [&quot;https://example.com/verified-source&quot;],
              &quot;requirements&quot;: [&quot;Authority, recency, reproducibility, licensing, or provenance requirements.&quot;],
              &quot;asset_source_overrides&quot;: [
                {
                  &quot;asset_id&quot;: &quot;input_asset_id&quot;,
                  &quot;strategy&quot;: &quot;generated, provided, imported, or source-backed&quot;
                }
              ],
              &quot;usage_guidance&quot;: [&quot;How sources should inform tasks without being copied mechanically.&quot;]
            },
            &quot;construction_requirements&quot;: [&quot;Requirements for turning this description into the requested number of complete tasks.&quot;],
            &quot;type_specific_requirements&quot;: {
              &quot;protocol&quot;: &quot;Optional namespaced protocol or task-type extension identifier.&quot;,
              &quot;requirements&quot;: {
                &quot;extension_field&quot;: &quot;Only requirements that cannot be expressed by the universal fields above.&quot;
              }
            },
            &quot;metadata&quot;: {}
          }
        ]
      }
    ]
  }
}</code></pre></details>


<a id="appendix-b-task-builder"></a>

### B.4 TaskBuilder base、构题研究与环境 Skill

运行时 `system`：

~~~text
TASK_BUILDER_PROMPT
+ 若 builder_job.requires_environment:
    "\n\n" + environment_skill_system_prompt(builder_job)
+ 若 research_enabled:
    "\n\n" + TASK_BUILDER_RESEARCH_PROMPT
~~~

`environment_skill_system_prompt()` 包含完整环境 Skill、当前 TaskDesign 到 reference
路由 JSON，以及只被该路由选中的 reference 全文。因此不同 Builder job 的 system 可能不同。
<details><summary>TaskBuilder base prompt：<code>evalclaw/prompts/task_builder.py</code></summary><pre><code class="language-text">TASK_BUILDER_PROMPT:
<!-- -->
You are the EvaluationClaw Task Builder.
<!-- -->
Implement one Planner-authored TaskDesign. When revision is present, implement
only the listed replacement tasks from that TaskDesign. Generate the number and
task type required by task_builder_contract. Treat the TaskDesign, resources,
and response schema as authoritative. A TaskDesign with task_count greater than
one describes a group of distinct tasks that all follow that design. Do not
invent optional sections that the TaskDesign does not request.
<!-- -->
Materialize every dependency implied by each concrete task. Include or bind the
actual inputs, assets, files, services, interaction state, and scoring evidence
needed to perform and evaluate it; do not merely describe a dependency that the
target or evaluator cannot access. Keep target-visible material separate from
runner-private setup and oracle material.
<!-- -->
Use English unless the evaluation explicitly tests another language. Return
pure JSON only, with no markdown. The top-level object must contain:
{
  &quot;construction_notes&quot;: &quot;...&quot;,
  &quot;resources&quot;: [],
  &quot;tasks&quot;: [
    {
      &quot;id&quot;: &quot;...&quot;,
      &quot;dimension_id&quot;: &quot;...&quot;,
      &quot;task_type&quot;: &quot;...&quot;,
      &quot;title&quot;: &quot;...&quot;,
      &quot;content_summary&quot;: &quot;...&quot;,
      &quot;description&quot;: &quot;...&quot;,
      &quot;prompt&quot;: &quot;...&quot;,
      &quot;resource_ids&quot;: [],
      &quot;choices&quot;: [{&quot;id&quot;: &quot;A&quot;, &quot;text&quot;: &quot;...&quot;}],
      &quot;correct_choice_ids&quot;: [],
      &quot;expected_text&quot;: null,
      &quot;rubric&quot;: null,
      &quot;judge_tools&quot;: [],
      &quot;output_contract&quot;: {},
      &quot;system_prompt&quot;: &quot;&quot;,
      &quot;interaction&quot;: {},
      &quot;scoring&quot;: {
        &quot;method&quot;: &quot;...&quot;,
        &quot;instructions&quot;: &quot;...&quot;,
        &quot;pass_criteria&quot;: &quot;...&quot;,
        &quot;partial_criteria&quot;: &quot;...&quot;,
        &quot;fail_criteria&quot;: &quot;...&quot;,
        &quot;score_levels&quot;: {},
        &quot;oracle_notes&quot;: &quot;...&quot;
      },
      &quot;challenge_effort&quot;: &quot;E3&quot;,
      &quot;tags&quot;: [],
      &quot;metadata&quot;: {
        &quot;challenge_effort_self_assessment&quot;: {
          &quot;requested_effort&quot;: &quot;E3&quot;,
          &quot;meets_requested_effort&quot;: true,
          &quot;rationale&quot;: &quot;...&quot;
        }
      }
    }
  ]
}
<!-- -->
For initial construction, the tasks array length and per-type counts must
exactly match the TaskDesign. For QC repair, they must instead exactly match
task_builder_contract.task_schema.required_task_type_counts.
Generate exactly task_count concrete tasks for every TaskDesign. In each task&#39;s
metadata, set task_design_id to the id of the TaskDesign it implements; the
per-design counts must exactly match
task_builder_contract.task_schema.required_task_design_counts. Populate only
the fields required by the task&#39;s type and TaskDesign. Choice and fill-blank
tasks use their deterministic keys; generation, multi-turn, and agent tasks use
their rubric and any requested Judge tools or runtime evaluator. Do not repeat
the same scoring rule in several fields.
When more than one resource is available, every source-backed task must list
the exact resources it uses in the task&#39;s top-level resource_ids. Do not put
this binding only in metadata.source_ids; metadata does not bind provenance.
<!-- -->
When available_models.models is non-empty, every task whose scoring requires an
LLM judge (generation, multi-turn, or agent rubric scoring), or that uses an
adaptive multi-turn dialogue, must select exactly one task model from that list
and record its id in metadata.task_model_id, choosing the model whose capability
matches the task&#39;s scoring or simulation complexity.
<!-- -->
When the benchmark or TaskDesign requires existing, real-world, or otherwise
source-grounded material, treat a URL, title, dataset landing page, or brief
research summary as a lead rather than as the underlying evidence. If the
provided context is not detailed enough to construct a faithful task, use any
research, search, or fetch capability available in this invocation to retrieve
the needed public details before writing the task. Do not silently replace
missing evidence with invented facts or a synthetic scenario presented as
source-backed. If the required material cannot be accessed or verified, keep
the provenance honest and state the limitation in construction_notes rather
than claiming that the task is grounded in details you did not obtain.
<!-- -->
During QC repair, return replacements only for revision.previous_tasks, preserve
their ids, and fix every listed issue. Do not return or modify tasks that are not
listed for repair.</code></pre></details>


<details><summary>研究补充、工具 schema 与消息循环：<code>evalclaw/construction/research.py</code></summary><pre><code class="language-python">&quot;&quot;&quot;Bounded external research tools for high-effort task construction.&quot;&quot;&quot;
from __future__ import annotations
<!-- -->
import json
from typing import Any
from urllib.parse import urlsplit
<!-- -->
from ..models.llm import TargetToolModelResponse, call_orchestrator_with_tools
from ..models.roles import role_model_settings
from ..protocols.tool import ToolCall, ToolResult, ToolSpec
from ..protocols.tool_adapters import (
    evalclaw_tool_result_to_anthropic,
    evalclaw_tool_result_to_openai,
    evalclaw_tool_result_to_openai_response_input,
)
from ..research.backends import fetch_url_text, web_search
from ..types import BenchmarkConfig
<!-- -->
TASK_BUILDER_RESEARCH_PROMPT = &quot;&quot;&quot;\
You may use the supplied research tools when source material would materially
improve the benchmark task. Use read_research_source to inspect text retained by
Deep Research, search_web for a new query, and fetch_url for a public HTTP(S)
source. Do not perform ceremonial searches, search for secrets, or use hidden
evaluator content. After research, return the complete task-builder JSON object.
The tool budget is bounded; stop researching once the task is adequately grounded.
&quot;&quot;&quot;
<!-- -->
<!-- -->
TASK_BUILDER_RESEARCH_TOOLS = [
    ToolSpec(
        name=&quot;read_research_source&quot;,
        description=&quot;Read source text retained by Deep Research without another network request.&quot;,
        parameters={
            &quot;type&quot;: &quot;object&quot;,
            &quot;properties&quot;: {
                &quot;url&quot;: {&quot;type&quot;: &quot;string&quot;, &quot;description&quot;: &quot;URL from source_material_index.&quot;},
                &quot;max_chars&quot;: {
                    &quot;type&quot;: &quot;integer&quot;,
                    &quot;description&quot;: &quot;Maximum retained text characters to return.&quot;,
                },
            },
            &quot;required&quot;: [&quot;url&quot;],
            &quot;additionalProperties&quot;: False,
        },
    ),
    ToolSpec(
        name=&quot;search_web&quot;,
        description=(
            &quot;Search public web/research sources for authoritative benchmark patterns, &quot;
            &quot;realistic failure modes, software documentation, or task resources.&quot;
        ),
        parameters={
            &quot;type&quot;: &quot;object&quot;,
            &quot;properties&quot;: {
                &quot;query&quot;: {&quot;type&quot;: &quot;string&quot;, &quot;description&quot;: &quot;Focused search query.&quot;},
                &quot;max_results&quot;: {
                    &quot;type&quot;: &quot;integer&quot;,
                    &quot;description&quot;: &quot;Maximum number of result summaries to retain.&quot;,
                },
            },
            &quot;required&quot;: [&quot;query&quot;],
            &quot;additionalProperties&quot;: False,
        },
    ),
    ToolSpec(
        name=&quot;fetch_url&quot;,
        description=&quot;Fetch readable text from one public HTTP(S) URL for source-grounded task design.&quot;,
        parameters={
            &quot;type&quot;: &quot;object&quot;,
            &quot;properties&quot;: {
                &quot;url&quot;: {&quot;type&quot;: &quot;string&quot;, &quot;description&quot;: &quot;Public HTTP(S) URL to inspect.&quot;},
                &quot;max_chars&quot;: {
                    &quot;type&quot;: &quot;integer&quot;,
                    &quot;description&quot;: &quot;Maximum text characters to return.&quot;,
                },
            },
            &quot;required&quot;: [&quot;url&quot;],
            &quot;additionalProperties&quot;: False,
        },
    ),
]
<!-- -->
<!-- -->
def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -&gt; int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))
<!-- -->
<!-- -->
def _tool_content(value: Any, *, max_chars: int) -&gt; str:
    encoded = json.dumps(value, ensure_ascii=False)
    return encoded[:max_chars]
<!-- -->
<!-- -->
def _execute_research_tool(
    call: ToolCall,
    config: BenchmarkConfig,
    *,
    max_chars: int,
) -&gt; ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    try:
        if call.name == &quot;read_research_source&quot;:
            url = str(args.get(&quot;url&quot;) or &quot;&quot;).strip()
            brief = config.research_brief
            material = next(
                (
                    candidate
                    for candidate in (brief.source_materials if brief is not None else [])
                    if candidate.url == url
                ),
                None,
            )
            if material is None:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content=&quot;No retained Deep Research source matched that URL.&quot;,
                    error=&quot;source_not_found&quot;,
                )
            requested_chars = _bounded_int(
                args.get(&quot;max_chars&quot;), default=max_chars, minimum=500, maximum=max_chars
            )
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(
                    {
                        &quot;url&quot;: material.url,
                        &quot;title&quot;: material.title,
                        &quot;content&quot;: material.content[:requested_chars],
                    },
                    max_chars=max_chars,
                ),
            )
<!-- -->
        if call.name == &quot;search_web&quot;:
            query = str(args.get(&quot;query&quot;) or &quot;&quot;).strip()
            if not query:
                raise ValueError(&quot;query must be non-empty&quot;)
            if not config.use_web_research or str(config.search_backend).lower() == &quot;none&quot;:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content=&quot;Web search is disabled by benchmark configuration.&quot;,
                    error=&quot;search_disabled&quot;,
                )
            result = web_search(query, backend=config.search_backend)
            if result is None:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content=&quot;No search result was available.&quot;,
                    error=&quot;no_search_result&quot;,
                )
            max_results = _bounded_int(args.get(&quot;max_results&quot;), default=5, minimum=1, maximum=8)
            value = {
                &quot;query&quot;: query,
                &quot;content&quot;: result.content,
                &quot;citations&quot;: result.citations[:max_results],
            }
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(value, max_chars=max_chars),
            )
<!-- -->    
        if call.name == &quot;fetch_url&quot;:
            url = str(args.get(&quot;url&quot;) or &quot;&quot;).strip()
            parsed = urlsplit(url)
            if parsed.scheme not in {&quot;http&quot;, &quot;https&quot;} or not parsed.netloc:
                raise ValueError(&quot;url must be an absolute HTTP(S) URL&quot;)
            requested_chars = _bounded_int(
                args.get(&quot;max_chars&quot;), default=max_chars, minimum=500, maximum=max_chars
            )
            content = fetch_url_text(url, max_chars=requested_chars)
            if content is None:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content=&quot;The URL could not be fetched as readable text.&quot;,
                    error=&quot;fetch_failed&quot;,
                )
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content({&quot;url&quot;: url, &quot;content&quot;: content}, max_chars=max_chars),
            )
<!-- -->    
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f&quot;Unknown research tool: {call.name}&quot;,
            error=&quot;unknown_tool&quot;,
        )
    except Exception as exc:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f&quot;Research tool failed: {type(exc).__name__}: {exc}&quot;,
            error=&quot;tool_error&quot;,
        )
<!-- -->
<!-- -->
def _append_tool_results(
    messages: list[dict[str, Any]],
    response: TargetToolModelResponse,
    results: list[ToolResult],
) -&gt; None:
    messages.append(response.assistant_message)
    if response.adapter == &quot;anthropic&quot;:
        messages.append(
            {
                &quot;role&quot;: &quot;user&quot;,
                &quot;content&quot;: [evalclaw_tool_result_to_anthropic(result) for result in results],
            }
        )
        return
    if response.adapter == &quot;openai_responses&quot;:
        messages.pop()
        output = response.assistant_message.get(&quot;responses_output&quot;)
        if isinstance(output, list):
            messages.extend(item for item in output if isinstance(item, dict))
        messages.extend(evalclaw_tool_result_to_openai_response_input(result) for result in results)
        return
    messages.extend(evalclaw_tool_result_to_openai(result) for result in results)
<!-- -->
<!-- -->
def run_task_builder_research(
    payload: dict[str, Any],
    *,
    system_prompt: str,
    config: BenchmarkConfig,
) -&gt; tuple[str, list[str]]:
    &quot;&quot;&quot;Run a bounded research/tool loop and return final builder JSON text.&quot;&quot;&quot;
    max_calls = _bounded_int(
        config.task_builder_research_max_calls,
        default=6,
        minimum=1,
        maximum=12,
    )
    max_chars = _bounded_int(
        config.task_builder_research_max_chars,
        default=50_000,
        minimum=1000,
        maximum=100_000,
    )
    settings = role_model_settings(config, &quot;task_builder&quot;)
    messages: list[dict[str, Any]] = [
        {
            &quot;role&quot;: &quot;user&quot;,
            &quot;content&quot;: json.dumps(
                {
                    **payload,
                    &quot;resources&quot;: {
                        **(
                            payload.get(&quot;resources&quot;)
                            if isinstance(payload.get(&quot;resources&quot;), dict)
                            else {}
                        ),
                        &quot;interactive_research&quot;: {
                            &quot;enabled&quot;: True,
                            &quot;max_tool_calls&quot;: max_calls,
                            &quot;available_tools&quot;: [tool.name for tool in TASK_BUILDER_RESEARCH_TOOLS],
                            &quot;instruction&quot;: &quot;Use tools only when they materially improve the task; return complete JSON when done.&quot;,
                        },
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
        }
    ]
    notes: list[str] = []
    calls_used = 0
    while True:
        response = call_orchestrator_with_tools(
            messages,
            system_prompt=system_prompt,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            tools=TASK_BUILDER_RESEARCH_TOOLS,
            max_tokens=16384,
            retry_on_truncation=False,
        )
        if not response.tool_calls:
            return response.content, notes
        remaining = max_calls - calls_used
        if remaining &lt;= 0:
            messages.append(response.assistant_message)
            messages.append(
                {
                    &quot;role&quot;: &quot;user&quot;,
                    &quot;content&quot;: &quot;The bounded research budget is exhausted. Return the complete final task-builder JSON now without further tool calls.&quot;,
                }
            )
            response = call_orchestrator_with_tools(
                messages,
                system_prompt=system_prompt,
                **settings.call_kwargs(),
                backend=config.llm_backend,
                tools=[],
                max_tokens=16384,
                retry_on_truncation=False,
            )
            return response.content, notes + [f&quot;research tool budget exhausted at {calls_used} call(s)&quot;]
        selected_calls = response.tool_calls[:remaining]
        results = [_execute_research_tool(call, config, max_chars=max_chars) for call in selected_calls]
        for skipped_call in response.tool_calls[remaining:]:
            results.append(
                ToolResult(
                    tool_call_id=skipped_call.id,
                    name=skipped_call.name,
                    content=&quot;This tool call was skipped because the bounded research budget was exhausted.&quot;,
                    error=&quot;research_budget_exhausted&quot;,
                )
            )
        calls_used += len(selected_calls)
        notes.append(f&quot;task-builder research used {len(selected_calls)} tool call(s), total={calls_used}&quot;)
        _append_tool_results(messages, response, results)
        if calls_used &gt;= max_calls:
            messages.append(
                {
                    &quot;role&quot;: &quot;user&quot;,
                    &quot;content&quot;: &quot;The bounded research budget is exhausted. Return the complete final task-builder JSON now without further tool calls.&quot;,
                }
            )
            response = call_orchestrator_with_tools(
                messages,
                system_prompt=system_prompt,
                **settings.call_kwargs(),
                backend=config.llm_backend,
                tools=[],
                max_tokens=16384,
                retry_on_truncation=False,
            )
            return response.content, notes + [f&quot;research tool budget exhausted at {calls_used} call(s)&quot;]
<!-- -->
<!-- -->
__all__ = [
    &quot;TASK_BUILDER_RESEARCH_PROMPT&quot;,
    &quot;TASK_BUILDER_RESEARCH_TOOLS&quot;,
    &quot;run_task_builder_research&quot;,
]</code></pre></details>


<details><summary>环境构题 Skill：<code>evalclaw/construction/skills/build-environment-tasks/SKILL.md</code></summary><pre><code class="language-markdown">---
name: build-environment-tasks
description: Construct agent benchmark tasks that require workspace, code-sandbox, container, browser, desktop, VM, or other executable environments. Use only for TaskDesigns with non-empty environment requirements.
---
<!-- -->
# Build Environment-Backed Tasks
<!-- -->
Implement only the environment capabilities requested by each TaskDesign. The runtime supplies a routing table that maps TaskDesign IDs to the references loaded for them. Apply a reference only to the listed TaskDesigns.
<!-- -->
For every environment-backed task:
<!-- -->
- Return an `environment` object using the runtime environment type in the routing table.
- Implement every TaskDesign-required input, fixture, initial-state property, action capability, output, and scoring check; do not merely describe what another system is assumed to provide.
- Make the initial state, permitted actions, completion condition, and scoring oracle executable and mutually consistent.
- If a required repair needs administrator, owner, privileged service, or delegated access, provision a concrete target-visible elevation or authorization path scoped to that repair. Do not assign a required privileged action to an account that cannot perform it.
- Use only actions and setup mechanisms the selected EvaluationClaw runtime actually exposes. Never invent a custom tool or provisioning path that exists only in prose.
- Represent task-specific setup through structured files, commands, provisioning, session state, or a concrete runner-resolvable prebuilt artifact. Keep descriptive explanation separate from image, template, snapshot, path, command, and tool identifiers.
- When a clean/default environment is sufficient, say so through the concrete launch state and do not add unnecessary setup. When non-default hidden or mutable state is required, provide both its setup or prebuilt-state reference and a baseline check that can establish it before the target starts.
- Populate only fields required by the TaskDesign and its loaded references.
- Keep target-visible inputs separate from setup-only material and evaluator-only material.
- Never expose hidden tests, reference answers, evaluator secrets, bridge credentials, or provider credentials.
- Prefer deterministic state, artifact, test, or trajectory checks over vague judge-only scoring when the environment permits them.
- Ensure the evaluator consumes the target&#39;s actual final answer, artifacts, state, or trajectory. It must not create, repair, or substitute for the work being scored.
- Keep task-specific files and state in structured fields rather than embedding them in long prompts.
- Make every generated setup and evaluation command internally exact: create required parent objects before using them, keep paths/identifiers/values byte-consistent across setup, baseline, prompt, and evaluation, and ensure commands work from the declared clean base rather than an assumed intermediate state.
- Ensure every evaluation condition is attainable from the target-visible instructions and executable fixture. Do not require an undisclosed arbitrary value, invocation mode, artifact, or event that neither the environment nor the compliant workflow can produce.
- When an evaluator creates fresh probes with unique identifiers, bind every relevant assertion to those exact identifiers; do not scan for any matching pre-existing artifact or event.
- The runner records the agent trajectory for audit, but generic environment scoring does not automatically judge or weight that trace. Do not assign score weight to diagnosis order, tool choice, or other trajectory behavior unless the selected runtime exposes a concrete executable trajectory check. Keep unsupported trajectory expectations qualitative and non-scoring.
- When several artifact paths are alternatives, list the candidate paths and set `artifact_requirement` to `any` or `exactly_one`; the default `all` means every listed artifact is required.
<!-- -->
Before returning, trace every TaskDesign requirement through the concrete task and verify this chain is complete: initial state -&gt; exposed observations/actions -&gt; target-produced result -&gt; evaluator evidence -&gt; score. If the runtime cannot realize a required link, do not claim the task is complete or hide the gap in `construction_notes`.
<!-- -->
EvaluationClaw derives canonical `metadata.agent_env`, `metadata.task_agent`, and `metadata.agent_task_package` records from the returned task fields during packaging. Do not duplicate those protocol objects manually unless the TaskDesign explicitly requires a protocol extension that cannot be expressed through `environment`, `system_prompt`, `interaction`, `scoring`, or ordinary task metadata.
<!-- -->
Read only the references selected by the runtime:
<!-- -->
- `references/workspace.md`
- `references/code-sandbox.md`
- `references/docker-workspace.md`
- `references/gui-desktop.md`
- `references/task-agent.md`
- `references/agent-task-package.md`</code></pre></details>


<details><summary>workspace reference：<code>evalclaw/construction/skills/build-environment-tasks/references/workspace.md</code></summary><pre><code class="language-markdown"># Workspace Environment
<!-- -->
Use runtime environment type `workspace`.
<!-- -->
- Use this runtime only for EvaluationClaw&#39;s built-in room, object, inventory, and outgoing-bin interaction model. Use `code_sandbox` or `docker_workspace` for file or shell work.
- Put the complete state under `environment.workspace` using exactly this shape:
<!-- -->
```json
{
  &quot;environment&quot;: {
    &quot;type&quot;: &quot;workspace&quot;,
    &quot;workspace&quot;: {
      &quot;start_room&quot;: &quot;office&quot;,
      &quot;rooms&quot;: {
        &quot;office&quot;: [&quot;brief&quot;],
        &quot;mailroom&quot;: []
      },
      &quot;item_descriptions&quot;: {
        &quot;brief&quot;: &quot;The document the target must inspect and deliver.&quot;
      },
      &quot;goal&quot;: {
        &quot;outgoing_bin&quot;: [&quot;brief&quot;]
      },
      &quot;max_steps&quot;: 8
    }
  }
}
```
<!-- -->
- `rooms` must be an object mapping room names to arrays of item ID strings. Do not use a room-object array, a separate `objects` array, or room `exits`; the built-in runtime makes every named room directly reachable.
- `goal.outgoing_bin` must be a non-empty array of item IDs, and every required item must appear in one of the `rooms` arrays. Include the `mailroom` required by the built-in `place` action.
- Use only the built-in look, move, inspect, take, place, and final actions. `environment.tools` cannot add custom behavior.
- Do not add files, shell setup, browser state, VM state, or evaluator commands; the runtime scores the final room/inventory/outgoing-bin state directly.</code></pre></details>


<details><summary>code_sandbox reference：<code>evalclaw/construction/skills/build-environment-tasks/references/code-sandbox.md</code></summary><pre><code class="language-markdown"># Code Sandbox Environment
<!-- -->
Use runtime environment type `code_sandbox`.
<!-- -->
- Put starter code and target-visible fixtures in `visible_files` when the task needs them; an empty mapping is valid for a create-from-scratch task.
- Put setup-only fixtures in `runtime_files` and hidden tests in `hidden_files`.
- Provide the exact deterministic `test_command` the runner must invoke.
- Keep hidden tests out of the prompt, visible files, setup commands, and task-visible tool output.
- Make the requested code change and the evaluator agree on paths, APIs, dependencies, and expected behavior.
- Prefer the minimal runtime needed for the task; use Docker workspace only when OS packages, non-Python runtimes, services, or native builds are genuinely required.</code></pre></details>


<details><summary>docker_workspace reference：<code>evalclaw/construction/skills/build-environment-tasks/references/docker-workspace.md</code></summary><pre><code class="language-markdown"># Docker Workspace Environment
<!-- -->
Use runtime environment type `docker_workspace`.
<!-- -->
- Choose a suitable common image, use `image: &quot;auto&quot;`, or define `image_build` only when a common image is insufficient.
- Put target-visible files in `visible_files`, setup-only server/application material in `runtime_files`, and evaluator-only tests in `hidden_files`.
- Use `setup_commands` for bounded initialization and provide the exact `test_command` for deterministic scoring; use `evaluation` to configure how that command&#39;s structured result is interpreted.
- Specify timeout and resource limits appropriate to the workload.
- If browser interaction is required, configure the canonical browser runtime with a start URL and allowed origins.
- Ensure the selected image or image build actually contains the declared runtime dependencies, but do not infer capabilities from image names alone.
- Do not expose raw command execution when protected runtime or hidden files exist; use structured workspace tools and runner-private evaluation.
- Keep image-build packages, commands, Dockerfile, and context files only as detailed as required by the TaskDesign.</code></pre></details>


<details><summary>gui_desktop reference：<code>evalclaw/construction/skills/build-environment-tasks/references/gui-desktop.md</code></summary><pre><code class="language-markdown"># GUI Desktop Environment
<!-- -->
Use runtime environment type `gui_desktop`.
<!-- -->
- Use this canonical field layout. Do not move `evaluation` into `session`, rename
  `vm_provisioning` to `provisioning`, or invent aliases such as
  `session.surface` or `session.evaluation_checks`:
<!-- -->
```json
{
  &quot;environment&quot;: {
    &quot;type&quot;: &quot;gui_desktop&quot;,
    &quot;requires_vm&quot;: true,
    &quot;vm&quot;: {
      &quot;guest_os&quot;: &quot;windows&quot;,
      &quot;required_capabilities&quot;: [
        &quot;desktop_bridge&quot;,
        &quot;cloudbase_init_nocloud&quot;,
        &quot;powershell&quot;
      ]
    },
    &quot;vm_provisioning&quot;: {
      &quot;powershell_commands&quot;: [&quot;task-specific state-building command&quot;],
      &quot;interactive_powershell_commands&quot;: [],
      &quot;restart_after_provisioning&quot;: false
    },
    &quot;session&quot;: {
      &quot;application&quot;: &quot;Windows Desktop&quot;,
      &quot;launch_state&quot;: &quot;The signed-in desktop is visible.&quot;,
      &quot;baseline_checks&quot;: [
        {
          &quot;id&quot;: &quot;initial_state_present&quot;,
          &quot;method&quot;: &quot;command&quot;,
          &quot;command&quot;: &quot;PowerShell command that succeeds only when the required initial state exists&quot;,
          &quot;expected_exit_code&quot;: 0
        }
      ]
    },
    &quot;evaluation&quot;: {
      &quot;method&quot;: &quot;bridge_state_check&quot;,
      &quot;checks&quot;: [
        {
          &quot;id&quot;: &quot;final_state_correct&quot;,
          &quot;method&quot;: &quot;command&quot;,
          &quot;command&quot;: &quot;PowerShell command that succeeds only when the target produced the required final state&quot;,
          &quot;expected_exit_code&quot;: 0
        }
      ],
      &quot;pass_criteria&quot;: &quot;All required final-state checks pass.&quot;,
      &quot;partial_criteria&quot;: &quot;Only a strict subset of independent checks pass.&quot;,
      &quot;fail_criteria&quot;: &quot;No required final-state check passes.&quot;
    },
    &quot;max_steps&quot;: 200,
    &quot;timeout&quot;: 3600
  }
}
```
<!-- -->
- Set `requires_vm` only when a VM is needed. Prefer `guest_os` plus `required_capabilities` so the runtime can resolve a compatible provider image. Pin an image, template, snapshot, or disk identifier only when that concrete identifier was supplied by runtime/user input; put descriptions in notes. Define how each run returns to the required baseline.
- Set `session.application` (or `session.applications` for multiple applications) and describe the concrete `session.launch_state`, input assets, workflow stages, handoff artifacts, and expected final artifacts. `session.surface` is not a runtime field.
- Put guest files in `visible_files` or session asset files; never put evaluator secrets there.
- Use setup commands, runtime files, VM provisioning, or a prebuilt image/snapshot only when the selected provider and guest OS can actually apply them. A sentence saying that a snapshot already contains task-specific state is not a snapshot reference or setup mechanism.
- Set `vm.guest_os` to `linux` or `windows` whenever files or provisioning are OS-specific. EvaluationClaw builds a per-task NoCloud config-drive ISO: Linux guests consume it with cloud-init; Windows guests consume PowerShell user data with Cloudbase-Init&#39;s NoCloud service. A Windows base template must therefore have Cloudbase-Init installed and configured for NoCloud before EvaluationClaw can customize it.
- For Windows provisioning, use `winget_packages`, `choco_packages`/`chocolatey_packages`, `windows_features`, `pip_packages`, `npm_packages`, `powershell_commands`, generic command fields, or PowerShell install steps. Do not use Linux package-manager fields. Relative visible paths are rooted at `C:\Users\Public` by default, so `Desktop/...` reaches the public desktop; override `vm_materialization.guest_root` only when the template uses a known different profile.
- When registering a password-backed Windows scheduled task, use the `Register-ScheduledTask` parameter set with `-User`, `-Password`, and optional `-RunLevel`. Do not combine `-Principal` with `-Password`; PowerShell rejects that ambiguous parameter set at runtime.
- A scheduled task&#39;s RunAs identity does not grant that account permission to modify a task registered by SYSTEM. If the target must repair task actions, triggers, or settings, provision concrete task ownership or a scoped task ACL that lets the target perform those exact changes. Prefer having the target identity create an `Interactive` task when the benchmark already guarantees that account is signed in. Add a non-repairing baseline check, such as reapplying the unchanged action, that proves the target can update the task before evaluation starts.
- When Windows provisioning changes the account that must own the interactive desktop session, configure that account through a concrete guest-supported logon mechanism and set `vm_provisioning.restart_after_provisioning` to `true`. EvaluationClaw then records successful provisioning before restarting and exposes the bridge only after the next boot. Verify the signed-in identity in `session.baseline_checks`; a `launch_state` sentence alone does not switch users.
- When a capability-resolved base VM is not guaranteed to contain the named target account, create that local user explicitly before referencing it in ACLs, Scheduled Task principals, or auto-logon configuration. Writing an unknown account name into those commands does not create the user and will fail provisioning.
- Put setup that must execute under the actual signed-in Windows user token (for example HKCU state, user-owned Scheduled Tasks, or GUI first-run initialization) in `vm_provisioning.interactive_powershell_commands` and also set `restart_after_provisioning=true`. EvaluationClaw installs it as one-time post-login setup and withholds the desktop bridge until it succeeds. Do not put evaluator secrets or other target-sensitive setup in this user-readable phase.
- Assign each setup command to exactly one identity phase. Never duplicate an `interactive_powershell_commands` entry in `powershell_commands` or `powershell_script`, because the duplicate would execute early as SYSTEM.
- Every VM-backed task must include runner-private executable `session.baseline_checks` that verify its required initial state before the target acts. For task-specific hidden or mutable state, also include either concrete `vm_provisioning` commands that create it or a runner-resolvable prebuilt image/snapshot identifier. The bridge must return `baseline_verified=true` when creating the session; otherwise EvaluationClaw fails closed. Final-state checks belong in `environment.evaluation` and must not create the initial state.
- A check with `method: &quot;command&quot;` must put the complete executable guest shell command in its `command` field. Opaque names such as `RUNNER_PRIVATE_BRIDGE_COMMAND:validator_name` are not registered or resolved by the generic bridge and are invalid.
- On Windows, the bridge executes `method: &quot;command&quot;` values as raw PowerShell script bodies. Do not wrap them in `powershell.exe -Command`/`pwsh -Command`, and do not use backslash-escaped quotes such as `\&quot;`; use ordinary PowerShell quoting. The built-in bridge supports only `command` and `file_exists` check methods.
- Generate JSON fixture files from PowerShell objects with `ConvertTo-Json`; do not hand-write JSON inside a quoted PowerShell string with `\&quot;`, `\n`, or backtick-newline escapes. Those characters can be written literally and produce a file that `ConvertFrom-Json` cannot read. For multiline scripts or data embedded in the Builder response, prefer an array of complete lines joined with `[Environment]::NewLine`; a PowerShell here-string header must be followed immediately by a real newline.
- Every evaluation command must itself decide whether the scored state is correct by returning a success or failure exit code (or by using an output comparison explicitly supported by the bridge). A command that only prints or serializes observations and then exits successfully is not an evaluator. Ordinary task metadata is descriptive and cannot register a runner-private or host-side evaluator.
- Do not invent a task-specific image or snapshot identifier. Use a prebuilt artifact only when its concrete identifier was supplied in the TaskDesign or runtime inputs; otherwise declare OS/capability requirements and construct the task-specific fixture with `vm_provisioning` on the provider-resolved base image.
- Bound `max_steps` and timeout, and define bridge-executable artifact, UI-state, page-state, final-state, or trajectory checks with full, partial, and failure criteria.
- `expected_artifacts` lists candidate paths. Set `artifact_requirement` to `all` (default), `any`, or `exactly_one` so alternative formats are not misrepresented as jointly required.
- The desktop bridge executes both target actions and final-state evaluator commands as the signed-in target user. An evaluator therefore cannot read an oracle directory protected for only SYSTEM or Administrators. Keep private oracle material inaccessible to the target and embed the required expected values or hashes directly in evaluator commands; never make a private oracle target-readable merely so scoring can access it.
- For multi-application workflows, require observable handoffs and provenance instead of reducing the task to one application.
- Never include bridge URLs, API keys, VM-provider credentials, or other runtime secrets in task metadata.</code></pre></details>


<details><summary>task-agent reference：<code>evalclaw/construction/skills/build-environment-tasks/references/task-agent.md</code></summary><pre><code class="language-markdown"># Task-Agent Interaction Contract
<!-- -->
Use `system_prompt` and `interaction` to describe task-specific agent behavior. EvaluationClaw packages them into canonical `metadata.task_agent`.
<!-- -->
- Keep `system_prompt` concise: role, non-disclosure rules, and high-level turn policy only.
- Put initial files, scenario state, session configuration, evaluator rules, and large structured content in their dedicated fields.
- For multi-turn tasks, use the exact `interaction` fields `initial_user_message`, `max_turns`, `user_turns` (a list of strings) or `followup_instruction`, and `stop_condition`. Do not invent aliases or nest these fields under `environment`.
- Make interaction scoring inspect the relevant transcript, state, artifact, or tool trace.
- Do not describe a code sandbox or workspace controller as a conversational helper when the target itself is meant to operate the environment.</code></pre></details>


<details><summary>agent-task-package reference：<code>evalclaw/construction/skills/build-environment-tasks/references/agent-task-package.md</code></summary><pre><code class="language-markdown"># Executable Agent Task Package
<!-- -->
EvaluationClaw derives canonical `metadata.agent_task_package` during packaging. Construct enough structured task and environment information for that package to be complete.
<!-- -->
- Identify the measured capability and provide concise task content.
- Separate visible inputs, setup-only runtime material, and evaluator-only references.
- Define required outputs or expected artifacts, including paths, formats, and side-effect constraints.
- Provide deterministic setup, execution, and evaluation semantics with bounded timeout and steps.
- Define full, partial, and failure criteria on a normalized score range.
- State which artifacts, logs, screenshots, and tool traces must be retained.
- Specify required tools and forbidden shortcuts when process behavior matters.
- Record source kind, public source URIs, license requirements, and construction notes when relevant.
- Do not copy environment file contents or secrets into package-like metadata; the environment remains the sole executable state definition.</code></pre></details>


<a id="appendix-b-qc"></a>
### B.5 QC prompt
<details><summary>完整源码：<code>evalclaw/prompts/qc.py</code></summary><pre><code class="language-text">QC_SYSTEM_PROMPT:
<!-- -->
You are the EvaluationClaw QC Gate. Review whether the benchmark is a good
evaluation plan for the user&#39;s need.
<!-- -->
Use English in all issue messages and suggestions unless the issue must quote
non-English benchmark content.
<!-- -->
Check individual item clarity, answer reliability, scoring criteria, and
coverage. Also perform meta-evaluation:
- Do the dimensions genuinely match the objective and user need?
- Are the task types, source strategy, and scoring method appropriate?
- Are there obvious omissions, content drift, shallow coverage, judge
  overreliance, or bias introduced by source choices?
- challenge_effort is a task-builder effort instruction, not an absolute
  challenge-effort claim. Do not create QC issues merely because an item looks easier
  than its challenge_effort; builder-level self-assessment handles that before
  this QC gate.
- metadata.challenge_effort_fidelity.status=uncertain means the builder had to
  regenerate after output truncation with reduced effort. Preserve this marker
  and do not reject an otherwise sound item solely for effort-label uncertainty;
  continue to report any concrete execution, scoring, or content defect.
- If an existing benchmark/source is needed, did the dataset use appropriate,
  hard, authoritative sources?
<!-- -->
Perform a complete audit in one pass. For every reviewed item, inspect every
applicable link in its task, environment, tools, files, output contract,
evaluator, scoring, and metadata, and report all independently actionable
problems you can substantiate rather than stopping after the first or most
salient issue. This instruction is about completeness, not criticism: do not
invent hypothetical defects, duplicate the same root cause under several
wordings, penalize harmless stylistic choices, or report an issue for a part
that is sound. An item with no substantiated problem should receive no issue.
Suggestions must be scoped to the reported defect and should preserve
unaffected task content.
<!-- -->
When an item has metadata.task_design_id, find the matching object in
task_designs and treat it as the Planner&#39;s authoritative construction contract.
Check that the concrete task implements its required inputs, interaction,
environment, outputs, scoring evidence, sources, and construction requirements.
Do not accept a field merely because it contains plausible prose.
<!-- -->
Apply task-type requirements according to what the runner actually consumes:
- choice needs at least two distinct id/text choices and one or more valid
  correct_choice_ids; multi-select is scored by exact set equality.
- fill_blank needs one non-empty expected_text and a prompt that makes the
  exact required response format unambiguous.
- generation and multi_turn need a concrete judge rubric. generation may use
  python_tests as Judge evidence; its test code must consume {model_output}.
- agent needs an environment whose actual evaluator scores the
  state, artifacts, answer, or trajectory produced by the target.
<!-- -->
Each sampled item includes prompt_is_complete and prompt_character_count. When
prompt_is_complete=false, prompt is an explicitly marked QC review excerpt
containing its beginning and end. Do not report prompt truncation merely because
the middle was omitted for QC context; report only a concrete defect visible in
the excerpt, or a warning when the omitted content prevents a reliable review.
Likewise, any `QC REVIEW EXCERPT` or `QC review excerpt clipped` marker anywhere
in the supplied metadata was inserted only while preparing this QC request. It
is not present in the canonical task, command, file, or validator. Never report
that marker or the excerpt boundary as a defect in the canonical benchmark.
<!-- -->
For executable tasks, metadata.agent_env and metadata.agent_task_package are the
canonical runtime contracts. Ordinary task metadata fields with names such as
required_tools, forbidden_shortcuts, or retained_evidence are descriptive and
cannot add, remove, or override runtime tools. Report a tool-contract conflict
only when the canonical environment or agent task package conflicts with the
runner contract.
<!-- -->
For every environment-backed task, cross-check the complete execution chain:
Planner requirements -&gt; resettable initial state -&gt; runner-exposed actions and
observations -&gt; target-produced result -&gt; evaluator inputs -&gt; score. A task may
start from a clean/default environment when that genuinely satisfies the
TaskDesign; do not demand setup files merely for uniformity. When task-specific
fixtures, hidden faults, accounts, services, documents, or application state
are required, however, require an executable setup mechanism or a concrete,
runner-resolvable prebuilt artifact plus a way to verify the required baseline.
A sentence claiming that an image, template, snapshot, or external session
already contains the state is not implementation evidence. The evaluator must
inspect what the target leaves behind and must not create or repair the expected
state itself. Do not accept custom tool names unless the selected runtime
actually exposes them.
<!-- -->
For task_type=agent with metadata.agent_env.type=code_sandbox:
- visible_files are available to the target through file tools.
- runtime_files are available to setup/runtime but protected from target file tools.
- hidden_files are intentionally not readable by the target but are available
  to the EvaluationClaw execution environment through run_tests.
- Do not mark the item unexecutable merely because hidden tests are hidden from
  the target or summarized in metadata, as long as hidden file names/count and a
  test_command are present.
- An empty visible_files mapping is valid when the task asks the agent to create
  new files from scratch. The deterministic test_command is still required.
- metadata.agent_env fields named visible_files_preview, files_preview, or
  hidden_files_preview are intentionally compact QC excerpts, not the canonical
  task files. Do not report truncation/omission issues solely because a preview
  field is abbreviated; only flag truncation when the actual prompt, visible
  task package, or executable file content explicitly contains placeholders
  such as &quot;...&quot;, &quot;truncated&quot;, &quot;same as above&quot;, or missing required code.
<!-- -->
For task_type=agent with metadata.agent_env.type=docker_workspace:
- hidden_files are likewise runner-private evaluator or reference files. Do not
  reject a task merely because an evaluator script is hidden from the target
  agent, as long as test_command/evaluation explains that the runner executes
  it after the agent finishes.
- Deterministic scoring may be binary or numeric partial-credit scoring such as
  0/0.5/1. Partial criteria are not incompatible with deterministic scoring
  when the evaluator has explicit checks for those levels.
- A prompt must not claim that browser, MCP, API, database, or other custom
  tools are available unless agent_env configures a runtime that actually
  exposes them. For EvaluationClaw&#39;s Docker text-browser runtime, browser.enabled
  must be true with runtime=playwright_python, start_url, allowed_origins, and a
  runtime that actually contains Playwright and a browser. Do not infer that a
  custom image lacks them solely because its image name does not say playwright.
- Check that setup_commands are feasible under the declared image and network
  policy, start required local services before the target begins, use paths
  consistent with the container workdir, and leave the evaluator runtime
  available. A network=none task cannot fetch pip/npm/apt dependencies during
  setup; those dependencies must already exist in the image or image_build.
- Reject setup_commands that reference hidden_files or /tmp/hidden_files. Any
  server/application asset needed before target execution belongs in
  runtime_files.
- Hidden evaluators may start or inspect services when needed, but must not
  perform, simulate, or replay the target agent&#39;s required state-changing
  actions. They must score the state/artifacts/final answer actually left by the
  target. Treat an evaluator that creates the expected state itself as an error.
- Compare prompt outputs with output_contract, expected_artifacts, scoring, and
  evaluator inputs. Treat an undeclared required file/state or an instructed
  output that the evaluator ignores as an error.
- Metadata file fields may contain explicitly labelled QC review excerpts.
  Use them to inspect dependency, setup, and evaluator consistency, but do not
  infer that canonical files are truncated merely because the QC copy is an
  excerpt.
<!-- -->
For task_type=agent with metadata.agent_env.type=workspace:
- This is EvaluationClaw&#39;s built-in room/inventory runtime, not a generic file
  workspace. It needs reachable rooms, a mailroom, available goal items, and a
  non-empty outgoing_bin goal. File editing, shell setup, browser state, and
  invented custom tools are not implemented by this runtime.
<!-- -->
For task_type=agent with metadata.agent_env.type=gui_desktop:
- Require an identifiable application or desktop surface, a launch/start
  state, bounded steps, and bridge-executable evaluation checks or method.
- When requires_vm=true, accept either a concrete runner-resolvable
  image/template/snapshot/disk or a declared guest OS plus non-empty
  required_capabilities for runtime provider resolution. Check that task-specific
  setup is compatible with the declared guest OS and capabilities.
- A concrete `vm.template`, `vm.image`, or VM disk field is independently a
  valid boot-source identifier. Never require both `environment.image` and a
  VM template/image field, and do not call the accepted field ambiguous merely
  because the other alternatives are empty.
- EvaluationClaw builds a NoCloud config-drive ISO for task-specific files and
  provisioning. Linux uses cloud-init; Windows uses PowerShell user data through
  Cloudbase-Init&#39;s NoCloud service. Require vm.guest_os for OS-specific setup,
  Linux package fields only on Linux, Windows package/PowerShell fields only on
  Windows, and a Cloudbase-Init-capable base template for dynamic Windows setup.
- `vm_provisioning` is itself the canonical VM setup path consumed by the VM
  materializer. It does not need to be copied into `setup_commands`; never report
  it as disconnected merely because `setup_commands` is empty. Audit the actual
  provisioning content and its compatibility with the guest/template instead.
- `expected_artifacts` may use `artifact_requirement=all`, `any`, or
  `exactly_one`; respect that explicit quantifier instead of treating every
  candidate path as jointly required.
- The runner retains the agent trace for audit, but generic GUI scoring is the
  score returned by the bridge evaluator. Reject promised trajectory points
  unless the canonical bridge evaluation defines a concrete executable way to
  score them.
- Hidden or mutable initial state needs runner-private session.baseline_checks;
  the bridge must confirm baseline_verified=true before the target starts.
- Do not require a VM for a valid externally managed desktop bridge, and do not
  require task-specific provisioning when the requested base application state
  is sufficient.
<!-- -->
For task_type=multi_turn with a dialogue contract:
- Require a positive turn bound and either scripted user turns or a concrete
  follow-up policy. The scoring oracle must inspect the relevant transcript,
  final answer, or resulting state rather than only the first response.
<!-- -->
For task_type=multi_turn or task_type=agent:
- If metadata.task_structure_validation.status is &quot;passed&quot;, the task has
  passed builder-level shape and runner-contract validation only. Do not repeat
  those low-level schema checks without evidence, but never treat this marker as
  proof that Planner requirements, initial state, tools, or evaluator semantics
  are complete.
- Prefer items that include metadata.task_agent with schema_version
  &quot;evalclaw.task_agent.v1&quot;.
- metadata.task_agent should define the task-specific agent system_prompt,
  initial_content, interaction rules, and scoring guidance. Missing task_agent
  is a warning for legacy items, not a blocking error by itself.
- Professional workflow, VM-backed, docker_workspace, GUI/browser/desktop
  software, or ALE-like executable agent tasks should also include
  metadata.agent_task_package with schema_version
  &quot;evalclaw.agent_task_package.v1&quot;. It should separate visible_inputs from
  runner-private hidden_references, define output_contract, setup/run/evaluate
  steps, evaluation checks, artifact_collection, trajectory_requirements,
  environment/software requirements, and provenance. Hidden references are
  intentionally unavailable to the target agent; do not reject an item merely
  because hidden_references are private.
<!-- -->
For items using metadata.multimodal:
- metadata.multimodal.schema_version should be evalclaw.multimodal.v1.
- metadata.multimodal.modalities and assets should be present and non-empty.
- The current target adapter supports native image/text content only; audio or
  video metadata must not be accepted as a native multimodal evaluation.
- image items should provide a usable URL, data URI, or local file path that the
  runner can resolve into provider-native image content.
<!-- -->
For items using metadata.science:
- metadata.science.schema_version should be evalclaw.science.v1.
- Check that the scientific skill, evidence context, units, and assumptions are
  consistent with the prompt and scoring rubric.
- For quantitative science items, constants/data and required units should be
  stated clearly enough to make the answer reliable.
- For experimental or literature-grounded science items, the prompt should
  provide enough observations, source excerpt, or study context to support the
  requested inference without hallucinated facts.
<!-- -->
Return pure JSON only, with no markdown. Format:
{
  &quot;issues&quot;: [
    {
      &quot;item_id&quot;: &quot;...&quot;,
      &quot;severity&quot;: &quot;warning&quot;,
      &quot;category&quot;: &quot;clarity&quot;,
      &quot;message&quot;: &quot;...&quot;,
      &quot;suggested_action&quot;: &quot;...&quot;
    }
  ],
  &quot;summary&quot;: &quot;...&quot;
}
<!-- -->
severity must be one of info/warning/error.
category must be one of schema/duplicate/scoring/clarity/coverage.
Mark error only for issues that make an item unexecutable or make the answer
clearly unreliable.</code></pre></details>


<a id="appendix-b-review"></a>
### B.6 人工审核 prompt 与协议 guidance

`PLANNER_REVIEW_SYSTEM_PROMPT` 在模块加载时追加 `TASK_AGENT_GENERATION_GUIDANCE` 和
`AGENT_TASK_PACKAGE_GENERATION_GUIDANCE`。若 `human_feedback` 非空，调用前还会追加一段要求应用人工修改的说明。
<details><summary>Planner review prompt 组装源码：<code>evalclaw/prompts/planning_loop.py</code></summary><pre><code class="language-python">&quot;&quot;&quot;Planner-supervised generation loop prompt templates.&quot;&quot;&quot;
from __future__ import annotations
<!-- -->
from ..protocols.agent_task_package import AGENT_TASK_PACKAGE_GENERATION_GUIDANCE
from ..protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE
<!-- -->
PLANNER_REVIEW_SYSTEM_PROMPT = &quot;&quot;&quot;\
You are the EvaluationClaw Planner reviewing a generated benchmark dataset before
any target model run.
<!-- -->
Use English for all JSON fields unless the evaluation explicitly tests another
language. Return pure JSON only, with no markdown.
<!-- -->
Your job:
1. Inspect every item against its assigned dimension. If an item is clearly
   off-target, either move it to a better existing dimension or delete it.
   When QC reports no errors and no rejected items, treat the current items as
   provisionally acceptable. Do not delete or move them for minor preference or
   style reasons. If you delete a QC-passed item, also request a concrete
   replacement with needs_more_items unless another existing item keeps the
   dimension filled.
2. Reconsider the dimension structure only when there is an obvious problem:
   underfilled dimensions, overlapping dimensions, or dimensions that are too
   broad to produce coherent items.
3. If a dimension is underfilled after deletions/moves, request more items for
   that dimension.
4. Do not chase perfection. If dimensions are reasonably independent, aligned
   with the objective, and sufficiently filled, return done=true.
5. For dimensions or items using multi_turn or agent, preserve or
   request metadata.task_agent. If you add/update such a dimension, include
   item_requirements that tell generation workers what the task-agent system
   prompt, initial content, interaction rules, and scoring standards must cover.
   For professional workflows, VM-backed tasks, GUI/browser/desktop software,
   docker_workspace tasks, or ALE-like executable tasks, also preserve or request
   metadata.agent_task_package with visible inputs, hidden references, output
   contract, setup/run/evaluate steps, artifact collection, trajectory
   requirements, environment requirements, and provenance.
6. For docker_workspace items that need specialized CLI tools or native
   packages beyond common Hub runtime images, preserve or request
   metadata.agent_env.image_build so EvaluationClaw can build a local task image.
7. For multi-industrial-software collaboration tasks, preserve the requirement
   that multiple named applications participate in one workflow. Keep explicit
   artifact handoffs, VM/software-stack requirements, workflow_manifest.json
   provenance, and hidden artifact/trace checks through every generation/QC
   repair cycle.
8. For VM-backed tasks with vm_provisioning, preserve vm.guest_os and its
   platform-compatible setup: Linux package managers, or Windows winget/choco,
   Windows features and PowerShell. Preserve install steps, commands, and bridge
   install/start commands unless the task explicitly depends on a prebuilt
   proprietary VM image.
<!-- -->
Allowed changes:
- delete_item_ids: remove off-target or unrepairable items.
- move_items: move an item to a better existing or newly created dimension.
- update_items: rewrite a specific item (its prompt, rubric, choices, expected
  answer, or environment) while keeping its id. Use this when a human reviewer
  asks to change a concrete item's content rather than its dimension. For each
  entry give the item_id, the dimension_id it belongs to, and a concrete
  guidance string describing exactly what to change and how.
- dimension_updates: update name/description/approach/requirements/counts.
- add_dimensions: add clearly requested missing dimensions.
- merge_dimensions: merge obviously overlapping dimensions.
- split_dimensions: split an obviously too-broad dimension and assign items.
- needs_more_items: request item generation for a dimension.
<!-- -->
Return JSON:
{
  &quot;done&quot;: true,
  &quot;delete_item_ids&quot;: [&quot;...&quot;],
  &quot;move_items&quot;: [{&quot;item_id&quot;: &quot;...&quot;, &quot;dimension_id&quot;: &quot;...&quot;, &quot;reason&quot;: &quot;...&quot;}],
  &quot;update_items&quot;: [
    {&quot;item_id&quot;: &quot;...&quot;, &quot;dimension_id&quot;: &quot;...&quot;, &quot;guidance&quot;: &quot;Rewrite this item so that ...&quot;}
  ],
  &quot;dimension_updates&quot;: [
    {
      &quot;id&quot;: &quot;...&quot;,
      &quot;name&quot;: &quot;...&quot;,
      &quot;measurement_target&quot;: &quot;...&quot;,
      &quot;boundary&quot;: &quot;...&quot;,
      &quot;description&quot;: &quot;...&quot;,
      &quot;approach&quot;: &quot;...&quot;,
      &quot;challenge_effort&quot;: &quot;E3&quot;,
      &quot;target_item_count&quot;: 3,
      &quot;target_source_backed_count&quot;: 0,
      &quot;target_generated_count&quot;: 3,
      &quot;task_types&quot;: [&quot;generation&quot;],
      &quot;task_type_allocation&quot;: [{&quot;task_type&quot;: &quot;generation&quot;, &quot;count&quot;: 3}],
      &quot;item_requirements&quot;: [&quot;...&quot;]
    }
  ],
  &quot;add_dimensions&quot;: [
    {
      &quot;id&quot;: &quot;...&quot;,
      &quot;name&quot;: &quot;...&quot;,
      &quot;measurement_target&quot;: &quot;...&quot;,
      &quot;boundary&quot;: &quot;...&quot;,
      &quot;description&quot;: &quot;...&quot;,
      &quot;approach&quot;: &quot;...&quot;,
      &quot;challenge_effort&quot;: &quot;E3&quot;,
      &quot;target_item_count&quot;: 2,
      &quot;task_types&quot;: [&quot;generation&quot;],
      &quot;task_type_allocation&quot;: [{&quot;task_type&quot;: &quot;generation&quot;, &quot;count&quot;: 2}],
      &quot;item_requirements&quot;: [&quot;...&quot;]
    }
  ],
  &quot;merge_dimensions&quot;: [
    {
      &quot;source_dimension_ids&quot;: [&quot;...&quot;, &quot;...&quot;],
      &quot;new_dimension&quot;: {&quot;id&quot;: &quot;...&quot;, &quot;name&quot;: &quot;...&quot;, &quot;description&quot;: &quot;...&quot;, &quot;approach&quot;: &quot;...&quot;}
    }
  ],
  &quot;split_dimensions&quot;: [
    {
      &quot;source_dimension_id&quot;: &quot;...&quot;,
      &quot;new_dimensions&quot;: [
        {&quot;id&quot;: &quot;...&quot;, &quot;name&quot;: &quot;...&quot;, &quot;description&quot;: &quot;...&quot;, &quot;approach&quot;: &quot;...&quot;}
      ],
      &quot;item_assignments&quot;: [{&quot;item_id&quot;: &quot;...&quot;, &quot;dimension_id&quot;: &quot;...&quot;}]
    }
  ],
  &quot;needs_more_items&quot;: [{&quot;dimension_id&quot;: &quot;...&quot;, &quot;count&quot;: 1, &quot;guidance&quot;: &quot;...&quot;}],
  &quot;notes&quot;: &quot;...&quot;
}
&quot;&quot;&quot; + &quot;\n\nTask-agent guidance for complex interactive item requirements:\n&quot; + TASK_AGENT_GENERATION_GUIDANCE + &quot;\n\nExecutable agent task package guidance:\n&quot; + AGENT_TASK_PACKAGE_GENERATION_GUIDANCE + &quot;\n&quot;</code></pre></details>


<details><summary>Task-agent guidance 来源：<code>evalclaw/protocols/task_agent.py</code></summary><pre><code class="language-python">&quot;&quot;&quot;Task-level agent specification helpers.
<!-- -->
Complex interactive items can provide ``metadata.task_agent`` as a structured
JSON object. The runner uses it to create a task-specific helper agent for
multi-turn simulations, to override target-agent system prompts for simulated
environments, and to pass item-specific scoring guidance to judges.
&quot;&quot;&quot;
from __future__ import annotations
<!-- -->
import json
from typing import Any
<!-- -->
from ..types import BenchmarkConfig, BenchmarkItem, Message
<!-- -->
TASK_AGENT_SCHEMA_VERSION = &quot;evalclaw.task_agent.v1&quot;
TASK_AGENT_METADATA_KEY = &quot;task_agent&quot;
<!-- -->
_RUNNER_PRIVATE_INITIAL_CONTENT_KEYS = frozenset(
    {
        &quot;api_key&quot;,
        &quot;baseline_checks&quot;,
        &quot;bridge_api_key&quot;,
        &quot;bridge_url&quot;,
        &quot;evaluation&quot;,
        &quot;hidden_files&quot;,
        &quot;hidden_file_names&quot;,
        &quot;initial_state_checks&quot;,
        &quot;provider_api_key&quot;,
        &quot;provider_url&quot;,
        &quot;runtime_files&quot;,
        &quot;seed_iso&quot;,
        &quot;setup_commands&quot;,
        &quot;test_command&quot;,
        &quot;vm_provider_api_key&quot;,
        &quot;vm_provider_url&quot;,
        &quot;vm_provisioning&quot;,
    }
)
<!-- -->
<!-- -->
def public_task_agent_initial_content(value: dict[str, Any]) -&gt; dict[str, Any]:
    &quot;&quot;&quot;Remove runner-private environment details from target-visible task context.&quot;&quot;&quot;
<!-- -->
    def scrub(child: Any) -&gt; Any:
        if isinstance(child, dict):
            return {
                str(key): scrub(item)
                for key, item in child.items()
                if str(key).strip().lower() not in _RUNNER_PRIVATE_INITIAL_CONTENT_KEYS
            }
        if isinstance(child, list):
            return [scrub(item) for item in child]
        return child
<!-- -->    
    return scrub(value)
<!-- -->
TASK_AGENT_SCHEMA: dict[str, Any] = {
    &quot;schema_version&quot;: TASK_AGENT_SCHEMA_VERSION,
    &quot;agent_role&quot;: &quot;dialogue_simulator | environment_controller | target_agent_executor | judge | api_oracle | research_synthesizer&quot;,
    &quot;system_prompt&quot;: &quot;System prompt for the task-specific agent.&quot;,
    &quot;initial_content&quot;: {
        &quot;scenario&quot;: &quot;Initial scenario, state, persona, policy, repository brief, or other task context.&quot;,
        &quot;files&quot;: {&quot;relative/path.ext&quot;: &quot;Initial file content when the task starts from a code/workspace state.&quot;},
        &quot;session&quot;: {
            &quot;application&quot;: &quot;GUI/browser/desktop application to launch, when applicable.&quot;,
            &quot;start_state&quot;: &quot;Initial desktop/browser/software state.&quot;,
            &quot;assets&quot;: [
                &quot;Input files, URLs, documents, or resources loaded into the session. &quot;
                &quot;Inline file assets may be objects with path/content.&quot;
            ],
            &quot;asset_files&quot;: {&quot;relative/or/guest/path.ext&quot;: &quot;Inline file content to materialize into a VM session.&quot;},
            &quot;expected_artifacts&quot;: [&quot;Files, page states, or other artifacts expected after completion.&quot;],
        },
        &quot;vm&quot;: {
            &quot;isolation&quot;: &quot;fresh_snapshot | persistent_session | none&quot;,
            &quot;image&quot;: &quot;VM image/template name, if a VM is required.&quot;,
            &quot;snapshot&quot;: &quot;Snapshot/reset point to use before the task.&quot;,
            &quot;display&quot;: {&quot;width&quot;: 1280, &quot;height&quot;: 900, &quot;scale&quot;: 1.0},
            &quot;required_software&quot;: [&quot;Desktop applications, browsers, fonts, plugins, or bridge services.&quot;],
            &quot;network&quot;: &quot;none | restricted | internet&quot;,
            &quot;locale&quot;: &quot;Locale/language assumptions.&quot;,
        },
        &quot;notes&quot;: &quot;Any non-secret setup detail needed to run the task.&quot;,
    },
    &quot;interaction&quot;: {
        &quot;max_turns&quot;: 3,
        &quot;initial_user_message&quot;: &quot;Optional first user message; defaults to BenchmarkItem.prompt.&quot;,
        &quot;user_turns&quot;: [&quot;Optional scripted follow-up turns for deterministic multi-turn tasks.&quot;],
        &quot;followup_instruction&quot;: &quot;How the helper agent should choose the next user turn from the transcript.&quot;,
        &quot;stop_condition&quot;: &quot;When the helper agent should stop the dialogue.&quot;,
    },
    &quot;scoring&quot;: {
        &quot;method&quot;: &quot;agent_judge | runner_judge | deterministic&quot;,
        &quot;instructions&quot;: &quot;How to score the transcript or trace.&quot;,
        &quot;levels&quot;: {
            &quot;5&quot;: &quot;Excellent / pass&quot;,
            &quot;3&quot;: &quot;Partial credit&quot;,
            &quot;1&quot;: &quot;Fail&quot;,
        },
        &quot;pass_fail&quot;: {
            &quot;pass&quot;: &quot;Full-credit completion standard.&quot;,
            &quot;partial&quot;: &quot;Partial-credit standard, if applicable.&quot;,
            &quot;fail&quot;: &quot;Failure standard.&quot;,
        },
    },
    &quot;execution&quot;: {
        &quot;environment_type&quot;: &quot;workspace | code_sandbox | docker_workspace | gui_desktop&quot;,
        &quot;environment_ref&quot;: &quot;metadata.agent_env&quot;,
    },
    &quot;agent_task_package&quot;: &quot;Optional summary pointer; full executable task package should live at metadata.agent_task_package.&quot;,
}
<!-- -->
TASK_AGENT_GENERATION_GUIDANCE = &quot;&quot;&quot;\
For complex interactive items, write a standardized JSON object at
metadata.task_agent using schema_version &quot;evalclaw.task_agent.v1&quot;.
<!-- -->
Fields:
- agent_role: role of the task-specific agent, such as dialogue_simulator,
  environment_controller, target_agent_executor, judge, api_oracle, or
  research_synthesizer.
- system_prompt: concise system prompt for the task-specific agent. It should
  state the evaluation role, non-disclosure rules, and high-level turn policy.
  Do not encode repository files, test suites, command protocols, score tables,
  or large environment state in system_prompt; put those in structured fields.
- initial_content: initial scenario/state. For code or repository tasks, include
  initial files under initial_content.files using relative paths and full file
  contents. Do not use aliases such as file_preview, file_snippets, omitted_files,
  or truncated_files in place of initial_content.files. Do not put secret hidden-test
  answers in visible initial_content. For any task that requires a VM, use
  initial_content.files, metadata.agent_env.visible_files, and/or
  metadata.agent_env.session.asset_files/assets with path/content objects to
  describe task-specific guest files. EvaluationClaw materializes these into a
  per-task NoCloud config-drive ISO before VM startup when no explicit seed ISO
  is supplied. Linux guests consume it with cloud-init; Windows guests consume
  PowerShell user data with Cloudbase-Init. For GUI/browser/desktop-software tasks,
  include public initial_content.session and initial_content.vm summaries:
  application/window, start state, assets/input files/URLs, expected artifacts,
  VM isolation/image/snapshot, and required software/display/network. Keep
  provisioning, baseline checks, evaluator commands, hidden references, runtime
  credentials, and scoring internals exclusively in metadata.agent_env and
  metadata.task_agent.scoring; never copy them into initial_content.
  For VM-backed tasks that can start from a base OS image, metadata.agent_env may
  include vm_provisioning.enabled=true with apt_packages/system_packages,
  pip_packages/python_packages, snap_packages, cran_packages/r_packages,
  bioconductor_packages/bioc_packages, julia_packages, conda_packages with
  conda_channels, cargo_packages, go_packages, gem_packages,
  composer_packages, apk/dnf/yum/pacman package fields for non-Ubuntu bases,
  install_steps, commands, and optional desktop_bridge_install_command/
  desktop_bridge_start_command. For Windows guests, set vm.guest_os=&quot;windows&quot;,
  use winget/choco, Windows features, pip/npm, PowerShell commands or PowerShell
  install steps, and select a base template with Cloudbase-Init NoCloud support.
  EvaluationClaw writes the selected OS-specific setup into the config drive so
  the VM installs task software at first boot.
- interaction: max_turns, optional initial_user_message, optional deterministic
  user_turns, followup_instruction, and stop_condition for multi-turn execution.
- scoring: scoring method plus instructions. For agent_judge, define 1-5 score
  levels. For deterministic or simulated pass/fail tasks, define pass, partial,
  and fail standards.
- execution: environment_type and environment_ref=&quot;metadata.agent_env&quot;. The
  environment itself exists only at metadata.agent_env; never duplicate it in
  task_agent or agent_task_package.
  For iterative code-repair tasks, prefer environment_type=&quot;code_sandbox&quot; with
  metadata.agent_env over a free-form environment_controller dialogue. In those
  tasks, the system_prompt should describe the target model as the coding agent
  who must inspect files, run tests, and revise code. Do not describe the helper
  as the environment itself or as an environment controller.
  Use environment_type=&quot;docker_workspace&quot; only when the task needs realistic
  OS dependencies, non-Python runtimes, package installation, command-line
  diagnostics, or native builds. Both code_sandbox and docker_workspace run in
  isolated containers. Provide image, visible_files, runtime_files,
  hidden_files, setup_commands, test_command, timeout, and resource_limits in
  metadata.agent_env. Setup-only server/application assets belong in
  runtime_files; hidden_files are injected only while the evaluator runs.
  Choose a common official runtime image when the requirement is clear, or set
  image to &quot;auto&quot; / leave it empty so EvaluationClaw can select a suitable
  Docker image from task files and commands before execution.
  If no common Hub image is sufficient, set image=&quot;build://auto&quot; or
  agent_env.image_build.enabled=true. image_build can include base_image,
  system_packages/apt_packages, python_packages/pip_packages,
  node_packages/npm_packages, cran_packages/r_packages,
  bioconductor_packages/bioc_packages, julia_packages, conda_packages with
  conda_channels, cargo_packages, go_packages, gem_packages,
  composer_packages, apk_packages/dnf_packages/yum_packages/pacman_packages,
  install_steps, commands, dockerfile, context_files, tag, rebuild, and
  build_timeout. EvaluationClaw will build a local task image before starting
  the container, then run the workspace in that image.
  Use environment_type=&quot;gui_desktop&quot; when the task requires screenshot-driven
  browser or desktop software operation. Provide max_steps, timeout, session,
  evaluation, and usually requires_vm=true plus vm in agent_env. Put task files
  that should exist in the guest under agent_env.visible_files or
  initial_content.files; put session-specific documents/data under
  agent_env.session.asset_files or assets with path/content objects. The session
  should describe application type, launch/start state, assets/input files/URLs,
  and expected artifacts. The vm object should describe image/template,
  snapshot/reset behavior, display, required software, network policy, and
  locale, and set vm.guest_os to linux or windows for OS-specific setup. Optional
  agent_env.vm_materialization can set guest_user, guest_root, enabled=false, or
  overwrite_seed_iso=true. The evaluation should describe artifact, UI-state, page-state, and
  trace checks with pass/partial/fail criteria. Do not put bridge or VM-provider
  secrets in task metadata; bridge_url, bridge_api_key, vm_provider_url, and
  vm_provider_api_key can be supplied by runtime config.
  For multi-industrial-software collaboration, do not collapse the task into a
  single CAD/EDA/rendering application. Use a VM-backed desktop_software
  agent_env with session.applications, workflow_stages, handoff_artifacts,
  expected_artifacts, and a workflow_manifest.json requirement. Default to a
  reproducible KiCad + FreeCAD + Blender stack when the request does not supply
  licensed software, and make the evaluator check intermediate artifacts,
  final artifacts, units, provenance, and trace evidence of multi-app use. Add
  vm_provisioning package lists or install_steps for kicad/freecad/blender when
  using a clean base image rather than a prebuilt industrial-software template.
  Keep hidden_files secret; the runner injects them only during run_tests.
  For multi-turn delegation tasks, keep the system_prompt focused on the helper
  role and the interaction.turn policy. Store any scripted turns in interaction.
  For API/tool/research/data-analysis tasks, use structured files or tool client
  stubs in initial_content.files rather than embedding large narratives in the
  system prompt.
- For professional, VM-backed, GUI/desktop-software, docker_workspace, or
  long-horizon executable tasks, also provide metadata.agent_task_package using
  schema_version &quot;evalclaw.agent_task_package.v1&quot;. metadata.task_agent remains
  the interaction/scoring prompt contract; metadata.agent_task_package is the
  executable package contract with visible inputs, hidden references, output
  contract, setup/run/evaluate steps, artifact collection, trajectory
  requirements, and provenance.
  &quot;&quot;&quot;
<!-- -->
<!-- -->
def get_task_agent_spec(item: BenchmarkItem) -&gt; dict[str, Any] | None:
    spec = item.metadata.get(TASK_AGENT_METADATA_KEY)
    return spec if isinstance(spec, dict) else None
<!-- -->
<!-- -->
def task_agent_initial_user_message(item: BenchmarkItem) -&gt; str:
    spec = get_task_agent_spec(item)
    interaction = spec.get(&quot;interaction&quot;) if spec else None
    if isinstance(interaction, dict):
        initial = interaction.get(&quot;initial_user_message&quot;)
        if isinstance(initial, str) and initial.strip():
            return initial.strip()
    return item.prompt
<!-- -->
<!-- -->
def task_agent_scripted_turns(item: BenchmarkItem) -&gt; list[str]:
    spec = get_task_agent_spec(item)
    interaction = spec.get(&quot;interaction&quot;) if spec else None
    if isinstance(interaction, dict):
        turns = interaction.get(&quot;user_turns&quot;)
        if isinstance(turns, list) and all(isinstance(turn, str) for turn in turns):
            return [turn for turn in turns if turn.strip()][:5]
    legacy_turns = item.metadata.get(&quot;turns&quot;)
    if isinstance(legacy_turns, list) and all(isinstance(turn, str) for turn in legacy_turns):
        return [turn for turn in legacy_turns if turn.strip()][:5]
    return []
<!-- -->
<!-- -->
def task_agent_max_turns(item: BenchmarkItem, default: int = 3) -&gt; int:
    spec = get_task_agent_spec(item)
    interaction = spec.get(&quot;interaction&quot;) if spec else None
    if isinstance(interaction, dict):
        try:
            parsed = int(interaction.get(&quot;max_turns&quot;, default))
        except (TypeError, ValueError):
            parsed = default
        return max(1, min(parsed, 5))
    return default
<!-- -->
<!-- -->
def task_agent_system_prompt(item: BenchmarkItem, fallback: str) -&gt; str:
    spec = get_task_agent_spec(item)
    system_prompt = spec.get(&quot;system_prompt&quot;) if spec else None
    return system_prompt.strip() if isinstance(system_prompt, str) and system_prompt.strip() else fallback
<!-- -->
<!-- -->
def task_agent_scoring(item: BenchmarkItem) -&gt; dict[str, Any]:
    spec = get_task_agent_spec(item)
    scoring = spec.get(&quot;scoring&quot;) if spec else None
    return scoring if isinstance(scoring, dict) else {}
<!-- -->
<!-- -->
def task_agent_initial_content_text(item: BenchmarkItem, limit: int = 6000) -&gt; str:
    spec = get_task_agent_spec(item)
    initial = spec.get(&quot;initial_content&quot;) if spec else None
    if not initial:
        return &quot;&quot;
    if isinstance(initial, str):
        text = initial
    else:
        text = json.dumps(initial, ensure_ascii=False, indent=2)
    if len(text) &lt;= limit:
        return text
    half = max(1, limit // 2)
    return text[:half] + &quot;\n...\n&quot; + text[-half:]
<!-- -->
<!-- -->
def task_agent_available(config: BenchmarkConfig) -&gt; bool:
    return bool(config.task_models)
<!-- -->
<!-- -->
def compact_task_agent_for_qc(spec: dict[str, Any]) -&gt; dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (&quot;schema_version&quot;, &quot;agent_role&quot;, &quot;system_prompt&quot;):
        value = spec.get(key)
        if isinstance(value, str):
            if key == &quot;system_prompt&quot; and len(value) &gt; 800:
                compact[key] = (
                    value[:400]
                    + &quot;\n... QC review excerpt clipped; canonical value is complete and longer ...\n&quot;
                    + value[-400:]
                )
                compact[&quot;system_prompt_character_count&quot;] = len(value)
            else:
                compact[key] = value
    interaction = spec.get(&quot;interaction&quot;)
    if isinstance(interaction, dict):
        compact[&quot;interaction&quot;] = {
            key: value
            for key, value in interaction.items()
            if key in {&quot;max_turns&quot;, &quot;user_turns&quot;, &quot;followup_instruction&quot;, &quot;stop_condition&quot;}
        }
    scoring = spec.get(&quot;scoring&quot;)
    if isinstance(scoring, dict):
        compact[&quot;scoring&quot;] = {
            key: value
            for key, value in scoring.items()
            if key in {&quot;method&quot;, &quot;instructions&quot;, &quot;levels&quot;, &quot;pass_fail&quot;}
        }
    initial = spec.get(&quot;initial_content&quot;)
    if isinstance(initial, dict):
        initial_summary: dict[str, Any] = {}
        files = initial.get(&quot;files&quot;)
        if isinstance(files, dict):
            initial_summary[&quot;file_names&quot;] = list(files.keys())[:20]
            initial_summary[&quot;file_count&quot;] = len(files)
            initial_summary[&quot;file_content_note&quot;] = (
                &quot;Full file contents are omitted from the LLM QC sample to avoid &quot;
                &quot;confusing compact excerpts with task truncation.&quot;
            )
        session = initial.get(&quot;session&quot;)
        if isinstance(session, dict):
            initial_summary[&quot;session_keys&quot;] = list(session.keys())[:20]
            for key in (&quot;kind&quot;, &quot;application&quot;, &quot;entrypoint&quot;, &quot;start_url&quot;):
                if key in session:
                    initial_summary[f&quot;session_{key}&quot;] = session[key]
            assets = session.get(&quot;assets&quot;)
            if isinstance(assets, list):
                initial_summary[&quot;session_assets&quot;] = assets[:20]
            expected_artifacts = session.get(&quot;expected_artifacts&quot;)
            if isinstance(expected_artifacts, list):
                initial_summary[&quot;session_expected_artifacts&quot;] = expected_artifacts[:20]
        vm = initial.get(&quot;vm&quot;)
        if isinstance(vm, dict):
            initial_summary[&quot;vm_keys&quot;] = list(vm.keys())[:20]
            for key in (&quot;isolation&quot;, &quot;image&quot;, &quot;snapshot&quot;, &quot;network&quot;, &quot;locale&quot;):
                if key in vm:
                    initial_summary[f&quot;vm_{key}&quot;] = vm[key]
            required_software = vm.get(&quot;required_software&quot;)
            if isinstance(required_software, list):
                initial_summary[&quot;vm_required_software&quot;] = required_software[:20]
            display = vm.get(&quot;display&quot;)
            if isinstance(display, dict):
                initial_summary[&quot;vm_display&quot;] = display
        evaluation = initial.get(&quot;evaluation&quot;)
        if isinstance(evaluation, dict):
            initial_summary[&quot;evaluation_keys&quot;] = list(evaluation.keys())[:20]
            for key in (&quot;method&quot;, &quot;pass_criteria&quot;, &quot;partial_criteria&quot;, &quot;fail_criteria&quot;):
                if key in evaluation:
                    initial_summary[f&quot;evaluation_{key}&quot;] = str(evaluation[key])[:800]
        for key, value in initial.items():
            if key == &quot;files&quot;:
                continue
            if key in {&quot;session&quot;, &quot;vm&quot;, &quot;evaluation&quot;}:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                initial_summary[key] = value
        if initial_summary:
            compact[&quot;initial_content&quot;] = initial_summary
    execution = spec.get(&quot;execution&quot;)
    if isinstance(execution, dict):
        compact_execution: dict[str, Any] = {}
        environment_type = execution.get(&quot;environment_type&quot;)
        if isinstance(environment_type, str):
            compact_execution[&quot;environment_type&quot;] = environment_type
        environment_ref = execution.get(&quot;environment_ref&quot;)
        if isinstance(environment_ref, str):
            compact_execution[&quot;environment_ref&quot;] = environment_ref
        if compact_execution:
            compact[&quot;execution&quot;] = compact_execution
    return compact
<!-- -->
<!-- -->
def transcript_text(history: list[Message]) -&gt; str:
    return &quot;\n\n&quot;.join(f&quot;[{message.role.upper()}] {message.content}&quot; for message in history)</code></pre></details>


<details><summary>Agent task package guidance 来源：<code>evalclaw/protocols/agent_task_package.py</code></summary><pre><code class="language-python">&quot;&quot;&quot;Executable agent task package protocol.&quot;&quot;&quot;
from __future__ import annotations
<!-- -->
import copy
from typing import Any
<!-- -->
from ..types import BenchmarkItem, TaskType
<!-- -->
AGENT_TASK_PACKAGE_SCHEMA_VERSION = &quot;evalclaw.agent_task_package.v1&quot;
AGENT_TASK_PACKAGE_METADATA_KEY = &quot;agent_task_package&quot;
<!-- -->
AGENT_TASK_PACKAGE_SCHEMA: dict[str, Any] = {
    &quot;schema_version&quot;: AGENT_TASK_PACKAGE_SCHEMA_VERSION,
    &quot;capability_target&quot;: {
        &quot;name&quot;: &quot;Agent capability being measured.&quot;,
        &quot;content_summary&quot;: &quot;Short report label.&quot;,
        &quot;description&quot;: &quot;Behavior tested by the task.&quot;,
    },
    &quot;environment_requirements&quot;: {
        &quot;environment_ref&quot;: &quot;metadata.agent_env&quot;,
        &quot;type&quot;: &quot;workspace | code_sandbox | docker_workspace | gui_desktop&quot;,
        &quot;os&quot;: &quot;linux | windows | macos | any&quot;,
        &quot;requires_vm&quot;: False,
        &quot;requires_gui&quot;: False,
        &quot;required_software&quot;: [&quot;Runtime or application requirements, without secrets.&quot;],
        &quot;required_capabilities&quot;: [&quot;Provider image capabilities required at runtime.&quot;],
        &quot;network&quot;: &quot;none | restricted | internet&quot;,
    },
    &quot;visible_inputs&quot;: {
        &quot;instructions&quot;: &quot;User-visible task instructions.&quot;,
        &quot;file_names&quot;: [&quot;Paths whose contents live only in metadata.agent_env.visible_files.&quot;],
        &quot;assets&quot;: [&quot;Public datasets, documents, URLs, images, or project files.&quot;],
    },
    &quot;hidden_references&quot;: {
        &quot;staging_phase&quot;: &quot;evaluation_only&quot;,
        &quot;file_names&quot;: [&quot;Paths whose contents live only in metadata.agent_env.hidden_files.&quot;],
        &quot;runtime_file_names&quot;: [&quot;Setup-only paths from metadata.agent_env.runtime_files.&quot;],
        &quot;reference_artifacts&quot;: [&quot;Runner-private expected outputs or states.&quot;],
        &quot;notes&quot;: &quot;Never expose evaluator-only material to the target.&quot;,
    },
    &quot;output_contract&quot;: {
        &quot;expected_artifacts&quot;: [&quot;Paths or states the target must produce.&quot;],
        &quot;artifact_requirement&quot;: &quot;all | any | exactly_one&quot;,
        &quot;required_outputs&quot;: [&quot;Structured outputs or final states.&quot;],
        &quot;schema&quot;: {},
        &quot;constraints&quot;: [&quot;Format, location, and side-effect constraints.&quot;],
    },
    &quot;execution&quot;: {
        &quot;environment_ref&quot;: &quot;metadata.agent_env&quot;,
        &quot;setup_command_count&quot;: 0,
        &quot;run&quot;: &quot;How the target interacts with the environment.&quot;,
        &quot;evaluate&quot;: &quot;Evaluator command or bridge method.&quot;,
        &quot;timeout_s&quot;: 0,
        &quot;max_steps&quot;: 0,
    },
    &quot;evaluation&quot;: {
        &quot;method&quot;: &quot;deterministic | artifact_check | bridge_state_check | judge&quot;,
        &quot;checks&quot;: [&quot;Named scoring checks.&quot;],
        &quot;score_range&quot;: [0, 1],
        &quot;pass_criteria&quot;: &quot;Full-credit standard.&quot;,
        &quot;partial_criteria&quot;: &quot;Partial-credit standard.&quot;,
        &quot;fail_criteria&quot;: &quot;Failure standard.&quot;,
    },
    &quot;artifact_collection&quot;: {
        &quot;collect_paths&quot;: [&quot;Artifacts to retain.&quot;],
        &quot;collect_trajectory&quot;: True,
        &quot;logs&quot;: [&quot;stdout&quot;, &quot;stderr&quot;, &quot;tool_trace&quot;, &quot;screenshots&quot;],
    },
    &quot;trajectory_requirements&quot;: {
        &quot;required_tools&quot;: [&quot;Tools required by the intended workflow.&quot;],
        &quot;forbidden_shortcuts&quot;: [&quot;Direct access to protected runtime or evaluator material.&quot;],
        &quot;audit_notes&quot;: &quot;What the trace should demonstrate.&quot;,
    },
    &quot;resource_provenance&quot;: {
        &quot;source_kind&quot;: &quot;generated_fixture | imported | web | dataset | repo&quot;,
        &quot;source_uris&quot;: [&quot;https://...&quot;],
        &quot;license&quot;: &quot;&quot;,
        &quot;construction_notes&quot;: &quot;&quot;,
    },
}
<!-- -->
AGENT_TASK_PACKAGE_GENERATION_GUIDANCE = &quot;&quot;&quot;\
For executable agent tasks, add metadata.agent_task_package with schema_version
&quot;evalclaw.agent_task_package.v1&quot;.
<!-- -->
metadata.agent_env is the sole executable environment definition. The package
must reference it with environment_ref=&quot;metadata.agent_env&quot; and must not copy
file contents, VM configuration, image-build configuration, browser settings,
setup commands, or hidden evaluator content.
<!-- -->
Keep three lifecycle phases distinct:
- visible_files: present before the target starts and available through tools.
- runtime_files: available to setup/runtime but protected from target file tools.
- hidden_files: injected only while the evaluator runs.
<!-- -->
Raw shell access must not be exposed when runtime_files or hidden_files are
present, because it would bypass lifecycle protections or leave a background
process waiting for evaluator injection. Use structured workspace tools and the
runner-private evaluator instead.
<!-- -->
The package describes capability intent, public input names, private reference
names, output contracts, evaluator semantics, artifact collection, trajectory
requirements, and provenance. Evaluators should write
{&quot;score&quot;: 0.0-1.0, &quot;passed&quot;: true|false, &quot;details&quot;: &quot;...&quot;} to the configured
evaluation.result_path. Numeric score files are valid for simple evaluators.
Target-controlled stdout is not a trusted score source and is ignored by
default; enable evaluation.allow_stdout_score=true only when the evaluator&#39;s
stdout cannot be influenced by the target. Define explicit partial-credit
behavior and keep all scores within [0, 1].
&quot;&quot;&quot;
<!-- -->
<!-- -->
def _env_from_item(item: BenchmarkItem) -&gt; dict[str, Any]:
    env = item.metadata.get(&quot;agent_env&quot;)
    if isinstance(env, dict):
        return env
    return {}
<!-- -->
<!-- -->
def get_agent_task_package(item: BenchmarkItem) -&gt; dict[str, Any] | None:
    package = item.metadata.get(AGENT_TASK_PACKAGE_METADATA_KEY)
    return package if isinstance(package, dict) else None
<!-- -->
<!-- -->
def item_requires_agent_task_package(item: BenchmarkItem) -&gt; bool:
    if item.task_type != TaskType.agent:
        return False
    env = _env_from_item(item)
    env_type = str(env.get(&quot;type&quot;) or &quot;&quot;).lower()
    if env_type in {&quot;docker_workspace&quot;, &quot;gui_desktop&quot;}:
        return True
    if bool(env.get(&quot;requires_vm&quot;) or env.get(&quot;vm&quot;)):
        return True
    tags = {str(tag).lower() for tag in item.tags}
    if tags &amp; {&quot;ale_style&quot;, &quot;professional_workflow&quot;, &quot;long_horizon&quot;, &quot;executable_task_package&quot;}:
        return True
    style = str(item.metadata.get(&quot;agent_benchmark_style&quot;) or &quot;&quot;).lower()
    return style in {&quot;ale&quot;, &quot;ale_style&quot;, &quot;executable_task_package&quot;}
<!-- -->
<!-- -->
def _has_visible_inputs(value: Any) -&gt; bool:
    if not isinstance(value, dict):
        return False
    if str(value.get(&quot;instructions&quot;) or &quot;&quot;).strip():
        return True
    for key in (&quot;file_names&quot;, &quot;assets&quot;, &quot;resources&quot;):
        child = value.get(key)
        if isinstance(child, (dict, list)) and bool(child):
            return True
    return bool(value.get(&quot;session&quot;))
<!-- -->
<!-- -->
def _has_output_contract(value: Any) -&gt; bool:
    if not isinstance(value, dict):
        return False
    for key in (&quot;expected_artifacts&quot;, &quot;required_outputs&quot;, &quot;schema&quot;, &quot;constraints&quot;):
        child = value.get(key)
        if isinstance(child, (dict, list)) and bool(child):
            return True
        if isinstance(child, str) and child.strip():
            return True
    return False
<!-- -->
<!-- -->
def _has_evaluation(value: Any) -&gt; bool:
    if not isinstance(value, dict):
        return False
    if str(value.get(&quot;method&quot;) or &quot;&quot;).strip():
        return True
    if isinstance(value.get(&quot;checks&quot;), list) and value[&quot;checks&quot;]:
        return True
    return any(str(value.get(key) or &quot;&quot;).strip() for key in (&quot;pass_criteria&quot;, &quot;partial_criteria&quot;, &quot;fail_criteria&quot;))
<!-- -->
<!-- -->
def agent_task_package_issues(item: BenchmarkItem) -&gt; list[str]:
    &quot;&quot;&quot;Return static validation issues for metadata.agent_task_package.&quot;&quot;&quot;
    package = get_agent_task_package(item)
    required = item_requires_agent_task_package(item)
    if package is None:
        return (
            [
                &quot;Executable agent task is missing metadata.agent_task_package.&quot;,
            ]
            if required
            else []
        )
<!-- -->
    issues: list[str] = []
    if package.get(&quot;schema_version&quot;) != AGENT_TASK_PACKAGE_SCHEMA_VERSION:
        issues.append(&quot;metadata.agent_task_package schema_version is missing or invalid.&quot;)
    capability = package.get(&quot;capability_target&quot;)
    if not isinstance(capability, dict) or not str(capability.get(&quot;name&quot;) or capability.get(&quot;description&quot;) or &quot;&quot;).strip():
        issues.append(&quot;metadata.agent_task_package.capability_target must name the evaluated capability.&quot;)
    if not _has_visible_inputs(package.get(&quot;visible_inputs&quot;)):
        issues.append(&quot;metadata.agent_task_package.visible_inputs must describe visible instructions/files/assets/session.&quot;)
    if not _has_output_contract(package.get(&quot;output_contract&quot;)):
        issues.append(&quot;metadata.agent_task_package.output_contract must define expected artifacts, outputs, or schema.&quot;)
    if not _has_evaluation(package.get(&quot;evaluation&quot;)):
        issues.append(&quot;metadata.agent_task_package.evaluation must define method, checks, or pass/partial/fail criteria.&quot;)
<!-- -->    
    env = _env_from_item(item)
    env_type = str(env.get(&quot;type&quot;) or &quot;&quot;).lower()
    if env_type in {&quot;docker_workspace&quot;, &quot;gui_desktop&quot;}:
        artifact_collection = package.get(&quot;artifact_collection&quot;)
        if not isinstance(artifact_collection, dict) or not (
            artifact_collection.get(&quot;collect_paths&quot;) or artifact_collection.get(&quot;collect_trajectory&quot;)
        ):
            issues.append(&quot;Docker/GUI agent task package must define artifact_collection paths or trajectory capture.&quot;)
        trajectory = package.get(&quot;trajectory_requirements&quot;)
        if not isinstance(trajectory, dict) or not trajectory.get(&quot;required_tools&quot;):
            issues.append(&quot;Docker/GUI agent task package must define trajectory_requirements.required_tools.&quot;)
<!-- -->    
    visible_files = set()
    visible_inputs = package.get(&quot;visible_inputs&quot;)
    if isinstance(visible_inputs, dict) and isinstance(visible_inputs.get(&quot;file_names&quot;), list):
        visible_files = {str(path) for path in visible_inputs[&quot;file_names&quot;]}
    hidden_refs = package.get(&quot;hidden_references&quot;)
    if isinstance(hidden_refs, dict) and isinstance(hidden_refs.get(&quot;file_names&quot;), list):
        overlap = visible_files &amp; {str(path) for path in hidden_refs[&quot;file_names&quot;]}
        if overlap:
            issues.append(
                &quot;metadata.agent_task_package exposes the same path as visible and evaluator-only: &quot;
                + &quot;, &quot;.join(sorted(overlap)[:5])
            )
    return issues
<!-- -->
<!-- -->
def public_agent_task_package(package: dict[str, Any]) -&gt; dict[str, Any]:
    &quot;&quot;&quot;Return a target-visible package summary with hidden references redacted.&quot;&quot;&quot;
    public = copy.deepcopy(package)
    public.pop(&quot;evaluation&quot;, None)
    hidden = public.get(&quot;hidden_references&quot;)
    if isinstance(hidden, dict):
        redacted = {
            &quot;staging_phase&quot;: hidden.get(&quot;staging_phase&quot;) or &quot;post_agent_or_runner_private&quot;,
            &quot;notes&quot;: &quot;Hidden references are runner-private and are not exposed to the target agent.&quot;,
        }
        if isinstance(hidden.get(&quot;file_names&quot;), list):
            redacted[&quot;file_count&quot;] = len(hidden[&quot;file_names&quot;])
        public[&quot;hidden_references&quot;] = redacted
    execution = public.get(&quot;execution&quot;)
    if isinstance(execution, dict):
        execution.pop(&quot;evaluate&quot;, None)
    return public
<!-- -->
<!-- -->
def _compact_text(value: Any, *, limit: int) -&gt; str:
    text = str(value)
    if len(text) &lt;= limit:
        return text
    return (
        text[:limit].rstrip()
        + &quot;\n[QC summary clipped here; canonical metadata.agent_task_package contains the full field.]&quot;
    )
<!-- -->
<!-- -->
def compact_agent_task_package(package: dict[str, Any]) -&gt; dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (&quot;schema_version&quot;, &quot;style&quot;):
        if key in package:
            compact[key] = package[key]
    capability = package.get(&quot;capability_target&quot;)
    if isinstance(capability, dict):
        compact[&quot;capability_target&quot;] = {
            key: _compact_text(value, limit=800)
            for key, value in capability.items()
            if isinstance(value, (str, int, float, bool))
        }
    for key in (&quot;environment_requirements&quot;, &quot;output_contract&quot;, &quot;evaluation&quot;, &quot;artifact_collection&quot;, &quot;trajectory_requirements&quot;):
        value = package.get(key)
        if isinstance(value, dict):
            compact[key] = {str(k): v for k, v in list(value.items())[:12]}
    visible = package.get(&quot;visible_inputs&quot;)
    if isinstance(visible, dict):
        compact_visible: dict[str, Any] = {}
        if &quot;instructions&quot; in visible:
            compact_visible[&quot;instructions&quot;] = _compact_text(visible[&quot;instructions&quot;], limit=2000)
        files = visible.get(&quot;files&quot;)
        if isinstance(files, dict):
            compact_visible[&quot;file_names&quot;] = list(files.keys())[:20]
            compact_visible[&quot;file_count&quot;] = len(files)
        assets = visible.get(&quot;assets&quot;)
        if isinstance(assets, list):
            compact_visible[&quot;assets&quot;] = assets[:20]
        if compact_visible:
            compact[&quot;visible_inputs&quot;] = compact_visible
    hidden = package.get(&quot;hidden_references&quot;)
    if isinstance(hidden, dict):
        compact_hidden: dict[str, Any] = {}
        files = hidden.get(&quot;files&quot;)
        if isinstance(files, dict):
            compact_hidden[&quot;file_names&quot;] = list(files.keys())[:20]
            compact_hidden[&quot;file_count&quot;] = len(files)
        refs = hidden.get(&quot;reference_artifacts&quot;)
        if isinstance(refs, list):
            compact_hidden[&quot;reference_artifacts&quot;] = refs[:20]
        if hidden.get(&quot;staging_phase&quot;):
            compact_hidden[&quot;staging_phase&quot;] = hidden[&quot;staging_phase&quot;]
        if compact_hidden:
            compact[&quot;hidden_references&quot;] = compact_hidden
    return compact</code></pre></details>


<a id="appendix-c"></a>
## 附录 C：Planner 完整输入与输出契约

### C.1 初次规划

实际调用：

~~~python
call_llm(
    [Message(role="user", content=user_content)],
    system=benchmark_planner_system_prompt(BENCHMARK_PLANNER_SYSTEM_PROMPT),
    **planner_role_settings,
    backend=config.llm_backend,
    max_tokens=4096_or_16384,
)
~~~

`user_content`：

<details><summary>C.1 Planner user_content 完整结构</summary><pre><code class="language-text">The following read-only Planner resources are available by path.
<!-- -->
&lt;PLANNER_RESOURCES&gt;
&lt;FILE path=&quot;resources/instruction.md&quot;&gt;
# User Evaluation Request
<!-- -->
{标准化后的英文 goal}
<!-- -->
# Framework-Supplied Task-Design Constraints
<!-- -->
{
  &quot;scale_budget&quot;: &quot;mid&quot;,
  &quot;scale_budget_guidance&quot;: &quot;Use MID budget: plan about 20 total items. ...&quot;,
  &quot;count_policy&quot;: &quot;Use scale_budget as guidance for the total number of tasks.&quot;,
  &quot;available_task_types&quot;: [&quot;choice&quot;, &quot;fill_blank&quot;, &quot;generation&quot;, &quot;multi_turn&quot;, &quot;agent&quot;],
  &quot;available_environment_types&quot;: [&quot;workspace&quot;, &quot;code_sandbox&quot;, &quot;docker_workspace&quot;, &quot;gui_desktop&quot;],
  &quot;challenge_effort_distribution&quot;: {&quot;E1&quot;: 0.2, &quot;E2&quot;: 0.3, &quot;E3&quot;: 0.5},
  &quot;effort_policy&quot;: &quot;The framework requires the total task count to be distributed across challenge_effort levels as follows: E1 ≈ 20%, E2 ≈ 30%, E3 ≈ 50%. Set each TaskDesign.challenge_effort so the planned per-level task counts approximate these ratios.&quot;
}
&lt;/FILE&gt;
<!-- -->
&lt;FILE path=&quot;resources/deepresearch/brief.json&quot;&gt;
{compact_brief_context，若存在}
&lt;/FILE&gt;
&lt;/PLANNER_RESOURCES&gt;
<!-- --></code></pre></details>
上例展示的是用户**未**显式指定题数的路径（传 `scale_budget`）。若用户显式指定了无歧义总题数，则 `scale_budget`/`scale_budget_guidance` 会被替换为 `explicit_total_task_count`（此时 `count_policy` 对应改为 "The user explicitly requested exactly this many tasks..."），审计阶段会强制各 `TaskDesign.task_count` 之和精确等于该数（见附录 C.3）。`source_backed_ratio` 只在显式设置时出现。`challenge_effort_distribution` 与 `effort_policy` 仅在配置了全局 E1/E2/E3 比例（非空且和为 1）时出现。

在 deep research 未开启，从而没有 research brief 时，第二个 FILE 替换为：

~~~xml
<DIRECTORY path="resources/deepresearch" empty="true" />
~~~

Planner 可见的 compact brief 字段：

~~~json
{
  "dimensions": [{"name": "...", "measurement_target": "...", "boundary": "...", "task_shapes": ["..."]}],
  "difficulty_factors": [{"factor": "...", "observable_signal": "...", "design_implication": "..."}],
  "task_patterns": [{"name": "...", "description": "...", "suitable_task_types": ["..."], "scoring_direction": "..."}],
  "source_recommendations": [{"title": "...", "url": "...", "why_useful": "..."}],
  "evidence": [{"observation": "...", "design_implication": "...", "source_urls": ["..."]}],
  "source_material_index": [{"title": "...", "url": "...", "content_chars": 12345}],
  "challenge_effort_anchors": {"最多": "4 个"}
}
~~~

框架在 brief 的 `<FILE>` 内容里、JSON 之后追加一段字段释义（`evalclaw/research/deep_research.py::compact_brief_field_guide`，英文原文如下），这样 Planner 不必从变量名猜字段语义。释义为参考材料不是输出 schema：

```
Field meanings for the Benchmark Design Research brief above (the brief is reference material, not an output schema):
- dimensions: evidence-supported candidates for measurable, non-overlapping benchmark dimensions; the Planner decides whether to adopt them.
- difficulty_factors: observable sources of task difficulty and their direct construction implications.
- task_patterns: task shapes that can measure the goal, including suitable task types and scoring directions.
- source_recommendations: verified documents or datasets that can ground source-backed tasks.
- evidence: external observations paired with concrete benchmark-design implications and their source URLs.
- source_material_index: a list of {title, url, content_chars} describing the fetched source bodies retained by the framework; the TaskBuilder may read a full source body by URL via read_research_source rather than re-fetching.
- challenge_effort_anchors: what E1-E3 construction effort means for this evaluation goal, as a guide for choosing TaskDesign.challenge_effort.
```

### C.2 计划修复输入

Planner 输出不会直接采用，而是先经过纯代码的确定性审计，检查：必填字段都完整、复核用户显式总题数等。如果不通过，会让 Planner 进行修复，本节介绍修复时给 Planner 的 prompt。确定性审计内容见下一节 C.3。

每次是新的单 user-message 调用，system 不变，在原资源包后追加：

~~~xml
<FILE path="resources/repair.json">
{
  "attempt": 2,
  "issues": ["完整错误列表"],
  "previous_response": {"上次解析结果，或 null"},
  "instruction": "Return the complete planning JSON file again. Fix every listed issue while changing sound parts as little as possible."
}
</FILE>
~~~

模型调用异常、非 JSON、Pydantic 解析失败和确定性计划审计失败都可能触发下一次 Planner 尝试。完整错误列表由 `evalclaw/planning/task_planner.py::_audit_plan` 产生（见[附录 C.3](#appendix-c)审计清单），每个错误都是一条字符串，描述具体问题（如「dimension/task_design 缺必填字段」、「task_count 总和不匹配显式题数」、「environment category 不可用」等）。错误呈现方式：框架把 `errors: list[str]` 与 `previous_response` 组装为修复 payload（见上方 C.2 示例），直接作为 user 消息传给 Planner，要求「Fix every listed issue while changing sound parts as little as possible」并返回修复后的完整 JSON。
HTTP/传输重试是底层另一套机制。

### C.3 输出

模型必须返回根对象含 `plan` 的纯 JSON，完整结构在 B.3 的 `universal_format.json`。
框架随后解析并审计 Dimension/TaskDesign ID、必填字段、精确总题数、环境、multi-turn 模式和 URL。
它不审计任何构题包归属，因为 Planner 输出里没有这类字段。`subjects` 和标准化
`scale_budget` 是模型返回后由框架写入；`builder_jobs` 则在访问时由 TaskDesign 确定性派生。

<a id="appendix-d"></a>
## 附录 D：TaskBuilder payload 与各题型字段

### D.0 构题前来源收集

`evalclaw/construction/resources.py::_select_blueprint_sources` 为当前 TaskDesign job 收集候选来源，顺序是：

1. 先把 Planner `source_plan.suggested_urls`（受 `max_research_sources` 上限）直接存成 `web` 来源——这是 Planner 已给的建议，不触发搜索；
2. 若来源数已达 `max_research_sources`，直接返回；
3. 若 `Dimension.needs_research=false` 或 `use_web_research=false`，返回当前名单（不再补来源）；若需要并启用了研究但 Research 角色未配置，则直接报错；
4. 否则从 `blueprint.resource_queries`（缺省回落 `dimension.research_queries`；两者都空时用 `f"{dimension.name} {blueprint.title} benchmark task resources"` 之类的默认查询）取其前 2 条做 `web_search`，把结果各 citation 的 URL 去重后追加为 `web` 来源，直到来源数达 `max_research_sources`。

「来源不足」不是一个显式的布尔判断，而是由上面第 3/4 步共同决定：只要需要研究、网页研究开启、Research 已配置、且当前来源未满上限，就会用研究查询补齐。`max_research_sources` 是这条来源数上限（配置见[附录 G](#appendix-g)）。收集结果随后被标准化为 `TaskResource` 经去重进入 suite 的 resources，并以 `resources.context` 呈现给 TaskBuilder（见 D.1）。

这里的查询回落只发生在选择查询之前：TaskDesign 没有 `search_queries` 时才使用 Dimension 查询。执行某条查询后若遇到 `search_backend="none"`、缺少所需 API key 或后端/API 错误，构题流程直接报错，不会改用 Dimension 查询掩盖故障。搜索超时会对同一条查询最多尝试 3 次，仍然超时则报错。合法但没有搜索结果不属于系统故障，此时可以继续尝试所选查询列表中的下一条查询。

<a id="appendix-d-payload"></a>
### D.1 初次 payload

每个 TaskDesign 是一个独立调用，user message 为下面对象的格式化 JSON：

<details><summary>D.1 TaskBuilder 初次 payload 完整 JSON</summary><pre><code class="language-json">{
  &quot;benchmark_context&quot;: {
    &quot;objective&quot;: &quot;...&quot;,
    &quot;task_types&quot;: [&quot;EvalSpec 全部题型&quot;],
    &quot;scale&quot;: &quot;...&quot;,
    &quot;constraints&quot;: [&quot;...&quot;],
    &quot;planner_notes&quot;: &quot;...&quot;,
    &quot;other_capabilities&quot;: [
      {&quot;id&quot;: &quot;...&quot;, &quot;name&quot;: &quot;...&quot;, &quot;description&quot;: &quot;...&quot;, &quot;task_types&quot;: [&quot;...&quot;], &quot;requirements&quot;: [&quot;...&quot;]}
    ]
  },
  &quot;task_plan&quot;: {
    &quot;capability&quot;: {
      &quot;id&quot;: &quot;...&quot;,
      &quot;name&quot;: &quot;...&quot;,
      &quot;description&quot;: &quot;...&quot;,
      &quot;measurement_target&quot;: &quot;测量目标及该维度必须覆盖的全部内容&quot;,
      &quot;boundary&quot;: &quot;范围边界、排除内容、相邻能力、混淆因素和禁止偏移&quot;,
      &quot;approach&quot;: &quot;...&quot;,
      &quot;challenge_effort&quot;: &quot;E1-E3&quot;,
      &quot;task_types&quot;: [&quot;...&quot;],
      &quot;task_type_allocation&quot;: [{&quot;task_type&quot;: &quot;...&quot;, &quot;count&quot;: 1}],
      &quot;requirements&quot;: [&quot;...&quot;],
      &quot;coverage&quot;: {
        &quot;target_item_count&quot;: 1,
        &quot;target_source_backed_count&quot;: 0,
        &quot;target_generated_count&quot;: 1
      },
      &quot;research_needed&quot;: false
    },
    &quot;builder_job_id&quot;: &quot;{dimension.id}__{task_design.id}&quot;,
    &quot;task_design&quot;: {
      &quot;id&quot;: &quot;...&quot;,
      &quot;task_type&quot;: &quot;choice&quot;,
      &quot;task_count&quot;: 5,
      &quot;challenge_effort&quot;: &quot;E1-E3&quot;,
      &quot;content_design&quot;: {&quot;完整 Planner TaskDesign 字段&quot;: &quot;...&quot;},
      &quot;input_requirements&quot;: {},
      &quot;interaction_requirements&quot;: {},
      &quot;environment_requirements&quot;: {},
      &quot;output_requirements&quot;: {},
      &quot;scoring_contract&quot;: {},
      &quot;source_plan&quot;: {},
      &quot;construction_requirements&quot;: [],
      &quot;type_specific_requirements&quot;: {},
      &quot;metadata&quot;: {},
      &quot;required_return_task_count&quot;: 5
    }
  },
  &quot;resources&quot;: {
    &quot;context&quot;: &quot;候选资源文本&quot;,
    &quot;deep_research&quot;: {&quot;compact brief 或空对象&quot;: &quot;...&quot;},
    &quot;selection&quot;: {
      &quot;queries&quot;: [&quot;...&quot;],
      &quot;suggested_urls&quot;: [&quot;...&quot;],
      &quot;strategy&quot;: &quot;...&quot;,
      &quot;requirements&quot;: [&quot;...&quot;]
    }
  },
  &quot;available_models&quot;: {
    &quot;models&quot;: [{&quot;id&quot;: &quot;...&quot;, &quot;model&quot;: &quot;...&quot;, &quot;provider&quot;: &quot;...&quot;}]
  },
  &quot;task_builder_contract&quot;: {
    &quot;task_schema&quot;: {
      &quot;required&quot;: [&quot;id&quot;, &quot;dimension_id&quot;, &quot;task_type&quot;, &quot;title&quot;, &quot;prompt&quot;, &quot;challenge_effort&quot;, &quot;metadata&quot;],
      &quot;optional&quot;: [&quot;按当前题型动态生成&quot;],
      &quot;allowed_task_types&quot;: [&quot;...&quot;],
      &quot;required_task_type_counts&quot;: {&quot;choice&quot;: 5},
      &quot;required_task_design_counts&quot;: {&quot;design_id&quot;: 5},
      &quot;task_design_metadata_field&quot;: &quot;task_design_id&quot;,
      &quot;type_requirements&quot;: {&quot;generation&quot;: [&quot;完整规则&quot;]}
    },
    &quot;response_format&quot;: &quot;Return one complete JSON object with construction_notes, resources, and tasks.&quot;,
    &quot;environment_skill&quot;: {&quot;仅需要环境的 TaskDesign 出现&quot;: &quot;...&quot;}
  }
}
<!-- --></code></pre></details>

`resources.context` 可包含 Planner URL、构题前搜索候选、ResearchBrief 索引或 self-generated fixture。
TaskBuilder 返回的 resources 会标准化、去重，再由每题顶层 `resource_ids` 建立 provenance。

<a id="appendix-d-tools"></a>
### D.2 构题研究消息

满足“需要研究且有保留正文/网页工具”，或“E3 且网页工具可用”，并且不是 QC repair 时启用。
首条 user JSON 在 D.1 的 `resources` 中增加：

~~~json
{
  "interactive_research": {
    "enabled": true,
    "max_tool_calls": "1-12，默认 6",
    "available_tools": ["read_research_source", "search_web", "fetch_url"],
    "instruction": "Use tools only when they materially improve the task; return complete JSON when done."
  }
}
~~~

工具：

- `read_research_source(url, max_chars?)`：按 URL 读取本次 Deep Research 已归档正文。
- `search_web(query, max_results?)`：发起新查询。
- `fetch_url(url, max_chars?)`：抓取公开 HTTP(S) 正文。

assistant tool call 与 tool results 继续追加进同一 `messages`。Anthropic、OpenAI Chat Completions、
OpenAI Responses 分别使用各自原生 tool-result 格式。达到预算后追加：

~~~text
The bounded research budget is exhausted. Return the complete final task-builder JSON now without further tool calls.
~~~

然后以 `tools=[]` 做最终请求。

<a id="appendix-d-task-types"></a>
### D.3 各题型完整字段契约

#### 公共字段

动态 contract 强制每题提供：

| 字段 | 要求 |
|---|---|
| `id` | 本次返回内非空；全局冲突由框架稳定改名 |
| `dimension_id` | 等于当前维度 |
| `task_type` | 等于当前 TaskDesign 的题型 |
| `title` | 非空 |
| `prompt` | 完整、自足的 target-visible 任务内容 |
| `challenge_effort` | 与所属 TaskDesign 一致 |
| `metadata` | 含 `task_design_id`，满足逐设计精确题量 |

公共可选字段为 `content_summary`、`description`、`resource_ids`、`tags`、`scoring`。
正常构题还要求：

~~~json
{
  "metadata": {
    "task_design_id": "...",
    "challenge_effort_self_assessment": {
      "requested_effort": "E3",
      "meets_requested_effort": true,
      "rationale": "具体理由"
    }
  }
}
~~~

多资源 source-backed 题必须在顶层 `resource_ids` 明确绑定实际资源；只写 metadata 不算 provenance。

#### `choice`

~~~json
{
  "choices": [{"id": "A", "text": "..."}, {"id": "B", "text": "..."}],
  "correct_choice_ids": ["A"]
}
~~~

至少两个 id/text 非空且 id 唯一的选项；正确 id 非空且必须存在。一个 id 表示单选，多个 id
表示 exact-set 多选。评分由答案键完成，不应另造 benchmark 级 accuracy 指标。

#### `fill_blank`

~~~json
{"expected_text": "唯一非空字符串"}
~~~

prompt 必须明确精确输出格式。runner 只裁剪首尾空白，再做完全匹配。

#### `generation`

~~~json
{
  "rubric": "具体 Judge 标准",
  "judge_tools": [{"tool": "python_tests", "config": {"test_code": "消费 {model_output}"}}],
  "output_contract": {}
}
~~~

rubric 或等价 scoring guidance 必须具体。Judge tool 可省略；当前只支持 `python_tests`，
且 test code 必须使用 `{model_output}`。工具只提供证据，最终分数仍由 Judge 判定。

#### `multi_turn`

~~~json
{
  "prompt": "第一轮完整 target-visible 内容",
  "system_prompt": "对话模拟器 prompt",
  "interaction": {
    "max_turns": 3,
    "user_turns": ["scripted 后续消息"]
  },
  "rubric": "检查完整 transcript/final answer/state"
}
~~~

`max_turns` 必须为 1-5。scripted 必须给 1-5 条 `user_turns` 并省略 `followup_instruction`；
adaptive 必须给 `followup_instruction` 和任务特定 simulator `system_prompt` 并省略 `user_turns`。
二者必须严格二选一。目标必需信息必须在 `prompt`，不能只放进 simulator system。

#### `agent`

~~~json
{
  "environment": {"type": "workspace/code_sandbox/docker_workspace/gui_desktop"},
  "output_contract": {},
  "rubric": "必要时使用",
  "judge_tools": [],
  "scoring": {
    "method": "...",
    "instructions": "...",
    "pass_criteria": "...",
    "partial_criteria": "...",
    "fail_criteria": "...",
    "score_levels": {},
    "oracle_notes": "..."
  }
}
~~~

必须有可执行、可重置且与 TaskDesign 环境要求一致的 environment，以及 output contract 和确定性
evaluator/checks 或任务特定 rubric。environment 只允许用于 agent。所需输入、fixture、文件、服务、
应用状态、授权路径与评分证据必须真正物化；evaluator 必须检查目标留下的结果，不能代替目标完成任务。
包装阶段会派生 `agent_env`、`task_agent` 和必要时的 `agent_task_package`。

`workspace` 是 room/inventory runtime；`code_sandbox` 用于文件和测试；`docker_workspace`
用于容器包、服务、shell、浏览器和 evaluator；`gui_desktop` 用于桌面/可选 VM。完整环境字段见
[附录 B.4 的环境 references](#appendix-b-task-builder)。

<a id="appendix-d-repair"></a>
### D.4 三种后续输入

结构修复在原 payload 增加：

~~~json
{
  "repair": {
    "reason": "task_structure_validation_failed",
    "attempt": 1,
    "max_repair_attempts": 2,
    "issues": ["全部结构问题"],
    "instruction": "返回完整 replacement JSON；精确保留题数/题型并少改无问题内容",
    "previous_response": {"解析结果或 raw_response_prefix": "..."}
  }
}
~~~

截断恢复增加：

~~~json
{
  "truncation_recovery": {
    "reason": "task_builder_output_truncated",
    "requested_effort_by_task_design": {"design_id": "E3"},
    "reduce_construction_effort": true,
    "instruction": "从头生成更紧凑、完整、可执行、可确定评分的任务"
  }
}
~~~

之后强制 LiteLLM、降低 effort、关闭研究，并标记 challenge-effort fidelity uncertain。

QC 定向重构增加：

~~~json
{
  "revision": {
    "previous_tasks": ["仅失败题的完整旧 JSON"],
    "qc_issues": ["相关 QC issues"],
    "expected_replacement_count": 2,
    "replacement_context": "轮次上下文"
  }
}
~~~

此时 contract 题量分布按旧失败题重算。Builder 只返回这些替换题并保留 ID；通过题不进入输入。
QC repair 不启用构题研究工具。

<a id="appendix-e"></a>
## 附录 E：LLM QC 输入契约

调用只有一条格式化 JSON user message：

<details><summary>附录 E：LLM QC user message 完整 JSON</summary><pre><code class="language-json">{
  &quot;objective&quot;: &quot;...&quot;,
  &quot;scale_budget&quot;: &quot;...&quot;,
  &quot;constraints&quot;: [&quot;...&quot;],
  &quot;planner_notes&quot;: &quot;...&quot;,
  &quot;dimensions&quot;: [&quot;全部 EvalDimension&quot;],
  &quot;task_designs&quot;: [&quot;仅抽样题引用的 TaskDesign&quot;],
  &quot;llm_qc_sampling&quot;: {
    &quot;strategy&quot;: &quot;stratified_by_dimension_and_task_type&quot;,
    &quot;sample_size&quot;: 50,
    &quot;total_items&quot;: 100,
    &quot;groups&quot;: 10
  },
  &quot;items&quot;: [
    {
      &quot;id&quot;: &quot;...&quot;,
      &quot;dimension_id&quot;: &quot;...&quot;,
      &quot;task_type&quot;: &quot;...&quot;,
      &quot;challenge_effort&quot;: &quot;E3&quot;,
      &quot;prompt&quot;: &quot;完整 prompt 或显式首尾 excerpt&quot;,
      &quot;prompt_is_complete&quot;: true,
      &quot;prompt_character_count&quot;: 1234,
      &quot;choices&quot;: [],
      &quot;correct_choice_ids&quot;: [],
      &quot;expected_text&quot;: null,
      &quot;rubric&quot;: &quot;...&quot;,
      &quot;judge_tools&quot;: [],
      &quot;output_contract&quot;: {},
      &quot;source&quot;: {},
      &quot;tags&quot;: [],
      &quot;metadata&quot;: {&quot;压缩后的 metadata&quot;: &quot;...&quot;}
    }
  ]
}
<!-- --></code></pre></details>

普通规模最多 50 题；大规模使用配置值。抽样按 `(batch_id 或 dimension_id, task_type)` 分组轮转，
组内按 id 排序。prompt 单题限额动态位于 1,200-6,000 字符；metadata 字符串限额位于
1,200-12,000。过长 prompt 会带明确 excerpt 标记。环境文件只传数量、名称和最多 4 个 review
excerpts，不会伪装成 canonical 全文；task_agent 和 agent_task_package 使用专门 compact 函数。

QC 模型只返回 issues 和 summary。passed/rejected ids、quality score 和 acceptability 由框架结合静态检查计算。
静态检查本身不调用 LLM，LLM QC 也不直接修改题。

<a id="appendix-f"></a>
## 附录 F：人工审核与重新规划输入契约

### F.1 Dataset review

H1 的单条 user JSON：

<details><summary>F.1 Dataset review user message 完整 JSON</summary><pre><code class="language-json">{
  &quot;objective&quot;: &quot;...&quot;,
  &quot;scale_budget&quot;: &quot;...&quot;,
  &quot;human_feedback&quot;: &quot;用户原文&quot;,
  &quot;dimensions&quot;: [&quot;全部当前 EvalDimension&quot;],
  &quot;dimension_dataset_summaries&quot;: [
    {
      &quot;dimension_id&quot;: &quot;...&quot;,
      &quot;planned_materialized_target&quot;: 3,
      &quot;current_items&quot;: 3,
      &quot;task_counts&quot;: {&quot;generation&quot;: 3},
      &quot;source_counts&quot;: {&quot;self_generated&quot;: 3},
      &quot;target_item_count&quot;: 3,
      &quot;target_source_backed_count&quot;: 0,
      &quot;target_generated_count&quot;: 3
    }
  ],
  &quot;target_counts&quot;: {&quot;dimension_id&quot;: 3},
  &quot;current_counts&quot;: {&quot;dimension_id&quot;: 3},
  &quot;qc_issues&quot;: [&quot;最多 60 条&quot;],
  &quot;items&quot;: [&quot;最多 80 个 item excerpt&quot;]
}
<!-- --></code></pre></details>

item excerpt 包含 id、dimension、type、effort、prompt 前 700 字符、答案字段、rubric 前 500 字符、
Judge tools、output contract、source、tags，以及 compact task_agent、最多 5 turns、agent env type
和 compact science metadata。模型输出 delete/move/update/add/merge/split/needs_more_items actions，
其中 `update_items` 是单题内容改写请求；框架把这些 actions 解析成保留/改写/补题计划（见[正文第六节](#六可选人工审核)），
而不是让模型直接改题——改写题由 TaskBuilder 以定向 revision 落地，未受影响的题原样保留。

### F.2 对缺失题目的定向补规划

对每个还欠量的维度（保留 + 改写后仍不足 `target_item_count`），框架用一个只含该维度的**裁剪 spec** 走一次 `plan_from_spec`（复用同一 Planner Skill），为这个维度设计 TaskDesign，再经 TaskBuilder 构题补齐。它是按维度定向的补建，不是对整个 EvalSpec 的全量重规划：

~~~text
review actions -> 保留未触碰的题 + 按 update_items 定向改写 + 按维度目标补题 -> 合并成 run-ready TaskSuite -> 重新跑 QC
~~~

被剪裁的维度其 Planner instruction 与 F.2 的 `plan_from_spec` 相同（仅 dimensions 列表只含该维度、scale 等于缺失数）。H1 与这些补规划调用是独立请求，不共享消息历史。

这些阶段完成且 QcReport 可接受后，benchmark 才达到本文边界。ExecutionPlan、运行环境探测和目标模型调用
属于之后的执行阶段。

<a id="appendix-g"></a>
## 附录 G：BenchmarkConfig 完整字段表

定义位置：`evalclaw/types.py` 的 `BenchmarkConfig`。当前模型使用 `extra="forbid"`，因此表外字段会被 Pydantic 拒绝。下表覆盖当前全部 69 个字段。

“LLM 可见性”含义：

- **直接**：字段值或由它生成的明确文本会进入某次 LLM 的 `system`/`user`/工具上下文。
- **派生**：字段本身不发送，但会改变抽样、资源、工具、任务或其他模型最终看到的内容。
- **调用参数**：只用于选择模型或连接接口，不属于模型可见消息。
- **否**：仅由 Python 流程、执行器、持久化或 UI 使用。

API key、bridge key、provider key 和 base URL 都不会作为标准 prompt 文本发送。每个角色必须显式配置：planner/task_builder 未配置时流程 fail-closed；qc/research/loop3 未配置时优雅降级或跳过对应功能；`task_models` 为空时，需要模型评分或对话模拟的任务在运行时无法选用模型、对应评分/模拟路径降级为确定性评分或跳过。`task_models` 中每项的任务级凭据（`api_key`/`api_key_env`/`base_url`）仅在该模型被实际调用时使用，不会进入 prompt 文本。

### G.1 模型角色与目标模型（22 个字段）

| 字段 | 类型 | 默认值 | 作用 | LLM 可见性 |
|---|---|---|---|---|
| `planner_model` | `Optional[str]` | `None` | Goal 翻译、BenchmarkPlan 与人工 review 使用的 Planner 模型 | 调用参数 |
| `planner_provider` | `Optional[str]` | `None` | Planner provider | 调用参数 |
| `planner_api_key` | `Optional[str]` | `None` | Planner 凭据；缺失则 Planner 未配置、流程 fail-closed | 调用参数 |
| `planner_base_url` | `Optional[str]` | `None` | Planner API 地址 | 调用参数 |
| `task_builder_model` | `Optional[str]` | `None` | TaskDesign 构题与 QC 定向重构模型 | 调用参数 |
| `task_builder_provider` | `Optional[str]` | `None` | TaskBuilder provider | 调用参数 |
| `task_builder_api_key` | `Optional[str]` | `None` | TaskBuilder 凭据；缺失则 TaskBuilder 未配置、流程 fail-closed | 调用参数 |
| `task_builder_base_url` | `Optional[str]` | `None` | TaskBuilder API 地址 | 调用参数 |
| `qc_model` | `Optional[str]` | `None` | 可选 LLM QC 模型 | 调用参数 |
| `qc_provider` | `Optional[str]` | `None` | QC provider | 调用参数 |
| `qc_api_key` | `Optional[str]` | `None` | QC 凭据；未配置时仍执行静态 QC | 调用参数 |
| `qc_base_url` | `Optional[str]` | `None` | QC API 地址 | 调用参数 |
| `task_models` | `list[TargetModelConfig]` | `[]` | 任务模型池：每题在执行阶段可能用到的辅助模型（LLM 评分 judge、adaptive 多轮对话模拟器）。TaskBuilder 对需模型的任务从该池选一个记入 `metadata.task_model_id` | 派生：列表摘要（id/model/provider）进入 TaskBuilder payload 的 `available_models.models` |
| `research_model` | `Optional[str]` | `None` | Deep Research 的查询、压缩、反思和综合模型 | 调用参数 |
| `research_provider` | `Optional[str]` | `None` | Research provider | 调用参数 |
| `research_api_key` | `Optional[str]` | `None` | Research 凭据 | 调用参数 |
| `research_base_url` | `Optional[str]` | `None` | Research API 地址 | 调用参数 |
| `loop3_model` | `Optional[str]` | `None` | 执行后 Loop 3 诊断模型 | 调用参数 |
| `loop3_provider` | `Optional[str]` | `None` | Loop 3 provider | 调用参数 |
| `loop3_api_key` | `Optional[str]` | `None` | Loop 3 凭据 | 调用参数 |
| `loop3_base_url` | `Optional[str]` | `None` | Loop 3 API 地址 | 调用参数 |
| `targets` | `list[TargetModelConfig]` | `[]` | 待评测目标模型列表；每项含 id/provider/model/凭据等 | 否；仅执行阶段调用，Planner 不接收它 |

`task_models` 每项是 `TargetModelConfig`，凭据字段 `api_key` 与 `base_url` 均可在配置该项时提供（CLI `--task-model` 传 JSON，或 `--task-config` 传完整配置）；`api_key` 也支持 `api_key_env` 指向环境变量，未显式配置时回退对应 provider 的环境变量。TaskBuilder 从 `available_models.models` 选模型时只收到每项的 `id`/`model`/`provider` 摘要，凭据不发往 Build/QC 的模型调用。

### G.2 规划、研究与规模策略（15 个字段）

| 字段 | 类型 | 默认值 | 作用 | LLM 可见性 |
|---|---|---|---|---|
| `scale_budget` | `ScaleBudget` | `mid` | low/mid/high/large/xlarge 规模指导，影响 Planner 与后续采样/改进 | 直接：Planner、人工 review、Loop 3 guidance |
| `max_planner_iterations` | `int` | `5` | Planner 调用、JSON 解析和计划审计的最大尝试次数。如果 planner 的输出超过 `max_planner_iterations` 轮仍不合法则 fail-closed。 | 否 |
| `max_qc_iterations` | `int` | `3` | 全局 QC 定向修复最大轮数 | 否 |
| `max_research_sources` | `int` | `3` | 每个相关范围保留/选择的研究来源上限 | 派生：影响提供给 Planner/Builder 的来源 |
| `max_hf_records_per_dimension` | `int` | `1` | **已废弃**：旧 generator 路径每维度最多导入的 HuggingFace 行数；当前 TaskDesign 构题路径不自动导入，该字段无实际作用 | 派生；保留仅为向后兼容 |
| `large_scale_generated_item_cap_per_dimension` | `int` | `50` | 大规模模式每维度 self-generated 题量上限 | 派生 |
| `source_backed_ratio` | `Optional[float]` | `None` | 全规模 source-backed 题量比例；显式设置时传给 Planner 作为约束，未设置时 LLM 看不到 | 直接：Planner constraints（仅显式设置时） |
| `challenge_effort_distribution` | `dict[str, float]` | `{}` | 全局 E1/E2/E3 题量比例，如 `{"E1": 0.2, "E2": 0.3, "E3": 0.5}`；各档比例和为 1 时作为硬约束传给 Planner，审计校验每档偏差 ≤1 题；为空时 Planner 自由决定各 TaskDesign 档位 | 直接：Planner constraints（非空时） |
| `large_scale_llm_qc_sample_size` | `int` | `120` | large/xlarge LLM QC 分层抽样基数 | 派生：改变 QC 模型收到的 items |
| `use_web_research` | `bool` | `True` | 是否允许构题前搜索和 TaskBuilder web tools | 派生：决定来源与工具是否可用 |
| `search_backend` | `str` | `"auto"` | `auto/gemini/keyless/none` 搜索后端 | 否；搜索结果可能进入模型上下文 |
| `use_deep_research` | `bool` | `False` | 是否在 Planner 前运行 Deep Research | 派生：决定是否产生 ResearchBrief |
| `max_research_iterations` | `int` | `3` | Deep Research 最大轮数 | 直接：R3 的 `max_rounds` |
| `research_brief` | `Optional[ResearchBrief]` | `None` | 预置或本次生成的研究结果与保留正文 | 直接但压缩：Planner/Builder 只收 compact brief；Builder 可按 URL 读保留正文 |
| `use_hf_discovery` | `bool` | `True` | Deep Research/来源阶段是否发现 HuggingFace 数据集候选 | 派生 |

### G.3 构题、QC 与模型调用控制（7 个字段）

| 字段 | 类型 | 默认值 | 作用 | LLM 可见性 |
|---|---|---|---|---|
| `task_builder_max_workers` | `int` | `4` | 可并发执行的 TaskDesign Builder job 数 | 否 |
| `task_builder_repair_attempts` | `int` | `2` | 每个 Builder job 在全局 QC 前的结构修复次数 | 直接：修复 payload 的 `max_repair_attempts` |
| `task_builder_research_max_calls` | `int` | `6` | 单次 Builder 构题研究工具调用预算，运行时限制为 1-12 | 直接：`interactive_research.max_tool_calls` |
| `task_builder_research_max_chars` | `int` | `50_000` | 每次构题研究工具结果的最大字符数，运行时限制为 1,000-100,000 | 派生：限制工具结果正文 |
| `judge_double_pass` | `bool` | `True` | 执行阶段 Judge 是否进行双遍审计 | 派生：决定 Judge 调用次数和第二遍输入 |
| `llm_backend` | `str` | `"auto"` | `auto/litellm/legacy` 模型调用实现 | 调用参数 |
| `allow_incomplete_benchmark` | `bool` | `False` | QC 仍有阻塞问题时是否允许保留不完整草稿 | 否 |

### G.4 流程、输出、人工审核与 Loop 3（13 个字段）

| 字段 | 类型 | 默认值 | 作用 | LLM 可见性 |
|---|---|---|---|---|
| `output_dir` | `str` | `"./benchmark-output"` | JSON、报告、viewer、调试目录等输出根目录 | 否 |
| `task_builder_debug_dir` | `Optional[str]` | `None` | TaskBuilder 请求、响应和修复调试记录目录 | 否 |
| `run_targets` | `bool` | `True` | benchmark/QC 完成后是否实际调用 targets | 否 |
| `runner` | `str` | `"direct"` | `direct/lm-eval/auto` 执行与导出路径 | 否 |
| `environment_claw` | `bool` | `True` | 是否运行环境能力探测与准备 | 否 |
| `environment_claw_auto_configure` | `bool` | `True` | 是否根据探测结果自动补全可恢复的环境配置 | 否 |
| `human_review` | `bool` | `False` | 是否在执行前进入人工审核循环 | 否；人工反馈文本本身会发送给 Planner |
| `improve_iterations` | `int` | `0` | 目标模型执行后 Loop 3 改进轮数 | 否 |
| `loop3_diagnosis` | `str` | `"llm"` | `llm/local` Loop 3 诊断方式 | 否 |
| `loop3_diagnosis_timeout_s` | `int` | `90` | Loop 3 LLM 诊断等待超时 | 否 |
| `loop3_max_actions` | `int` | `4` | 每轮改进 action 上限；会按 scale budget 调整 | 派生：限制采用的模型输出 actions |
| `viewer_item_limit` | `int` | `1000` | viewer payload 最多嵌入的 benchmark items | 否 |
| `viewer_result_limit` | `int` | `2000` | viewer payload 最多嵌入的执行结果 | 否 |

### G.5 Docker、GUI 与 VM 运行时（12 个字段）

| 字段 | 类型 | 默认值 | 作用 | LLM 可见性 |
|---|---|---|---|---|
| `docker_auto_select_image` | `bool` | `True` | 是否为 docker workspace 自动选择/构建镜像 | 否 |
| `docker_pull_timeout_s` | `int` | `300` | Docker 拉取镜像超时 | 否 |
| `docker_executable` | `str` | `"docker"` | Docker CLI 可执行文件名或路径 | 否 |
| `container_sandbox_image` | `str` | `"python:3.11-slim"` | 通用容器沙箱默认镜像 | 否 |
| `environment_preflight` | `bool` | `True` | 运行 targets 前是否做环境预检 | 否 |
| `gui_bridge_url` | `Optional[str]` | `None` | GUI/desktop bridge 地址 | 否；只注入运行时环境配置 |
| `gui_bridge_api_key` | `Optional[str]` | `None` | GUI bridge 凭据 | 否；秘密字段 |
| `gui_bridge_timeout_s` | `int` | `30` | GUI bridge 调用超时 | 否 |
| `vm_provider_url` | `Optional[str]` | `None` | VM provider 地址；需要 VM 时可回退 `local://auto` | 否；只注入运行时环境配置 |
| `vm_provider_api_key` | `Optional[str]` | `None` | VM provider 凭据 | 否；秘密字段 |
| `vm_provider_timeout_s` | `int` | `600` | VM provider 创建/操作超时 | 否 |
| `vm_provider_destroy_on_cleanup` | `bool` | `True` | 清理阶段是否销毁临时 VM | 否 |

`TargetModelConfig` 和 `ResearchBrief` 是嵌套模型，不在 69 个顶层字段计数中；后者的完整结构见
[附录 H](#appendix-h)。新增或删除 `BenchmarkConfig` 字段时，应同时更新本附录的
分组计数和字段行。

<a id="appendix-h"></a>
## 附录 H：ResearchBrief 完整数据契约

ResearchBrief 是 **Benchmark Design Research** 的中间产物，不是通用领域研究报告。它只保留
会改变当前 benchmark 维度、难点、任务/评分、来源选择或构题投入判断的内容；领域综述、学术
新颖性、市场背景和与构题无关的 benchmark gap 不属于这个对象。

定义位置：`evalclaw/types.py` 的 `ResearchBrief` 及其六个嵌套模型；R4 解析位于
`evalclaw/research/deep_research.py::_parse_brief()`。当前对象有 9 个顶层字段：
`dimensions`、`difficulty_factors`、`task_patterns`、`source_recommendations`、`evidence`、
`challenge_effort_anchors`、`source_materials`、`research_notes` 和 `created_at`。

### H.1 字段所有权与生成顺序

```text
R1-R3 累计 evidence 和抓取正文
    -> R4 综合 7 个设计字段
    -> _parse_brief() 规范化 R4 JSON
    -> 框架覆盖写入 source_materials
    -> created_at 使用模型默认值
    -> 最终 ResearchBrief
```

R4 返回 `dimensions`、`difficulty_factors`、`task_patterns`、`source_recommendations`、
`evidence`、`challenge_effort_anchors` 和 `research_notes`。`source_materials` 始终由框架依据
真实抓取过程写入，防止综合模型伪造来源正文；R4 只能引用 `known_sources` 中的 URL。

### H.2 最终完整 JSON 结构

下面展示的是持久化结构；示例值不是额外默认内容。

```json
{
  "dimensions": [
    {
      "name": "可测量的能力维度",
      "measurement_target": "要观察的能力",
      "boundary": "纳入与排除范围",
      "task_shapes": ["适合的任务形态"]
    }
  ],
  "difficulty_factors": [
    {
      "factor": "可观察的困难因素",
      "observable_signal": "题目或输出中的信号",
      "design_implication": "如何把它设计成可测任务"
    }
  ],
  "task_patterns": [
    {
      "name": "任务模式",
      "description": "任务测量的内容",
      "suitable_task_types": ["choice"],
      "scoring_direction": "评分应关注什么"
    }
  ],
  "source_recommendations": [
    {
      "title": "可用于 source-backed 构题的来源",
      "url": "https://example.com/source",
      "why_useful": "为什么有助于当前目标的构题"
    }
  ],
  "evidence": [
    {
      "observation": "外部来源中的观察",
      "design_implication": "对当前 benchmark 设计的直接影响",
      "source_urls": ["https://example.com/source"]
    }
  ],
  "challenge_effort_anchors": {
    "E1": "简单直接的构题投入",
    "E2": "需要边界情况和验证的构题投入",
    "E3": "需要高投入材料、环境或多步验证的构题投入"
  },
  "source_materials": [
    {
      "title": "抓取来源标题",
      "url": "https://example.com/evidence",
      "query": "发现该来源的搜索查询",
      "content": "实际抓取并保留的可读正文"
    }
  ],
  "research_notes": "局限、开放问题和覆盖说明",
  "created_at": "ISO-8601 UTC 时间"
}
```

### H.3 顶层字段要求

所有顶层字段都有默认值，因此部分 brief 可以通过模型验证；“必填”主要发生在已提供的嵌套对象内部。

| 字段 | 类型 | 默认值 | 生产者与约束 |
|---|---|---|---|
| `dimensions` | `list[ResearchDimension]` | `[]` | R4；当前目标下有证据支持的可测量候选维度 |
| `difficulty_factors` | `list[ResearchDifficultyFactor]` | `[]` | R4；困难因素必须对应可观察信号和构题影响 |
| `task_patterns` | `list[ResearchTaskPattern]` | `[]` | R4；任务形态、适用题型和评分方向 |
| `source_recommendations` | `list[ResearchSourceRecommendation]` | `[]` | R4；URL 必须出现在 `known_sources` 中 |
| `evidence` | `list[ResearchEvidence]` | `[]` | R4；外部观察、直接设计影响和来源 URL |
| `challenge_effort_anchors` | `dict[ChallengeEffort, str]` | `{}` | R4；描述当前目标的 E1/E2/E3 构题投入 |
| `source_materials` | `list[ResearchSourceMaterial]` | `[]` | 框架；按 URL 去重，同 URL 保留正文更长的版本 |
| `research_notes` | `str` | `""` | R4；记录局限、开放问题和覆盖范围 |
| `created_at` | `str` | 当前 UTC 时间 | Pydantic 默认工厂；ISO-8601 字符串 |

### H.4 嵌套对象要求

| 模型 | 必填字段 | 有默认值的字段 |
|---|---|---|
| `ResearchDimension` | `name: str` | `measurement_target=""`、`boundary=""`、`task_shapes=[]` |
| `ResearchDifficultyFactor` | `factor: str` | `observable_signal=""`、`design_implication=""` |
| `ResearchTaskPattern` | `name: str` | `description=""`、`suitable_task_types=[]`、`scoring_direction=""` |
| `ResearchSourceRecommendation` | `title: str`、`url: str` | `why_useful=""` |
| `ResearchEvidence` | `observation: str`、`design_implication: str` | `source_urls=[]` |
| `ResearchSourceMaterial` | `url: str`、`content: str` | `title=""`、`query=""` |

模型层本身没有验证 URL 必须可访问，也没有在 `ResearchSourceMaterial.content` 上声明字符数约束；
来源真实性和每个来源最多保留约 50,000 字符由抓取流程负责。

### H.5 R4 解析边界

R4 必须返回当前 schema 的 JSON 对象。`_parse_brief()` 只做类型规范化、丢弃缺少核心字段的
条目，以及过滤不在 `known_sources` 中的 URL；不会把旧字段映射回新字段，也不会接受未声明的
嵌套字段。ResearchBrief 及其嵌套模型使用 `extra="forbid"`，契约外字段会被拒绝。

### H.6 下游可见范围

完整 `ResearchBrief` 会写入 `research_brief.json`。Planner 不接收完整对象，而只接收
`compact_brief_context()`：最多 12 个候选维度、困难因素和任务模式，10 个来源建议，30 条设计
evidence，来源的 title/URL/content 字符数索引，以及最多 4 个 E1-E3 anchors；不包含
`source_materials[].content` 正文。

TaskBuilder payload 同样携带 compact brief。需要来源细节时，TaskBuilder 可调用
`read_research_source(url)` 从本次完整 brief 中读取对应正文；因此“正文被保留”和“正文直接塞进
Planner/TaskBuilder 首轮 prompt”是两件不同的事。

<a id="appendix-i"></a>
## 附录 I：数据模型字段与 QC 检查清单

定义位置均为 `evalclaw/types.py` 与 `evalclaw/quality/`。本附录汇集正文中「完整字段见附录 I」所引用的契约。

### I.1 TaskResource 字段

标准化后的构题来源：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `id` | `str` | 必填 | 稳定资源 ID，被题目的 `resource_ids` 引用 |
| `kind` | `str` | `"web"` | 资源种类，可选值：`web`（网页）、`hf_dataset`（HuggingFace数据集）、`lm_eval`（lm-eval任务）、`self_generated`（框架自生成）、`imported`（导入） |
| `uri` | `str` | `""` | 可解析地址或标识 |
| `title` | `str` | `""` | 标题；若资源本身无明确标题，框架会回退使用 `resource.id` 或从 `uri` 派生的描述性标识（见 `pack_task_item` 与 suite 资源汇总） |
| `license` | `str` | `""` | 许可信息；该字段不呈现给 TaskBuilder LLM，仅用于数据集元数据记录与合规追踪（见 `evalclaw/construction/suite.py` payload 组装，license 未包含在 resources.context 中） |
| `content_summary` | `str` | `""` | 内容摘要；包含对资源内容的简要描述，TaskBuilder 可见此字段作为来源上下文 |
| `metadata` | `dict` | `{}` | 附加信息 |

### I.2 TaskSuite 字段

run-ready 的正式任务容器，贯穿 QC、执行、报告。定义在 `evalclaw/types.py`：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `id` | `str` | `"task_suite"` | 套件 ID |
| `objective` | `str` | 必填 | 目标 |
| `spec` | `EvalSpec` | 必填 | 总体测评规格（构题时按实际物化题型归一化 `task_types`） |
| `dimensions` | `list[EvalDimension]` | `[]` | 维度列表 |
| `blueprints` | `list[TaskBlueprint]` | `[]` | Builder job；`builder_jobs` 属性是其别名 |
| `resources` | `list[TaskResource]` | `[]` | 去重规范化后的资源 |
| `tasks` | `list[BenchmarkItem]` | `[]` | 全部 run-ready 题目 |
| `plan` | `Optional[BenchmarkPlan]` | `None` | Planner 完整计划；`exclude=True`，不写入序列化 JSON |
| `construction_notes` | `str` | `""` | 汇总的构造备注 |
| `created_at` | `str` | 当前 UTC | 时间戳；用于追踪构题时间、数据集版本管理与审计日志，不影响题目执行或评分逻辑 |

### I.3 `to_eval_spec()` 的派生字段

`BenchmarkPlan.to_eval_spec()` 逐维度汇总出 `EvalDimension`：`id`/`name`/`measurement_target`/`boundary`/`approach` 直接来自对应 `BenchmarkPlanDimension`；`challenge_effort` 取该维度题量加权后最高的 effort；`needs_research` 由 `source_plan.search_queries` 非空或 source-backed 题量 > 0 推导；`target_item_count` = 该维度 `task_count` 之和；`target_source_backed_count` 为 `source_plan.strategy` 属 source_backed/imported_dataset/mixed 的题量；`target_generated_count` = 总数减 source-backed 数；`task_types`/`task_type_allocation` 由各 TaskDesign 聚合；`challenge_effort_distribution` 是各 effort 题量占比。spec 级 `scale` = 全 plan 的 `task_count` 之和，`task_types` 去重、`constraints`/`planner_notes` 直接透传。

### I.4 单题静态 QC 检查清单

`_static_item_issues` 逐题、不调用 LLM，主要检查：

- **基础**：`prompt` 非空（error）、不过短（<20 字符 warning）。
- **choice**：至少两个选项（error）；选项 id 唯一非空（error）；有 `correct_choice_ids` 且指向存在的选项（error）；选项文本去规范化后无重复（error）；rubric 里若出现显式答案键，须与 `correct_choice_ids` 一致（error）。
- **fill_blank**：`expected_text` 非空（error）。
- **generation / multi_turn**：有 rubric（error）。
- **judge_tools**：只允许 `python_tests`（error）；仅 generation/multi-turn/agent 可用（error）；`test_code` 必须消费 `{model_output}`（error）。
- **agent**：无 rubric 时必须有可执行环境 evaluator（error）；`metadata.agent_env` 必须存在（error）；环境文件路径无跨生命周期重叠（error）；`setup_commands` 不引用 hidden_files（error）；workspace/code_sandbox/gui_desktop 各有必填契约。
- **多模态**：`metadata.multimodal` 的 schema_version、modalities、assets、content 引用完整。多模态题目由 TaskBuilder 在构题时显式标记：当题目需要图像、音频等非纯文本模态时，TaskBuilder 在返回的题目中填充 `metadata.multimodal` 字段（schema_version=evalclaw.multimodal.v1、modalities列表、assets列表、可选content引用），QC 静态检查会校验该字段的完整性（见 `evalclaw/quality/static_checks.py` 和 `evalclaw/protocols/multimodal.py`）。五个基础题型（choice/fill_blank/generation/multi_turn/agent）均可携带多模态标记，题型本身不限制模态。
- **science / task_agent / agent_task_package**：schema_version、system_prompt、scoring guidance 等 metadata 契约。
- **rubric 自纠正**：检测 rubric 中自纠正/矛盾参考答案（error）。

### I.5 数据集级 QC 检查清单

`_duplicate_issues` / `_coverage_issues`，同样不调用 LLM：

- **重复**：重复 item id（error）；完全重复 prompt（error）；相似度 `SequenceMatcher >= 0.92` 且 token 重叠 `>= 0.78` 的近似重复（warning，近重复只在 high/large/xlarge 限额内检查）。
- **覆盖**：题目引用未知 dimension（error）；某 dimension 无任何题（error）；high/large/xlarge 下某维度仅 1 题（warning）；source-backed 题量未达计划（warning）；计划题型无对应题（warning）。

### I.6 QcReport 与 QcIssue 字段

`QcReport`：`issues: list[QcIssue]`、`passed_item_ids: list[str]`、`rejected_item_ids: list[str]`、`quality_score: float`、`summary: str`。`is_acceptable` 属性 = 无 error issue 且 `rejected_item_ids` 为空。

`QcIssue`：`item_id: Optional[str]`（空表示数据集级问题）、`severity: info|warning|error`、`category: schema|duplicate|scoring|clarity|coverage|challenge_effort`、`message`、`suggested_action`。

### I.7 构题阶段单题结构检查（`task_structure_issues`）

TaskBuilder 返回后、进入全局 QC 之前，系统对每题跑一遍「结构检查」（`evalclaw/construction/validation.py::task_structure_issues`），产出 `task_structure_issues: list[str]` 并写入 `metadata.task_structure_validation`（`schema_version` / `status: passed|failed` / `issues`）。它刻意窄于内容 QC：**不评判质量**，只校验「这道题按其题型与可选执行能力是否具备可执行所需的字段」。出现任何 issue 时，把结构错误与上次返回一并交回 TaskBuilder 修复。

基础字段：
- `id`、`title`、`prompt` 非空；`prompt` 不以截断/不完整指令结尾。
- 提供 `dimension` 时 `dimension_id` 必须匹配；提供 `task_design`/`dimension` 的期望 `challenge_effort` 时，任务必须一致。
- 元数据里任何名字含 `evaluator`/`evaluation`/`validation` 的字段不得声明 runner 可执行求值器——普通 metadata 不可执行，完整求值器必须放进被选中 runtime 的规范环境求值字段。
- 对 LLM 构题（`require_challenge_effort_self_assessment`）：必须有 `metadata.challenge_effort_self_assessment`，`requested_effort` 匹配期望档、`meets_requested_effort=true`（除非 `challenge_effort_fidelity.uncertain` + `reduced_effort_litellm_retry`）、`rationale` 解释自评。

按题型的字段契约：
- `choice`：至少两个非空且互异的 choice；至少一个 `correct_choice_id` 且引用已有的 choice id。
- `fill_blank`：非空 `expected_text`。
- `generation`/`multi_turn`：必须提供 judge rubric 或评分指引。
- `judge_tools`：仅 `python_tests` 被注册；仅对 generation/multi_turn/agent 合法；`python_tests` 必须有非空 `config.test_code` 且其代码消费 `{model_output}`。
- `agent`：必须提供可执行 `environment`。
- `multi_turn`：`interaction.max_turns` 在 1–5；`user_turns`（1–5 个非空串）与 `followup_instruction` 恰选其一；`followup_mode=adaptive` 时须 `omit user_turns`、给 `followup_instruction` 和模拟器 `system_prompt`；`scripted` 时反之。

环境契约（有 `blueprint` 时其 `environment_type` 是权威；任务环境类型必须匹配，且只有 agent 任务可携带可执行环境）：
- 通用：`artifact_requirement` ∈ {all, any, exactly_one}；`max_steps`、`timeout` 为正；`environment.tools` 不定义自定义可执行行为；`visible_files`/`runtime_files`/`hidden_files` 彼此无路径冲突，每个文件只属一个阶段；`setup_commands` 不得引用 `/tmp/hidden_files` 或 evaluator 私有 `hidden_files`。
- `code_sandbox`：必须有确定性的 `test_command`。
- `docker_workspace`：必须有确定性的 `test_command`；TaskDesign 要求 browser 动作时 `browser.enabled=true` 且必须是实际含 Playwright 与浏览器的 runtime；`browser.runtime=playwright_python`、有 `start_url`、非空 `allowed_origins`；`executable_path` 必须是精确 guest 路径而非通配符；prompt 不得命名 `final_answer` 工具；有文件产物时经 `workspace_tools` 暴露 `write_file` 且产物落在 `workdir` 内。
- `gui_desktop`：必须有 `environment.session`（application/kind/applications 之一 + launch/start 状态之一）与可执行求值（`environment.evaluation`，不是 `session.evaluation_checks`）；`requires_vm=true` 时需 runner 可解析的 template/image/disk 标识、或 guest OS + 非空 `required_capabilities`，`baseline_checks`、provisioning、PowerShell 语法与身份、protected-evaluator 引用等走专项检查子程序。
- `workspace`：必须有非空 `workspace.rooms`（对象映射 room 名→item-id 数组，含 `mailroom`）与非空 `workspace.goal.outgoing_bin`（且每个 goal item 都存在于某 room）；不得混入文件/shell/browser/VM 能力。

结果以 `metadata.task_structure_validation.status` 落库，供下游 QC 读取：`passed` 仅表示通过低层 shape/runner 契约校验，**绝不**证明 Planner 需求、初始状态、工具或求值语义完整（见 B.5 QC 中对 status=passed 的说明）。

### I.8 打包阶段单题处理详情（`pack_task_item`）

`pack_task_item`（`evalclaw/construction/packaging.py`）由 `build_task_suite` 在合并每个 Builder job 产物时对每个 `TaskDefinition` 调用，不调用任何模型，是纯代码转换：

1. **结构校验**：调用 `task_structure_issues`（校验条目见[附录 I.7](#appendix-i)），结果写入 `metadata.task_structure_validation`（字段见附录 I.7 末段）。这里需要 `blueprint`/`task_design` 提供期望的 `challenge_effort`/`environment_type` 上下文，由 `build_task_suite` 从 `item.metadata.builder_job_id`/`task_design_id` 反查传入。
2. **关联 Builder job 与 TaskDesign**：从 `metadata.builder_job_id` 反查 `suite.builder_jobs` 中的对应 job，再从 `metadata.task_design_id` 反查该 job 下的具体 `TaskDesign`（见第 1 步，用于结构校验上下文）。
3. **生成内容摘要**：调用 `compact_task_content_summary`（`evalclaw/core/task_summary.py`），不调用模型。按顺序取第一个非空候选——`task.content_summary` → 已有的 `metadata.task_content_summary` → `task.title` → `task.description` → `task.prompt`——截取前 8 个词并做去下划线、首字母大写等归一化，写入 `metadata.task_content_summary`，供报告展示用。
4. **归一化 rubric**：优先 `task.rubric`；否则 `task.scoring.instructions`；再否则拼接 `pass_criteria`/`partial_criteria`/`fail_criteria` 三段文本。
5. **生成 `task_agent` metadata**（`_task_agent_metadata_for_task`，不调用模型）：仅当题目是 `multi_turn` 或带 `environment` 时执行。内容包括 `agent_role`（multi_turn 为 `dialogue_simulator`，其余为 `target_agent_executor`）、`system_prompt`（沿用 `task.system_prompt` 或按角色给默认值）、`initial_content`（汇总环境的可见文件/session/vm/browser 等公开信息）、归一化后的 `scoring`（含按 partial 文本推断出的 `levels` 0/0.5/1 映射）。
6. **生成 `agent_env` 与 `agent_task_package`**（仅带 `environment` 的题目，不调用模型）：`_environment_for_runner` 把 `TaskDefinition.environment` 按环境类型（workspace/code_sandbox/docker_workspace/gui_desktop）铺开成 runner 可直接消费的字典，补默认值（如 workspace 缺 `rooms` 时补一个最小房间布局，`code_sandbox` 缺 `test_command` 时补 `python3 tests.py`）；`_agent_task_package_for_task` 在此基础上组装完整的 `agent_task_package`（能力目标、环境需求、可见输入、隐藏引用、输出契约、执行/求值/产物采集/轨迹要求、来源溯源），若 Builder 已给出同 schema 版本的旧值则做字段级合并而非整体覆盖。
7. **构造 `BenchmarkSource`**：优先从 `agent_task_package.resource_provenance` 取来源类型与 URI；若无则退回 `task.resource_ids` 指向的 `TaskResource`；两者都没有则标记为 `self_generated`。
8. **组装 `BenchmarkItem`**：字段为 `id`、`dimension_id`、`task_type`、`prompt`、`choices`、`correct_choice_ids`、`expected_text`、`rubric`（第 4 步结果）、`judge_tools`、`output_contract`、`challenge_effort`、`source`（第 7 步结果）、`tags`、`metadata`（含前述步骤写入的所有字段），并保留原始 `TaskDefinition` 到 `source_definition`（`exclude=True`，不写入 JSON）供 QC repair 取回传给 TaskBuilder。`build_task_suite` 最终把它加入 `TaskSuite.tasks`。

### I.9 BenchmarkItem 字段

run-ready 的单题格式，定义在 `evalclaw/types.py`：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `id` | `str` | 必填 | 稳定题目 ID |
| `dimension_id` | `str` | 必填 | 所属维度 |
| `task_type` | `TaskType` | 必填 | 题型：choice/fill_blank/generation/multi_turn/agent |
| `prompt` | `str` | 必填 | 题目文本 |
| `choices` | `list[ChoiceOption]` | `[]` | choice 选项 |
| `correct_choice_ids` | `list[str]` | `[]` | choice 正确选项 id |
| `expected_text` | `Optional[str]` | `None` | fill_blank 答案 |
| `rubric` | `Optional[str]` | `None` | 评分 rubric（打包时由 `scoring` 归一化） |
| `judge_tools` | `list[JudgeToolRef]` | `[]` | 需要的 judge 工具 |
| `output_contract` | `dict` | `{}` | 输出契约 |
| `challenge_effort` | `ChallengeEffort` | `E2` | 构题档位 |
| `source` | `BenchmarkSource` | self_generated | 来源 provenance |
| `tags` | `list[str]` | `[]` | 标签 |
| `metadata` | `dict` | `{}` | 含 `task_content_summary`、`task_structure_validation`、`task_agent`、`agent_env`、`agent_task_package` 等打包期写入字段 |
| `source_definition` | `Optional[TaskDefinition]` | `None` | 打包前的原始 `TaskDefinition`；`exclude=True`，不写入 JSON，仅供内存中 QC repair 取回 |

`metadata.builder_job_id` / `metadata.task_design_id` 记录题目所属 Builder job 与 TaskDesign；`item.builder_job_id` / `item.task_design_id` 是读取它们的便捷属性。

