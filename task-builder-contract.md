# TaskBuilder 任务字段契约（超集）

TaskBuilder 的职责：根据 planner 给的 TaskDesign，生成任务对象（`TaskDefinition`），框架再打包成 `BenchmarkItem` 交给 Runner 执行。本文列出**所有任务类型字段的并集**（最通用的超集），以及每个字段的类型、语义、适用任务类型、必填性。

## 1. 输出结构总览

```
tasks[]（每个元素是一个 task 对象，框架打包成 BenchmarkItem）
├── task_type / title / prompt / challenge_effort / metadata   # 公共必填
├── content_summary / description / assets / tags               # 公共可选
├── resource_ids                                                # 仅 source-backed
├── [choice]     choices / correct_choice_indices
├── [fill_blank] expected_texts
├── [generation] rubric / judge_tools / output_contract / scoring
├── [multi_turn] system_prompt / interaction / rubric / judge_tools / scoring
└── [agent]      system_prompt / interaction / environment / workflow
                 / output_contract / rubric / judge_tools / scoring
```

`[type]` 标记该组字段只属于对应任务类型；`resource_ids` 仅 `adapted`/`reused`/`imported_dataset` 任务。`choices`、`judge_tools`、`scoring`、`environment`、`workflow` 内部还有子结构（见 §4）。

## 2. 任务类型（TaskType）

| 值 | 含义 |
|---|---|
| `choice` | 选择题（单选/多选） |
| `fill_blank` | 填空题 |
| `generation` | 生成题 |
| `multi_turn` | 多轮交互题 |
| `agent` | agent / 环境操作题 |

## 3. 字段超集

### 3.1 公共字段（所有任务类型）

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `task_type` | `TaskType` | 是 | 任务类型，决定框架用哪套评分/执行逻辑 |
| `title` | `str` | 是 | 任务标题 |
| `prompt` | `str` | 是 | 发给被评测模型的完整任务提示 |
| `challenge_effort` | `ChallengeEffort` | 是 | 难度档位：`E1` / `E2` / `E3` |
| `metadata` | `dict` | 是 | 附加元数据（`task_design_id`、`task_model_id` 等） |
| `content_summary` | `str` | 否 | 任务内容摘要（默认空串） |
| `description` | `str` | 否 | 详细描述（默认空串） |
| `assets` | `list[TaskAsset]` | 否 | 附加资源文件（`TaskAsset.path`） |
| `tags` | `list[str]` | 否 | 标签 |

### 3.2 框架注入字段（Builder 不写，由框架生成）

| 字段 | 来源 |
|---|---|
| `id` | 框架生成的任务 id |
| `dimension_id` | 所属维度 id |
| `metadata.task_design_id` | 关联的 TaskDesign id |

### 3.3 选择题 `choice` 专属

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `choices` | `list[ChoiceOption]` | 是 | 至少两个选项，每项只有 `text`（`id` 由框架规范化） |
| `correct_choice_indices` | `list[int]` | 是 | 零基位置；单个=单选，多个=多选。框架转成 `correct_choice_ids`（canonical id） |

### 3.4 填空题 `fill_blank` 专属

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `expected_texts` | `list[str]` | 是 | 可接受答案列表；任一命中即正确（精确匹配，忽略首尾空白） |

### 3.5 生成题 `generation` 专属

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `rubric` | `str` | 是 | 具体评分标准 |
| `judge_tools` | `list[JudgeToolRef]` | 否 | 可请求的外部验证（如 `python_tests`），结果作为证据，不直接给分 |
| `output_contract` | `dict` | 否 | 声明期望的输出结构 |
| `scoring` | `TaskScoringSpec` | 否 | 评分规格 |

### 3.6 多轮交互 `multi_turn` 专属

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `system_prompt` | `str` | 仅 adaptive | 对话模拟器的 prompt（与任务 prompt 分离） |
| `interaction` | `dict` | 是 | `max_turns`（1–5）+ 追问方式（见下） |
| `rubric` / `judge_tools` / `scoring` | — | rubric 是；其余否 | 同生成题 |

`interaction` 的追问方式二选一：
- **scripted**：`interaction.user_turns`（1–5 个非空字符串）。
- **adaptive**：`interaction.followup_instruction`（按模型响应条件追问）。

### 3.7 agent / 环境题 `agent` 专属

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `environment` | `AgentEnvironmentSpec` | 是 | 可执行环境定义（见 §4.4） |
| `workflow` | `AgentWorkflow` | 否（仅多阶段） | 多阶段工作流（见 §4.5） |
| `system_prompt` / `interaction` | — | 否 | 同多轮 |
| `output_contract` / `rubric` / `judge_tools` / `scoring` | — | 否 | 同生成题 |

## 4. 子结构

### 4.1 ChoiceOption

| 字段 | 类型 | 必填 |
|---|---|---|
| `id` | `str` | 否（框架规范化） |
| `text` | `str` | 是 |

### 4.2 JudgeToolRef

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tool` | `str` | 是 | 工具名（当前支持 `python_tests`） |
| `config` | `dict` | 是（`python_tests` 需 `config.test_code`） | 工具配置 |

### 4.3 TaskScoringSpec

| 字段 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `method` | `str` | 否 | `"deterministic"` |
| `instructions` | `str` | 否 | `""` |
| `pass_criteria` | `str` | 否 | `""` |
| `partial_criteria` | `str` | 否 | `""` |
| `fail_criteria` | `str` | 否 | `""` |
| `allows_partial_credit` | `bool` | 否 | `false` |
| `score_levels` | `dict[str,str]` | 否 | `{}` |

### 4.4 AgentEnvironmentSpec（environment 字段）

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `type` | `docker_workspace` \| `vm` | 是 | `docker_workspace` | 环境类别 |
| `visible_files` | `dict[str,str]` | 否 | `{}` | 解题前可见的文件（path→内容） |
| `runtime_files` | `dict[str,str]` | 否 | `{}` | 运行时文件 |
| `hidden_files` | `dict[str,str]` | 否 | `{}` | 评分用的隐藏文件（如测试） |
| `image` | `str` | 否 | `""` | Docker 镜像（空则自动选） |
| `auto_select_image` | `bool` | 否 | `true` | 是否按任务文本自动选镜像 |
| `image_selection` | `dict` | 否 | `{}` | 镜像选择元数据 |
| `image_build` | `dict` | 否 | `{}` | 镜像构建定义（`context_dir`/`base_image`/`dockerfile_name` 等） |
| `pull_image` | `bool` | 否 | `true` | 是否拉取镜像 |
| `pull_timeout` | `int` | 否 | `300` | 拉取超时（秒） |
| `setup_commands` | `list[str]` | 否 | `[]` | 环境初始化命令 |
| `test_command` | `str` | 否 | `""` | 评分测试命令（默认 `pytest -q`） |
| `max_steps` | `int` | 否 | `8` | 最大交互步数 |
| `timeout` | `int` | 否 | `20` | 单步超时 |
| `network` | `str` | 否 | `"none"` | 容器网络策略 |
| `resource_limits` | `dict` | 否 | `{}` | 资源限制 |
| `workdir` | `str` | 否 | `"/workspace"` | 容器内工作目录 |
| `browser` | `dict` | 否 | `{}` | 浏览器工具约束 |
| `bridge_url` | `str` | 否 | `""` | GUI 桥接地址（vm 用） |
| `bridge_api_key` | `str?` | 否 | `null` | 桥接鉴权 |
| `requires_vm` | `bool` | 否 | `false` | 是否需要 VM |
| `vm_provider_url` | `str` | 否 | `""` | VM provider 地址 |
| `vm_provider_api_key` | `str?` | 否 | `null` | VM provider 鉴权 |
| `vm` / `vm_materialization` / `vm_provisioning` | `dict` | 否 | `{}` | VM 相关定义 |
| `session` | `dict` | 否 | `{}` | 会话定义 |
| `evaluation` | `dict` | 否 | `{}` | 评估定义 |
| `notes` | `str` | 否 | `""` | 备注 |

### 4.5 AgentWorkflow / WorkflowStage / WorkflowMetric

`AgentWorkflow`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `stages` | `list[WorkflowStage]` | 是 | 阶段列表（≥1，id 唯一） |
| `score_stage` | `str` | 是 | 指到某个 `evaluate` 阶段 |
| `metrics` | `dict[str,WorkflowMetric]` | 否 | 指标（引用的阶段必须是 evaluate） |

`WorkflowStage`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | `str` | 是 | 阶段 id |
| `kind` | `agent` \| `text` \| `evaluate` | 是 | 阶段类型 |
| `prompt` | `str` | 是（非 evaluate） | 阶段 prompt（非 evaluate 必填） |
| `system_prompt` | `str` | 否 | 系统 prompt |
| `context` | `fresh` \| `continue` | 否 | 上下文模式 |
| `inputs` | `list[StageInput]` | 否 | 引用前置阶段输出（`stage_id`+`field`） |
| `environment` | `fresh` \| `reuse` | 否 | 环境生命周期 |
| `environment_spec` | `AgentEnvironmentSpec?` | 否（仅 `environment=fresh`） | 仅 `environment=fresh` 时可用 |
| `files` | `list[StageFile]` | 否 | 从前置阶段引入文件 |
| `output_files` | `list[str]` | 否 | 本阶段产出的文件 |
| `max_steps` / `max_tokens` | `int` | 否 | 步数/令牌上限 |
| `allow_evaluation_feedback` | `bool` | 否 | 是否允许评估反馈 |
| `test_command` | `str` | 否 | 测试命令 |
| `evaluation` | `dict` | 否 | 评估定义 |
| `resume_commands` | `list[str]` | 否 | 恢复命令 |

`WorkflowMetric`：`operation`（`mean`/`difference`）+ `stages`（列表，`difference` 须恰好两个）。

## 5. 字段契约规则（Builder 侧约束）

- **必填（所有类型）**：`task_type`、`title`、`prompt`、`challenge_effort`、`metadata`。
- **可选基础**：`content_summary`、`description`、`assets`、`tags`。
- **按类型扩展的可选字段**：

| 任务类型 | 追加可选字段 |
|---|---|
| `choice` | `choices`、`correct_choice_indices` |
| `fill_blank` | `expected_texts` |
| `generation` | `rubric`、`judge_tools`、`output_contract`、`scoring` |
| `multi_turn` | `system_prompt`、`interaction`、`rubric`、`judge_tools`、`scoring` |
| `agent` | `system_prompt`、`interaction`、`environment`、`workflow`、`output_contract`、`rubric`、`judge_tools`、`scoring` |

- **source-backed 任务另有 `resource_ids`**：`adapted`/`reused`/`imported_dataset` 任务绑定所用素材 id（对应工作文件 `resources` 里的 id）。
- **框架注入（Builder 不写）**：`id`、`dimension_id`、`metadata.task_design_id`。

## 6. 各类型的语义要求（Builder 必须遵守）

- **choice**：`choices` 至少两个，每项仅 `text`；`correct_choice_indices` 非空，用零基位置；不要把多部分答案对象塞进选择题；选项只放 `choices`，prompt 里不要重复选项文本。
- **fill_blank**：`expected_texts` 为可接受答案列表，任一命中即正确；评分用精确匹配（忽略首尾空白）。prompt 里说清楚限制或枚举所有正确答案，确保列表之外不可能有正确答案。
- **generation**：提供具体 `rubric`；可选 `judge_tools` 请求 `python_tests` 做外部验证，Judge 把工具结果当证据，不直接给分。
- **multi_turn**：顶层 `interaction` 对象，`interaction.max_turns` 在 1–5；scripted 用 `interaction.user_turns`（1–5 个非空字符串）、adaptive 用 `interaction.followup_instruction`（别名如 `scripted_user_turns`/`turns`/`follow_up_policy` 非法）；提供针对性的转写评分标准；`prompt` 是发给目标的第一段完整内容，`system_prompt` 单独作为对话模拟器 prompt。
- **agent**：提供可执行环境、输出契约、确定性检查或针对结果的 rubric；单任务多阶段时提供 `workflow.stages`（显式 stage id、kind、prompts、context、环境生命周期、文件交接、evaluation 阶段），只引用前置阶段的输出，并定义 `workflow.score_stage` 和 `metrics`。
