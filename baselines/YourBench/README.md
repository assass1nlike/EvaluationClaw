固定官方 YourBench v0.9，commit `46807647f99bd954747257a3db6a31a12f50b820`。源码在 `upstream/`，按上游 `uv.lock` 安装 Python 3.12.13 环境。

在 `baselines/` 下运行：

```bash
bash YourBench/setup.sh
bash YourBench/run.sh
```

默认读取上游自带的 `upstream/example/default_example/data/yourbench_arxiv_paper.pdf`。使用自己的文档时，先放进 `YourBench/` 内，再运行：

```bash
bash YourBench/run.sh --source YourBench/data
```

模型配置在 `config.yaml`，本机使用 `deepseek-flash`，接口为 `https://api.deepseek.com`。凭据保存在权限为 0600 的 `.env`，不提交 Git。该文件包含 `YOURBENCH_API_KEY`、`YOURBENCH_BASE_URL` 和 `YOURBENCH_MODEL`。

运行调用官方文档读取、分层摘要、分块、单跳出题、多跳出题、去重、评测集导出和引用评分流程。`schema.py` 直接引用上游开放式问答结构，通过官方配置接口提供给两个出题阶段。去重依据规范化问题文本；引用阶段仅计算分数。所有结果保存到本机。

每次运行建立独立的 `runs/<UTC时间>/`：

- `config.yaml`：含默认值和原始提示词的完整配置，密钥替换为环境变量名。
- `metadata.json`：源码版本、输入文件 SHA-256 和种子。
- `dataset/`、`jsonl/`：各阶段数据；最终问答、原文、引用和引用分数在 `jsonl/prepared_lighteval.jsonl`。
- `responses.jsonl`、`logs/`：模型请求和响应，以及上游运行日志。token 数为上游 tokenizer 估算。
- `verification.json`：非空产物、摘要、问答必需字段、多跳来源和导出一致性的验证结果；验证失败时进程退出码非零。

Python、NumPy 和请求 seed 为 42，temperature 为 0.7，每次输出最多 16384 tokens，并发 2，关闭 thinking。摘要块上限 32768 tokens、重叠 512；出题块上限 8192 tokens，沿用上游实际实现的零重叠；多跳组合使用 2–5 个块，数量系数为 1。上游请求超时为 300 秒，最多尝试 12 次。完整参数见每次运行的配置。

远程服务是否执行 seed 由服务方决定；上游随机生成文档 UUID，并据此抽取多跳组合，因此另存了实际分块及组合。环境、缓存、临时目录及产物均位于本目录。

此入口验证评测集生成；被测模型作答和 EvaluationClaw 的 LaaJ 评分尚未接入。运行记录见 [exps.md](exps.md)。

2026-09-16 验证：上游 91 项测试通过；真实运行生成 146 条问答（单跳 91、多跳 55），全部包含答案、原文引用和来源块，数据集与 JSONL 一致。结果在 [runs/20260916T060527508811Z/](runs/20260916T060527508811Z/)，检查结果见其中的 `verification.json`。引用对原文的平均匹配分数为 96.39/100，最低 47；这是文本匹配分数，不代表答案正确率。

上游导出阶段会探测未启用的跨文档子集并尝试读取 Hub，产生一次仓库不存在日志后继续处理本地数据。上游汇总调用 CSV 重复累计用量；本机 `verification.json` 按 `responses.jsonl` 中的实际调用统计。
