从仓库根目录使用已有环境运行。参数由官方入口原样解析：

```bash
conda activate benchmaker-baseline
python local/run_with_usage.py \
  --topic_id user_queries/user_query_physical_sciences_engineering_smoke \
  --dataset_card_config utils/resources/dataset_cards.yaml \
  --cache_path cache/experiments/ \
  --model_config_path utils/resources/models.yaml
```

启动脚本在进程内观察 Agent 和工具的模型调用，随后调用官方 `main`。不修改请求、响应、提示词、重试、缓存、规划、生成、验证或补题策略。直接运行 `generate_benchmark.py` 时不启用统计。

每次启动独立保存到 `<实际缓存目录>/token_usage/<run_id>/`：

- `calls.jsonl`：每次已返回或抛出异常的调用记录，包含模型、响应 ID、原始 `usage` 和异常类型，不保存密钥、提示词或模型回答。每次调用完成后追加落盘。
- `summary.json`：输入 `prompt_tokens`、输出 `completion_tokens`、合计 `total_tokens`，以及按请求模型的汇总。每次调用完成后更新；重跑同一缓存目录会生成独立统计目录。

统计包括框架层的重试、验证、自动修正以及后来被拒绝的样本。本地缓存命中不发生模型调用，因此不重复计费。数据卡准备、单独补题和其他进程的调用不属于本次统计。

`reported_tokens` 仅累加 API 返回的用量。思考 token 和服务商缓存命中等明细保存在原始 `usage` 中，不重复加到总量。`calls_with_incomplete_usage` 表示缺失完整用量的调用数（包含无用量的异常）；不能将其理解为零消耗。网络超时、SDK 内部重试等未向调用方暴露的服务商消耗无法准确追溯。流式响应不被读取或改写，因而在本记录器中按缺失用量处理；官方命令使用非流式调用。

记录错误会提示并增加 `logging_errors`，不会中断 baseline。`status=completed` 仅表示官方入口正常返回，不表示生成题数达到目标；`failed` 表示入口抛出异常，强制终止时可能保留 `running`。有未知用量、记录错误或运行中断时，总数不能视为完整账单。
