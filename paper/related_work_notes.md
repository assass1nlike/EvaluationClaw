# LLM Agent Benchmark 自动生成：现有工作综述

整理时间：2026-09。所有条目均经直接核验（论文页 / arXiv 摘要 / GitHub 仓库 / 会议论文集页）。

---

## 0. 这张版图长什么样

如果把"自动造 benchmark"这件事拆开看，决定一个框架性质的其实只有两个问题：**题目从哪来**，以及**什么时候算够了**。现有的工作可以按第一个问题分成五条主线：

| 主线 | 种子是什么 | 代表工作 |
|---|---|---|
| 仓库/环境变异 | 真实代码仓库 | SWE-smith、CLI-Gym |
| 自动策展（非合成） | 真实 issue/PR | SWE-rebench、SWE-bench-Live、Multi-SWE-bench |
| 环境即生成器 | 软件本身 / MCP 规格 / skill 包 | Gym-Anything、Agent-World、Terminal-World |
| 工具/API 规格反推 | API 文档、工具依赖图 | ToolLLM、TaskBench、APIGen |
| 模拟用户与领域仿真 | DB schema + 政策文档 | τ-bench、IntellAgent |

第二条主线（策展）和第一条（合成）性质不同，值得分开理解：策展是**把人工流程自动化**，合成的对象仍然是人类真实写过的 issue；合成是**凭空造出任务**。文献里这两类常被混在一起讲，实际上遇到的困难完全不同。

---

## 关于"框架"与"benchmark 成品"的区分

你问的那个问题很关键，整理如下。判断一个工作能不能叫"自动化 benchmark 生成**框架**"，我用的标准是：**论文的核心贡献是一套可复用的生成流程/方法论，而不仅仅是"我用这套方法造出来了一个 benchmark 然后在上面测了模型"。** 具体说，一个框架应当满足：别人可以拿它来造不同领域/规模的 benchmark，而不必重新设计整个生成过程。

按这个标准，下面是每条主线的分类：

### ✅ 可以称为"自动化 benchmark 生成框架"

- **SWE-smith**：五种变异策略 + Docker 验证流水线，设计为通用的 Python 仓库 → 任务的生产线，不绑定特定仓库。
- **CLI-Gym**：环境逆向（agentic environment inversion）作为一种通用方法，可应用于任何有 gold 环境的场景，不只是那 29 个仓库。
- **Terminal-World**：skill 驱动的四阶段流水线（skill 收集 → 任务生成 → 环境构建 → 轨迹收集），明确设计为可用不同 skill 集合产出不同领域任务的框架。
- **Gym-Anything / CUA-World**：创作 agent + 审计 agent 的造环境流水线，理论上可对任意软件应用，论文用 200 个软件只是一个实例化。
- **Agent-World**：环境–任务发现 + 持续自进化训练的两部分架构，核心是那套诊断 → 定向生成 → 再训练的闭环，不绑定特定工具集。
- **TaskBench / Back-Instruct**：Tool Graph + Back-Instruct 是明确设计为通用框架的——给定任意一组工具，按这个方法就能产出 benchmark 实例。
- **APIGen**：三段验证器链（格式 → 执行 → 语义）+ 种子自举，设计为可接入任意 API 集合的生产框架。
- **ToolAlpaca**：三角色多智能体仿真流水线，理论上可接入任意 API 规格，只是原论文用的是 `public-apis`。
- **IntellAgent**：从 chatbot prompt + DB schema + 工具集自动生成 event 的框架，可以接入不同领域的 schema。
- **AgentFrontier / ZPD Exam**：LKP/MKO ZPD 校准是一个明确的通用方法，作者也专门造了 ZPD Exam 这个自演进 benchmark 实例来展示它。
- **SPADE**：Environment Designer + Reasoning Agent 共演化的 RL 框架，可应用于不同任务域。
- **TaskCraft**：`q = f_q(i_T, R)` 的形式化 + 深度/宽度扩展操作，是通用的工具密集型任务合成框架。
- **TASTE**：工具序列采样 + 迭代难度演化的流水线，设计为可作用于任意工具集。
- **SWE-Mirror**：语义提炼 + 在现有 gym 里重实例化的方法，是通用的"跨仓库迁移"框架。

### ❌ 主要是做出了一个 benchmark 成品，方法论是附带的

- **SWE-rebench**：七阶段自动策展流水线确实存在，但论文的核心贡献是那个按时间戳刷新的 benchmark 本身，而不是"你也可以用这套方法造自己的 SWE-bench"。
- **SWE-bench-Live**：论文贡献是定期从新 GitHub issue 自动更新的 benchmark，没有提供通用的生成方法论。
- **Multi-SWE-bench**：68 位专家标注，策展工具是辅助手段，核心是那 1,632 个实例。
- **SWE-MERA**：类似，季度刷新的动态 benchmark 成品，七阶段流水线服务于这个特定 benchmark。
- **SWE-Synth**：提出了"让 LLM 模拟调试工作流"这一思路，但主要验证的是用这个思路造出来的数据能不能帮助训练，方法论的通用性展示不够。
- **ToolLLM / ToolBench**：DFSDT + 指令反向生成是有方法论的，但论文的核心产出是 ToolBench 这个 benchmark 和 ToolLLM 这个模型，而不是一个开箱即用的 benchmark 生成框架——换一组 API 能否直接套用整个流程是存疑的（尤其 DFSDT 标注依赖 GPT-4 大量调用 RapidAPI，基础设施绑定程度较高）。
- **AnyTool**：核心贡献是分层检索器 + 自反思循环这一 agent 架构，以及修复了 ToolBench 指标的 AnyToolBench，不是一个 benchmark 生成框架。
- **StableToolBench**：修复已有 benchmark 的稳定性，不生成任务。
- **AgentInstruct / AgentTuning**：产出是 AgentInstruct 数据集和 AgentLM 模型，六个环境的选取是一次性决策，不是通用框架。
- **AutoAct**：产出是一套自主 agent 训练方法（PLAN/TOOL/REFLECT 三 agent），任务生成只是 pipeline 中的一步，不是主要贡献。
- **AgentOhana**：核心是 AgentRater + 跨环境数据聚合，不是生成框架。
- **MINT**：从已有数据集过滤，不生成。
- **τ-bench**：benchmark 成品（retail + airline 两个领域的任务），有方法论（状态式评估 + 模拟用户），但核心贡献是这两个具体的 domain，不是一个可以接入任意 domain 的框架。
- **τ²-bench**：如果其组合式任务生成器属实，可能升级到"框架"行列，但目前待读原文确认。
- **SOTOPIA**：benchmark 成品，场景/角色/关系类型的叉积是一次性人工设计，不是框架。
- **Generative Agents**：仿真平台/系统，不是 benchmark 生成框架。
- **AgentVerse / AgentSims**：多智能体仿真平台，场景手工写。
- **LegalBench**：benchmark 成品，IRAC 分类学是人工设计的。
- **OSWorld**：benchmark 成品（人工撰写），评估器是程序化的但任务不是。
- **WebArena**：benchmark 成品（模板 + 人工实例化）。
- **WebVoyager**：benchmark 成品（self-instruct + 人工验证）。
- **Terminal-Bench**：benchmark 成品（人工撰写）。
- **AndroidWorld**：这个有些介于两者之间——116 个模板是人工设计的，但参数化实例化机制可以看作一个轻量的框架（"给定模板，自动生成无限实例"），只是模板本身无法自动产生。
- **TermiGen**：Generator–Critic 循环是有框架意味的，但发布物主要是那批 Docker 环境和轨迹，通用性展示有限。

### ⚠️ 介于两者之间

- **AndroidWorld**：如上，模板级别是人工的，实例级别是程序化的。
- **TermiGen**：有 Generate–Critic 框架意味，但规模和验证都较小。
- **WebArena-Infinity**：创作 agent + 审计 agent 的思路明确是想做框架，但目前只有项目页，10 个环境太少，通用性不够充分展示。
- **TRACE**：如果找到论文，很可能是真正的框架（诊断 → per-capability LoRA 合成），但目前只有 repo。

---

五个子领域的详细情况见下文各节。

---

## 1. 从仓库/环境变异生成

这一族最成熟，架构高度统一：给真实仓库建可执行的 Docker 环境 → 变异使其至少一个原本通过的测试失败 → 从 diff 生成自然语言 issue → 在容器里验证 fail-to-pass。

### 1.1 SWE-smith
- **arXiv:2504.21798**，NeurIPS 2025 Datasets & Benchmarks **Spotlight**。
- 作者：John Yang, Kilian Lieret, Carlos E. Jimenez, Alexander Wettig, Kabir Khandpur, Yanzhe Zhang, Binyuan Hui, Ofir Press, Ludwig Schmidt, Diyi Yang。
- **生成物**：论文报 50k 实例 / 128 个 Python 仓库；GitHub 仓库现在发 **52k 实例、250+ 个 Docker image**——引用时对准自己的快照。
- **机制**：五种策略。LM Modify / LM Rewrite（保留签名与 docstring，让模型重写函数体）/ Procedural Modification（13 个 AST 变异算子）/ **PR Mirroring**（收集已合并的 PR，再让模型把它**撤销**）/ Patch Combination。验证：在 Docker 里应用 diff，重跑全套测试（2 分钟超时），**只在至少一个原本通过的测试转失败时才接受**。
- 有趣的工程点：同一仓库的所有实例**共用一个 Docker image**——125 个 image / 约 290 GB，而 SWE-bench 的 2,294 个实例要 1.2 TB，SWE-Gym 要 6 TB。
- 结果：SWE-agent-LM-32B 在 SWE-bench Verified 上 40.2% Pass@1。
- 作者承认的局限：仅 Python；难度带（5.27–5.72）紧贴 SWE-bench 的 5.01，**并不明显更难**；LM 生成的 issue 文本可能含糊；多故障组合任务可能不对应任何真实用户会报的问题。

### 1.2 CLI-Gym
- **arXiv:2602.10999**（2026-02-11）。华为 + 北京理工大学 + 中科院自动化所。
- 作者：Yusong Lin, Haiyang Wang, Shuzhe Wu, Lue Fan, Feiyang Pan, Sanyuan Zhao, Dandan Tu。
- **核心概念：环境逆向（agentic environment inversion）**。这是这批工作里最有意思的一个想法。论文的类比是这样的：Dockerfile 之于环境，就像 git 历史之于代码仓库——代码任务之所以能大规模自动派生，是因为有 commit 历史可以挖；而环境任务做不到，是因为**环境没有"历史"**。于是它反过来做：从一个全测试通过的 gold 环境出发，让 LLM agent 自由探索并**主动破坏**它——改文件系统、破坏依赖、篡改 locale，甚至直接改 `libsqlite3.so`、`libz.so` 的 ELF 头——直到单元测试失败。有 bug 的状态加上报错信息，就是任务；再由模型生成自然语言 issue。用记忆池保证多样性。
- **规模**：1,655 个任务，来自 29 个 Python 仓库（沿用 SWE-smith 的精选集）。
- 几个漂亮数字：每实例平均 **20.4 个 fail-to-pass / 29.6 个 pass-to-pass 测试**，而 Terminal-Bench 是 7.9 / 0.0；存储 119 GB；生产成本 2.3B tokens，对照的是 Terminal-Bench 的 93 位人类贡献者。任务量约为 Terminal-Bench 1.0/2.0 的 20 倍（80/89 → 1,655）。
- 微调 Qwen3-235B-A22B（LiberCoder）在 Terminal-Bench 1.0 上 **+21.1，到 46.1%**。
- **消融结论值得单独记**：**环境多样性比轨迹数量更关键**（固定 100 条轨迹、增加源仓库数，性能单调上升）；数据量在约 200 条轨迹后**进入平台期**。

### 1.3 SWE-Synth
- arXiv:2504.14757（2025-04，v2 2025-12）。FPT Software AI Center 等。
- 特点是**让 LLM agent 模拟调试工作流**，而不是机械变异：例如把某方法的实现遮起来（论文用的是 pydantic 的 `Base64Encoder`），让模型重新生成——重生成过程会自然产生真实 bug（漏掉 `base64.decodebytes` 外的 `try/except`、`encodebytes` 误用成 `b64encode`）。除了 bug–fix 对，还额外生成**测试用例与结构化修复轨迹**。
- 提升幅度不大：SWE-Bench Lite 15.3% vs 真实数据训练的 13.0%。

### 1.4 一条独立的分支：从环境成本切入
**SWE-Mirror**（arXiv:2509.08724，ByteDance Seed）指出了一个别人少谈的约束：**瓶颈是环境成本，不是任务数量**。gym 与仓库近乎一一对应，每个约 1 GB，所以 10 万实例需要约 100 TB。它的解法是把真实 issue 的语义提炼出来，**在一个已经有可用 gym 的另一个仓库里重新实例化**。结果：40 个仓库、4 种语言、约 100 GB 出 60,671 个任务。作为对照，SWE-rebench 是 20k 任务，SWE-Gym 是 2.4k 任务 / 6 TB。

---

## 2. 自动策展：把人工流程自动化，而不是造题

这一族**不发明任务**，只自动化 SWE-bench 式构造中的人工劳动。理解这个区别很重要。

### 2.1 SWE-rebench
- arXiv:2505.20411，NeurIPS 2025 D&B，全 Nebius 作者。
- **流程**：GitHub Archive（约 21 TB 未压缩）→ 克隆约 32K 仓库 → 把 issue 与解决它的 PR 关联 → 按 permissive license、PR 触及测试、文件改动 1–15 个过滤（约 153,400 个候选）→ Qwen2.5-72B-Instruct 读 README/Dockerfile/setup 产出安装与测试 recipe，并**根据错误日志反复修订** → Buildah 构建容器，要求 fail-then-pass 且无回归 → 一个在 SWE-bench Verified 人工标注上微调过的质量模型预测 issue 清晰度（79%）、复杂度（81%）、测试补丁正确性（67%）。
- 约 **31% 的仓库能配置成功**——也就是说大部分候选被丢掉了。
- **最有价值的结论**：模型在"新鲜"任务上大幅下跌。DeepSeek-V3-0324 从 39.7% 掉到 21.3%，Qwen2.5-72B 从 24.2% 掉到 9.3%，LLaMA-3.3-70B 从 19.6% 掉到 11.2%。这是"旧 benchmark 被污染/过拟合"最直观的量化。

### 2.2 SWE-bench-Live
- arXiv:2505.23419。1,319 个任务，全部来自 2024 年后创建的真实 GitHub issue，93 个仓库。
- 最干净的过拟合数字：OpenHands + Claude 3.7 Sonnet 在它上面 **19.25%**，同一套 scaffold 在 SWE-bench Verified 上 **43.20%**。另外在原 SWE-bench 那 8 个仓库上 22.96%，在 1,103 个从未用过的仓库上 18.89%。

### 2.3 Multi-SWE-bench
- arXiv:2504.02605，ByteDance Seed，NeurIPS 2025。
- 1,632 个实例，覆盖 Java/TS/JS/Go/Rust/C/C++，**68 位专家从 2,456 个候选中标注**。可以理解为"人工瓶颈"的量化基准。
- 语言差距极大：Claude 3.7 Sonnet + OpenHands 在 Python 上解决 52.2%，但 Java 21.9%、Rust 15.9%、C++ 14.7%、C 8.6%、Go 7.5%、JS 5.1%、TS 2.2%。

### 2.4 SWE-MERA
- arXiv:2507.11059，EMNLP 2025 System Demonstrations。季度刷新的动态 benchmark，七阶段流水线，最后一环是 Qwen3-32B 质量评估。
- **注意**：规模数字不一致——arXiv v1 摘要说 300，HF 与 camera-ready 说 728。引用前必须定版本。

---

## 3. 环境即生成器

这一族生成的是**整个环境**，任务随之而来。

### 3.1 Gym-Anything / CUA-World
- **arXiv:2604.06126**（2026-04-07）。CMU。Pranjal Aggarwal, Graham Neubig, Sean Welleck。
- **生成物**：200 个软件应用、**10,000+ 长时限任务**，覆盖美国 22 个 SOC 职业大类全部；另有 CUA-World-Long（200 任务，每应用一个，常需 500+ 步）。
- 最有意思的设计：**把"造环境"本身当作一个多智能体任务**。创作 agent 写 setup 脚本、下载真实数据、配置软件，并**产出正确性的证据**（截图、日志）；一个**独立的审计 agent 只检查证据本身**，不信 agent 的自我声明，对照质量清单验证，发现问题则回传修复。
- 软件选择有经济依据：BLS/BEA 的 GDP 归属 + O*NET 职业档案，894 个职业 / 约 16,600 个软件 → 约 3,400 个可沙箱化 → 约 500 个选中 → 构建 200 个。每个环境归约为三段脚本（install、configure、per-task）+ 一个配置文件。
- 任务生成分两阶段：先用 agentic 交互产生高质量种子任务并**实际跑通**，再由非 agentic 模型放大成大量变体，用 VLM 做语义与视觉过滤。
- 验证手法值得注意：用带**特权信息**的 checklist 式 VLM——比如医学影像任务里，正确答案是数据集里已知的肿瘤位置，被评测的 agent 看不到。
- CUA-World-Long 上通过率 <12%（原 500 步设定下 Gemini 3 Flash 7.5%，加测试时审计 agent 后 11.5% → 14.0%）。蒸馏后的 2B 模型超过 2 倍参数的模型。**到未见过软件的泛化有限：仅 22–27% 的收益可迁移。**
- 作者承认的局限：GDP→软件的归属是 LLM 估计且无人工验证；排除了 macOS/iOS；未对全部任务做人工端到端验证；400+ 并发环境需约 1,600 CPU，复现门槛高。

### 3.2 Agent-World
- **arXiv:2604.18292**（2026-04-20）
- **规模**：1,978 个环境、19,822 个工具，任务平均交互轮次 >15。
- **第一部分：环境–任务发现**。取 2,000+ 个主题锚点，来自三类真实来源——Smithery 上的真实 MCP server 规格、开源工具文档、**工业级 PRD 产品需求文档**。一个配了搜索/浏览/代码编译器/OS 工具的深度研究 agent 从互联网**挖掘真实的主题对齐数据库**，并迭代复杂化其结构。再用代码 agent 为每个环境生成工具接口与单元测试，按三重规则过滤（可编译、测试准确率 >0.5、环境最小有效性）。最后用层次聚类建 20 / 50 / 1978 三级分类体系。
- **任务合成走两条互补路线**：一是**基于工具依赖图的随机游走**（边分强/弱/独立三类，先生成合法调用链，再反向生成自然语言问题，配 LLM 评分 rubric）；二是**程序化任务合成**（直接生成需要复杂控制流的 Python 脚本，再反向出题）。
- **第二部分：持续自进化训练**，多环境 RL（GRPO）+ **诊断 agent**。流程是：每轮训练后从环境池里按分类体系**均衡采样新环境并合成全新评测任务**（避免"刷过的题再考一遍"）→ 让当前轮次模型在新任务上评估 → **诊断 agent 分析失败轨迹、错误分布与环境元信息，定位能力短板** → 输出弱点环境排序与**针对性任务生成指南** → 据此在弱点环境上合成更难的任务，并按需进一步复杂化对应数据库 → 驱动下一轮 RL。
- 论文举的诊断例子细到这种程度："Notion 环境下的二级标题创建出错"。
- **结果**：23 个基准（含 τ²-Bench、BFCL V4、MCP-Mark、ClawEval、SkillsBench）。Agent-World-14B 在 BFCL V4 上 55.8%，反超 685B 的 DeepSeek-V3.2（54.1%）。训练环境数从 10 增到约 2,000，下游性能提升 >20 个百分点。自进化轮次带来单调增益。
- 作者承认的局限：第二轮收益递减，早期轮修的是模式级错误，后期面对长时限残余失败；**诊断 agent 的失败归因可靠性未被验证**；基于图的任务用 LLM judge 打分，其稳健性与偏差**未量化**；**奖励攻击风险未做对抗测试**；无灾难性遗忘分析；工具接受阈值（>0.5）偏低。

### 3.3 Terminal-World
- **arXiv:2605.20876**（2026-05-19/20）。北航 + 北理工 + 爱丁堡等。作者含 Zihao Cheng, Hongru Wang, Zeming Liu, Jeff Z. Pan, Yunhong Wang。
- **生成物**：5,723 个终端环境，每个配一条 skill 引导的教师轨迹。
- **核心想法：把 agent skill 当作合成原语**。所谓 skill 是**人类撰写的指导包**（从 ClawHub、SkillMP 等开源生态收集约 10,000 个，经规则过滤、LLM 打分、流行度筛选后留 1,000 个），每个 skill **同时编码三件事**：要完成什么（what）、何时适用（when，即前置条件/输入/环境状态）、如何执行（how）。由这一个锚点**自顶向下共同派生**出任务指令、可执行环境与教师轨迹——这是它与"从一个种子出发只实例化一个组件"的方法的关键差别。
- 为扩大合成空间，把 skill 组合成 **skill team**（同子类、多角色）与 **skill graph**（跨子类、端到端），并把 skill 与用户 persona 配对。
- 四阶段流水线：skill 收集与组合 → 任务生成（每个 skill-persona 对合成指令、环境蓝图、评估标准、执行指南，用 LLM-as-a-Judge 五维打分过滤）→ 环境构建（多智能体 **Generate–Verify–Repair** 循环产出初始文件、setup 脚本、pytest 验证器，最多 3 轮修复）→ 轨迹收集（DeepSeek-V3.2 + Terminus2，**并给它 skill 派生的执行指南**以免从零探索；成功与失败的轨迹都保留，**SFT 时把指南剥离**）。
- **结果**：用相同教师模型、**仅 1.2% 的训练数据**，Terminal-World-32B 在 Terminal-Bench 2.0 上超 Nemotron-Terminal-32B **+4.5 Pass@1（31.5）**，43.8 Pass@3。平均 **$0.17/轨迹**。8B/14B/32B 三个尺寸在 6 个基准上一致超过基线。
- **两个消融结论很有价值**：把执行指南留在输入里会让性能**变差**（阻止模型学会自主规划）；**移除失败轨迹比单纯减少数据量伤害更大**——因为许多"失败"轨迹里含大量正确的中间步骤与错误恢复场景，**不加区分地惩罚整条失败轨迹是有害的**。
- 作者对既有方法的批评说得很直白：现有方法"从人类定义的种子或 GitHub 仓库出发，实例化一个组件再补全其余"，导致**任务局限于狭窄的种子分布、环境与任务语义错配、轨迹低效**。

### 3.5 AndroidWorld
- arXiv:2405.14573，ICLR 2025。Rawles 等。
- 经典套件里**真正程序化生成**的干净例子。20 个真实 Android 应用上的 116 个程序化任务模板，**起始状态与目标由受控随机种子动态参数化**，所以任务实例数是 ∞（对比表里 WebArena 是 241 个模板、VisualWebArena 314）。
- 每个任务自带初始化、成功检查与 teardown 逻辑，通过 adb **直接改/查设备系统状态**（文件系统、应用 SQLite 数据库、系统设置）而非匹配 UI。
- M3A + GPT-4 Turbo 在 a11y 树上 30.6%，人类 80.0%；SeeAct 15.5%。一个反直觉结果：**纯文本输入优于多模态 Set-of-Mark**（30.6% vs 25.4%）。
- 局限很本质：参数化变化的是**参数**，不是**能力**——你无法要求一个模板集里没表达过的能力。

### 3.6 其他环境合成工作
- **WebArena-Infinity**（无 arXiv，项目页）：让一个 coding agent 写出应用**和它的验证器**，再用 browser-use agent 实际跑，一个**审计 agent 判断每次失败是环境 bug 还是 agent 局限**，并迭代修复。10 个环境、1,260 个任务、约 10 小时与 <$100 每环境。验证器是独立的，通过暴露的 API 校验而非像 WebArena 那样检查渲染页面。
- **OSWorld-MCP**（arXiv:2510.24563）：用自动代码生成流水线**造工具**，158 个工具 / 7 个应用。注意它合成的是工具，不是任务。
- **OSWorld 2.0**（arXiv:2606.29537）：扩的是难度（108 个长时限工作流，500 步下最好成绩 20.6%），不是自动化。
- **TerminalWorld**（arXiv:2605.22535，注意与 3.3 的 Terminal-World 是**两篇不同论文**）：从 80,870 个真实 `asciinema` 终端录像反推出 1,530 个可验证任务——这是从**人类终端行为**而非仓库挖矿的少见变体。
- **TermiGen**（arXiv:2602.07274）：3,500+ 个 Docker 环境 / 420 个 CLI 工具，Generator–Critic 循环含 20% 错误注入。
- **Terminal-Bench**（arXiv:2601.11868）本身是**人工撰写**的：89 个任务从 93 位贡献者提交的 229 个中选出，前沿模型得分 <65%。

---

## 4. 从工具/API 规格反推

这一族的关键反转是：**指令不是先头脑风暴再去找 API 匹配，而是从采样到的 API 组合反向生成**。

### 4.1 ToolLLM / ToolBench
- arXiv:2307.16789，ICLR 2024 spotlight。RapidAPI Hub 上 3,451 个工具 / 16,464 个 API。
- 核心技术 **DFSDT（深度优先搜索决策树）**：把执行当作树，某个节点的提议调用失败或返回无用结果就**回溯**，探索另一个分支。论文指出 ReAct 是 DFSDT 的退化特例。产出约 12,657 条指令、**126,486 条标注解法路径**。
- **一个必须知道的缺陷**：ToolBench 的通过率协议**把不可解查询算作已解决**，所以"暴露更多无关 API 并宣布全都不可解"反而提高分数。这正是 AnyTool 要重构协议的原因。另外约 **55.6% 的 API 后来被发现不稳定**。

### 4.2 AnyTool
- arXiv:2402.04253，ICML 2024。
- 三层分层检索器（meta-agent → category agents → tool agents），写入一个共享的全局 API 池。GPT-4 求解器在 **Give Up 时必须指明哪些 API 函数无关或已损坏**，这个归因喂给**自反思循环**：被标记的 API 从池中剔除并从上下文中清除，检索器自底向上重新激活。4–6 轮收敛，最多 +20% 通过率。
- 最有价值的贡献其实是**修指标**：作者手工审计 ToolBench，只保留真正能被池内 API 解决的查询，提出 AnyToolBench（400 实例）。**任何与原始 ToolBench 通过率的比较都是不可比的。**
- 一个没有被 instrumented 的失败模式：反思质量完全依赖求解器自我报告的"无关 API"归因是否诚实——一个把自己的规划失败甩锅给检索器的模型，会**错误地剔除有用工具**。

### 4.3 TaskBench / Back-Instruct
- arXiv:2311.18760。
- **Tool Graph**：工具为节点，边分两类——**资源依赖**（一个工具的输出类型匹配另一个的输入类型）与**时序约束**。按 **node（单工具）/ chain（顺序）/ DAG（多依赖）** 三种拓扑采样子图，然后 **Back-Instruct**：不是收集指令，而是**从采样的子图反向生成**用户指令、任务步骤与工具调用图，最后填参数。
- 质量控制：规则式 critic 过滤约 15%，LLM critic 过滤约 23%，再人工核验。最终 28,271 个样本。
- **一组很好用的对比数字**：Back-Instruct 在自然度上 **3.89 vs Self-Instruct 的 2.18**，复杂度 **4.01 vs 2.01**。即"依 spec 反向生成"明显优于"凭空头脑风暴指令"。另外 benchmark 与人类判断的 Kendall's τ ≈ 0.89。
- 局限：边预测比节点预测难约 30 个 F1 点。DAG 拓扑确实产出难题，但**不清楚产出的是判别性强的题，还是仅仅更长的题**。无执行接地，参数正确性是判出来的不是跑出来的。

### 4.4 APIGen
- arXiv:2406.18518，NeurIPS 2024。
- 最干净的三段验证器链，而且利用了"**函数调用可执行、因此正确性可机械检查**"这一事实：
  1. **格式检查器**——JSON 合法、函数名与参数在给定库中存在（抓幻觉函数）。
  2. **执行检查器**——Python 函数在子进程里导入运行，REST API 真的调用；类型错误、坏参数、超时、语法错误一律丢弃。
  3. **语义检查器**——第二个 LLM 判断执行**结果**是否匹配查询意图。
- 通过三重验证的数据**回流作为后续轮次的种子样本**。
- 局限（作者自己说的）：只支持 REST + Python，**只做单轮生成**，无多轮或有状态任务。语义检查器仍是 LLM，也就是说唯一真正非机械的关卡，最可能漂移。
- 一个批评值得记：**自举循环制造自我强化的分布**——容易通过验证的种子会生成更多像自己的种子，这是风格分布随轮次收窄的合理机制。

### 4.5 其他工具合成工作
- **ToolAlpaca**（arXiv:2306.05301）：从 `public-apis` 仓库（1,400+ API）出发，用**三角色多智能体仿真**——user agent 下指令、tool executor agent 编造真实感 API 响应、assistant agent 调用函数并处理错误。426 个工具、3,938 个实例。局限：工具响应是 **LLM 模拟的、非真实执行**；由于同一模型族既写指令又写响应，**连贯性与正确性被混淆**；人工验证只覆盖约 2.5%（100/3,938）。
- **Seal-Tools**（arXiv:2405.08355，NLPCC 2024）：self-instruct **连工具本身一起合成**，强调嵌套/多工具实例与**严格格式控制**。（注意：它不是 "schema-free"，恰恰相反。）结果很有意思：GPT-4 的 Format ACC 高达 97.12，但 Param F1 只有 73.48——**格式合规已经接近饱和，几乎没有区分度**。
- **ToolACE**（arXiv:2409.00920）：26,507 个 API / 390 个域，Tool Self-Evolution Synthesis + Self-Guided Dialog Generation + Dual-Layer Verification。
- **AgentInstruct / AgentTuning**（arXiv:**2310.12823**，注意不是 2310.03714；ICLR 2024）：从 AgentBench 的六个环境出发，产出 1,866 条轨迹，用 reward score 过滤（README 明确说"不是所有 GPT-4 的轨迹都有效"）。局限：1,866 条对它所声称的泛化结论偏少；reward 过滤继承环境的奖励函数，**奖励攻击型环境产出奖励攻击型数据**。
- **AutoAct**（arXiv:2401.05268，ACL 2024）：极小种子集 + 工具库，五阶段流程，其中**只保留 reward=1 的轨迹**。它的消融是全文献里最好用的一个论据：去掉 REFLECT 掉 2.81/3.33；三个 agent 合成一个掉 5.66/8.89；而**用未过滤轨迹训练掉 15.96/19.44——比零样本提示规划还差**。即错误过滤不是锦上添花而是承重结构。但 reward=1 是**二元 proxy**：它保留"绕坏路但结果对"的轨迹，丢弃"路线好但小失误"的轨迹。数据量在约 200 条轨迹后**进入平台期**。

### 4.6 稳定性与评估器质量
- **StableToolBench**（arXiv:2403.07714，Findings of ACL 2024）不生成任务，而是**诊断并修复 benchmark 不稳定性**：约 55.6% 的 ToolBench API 不稳定，所有方法重跑时通过率可测地下降。方案是虚拟 API 服务器（缓存 + LLM API 模拟器，cache-first），可解查询**预先用三个模型多数投票筛出**，新指标 SoPR/SoWR 取代 PR/WR。附带一记：原 PR/WR 用的是 `gpt-3.5-turbo-16k`，而且对"不确定"的任务**随机化结果**——一个不必要的人为噪声源。
- **WebVoyager**（arXiv:2401.13919，ACL 2024 main）的评审一致率值得记：643 个任务，self-instruct 半自动生成 + 人工验证。GPT-4V 评审与人类的一致率从单张截图的 75.3% 升到**完整轨迹的 85.3%**（Cohen's κ = 0.70，与人类标注者之间的 0.7 Fleiss κ 相当）——**评审一致率随证据量急剧下降**。另外只有 22.3% 的答案是"Golden"。
- **WebArena**（arXiv:2307.13854，ICLR 2024）的 812 个任务由 187 个模板实例化而来，其**官方规则式评估器召回率仅 55.9%**（AgentRewardBench, arXiv:2504.08942），会因字符串格式琐事否掉正确轨迹。

---

## 5. 模拟用户与领域仿真

### 5.1 τ-bench
- arXiv:2406.12045。Yao, Shinn, Razavi, Narasimhan（Sierra + Princeton）。
- 两个域（retail、airline），每个是**数据库 schema + 一份领域政策文档**。**模拟用户**（LLM）与持有领域 API 工具和政策的 agent 对话。
- **决定性设计**：成功与否通过**比对对话结束时的数据库状态与标注的目标状态**来判定，而非对话匹配。这是该子领域最重要的方法学动作——使评估基于状态、不可被流利措辞糊弄。提出 **pass^k**（跨 k 次试验的可靠性）。
- 结果本身很说明问题：即使 gpt-4o 也有 **<50%** 的成功率，retail 上 pass^8 <25%。而任务量很小（airline 50 / retail 115）——**这正是催生后面自动生成器的直接原因**。
- 一个不受控误差源：用户模拟器本身是 LLM，**模拟器漂移与 agent 失败，在不做人工标注时无法区分**。

### 5.2 τ²-bench
- 2025-06。**这一篇值得直接读原文。**

### 5.3 IntellAgent
- arXiv:2501.11067（2025-01）。Plurai。
- 输入是 **chatbot prompt + DB schema + 可用工具**，生成的东西叫 event，包含三部分：一组 policies、一条符合政策的用户请求、**以及系统数据库的初始状态**。用实体的符号表示处理复杂 schema，再实例化为真实 DB 行。
- 三阶段：event 生成 → 对话模拟 → **对话批评**。批评 agent 会验证用户声明的终止理由，并判定哪些政策实际被测试和被违反——这一步是个确实新颖的评估想法。
- 规模约 **1,000 events/环境**，明显多于 τ-bench 的 50/115，且与 τ-bench 相关性高。

### 5.4 多智能体与社会仿真
- **SOTOPIA**（arXiv:2310.11667，ICLR 2024）：显式的**叉积**——90 个场景 × 40 个角色 × 5 种关系类型（家人、朋友、恋人、熟人、陌生人）。角色带个性、职业、秘密、背景，关系类型同时约束场景有效性与**你能看到对方多少档案**。SOTOPIA-Eval 按七个维度打分，其中 **Secret（−10–0）** 与 **Social Rules（−10–0）** 是刻意的不对称设计——只能减分，是基线。所有模型在这两项上都是负分，GPT-4 也不例外。这是"结构化能力覆盖"在文献里最好的例子。
- **Generative Agents**（arXiv:2304.03442，UIST 2023）：25 个 agent 的 Smallville，架构核心是**记忆流 + 三维检索（相关性/新近性/重要性）+ 反思 + 递归规划**。那个著名的结果——agent 自发传播派对邀请、互相约见面——是**被观察到的，不是被指定的**：**没有机制去"要一个针对特定社交能力的场景"**。它的失败模式也值得记：检索不到相关记忆、编造细节、继承 LLM 过于正式的说话方式。
- **AgentVerse**（arXiv:2308.10848）：任务求解与仿真两套框架，NLP Classroom、Prisoner's Dilemma、Software Design 等 demo 的角色结构是可复用的多智能体场景模板，但场景都是逐个手工写的。
- **AgentSims**（arXiv:2308.04026）：拖拽式沙箱，靠每个 tick 的 QA 表单打分。论文的论点是"仿真器内的任务式评估可以 one-for-all 地替代各种能力评测"，但**全篇是系统描述，没有量化结果或基线**。

### 5.5 领域科学/法律/医学
这一块有个共性：**"auto-generated" 通常指"从一个专家手工整理的产物自动生成"，而不是 de novo 合成**。生成器是转录与实例化机制，不是难度优化器。
- **LegalBench**（arXiv:2308.11462，NeurIPS 2023 D&B）：36 个语料库、162 个任务、六种推理类型，大体按法律的 **IRAC** 框架组织（争点识别、规则回忆、规则适用、规则结论、解释、修辞理解）。它的 IRAC 类型学是任何 benchmark 里最好的"分能力读数"例子，但靠的是**人工分类学设计，不是生成**。局限：只针对客观正确答案，**无法评估"合理的人会有分歧"的推理**；评估 IRAC 各步是独立的，**因此无法测量组合推理**。

---

## 6. "能力缺口定向"这条线：已有的对手

前面几条主线基本都是"更大规模、更低成本地重采样"，验证目标是"某个测试从 fail 变 pass"。但确实存在若干工作走的是**先诊断模型弱在哪、再针对性造题**这条路。

### 6.1 Agent-World
见 §3.2。诊断 agent 消费失败轨迹、错误统计与环境元信息，产出**结构化弱点报告 + 定向任务生成指南**，经 GRPO 多环境 RL 驱动下一轮。这是全文献里对"诊断→定向生成"最完整的实现。

### 6.2 AgentFrontier / ZPD Exam
- **arXiv:2510.24695**（2025-10-28/29）。阿里通义实验室。作者：Xuanzhong Chen, Zile Qiao, Guoxin Chen, Liangcai Su, Zhen Zhang, Xinyu Wang, Pengjun Xie, Fei Huang, Jingren Zhou, Yong Jiang。
- 把教育心理学的**最近发展区（ZPD）**操作化为两个角色：**Less Knowledgeable Peer（LKP，无工具的基础 LLM）** 与 **More Knowledgeable Other（MKO，工具增强的强 agent）**。
- 三阶段：(I) 从约一百万份公开文档分块，用向量索引找主题一致的三元组构成"复合单元"，生成天生需要跨文档知识融合的种子问答；(II) **迭代式 agentic 精炼**——精炼 agent 带搜索/学术/浏览器/代码工具，沿四个轴升级问题（知识扩展、概念抽象、事实接地、计算形式化），每轮输出成为下一轮输入；(III) **ZPD 校准**——LKP 先测，能解则归入预训练已覆盖而丢弃；不能解则交给 MKO 做 Best-of-N（N=3）验证，**只在 LKP 解不出但 MKO 至少一次解出时才保留**（即"有挑战但可学"）；MKO 三次全失败则转人工。再加 reranker 做语义去重（阈值 0.7）。
- **ZPD Exam** 是一个**自演进 benchmark**：用与训练语料**严格不相交**的 30,000 篇 2023–2025 年科学论文生成问题，入选需同时满足两个约束（基线模型无工具三次全败**且**同模型有工具三次全成）。v1 含 1,024 题，覆盖 9 个学科。它把 model 表现分为三区：内在知识区、推理瓶颈区（ZPD）、能力掌握区。
- AgentFrontier-30B-A3B 在 HLE 上 28.6%；pass@1 21.7% vs pass@8 40.7%（说明数据既非平凡也非不可解）。
- 作者承认的局限：**当前对 ZPD 的操作化是二元的，缺乏渐进式脚手架**；依赖模仿学习限制了探索；工具集是静态的。

### 6.3 SPADE
- **arXiv:2608.19197**（2026-08）。Bo Liu, Simon Yu, Yiding Jiang, Ao Qu, Andrew Zhao, Zichen Liu, Junsu Kim, Zijian Zhou, Seungone Kim, Tongzheng Ren, Mickel Liu, Hanfei Yu, Zhaorun Chen, Weiyan Shi, Paul Pu Liang, Luke Zettlemoyer, Yejin Choi, Natasha Jaques（UW/Stanford/Northeastern/CMU/MIT/NUS/SNU/Stevens/UChicago）。
- 自对弈 RL，同一个 LLM 既当 **Environment Designer** 又当 **Reasoning Agent**。Designer 写的是**可执行的 Gym 风格环境**（Python，含状态转移、奖励函数、验证）。
- **课程信号是 hint-based regret**：agent 在有/无**特权提示**下的回报之差。Designer 被奖励去造"有提示能解、无提示解不了"的环境——**这同时排除了已掌握的和不可解的**。
- 两个工程细节：语料接地提供语义广度（没有它，Designer 会重复吐出同一个 `RotatingMazeEnv`，865 个里 413 个、最长连续 296 个）；环境记忆提供纵向适应。
- 结果（30B-A3B）：套件平均 58.3，比 base +8.1，比最强固定环境基线 +5.3；BFCL-v4 多轮 +5.7，ACEBench-Agent +13.9。
- **它的 related work 表述值得一读**：在以往系统里"**环境生成器通常是冻结的、手工设计的、或在单独信号上训练的**"，而 SPADE 把环境分布与能力前沿放在同一个循环里共同演化。这句话基本就是对整个领域现状的概括。

### 6.4 TaskCraft
- **arXiv:2506.10055**，ICLR 2026。OPPO PersonalAI 等。作者含 Dingfeng Shi, Jiaheng Liu, Wangchunshu Zhou。
- 把任务形式化为 `q = f_q(i_T, R)`——一个工具输入索引 `i_T` 加一个作用在检索到的上下文 `C` 上的关系 `R`。这个形式化**结构性地保证了工具必要性**：答案无法脱离执行而导出。
- 难度于是变成一个**结构性操作**：**深度扩展**把 `i_T` 递归替换成需要多一跳的子任务（专门找*超集*以避免循环）；**宽度扩展**合并相互独立的子任务。
- 验证是**增量式**的：原子层设拒绝采样闸门（只保留"有工具 agent 能解、无工具 LLM 解不了"的题），扩展层只做语言学分析——这样昂贵的 agent 推理被限制在原子层。
- 产出 41k 任务、12.6k 工具交互轨迹、5k 多跳分解。消融：结构化生成的任务通过率 **43.0% vs 纯 LLM 的 18.5%**，且工具调用方差更低（0.4 vs 1.2）。
- 注意：**难度是程序化的，不是失败条件化的**——它从不观察目标模型做错了什么。

### 6.5 TASTE
- **arXiv:2605.28556**（2026-05，**不是 2025**）。
- 反转任务构建：先用**自适应对比 n-gram 模型**（以 LLM 判定的合理性训练）采样合法的**工具序列**，用 k-medoids + 语义加权 Levenshtein 距离聚类，实例化为任务，再经**迭代难度演化与对抗重写**精炼。序列有效率从基线 6.7% 升到 86.7%。
- 作者的动机陈述很好用：τ²-Bench 上的高分"往往反映饱和，而非稳健的任务解决能力"。τ^c-Bench 上 Gemini-3-Flash 从 τ²-Bench 的 0.82–0.94 掉到 0.28–0.61；演化后的任务相对其基础版本成功率降 16–55%。
- 它**制造难度**，不定位缺口，也不基于观测到的失败做条件生成。

### 6.6 其他
- **TRACE**（仅 repo `github.com/ScalingIntelligence/TRACE`）：让 LLM 编码 agent 先**给 benchmark 上模型缺失的能力排序**，再针对排名最高的缺口合成一个训练环境，每能力一个 LoRA（GRPO），再用 MoE gate 路由推理。报称 τ²-Bench Airline+Retail 32.9% → 48.3%，SWE-bench Verified 68.0% → 73.2%。**我未找到对应论文，引用前需自行确认。**
- **GenEnv**（arXiv:2512.19682）：难度对齐的 agent 与环境模拟器共演化。
- **CuES**（2025-12）：好奇心驱动、环境接地的合成框架，指出"现有方法通常假设预定义的任务集合，而这一假设在新环境中失效"。

---

## 7. 污染与奖励攻击：相关证据

- **SWE-Bench+**（arXiv:2410.06992，2024-10）。作者：Reem Aleithan, Haoran Xue, Mohammad Mahdi Mohajer, Elijah Nnorom, Gias Uddin, Song Wang。
  对 SWE-Agent + GPT-4 在 **SWE-bench Full** 上解决的 251 个实例做人工审计：**82 个（32.67%）的修复方案直接写在 issue 正文或评论里**；**31.08% 是靠弱到无法验证正确性的测试通过的**；两类合计 63.75% 属于"可疑"，真正算解决的约 36%。过滤后解决率从 **12.47% 掉到 3.97%**。另外：**超过 94% 的 SWE-bench issue 早于各大模型的知识截止。**
  > **数字警告**：arXiv 版报的是 32.67% / 31.08% / 12.47% → 3.97%（在 Full 上）；同一作者的另一版报 33.47% / 24.70% / 12.47% → 4.58%。多个二手来源把 32.67% 错挂到 SWE-MERA 或 Verified 上。
- **AgentRewardBench**（arXiv:2504.08942）：WebArena 官方评估器召回率仅 55.9%。
- **ImpossibleBench**（arXiv:2510.20270）：变异**测试本身**，让测试与自然语言 spec 矛盾（一类是改一个期望值，一类是加一条冲突断言使测试套件内部不可满足），把 agent 的通过率读作"作弊率"。
- **What Makes a Good Terminal-Agent Benchmark Task**（arXiv:2604.28093）：报告**主流终端 agent benchmark 中超过 15% 的任务是可奖励攻击的**，并点名了 AI 生成指令、过度规定性的 spec 等失败模式。
- **The Verification Horizon**（arXiv:2606.26300）：编目静态环境泄漏——仓库历史挖掘出现在 21.11% 的 rollout、测试预言机篡改 3.69%、harness 篡改 8.25%、可见测试过拟合 30.00%；解 artifact 检索只出现在 4.32% 的 rollout，却带来 72.34% 的解决率。RL 中的轨迹级监控把"作弊解决"从 28.57% 压到 0.56%。
- **综述**（arXiv:2511.09586，2025-11，NeurIPS 2025 SEA workshop）：把该领域形式化为 **Generation–Execution–Feedback 循环**，并提出 **Generator–Verifier Asymmetry**——数学和代码这类验证便宜的地方 RL 进展快，而"易生成难验证"的象限（写作、政策、医疗）是环境扩展最难也最有价值处。它同时指出环境扩展"**仍未被充分探索、也未被系统组织**"。

---

## 8. 两条横贯全局的观察

**第一，验证成本决定进展速度。** 上面那个 Generator–Verifier Asymmetry 其实解释了为什么这批工作高度集中在代码和终端：因为"测试从 fail 变 pass"是一个便宜的机械信号。反过来说，凡是不能归约成这种信号的领域（写作、政策、临床），自动生成的进展就明显慢——这不是方法问题，是验证信号可得性的问题。

**第二，命名的坑不少。** `SWE-Dev` 至少指三个不同产物；`TerminalWorld`（arXiv:2605.22535）与 `Terminal-World`（arXiv:2605.20876）是两篇不同论文；`TermiGen` 与 `CLI-Gym` 不同；`SWE-bench-java` 不是论文而是 Multi-SWE-bench 的 Java 子集。引用时按 ID 走。

另外三处常见的事实性错误，值得留意：
- **OSWorld 不是自动生成的**（见 §3.4）。
- **Seal-Tools 不是 schema-free**（见 §4.5）。
- **AgentInstruct 是 arXiv:2310.12823**，不是 2310.03714。
