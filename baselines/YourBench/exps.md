2026-09-16，本机运行 YourBench v0.9，commit `46807647f99bd954747257a3db6a31a12f50b820`。Python 3.12.13，依赖使用 `upstream/uv.lock`；Hugging Face Hub 0.34.3、datasets 4.0.0、NumPy 2.3.1、aiohttp 3.12.14。上游测试为 91 passed，日志在 `runs/tests.log`。

输入为 `upstream/example/default_example/data/yourbench_arxiv_paper.pdf`，使用完整 PDF，经官方转换后共 132655 字符。模型为 DeepSeek API 的 `deepseek-flash`，地址 `https://api.deepseek.com`，无 HF 模型名。所有模型角色使用同一模型，temperature=0.7、max_tokens=16384、seed=42、thinking.type=disabled、max_concurrent_requests=2；其余模型采样参数由服务方默认。Python random 和 NumPy seed=42，PYTHONHASHSEED=42。上游文档 UUID 随机生成，多跳组合受其影响；实际组合保存于各轮 `jsonl/chunked.jsonl`。

按官方顺序执行 PDF 读取、摘要、分块、单跳和多跳生成、导出、引用评分。摘要块上限 32768 tokens、重叠 512；出题块上限 8192 tokens，实际零重叠，h_min=2、h_max=5、num_multihops_factor=1，不采样单跳块。问答模式为 open-ended，无额外出题指令。引用评分 alpha=0.7、beta=0.3，仅记录分数。tokenizer 为 cl100k_base，请求超时 300 秒，最多 12 次尝试。使用上游原始提示词和规范化文本去重；不进行跨文档出题或问题改写，不上传 Hugging Face。各轮配置保存全部默认参数和提示词，metadata 保存输入 SHA-256。

`runs/20260916T055424816253Z/`：默认 schema 配置的首次链路验证。1 个文档生成 5 个块、4 个多跳组合；最终有 101 条单跳和 47 条多跳问答，但摘要为空且缺少引用，未通过有效性检查，退出码 1。该轮配置和原始问答响应保存在目录内，终端日志为 `console.log`。随后对第一个摘要块执行一次诊断请求，获得可解析的摘要，响应为 `summary_diagnostic.txt`；该诊断调用追加在本轮调用 CSV 中。

`runs/20260916T060527508811Z/`：通过官方 question_schema 配置显式引用上游 OpenEndedQuestion，保持上游源码与提示词不变，重新运行上述完整流程。退出码 0，验证通过。1 个文档、5 个块、4 个多跳组合，摘要非空；生成 91 条单跳和 55 条多跳问答，共 146 条，均有答案、引用和来源块，JSONL 与 Arrow 数据一致。引用对原文匹配分数均值 96.3932/100、最低 47，未按分数删除题目；该分数不用于判断答案是否正确。

这轮共 12 次模型调用：分块摘要 2 次、合并摘要 1 次、单跳 5 次、多跳 4 次。按保存的响应逐次统计，输入约 178359 tokens、输出约 56952 tokens（cl100k_base 估计，不是服务端账单用量），最大单次输出约 11333 tokens。生成与保存耗时约 156 秒。所有模型请求和响应在 `responses.jsonl`，完整配置在 `config.yaml`，检查结果在 `verification.json`，终端日志为 `console.log`。

导出阶段探测未启用的跨文档子集时产生一次 Hugging Face 仓库不存在错误日志，该异常被上游捕获，随后正常导出本地问答。上游汇总调用 CSV 重复计数；以上调用和用量统计来自逐次响应记录。该运行只验证生成链路，不包含被测模型作答、LaaJ 或论文分数复现。
