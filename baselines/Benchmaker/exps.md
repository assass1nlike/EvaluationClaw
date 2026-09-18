# 本机运行验证

2026-09-16，BenchMaker 上游提交 `8aaa2b6c644d52580a640c67f3ee024f217eb240`，Python 3.10.12，依赖版本见 `requirements.lock`。

输入：`configs/smoke.json`。没有外部数据集；使用上游 Gradio 示例中的能力描述 `Assess the model's proficiency in algebraic operations using Chinese`，生成中文代数选择题。benchmark 名为 `Math_Smoke`，1 种能力、10 题、4 个选项，参考题数 8、候选数 5；属性分析执行上游的 5 次候选属性生成及合并，难度属性组合、熵筛选、10 次作答校验、答案校准均沿用上游。

本次生成 12 个难度属性，每个属性 4 个取值。上游完整枚举 `4^12=16777216` 个组合，按难度分数排序后保留后半部分，再划分为十档；这一步只在本地计算，不调用 API。

生成模型、作答校验模型和内部裁判均为 DeepSeek API 的 `deepseek-flash`，地址 `https://api.deepseek.com`，无 HF 名称。生成及作答温度 1，内部校准裁判温度 0；每个请求输出上限 16384 tokens，thinking.type=disabled，并发 2、超时 180 秒、SDK 重试 2 次；其余采样参数使用服务默认值。上游自身的重试循环保持原样。

`seed_everything(42)` 固定 Python random、NumPy 和启动时的 PYTHONHASHSEED；API seed=42+请求序号，多候选请求拆为独立请求。远程服务不保证确定性，实际请求和回复保存在 `runs/smoke/requests.jsonl`。上游词云布局自身未显式固定随机种子；它在生成完成后绘制，不影响生成题目。

命令：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u run.py --run smoke > runs/smoke.log 2>&1`。

环境检查：两次启动分别因 NLTK 3.10.3 的代理限制、缺少 SOCKS 依赖而退出，尚未调用模型。日志为 `runs/setup.log` 和 `runs/setup-api.log`。运行依赖固定 NLTK 3.9.1，并包含 socksio。

结果：进程退出码 0，完成 10 道不同的中文代数选择题，导出至 `runs/smoke/benchmark.json`。每题包含题干、选项、答案、推理及 10 次作答记录；共 100 条作答记录，均正常结束，没有截断。属性生成、候选筛选、作答校验、内部答案校准、解码及词汇统计均已实际执行。没有运行额外的外部忠实性、相关性或 embedding 评估。

上游统计：校准比例 0.1，自检平均错误率 0.01，词汇熵 5.7966，不同二元词组数 173，平均题干长度 71.2 个 NLTK token。这些是生成模型的内部统计，不是独立评测结论。完整统计与结构检查分别见 `runs/smoke/summary.txt` 和 `runs/smoke/validation.json`。

续跑：首次进程完成 9 题后，最后一题出现截断回答，本地接口的整组失败判断导致重复生成，因此中止该进程。API 接口采用直接返回原始回答、由上游逐条解析筛选的方式后，使用 `.venv/bin/python -u run.py --run smoke --resume >> runs/smoke.log 2>&1` 续跑。保留前 9 题和属性文件，删除最后一题的空占位；Python/NumPy seed 重新设置为 42，API 请求序号从已有日志最大序号加一开始。具体续跑模型、参数和序号见 `runs/smoke/resumes.jsonl`。首次进程观测到的内存峰值为 15761848 KiB（约 15.0 GiB）。

两次进程共记录 186 条 API 回复，包括 8 条因输出上限截断的候选生成回复；输入 227330 tokens，输出 587139 tokens。上述用量只统计已记录的回复，不含中止时未返回的请求。含中断及续跑的墙钟时间为 2443.8 秒，续跑约 652.4 秒。最终数据 SHA-256：`56dae255ff983e1d6fef4d95a10fddf98e461db1200889229a7b52d0097a8f95`。

## 三组 50 题，thinking 模式

2026-09-16 19:57:41 UTC 启动。上游提交 `8aaa2b6c644d52580a640c67f3ee024f217eb240`；启动前对照该提交在线核验本地 22 个 Python 和生成提示文件，全部一致。Python 3.10.12，依赖见 `requirements.lock`，API 适配、日志和批量启动位于上游目录之外。

三组各包含一个能力，无外部数据集，能力名称与运行名称相同。配置为 `configs/<名称>.json`，描述原样使用：

- `knowledge`：I want to evaluate whether a model can answer broad and expert-level factual questions and correctly apply the relevant knowledge.
- `data-analysis`：I want to evaluate whether a model can interpret semi-structured data and experimental results, perform operations and analysis, and derive the correct conclusion.
- `instruction-following`：I want to evaluate whether a model can satisfy multiple instructions and constraints that are simultaneous, compositional, and out-of-distribution when serving as an AI assistant.

每组 NumberPerAbility=50、OptionNum=4、DemoNum=8、DiverNum=5、seed=42，总目标题量 150。原方法保持属性分析（5 次通用属性候选及合并）、完整难度组合枚举、十档难度选择、参考题选择、5 个候选的词汇熵筛选、10 次作答校验及内部答案校准，再解码和词汇统计。三种需求均生成单项选择题，不扩展为开放回答或执行任务；不运行额外的外部忠实性、相关性、embedding 或 EvaluationClaw LaaJ 评估。

所有模型角色使用 `deepseek-flash`，API 为 `https://api.deepseek.com`。官方文档在启动时将此别名标注为 DeepSeek-V4.1-Flash，无 HF 名称；各请求还记录 API 实际返回的模型标识。max_tokens=200000，thinking.type=enabled，reasoning_effort 未显式指定，服务默认 high。生成及作答传入 temperature=1，内部校准裁判传入 temperature=0；根据 DeepSeek 文档，thinking 模式会忽略 temperature，不能将这些传入值解释为生效的采样温度。其余采样参数使用服务默认值。

每组请求并发上限 20，三个独立进程并行；原流程每轮最多 5 个生成请求或 10 个作答请求，不额外并行不同题目。接口等待超时 3600 秒、SDK 重试 2 次，保留上游重试循环。`seed_everything(42)` 固定 Python random、NumPy 和启动时 PYTHONHASHSEED；每组 API seed=42+本组请求序号。上游词云布局未显式固定种子，仅影响后续图像。远程服务不保证确定性。

启动前进行一次真实 API 预检，使用相同模型、thinking、输出上限、seed=42，问题为 `Which is greater, 9.11 or 9.8? Give a short answer.`，正常返回 `9.8 is greater.` 且包含 reasoning_content；输入 49 tokens、输出 46 tokens、总计 95 tokens。该记录位于 `runs/batch-50/preflight/`，不计入三组正式运行。

启动命令：`tmux new-session -d -s benchmaker-50 -c /data1/zangyihe/EvaluationClaw/baselines/Benchmaker 'exec env PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 /data1/zangyihe/EvaluationClaw/baselines/Benchmaker/.venv/bin/python -u /data1/zangyihe/EvaluationClaw/baselines/Benchmaker/batch.py >> /data1/zangyihe/EvaluationClaw/baselines/Benchmaker/runs/batch-50/launcher.log 2>&1'`。批量入口分别调用 `.venv/bin/python -u run.py --config configs/<名称>.json --run <名称>`。

运行托管于 tmux，服务器 logind 的 KillUserProcesses=false，SSH 断联不终止任务。初始 supervisor PID=1302974，三个任务 PID 分别为 1302980、1302981、1302982；状态与退出码持续写入 `runs/batch-50/status.json`。日志为 `runs/<名称>.log`，配置快照、完整请求回复、thinking 内容、累计 token 用量和最终产物在 `runs/<名称>/`。`usage.json` 只累计收到 usage 的回复，包括失败筛选和重试；中止或超时而未返回的请求不能计入，输出用量包含服务端报告的思考 token。

运行结果：三组均在属性分析之后的难度组合枚举阶段停止，最终题量均为 0；属性文件与 API 请求记录完整保留。2026-09-17 02:40 UTC 左右，管理员依用户要求向 knowledge 和 instruction-following 发送 SIGTERM，退出码均为 -15。随后排查发现 data-analysis 单进程 RSS 为 246979024 KiB（约 235.5 GiB），于 02:48 UTC 左右发送 SIGTERM 释放内存。三组均未重启，实际结束时间与退出码见 `runs/batch-50/status.json`。

难度组合规模：knowledge 为 16 个属性（12 个各 4 值、4 个各 5 值），共 10485760000 种；data-analysis 为 15 个属性、每个 4 值，共 1073741824 种；instruction-following 为 20 个属性、每个 5 值，共 95367431640625 种。上游逐个深拷贝并保存整个笛卡尔积，完整枚举后才排序、截取后半段和分档。枚举过程中旧列表和新列表同时存在；完整组合列表的局部引用也不会因后续截取而全部释放。批量启动器未设内存限制或组合规模检查，因此没有及时阻止超大分配。单纯执行垃圾回收无法解决活跃组合对象的指数增长。

截至停止，knowledge 已记录 103325 tokens，data-analysis 为 123613，instruction-following 为 196530，合计 423468 tokens，均为属性阶段；预检的 95 tokens 单独计算。诊断时的进程状态和属性规模证据保存在 `runs/batch-50/memory-incident.json`。停机后保留既有进度，重新运行前需解决组合展开的资源问题。

## 难度组合等价实现验证

2026-09-17，Python 3.10.12，纯本地计算，无模型调用或新增 token 消耗。测试代码为 `tests/test_difficulty.py`、`tests/verify_difficulty.py`，实现为 `upstream/difficulty.py`；题目生成入口仅替换难度组合的构建语句和对应导入。配置快照记录实现名称及文件 SHA-256。

方法：按属性前缀计算每个整数难度总分的组合数量。每次仍由原有 random.choice 在对应档内抽取排名，先定位该排名的总分，再按最后一个属性优先的枚举顺序逐级定位取值，最终按原属性顺序输出字典。保留全组合空间、同分时稳定顺序、排序后半段、原浮点计算的十档边界、随机调用次数和状态。难度分数采用上游已解析的 1–10 整数；不改变分数解析、属性数量、候选筛选、作答校验、答案校准或模型参数。

等价性命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=42 .venv/bin/python -m unittest discover -s tests -v`。5 项测试全部通过：729 组穷举小规模分数、50 组随机属性规模及分数、5 组空输入/单组合/重复值/同分/奇数规模案例，均与原枚举实现逐项核对完整排序、十档切分及种子 42 的抽样结果和随机状态；额外验证 5^20 个同分组合的 1000 次精确排名恢复，以及实际生成入口十档抽样语句的行为。随机测试用 random.Random(42)，不使用 NumPy 或其他随机库。

资源验证命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=42 .venv/bin/python tests/verify_difficulty.py`。输入为三组已保存的 `runs/<名称>/API_Com_syn/<名称>/deepseek-flash/attr/raw_data/<名称>###<名称>###<名称>/attrs/attr3.json`。每组 seed_everything(42) 固定 Python random 和启动时 PYTHONHASHSEED；不使用 NumPy。进程设置 RLIMIT_AS=268435456 bytes（256 MiB 地址空间），每档抽样 100 次、每组共 1000 次，核对组合总数、档位大小、属性顺序和取值合法性。

| 输入 | 组合数 | 保存的计数项 | 初始化时间 | 初始化及 1000 次抽样时间 | 此步骤 Python 分配峰值 |
|---|---:|---:|---:|---:|---:|
| knowledge | 10485760000 | 860 | 0.0024 s | 0.0566 s | 78320 bytes |
| data-analysis | 1073741824 | 543 | 0.0015 s | 0.0481 s | 42012 bytes |
| instruction-following | 95367431640625 | 1476 | 0.0044 s | 0.0764 s | 109108 bytes |

验证进程报告的 RSS 峰值为 81516 KiB；表中分配峰值由 tracemalloc 记录，均仅说明该本地验证的资源使用，不代表完整生成任务或远程 LLM 的资源使用。结果和源码 SHA-256 保存在 `runs/difficulty-check/results.json`。三组正式实验仍保持停止，既有属性、请求和 token 记录未修改。


## 三组干净重跑

2026-09-17 03:03:22 UTC，依用户要求三路并行从头生成。上一轮三个运行目录、日志及 batch-50 状态目录整体移至 `runs/archive/batch-50-initial/`；上文旧运行记录中 `runs/knowledge`、`runs/data-analysis`、`runs/instruction-following` 和 `runs/batch-50` 对应此归档下的同名路径。此次不读取旧属性、旧题目或旧请求，三个新目录均从空目录创建，未传入 --resume，API 请求序号均从 0 开始。独立冒烟测试与离线等价验证记录保留原位置。

输入为 `configs/knowledge.json`、`configs/data-analysis.json`、`configs/instruction-following.json`，三个英文需求与前述原文完全一致，无外部数据集。每组 1 个能力、NumberPerAbility=50、OptionNum=4、DemoNum=8、DiverNum=5，总目标题量 150。所有模型角色为 DeepSeek API 的 deepseek-flash，地址 https://api.deepseek.com，无 HF 名称；max_tokens=200000、thinking.type=enabled、reasoning_effort 使用服务默认 high、每组请求并发上限 20、等待超时 3600 秒、SDK 重试 2 次。温度仍由上游传入生成/作答 1、内部裁判 0，DeepSeek thinking 模式不应用温度。其余模型参数使用服务默认值。

每组 seed_everything(42) 固定 Python random、NumPy、PYTHONHASHSEED；API seed=42+本组请求序号，远程服务不保证确定性。全流程重新执行属性分析、按完整组合的难度排序与十档抽样、候选熵筛选、10 次作答校验和答案校准、解码及词汇统计。难度组合采用上一节已验证的精确排名读取实现，排序和抽样逻辑不变；实现名称及代码 SHA-256 保存在各组 config.json。

批量入口为每个进程设置 RLIMIT_AS 软硬上限均为 17179869184 bytes（16 GiB 地址空间，包含共享库和线程栈的虚拟地址预留），系统限制独立生效；不是修改模型 token 上限或题目参数。已从三个实际运行进程的 /proc/<PID>/limits 核验该限制。

启动命令：`tmux new-session -d -s benchmaker-50 -c /data1/zangyihe/EvaluationClaw/baselines/Benchmaker 'exec env -u BENCHMAKER_REQUEST_OFFSET PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 /data1/zangyihe/EvaluationClaw/baselines/Benchmaker/.venv/bin/python -u /data1/zangyihe/EvaluationClaw/baselines/Benchmaker/batch.py >> /data1/zangyihe/EvaluationClaw/baselines/Benchmaker/runs/batch-50/launcher.log 2>&1'`。

supervisor PID=3207308；knowledge PID=3207310、data-analysis PID=3207311、instruction-following PID=3207312。状态及退出码写入 runs/batch-50/status.json，每组日志为 runs/<名称>.log，逐次请求及累计用量分别为 runs/<名称>/requests.jsonl、usage.json。三组启动时均约 212 MiB RSS，当前状态为运行中；完成情况以状态文件和通过验证后导出的 benchmark.json 为准。

本轮之前有一次启动检查因记录资源限制时的变量名冲突退出，发生于任何模型请求之前，未产生 token 用量；其日志与目录位于 `runs/archive/batch-50-startup/`。已修正变量名，新运行目录重新创建。


2026-09-17 09:22 UTC 完成情况核查：knowledge 于 04:20:52 UTC 正常退出，data-analysis 于 04:56:29 UTC 正常退出，均导出 50 道不同题目，每题 10 次作答记录。instruction-following 于 04:23:32 UTC 退出码 1：上游生成并解码了 50 道不同题目，但本地四选一标签检查失败，未生成最终 benchmark.json 链接。解码 idx=15、29、39（生成序号 37、47、33）的答案分别为 E、F、E，对应候选确实超出了 A–D，违反 OptionNum=4；这 50 题也都有 10 次作答记录。原始和解码数据保留，本次仅核查，未修改或重跑。证据见 runs/batch-50/completion-check.json。

本轮累计 token：knowledge 输入 1748881、输出 3486295、总计 5235176；data-analysis 输入 4684615、输出 7307914、总计 11992529；instruction-following 输入 3455395、输出 4712738、总计 8168133。三组合计 25395838 tokens，与前轮归档用量分开。


2026-09-17 费用核算：按当日 DeepSeek 官方价格页 https://api-docs.deepseek.com/zh-cn/quick_start/pricing ，Flash 空闲时段每百万 token 缓存命中输入 0.02 元、未命中输入 1 元、输出 4 元，高峰翻倍；高峰为工作日 UTC 01:00–04:00、06:00–10:00。逐请求按实际 usage 的缓存命中/未命中及输出数量计费，thinking 已包含在输出 token，不另加。按请求开始时刻估算，本轮 knowledge 26.55 元、data-analysis 48.85 元、instruction-following 36.58 元，共 111.99 元；12 个请求跨越峰谷边界，若按完成时刻归档，合计为 111.17 元，故报告约 112 元，不能视为服务商账单。

本轮输入 9888891、输出 15506947、总计 25395838 tokens，其中 reasoning_tokens=13446690。包含之前冒烟测试、中止那轮及预检后，全部已记录输入 10185779、输出 16448091、总计 26633870 tokens。冒烟测试没有逐请求时间戳，其费用按峰谷两档给出范围，结合跨界请求的不确定性，全部已记录调用约 115.08–118.33 元。未返回 usage 的中止/失败请求不在本地统计内，实际扣款需以服务商账单为准。计算明细见 runs/batch-50/cost.json。
