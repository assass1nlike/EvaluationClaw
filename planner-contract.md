# Planner 字段契约

Planner 把用户的自然语言评测请求转成一份完整的 benchmark 内容设计。它的输出是**一个** `BenchmarkPlan`（对应 `universal_format.json` 的顶层 `plan`），三层结构：**plan → dimensions → task_designs**。本文是这一份契约的完整字段集。

## 1. 输出结构总览

```
plan
├── objective              # 整个 benchmark 测量什么
├── constraints            # benchmark 级要求与排除
├── planner_notes          # 跨 plan 的可选决策
└── dimensions[]
    ├── name
    ├── measurement_target
    ├── boundary
    ├── approach
    └── task_designs[]
        ├── task_type / task_count / challenge_effort
        ├── content_design / input_requirements
        ├── interaction_requirements / environment_requirements
        ├── output_requirements / scoring_contract
        └── source_plan / construction_requirements
            / type_specific_requirements / metadata
```

## 2. Plan 层（`BenchmarkPlan`）

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `objective` | `str` | 是 | 整个 benchmark 作为整体测量什么 |
| `constraints` | `list[str]` | 否 | benchmark 级要求与排除 |
| `planner_notes` | `str` | 否 | 跨 plan 的决策（可选） |
| `dimensions` | `list[BenchmarkPlanDimension]` | 是 | 维度列表 |

框架注入（planner 不写）：`id`、`subjects`、`scale_budget`、`audit`。

## 3. Dimension 层（`BenchmarkPlanDimension`）

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `name` | `str` | 是 | 简洁、描述性的维度名 |
| `measurement_target` | `str` | 是 | 该维度**独立**测量的能力，及该维度任务**必须覆盖**的全部内容 |
| `boundary` | `str` | 是 | 精确的范围边界：排除内容、相邻能力、混淆项、禁止的漂移 |
| `approach` | `str` | 是 | 该维度任务如何引出并测量目标能力 |
| `task_designs` | `list[TaskDesign]` | 是 | 该维度下的 TaskDesign 列表（非空） |

框架注入：`id`。

## 4. TaskDesign 层（`TaskDesign`）

一个 TaskDesign 描述「一个或一组同类任务」，框架为每个 TaskDesign 派发**一个** TaskBuilder 调用。

### 4.1 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 框架拥有（planner 不发明） |
| `task_type` | `TaskType` | `choice` / `fill_blank` / `generation` / `multi_turn` / `agent` |
| `task_count` | `int`（≥1） | 这一个 TaskDesign 要产出的具体任务总数 |
| `challenge_effort` | `E1`/`E2`/`E3` | 构建投入：E1 直接、E2 中等带边界、E3 深度规划+源使用 |
| `content_design` | `dict` | 内容设计（§4.2） |
| `input_requirements` | `dict` | 输入要求（§4.3） |
| `interaction_requirements` | `dict` | 交互要求（§4.4） |
| `environment_requirements` | `dict` | 环境要求（§4.5，仅 agent） |
| `output_requirements` | `dict` | 输出要求（§4.6） |
| `scoring_contract` | `dict` | 评分契约（§4.7） |
| `source_plan` | `dict` | 素材来源计划（§4.8） |
| `construction_requirements` | `list[str]` | 构建任务时的额外要求 |
| `type_specific_requirements` | `dict` | 类型专属扩展（§4.9） |
| `metadata` | `dict` | 附加元数据 |

### 4.2 `content_design`

| key | 说明 |
|---|---|
| `purpose` | 覆盖的任务在维度内测量什么 |
| `description` | 一个复杂任务的具体构想，或多个简单任务的共享内容描述 |
| `coverage_requirements` | 这些任务必须覆盖的内容 |
| `variation_requirements` | 多个任务如何彼此区分 |
| `task_relationships` | 任务间的可选关系/依赖 |
| `exclusions` | 必须避免的内容、捷径、混淆项 |

### 4.3 `input_requirements`

| key | 说明 |
|---|---|
| `description` | 任务收到什么信息/材料 |
| `modalities` | `text` / `image` / `audio` / `video` / `table` / `files` |
| `format_or_schema` | 输入格式/结构/schema |
| `shared_inputs` | 共享输入 |
| `per_task_variation` | 具体任务间输入如何变化 |
| `asset_requirements` | 资产列表，每项 `asset_ref` / `kind` / `role` / `visibility`（`task_visible` 或 `runner_private`）/ `properties` |

### 4.4 `interaction_requirements`

| key | 说明 |
|---|---|
| `mode` | `single_turn` / `multi_turn` / `tool_use` / `environment_interaction` / `mixed` |
| `followup_mode` | 仅 multi_turn：`adaptive` 或 `scripted`（必填） |
| `roles` | 参与交互的角色 |
| `statefulness` | 什么状态持久、如何变化 |
| `turn_or_step_policy` | 轮次/步数策略 |
| `allowed_action_or_tool_categories` | 被评测对象可用的能力 |
| `observation_model` | 动作应产生的反馈 |
| `completion_condition` | 成功/终止条件 |
| `trajectory_requirements` | 过程行为的必需/禁止/计分点 |

### 4.5 `environment_requirements`（仅 agent）

| key | 说明 |
|---|---|
| `category` | `docker_workspace` 或 `vm` |
| `purpose` | 为什么需要执行环境 |
| `initial_state` | 每个任务的初始状态 |
| `required_capabilities` | 环境必须暴露的能力 |
| `required_software_or_services` | 需要的软件/服务 |
| `network_requirements` | 是否需要网络及原因 |
| `fixture_asset_refs` | 引用 `input_asset` |
| `constraints` | Builder 必须保留/避免的环境属性 |

### 4.6 `output_requirements`

| key | 说明 |
|---|---|
| `response_modes` | `choice` / `text` / `structured_data` / `code` / `artifact` / `state_change` / `trajectory` |
| `description` | 成功响应/完成任务应产出什么 |
| `format_or_schema` | 输出格式/schema/接口 |
| `required_components` | 响应的必需部分 |
| `artifacts` | 交付物列表，每项 `kind` / `description` / `format` / `required` |
| `constraints` | 输出属性、限制、禁止的捷径 |

### 4.7 `scoring_contract`

| key | 说明 |
|---|---|
| `components` | 评分组件列表，每项 `method`（exact answer / rubric / executable test / artifact inspection / final-state check / trajectory check / comparison / 其他）、`oracle_type`、`criteria`、`partial_credit`、`required_evidence`、`verification_direction` |
| `aggregation` | 多检查/轮次/交付物/子分如何合并 |
| `trial_policy` | 可选的重复/采样/随机评估要求 |
| `failure_conditions` | 必须判失败的条件 |

### 4.8 `source_plan`

| key | 说明 |
|---|---|
| `strategy` | 恰好一个：`generated` / `adapted` / `reused` / `imported_dataset` |
| `search_queries` | 补充检索词（`generated` 时留空） |
| `suggested_urls` | 源 URL（`adapted`/`reused`/`imported_dataset` 至少一个） |
| `requirements` | 权威性/时效/可复现/许可/来源要求 |
| `asset_source_overrides` | 每项 `asset_ref` + `strategy` |
| `usage_guidance` | 所选策略如何使用素材 |

### 4.9 `type_specific_requirements`

| key | 说明 |
|---|---|
| `protocol` | 可选的命名空间协议/类型扩展标识 |
| `requirements` | 仅放 universal 字段表达不了的要求 |

## 5. 关键行为规则（SKILL.md 摘录）

### 维度划分

- 维度彼此**不重叠**，整体**充分覆盖**用户目标。
- `measurement_target` 写清「该维度独立测什么 + 任务必须覆盖什么」；`boundary` 写清「范围边缘、相邻能力、排除内容、混淆项、漂移形式」。
- **不另设维度级 content-requirement / exclusion 字段**——它们的完整含义直接表达在 `measurement_target` 和 `boundary` 里。任务级覆盖与排除仍放在各 TaskDesign 的 `content_design`。

### 任务与类型

- 只用五种任务类型：`choice`（两个以上选项 + 一个或多个正确位置）、`fill_blank`（expected_texts 列表，任一命中即精确匹配）、`generation`（Judge 按 rubric 评分）、`multi_turn`（scripted/adaptive 对话）、`agent`（工具 + 可执行环境）。
- 所有维度 `task_count` 之和 = 用户目标总数；按覆盖价值分配，不默认均分。
- `challenge_effort` 只有三档。
- **环境仅 agent**：`choice`/`fill_blank`/`generation`/`multi_turn` 的 `environment_requirements` 必须返回 `{}`（不要展开内部字段为 null/空串/空列表）；要可执行交互就改成 `agent`。`multi_turn` 的对话行为走 `interaction_requirements`，不用执行环境。
- **多轮必设**：`interaction_requirements.followup_mode` 必须 `adaptive` 或 `scripted`。
- **source_plan.strategy 恰好一个**：`generated` 留空 URL；`adapted`/`reused`/`imported_dataset` 至少给一个 `suggested_urls`。
- **非 agent 不用文件资产**（除图片）：非 agent 任务用文本 + 图片（以 `Image N` 引用，框架按 assets 顺序附加）；非图片文件需求 → 改 `agent`。

### 全局审计

- 完整覆盖用户目标并满足请求；每个任务都有足够具体的 `content_design`；所有 JSON 字段符合格式、任务数吻合。

### 输出

- 返回一个完整 JSON 对象，严格遵循 `universal_format.json`，含 benchmark 级 plan、每个维度、每个 TaskDesign。
- **不加** Blueprint / batch / 分配 / 分组 / 工作量分区字段——框架会在 planning 后为每个 TaskDesign 确定性地派一个并发 Builder job。
- 最终响应只输出纯 JSON，无 Markdown 围栏、无前后文字。

## 6. 与框架内部对象的对应

Planner 输出的 `BenchmarkPlan` 与内部 `EvalSpec`/`EvalDimension` 的关系：

- `BenchmarkPlan` 是 Planner 的**对外契约**（plan + 维度 + TaskDesign 三层）。
- 内部 `EvalDimension`/`EvalSpec` 字段更丰富（`weight`、`needs_research`、`target_item_count`、`challenge_effort_distribution`、`scale_budget` 等），这些由框架在 planning 阶段填充，**不属于 Planner 的编写契约**。
- 框架拥有所有 id（plan / dimension / TaskDesign / task / resource / choice-option），Planner 不得发明。
