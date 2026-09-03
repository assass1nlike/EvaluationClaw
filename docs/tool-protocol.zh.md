# EvaluationClaw Tool Protocol

EvaluationClaw 现在有一套内部标准工具调用协议，版本号为：

```text
evalclaw.tool_protocol.v1
```

它的目标不是替代 OpenAI、Anthropic、Gemini 或自研 agent 的原生协议，而是作为 EvaluationClaw 内部统一格式：

```text
外部原生工具协议
  -> adapter
  -> EvaluationClaw ToolSpec / ToolCall / ToolResult / AgentTrace
  -> runner / scorer / reporter
```

这样未来无论接入主流大模型还是内部 agent，都只需要写 adapter，把原生事件转换成 EvaluationClaw 的 canonical trace。

## 核心对象

`ToolSpec`

描述一个工具：

```json
{
  "name": "read_file",
  "description": "Read a visible file by relative path.",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {"type": "string"}
    },
    "required": ["path"],
    "additionalProperties": false
  }
}
```

当前校验支持一个小而确定的 JSON Schema 子集：

- object
- required
- properties
- primitive type: string / integer / number / boolean / object / array
- enum
- additionalProperties=false

`ToolCall`

描述模型请求调用的工具：

```json
{
  "id": "call_1",
  "name": "read_file",
  "arguments": {"path": "solution.py"},
  "raw": {}
}
```

`ToolResult`

描述工具执行结果：

```json
{
  "tool_call_id": "call_1",
  "name": "read_file",
  "content": "def solve():\n    pass\n",
  "error": null,
  "raw": {}
}
```

`AgentTrace`

描述完整 agent 运行过程：

```json
{
  "protocol_version": "evalclaw.tool_protocol.v1",
  "turns": [],
  "final_answer": "",
  "final_state": {},
  "raw_native_trace": {},
  "adapter_notes": ""
}
```

当前 `agent` runner 仍保留 trace 字段，例如 `parsed_action`、`observation`、`score_after_step`，同时新增标准字段：

```json
{
  "tool_protocol_version": "evalclaw.tool_protocol.v1",
  "tool_specs": [],
  "trace": [
    {
      "step": 1,
      "model_output": "{\"action\":\"read_file\",\"args\":{\"path\":\"solution.py\"}}",
      "parsed_action": {"action": "read_file", "args": {"path": "solution.py"}},
      "tool_call": {
        "id": "call_1",
        "name": "read_file",
        "arguments": {"path": "solution.py"}
      },
      "tool_result": {
        "tool_call_id": "call_1",
        "name": "read_file",
        "content": "File solution.py:\n...",
        "error": null
      },
      "observation": "...",
      "error": null,
      "score_after_step": 0.25,
      "done": false
    }
  ]
}
```

## 当前内置环境

`docker_workspace`

内置工具：

- `list_files`
- `read_file`
- `write_file`
- `run_command`
- `run_tests`
- `final`

具体工具会按任务的文件保护和浏览器配置收窄。

`gui`

内置工具：

- `screenshot`
- `cursor_position`
- `key` / `key_down` / `key_up` / `type` / `hold_key`
- `mouse_move` / `click` / `drag` / `mouse_down` / `mouse_up` / `scroll`
- `wait`
- `list_files`
- `read_file`
- `write_file`
- `run_command`
- `evaluate`
- `final`

这些工具现在都由结构化 `ToolSpec` 定义，prompt 中展示给模型的 action schema 也是从 `ToolSpec` 自动生成。

## 校验流程

agent runner 每一步执行：

```text
1. 从模型文本中解析 JSON action
2. 转成 ToolCall
3. 根据当前环境的 ToolSpec 校验工具名和参数
4. 校验失败：记录 ToolResult(error=...)，不执行环境 action
5. 校验通过：执行环境 action
6. 把结果记录成 ToolResult
7. 旧 trace 字段和新 canonical 字段同时保存
```

这让当前 JSON action 体系更严格，也让未来 native adapter 更容易接入。

## 和未来 adapter 的关系

主流大模型 adapter：

```text
OpenAI tools/tool_calls
Anthropic tool_use/tool_result
Gemini function declarations/function_call
```

未来都应转换成同一套：

```text
ToolSpec
ToolCall
ToolResult
AgentTrace
```

非主流 agent adapter：

```text
HTTP agent
CLI agent
Python SDK agent
公司内部 agent 平台
```

也只需要输出同样的 canonical trace。这样 EvaluationClaw 的 scoring/reporting 不需要理解每种 agent 的私有协议。

## 已实现的主流模型 adapter

当前代码位置：`evalclaw/protocols/tool_adapters.py`。

GPT / OpenAI-compatible adapter：

- `openai_tool_spec` / `openai_tools`：把 `ToolSpec` 转换成 OpenAI/DeepSeek 可用的 `tools=[{"type":"function", ...}]` 格式。
- `openai_tool_call_to_evalclaw`：把 OpenAI Chat Completions 的 `tool_calls`，以及 OpenAI Responses API 的 `function_call` 输出项，转换成 EvaluationClaw 的 `ToolCall`。
- `openai_tool_calls_from_message` / `openai_tool_calls_from_response`：从 provider 原生 message 或 response 中抽取工具调用。
- `evalclaw_tool_result_to_openai`：把 `ToolResult` 转换成 Chat Completions 下一轮需要的 `{"role":"tool", ...}` 消息。
- `evalclaw_tool_result_to_openai_response_input`：把 `ToolResult` 转换成 Responses API 下一轮需要的 `function_call_output` 项。

DeepSeek 当前按 OpenAI-compatible 协议处理，因此不需要独立 adapter。

Claude / Anthropic adapter：

- `anthropic_tool_spec` / `anthropic_tools`：把 `ToolSpec` 转换成 Claude Messages API 的 `tools=[{"name":..., "input_schema":...}]` 格式。
- `anthropic_tool_use_to_evalclaw`：把 Claude 返回的 `tool_use` content block 转换成 EvaluationClaw 的 `ToolCall`。
- `anthropic_tool_calls_from_response`：从 Claude Messages API response 的 `content` blocks 中抽取所有 `tool_use`。
- `evalclaw_tool_result_to_anthropic`：把 `ToolResult` 转换成 Claude 下一轮 user message content 中的 `tool_result` block。

Gemini native adapter：

- `gemini_function_declaration` / `gemini_tools`：把 `ToolSpec` 转换成 Gemini 的 `functionDeclarations` 格式。
- `gemini_function_call_to_evalclaw`：把 Gemini 返回的 `functionCall` 转换成 EvaluationClaw 的 `ToolCall`。
- `gemini_tool_calls_from_response`：从 Gemini response 的 `function_calls` 或 `candidates[0].content.parts` 中抽取函数调用。
- `evalclaw_tool_result_to_gemini`：把 `ToolResult` 转换成 Gemini 下一轮需要的 `functionResponse` part。

Mistral adapter：

- Mistral 当前工具格式与 OpenAI function tools 很接近，因此 `mistral_tool_spec`、`mistral_tool_call_to_evalclaw`、`evalclaw_tool_result_to_mistral` 复用 OpenAI-like 转换。

Cohere v2 adapter：

- Cohere v2 的 tool definition 和 tool call 也是 OpenAI-like 结构，因此 `cohere_tool_spec` 和 `cohere_tool_call_to_evalclaw` 复用 OpenAI-like 转换。
- `cohere_tool_calls_from_response` 会优先从 `response.message.tool_calls` 抽取工具调用。
- `evalclaw_tool_result_to_cohere` 会把 `ToolResult` 转换成 Cohere v2 tool message。

AWS Bedrock Converse adapter：

- `bedrock_tool_spec` / `bedrock_tools`：把 `ToolSpec` 转换成 Bedrock Converse 的 `toolSpec` 格式。
- `bedrock_tool_use_to_evalclaw`：把 Bedrock 返回的 `toolUse` block 转换成 EvaluationClaw 的 `ToolCall`。
- `bedrock_tool_calls_from_response`：从 `response.output.message.content` 中抽取 `toolUse`。
- `evalclaw_tool_result_to_bedrock`：把 `ToolResult` 转换成 Bedrock 下一轮需要的 `toolResult` block。

MCP adapter：

- MCP 不是模型原生输出 `tool_call` 的格式，而是 agent/工具服务器之间的工具协议；很多非主流 agent 可能通过 MCP 暴露工具。
- `mcp_tool_spec` / `mcp_tools` / `mcp_tools_list_result`：把 `ToolSpec` 转换成 MCP `tools/list` 可返回的工具描述。
- `mcp_tool_call_to_evalclaw`：把 MCP `tools/call` JSON-RPC request 或 `params` 对象转换成 EvaluationClaw 的 `ToolCall`。
- `evalclaw_tool_result_to_mcp`：把 `ToolResult` 转换成 MCP `tools/call` result。

分发辅助函数：

- `tool_adapter_for_target(target)` 会根据 `TargetModelConfig.provider/model` 返回 `"openai"`、`"anthropic"`、`"gemini"`、`"mistral"`、`"cohere"`、`"bedrock"`、`"mcp"` 或 `None`。
- `openai`、`openai_compatible`、`deepseek-*`、`gpt-*`、`o*` 使用 OpenAI adapter。
- `anthropic`、`claude*` 使用 Anthropic adapter。
- `gemini` / `google` / `gemini*` 使用 Gemini adapter。
- `mistral` / `mistral-*` / `codestral-*` 使用 Mistral adapter。
- `cohere` / `command-*` / `c4ai-*` 使用 Cohere adapter。
- `bedrock` / `aws_bedrock` 使用 Bedrock Converse adapter。
- `mcp` 使用 MCP adapter。
