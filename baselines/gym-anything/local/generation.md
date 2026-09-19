安全批量生成入口为 `local/isolation/vm/run_batch.py`，每款软件在独立生成 VM 中运行。旧宿主/特权容器批量入口保持禁用。配置与批次记录见 [100 题实验](seed100_experiment.md)。

生成 VM 的 CLI 外部入口对结构化 API 临时错误最多额外重试 3 次，间隔 5 秒：连接中断、408/409/429 和 5xx。恢复同一会话及已有文件，不重复提交最初的批量生成请求；需求和 thinking/high 配置保留。重试计入原阶段 10 小时限额，普通任务失败、认证错误及框架异常不自动重试。每次尝试记录到 `phase_N_attempt_K.jsonl` 和 `api-retries.jsonl`；耗尽后返回最终退出码，官方阶段推进逻辑保持原样。本机制不修改官方源码，也不覆盖截图 MCP 的独立 API 调用。

`generate.py` 是官方 Propose-and-Amplify 流程的外部入口，新增 `--requirement-file` 参数，读取 UTF-8 评测需求。用户的五条原始需求保存在 `requirements/goal_1.txt` 至 `goal_5.txt`。

需求在两个位置传入模型：提题时使用 Claude Code 的 `--append-system-prompt`，各次会话调用均可见；扩增时追加到官方任务描述生成提示的末尾。文件生成阶段沿用官方保存的扩增对话，因此继承需求。两处均添加相同的统一说明和需求原文：以需求中的能力与限制条件为设计目标，使任务情境、初始状态和成功判据能够检验它们；遵循官方构建流程与质量要求，已有软件示例用于参考实现方式，不能替代用户的评测目标。不添加我们设计的题目、解法或评分规则。

入口在当前进程内临时包装官方调用，并为任务描述生成子进程加载相同的提示适配。需求适配不修改官方源码；本轮另将官方提题提示的数量从 5 改为 10，示例选择、阶段顺序、文件生成和提取逻辑仍由官方实现执行。

在 `gym-anything/` 下查看参数：

```bash
.venv/bin/python local/generate.py --help
```

以下单软件命令只在生成 VM 内执行，读取来宾内的 DeepSeek 配置：

```bash
.venv/bin/python local/generate.py \
  --deepseek \
  --requirement-file local/requirements/goal_1.txt \
  --software ERPNext --env-dir erpnext_env \
  --stage propose --output-dir local/outputs/erpnext_goal_1
```

`--stage amplify` 执行扩增和文件生成，`--stage extract` 提取任务文件，`--stage all` 执行完整流程。继续同一次运行时使用相同的需求文件和输出目录。每次保存 `requirement.txt` 和 `input_<stage>.json`；同一输出目录不接受不同需求。未指定输出目录时，记录放在 `local/outputs/generation_<UTC时间>/`。生成的任务仍写入官方参数指定的环境目录。

`--deepseek` 从 `local/.env` 读取 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`，通过 `https://api.deepseek.com/anthropic` 为提题 CLI 和扩增子进程配置服务，两个阶段默认使用 `deepseek-flash`。显式传入的 `--proposer-model` 和 `--amplifier-model` 优先。凭据仅通过进程环境传递，不写入运行配置；未指定 `--deepseek` 时使用官方模型与服务配置方式。

本轮种子构建的四次 Claude Code 调用均加载 `local/deepseek-settings.json`：`alwaysThinkingEnabled=true`、`effortLevel=high`、`CLAUDE_CODE_EFFORT_LEVEL=high`，并显式传入 `--effort high`。Claude Code 2.1.229 实际发送 `thinking.type=adaptive` 和 `output_config.effort=high`；DeepSeek 返回了思考内容并完成工具调用。按 [DeepSeek 参数说明](https://api-docs.deepseek.com/guides/thinking_mode)，Anthropic 协议的 `output_config.effort=high` 对应 OpenAI 协议的 `reasoning_effort=high`。配置不覆盖正常 MCP 发现或官方阶段逻辑。其它 SDK 调用不读取这个 CLI 配置。批量生成的截图 MCP 使用外部入口显式加入 `thinking.type=enabled`、`reasoning_effort=high`，保留官方图像处理、提示、输出解析和 4096 token 上限；本轮不运行扩增。

本机依赖锁定 Anthropic SDK 0.84.0，兼容官方 `messages.stream()` 调用及其 `temperature` 参数。官方客户端继续原样发送 `temperature=1.0`、`max_tokens=40000`、开启 thinking 且 `budget_tokens=16384`，并沿用流式解析、对话保存和重试逻辑。没有删减请求参数或改写官方 API 调用代码。

官方提题原定 5 道，本轮改为每软件 10 道种子题，共 100 道；每阶段超时 10 小时，使用 `isolation/vm/run_batch.py` 最多 10 并行，在各软件独立的文件系统、临时目录、Claude 会话、Docker 和 QEMU 缓存中调用 `seed_batch.py`，仅运行提题。配置与产物位置见 `seed100_experiment.md`。上一轮记录见 `seed_experiment.md`。扩增默认 75 道，本轮不运行。

此次验证覆盖完整官方阶段调度下的需求传递、扩增提示保留、原始需求快照，以及空需求和混用需求的拒绝行为。模型调用和外部进程执行在测试中替换，不生成实验题目。

2026-09-16 回归结果：313 passed、22 skipped、7 subtests passed，包含新增的 4 项需求接入测试；日志见 `outputs/requirement-tests.log`。

API 接入验证：官方客户端经 DeepSeek 服务完成真实流式请求，并在独立进程中恢复保存的对话继续调用；正文、thinking 和上下文传递均通过检查，记录见 [API 检查结果](outputs/api_compat/result.json)。SDK 请求超时 90 秒，验证时禁用重试；Python 与 NumPy 种子为 42，远端 Anthropic 协议不暴露 seed 参数。回归结果为 315 passed、22 skipped、7 subtests passed，日志见 `outputs/api_compat/pytest.log`。这项检查没有生成正式 benchmark。
