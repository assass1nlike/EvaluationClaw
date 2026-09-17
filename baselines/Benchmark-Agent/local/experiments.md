2026-09-16：同时启动三个独立的官方 Benchmark-Agent 流程，需求见 `user_queries/knowledge_50.json`、`user_queries/data_analysis_50.json`、`user_queries/instruction_following_50.json`，各目标 50 题。框架调用并发为 3，API 并发沿用官方默认值。生成结果以官方验证实际通过数量为准，不补题。

本批次已在转换阶段停止，尚未完成生成或自测。实测发现纯工具规划器硬编码 `gpt-5.1`，绕过模型配置，数据分析与指令遵循运行产生了失败调用；已将该规划器和网页检索工具的默认模型改为读取配置，保留显式模型覆盖和原有工具参数。随后单独测试 DeepSeek 原生网页检索，接口返回 HTTP 400：`tools[0].type: unknown variant web_search, expected function`。继续实验需要决定是否为网页检索使用支持该能力的接口，或接受官方检索失败处理后继续纯 DeepSeek 流程。

停止前已记录 token：知识 793,633，数据分析 1,444,437，指令遵循 1,055,321，合计 3,293,391；另有 135 次 gpt-5.1 失败调用无用量返回。终止时的在途请求可能未记录用量，因此这些数值不是完整账单。进程被终止，原始 token 汇总保留 `running` 状态，不能误解为仍在运行；批次状态见 `batch.json`。接口能力探测单独记在批次目录的 `setup_probe/`。

生成、转换、验证、被测模型与开放题判分均使用 `openai/deepseek-flash`，接口为 `https://api.deepseek.com`，模型设置见 `utils/resources/models.yaml`。生成阶段所有提示词、随机性和参数沿用仓库当前版本；没有额外设置随机种子，因此不保证逐题可复现。数据池为 HF `General-Level/General-Bench-Openset` 的 `nlp` 和 `image/comprehension`，336 个数据集，资源清单为 `utils/resources/dataset_cards.yaml`。

启动方式（使用 `benchmaker-baseline` 环境）：

```bash
python local/run_batch.py cache/batch_20260916_deepseek_flash_50
```

缓存根目录为 `cache/batch_20260916_deepseek_flash_50/`。`batch.json` 记录实际进程与退出状态，每个需求的官方产物保存在 `user_queries/<需求名>/`。各进程的独立完整终端日志保存在批次根目录。生成 token 统计位于各需求的 `token_usage/`。

自测是独立后处理，不属于官方生成算法：全部生成任务结束后并行评测三个结果集。被测模型只接收导出题目的 `input`；对于 `choice` 子任务要求只输出选项字母并严格匹配参考字母，其他类型按题目指令自然回答，再使用独立的同模型请求检查答案正确性和约束满足情况。自测 temperature=0、max_tokens=12000、thinking 使用服务商默认值，每个需求使用 10 个工作线程，无额外全局 API 限制；脚本不额外重试失败请求。截断响应、调用失败和无法解析的判分单独计数，不伪装成已评分题目。

自测提示词、配置、逐题响应、判分理由、汇总分别保存在 `selftest/config.json`、`selftest/items/`、`selftest/results.json`、`selftest/summary.json`；回答与判分的 token 消耗分别位于 `selftest/answering/` 和 `selftest/judging/`。开放题结果属于同模型判分，没有独立人工核验。token 汇总只包括 API 返回且已记录的用量，未知消耗单列。
