# TaskBuilder 任务字段契约（超集）

TaskBuilder 根据 Planner 的 TaskDesign 生成 `TaskDefinition`。Builder、QC、Runner、Analyzer 和 LaaJ 使用同一份任务定义；`BenchmarkItem` 只增加题集来源信息，`source_definition` 是兼容访问视图。定义的版本号为 `schema_version: 2`；旧题可直接读取并沿用原来的呈现与评分语义。

通常使用下文的简短题型模板。需要准确保留角色化上下文、任意资源、自定义评分或自适应交互时，使用同一模型中的显式契约：

| 字段 | 内容 |
| --- | --- |
| `content` | 有序 `messages`，每条含 `role`、`content`，可注明 `origin` 为 task、seeded_context 或 prefill。内容为文本或 text/json/asset/image 块；输出要求放在 `content.output_contract`。可声明 stop、generate/continuation_likelihood 及待评分续写。 |
| `assets` | id、path、media_type、sha256、version、uri、visibility、mount_path、writable、status。目标输入只能引用授予 target 的资源；组件只接收自身 assets 列表中的资源。mount_path 是包内相对路径；writable=null 沿用后端行为，文件系统只读授权暂不支持，显式声明会被拒绝。 |
| `environment` | 现有 Docker/VM，或 tool_service：版本固定的服务组件、工具 schema、初始状态和显式 checkpoint/inspect 能力。容器承载服务不意味着目标获得 shell。 |
| `interaction` | protocol 为 response/dialogue/tool_loop/program/model；参与者、工具权限、控制动作授权、控制器可见事件来源、对话后续输入及预算。actor_contact_tool 可暴露角色联系入口。 |
| `evaluation` | references、metrics、scorers、可选 scalar、verification_cases。参考可为答案、标签、轨迹、测试、状态、准则，注明示例或完整允许集合。评分可为 exact/json/component/llm/agent/environment/aggregate，保留每项原生指标与方向。 |
| `provenance` / `annotations` | 来源和原字段映射；原生语言、难度、类别等注释。不为导入题凭空赋予构题 effort。 |

使用 `content` 时，删除模板中的 prompt、system_prompt、choices、output_contract，并将答案、参考轨迹、rubric 和评分配置统一放入 evaluation；不能维护两份互相竞争的输入或评分规则。exact/json 评分器需要内联参考值，llm/agent 评分器需要明确指令。题型标签不改变显式契约的执行或评分。无唯一答案的任务可用完整的检查器评分。用于 Analyzer 的题目必须明确选择 `evaluation.scalar` 的指标、范围和方向；否则只保留多指标结果，不猜测能力分数。题集级 mean/sum/micro/component 聚合写在 `TaskSuite.evaluation_plan`，分支不增加题目数量。

Builder 可调用 `read_task_contract(section="schema")` 获取实际完整 schema，调用 `read_task_contract(section="component_protocol")` 获取服务协议，均支持分页。Planner 和 Builder 均收到 task_runtime_capabilities，描述当前运行绑定的实际能力。CLI 显式工作区支持 Docker、初始 user 文本、response/tool_loop/dialogue 和现有 environment actors；interaction.turns 按顺序投递 user 消息，工作区持续保留，interaction.reset_between_turns=true 时重置对话历史，否则要求 harness 支持会话续接。后续消息不会提前公开，评分保留各轮输入与输出。原生接口重置时保留初始 system/developer 指令与公开提交契约，历史交互仍留在审计事件中。原生角色历史、参与者工具授权、自适应控制器及工具服务使用兼容的原生模型接口。prefill、续写似然等能力不可用时，预检明确报错，不改写实验。

需要文件交付时，可在 output_contract（显式任务为 content.output_contract）声明 `{"schema_version":"evalclaw.output.v1","artifacts":[{"id":"report","path":"deliverables/report.json","format":"json","required":true,"schema":{"type":"object"}}]}`。path 相对工作区，format 可为 file/directory/text/json/csv；schema 仅用于 JSON，response_schema 可描述最终文本回答的 JSON 结构。`read_task_contract(section="submission_contract")` 返回完整字段定义。框架将这份公开契约加入目标输入，并在评分证据的 submission_contract.artifact_paths 中提供相同的 ID→绝对路径表；工作区评分器通过 `/evalclaw-evidence/episode.json` 读取，显式组件通过评分请求读取。评分器应按 ID 使用路径；题面和示例不得与契约矛盾。契约不自动修改产物、转换类型或决定得分。没有该版本声明的既有输出契约维持原语义。

Docker 环境的 interventions 支持 `trigger:{"type":"episode_end"}`，在目标正常结束或题目预算耗尽后、评分前按声明顺序执行 action；异常退出清理不执行结算。未触发的 elapsed_time/condition 不会自动补跑。结算失败视为执行错误。公开任务规则应说明观察时点，结算脚本在 stdout 或审计记录中保留相关前后状态，不得补做目标的工作。验证案例可用 required_interventions 要求结算实际发生。

已有文件和镜像工具用于创建组件。`verify_candidate` 对显式契约接受 tool_calls/final_answer 的交互试交付，或 responses 数组中的逐轮 content、tool_calls、usage，通过正式状态机调用工具与评分器，不调用目标模型。多轮与控制器协议使用 responses。可在 evaluation.verification_cases 声明 id、responses 和 expected_metrics（指标名到 [最小值, 最大值] 的映射），预检独立重放并核对，建议覆盖正确与错误交付。CLI 工作区使用 environment.verification_cases 的命令与最终答案，按显式契约所选 scalar 检查结果。试运行单独标记，其预设回答不是模型实测表现。

组件声明 image、version、command、files、config、输入/输出 JSON Schema、可访问 assets、网络权限、超时和 model_roles。组件在独立 Docker 容器中通过 stdin/stdout JSON 行通信，日志写 stderr；请求为 `{id, method, params, config}`，响应为 `{id, result}` 或 `{id, error}`。环境依次处理 initialize、call_tool、finalize，再由独立组件实例 score；原生 post-task/export 应在 finalize 内完成。控制器 next 接收获准来源的新增事件和自身状态，返回 actions 和状态。原生依赖可预装在镜像中，组件可以直接调用原实现，无需重写判分逻辑。模型回调通过声明的 actor/judge 角色绑定，不向容器提供 API 凭据。

每个组件实现 describe，返回 `{version, methods}`；预检核对版本与所需方法。缺失的原生组件可用 status 与 unavailable_reason 如实记录，供静态审阅，但不能执行。finalize 的 artifact_files 将产物名映射到容器内文件，框架导出并记录 SHA-256；评分组件在 `/component/outputs/<产物名>` 读取校验后的副本。agent 评分器可按需读取证据、产物并检查独立环境状态。评分器仅能看到 depends_on 明确引用的已有指标；aggregate 按显式 weights 加权。response_view 区分目标新生成内容与包含 prefill 的完整消息。

交互控制动作包括 message、target、tool_result、tool_call、register_tools、reset_session、checkpoint、restore、branch、actor、end，必须逐项授权。participants 的可执行角色为 target 和 actor；控制器使用 interaction.controller/controller_prompt，模拟服务在环境组件中实现。checkpoint 明确选择 conversation/environment/actors；恢复不删除审计事件，不退还已消耗预算。Actor 只接收自己的指令、授权资源和通信历史。外部 prefill 与目标新生成的内容分别记录。

每次运行生成 `EpisodeRecord`：定义哈希、运行绑定、seed、按来源区分的事件、初末状态、输出、产物、预算、终止原因及原生指标。事件增量写入 events.jsonl，生命周期节点保存 episode.json。旧执行器保留完整原生证据引用，不伪造旧日志无法确定的事件。评分错误与有效零分分开。QC、Analyzer、LaaJ 首先收到题目与组件文件目录，完整内容可按需分页读取；read_task_file 的 area=definition、path 为 JSON Pointer。QC 保存被审题目的定义哈希；Analyzer 读取时区分匹配、过期和未绑定版本的审阅。Analyzer 的 evidence_assessments 跨轮保留任务引用、问题类别、涉及评分组件及具体证据；尚未消除题目或执行疑点的任务不能进入最终弱点题集。LaaJ 在新实例中试交付并调用评分器，其操作不归到目标名下。CLI 多轮探索仅支持初始环境检查，不能以单阶段命令验证案例代替完整会话验证。

构题 Python 在独立 Docker 环境中运行，同一 Builder 的调用共享环境，仅挂载该作业的文件目录，使用独立 `/tmp`。默认镜像为 `python:3.11-slim`，每个构题执行容器的内存上限为 8192 MiB、进程数上限为 512；运行方可通过 `builder_sandbox_image`、`builder_memory_mb`、`builder_pids_limit` 配置。可在其中安装 Python 包、启动后台服务；后台进程需把输入输出重定向到文件或 DEVNULL。Python 调用超时（60 秒）会停止整个环境，作业结束或所属框架进程退出时会清理容器。只有作业目录中的文件保留。Docker 构建与检查通过框架工具完成；检查容器也挂载该作业目录，且受内存、进程和生命周期管理约束。

## 1. 简短模板的输出结构

```
tasks[]（每个元素是一个 task 对象，框架打包成 BenchmarkItem）
├── task_type / title / prompt / challenge_effort / metadata   # 公共必填
├── content_summary / description / assets / tags               # 公共可选
├── resource_ids                                                # 仅 source-backed
├── [choice]     choices / correct_choice_indices
├── [fill_blank] expected_texts
├── [generation] reference_answer / rubric / judge_tools / output_contract / scoring
├── [multi_turn] system_prompt / interaction / rubric / judge_tools / scoring
└── [agent]      system_prompt / interaction / environment / workflow
                 / output_contract / reference_trajectory / rubric / judge_tools / scoring
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
| `task_type` | `TaskType` | 是 | 模板与报告标签；显式 content/evaluation 契约独立决定执行与评分 |
| `title` | `str` | 是 | 任务标题 |
| `prompt` | `str` | 是 | 发给被评测模型的完整任务提示 |
| `challenge_effort` | `ChallengeEffort` | 是 | 难度档位：`E1` / `E2` / `E3` |
| `metadata` | `dict` | 是 | 附加元数据（`task_design_id`、`task_model_id` 等） |
| `content_summary` | `str` | 否 | 任务内容摘要（默认空串） |
| `description` | `str` | 否 | 详细描述（默认空串） |
| `assets` | `list[TaskAsset]` | 否 | 附加资源文件（`TaskAsset.path`）；正文内的文本表格不需要附件，明确要求的文件输入仍须提供 |
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
| `reference_answer` | `str` | 是 | 一份正确、自包含的参考答案；供 Judge 和审计使用，不展示给被测模型，也不限定唯一措辞 |
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
| `system_prompt` | `str` | 否 | 目标的任务级指令 |
| `interaction` | `dict` | 否 | 保持为空；追加用户消息和上下文切换使用 `workflow.stages` |
| `reference_trajectory` | `list[ReferenceTrajectoryStep]` | 是 | 一条按顺序排列、确实可行的参考操作路径；每步含 `action`，可含 `tool`、`arguments`、`expected_observation`；不要求被测模型逐步复现 |
| `output_contract` / `rubric` / `judge_tools` / `scoring` | — | 否 | 同生成题 |

## 4. 子结构

单阶段 Docker 题可用 `verify_candidate(task_index=...)` 验证当前候选的验证用例；提交前框架会重新执行。参考解、空/不完整产物、核心违规或合法替代解应有相应分数区间。参考轨迹和已知缺陷并不穷尽所有合法解；开放语义可使用 judge，实际配置和操作使用结构化检查，不用自然语言关键词判定是否执行或同意某行为。

外部 harness 的 workflow 支持同一 Docker 环境内若干 agent 阶段及最后一次 evaluate：首阶段 environment=fresh，之后 reuse；context=fresh 重置对话，continue 保留对话。保留对话要求 manifest 提供 `session_run`，内置 OpenClaw 已提供。外部 workflow 不支持 text 阶段、阶段环境覆盖、文件转交、中途评分及派生 metrics；评分配置只放在最终 evaluate 阶段。非默认的阶段 max_steps/max_tokens 要求 harness 命令提供对应参数；默认值不代表外部 harness 会强制这些限制。后续提示词仅在轮到对应阶段时发送。环境变化使用 interventions。

评估证据中的 availability/provenance 说明记录来源与完整性；空轨迹不代表没有操作。模型 API 轨迹记录模型请求和 harness 报告的工具返回，不等同于系统调用审计。初始化、harness 维护和评审操作不能仅因相同 UID 而归责目标。

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
| `runtime_files` | `dict[str,str]` | 否 | `{}` | 原生运行时的私有支持文件；外部 harness 不支持，初始化支持材料放入 `image_build`，目标可见材料放入 `visible_files` |
| `hidden_files` | `dict[str,str]` | 否 | `{}` | 仅在评分时注入的隐藏文件（如测试）；setup 不可依赖它们，评测文件初始化放入 `test_command`，不向目标暴露 |
| `image` | `str` | 否 | `""` | Docker 镜像（空则自动选） |
| `auto_select_image` | `bool` | 否 | `true` | 是否按任务文本自动选镜像 |
| `image_selection` | `dict` | 否 | `{}` | 镜像选择元数据 |
| `image_build` | `dict` | 否 | `{}` | 镜像构建定义（`context_dir`/`base_image`/`dockerfile_name` 等） |
| `pull_image` | `bool` | 否 | `true` | 是否拉取镜像 |
| `pull_timeout` | `int` | 否 | `300` | 拉取超时（秒） |
| `setup_commands` | `list[str]` | 否 | `[]` | 环境初始化命令 |
| `readiness_checks` | `list[str]` | 否 | `[]` | Docker 初始化后以目标身份执行的只读就绪检查；非零退出阻止启动 |
| `preflight_commands` | `list[str]` | 否 | `[]` | 只在独立 Docker 预检实例执行的功能自检；非零退出表示环境不合格 |
| `verification_cases` | `list` | 否 | `[]` | 私有验证用例：`id`、目标身份执行的 `commands`、`final_answer`、`min_score`、`max_score`；可用 `required_interventions` 列出必须成功触发的干预 ID；各用例独立初始化并运行原评分器 |
| `budget` | `EpisodeBudget` | 否 | `null` | 外部 shell harness 的 `wall_time_seconds`；准备完成后的目标启动开始计时，包含推理、网络等待和各阶段，到期保留产物并评分 |
| `test_command` | `str` | Docker 脚本或混合评分必填 | `""` | 显式评分命令，放在 environment 下 |
| `max_steps` | `int` | 否 | `8` | 原生运行时最大交互步数；外部 harness 用于计算基础设施超时，不保证工具调用次数限制 |
| `timeout` | `int` | 否 | `20` | 原生单步超时；外部 harness 与 max_steps 共同决定基础设施超时 |
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
| `judge` | `AgentJudgeSpec` | 否 | `null` | Docker 题的探索式作答评分；省略时使用脚本；外部 workflow 可用于最终评分 |
| `notes` | `str` | 否 | `""` | 备注 |

外部 shell harness 共用同一套题目初始化、运行检查和评分流程。`setup_commands` 和评分器以 root 执行，目标以非 root 用户执行；初始化时可使用 `EVALCLAW_TARGET_UID`、`EVALCLAW_TARGET_GID` 为需要目标修改的文件设置所有权。声明结构化评分时，即使尚无作答也必须返回合法分数，不能把评分器异常当作答错。

镜像预置的 `/workspace` 内容保留后，再覆盖声明的 `visible_files`；资源文件不能与已有文件冲突。为关键输入和服务提供 `readiness_checks`，验证目标可读、可访问及必要服务已就绪；检查应快速、只读，不消费任务预算。需要实际请求、断连后重连或验证参考路径时，使用 `preflight_commands`，它只作用于随后丢弃的预检实例。不要把题目故意安排的后续故障自动修复，也不要用“尚无目标产物所以得 0 分”代替环境健康检查。

`environment.judge` 包含 `mode`（`judge` 或 `hybrid`）、`instructions` 和非空 `criteria`。每项 criterion 包含唯一 `id`、描述 0–1 分锚点及证据要求的 `rubric`，以及正数 `weight`（默认 1）。Builder 从可用 task models 中选择一个，写入 `metadata.task_model_id`；模型连接由运行配置提供。Judge 分数是各项分数的加权平均，必须附带理由和所引用的审阅工具调用 ID。

`judge` 模式不要求 `test_command`。`hybrid` 模式要求脚本和显式 `script_weight`，按 `script_weight × 脚本分 + (1-script_weight) × judge分` 汇总；可设 `script_gate=true`，使脚本分不足 1 时总分为 0。脚本与 judge 执行异常均作为评估错误。

Judge 审阅本次作答后的文件系统副本和保存的执行证据，命令以评审权限运行并单独留痕。副本保留文件及目录挂载的权限，不保留原进程、内存或外部网络。可选 `judge.setup_commands` 用于在副本中恢复本地服务，不得重新初始化、修复或代做目标的产物。需要判定历史行为时，应在环境中留下相应日志。VM 和原生多阶段 workflow 暂不支持这一评分方式。

角色通过 `environment.actors` 定义，各自提供 `id`、`system_prompt`，以及可选的 `description`、`actor_toolsets` 中的 `toolset` 名称。各个外部 shell harness 均通过 `python3 /run/evalclaw-contacts/contacts.py list` 列出联系人，通过 `python3 /run/evalclaw-contacts/contacts.py send CONTACT_ID 'message'` 联系角色；任务镜像须包含 Python 3，客户端和使用说明由框架提供。角色的历史、工具权限和私有角色知识由框架管理，模型接口凭据不进入题目容器。

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
| `generation` | `reference_answer`、`rubric`、`judge_tools`、`output_contract`、`scoring` |
| `multi_turn` | `system_prompt`、`interaction`、`rubric`、`judge_tools`、`scoring` |
| `agent` | `system_prompt`、`interaction`、`environment`、`workflow`、`output_contract`、`reference_trajectory`、`rubric`、`judge_tools`、`scoring` |

- **source-backed 任务另有 `resource_ids`**：`adapted`/`reused`/`imported_dataset` 任务绑定所用素材 id（对应工作文件 `resources` 里的 id）。
- **框架注入（Builder 不写）**：`id`、`dimension_id`、`metadata.task_design_id`。

Builder 可用 `read_document` 分页读取工作目录内的 UTF-8 文本、PDF 或指定 ZIP/TAR 成员，用 `list_archive` 分页查看成员，用 `extract_archive` 解出指定文件或整个包（每次最多 64 个文件、解压后总计 1 GiB）。解压保留目录结构和可执行权限，不执行文件；返回路径可直接作为 `assets` 或 `build_image.context_files` 的来源，后者通过目标路径保留 Docker 内的目录布局。返回列表不完整时，可读取 `manifest_path` 获取全部文件。以上本地工具不依赖联网开关。PDF 文本提取需安装 Poppler 的 `pdftotext`，不包含扫描件 OCR。`fetch_url` 和 `read_research_source` 也支持用 `offset` 接续返回的 `next_offset`；后者仅能读取 Planner 已保留的文本。

## 6. 各类型的语义要求（Builder 必须遵守）

- **choice**：`choices` 至少两个，每项仅 `text`；`correct_choice_indices` 非空，用零基位置；不要把多部分答案对象塞进选择题；选项只放 `choices`，prompt 里不要重复选项文本。
- **fill_blank**：`expected_texts` 为可接受答案列表，任一命中即正确；评分用精确匹配（忽略首尾空白）。prompt 里说清楚限制或枚举所有正确答案，确保列表之外不可能有正确答案。
- **generation**：提供正确、自包含的 `reference_answer` 和具体 `rubric`；可选 `judge_tools` 请求 `python_tests` 做外部验证，Judge 把工具结果当证据，不直接给分。
- **multi_turn**：顶层 `interaction` 对象，`interaction.max_turns` 在 1–5；scripted 用 `interaction.user_turns`（1–5 个非空字符串）、adaptive 用 `interaction.followup_instruction`（别名如 `scripted_user_turns`/`turns`/`follow_up_policy` 非法）；提供针对性的转写评分标准；`prompt` 是发给目标的第一段完整内容，`system_prompt` 单独作为对话模拟器 prompt。

对话模拟器的角色设定只约束其发送给目标的消息内容；框架单独管理 JSON 传输和结束标记。`generation` 与 `multi_turn` 声明的 `python_tests` 都实际执行：`{model_output}` 分别替换为目标回复字符串、完整对话 JSON 字符串（按顺序排列的 `role`、`content` 对象数组），序列化标记不是目标回复正文。工具输出作为评分证据保存。rubric 应明确满分和聚合规则，评分器返回同一尺度的所得分与满分，由框架计算二者之比；不固定将题目的原始得分除以 5。
- **agent**：提供可执行环境、输出契约、确定性检查或针对结果的 rubric，并给出一条可行但非唯一的 `reference_trajectory`；单任务多阶段时提供 `workflow.stages`（显式 stage id、kind、prompts、context、环境生命周期、文件交接、evaluation 阶段），只引用前置阶段的输出，并定义 `workflow.score_stage` 和 `metrics`。
