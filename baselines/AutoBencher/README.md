AutoBencher 官方仓库：https://github.com/XiangLi1999/AutoBencher ，固定提交 `a05be9f1f776e4658de77e28c6bf22606cea01ab`。源码在 `upstream/`，本地启动和 API 转发位于当前目录。

已用 `deepseek-flash` 完成 history 两轮运行，共 450 题，出题、作答、判分及反馈迭代均通过验证。第一轮 201/225 正确（89.33%），第二轮 212/225 正确（94.22%）；两轮均高于设定的 10%–30% 目标准确率。结果在 [runs/20260917T130416029536Z/](runs/20260917T130416029536Z/)，核验汇总为其中的 `verification.json`。

经用户确认，已应用三个补丁：`patches/wikipedia-user-agent.patch` 设置应用标识，`patches/wikipedia-retries.patch` 复用连接，设置连接与读取等待超时 30 秒、最多 5 次重试。`patches/wikipedia-search-encoding.patch` 使用标准查询参数编码，完整传递含 `&` 等特殊字符的维基标题。核心出题、筛选、作答和判分逻辑沿用官方实现。

模型和凭据已保存在 `.env`，文件权限为 0600，已被 Git 忽略。配置格式见 `.env.example`。重新运行：

```bash
cd /data1/zangyihe/EvaluationClaw/baselines/AutoBencher
.venv/bin/python -u run.py
```

默认使用 `deepseek-flash` 执行出题、作答和判分，主题为 history，迭代 2 轮，目标正确率为 0.1–0.3，seed 为 42，开启 thinking。入口通过官方命令行执行主题生成、维基候选检索、访问量排序、资料出题、模型作答、判分和反馈迭代；题量由原始流程决定。`--iterations`、`--theme` 和 `--acc-target` 可调整对应官方参数。网络中断后可运行 `.venv/bin/python -u run.py --resume runs/<UTC时间>`，沿用已保存配置及官方缓存；入口只清理未写入内容的主题题目文件，续跑时间及实际源码差异保存在 `resumes.jsonl`。

官方代码只将 `gpt*` 模型名路由到 OpenAI 兼容接口。本地转发服务将 `gpt-autobencher` 映射为实际模型名，附加 seed 和供应商参数，并记录请求与响应；提示词、温度和响应正文沿用官方实现，输出上限可通过 extra_body.max_tokens 覆盖。服务仅监听本机回环地址，单请求超时 300 秒；传输错误及 HTTP 408/409/429/5xx 最多尝试 3 次，间隔 1、2 秒，官方 SDK 和调用层的重试仍保留。

独立被测模型通过 `--test-taker` JSON 或批次配置的 test_taker 指定，字段为 model、base_url、api_key_env、extra_body；被测调用使用独立别名和供应商参数，出题与裁判继续使用主模型。续跑自动恢复两套配置。八需求八轮的 DeepSeek 出题/裁判、Qwen 作答配置为 `configs/eight-needs-qwen-high.json`，运行 `.venv/bin/python -u batch.py configs/eight-needs-qwen-high.json`。DeepSeek thinking/high、max_tokens=300000；Qwen thinking/xhigh、max_tokens=131072；八组同时运行，下一轮选题使用 Qwen 的评测结果。

每次运行写入独立的 `runs/<UTC时间>/`：`config.json` 保存参数、源码版本和源码差异，`requests.jsonl` 保存实际模型请求、回答和 token 用量。官方题目、作答和判分结果分别为 `wiki.<轮次>.KI_questions.json`、`wiki.<轮次>.test_taker_inference.json`、`wiki.<轮次>.compare_answers.json`。成功完成后，`verification.json` 记录逐轮题量、准确率、用量和输出截断数。

Python、NumPy、PyTorch 和 Python 哈希种子固定为 42，远程请求也传入 seed；服务端不保证确定性。上游以实时维基页面为资料源，访问量时间窗为 2020-04-01 至 2023-04-07。本次目标是本机流程验证，不是论文结果复现。

重建环境运行 `bash setup.sh`。Python 3.10 环境使用上游指定依赖，另补齐 HELM、datasets 和兼容的间接依赖；完整版本在 `requirements.lock`。PyTorch 使用 CPU 构建，模型推理通过远程 API 完成。安装缓存、虚拟环境和产物均在本目录内。运行记录见 `exps.md`。

四个需求的并行配置在 `configs/four-needs.json`。在当前目录运行 `.venv/bin/python -u batch.py configs/four-needs.json`，每个需求启动独立进程，各跑两轮。批次目录保存各任务日志、独立产物及 `status.json`。

已执行批次 [runs/batch-20260917T153233865694Z/](runs/batch-20260917T153233865694Z/) 共两轮：第一轮 840 题，第二轮 870 题，累计 1,710 题。出题、被测模型和裁判均为 deepseek-flash。第二轮选题使用第一轮逐主题正确率，第一轮产物未改写。

mathematics、computer-science 两轮完整核验通过。knowledge 第一轮与 reasoning 第二轮各有一条裁判未给出判定，保留官方原始结果和核验失败状态。逐轮题量、准确率、用量及异常回复见批次目录 `summary.json`；单轮配置和汇总快照位于 `archive/iterations-1/`。

在已有单轮结果上追加第二轮：

```bash
.venv/bin/python -u batch.py configs/four-needs.json --resume runs/batch-20260917T153233865694Z
```

单个任务使用 `run.py --resume <目录> --iterations 2` 将总轮数扩展到两轮；不指定轮数则沿用保存的配置。扩展时留存旧配置和核验结果，复用官方题目、作答和判分缓存。

新增数据分析、指令遵循、长上下文、多语言四需求配置为 `configs/four-more-needs.json`，运行命令为 `.venv/bin/python -u batch.py configs/four-more-needs.json`。四组已并行完成三轮，被测模型均为 deepseek-flash，共 2,445 题。逐轮结果、反馈核验、用量与费用见 [三轮批次汇总](runs/batch-20260917T160537909079Z/summary.json)，复现参数见 `exps.md`。指令遵循与长上下文组第二轮各有一条无效判分，原始产物及最终核验失败状态均已保留。

新实验默认开启 thinking：DeepSeek 使用 `thinking.type=enabled`，Qwen 使用 `enable_thinking=true`，GPT 使用 `reasoning_effort=high`。这些设置同时覆盖出题、作答和裁判的相应配置；模型供应商的实际行为记录在请求响应日志中。输出 token 上限沿用现有配置。已完成实验的配置快照保存在各运行目录；固定题集评测续跑应使用该目录的 `config.json`，例如 `.venv/bin/python -u evaluate_fixed.py runs/<评测目录>/config.json --resume runs/<评测目录>`。
