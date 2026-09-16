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
