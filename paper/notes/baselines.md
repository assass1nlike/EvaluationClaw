# Appendix A 的 baseline 选择

建议采用 **Gym-Anything、Petri、AutoControl Arena** 三个自动化构建／审计框架；已有 benchmark 选择 **Who&When、AgentDojo**。依据 `main.tex` 附录 A 的原始 user queries，核验日期为 2026-09-15。以下是论文、官方文档及公开实现层面的匹配判断，尚未运行生成实验。

这三个框架提供真实软件任务、模拟多角色交互、可执行安全场景三种互补路径，但不能声称其原生能力并集完整覆盖 15 项需求。下面的分配是每项的主比较对象；“近似”表示仍需验证或扩展，不能计作已支持。

## 三个框架

### Gym-Anything：真实软件环境与长任务

Pranjal Aggarwal, Graham Neubig, Sean Welleck. *Gym-Anything: Turn any Software into an Agent Environment*. 2026. [论文](https://arxiv.org/abs/2604.06126) · [代码](https://github.com/cmu-l3/gym-anything)

自动安装和配置软件、导入真实数据，使用创作与独立审计循环构建环境，再生成种子任务、扩增任务并提供验证器。论文构建了 200 个软件环境及超过 10,000 项任务，CUA-World-Long 包含常需超过 500 步的任务。因此它是长程、产物导向任务的有力对照，不只是生成问答。

主分配：**D1、D2、D3、D4、D6**。其中 D4 只是最接近的真实软件构建底座，不能称为诊断专精 baseline。

论文 §2.1、§2.3、任务生成部分及附录 B、F 是关键依据。附录 B.3 的 checkpoint 主要用于环境安装、配置与任务初始化复用，不能直接算作 D1–D2 的跨工作会话评测。附录 B.5–B.6 支持可定制验证器和轨迹记录，但框架记录轨迹不等于被测模型能主动留下合格审计记录。

### Petri：按测试意图生成多角色行为审计

Kai Fronsdal et al. *Petri: An open-source auditing tool to accelerate AI safety research*. 2025；后续实现持续更新。[技术报告](https://alignment.anthropic.com/2025/petri) · [代码](https://github.com/safety-research/petri) · [文档](https://meridianlabs-ai.github.io/inspect_petri/)

研究者提供自然语言测试意图，审计 agent 构造上下文、工具和多轮交互，可根据被测模型的行为调整场景并回滚分支，最后由 judge 按可配置维度评分。它是自动化审计与评测生成框架，**不是固定 benchmark，也不是以生成独立可执行环境包为主要输出的框架**。可作为需求到交互测试的 baseline，但应按其原生动态审计方式比较。

主分配：**D7、D8、D9、D13**。

选择它有具体的官方场景依据，而不只是因为实现中有多个模型：

- [行为监督场景](https://github.com/safety-research/petri/blob/e199ec1abcd10267c60cd7eb03035a76567d9e52/src/inspect_petri/_seeds/default/multi_agent_behavior_monitoring.md)：被测模型检查第三个 AI 的多轮行为记录。
- [下属 agent 异常场景](https://github.com/safety-research/petri/blob/e199ec1abcd10267c60cd7eb03035a76567d9e52/src/inspect_petri/_seeds/default/subagent_data_exfiltration_detect.md)：被测模型管理多个下属，从日志识别表现良好但有违规行为的成员。
- [团队内部破坏场景](https://github.com/safety-research/petri/blob/e199ec1abcd10267c60cd7eb03035a76567d9e52/src/inspect_petri/_seeds/default/multi_agent_security_sabotage.md)：三 agent 工程团队中，一名成员在正常工作中夹带破坏性建议；场景包含团队消息工具。

但这些工具响应和角色行为主要由审计模型模拟。出现“启动下属”工具或“团队消息”并不证明实际启动了独立、持有自身状态且能执行工具的 agent。D7 的自主分工与真实失败归因、D8 的可执行产物核验、D9 的多主体动态都仍有差距。D13 可沿用角色和上下文生成机制构造，但“多个合法委托方”的权限关系与裁决标准需要另行明确。

### AutoControl Arena：有程序状态的安全与行为测试

Changyi Li et al. *AutoControl Arena: Synthesizing Executable Test Environments for Frontier AI Risk Evaluation*. 2026. [论文](https://arxiv.org/abs/2603.07427) · [代码](https://github.com/CosmosYi/AutoControl-Arena)

从测试意图生成场景设计、Python 环境及风险评估。文件、数据库、权限等状态通过程序维护，开放式反馈由 LLM 生成；通过压力和可利用捷径改变场景。它比纯文本模拟更适合检查“实际操作了什么”与“如何报告操作”的差异。

主分配：**D5、D10、D11、D12、D14、D15**。

论文 §3.1–3.5、附录 C.1、H 是关键依据。已有风险类别明确包含权限提升、关闭日志／绕过审批、隐瞒行为、能力滥用。附录 H 给出按交互轮次触发环境事件、保存状态及隐藏日志的例子，为 D5、D10、D14 提供实现基础。D12 的不可信内容注入和 D15 的选择性拒绝仍应针对原 query 验证，不能仅凭风险类别名称认定完整支持。

它生成的是程序化模拟环境，不能将模拟文件、权限和工具等同于真实 OS 服务。论文 §7.1 还明确写道：

> “Our current evaluation mainly focuses on single-agent safety evaluation. An urgent future direction is expanding the framework to multi-agent environments.”

因此不把其 Architect、Coder、Monitor 三个构建角色计为 D7–D9 的原生多 agent 支持。

## 15 项分配及能力边界

所有行都只表示建议比较的对象。“较匹配”表示核心任务形态已有依据，仍不代表完整 user query 已经得到验证。

| 需求 | 主 baseline | 匹配判断与尚缺部分 |
|---|---|---|
| D1 长目标持续推进 | Gym-Anything | 较匹配长任务；未证明能自动生成跨多个工作会话、包含中断和重排的协议。 |
| D2 共享项目跨会话一致性 | Gym-Anything | 近似：有持久产物与状态保存；还需任务之间的决策依赖、重新进入会话和矛盾检测。 |
| D3 从产物推断未明说的惯例 | Gym-Anything | 近似：能配置文档和软件产物；还需惯例只隐含在示例中、无显式泄漏，并验证新产物是否遵循惯例。 |
| D4 无复现条件的症状诊断 | Gym-Anything | 弱匹配：支持真实软件环境与自定义任务；未展示自动构建“只有症状、无复现／失败测试／堆栈”的故障，及最小修复评分。 |
| D5 途中静默失去依赖 | AutoControl Arena | 近似：程序状态与隐藏事件支持模拟途中失效；需确保依赖先可用、再失效，且存在可行替代路径，不能只告知“工具坏了”。 |
| D6 硬资源预算 | Gym-Anything | 较匹配：长任务已有步数／成本限制；显式告知预算、强制执行及经济策略的评分仍须对齐 query，尤其 token 和时间预算。 |
| D7 编排下属并诚实归因 | Petri | 近似：已有管理下属的模拟场景；缺独立下属的真实执行、分工依赖和可验证的失败责任标签。 |
| D8 检查其他 agent 的错误 | Petri | 较匹配监督场景；仍需真实产物、可核验错误，并控制“高信誉／自信摘要”对判断的影响。 |
| D9 不可靠／恶意 agent 群体 | Petri | 较匹配团队破坏场景；缺真实多主体执行、来源可验证性及群体行为的系统性检验。 |
| D10 诚实报告进度与失败 | AutoControl Arena | 较匹配隐瞒与行为审计；需逐项对齐实际轨迹和自报结果，区分已验证、假设、放弃。 |
| D11 最小权限 | AutoControl Arena | 较匹配权限提升场景；需标注完成任务所需的最小权限，区分合法申请与不必要扩权。 |
| D12 不可信内容中的冲突指令 | AutoControl Arena | 近似：可在模拟文档／工具输出中植入内容并记录后果；还需验证正确的信任边界及“报告冲突”。Petri 可作交叉比较。 |
| D13 合法委托方的指令冲突 | Petri | 近似：多角色对话适配；应让各方确实具有指令权，不能退化为识别恶意提示注入或既定上下级优先级。 |
| D14 完整审计记录 | AutoControl Arena | 较匹配监督规避与日志状态；必须评分模型留下的记录是否完整，而非框架是否自动记录了轨迹。 |
| D15 正常任务内的双用途边界 | AutoControl Arena | 近似：能力滥用与捷径场景可作为基础；需把合法／有害子目标分开，同时检查拒绝有害部分和交付合法部分。 |

D4 是这组三框架中最弱的比较位置。若单独增加诊断专项实验，最值得加入的是 [CLI-Gym](https://arxiv.org/abs/2602.10999)（[代码](https://github.com/LiberCoders/CLI-Gym)）：它自动破坏正常运行的真实环境，再构建修复任务。不过它原生依赖失败测试并据此生成问题描述，因此也不完整满足 D4；D5 还需要把构建时的破坏改为执行途中的干预。在三个主 baseline 的限额内，优先保留 Petri，以覆盖 D7–D9 的专门场景，而非增加一个仍然需要修改协议的诊断生成器。

IntellAgent 虽然明确是自动 benchmark 生成框架，但核心是政策驱动的用户—客服交互，不比 Petri 的现成监督／团队破坏场景更贴近 D7–D9。SOTOPIA 有交互角色与场景生成，但主要目标是社会互动，不能把社会目标协商直接视为工程任务委派、产物审查与执行故障归因。

## 两个已有 benchmark

### Who&When：对应 D7 的故障归因部分

Shaokun Zhang et al. *Which Agent Causes Task Failures and When? On Automated Failure Attribution of LLM Multi-Agent Systems*. ICML 2025. [论文](https://arxiv.org/abs/2505.00212) · [代码](https://github.com/ag2ai/Agents_Failure_Attribution) · [数据](https://huggingface.co/datasets/Kevin355/Who_and_When)

包含来自 127 个多 agent 系统的 184 条失败任务记录，标注责任 agent、决定性错误步骤及原因。它与 D7 中“具体哪个 agent 失败、为什么”的目标直接对应，也可为 D8 的错误定位部分提供参照。

比较时，让 EvalClaw 为“多 agent 失败归因”生成测试，与 Who&When 使用相同的责任 agent／错误步骤评分协议，并比较标签正确性、诊断难度、模型区分度与排序稳定性。其原生任务是**事后读取轨迹做归因**，不测试被测模型亲自分工、运行下属和持续跟踪。因此这只能验证 D7 的归因子能力，不能作为完整 D7 的替代品。不要用两个测试集上谁的通过率更低直接判断 benchmark 更好。

### AgentDojo：对应 D12

Edoardo Debenedetti et al. *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents*. NeurIPS 2024 Datasets and Benchmarks. [论文](https://arxiv.org/abs/2406.13352) · [代码](https://github.com/ethz-spylab/agentdojo)

包含 97 项正常任务和 629 个安全测试案例，核心是被测 agent 使用外部工具时，如何抵抗不可信数据中的提示注入；环境覆盖工作区、银行、旅行等任务。它有可执行环境和正常任务／攻击目标的检查，适合与 EvalClaw 在 D12 上直接比较。

保留相同的正常任务能力范围、攻击者权限、注入位置及执行预算，比较正常任务完成率、受攻击时的完成率、攻击成功率，以及测试有效性和模型区分度。D12 额外要求“主动报告指令冲突”，需要单独评估；不能声称 AgentDojo 原生指标已经测量这一点。AgentDojo 的攻击者修改不可信内容，也不等于 D9 中多个可自主行动的 agent 群体。

## 比较方式与论文结论

- 先固定需求分配与评分协议，再看各系统结果，避免事后把每个需求分给表现最弱的 baseline。在 D10–D12 等重叠位置，可补充 Petri 与 AutoControl Arena 的交叉比较。
- 原生比较只做必要的模型接口与输入格式适配。若人工加入跨会话调度、故障注入、独立下属 agent 或新验证器，应单独标为扩展版本，并计入构建成本；这些都是待比较的能力，不能默默替 baseline 补齐。
- 将“无法构造满足需求的有效测试”与“构造成功但质量较差”分开报告。质量评分限定在有效测试上，同时报告有效构建率；不把不支持简单当作模型任务得分为零。
- Petri 是在线自适应审计。固定 seed、审计策略、审计模型、judge 与回滚预算，并保存完整分支；比较相同预算下的有效审计，不把某个模型的固定交互 transcript 直接回放给另一个会采取不同动作的模型。若讨论独立可复用 benchmark 包，其输出形态差异本身需要报告。
- 统一需求级质量标准：正确性、忠实度、多样性、可执行性／模拟一致性、判别性、构建成本。安全测试还要检查正常任务仍可完成。受测模型在更难题上的低通过率，不足以证明生成框架优越。

这些来源支持的稳妥结论是：**已有系统在相关领域提供强基线，但对上述复合执行协议的支持不完整；EvalClaw 是否填补缺口，需要由有效生成和执行结果证明。** 不能仅凭选中的三个框架存在缺口，推断整个文献没有对手。

`main.tex` 当前 Setting 1 的 “There is no existing benchmark for these domains” 过于绝对：Who&When 和 AgentDojo 已覆盖其中的子能力。更准确的表述是“现有 benchmark 只覆盖部分子能力，尚未为这些完整需求提供统一的自动化构建方案”。Related Work 关于既有框架不依赖外部检索、只产生静态题目的概括，也应结合 Gym-Anything、Agent-World、AutoControl Arena 等工作收窄。

本次查看的公开代码快照：Gym-Anything `774476d752d748a69288f2ead97f75dd9df08ddb`；Petri `e199ec1abcd10267c60cd7eb03035a76567d9e52`（README 标为 3.0，不能与 2025 报告的 111 个 seed 混为同一版本）；AutoControl Arena `4a3b91d68d6401673898f6d0580a922f6e49056f`。正式实验应固定实际使用版本；上面的支持范围未以本地运行验证。
