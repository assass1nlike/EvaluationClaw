# Multimodal Item Spec

`metadata.multimodal` 是 EvaluationClaw 给多模态题目的标准化 JSON 对象。它和 `metadata.task_agent` 一样，不是单独的文件路径，而是写在每道题的 `metadata` 里；导出 benchmark package 时也会原样保存。

当前代码里对应的 schema 常量在 [evalclaw/multimodal.py](../evalclaw/multimodal.py)。

这个规格主要用于：

- 图像理解、视觉推理、OCR、图表理解、截图问答等题目。
- 未来的音频、视频、多模态对话等题目。

## 字段

`schema_version`

固定为 `evalclaw.multimodal.v1`。

`modalities`

题目涉及的模态列表。例如：

- `image`
- `audio`
- `video`
- `text`

`assets`

媒体资产列表。每个资产至少需要：

- `id`：稳定引用名，比如 `image_1`
- `kind`：资产类型，通常是 `image`

常见可选字段：

- `uri`：公网 URL、data URI，或者可解析的本地路径
- `path` / `data_uri`：本地路径或显式 data URI
- `mime_type`：如 `image/png`、`image/svg+xml`
- `caption` / `alt_text`：给生成和 QC 看的说明
- `detail`：给 provider 用的图像细节等级，例如 `high`

`content`

按顺序组织的输入块列表。常见两种块：

- `{"type":"text","text":"..."}`：普通文本
- `{"type":"asset","asset_id":"image_1","detail":"high"}`：引用某个资产

如果没有显式写 `content`，runner 会默认用题目文本加上全部资产。

`scoring`

评分说明。可以是：

- 绝对分数 rubric
- pass/fail 规则
- 视觉证据相关的 judge 指导

## runner 行为

当前 runner 会根据目标 provider 把 `metadata.multimodal` 转成原生内容块：

- OpenAI / OpenAI-compatible：`text` + `image_url`
- Anthropic：`text` + `image`

如果资产是本地文件，runner 会尽量转换成 data URI；如果是公网 URL，则直接传给 provider。

## 生成要求

当 planner 判断某个维度需要多模态能力时，item-generation worker 应当：

- 在维度说明和 item_requirements 里明确写出需要哪些模态。
- 在 item 的 `metadata.multimodal` 里写完整的资产、顺序和评分标准。
- 让 prompt 本身明确指出模型需要看什么、回答什么，以及哪些视觉证据是关键。

