从仓库根目录使用已有环境运行。参数由官方入口原样解析：

已发布题集的统一任务转换与LaaJ使用主仓库 `scripts/evaluate_benchmark_agent.py`，输入为固定HF版本的 `benchmark-agent/` 下载目录。转换保留原始JSON输入、作答提示、内嵌选项、严格字母匹配或原模型裁判，以及已有作答判分；不会重跑构题或修改原题。每需求固定seed抽样，默认包含污染检索，接口参数见脚本 `--help`。

```bash
conda activate benchmaker-baseline
python local/run_with_usage.py \
  --topic_id user_queries/user_query_physical_sciences_engineering_smoke \
  --dataset_card_config utils/resources/dataset_cards.yaml \
  --cache_path cache/experiments/ \
  --model_config_path utils/resources/models.yaml
```

本地启动脚本按 `models.yaml` 的 `request_parameters` 注入思考设置，统计 Agent 和工具调用，再运行官方 `main`。DeepSeek 为 thinking enabled、reasoning_effort=high；Luna 为 reasoning.effort=high；Qwen 为 enable_thinking=true、reasoning_effort=high。本地适配层通过 LiteLLM 的原始响应回调保留 DeepSeek 的 reasoning_content，供工具调用续轮原样回传。统计器本身只观察用量；提示词、规划、转换、验证和补题策略沿用官方流程。直接运行 `generate_benchmark.py` 不启用这些本地适配和统计。

DeepSeek 接口不接受 thinking enabled 与 tool_choice=required 的组合，官方设计、匹配、配额 Agent 均使用 required。当前新配置尚不能启动正式构题；将 API 请求改为 auto 会放宽强制工具调用约束，需要明确确认，启动层目前没有进行这种替换。

每次启动独立保存到 `<实际缓存目录>/token_usage/<run_id>/`：

- `calls.jsonl`：每次已返回或抛出异常的调用记录，包含模型、响应 ID、原始 `usage` 和异常类型，不保存密钥、提示词或模型回答。每次调用完成后追加落盘。
- `summary.json`：输入 `prompt_tokens`、输出 `completion_tokens`、合计 `total_tokens`，以及按请求模型的汇总。每次调用完成后更新；重跑同一缓存目录会生成独立统计目录。

Responses API 的 `input_tokens`、`output_tokens` 分别映射到汇总中的输入、输出字段，原始 `usage` 仍原样保存。原生搜索的每次实际请求均记录，不重复统计外层调用；日志包括响应状态、未完成原因、搜索动作与来源、网关返回的 `tool_usage`、密钥的 SHA-256 前 12 位标识、HTTP 错误码及限流响应头。HTTP 成功但被过滤的响应可能有用量；其状态单独记录，不计作传输异常。搜索服务费用不包含在 token 数中，网关返回的搜索请求次数可能与响应中的搜索动作条数不同。

统计包括框架层的重试、验证、自动修正以及后来被拒绝的样本。本地缓存命中不发生模型调用，因此不重复计费。数据卡准备、单独补题和其他进程的调用不属于本次统计。

`reported_tokens` 仅累加 API 返回的用量。思考 token 和服务商缓存命中等明细保存在原始 `usage` 中，不重复加到总量。`calls_with_incomplete_usage` 表示缺失完整用量的调用数（包含无用量的异常）；不能将其理解为零消耗。网络超时、SDK 内部重试等未向调用方暴露的服务商消耗无法准确追溯。流式响应不被读取或改写，因而在本记录器中按缺失用量处理；官方命令使用非流式调用。

记录错误会提示并增加 `logging_errors`，不会中断 baseline。`status=completed` 仅表示官方入口正常返回，不表示生成题数达到目标；`failed` 表示入口抛出异常，强制终止时可能保留 `running`。有未知用量、记录错误或运行中断时，总数不能视为完整账单。

当前网页搜索使用 `gpt-5.6-luna` 和 `https://api.fangcunleap.com/azure-gateway/v1`，密钥从 `.env` 的 `WEB_SEARCH_API_KEY`、`WEB_SEARCH_API_KEY_2`、`WEB_SEARCH_API_KEY_3`、`WEB_SEARCH_API_KEY_4` 读取。正常请求和重试均按进程内线程安全的轮转顺序选择 key，各进程以 PID 错开起点。所有框架进程及主、备用搜索端点共享 8 个 Luna 请求名额，配置为 `web_search_api.global_concurrency=8`，锁文件与占用记录位于 `cache/runtime/luna/`。请求结束或进程退出时释放名额，退避期间不占名额；排队不消耗请求超时或重试预算，排队与退避期间暂停转换阶段的无进展计时。其余阶段使用 DeepSeek 和 `LLM_API_KEY`，不增加全局 API 并发限制，沿用官方工作线程池。

所有已配置的 DeepSeek 调用统一使用 `models.yaml` 中 `max_tokens[openai/deepseek-flash]=300000`，覆盖 Agent、工具、生成、转换、验证、自测回答与判分。该值是推理和最终答案共享的输出上限，不是上下文长度或单独的推理额度。自测将实际预算及思考参数写入其 `config.json`；已有结果不能混用不同配置续跑，应另建实验目录。

DeepSeek 请求超时由同文件的 `request_timeout_seconds[openai/deepseek-flash]=7200` 统一设置，覆盖工具局部的较短超时；自测在 `config.json` 中记录实际值。转换阶段连续无样本完成的终止阈值为 `transform_no_progress_timeout_seconds=86400`（24 小时），也可用 `TRANSFORM_NO_PROGRESS_TIMEOUT_S` 环境变量显式覆盖。这些是客户端等待设置，服务商仍可能提前结束请求。

搜索通过 OpenAI SDK 调用网关的原生 Responses `web_search`，使用原提示词、medium 搜索上下文、强制搜索、180 秒请求超时和 12000 输出 token 上限。网关不接受 Luna 的 temperature 参数，因此省略并采用服务端默认值；本地启动层显式设置 reasoning.effort=high。未完成响应或未实际执行要求的搜索会按调用失败处理。仓库固定的 LiteLLM 1.55.0 无 Responses 支持，补充的代码负责接口转换、凭据选择、429 重试及响应读取，没有自建检索、网页读取或搜索决策。

429 重试配置位于 `models.yaml` 的 `web_search_api`：最多 6 次实际请求；优先遵循 `Retry-After`（秒数或 HTTP 日期）与毫秒形式的服务端等待提示，多个提示取最长；无有效提示时按 2 秒起步的指数退避，指数部分封顶 60 秒，另加 0–1 秒随机间隔。单次调用的请求与退避共用 180 秒重试预算，获取并发名额的排队时间单独扣除；不会为了赶预算而提前重试。明确的额度耗尽错误不重试。SDK 自动重试关闭，外层 JSON 循环不重复重试已耗尽的 429。`stop_on_api_error=true` 时，重试耗尽或其他搜索 API 异常会使受影响运行失败退出并保留缓存，不将基础设施错误作为工具失败反馈规划器；模型内容过滤及 JSON 解析仍沿用既有处理。这些设置只作用于原生搜索。策略参考 [OpenAI 的 429 重试建议](https://developers.openai.com/api/docs/guides/rate-limits#retrying-with-exponential-backoff)。

单独验证已配置的搜索工具并保存用量：

```bash
python local/check_web_search.py --output cache/search_probe \
  --query 'Find an official NASA source explaining why Venus is the hottest planet. Cite its URL.'
```

需要图片上下文时添加 `--image /absolute/path/to/image.png`。

`python local/check_search_keys.py --output cache/search_key_probe` 在固定 4 并发下交错比较单 key／四 key，最多 16 次请求，关闭重试以保留原始限流现象；出现 429 后不继续下一组。报告包括响应头、来源、用量和各组时长。未触发限流只能证明凭据可用，不能证明各 key 拥有独立额度或估算最大吞吐量。

多个需求使用 `python local/run_batch.py <新批次目录> --topics <需求文件名，不含.json> ...` 同时启动，全部生成结束后自动自测成功导出的结果。配置和需求快照位于批次的 `configuration/`，各任务日志及 `batch.json` 位于批次根目录。`python local/audit_run.py <批次目录>` 可查看进度、用量和失败记录。后台运行采用 `nohup` 与独立会话，标准输入接 `/dev/null`，输出写入批次日志；任务不依赖 SSH 会话或对话持续在线。
