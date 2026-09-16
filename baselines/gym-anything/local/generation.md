`generate.py` 是官方 Propose-and-Amplify 流程的外部入口，新增 `--requirement-file` 参数，读取 UTF-8 评测需求。用户的五条原始需求保存在 `requirements/goal_1.txt` 至 `goal_5.txt`。

需求在两个位置传入模型：提题时使用 Claude Code 的 `--append-system-prompt`，各次会话调用均可见；扩增时追加到官方任务描述生成提示的末尾。文件生成阶段沿用官方保存的扩增对话，因此继承需求。两处都只添加标题和需求原文，不添加我们设计的题目、解法或评分规则。

入口在当前进程内临时包装官方调用，并为任务描述生成子进程加载相同的提示适配。官方源码文件不修改，示例选择、阶段顺序、文件生成和提取逻辑由官方实现执行。

在 `gym-anything/` 下查看参数：

```bash
.venv/bin/python local/generate.py --help
```

使用本机 DeepSeek 配置运行某个环境的提题阶段：

```bash
.venv/bin/python local/generate.py \
  --deepseek \
  --requirement-file local/requirements/goal_1.txt \
  --software ERPNext --env-dir erpnext_env \
  --stage propose --output-dir local/outputs/erpnext_goal_1
```

`--stage amplify` 执行扩增和文件生成，`--stage extract` 提取任务文件，`--stage all` 执行完整流程。继续同一次运行时使用相同的需求文件和输出目录。每次保存 `requirement.txt` 和 `input_<stage>.json`；同一输出目录不接受不同需求。未指定输出目录时，记录放在 `local/outputs/generation_<UTC时间>/`。生成的任务仍写入官方参数指定的环境目录。

`--deepseek` 从 `local/.env` 读取 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`，通过 `https://api.deepseek.com/anthropic` 为提题 CLI 和扩增子进程配置服务，两个阶段默认使用 `deepseek-flash`。显式传入的 `--proposer-model` 和 `--amplifier-model` 优先。凭据仅通过进程环境传递，不写入运行配置；未指定 `--deepseek` 时使用官方模型与服务配置方式。

本机依赖锁定 Anthropic SDK 0.84.0，兼容官方 `messages.stream()` 调用及其 `temperature` 参数。官方客户端继续原样发送 `temperature=1.0`、`max_tokens=40000`、开启 thinking 且 `budget_tokens=16384`，并沿用流式解析、对话保存和重试逻辑。没有删减请求参数或改写官方 API 调用代码。

官方提题默认 5 道、扩增默认 75 道。本轮每软件生成 5 道种子题，共 50 道，使用 `seed_batch.py` 并行执行；配置与产物位置见 `seed_experiment.md`。

此次验证覆盖完整官方阶段调度下的需求传递、扩增提示保留、原始需求快照，以及空需求和混用需求的拒绝行为。模型调用和外部进程执行在测试中替换，不生成实验题目。

2026-09-16 回归结果：313 passed、22 skipped、7 subtests passed，包含新增的 4 项需求接入测试；日志见 `outputs/requirement-tests.log`。

API 接入验证：官方客户端经 DeepSeek 服务完成真实流式请求，并在独立进程中恢复保存的对话继续调用；正文、thinking 和上下文传递均通过检查，记录见 [API 检查结果](outputs/api_compat/result.json)。SDK 请求超时 90 秒，验证时禁用重试；Python 与 NumPy 种子为 42，远端 Anthropic 协议不暴露 seed 参数。回归结果为 315 passed、22 skipped、7 subtests passed，日志见 `outputs/api_compat/pytest.log`。这项检查没有生成正式 benchmark。
