2026-09-17，使用 `deepseek-flash` 完成 history 两轮本机运行，进程退出码 0。生成、作答、判分及第二轮反馈均通过验证。

| 轮次 | 题量 | 答对 | 准确率 |
| --- | ---: | ---: | ---: |
| 1 | 225 | 201 | 89.33% |
| 2 | 225 | 212 | 94.22% |

目标准确率为 10%–30%，两轮实际结果均高于目标。本次验证运行流程，不作为论文结果复现或正式 baseline 对比结论。450 条题目包含 444 种不同的问题文本（按字符串精确比较），保留官方输出。

运行目录：`runs/20260917T130416029536Z/`。`config.json` 保存初始参数和源码差异，`resumes.jsonl` 保存续跑时间及最后一次续跑的源码差异，`requests.jsonl` 保存所有模型提示、回答和用量，`verification.json` 保存核验结果。控制台日志为 `runs/history.log`。

- 官方仓库：`https://github.com/XiangLi1999/AutoBencher`，commit `a05be9f1f776e4658de77e28c6bf22606cea01ab`。出题、被测模型和内部裁判均为 `deepseek-flash`，接口 `https://api.deepseek.com`，thinking disabled。
- 模式为 autobencher，主题 history，`use_helm=no`，2 轮，目标正确率 `0.1--0.3`，seed 42。外部入口的 `seed_everything` 固定 Python、NumPy、PyTorch 和可用 CUDA 种子；Python 哈希种子与 API 请求 seed 同为 42。远程服务是否执行 seed 由服务方决定。
- 数据来自实时英文维基百科，没有使用 HF 数据集。每轮生成候选主题并检索相关页面，筛选 10 个主题，再按 2020-04-01 至 2023-04-07 的页面访问量保留前 5 个。每主题以 20 段为一组，最多处理 3 组，每组请求 15 道问答；实际题量由上游流程决定。已确认第二轮的实际提示词包含第一轮各主题准确率和答对题数。
- 第一轮主题：World War II、Renaissance、Roman Empire、Cold War、French Revolution；第二轮主题：Vietnam War、American Civil War、Byzantine Empire、Industrial Revolution、Mongol Empire。每个主题均生成 45 题，题目、参考答案和维基来源保存在 `wiki.<轮次>.KI_questions.json`。

| 阶段 | temperature | max_tokens | n |
| --- | ---: | ---: | ---: |
| 主题生成、筛选与资料出题 | 0 | 2000 | 1 |
| 被测模型作答 | 0.01 | 50 | 1 |
| 内部判分 | 0 | 3000 | 1 |

模型调用串行执行；未额外设置 top_p，沿用接口默认值。上游 CLI 的 temperature 和 top_p 参数未参与这条流程的实际请求。OpenAI SDK 默认最多重试 2 次，上游外层请求函数最多尝试 5 次，外部转发的连接与读取等等待超时为 300 秒。本地转发只映射模型名并附加 seed、thinking 参数，保留原始提示、采样参数及响应正文。

主运行共 934 次模型调用：34 次生成/筛选、450 次作答、450 次判分，全部返回 HTTP 200。输入 265,157 tokens、输出 35,514 tokens，合计 300,671 tokens。933 次正常结束；一条第一轮作答达到官方 50-token 上限被截断，仍按官方流程判分。两轮题目、作答和判分条数一致，问题与作答逐条对应，判分值均为 true 或 false。

环境为 Python 3.10.12、torch 2.1.2+cpu、transformers 4.37.2、openai 1.12.0、pyautogen 0.2.17、crfm-helm 0.5.0、datasets 2.17.1。完整依赖版本在 `requirements.lock`。134 个已安装包通过依赖兼容性检查，官方入口导入和本地 API 转发检查通过。

经用户确认，官方网络请求应用两个补丁：应用 User-Agent；共享 Session 的 HTTPS 适配器配置 Retry(total=5, backoff_factor=1)，连接与读取等待超时均为 30 秒。补丁文件位于 `patches/`，安装脚本自动应用；已验证从官方原始代码按序应用两个补丁，可以准确重建当前源码。官方代码仅 `tool_util.py` 有上述网络改动。

运行过程中维基 SSL 中断后累计续跑 5 次，复用已完成题目、作答和判分，只清除两个未写入题目的空文件。主运行使用本机代理 `127.0.0.1:7890`，第 4 次续跑尝试 `127.0.0.1:7894`，也遇到 SSL 中断；最后一次应用网络重试修复后，使用原代理完成运行。初始运行及前四次续跑只有 User-Agent 补丁，最后一次续跑同时包含两个获准补丁。

在 `AutoBencher/` 下复现：

```bash
bash setup.sh
.venv/bin/python -u run.py
```

每次新运行会创建独立目录。相同配置的中断运行可续跑：

```bash
.venv/bin/python -u run.py --resume runs/20260917T130416029536Z
```

另进行过一次独立模型连接检查：通过官方生成函数请求 `What is 1 + 1? Reply with only the number.`，temperature 0.01、max_tokens 50、seed 42、thinking disabled，返回 `2`。输入 26、输出 1、合计 27 tokens，日志在 `runs/api-check/requests.jsonl`，未计入上述主运行用量。连接检查和主运行合计 300,698 tokens。本机模拟接口检查验证了模型名转发、参数保留及用量记录，不调用真实模型。准备检查摘要在 `runs/preflight/checks.json`。

按本次查询的 DeepSeek 官方价格估算费用（https://api-docs.deepseek.com/zh-cn/quick_start/pricing）：所有请求发生在北京时间 2026-09-17 21:03–21:47，属于空闲时段。每百万 tokens 的人民币单价为缓存命中输入 0.02 元、未命中输入 1 元、输出 4 元。主运行缓存命中输入 65,792、未命中输入 199,365、输出 35,514 tokens，估算 0.34273684 元；连通性检查额外 0.00003 元。合计 300,698 tokens，估算 0.34276684 元（约 0.343 元）。按官网美元单价独立计价为 0.051415026 美元。统计明细在运行目录的 `cost.json`，查询到的官方中英文价格页正文分别保存为 `pricing-zh.txt` 和 `pricing-en.txt`；该金额为标价计算值，未读取账户实际账单。

四需求并行实验，2026-09-17。四段用户原始需求逐字保存在 `configs/four-needs.json`，单轮配置快照在 `runs/batch-20260917T153233865694Z/archive/iterations-1/config.json`，分别对应 knowledge、reasoning、mathematics、computer-science。四个独立进程均使用现有维基问答入口，各运行 1 轮；模型均为 deepseek-flash，接口 https://api.deepseek.com，目标正确率 0.1--0.3，seed 42，thinking disabled。其余提示、采样参数、维基筛选与两个获准网络补丁同上。每个进程调用 seed_everything，并固定 Python 哈希与 API 请求种子。

启动命令：`.venv/bin/python -u batch.py configs/four-needs.json`，托管于 tmux 会话 `autobencher-four-needs`。批次目录为 `runs/batch-20260917T153233865694Z`；每个任务独立保存题目、作答、判分、请求日志、源码版本和配置，控制台日志为批次目录内 `<任务名>.log`，状态及退出码写入 `status.json`。四个任务均传入完整原始需求，不按需求关键词切换入口。

四需求批次已完成所有题目的生成、作答和官方判分。三组通过外部核验；knowledge 组的一个裁判回复未给出 true/false，外部核验因此退出码为 1。官方原始结果保留，未重判或改写判分。

| 任务 | 题量 | 官方答对数 | 官方准确率 | 核验 | Tokens | 估算费用（元） |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| knowledge | 195 | 177 | 90.77% | 1 条无效判分 | 122,905 | 0.132867 |
| reasoning | 195 | 133 | 68.21% | 通过 | 125,767 | 0.155627 |
| mathematics | 225 | 195 | 86.67% | 通过 | 129,670 | 0.159633 |
| computer-science | 225 | 192 | 85.33% | 通过 | 132,284 | 0.160177 |

总计 840 题、510,626 tokens，按已查询的官方空闲时段价估算 0.608304 元。完整分项、缓存用量和核验状态见批次目录 `summary.json`。全部模型请求返回 HTTP 200，四组题目、作答和判分逐条对应。

knowledge 的 List of national capitals 页面仅有 8 段可用资料，reasoning 的 Logic puzzle 页面仅有 13 段，两者各生成一批 15 题，因此这两组各为 195 题；其余主题各生成三批共 45 题。没有发生出题解析失败。

knowledge 中氦原子序数一题的参考答案和模型回答均为 2，但裁判回复要求提供问题、预测及参考答案，没有给出判定。官方将该非 true 值计入未答对，得到 177/195 的原始准确率；有效判分为 177 条 true、17 条 false，无效判分 1 条。外部核验保留失败状态，详情见 `summary.json` 的 invalid_judgments。

四组触及原始输出长度上限的回复数分别为：knowledge 2, reasoning 0, mathematics 8, computer-science 2。完整请求和结束原因保存在各组 requests.jsonl。

用户要求在四需求已有结果上追加第二轮，被测模型使用 deepseek-flash。第一轮的出题模型、被测模型和裁判本来均为 deepseek-flash，因此直接复用原始题目、作答和评分。四个任务总轮数从 1 改为 2，其他参数、模型、原始需求和官方源码均保持一致。官方入口读取第一轮缓存，将其逐主题正确率汇总到第二轮选题提示词，并执行第二轮生成、作答与判分。knowledge 第一轮那条无效裁判回复保留，按官方原始统计进入反馈。

启动命令：`.venv/bin/python -u batch.py configs/four-needs.json --resume runs/batch-20260917T153233865694Z`，四进程并行，tmux 会话 `autobencher-four-needs-r2`。单轮批次配置、状态和汇总已保存至批次目录 `archive/iterations-1/`；每组单轮配置和已通过的核验分别保存为 `config.iterations-1.json`、`verification.iterations-1.json`。第一轮 56 个产物的 SHA-256 保存于批次目录 `first-round-sha256.json`，用于确认续跑没有改写第一轮结果。

四需求第二轮已完成生成、作答和官方判分；已检查四组第二轮真实选题提示词，均含第一轮逐主题正确率及答对题数。第一轮 56 个产物的 SHA-256 均保持一致。

| 任务 | 第二轮题量 | 第二轮官方答对数 | 第二轮官方准确率 | 第二轮无效判分 | 新增 tokens | 新增估算费用（元） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| knowledge | 225 | 207 | 92.00% | 0 | 149,284 | 0.167137 |
| reasoning | 195 | 159 | 81.54% | 1 | 122,342 | 0.146875 |
| mathematics | 225 | 204 | 90.67% | 0 | 136,279 | 0.163969 |
| computer-science | 225 | 177 | 78.67% | 0 | 135,896 | 0.164414 |

第二轮新增 870 题，两轮累计 1710 题。新增 543,801 tokens，估算 0.642396 元；两轮累计 1,054,427 tokens，估算 1.250700 元。沿用前述官方价格，按实际请求时间区分高峰和空闲时段。主汇总为批次目录 `summary.json`；第一轮原始汇总在 `archive/iterations-1/summary.json`。

knowledge 第二轮核验通过，整组仍因第一轮已有的一条无效判分退出码为 1；reasoning 第二轮有一条裁判仅回复要求提供问题及答案、未给出 true/false，整组核验退出码为 1；mathematics 和 computer-science 两轮完整核验通过，退出码为 0。两条无效裁判回复均保留原样，官方统计按非 true 计入未答对。所有题目、参考答案、作答和判分逐条对应，全部必需内容存在；模型请求均返回 HTTP 200。

knowledge 第二轮主题及题量：World War I: 45, Ancient Egypt: 45, Greek mythology: 45, Plate tectonics: 45, Nobel Prize in Literature: 45。

reasoning 第二轮主题及题量：Deductive reasoning: 45, Syllogism: 45, Rule of inference: 45, Causal inference: 30, Cognitive map: 30。

mathematics 第二轮主题及题量：Calculus: 45, Graph theory: 45, Topology: 45, Partial differential equation: 45, Mathematical logic: 45。

computer-science 第二轮主题及题量：Operating system: 45, Database: 45, Deep learning: 45, Reinforcement learning: 45, Software testing: 45。

复现相同四需求两轮配置：`.venv/bin/python -u batch.py configs/four-needs.json`。单独扩展已有任务可用 `.venv/bin/python -u run.py --resume runs/<任务目录> --iterations 2`；未指定 --iterations 时沿用保存的轮数。

新增四需求三轮并行实验，北京时间 2026-09-18 00:05 启动。四段原始需求逐字保存在 `configs/four-more-needs.json`，任务为 data-analysis、instruction-following、long-context、multilingual。四个独立进程均使用官方 `wiki_autobencher.py` 入口，完整需求作为 theme，各运行 3 轮；每轮出题、作答和判分后，将已有轮次逐主题正确率用于后续选题。

出题、被测模型和内部裁判均为 deepseek-flash，接口 https://api.deepseek.com，thinking disabled，目标正确率 0.1--0.3，seed 42。每个进程执行 seed_everything 固定 Python、NumPy、PyTorch、CUDA 种子，同时固定 Python 哈希及 API 请求种子。资料源为实时英文维基百科；候选筛选、访问量窗口、每批资料和题量、各阶段 temperature、max_tokens、n、重试与超时设置均同上。官方提交及两个已批准的网络补丁不变。

启动命令：`.venv/bin/python -u batch.py configs/four-more-needs.json`，tmux 会话 `autobencher-more-needs`。批次目录为 `runs/batch-20260917T160537909079Z/`，保存配置、状态和四个独立任务目录；各任务保存三轮题目、作答、裁判结果及完整模型请求用量。

新增四需求均已完成三轮生成、作答与官方判分，共 2,445 题。已逐条核对题目、参考答案、被测回答和评分的对应关系及必需内容；已用官方汇总函数重建反馈，确认四组第二、三轮的候选生成和筛选提示分别包含第一轮、前两轮累计逐主题评测反馈。详细结果见批次目录 `summary.json`。

下表每轮为官方答对数/题量（准确率）。

| 任务 | 第一轮 | 第二轮 | 第三轮 | Tokens | 估算费用（元） |
| --- | --- | --- | --- | ---: | ---: |
| data-analysis | 170/210（80.95%） | 162/210（77.14%） | 171/210（81.43%） | 382,112 | 0.485329 |
| instruction-following | 175/195（89.74%） | 169/195（86.67%） | 207/225（92.00%） | 399,094 | 0.399780 |
| long-context | 127/195（65.13%） | 118/195（60.51%） | 102/180（56.67%） | 336,171 | 0.407632 |
| multilingual | 135/210（64.29%） | 153/195（78.46%） | 161/225（71.56%） | 392,430 | 0.470459 |

全部 5,077 次模型请求均返回 HTTP 200；输入 1,278,370 tokens（缓存命中 449,916、未命中 828,454），输出 231,437 tokens，合计 1,509,807 tokens。请求均发生在空闲时段，按此前保存的 DeepSeek 官方标价（每百万 tokens：命中输入 0.02 元、未命中输入 1 元、输出 4 元）估算为 1.76320032 元。价格快照见 `runs/20260917T130416029536Z/pricing-zh.txt`，计价明细见本批次 `summary.json`。

data-analysis、multilingual 三轮核验通过，退出码 0。instruction-following、long-context 均完成三轮，但第二轮各有一条无效裁判回复，最终核验退出码 1。前者为日本首都题，参考答案与被测回答均为 Tokyo；后者为 Georgia Guidestones 所在地题，参考答案与被测回答均为 Elbert County, Georgia, United States。两条裁判回复均要求提供问题及答案，未给出 true/false。保留原始回复和核验失败状态，官方按非 true 计入未答对。

触及官方输出长度上限的回复数：data-analysis 24、instruction-following 7、long-context 13、multilingual 4；保留原始输出。各轮主题与题量保存在 `summary.json` 的 categories，完整提示和响应在各任务的 `requests.jsonl`。本批次没有中断续跑，官方源码继续仅含两项已批准的网络修复。

八需求八轮并行实验，北京时间 2026-09-18 01:21 启动。八段用户原始需求逐字保存在 `configs/eight-needs.json`，依次为 knowledge、reasoning、mathematics、computer-science、data-analysis、instruction-following、long-context、multilingual。本次创建全新批次，从第一轮开始，每个任务总计 8 轮，8 个独立进程并行运行。

出题、被测模型、裁判均为 deepseek-flash，接口 https://api.deepseek.com，thinking disabled；官方入口 wiki_autobencher.py，exp_mode=autobencher，use_helm=no，目标准确率 0.1--0.3。seed_everything 固定 Python、NumPy、PyTorch、CUDA 的种子为 42，Python 哈希和 API 请求种子同为 42。每轮完成生成、作答、判分，并把已有各轮累计逐主题结果用于下一轮选题。资料为实时英文维基百科，无 HF 数据集；主题筛选、访问量窗口、资料批次和题量及采样配置同前述实验：选题/出题 temperature=0、max_tokens=2000；被测作答 temperature=0.01、max_tokens=50；判分 temperature=0、max_tokens=3000；n=1。官方提交 a05be9f1f776e4658de77e28c6bf22606cea01ab，仅沿用已批准的 User-Agent 和网络重试修复；其余配置不变，依赖版本见 requirements.lock。

启动命令：`.venv/bin/python -u batch.py configs/eight-needs.json`，托管于 tmux 会话 `autobencher-eight-needs`。产物目录 `runs/batch-20260917T172122472021Z/`；批次 config.json、status.json 保存配置与任务状态，各任务目录保存逐轮题目、作答、判分、源码信息和 requests.jsonl 完整请求用量，控制台日志为批次目录内 <任务名>.log。已确认 8 个进程均运行、各组实际配置为 8 轮且三个模型角色均为 deepseek-flash，每组初始模型请求均返回 HTTP 200。启动时实验尚在进行，最终完成状态以 status.json 和逐轮产物为准。

八需求八轮批次进度检查：knowledge、reasoning、mathematics、computer-science、data-analysis、multilingual 已完成 8 轮；instruction-following 完成 3 轮，long-context 完成 5 轮。两组分别在第 4、6 轮候选生成中达到官方 2000-token 输出上限，JSON 被截断，解析报错退出。失败状态及选题提示/输出快照保存在 `runs/batch-20260917T172122472021Z/archive/resume-20260917T181338Z/`，完整请求始终保存在 requests.jsonl。使用 `.venv/bin/python -u batch.py configs/eight-needs.json --resume runs/batch-20260917T172122472021Z` 续跑，tmux 会话 autobencher-eight-needs-resume；已完成部分复用官方缓存，未修改输出上限、提示、解析代码或原始判分。六个已完成组共 7 条无效判分（reasoning 1、mathematics 2、computer-science 1、multilingual 3），按官方结果保留，相关组最终核验失败。

八需求八轮批次已全部完成，共 64 个完整轮次、13500 题。已核对所有轮次题目、作答和判分逐条对应且必需内容完整；已用官方汇总函数重建历史反馈，确认每组第 2–8 轮候选生成和筛选提示均包含此前全部轮次的累计逐主题结果，包括续跑后的轮次。详细结果、主题题量、无效裁判原文、用量及估算费用见 `runs/batch-20260917T172122472021Z/summary.json`。

下表各轮为官方准确率，非 true 判分按官方逻辑计入未答对。

| 需求 | 题量 | 第1轮 | 第2轮 | 第3轮 | 第4轮 | 第5轮 | 第6轮 | 第7轮 | 第8轮 | 无效判分 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| knowledge | 1710 | 95.90% | 95.11% | 90.22% | 94.22% | 92.89% | 81.54% | 86.67% | 91.79% | 0 |
| reasoning | 1575 | 66.67% | 67.14% | 73.33% | 71.11% | 67.56% | 76.11% | 66.67% | 80.61% | 1 |
| mathematics | 1620 | 88.89% | 87.56% | 88.89% | 84.89% | 71.43% | 77.78% | 75.76% | 69.09% | 2 |
| computer-science | 1740 | 88.89% | 84.44% | 87.56% | 90.95% | 73.33% | 85.71% | 84.00% | 81.03% | 1 |
| data-analysis | 1680 | 80.44% | 79.05% | 84.76% | 84.44% | 74.76% | 80.00% | 79.56% | 80.61% | 0 |
| instruction-following | 1800 | 93.33% | 89.33% | 89.33% | 90.22% | 81.33% | 80.89% | 83.11% | 81.78% | 0 |
| long-context | 1665 | 92.44% | 76.00% | 41.90% | 46.19% | 41.82% | 40.89% | 39.49% | 65.71% | 2 |
| multilingual | 1710 | 78.57% | 84.44% | 72.00% | 76.00% | 70.22% | 80.00% | 62.86% | 75.71% | 3 |

合计 28,030 次模型请求，HTTP 非 200 次数为 0；输入 7,187,412 tokens，输出 1,298,894 tokens，总计 8,486,306 tokens，包含中断的截断请求及续跑请求。按已保存官方价格快照和逐请求时间估算 9.62519058 元，未读取账户账单。

共 9 条无效裁判回复，均保留原样。knowledge、data-analysis、instruction-following 最终核验通过；其他五组最终仅因无效裁判回复未通过枚举值核验，八轮均已完成。指令遵循和长上下文在重新请求失败选题步骤后完成剩余轮次，未修改官方实验逻辑或配置。

八需求八轮的全部 13,500 题已上传至 HF dataset `assassinlike/b635`，配置 `autobencher`、split `test`。首次提交 27384002f188bd7c55687348a69ef2f4d4abec23；按用户要求整理后的提交为 276b1e6362449cb3706682bd21b2b14184c8c259。根目录仅保留 .gitattributes、README.md、gym-anything/、autobencher/。Gym-Anything 原有 591 个文件按字节保持原样移至独立目录，路径以 gym-anything/ 为基准；新增 gym-anything 配置并保留 default 别名。AutoBencher 按八组保存 JSONL，保留全部原始题目字段、需求、轮次、参考答案、模型提示和作答、裁判原文及判定、有效判分标记与官方正确性结果；无去重或删题。远端 autobencher/provenance/ 保存配置、汇总和 SHA-256 清单。本地导出及上传记录在批次目录 hf-export/。远端加载核验通过：autobencher 13,500 行、64 个任务轮次组合、唯一行 ID、9 条无效判分；gym-anything 与 default 均为 51 行。上传未包含凭据。

八需求八轮准确率表已从各轮原始 compare_answers.json 重新统计并输出到 `/data1/zangyihe/autobencher-results.md`（相对 baselines 工作目录为 `../../autobencher-results.md`）。行按八个用户需求排列，列为第 1–8 轮，百分比保留两位小数，9 条无效判分遵循官方规则计入未答对。

固定第一轮题目评测 Qwen 实验。题集取自八需求八轮批次 `runs/batch-20260917T172122472021Z/` 的八组 `wiki.1.KI_questions.json`，共 1,725 题，知识 195、推理 195、数学 225、计算机科学 225、数据分析 225、指令遵循 225、长上下文 225、多语言 210。题目和参考答案原样复用，不重新生成。被测模型 qwen3.8-27b，接口 https://dashscope.aliyuncs.com/compatible-mode/v1，enable_thinking=false，temperature=0.01，max_tokens=50，n=1，seed=42，并发上限 128。裁判 deepseek-flash，接口 https://api.deepseek.com，thinking disabled，temperature=0，max_tokens=3000，n=1，seed=42，并发上限 8。沿用官方 system/user 提示、判分提示及解析规则，只有被测模型及供应商 thinking 参数变化。1,725 题的实际作答与裁判请求模板已逐一与原始请求对比一致。

外部入口 `evaluate_fixed.py` 实现固定题集的并发评测，不修改官方源码。每条回答与判分即时写入，失败后可用 --resume 复用成功结果；只对传输错误及 HTTP 408/409/429/5xx 最多尝试 3 次，等待 1、2 秒，单请求超时 300 秒；不重试无效裁判判定。复用 seed_everything 固定 Python、NumPy、PyTorch、CUDA 种子，并固定 Python 哈希种子。配置 `configs/qwen-first-round.json`。启动命令 `.venv/bin/python -u evaluate_fixed.py configs/qwen-first-round.json`，tmux 会话 autobencher-qwen-first-round，日志 runs/qwen-first-round.log。新建独立 runs/eval-<UTC时间>/ 目录，保存配置、原题副本与 SHA-256、原始请求响应及用量、逐题回答判分、进度及汇总。凭据只保存在被 Git 忽略且权限 0600 的 .env。

固定第一轮 Qwen 评测已完成，目录 `runs/eval-20260918T165258109475Z`。结果如下，DeepSeek 列来自相同题集已有第一轮评测：

| 组别 | 题量 | Qwen 答对 | qwen3.8-27b | deepseek-flash | 差值（百分点） |
| --- | ---: | ---: | ---: | ---: | ---: |
| 知识 | 195 | 177 | 90.77% | 95.90% | -5.13 |
| 推理 | 195 | 113 | 57.95% | 66.67% | -8.72 |
| 数学 | 225 | 194 | 86.22% | 88.89% | -2.67 |
| 计算机科学 | 225 | 189 | 84.00% | 88.89% | -4.89 |
| 数据分析 | 225 | 173 | 76.89% | 80.44% | -3.56 |
| 指令遵循 | 225 | 202 | 89.78% | 93.33% | -3.56 |
| 长上下文 | 225 | 198 | 88.00% | 92.44% | -4.44 |
| 多语言 | 210 | 146 | 69.52% | 78.57% | -9.05 |
| 合计 | 1725 | 1392 | 80.70% | 85.86% | -5.16 |

Qwen 作答并发上限 128，temperature=0.01、max_tokens=50、enable_thinking=false；裁判并发上限 8，temperature=0、max_tokens=3000、thinking disabled；n=1、seed=42。Qwen 25 条回答达到输出上限，按原始输出判分。推理与数学各有一条无效裁判回复，完整回复见 summary.json。

Qwen 用量 106,716 tokens（输入 94,370、输出 12,346）；DeepSeek 裁判用量 628,105 tokens（输入 562,866、输出 65,239），合计 734,821 tokens。全部 3,450 次请求 HTTP 200，无连接重试或中断续跑。

已逐题验证题目/作答/判分对应关系、原始参考答案、源文件 SHA-256 和副本字节一致；全部请求返回模型名与配置一致。核验结果 verification.json、逐组及异常判分汇总 summary.json、易读对比表 results.md 均位于运行目录。官方源码未修改。

固定八组第一轮题目评测 gpt-5.6-sol。复用 `runs/batch-20260917T172122472021Z/` 八组第一轮共 1,725 题及参考答案，题目副本、SHA-256 和原始提示保存在独立评测目录。被测接口 https://www.rightapi.ai/v1，模型 gpt-5.6-sol，最大并发 8（重试也占用同一并发槽），temperature=0.01、max_tokens=50、n=1、seed=42，不附加供应商专有 thinking 参数。裁判沿用 deepseek-flash（https://api.deepseek.com），并发 8，temperature=0、max_tokens=3000、n=1、seed=42、thinking disabled。作答提示、判分提示和解析逻辑同前次 Qwen 固定题集评测。Python、NumPy、PyTorch、CUDA 与 Python 哈希种子通过现有 seed_everything 和启动逻辑固定为 42。

配置 `configs/gpt-first-round.json`，入口 `evaluate_fixed.py`，命令 `.venv/bin/python -u evaluate_fixed.py configs/gpt-first-round.json`。单请求超时 300 秒；传输错误或 HTTP 408/409/429/5xx 最多 3 次尝试（2 次重试），等待 1、2 秒；无效裁判判定不重试。首题先验证作答及判分，再并发执行其余题目。tmux 会话 autobencher-gpt-first-round，日志 runs/gpt-first-round.log。凭据在被 Git 忽略且权限为 0600 的 .env，产物、完整请求响应和用量写入独立 runs/eval-<UTC时间>/ 目录。
