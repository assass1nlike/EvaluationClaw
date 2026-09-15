附录 B 选择 Benchmark-Agent 与 YourBench；两者均在全部 8 个完整 user query 上实验，不按领域分配。以下是截至 2026-09-15 的论文和公开实现核查，尚未运行生成实验。

| 框架 | 选择依据 | 实际边界 |
|---|---|---|
| [Benchmark-Agent](https://arxiv.org/abs/2606.06462)，2026 | 直接输入自然语言需求，自动拆分子任务、从数据集寻找依据、制定转换计划、分配样本并验证。论文附录 A 给出数学证明检查、多语言、跨轮对话和代码推理案例。 | 依赖可用数据集与转换工具；代码问答、预写对话不等于可执行代码评测或真实长程交互。 |
| [YourBench](https://arxiv.org/abs/2504.01833)，COLM 2025 | 从任意领域文档生成带答案和引用的评测题，支持跨片段推理、自定义生成指令与输出 schema；材料与目标都能配置，适合全部 8 类的统一比较。 | 原论文主要验证文档问答；约束遵循、代码执行、长任务和低资源语言的完整支持不能由可配置性推出。引用匹配也不证明答案正确。 |

Benchmark-Agent 的[官方实现](https://github.com/Shiyun-x/Benchmark-Agent)、[输入数据说明](https://github.com/Shiyun-x/Benchmark-Agent/blob/3ceca326c33b100291a9b397c8a275d2eb5b411d/data/data.md)和[工具说明](https://github.com/Shiyun-x/Benchmark-Agent/blob/3ceca326c33b100291a9b397c8a275d2eb5b411d/tools/executor_tools/tools.md)提供数据注册、生成流程和工具边界；本次核查版本为 `3ceca326c33b100291a9b397c8a275d2eb5b411d`。工具说明指出部分音频/图像工具尚为占位实现，因此此次仅按附录 B 的文本需求讨论支持。

YourBench 使用 [huggingface/yourbench](https://github.com/huggingface/yourbench) 主仓库，而不是作者的镜像；核查版本为 `3502e474bb260cf33e9a1219ccd62054f1de23e1`。[配置说明](https://github.com/huggingface/yourbench/blob/3502e474bb260cf33e9a1219ccd62054f1de23e1/docs/CONFIGURATION.md)、[输出格式说明](https://github.com/huggingface/yourbench/blob/3502e474bb260cf33e9a1219ccd62054f1de23e1/docs/CUSTOM_SCHEMAS.md)和[多跳生成提示](https://github.com/huggingface/yourbench/blob/3502e474bb260cf33e9a1219ccd62054f1de23e1/yourbench/prompts/question_generation/multi_hop_system_prompt.md)确认了目标配置、结构化输出和跨片段证据组合能力。当前实现比 2025 年论文增加了自然语言配置入口；不能把后续功能当作原论文的实验结论。

检索覆盖 arXiv 的 benchmark construction、benchmark generation、benchmark synthesis、custom evaluation、automated benchmark 等主题及 GitHub 官方仓库。进一步核查后未入选的主要候选：

| 候选 | 未列为本 setting 的两个主 baseline 的原因 |
|---|---|
| [AutoBencher](https://arxiv.org/abs/2407.08351)，ICLR 2025 | 目标驱动的类别优化很相关，但[公开入口](https://github.com/XiangLi1999/AutoBencher)主要为知识、数学和多语言；扩到约束、长输入和软件任务需要更多专门适配。可作为额外消融或补充比较。 |
| [AutoBench](https://arxiv.org/abs/2510.22593)，2025；[CoEval](https://arxiv.org/abs/2606.03650)，2026 | 能跨领域生成任务，但重点是模型轮流出题、作答、互评并形成排名。与独立构建含评分依据的 benchmark 相比，构建与被测模型面板耦合更强。 |
| [InfoSynth](https://arxiv.org/abs/2601.00575)，2026 | 信息论指标和迭代执行验证有价值，但端到端实现聚焦 Python 编码题，不能以推理框架的泛称推断覆盖全部 8 类。 |
| [SciCustom](https://arxiv.org/abs/2605.19357)，ACL 2026 | 根据需求从科学知识体系和大规模数据选择评测，实验主要在化学与医疗，扩展到其余任务需要新的知识体系及数据。 |
| [From Raw Corpora to Domain Benchmarks](https://arxiv.org/abs/2506.07658)，2025 | 通过领域词汇补全衡量知识，任务形态不适合一般推理、约束执行等需求。 |
| [AutoEval Done Right](https://arxiv.org/abs/2403.07008)，2024 | 核心是结合人工与合成标签提高评估统计效率，不是完整的需求驱动 benchmark 构建系统。 |

每项已有 benchmark 直接从原附录 B 的 derivation 来源选取：

| 需求 | 主参照 | 选择理由与范围 |
|---|---|---|
| Knowledge | [MMLU-Pro](https://arxiv.org/abs/2406.01574) | 广泛学科知识及应用，比仅研究生科学的 GPQA 更贴合 broad knowledge。 |
| Reasoning | [LiveBench Reasoning](https://github.com/LiveBench/LiveBench) | 包含逻辑、空间和常识相关推理，以选定 release 的题型和客观评分器为准。 |
| Mathematics | [HLE](https://arxiv.org/abs/2501.14249) 的纯文本数学子集 | 原 derivation 的困难数学参照；固定数学标签并排除含图题。 |
| Computer Science | LiveBench 的 Coding + Agentic Coding | 作为一个 suite 同时提供编码与仓库问题解决；比单纯编程竞赛题更接近复合需求，仍不完整覆盖 AI 理论知识。 |
| Data & Experimental Analysis | LiveBench Data Analysis | 对应主要的数据操作与分析需求；不将其视为完整实验结果解释评测，LAB-Bench 保留为 derivation 来源。 |
| Constraint Following | [IFBench](https://arxiv.org/abs/2507.02833) | 明确强调新型、可验证、分布外约束；官方评测包含 strict/loose accuracy，论文主指标使用 prompt-level loose accuracy。 |
| Long Context & Horizon | [HELM Long Context](https://crfm.stanford.edu/2025/09/29/helm-long-context.html) | 直接对应长输入检索与推理，优先覆盖这项复合需求中的长上下文部分；BrowseComp 保留为长程搜索的来源依据。不能把此参照得分解释为长任务能力。 |
| Multilingual Capability | [SEA-HELM](https://arxiv.org/abs/2502.14301) | 比仅多语言知识选择题更适合覆盖理解、生成及推理；只能对所选东南亚语言作结论。 |

LiveBench 的[更新说明](https://github.com/LiveBench/LiveBench/blob/main/changelog.md)确认：2025-04-25 后编码题不再直接取自 LiveCodeBench，2025-05-30 新增仓库问题解决，2025-10-03 更换 agent scaffold。因此实验必须冻结数据与评分代码，不能混用各期榜单分数。HELM Long Context 官方说明列出的五项为 RULER SQuAD、RULER HotPotQA、∞Bench En.MC、∞Bench En.Sum 和 OpenAI-MRCR；它是已有任务的评测集合，不是独立生成框架。

统一给三个构建系统开放同一初始来源集合，允许其原生流程选择和使用材料；数据卡、文档格式及目标提示适配记入准备成本。参照测试实例及其答案与构建材料隔离。两个 baseline 都报告全部 8 项，不把失败项或未覆盖子能力从平均值中删掉。代码执行、约束验证和长任务协议的人工补充必须明确标成扩展并计入成本。本次选择说明的是可开展比较的生成路径，不声称两个框架已经成功实现全部完整需求。
