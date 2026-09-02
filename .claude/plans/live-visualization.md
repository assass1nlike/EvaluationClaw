# 方案：框架运行实时可视化 + LLM 全路径真流式

## 背景与验证结论

用户诉求：给需求后到产出前的长跑阶段，想在浏览器里实时看到 (1) 当前所处阶段/进度 (2) 各个 LLM 调用的实时输出（逐 token 增长）。已确认服务形态为「独立常驻进程」，可多 run 并存、多 tab 打开。

已实测（真实 API）：
- LiteLLM 流式文本：`finish_reason="stop"` 正确，24 chunks，TTFT 0.23s，稳定。
- LiteLLM 流式工具调用：`finish_reason="tool_calls"`，`arguments` 以 JSON 片段增量累积，拼接后是合法 JSON，可被现有 `openai_tool_calls_from_message` 消费。
- Anthropic SDK：`client.messages.stream(...)` 返回 `MessageStreamManager`，含 `text_stream` / `get_final_message()`（静态确认，无 key 未实测）。

结论：所有非流式路径改成真流式可行且更优。

## 总体架构

新增一个常驻的本地 `live` 组件（HTTP + SSE），pipeline 每次运行时自动注册进去；LLM 层所有调用点连到 live 总线，逐 token 推送；前端每个 run 一个 tab，展示阶段进度 + 各 LLM 调用实时输出。已有事件（log/progress）与新增 token 事件统一走一条 SSE 流。

```
pipeline 跑起来
   ├─ run 注册到 live 服务 (port 默认 8800, localhost only)
   ├─ log()/progress() → live 事件 "stage"/"log"/"progress"
   └─ llm.py 各流式路径 → 每 token 触发 live "token" 事件
浏览器:
   http://localhost:8800/            → 运行列表页 (多 run)
   http://localhost:8800/run/{id}    → 单 run 实时视图 (阶段 + LLM 卡片)
   http://localhost:8800/events/{id} → SSE 事件流
```

关健设计决定：**live 上下文不逐处透传参数**。`llm.py` 里所有调用点已经携带 `trace_dir`（唯一 run 调试目录）和 `trace_name`。live 层维护一个 `run_dir → run_id` 的注册表，`llm.py` 从调用点已有的 `trace_dir` 自动解析出 `run_id` 和 **stage**（由 `trace_dir` 相对 run_dir 的路径段推导：planner / construction / qc / research / runner / analysis / judge 等）。这样改造只在 `llm.py` 内部和 pipeline 注册处，几十个调用点零改动。

安全性：只绑定 127.0.0.1；事件文本复用现有 `redact_secrets`。不引入任何外部前端依赖。

## 一、LLM 层：四条非流式路径改真流式（`evalclaw/models/llm.py`）

统一新增一个可选的 token 回调参数 `live_stream: callable | None`（默认 None），由 `trace_dir` 注入实际的 live 发布器；每个流式路径在收到增量文本时调用它。四处改造：

1. `_call_litellm`（`call_llm` 默认走这）：加 `stream=True`，改为迭代 chunk 累积内容，按 `finish_reason=="length"` 判定截断（与现逻辑一致）。OpenAI 兼容路径。
2. `_call_anthropic_text` / 原生 Anthropic 文本分支（`call_llm`、`call_target_model`）：改用 `client.messages.stream(...)`，遍历 `stream.text_stream` 累积，`stop_reason=="max_tokens"` 判截断。
3. `call_orchestrator_with_tools` 的 Anthropic 分支：`messages.stream(...)`，用 `get_final_message()` 组装完整 assistant message（含 text + tool_use 块），延续现有 `anthropic_tool_calls_from_response` / `_anthropic_text` 消费。
4. 原生 `tool_adapter_for_target` == anthropic 的 `call_target_model_with_tools`：同上 `messages.stream` + `get_final_message()`。

其余：
- `_post_streaming_openai_compatible` / `_post_streaming_responses`（已是流式）：补充 token 回调推送。
- 保持 `retry_on_truncation`（加倍预算重试）语义不变；流式下仍按 finish/stop reason 检测截断后抛出 `LLMOutputTruncatedError`。
- `EVALCLAW_LLM_STREAMING` 作为额外开关保留；live 模式下无论该开关与否都应流式（因为 live 需要逐 token）。

## 二、live 组件（新增 `evalclaw/live/`）

- `evalclaw/live/__init__.py` — 模块导出。
- `evalclaw/live/bus.py` — 线程安全的 per-run 事件总线（stage/log/progress/token/run_end），订阅者（SSE 连接）队列；`register_run` / `publish` / `subscribe`。
- `evalclaw/live/registry.py` — run_dir→run_id 映射，供 `llm.py` 无参透传地解析 run 上下文。
- `evalclaw/live/server.py` — `ThreadingHTTPServer`，路由：`/`（运行列表，静态 HTML 注入 JSON）、`/run/{id}`（单 run view）、`/events/{id}`（SSE 长连接）、`/api/runs`。仅监听 127.0.0.1；`serve` 子命令启动；首个 run 注册时自动 lazy-start。
- `evalclaw/live/streamers.py` — 从 `trace_dir` 推导 stage/run_id，构造 token 回调发布器。
- `evalclaw/live/template.html` — 自包含前端（见四）。

## 三、pipeline / CLI 接线

- `evalclaw/live/cli.py`：新增 `evalclaw serve` 子命令，常驻并打印列表页地址；`generate` 增加 `--live` 开关（默认开，可用 `--no-live` 关）。live 关闭时零开销（发布函数为 no-op）。
- `evalclaw/pipeline.py` `run_pipeline`：注册 run（goal、config、start time）→ 挂接 live 发布到 `log`/`progress` 回调（沿用现有 `traced_log`/`traced_progress` 机制一并转发）→ run 结束发 `run_end`（含最终结果路径）。
- `evalclaw/cli.py` (`main`)：注册 `serve` 命令；`generate` 结束打印 live 链接。

## 四、前端 `evalclaw/live/template.html`

单文件自包含（内嵌 CSS/JS，无外部依赖、无构建，沿用现有 viewer 风格），一个模板同时是列表页与 run 视图（JS 按 path 判断）。

布局：
- 顶栏：run 标题 + goal + 状态（running / completed / failed）+ 已等待时长（计时 animation）。
- 主区左侧：**阶段时间线**（translation → deep_research → planner → construction → qc → runner → analysis → report），当前阶段高亮，各阶段完成/进行中/失败状态。
- 主区右侧：**LLM 调用卡片**，每张卡片 = 一次模型调用（按 role/model/stage 分组，如 `Planner · attempt 01`、`Task Builder · dimension_1 task_design_2 1/4`、`Judge · first pass`、`Deep Research · reflect round 1`）。卡片内：
  - 头部：role(模型名)、发起时间、已等待时长、状态徽章（调用中/截断重试中/完成/失败）。
  - 主体：等宽字体、语法高亮（JSON 高亮，非 JSON 用纯文本），**逐 token 增长**（来自 SSE `token` 事件），自动滚到最新；已完成显示完整内容 + 完成耗时。
  - 工具调用（task-builder）：显示 tool 循环轮次。

数据流：页面用 `EventSource(/events/{run_id})` 接收增量事件，JS 就地更新 DOM（不重渲染）。断线自动重连；刷新后从服务端快照恢复（服务端为每个 run 保留事件日志，`/run/{id}` 首次加载先拉快照再订 SSE）。

## 五、验证与测试

- 新增 pytest：live/bus 发布-订阅-多 run 隔离；registry 的 run_dir 推导；stage 推导；token 累积 ≥ 后端不变量（逐 token 拼接 == 最终内容）。
- 保留现有 462 测试；改流式后确认 `test_azure_and_search`、`test_model_endpoints` 仍过。
- `call_llm` / `call_orchestrator_with_tools` 流式在 DeepSeek/OpenAI 真实调用下回归（社区 key）。
- Anthropic SDK 真流式无法在无 key 环境实测——该分支代码给出，标注需在有 `ANTHROPIC_API_KEY` 时验证；所用 `messages.stream`/`MessageStreamManager`/`get_final_message` API 形状已按本机 SDK 0.105.2 静态核对。

## 六、文件清单

改动：
- `evalclaw/models/llm.py` — 4 处非流式→流式 + token 回调。
- `evalclaw/cli.py` / `evalclaw/live/cli.py` — `serve` 子命令、`--live` 开关、结尾打印链接。
- `evalclaw/pipeline.py` — run 注册、log/progress→live、run_end。
- `tests/` — live 相关单测。

新增：
- `evalclaw/live/__init__.py`、`bus.py`、`registry.py`、`server.py`、`streamers.py`、`template.html`、`cli.py`。

## 待确认（默认按推荐执行）

1. Anthropic SDK 真流式本机无 key，无法端到端实测——接受"代码给出+静态核对，运行时由你验证"。
2. `--live` 默认开启（关闭零开销）。
3. 端口默认 8800，被占用时自动 +1。
