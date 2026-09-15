# 自动化Benchmark构建相关工作综述

## 1. LLM驱动的Benchmark生成框架

### BenchMaker: LLM-Powered Benchmark Factory
- **arxiv**: 2502.01683
- **输入来源**: 仅依赖用户输入——任意评估需求文本X是唯一输入；无外部检索/搜索，明确设计为"不依赖seed benchmark"。
- **支持题型**: 选择题为主（明确选MCQ为默认题型）；输出题仅通过格式转换支持（如把MATH开放式转MCQ）；**不支持生成题**——特意避免用LLM-as-a-Judge打分。
- **迭代**: 有。逐样本自我纠错+冲突引导对比判别+难度扩散机制——按已生成样本的被测错误率β排序，挑最难样本作参考，让模型生成更难的题。迭代信号为内部错误率/自洽冲突，非外部判官。

### YourBench: Easy Custom Evaluation Sets for Everyone
- **arxiv**: 2504.01833
- **输入来源**: 仅依赖用户文档。Document-to-Evaluation管线（摄入→分块→摘要），无外部搜索/检索，不把已有benchmark/dataset作为生成源（MMLU仅作复现对照）。
- **支持题型**: 生成题为默认（开放问答+引用依据，用judge LLM集成做成对比较打分）；选择题通过改写提示支持（MMLU复现即用此，简单精确匹配打分）；输出题支持较弱——可引导生成numeric/factual题型，但无代码执行判分器。
- **迭代**: 类一次性。流水线多阶段（提供上下文→生成本→过滤），过滤自动执行：citation grounding分数（阈值0.85）+DBSCAN语义去重（簇大小作显著性权重）。无基于分数的反复再生成循环；人工细化仅作为可选能力。

### AutoBencher: Towards Declarative Benchmark Construction
- **arxiv**: 2407.08351
- **输入来源**: 用户声明目标+外部检索/特权信息。知识域用Wikipedia Search API检索相关文章作grounding；多语言同样基于Wikipedia+翻译系统；数学用sympy/scipy/numpy计算验证；安全域无特权信息。另需用户提供显著主题集（如Wikipedia浏览量≥50万过滤候选）。
- **支持题型**: 输出题（知识/数学/多语言均为确定性答案或代码验证）；生成题（能力数据集用GPT-4作为judge做CoT正确性判断）；**不支持选择题**（明确指出生成集不用预置选项）。
- **迭代**: 有。两阶段：自适应搜索循环（每轮针对过去(描述,准确率)轨迹提出K个新描述，以小数据集测评候选LM准确率作信号）；最终再重排（按新颖性+难度+可分性/安全性目标函数挑选最优描述并生成更大数据集）。迭代信号为模型错误率/难度。

### BenchBench: Benchmarking Automated Benchmark Generation
- **arxiv**: 2603.20807
- **输入来源**: 完全由seed benchmark驱动。从CSBench/WeMath/MedXpertQA/ToMBench抽取结构化domain card（子域、术语、模态/语言约束），生成时"conditioned on domain card rather than raw seed items"。无外部搜索/检索。
- **支持题型**: 三类都支持。选择题（mcq_single/mcq_multi，精确或集合匹配）；输出题（open_ended/structured短答案，numeric/symbolic匹配）；生成题（rubric-guided LLM判断，gemini-2.5-pro按参照评分，约22%核心响应走rubric判断，其余用客观验证器）。另有独立质量判官给出clean/not_well_posed/gold_incorrect/ambiguous标记。
- **迭代**: 批量迭代，但由配额驱动而非模型表现。设计器分批生成，每批后计算配额缺口并做定向"补足"批次，直到覆盖目标。验证是另一个闭环（schema校验+动态质量过滤，不合格项被剔除出核心集，而非再生成）。

### BeTaL: Automating Benchmark Design
- **arxiv**: 2510.25039
- **输入来源**: 模板/已有benchmark参数化+无外部检索。从"欠指定环境"（高层任务描述+有限参数集）出发，可复用已有静态benchmark（其中一个由τ-bench airline环境参数化而来）。无网络搜索/检索步骤。
- **支持题型**: 输出题为主——三个域均为确定性答案任务（算术序列、空间坐标、τ-bench代理API调用对黄金数据库态），逐项程序化验证。**不使用选择题**。生成题仅作为无ground truth时的兜底方案（LLM-as-Judge / Program-as-Judge）。
- **迭代**: 明确迭代。交互式循环：设计器提参数→模拟器实例化环境生成数据集→目标模型在小型任务集上评估→参数选择+观察到的表现总结回设计器。驱动信号为性能差距g=|观测表现−用户指定目标ρ|，I轮后返回差距最小的配置。

### AutoBench: Automating LLM Evaluation through Reciprocal Peer Assessment
- **arxiv**: 2510.22593
- **输入来源**: 完全自主，仅由提示驱动，无外部搜索/检索/既有数据集。任务类别为预定义集合（数学、时事新闻、创意写作、逻辑、语法、编码、历史、通识、科学、技术），均匀采样；难度按0.6/0.3/0.1偏难采样。实际任务内容为模型生成，非外部策展。
- **支持题型**: 生成题为主。作答提示用"严格正确性门控"后按正确性/清晰度/相关性/结构/深度打分，基于rubric的主观评价，非ground-truth匹配。**不使用选择题**。虽有数值答案可能，但评分机制仍走judge评级1-5。
- **迭代**: 两级迭代。任务生成是重试循环（最多k=3，信号为质量门控：所有模型评分的加权均值和众数需超阈值，未达标则换生成器）；整体框架跑T=40轮，权重随累计表现更新——judge权威度迭代演化，是自我强化的重新加权信号，而非修订答案。

### DyVal: Dynamic Evaluation of LLMs for Reasoning Tasks
- **arxiv**: 2309.17167
- **输入来源**: 用户可配置参数，纯合成，无外部检索/既有数据集。形式化描述语言A_T=F(G(C))：生成算法G引入随机性，约束C（任务约束+复杂度约束）调控难度与有效性，描述函数F把样本转成自然语言。难度由树深/宽、节点数、附加随机链接等参数控制，全部现场生成。
- **支持题型**: 输出题（全部7个任务均为确定性可精确判定的答案）。数学：算术（相对精度分级）、线性方程组（精确解）；逻辑：布尔/演绎/溯因（True/False/N/A）；算法：可达性（布尔）、最大路径和（精确数值）。**不支持选择题**，**不支持生成题**（无LLM-as-Judge）。
- **迭代**: 一次性生成。每个样本独立构造DAG生成，评估一次性通过。无将评估结果反馈回改样本的机制。"动态"指可调随机性+复杂度约束（D1-D4共演化难度），而非基于模型反馈的迭代精炼。

## 2. 动态和自适应评估系统

### DARG: Dynamic Evaluation via Adaptive Reasoning Graph
- **arxiv**: 2406.17271
- **输入来源**: 基于已有评测数据集。提取现有基准（GSM8K数学、BBQ社会、BBH Navigate空间、BBH Dyck符号）中数据点的推理图并扰动，不依赖用户输入，不做外部搜索。
- **支持题型**: 可客观判定的输出题为主——数学为精确数值（代码解释器验证）、社会题为选择题（pro-bias/anti-bias/neutral）、空间题为yes/no、符号题为精确匹配；用code-augmented LLM+外部解释器核对标签，不用LLM-as-a-Judge。选择题只有BBQ一种（预置选项）。
- **迭代**: 有"生成→校验→修正"循环，驱动信号是标签正确性/一致性（图推导标签与原标签或新生成文本不一致时，迭代重提示直到对齐；扰动环节本身用规则函数、不引入噪声）。优化目标是生成项的"有效性/正确性"，复杂度（深度+）是事先设定的控制参数而非优化信号。

### TestAgent: Automatic Dynamic Benchmark Generation
- **arxiv**: 2410.11507
- **输入来源**: 基于用户提供的领域知识库（RAG）+用户的主题兴趣，不依赖用户逐条实时提问，也不做外部联网检索。知识源如医疗OpenKG/CareGPT、政府官方基金管理网站等。
- **支持题型**: 生成题（开放问答），答案判分用LLM-as-a-Judge按两阶段标准（内容准则+文本准则如流畅度、拟人感，可小数评分）打分，不是选择题/客观输出题。
- **迭代**: 问题的生成与两阶段标准生成是一次性（单次通过），无"生成→评估→修正问题"的循环。迭代发生在交互阶段：PPO策略在"追问vs挑战"两个动作间选择，状态为问题嵌入+当前分数+分数变化+相邻回答余弦相似度，奖励为相邻回答间分数绝对变化+(1-余弦相似度)，即优化每轮的信息增益（探索轨迹），而非重写题目本身。

### Fluid Benchmarking
- **arxiv**: 2509.11106
- **输入来源**: 基于已有评测项+已有模型成绩。项目池为Open LLM Leaderboard（ARC-Challenge, GSM8K, HellaSwag, MMLU, TruthfulQA, WinoGrande），用该榜上102个LM的公开成绩拟合IRT/2PL模型。无用户输入、无外部检索。
- **支持题型**: 以选择题与客观二值（对/错）题型为主（本就按二元正确率的IRT建模，且要求二值作答），MMLU/ARC/HellaSwag/WinoGrande为选择题，GSM8K为数值客观题；不用LLM-as-a-Judge。严格来说只支持可二值判定正确/错误的题。
- **迭代**: 不是"生成→评估→修正"的生成循环，而是在评测时对固定题库做自适应选题（计算机化自适应测试，以Fisher信息最大为选题信号，动态选择难度匹配当前能力估计、区分度高的题，并支持动态停止）。优化目标是评测效率与方差（以更少题获得高信度，如MMLU减少50倍题量）。

### Code2Bench: Dynamic Benchmark Construction for Real-World Code Evaluation
- **arxiv**: 2508.07180
- **输入来源**: 外部检索真实世界代码。持续从活跃GitHub仓库（880个≥500星Python项目，取自2024-08~2025-05的近期commit）拉取函数，选择刻意落在多数模型知识截止之后、避免污染。无用户输入。
- **支持题型**: 代码生成/输出题，客观测试（基于属性的PBT测试+差分测试，Pass@1）；不用选择题、不用LLM-as-Judge判分（LLM仅用于构建时的候选筛选与难度标注）。
- **迭代**: 是"生成→验证"循环，但只作用于测试套件层：采样输入→对ground-truth实现执行→只保留达到100%分支覆盖率的测试套件，并通过dry-run确认可用；被优化的目标是测试严谨度/覆盖率，而非难度（难度由独立LLM判断分配）。ground-truth函数被视为固定，无"改函数"的循环。求解侧为单次零样本greedy。

### Prism: Dynamic and Flexible Benchmarking with MCTS
- **arxiv**: 2504.05500
- **输入来源**: 内部搜索树，无外部检索、无已有数据集、无用户输入。问题空间为(概念c, 难度d)对，由LLM（4o-M作Challenge Designer）按指定概念+难度生成问题；仅"风格"模仿LeetCode，题目本身为生成而非抓取。
- **支持题型**: 代码生成/输出题，客观测试验证（模型生成解决方案并通过未知测试套件；解题与测试生成器彼此隔离防串扰），Pass/fail计分；不用选择题；LLM-as-Judge仅用于第3阶段失败根因分析，不作最终分数（作者亦承认此为局限）。
- **迭代**: 三阶段MCTS搜索，含"生成→求解→测试→反馈修复"循环（失败时模型接收执行错误重试，超次数后由Problem Fixer介入修复）。驱动信号随阶段变化：Phase1奖励成功（偏向较难难度，探索模型尚能处理的更强组合题），Phase2偏好失败（聚焦弱项、测量修复能力），Phase3扩展弱节点以区分偶发/系统性失败。奖励经TD更新（UUCB1+ε-greedy选择），优化目标是先能力映射、后失败发现，即"随模型能力自适应勘探"，非覆盖固定集合。

## 3. 抗污染和自进化Benchmark

### AntiLeakBench: Preventing Data Contamination by Automatically Constructing Benchmarks with Updated Real-World Knowledge
- **arxiv**: 2412.13670
- **输入来源**: 外部检索真实世界知识，来源为Wikidata（抽取(subject, relation, object)三元组，用start/end time限定词找"截止时间后发生变化"的对象）+Wikipedia（用修订历史取更新后的页面，以支撑文档），刻意不用LLM生成内容（避免幻觉/偏差）。流程全自动，无需用户输入，只要下载最新Wikidata dump即可。
- **支持题型**: 两种，均为可客观判定——(a)生成式短问答，用精确匹配(EM)与token级F1客观判分，不用LLM-as-Judge；(b)选择题，预置选项即正确项/Unknown项/过期项/噪声项，用Acc/F1计分。
- **迭代**: 一次性构建，无"生成→评估→修正"循环。流程为固定序列：准备数据→识别截止时间后更新的知识→构建支撑文档→构造无污染样本；唯一的评估是人类验证（对Gold样本各100条），是最终质检，不驱动重新生成，也不优化任何指标。

### EvolMathEval: Towards Evolvable Benchmarks for Mathematical Reasoning via Evolutionary Testing
- **arxiv**: 2508.13003
- **输入来源**: 既有数据集+程序化生成，无用户输入、无外部联网检索。种子题由"逆向工程"从稀疏线性方程组从零生成（先随机生成解向量，再在预定义整数空间内构造满秩/必要性校验的方程）；作为泛化实验，也"演化"公开数据（GSM8K、SVAMP、MAWPS，先用LLM抽取核心数学公式再演化）。
- **支持题型**: 数值客观题，每个种子题有唯一确定整数解，按模型精确答案的accuracy判定，不用LLM-as-Judge判分（LLM-as-Judge只作为适应度函数里0-10的"难度裁判"，用于难度打分，不做答案评定）。
- **迭代**: "生成→评估适应度→选择/淘汰→被淘汰题再演化"循环。驱动信号为复合难度分数——启发式裁判分(0-10)+语言复杂度（词数、可读性、句法复杂度、词法熵）+数学-逻辑结构（变量/方程数、噪声比），权重由与实际准确率的Pearson相关/t-检验显著学习得到；经双重筛选（综合分阈值+任一指标倒数1%的缺陷剔除）淘汰的候选回到演化循环做第二轮变异/交叉。优化目标是最大化难度，以实测准确率下降验证；设计上两代后终止（过多代会导致冗长、可读性下降）。

### Recent Advances in LLM Benchmarks against Data Contamination: From Static to Dynamic Evaluation (Survey)
- **arxiv**: 2502.17521
- **输入来源**: 作为综述，它描述的不是单一管线而是各类动态基准的多种来源——时间过滤的外部内容（LeetCode/编程竞赛、AoPS论坛、近12个月数学竞赛、预测市场、最新arXiv论文）、人工编写模板+变量槽（GSM-Symbolic、Mathador-LM、MMLU-CF）、以已有数据集为种子改写（Auto-Dataset、StructEval、VarBench、ITD）、LLM从头生成（TreeEval等），以及众包提交（Dynabench）。注意：其"检索"指选取晚于训练截止的新数据，而非评测时实时联网搜索。
- **支持题型**: 三类都覆盖，随基准而异——选择题（MMLU-CF、C2LEVA）；答案确定的输出题（GSM-Symbolic、DyVal/NPHardEval求值、S3Eval执行SQL、HumanEval式pass@k）；开放生成题由LLM/人工判定（LLM-as-an-Interviewer、KIEval、TreeEval）。
- **迭代**: 描述了多种循环，但无统一的自闭环系统——BENCHAGENTS（规划/生成/验证/评估分派给专职agent+人工反馈，目标是质量与多样性）、交互式基准（依被测模型响应生成追问，问题难度自适应）、Benchmark Self-Evolving（多agent扩展）、ITD（检测污染后改写以保留难度）。综述本身指出动态基准缺乏"评估自身"的统一标准，故迭代信号/目标是各方法各自定义的。

## 4. LLM-as-Judge和竞技场评估

### Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena
- **arxiv**: 2306.05685
- **输入来源**: MT-Bench为研究者人工编写的多轮问题集；Chatbot Arena为众包用户提交/在线平台对战数据。两者都不做外部检索。
- **支持题型**: 开放题（open-ended多轮问答），由LLM judge打分/两两比较。可确认**不支持**选择题、**不支持**答案确定的输出题（无ground-truth匹配，靠judge偏好）。
- **迭代**: 基准构建本身无"生成→评估→修正"循环。MT-Bench是固定问题集。Arena通过用户持续对战累积，属"持续补充"非"基于信号修正"；本文的迭代发生在评测设计层面（v1→v4修订、扩大基准），而非对题目的自动修正。

### Constructing Domain-Specific Evaluation Sets for LLM-as-a-Judge
- **arxiv**: 2408.08808
- **输入来源**: 来自外部已有数据集聚合（14个来源：LMSys Arena、PubMedQA、MathQA、No Robots、Aya、Legal reddit、BillSum、Airoboros-gpt4、Finance Advisor、MMLU、TruthfulQA、GSM8K等），加上人工标注种子与人工清洗。不做LLM合成，不做评测时实时检索；管线可周期性重跑同一数据获得新样本（LiveBench式去污染策略）。
- **支持题型**: 开放生成题，LLM-as-a-judge两两偏好比较（靶模型vs GPT-4o，判断输出`[[A]]/[[B]]/[[C]]`更好），无选择题、无确定答案输出题。
- **迭代**: 建题阶段无"生成→评估→修正"循环（嵌入→分类→分层采样→人工清洗，固定单遍）。相邻机制：周期性重跑管线刷新样本（非judge驱动的修正）；以及依人工错误分析修改judge prompt（对多语言/代码判分错误加惩罚、强调正确性而非风格）和为类别不足时补充样本——这些是改"评测"而非改"题目"，且由人工信号驱动。优化目标是类别平衡/多样性+与Chatbot Arena人类偏好对齐（84.44%一致率、Spearman 0.915）。

### A Survey on LLM-as-a-Judge
- **arxiv**: 2411.15594
- **输入来源**: 多元——已有数据集/基准（Alpaca 52K、LMSYS-Chat、Toxicchat等构建元评测训练数据）；模型生成内容（GPT-3.5/4、Vicuna、ChatGLM等的响应与候选）；大规模爬取数据；人工标注/众包/评审修正；模板填充与Deep Transformation式变换。不依赖评测时实时检索，但把"retrieval"作为应用语境与知识图谱充分性检查讨论。
- **支持题型**: 几近全覆盖，且明确分类——选择题、yes/no/true-false等答案确定的判定题、两两/三选/四选/并列对比、listwise/ranking比较，以及开放任务由judge给分或写critique（Likert 1-3/1-5/1-10或连续0-1/0-100分维）。
- **迭代**: 描述了多个循环——Reflexion式自我优化（judge给成功/失败或"需修改"信号，模型语词自省后重试）；Self-Taught Evaluator（在合成对照输出上训练judge，再用其自身预测持续改进，一"循环自我增强"）；INSTRUCTSCORE（收集失败模式→GPT-4反馈→迭代微调）；JADE（人工纠正judge，最常被纠正的样本回填few-shot）；GRPO/规则奖励（Think-J，在线RL）。迭代信号统一是"更贴近人类偏好的反馈"，目标是推进judgment向人类标准对齐。

### BenchBuilder / Arena-Hard-Auto: From Crowdsourced Data to High-Quality Benchmarks
- **arxiv**: 2406.11939
- **输入来源**: 众包用户查询。初始池为Chatbot Arena的20万条prompt；另一轮对WildChat-1M的15万条查询跑同一流程。不做外部检索/搜索。
- **支持题型**: 开放生成题，LLM-as-a-judge两两打分（靶模型vs GPT-4-0314基线，judge用GPT-4-Turbo，5点Likert+思维链+位置交换），Bradley-Terry聚合。无选择题、无确定答案输出题。
- **迭代**: 数据策展阶段是单遍过滤管线（BERTopic+embedding+UMAP+HDBSCAN聚类→LLM annotator按七项质量准则打分→丢弃低分→高质量簇中均匀采样），无对prompt的修订循环。迭代发生在"评测协议"层面而非"题目"层面：为对抗长度/markdown偏差给Bradley-Terry加风格控制、集成多judge（GPT-4-Turbo+Gemini-1.5-Pro）降低自偏差。优化信号是基准级质量（separable、人类偏好对齐），驱动的是打分/判分改进而非题目策展。其"无人在环的持续更新"指随时间刷新基准，非逐题修正。

## 5. 行为和自动化测试套件构建

### CheckList: Beyond Accuracy — Behavioral Testing of NLP Models
- **来源**: ACL 2020
- **输入来源**: 人工编写的测试模板——由"通用语言能力×测试类型"矩阵（capability如vocabulary/POS/taxonomy/NER/fairness/temporal/negation/coreference/SRL/logic；test type如MFT/INV/DIR）指导测试者自行构思并快速生成大量测试用例，结合masked-LM做模板填充（如"I really {mask} the flight."）。不做外部检索，不自外部数据集采样；用户在研究中自行构造测试，是人工驱动的模板/构思式生成。
- **支持题型**: 确定答案的输出题（判类/蕴含/span抽取，如情感分析、NLI/QQP、机器理解），预测结果可与标签对照，无选择题、无开放式LLM判分题。这是论文覆盖的判定式设置；文献化确认的细粒度题型与NLP之外的任务需进一步确认。
- **迭代**: 存在人工驱动的内隐循环——测试者可跑CheckList、发现bug、再补更多针对性测试（研究中用CheckList者测试数约翻倍、发现bug数约为3倍），但论文无自动"生成→评估→修正"回路，无信号自动驱动、无明确优化目标（优化的是"覆盖更多bug"这一人类目标）。其开放源码工具被下游（如TextAttack）作为INV扰动复现。

### Automatic Construction of Evaluation Suites for NLG Datasets
- **arxiv**: 2106.09069
- **输入来源**: 已有数据集（GEM，如WebNLG/ToTTo/XSum等，产出80个challenge sets/12套件）；新收集的预编译数据（时间偏移的含COVID关键词新闻等"Data Shift"类别）；程序化变换（butter-fingers、back-translation）与人工/参与者编写的变换模板（NL-Augmenter仓库、BIG-bench式参与者构建）。无评测时实时检索。
- **支持题型**: 开放生成题（text-to-text摘要/简化、data-to-text三元组/表格/dialog act显化、对话响应），无选择题、无确定答案输出题——论文明确指出NLG搜索空间指数大、多个正确输出，故无法用分类式确定性标签翻转。
- **迭代**: 管线为"构建→评测→分析"，无闭环生成-修正循环；challenge sets保持固定，score事后分析以暴露模型行为。其迭代信号是人类/参与者驱动——欢迎向仓库提交变换生成器与过滤条件来扩展challenge sets；明确拒绝对抗式（生成模型失败的扰动）而选择"过采样代表性不足样本"。隐式优化目标是诊断表现力（揭示未见主题、对扰动的脆弱性），而非由度量驱动自动改写set。

### SYNTHEVAL: Hybrid Behavioral Testing of NLP Models with Synthetic CheckLists
- **arxiv**: 2408.17437
- **输入来源**: 不是用户输入，也无外部搜索/检索。用已有数据集做种子（随机采样IMDb训练集、ToxiGen train的词作查询，随机采样100k句），LLM受控续写生成。后期模板由人类专家手工设计，非自动提取。
- **支持题型**: 情感/毒性二分类，确定性输出（few-shot in-context预测标签，如"Answer with positive or negative"）。非选择题；无LLM-as-Judge开放评分。
- **迭代**: 生成阶段一次性（一次生成10万句）。评估是"生成→对比找难例→人工归纳模式"三段流程；但难例归纳→模板是人工的，无自动"评估→修正"闭环。作者明确承认irony/simile未能形式化为测试类型并列为局限。

### Automatic Behavioral Test Cases for NLP Using Clustering and Prompting
- **arxiv**: 2408.00161
- **输入来源**: 非用户输入、无外部检索。输入为已有数据集（Amazon Reviews语料）+对文本表征做聚类得到的"有意义分组"，再经prompting生成MFT（Minimal Functionality Tests）。种子/分组来自聚类结果。
- **支持题型**: MFT源自CheckList传统，评估是分类模型的标签预测，应为答案确定、可按标签客观判定的输出题（非选择题、非开放生成）。
- **迭代**: 从摘要看为"聚类→prompting→生成→跨四个分类器分析行为画像"的单次流程，未见"生成→评估→修正"循环。是否在正文含迭代需进一步确认（正文HTML版在arXiv不可用，仅按摘要核实）。

### AutoTestForge: Multidimensional Automated Testing Framework for NLP
- **arxiv**: 2503.05102
- **输入来源**: 非用户输入、无外部检索。从LLM交互生成的"句子结构描述"与模板做起种子，未提到用外部数据集做种子；词填充模型（roberta-large）+token mask替换提供词汇素材。
- **支持题型**: 模板为带槽位的word-filling模式，每个模板带预定义二分类标签（0/1），按标签判分类正确性——这类是答案确定的输出题（非选择题）。三个多维度扩展轴：taxonomy、fairness、robustness。
- **迭代**: 有。流水线多阶段，最后阶段用多模型投票/differential testing作反馈信号：一致性分数=1的丢弃、(0.5,1)的加入、≤0.5的经LLM优化（重标/修复）后再回插入套件，并再次用修改过阈值的差分测试复验。

## 6. 合成数据和标注流程

### Using Synthetic Data for Model Evaluation (Autoevaluation)
- **arxiv**: 2403.07008
- **输入来源**: 非用户输入、无外部检索。用"已有的大量无标注数据点+少量人工标注数据"，由标注模型为这些既有输入生成合成标签；实验里输入是真实人工prompt与20个LLM的回答。
- **支持题型**: 面向已有数据点生成标签（分类标签/偏好对），标签为点估计或标签分布（如softmax向量）。属答案确定、可客观判定的输出题；用judge LLM做二选一偏好判断。非选择题、非开放长文生成评分。
- **迭代**: 无"生成→评估→修正"循环。一次性生成合成标签，再用人工数据估bias并做统计修正（PPI去偏），λ参数单次按最小方差选取；"修正"是事后统计校正，非迭代再生成。

### PRDBench: Automatically Benchmarking LLM Code Agents through Agent-Driven Annotation
- **arxiv**: 2510.24358
- **输入来源**: 需人工监督。任务种子来自三类已有来源：内部AI产品平台的真实用户开发请求、GitHub上公开的CS课程最终项目、CS学位论文的代码复现任务；再由代码agent生成PRD与可执行criteria scheme，经人工验证。无评估时外部检索。
- **支持题型**: 非选择题。元数据是三种metric（unit test / shell interaction / file comparison）对确定性输出比对；同时用Agent-as-a-Judge（PRDJudge微调模型）按criteria scheme给单元测试之外的开放式代码质量打分，是"确定性输出+LLM-as-Judge"混合。
- **迭代**: 有。构建时多轮"人工检查→Agent修复与精化"循环，直到所有问题解决，且仅保留经过至少5轮人工-代理迭代精化的任务；评估时另有Round1(DEV)/Round2(DEBUG)两轮协议，DEBUG以PRDJudge扣分报告为信号驱动代码修复。

### PACIFIC: Benchmarks for Sequential Instruction Following in Code
- **arxiv**: 2512.10713
- **输入来源**: 非用户输入、无外部检索。只用自身已有的Instruction Pool（用Python/Java/C++实现的可复用指令），在类型一致性与长度调整约束下随机采样指令序列与输入；预期输出由执行参考实现计算得出，全部由固定随机种子可复现。
- **支持题型**: 仅确定性输出题——"clearly defined expected outputs"经"simple output comparison"判定，明确避免LLM-as-a-Judge。逐步准确率/指令级准确率为确定性规则度量。不含选择题、不含开放生成题。
- **迭代**: 一次性生成，无"生成→评估→修正"循环。难度靠前置参数控制（指令数量为定量难度调节器、目标输出长度为定性难度调节器），非迭代精化。

## 7. 进化和基于优化的Benchmark生成

### An Evolutionary Framework for Automatic Optimization Benchmark Generation via LLMs
- **arxiv**: 2601.12723
- **输入来源**: 无外部检索；是一个自包含进化过程。LLM作为"生成算子"在表达空间中生成并进化benchmark问题，靠进化算子（变异/重组/选择）与初始种群驱动；案例研究用数学表达式最小化问题。初始种子种群的具体来源摘要未细述。
- **支持题型**: 非问答型选择题/输出题/生成题，而是"优化benchmark问题"（连续最小化测试函数），目标算法在该问题上跑优。判据是"目标算法在>80%试验中稳定优于对比算法"——近似于可客观判定的输出题（函数有确定最优），但角色是测试函数而非考试题。
- **迭代**: 有。基于适应度的进化选择循环，进化信号是"区分度"——最大化GA与DE的性能差距以偏向预设目标算法；属强优化（非追求一般难度/覆盖度）。exploratory landscape analysis是事后特征分析，非驱动信号。

## 总体观察

横跨所有方法的最一致gap：
- 几乎所有方法仅在窄领域或任务类型上验证。
- 依赖强大的frontier模型作为生成器或评判者，造成依赖性，限制在低资源或高度专业化评估场景中的适用性。
- 污染问题与评估成本、覆盖范围、任务多样性之间存在根本性权衡，尚无完美解决方案。
