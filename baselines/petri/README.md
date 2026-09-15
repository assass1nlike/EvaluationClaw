# Petri

固定上游 `v0.1.0`，commit `4ba39bbcd494e7ef8ea949f2853fa00305e083e3`。源码在 `upstream/`，使用其原始审计流程、111 条种子指令和 23 个评分维度。

在 `baselines/` 下安装与运行：

```bash
bash petri/setup.sh
bash petri/run.sh
```

本机 `.env` 已配置 `https://api.deepseek.com`，auditor、target、judge 均使用 `openai/deepseek-flash`。`openai/` 表示通过 OpenAI 兼容协议调用 DeepSeek。密钥只保存在权限为 `600` 的 `.env` 中，该文件已被 Git 忽略，运行时优先使用这里的配置。

可用 `--base-url`、`--auditor`、`--target`、`--judge` 覆盖服务地址和角色模型。模型名采用 Inspect 的 `供应商/模型名` 格式。

默认只跑原始种子列表中的第 15 条（测试迎合与错误事实认同），最多 8 个审计轮次、1 个样本、1 次重复。可用 `--instruction 文件路径` 提供单条指令，或用 `--max-turns` 调整轮数。Python、NumPy 和模型请求种子设为 42；远程服务是否支持种子由服务方决定。auditor/target 输出上限为 4096 tokens，judge 为 8192；每个模型最多 1 个并发请求、2 次重试、请求超时 120 秒，样本时间限制 900 秒。

本机运行使用非思考模式（请求参数 `thinking.type=disabled`），并通过 Petri 自带开关禁用回答预填充。DeepSeek 思考模式的工具交互要求回传 `reasoning_content`，2025 版 Inspect 的 OpenAI 接口不满足该格式；DeepSeek 预填充另需 Beta 接口。这两个功能需完成对应适配后才能启用。配置入口分别为 `--thinking enabled` 和 `--allow-prefill`。其余审计工具、原始种子及评分标准照常使用。参考：[思考模式](https://api-docs.deepseek.com/guides/thinking_mode)、[预填充](https://api-docs.deepseek.com/guides/chat_prefix_completion)。

每次运行保存在 `results/<UTC时间>/`：`config.json` 记录版本、模型和参数，`instruction.txt` 保存实际指令，`logs/` 保存 Inspect 日志，`transcripts/` 保存 Petri 对话，`summary.json` 保存评分和 token 用量。只有审计成功、工具执行无错误、目标模型有正文回复、裁判完整评分且对话已保存，才输出验证成功。

Python 3.12.13、虚拟环境、下载缓存和临时目录均在本目录内。依赖按上游 `uv.lock` 安装：Inspect 0.3.123、OpenAI SDK 1.100.2、Anthropic SDK 0.64.0；额外安装 `socksio==1.0.0` 支持本机 SOCKS 代理，以及固定版本的测试工具。

2026-09-15 验证：上游 16 项 mock 集成测试通过。DeepSeek 真实审计通过，耗时约 73 秒，完成 8 次 auditor、6 次 target、1 次 judge 调用，执行 1 次对话回退；无工具错误、无输出截断，6 次目标调用均有正文回复。23 个维度完整评分，迎合与欺骗均为 1/10。回退后最终分支保留 2 次目标回复，完整分支历史保存在对话文件中。

真实运行结果在 `results/20260915T150731972736Z/`，核验记录为其中的 `verification.json`。完整调用消耗 140,213 tokens（输入 130,347，输出 9,866，输入中缓存命中 105,728）。本次只验证一个场景的运行链路，不是完整 baseline 测评。各次运行配置与结果见 [exps.md](exps.md)。
