2026-09-16：同时启动三个独立的官方 Benchmark-Agent 流程，需求见 `user_queries/knowledge_50.json`、`user_queries/data_analysis_50.json`、`user_queries/instruction_following_50.json`，各目标 50 题。框架调用并发为 3，API 并发沿用官方默认值。生成结果以官方验证实际通过数量为准，不补题。

本批次已在转换阶段停止，尚未完成生成或自测。实测发现纯工具规划器硬编码 `gpt-5.1`，绕过模型配置，数据分析与指令遵循运行产生了失败调用；已将该规划器和网页检索工具的默认模型改为读取配置，保留显式模型覆盖和原有工具参数。随后单独测试 DeepSeek 原生网页检索，接口返回 HTTP 400：`tools[0].type: unknown variant web_search, expected function`。

停止前已记录 token：知识 793,633，数据分析 1,444,437，指令遵循 1,055,321，合计 3,293,391；另有 135 次 gpt-5.1 失败调用无用量返回。终止时的在途请求可能未记录用量，因此这些数值不是完整账单。进程被终止，原始 token 汇总保留 `running` 状态，不能误解为仍在运行；批次状态见 `batch.json`。接口能力探测单独记在批次目录的 `setup_probe/`。

生成、转换、验证、被测模型与开放题判分均使用 `openai/deepseek-flash`，接口为 `https://api.deepseek.com`，模型设置见 `utils/resources/models.yaml`。生成阶段所有提示词、随机性和参数沿用仓库当前版本；没有额外设置随机种子，因此不保证逐题可复现。数据池为 HF `General-Level/General-Bench-Openset` 的 `nlp` 和 `image/comprehension`，336 个数据集，资源清单为 `utils/resources/dataset_cards.yaml`。

启动方式（使用 `benchmaker-baseline` 环境）：

```bash
python local/run_batch.py cache/batch_20260916_deepseek_flash_50
```

缓存根目录为 `cache/batch_20260916_deepseek_flash_50/`。`batch.json` 记录实际进程与退出状态，每个需求的官方产物保存在 `user_queries/<需求名>/`。各进程的独立完整终端日志保存在批次根目录。生成 token 统计位于各需求的 `token_usage/`。

自测是独立后处理，不属于官方生成算法：全部生成任务结束后并行评测三个结果集。被测模型只接收导出题目的 `input`；对于 `choice` 子任务要求只输出选项字母并严格匹配参考字母，其他类型按题目指令自然回答，再使用独立的同模型请求检查答案正确性和约束满足情况。自测 temperature=0、max_tokens=12000、thinking 使用服务商默认值，每个需求使用 10 个工作线程，无额外全局 API 限制；脚本不额外重试失败请求。截断响应、调用失败和无法解析的判分单独计数，不伪装成已评分题目。

自测提示词、配置、逐题响应、判分理由、汇总分别保存在 `selftest/config.json`、`selftest/items/`、`selftest/results.json`、`selftest/summary.json`；回答与判分的 token 消耗分别位于 `selftest/answering/` 和 `selftest/judging/`。开放题结果属于同模型判分，没有独立人工核验。token 汇总只包括 API 返回且已记录的用量，未知消耗单列。

2026-09-17：网页搜索改用 `openai/responses/gpt-5.6-luna`，接口为 `https://api.fangcunleap.com/azure-gateway/v1`，使用服务端原生 `web_search`。其他阶段及自测仍使用 DeepSeek。搜索提示词、medium 上下文、强制检索、180 秒超时、12000 输出 token 上限和原 JSON 重试流程沿用仓库实现。Luna 不接受 temperature，使用服务端默认值；未指定 reasoning，探测响应报告 medium。没有自建搜索后端，没有额外固定随机种子。

配置探测保存在 `cache/luna_search_probe/`。首次直接 Responses 探测 NIST 秒定义执行了搜索，但被网关的 protected_material_text 过滤，返回 incomplete，usage 为输入 4325、输出 42、合计 4367 tokens，网关报告 1 次搜索；这次直接探测不在后续 token 记录器内。另有 4 次 temperature 参数不兼容的 HTTP 400 请求（其中 3 次由框架重试并记录，1 次直接诊断），均无用量。NASA 行星温度问题通过框架调用成功，记录输入 8663、输出 295、合计 8958 tokens，网关报告 2 次搜索；检索来源包括 NASA Venus、Mercury 与太阳系温度页面。图片探测使用 HF `General-Level/General-Bench-Openset` 的 `image/comprehension/WoodAnomalyDetection/images/0.png`，验证图片输入、原生检索及有来源的回答，逐次用量与结果见同目录。14 项离线测试通过，覆盖接口转换、两套凭据隔离、未完成响应及缺失搜索的重试、token 统计与既有自测行为。

图片探测记录输入 16372、输出 830、合计 17202 tokens，网关报告 4 次搜索，最终回答区分图中的木纹与斜向划痕，并引用 USDA Forest Products Laboratory 文献。独立 DeepSeek 路由探测成功，记录 98 tokens。

正式重跑目录为 `cache/batch_20260917_deepseek_luna_50/`，命令为 `python local/run_batch.py cache/batch_20260917_deepseek_luna_50`。三个需求、各目标 50 题、数据池、框架并行数 3、API 不额外限流、不补题、生成后 DeepSeek 自测的配置同上。该批次从头运行，未复用中断批次的规划或样本；前次中断和配置探测的费用独立保留。运行 PID、退出码、实际题数及起止时间以本批次 `batch.json` 为准。

该批次于 2026-09-17 14:32:17 UTC 完成，三个生成进程和三个自测进程均以 0 退出。知识问答导出 48 题，自测 47/48；数据分析导出 48 题，自测 44/48；指令遵循导出 46 题，自测 46/46；全部导出题目均完成评分。生成加自测已记录 token 分别为 3,437,672、4,652,923、5,218,559，总计 13,309,154。另有 10 次 Luna 429 无用量，完整账单仍不能从记录中确定。这些结果使用单搜索 key 和原先无退避的策略，不受后续重试修改影响。

四搜索 key 配置验证：`python local/check_search_keys.py --output cache/search_key_probe`，模型、网关、medium 原生搜索、强制搜索、12000 输出 token 上限和服务端默认 reasoning/temperature 同上。固定 4 并发，按单 key／四 key／四 key／单 key 顺序，每组 4 请求，所有请求使用相同的 NASA 行星温度查询，每请求仅尝试一次、不重试、未指定随机种子。记录在 `cache/search_key_probe/token_usage/20260917T155002Z_b0535e96/comparison.json`。16 次请求均 HTTP 200 且 completed，三个新增 key 各完成 2 次搜索回答；总计 137,475 tokens，网关报告 28 次搜索请求。响应头均报告 limit-requests=250、limit-tokens=250000。四组耗时分别为 9.043、23.405、5.731、6.588 秒；搜索内容、缓存和后台负载未控制，且没有触发限流，不能据此判断 key 是否共享额度或声称多 key 提高吞吐量。

后续运行使用四 key 轮转及 429 退避，配置和预算见 `local/README.md`。重试逐请求计入 token 记录，不重复统计外层调用；核心规划、转换、验证、题量和自测规则保持原样。26 项离线测试通过，覆盖服务端等待提示、预算、重试耗尽、并行 key 分配、逐请求用量、接口转换及既有流程。

四 key 配置下的框架搜索接口集成探测成功，调用 `local/check_web_search.py`，问题为 NASA 对金星高温的官方解释；结果与逐请求记录位于 `cache/search_key_probe/integration/token_usage/20260917T155125Z_88647142/`，1 次模型响应，输入 4679、输出 330、合计 5009 tokens。真实探测未触发 429，退避等待和耗尽行为由模拟 HTTP 429 的离线测试验证。

2026-09-17 再次运行：`python local/run_batch.py cache/batch_20260917_retry_50`。三个需求各目标 50 题，3 个框架进程并行，API 不额外限流；模型、数据集与自测规则沿用上一轮。搜索采用四 key 轮转，429 最多尝试 6 次，重试预算 180 秒，服务端等待提示优先，否则 2 秒起步指数退避加抖动。未额外设置随机种子，不复用此前生成缓存。配置与需求快照位于该批次 `configuration/`。本轮接受服务端内容过滤，重点检查基础设施故障是否在内部重试后仍返回框架，从而触发重新规划；检查依据是实际工具执行历史、逐请求错误及响应状态，不将进程正常退出直接视为没有轨迹影响。发现问题时先分析具体根因，变更和受影响样本另行记录。

该批次于 17:35:32–17:56:41 UTC 运行，三个生成进程和三个自测进程均以 0 退出。知识问答导出 47 题，自测 42/46 已评分、1 题未完成；数据分析导出 47 题，自测 45/47；指令遵循导出 50 题，自测 45/48 已评分、2 题未完成。自测仍采用严格选项匹配或独立的同模型判分，未额外补题或重跑。

逐请求记录中只有知识问答第一子任务的 7 次 HTTP 429，均通过内部退避恢复；该子任务的 22 个候选题全部完成转换，没有失败工具步骤。全批次原生搜索返回 26 次 completed，没有 incomplete 或内容过滤；没有发现基础设施错误进入框架。三个内容驱动的重新生成分别修正上下文字段类型、约束违反情境和选项泄漏提示，属于官方规划逻辑，没有对应 API 错误。本轮未据此修改核心流程、重试实现或模型参数，仅增加只读审计脚本 `local/audit_run.py` 和实验记录。

转换产物数量为知识 48、数据分析 50、指令遵循 50；验证分别拒绝 1、3、0 题。知识的验证拒绝原因是答案缺乏可核验证据；数据分析的三个拒绝原因是答案与表格或计算不一致。知识第二子任务另有 `8021676b::159` 和 `df805e9d::59` 未进入转换产物，已保存步骤均成功，且该子任务没有 API 异常；官方缓存不保存最终放弃原因，不能确定其具体退出分支。

三条自测未完成记录均为 `finish_reason=length`、最终答案为空；对应回答请求各消耗 12,000 个输出 token，全部报告为 reasoning tokens，达到原配置上限。涉及知识问答 index 41（`b7ea85be::39`）以及指令遵循 index 9、12（源 idx 151、146）。这是被测模型在既定 token 预算内未完成作答，不是基础设施异常，也没有回流到 benchmark 生成流程；保留未评分状态，不调整预算或选择性重测。

生成加自测已记录 token：知识 3,612,060，数据分析 4,361,252，指令遵循 4,766,463，合计 12,739,775。7 次 429 没有返回用量；记录器没有写入错误，但这些总数仍不等同于完整账单。逐需求结果、审计证据与限制汇总见 `cache/batch_20260917_retry_50/audit.json`，进程状态见同目录 `batch.json`。

2026-09-17 输出预算探测：向 `https://api.deepseek.com` 的 `deepseek-flash` 发送单条 `Reply with OK only.`，`max_tokens=300000`、timeout=60、SDK 重试关闭，其余采样与 thinking 参数采用服务端默认值，未设 seed。请求成功且 `finish_reason=stop`，输入 35、输出 11（含推理 9）、合计 46 tokens；记录位于 `cache/deepseek_budget_probe/token_usage/`。这验证接口接受 300,000 上限，不代表请求实际生成了这么多 token。官方接口文档列出最大输出 393,216、上下文 1M；`max_tokens` 控制推理和最终答案共享的生成预算。来源：`https://api-docs.deepseek.com/api/create-chat-completion` 和 `https://api-docs.deepseek.com/quick_start/pricing`。

按用户确认，后续所有已配置的 DeepSeek 调用采用 300,000 输出 token 上限，统一配置于 `utils/resources/models.yaml`，覆盖同步／异步 Agent、工具、生成、转换、验证、自测回答与判分。Luna 搜索仍为 12,000；各阶段原有 thinking、提示词、超时、重试与流程保留。此前批次的结果和配置快照保留，本次未重跑实验。31 项离线测试通过，包括请求层预算覆盖、自测回答与判分及记录的一致性，以及搜索预算、重试和用量统计的回归检查。

随后按用户要求提高超时：所有已配置的 DeepSeek 请求统一为 7,200 秒（2 小时），覆盖同步／异步 Agent、工具、自测回答和判分；转换阶段连续无样本完成的终止阈值为 86,400 秒（24 小时），为样本内多轮调用及重试留出等待时间。配置位于 `utils/resources/models.yaml`，自测记录实际请求超时。Luna 搜索的 180 秒请求超时与重试预算保持原配置。31 项离线测试通过，验证原局部 90 秒超时被模型配置覆盖、自测请求与记录一致、搜索超时独立；新进程加载仓库配置实测得到 7,200／86,400 秒。此次没有重新发起实验或修改历史结果。

2026-09-17 四 key 搜索并发探测：`local/check_search_concurrency.py`，产物根目录 `cache/luna_concurrency_20260917/`。使用已配置的四个 key，按请求序号模 4 分配，`gpt-5.6-luna`、原网关、原生 `web_search`、medium、强制搜索、12,000 输出 token、180 秒请求超时；SDK 与应用自动重试均关闭，reasoning/temperature 使用服务端默认值，未设 seed。固定查询为 NASA 关于金星与水星何者最热及原因的官方来源，完整请求写入每次探测的 `concurrency.json`。每轮同时发起该档数量的请求，独立记录开始／结束时间、客户端在途峰值、HTTP 状态、搜索完成情况、用量、脱敏错误及限流响应头。只测 API，不调用或改变 benchmark 生成流程。

首组按 4、8、16、32、64、128、256 递增，每档 2 轮、轮间冷却 65 秒，首次出现 429 的档位测完后停止；首轮不冷却。记录在 `token_usage/20260917T190838Z_8e4b0b98/`。4 和 8 并发均全部成功；16 并发第一轮 14 成功、2 次 429，第二轮 16 次全部成功，因此在 16 停止，未测试更高档。后续细测命令为 `python local/check_search_concurrency.py --output cache/luna_concurrency_20260917 --levels 12 14 15 --rounds 3`，开始及轮间均冷却 65 秒，记录在 `token_usage/20260917T191631Z_2a5f1d11/`。这些是固定查询下的突发并发测试，不能仅凭峰值推断持续吞吐量或后端 key 配额是否独立。

细测完成：12、14、15 并发分别 36/36、42/42、45/45 成功。随后同脚本测试 `--levels 15 --rounds 6 --cooldown 0`，开始冷却 65 秒，批间不冷却，90 次中 28 成功、62 次 429，记录在 `token_usage/20260917T192915Z_037b5166/`。成功响应显示剩余请求额度仍充足、剩余 token 额度降至零以下、token 恢复提示约 60 秒，支持 token 速率额度成为主要瓶颈，不能把 15 当作持续零限流的并发上限。

持续补入请求测试使用同脚本的 `--requests`：固定数量的在途请求，每完成一个立即补下一个；各次测试前冷却 65 秒，关闭重试。`--levels 8 --rounds 1 --requests 64` 用时 75.18 秒，33 成功、31 次 429，记录在 `token_usage/20260917T193236Z_cf2672b8/`；`--levels 4 --rounds 1 --requests 48` 用时 101.74 秒，38 成功、10 次 429，记录在 `token_usage/20260917T193521Z_6d5ded52/`。

`--levels 3 --rounds 1 --requests 60` 按用户要求中止，已返回的 11 次均成功，不能据此判断 3 并发持续稳定。记录在 `token_usage/20260917T193827Z_2f1b9343/`，客户端进程已退出。此次系列探测共记录 392 次返回，287 次成功、105 次 429，已记录 2,209,926 tokens；105 次错误及中止时在途请求的用量未知。没有据此改变 baseline 的并发配置。

2026-09-17 19:50:50 UTC 启动八需求批次 `cache/batch_20260917_eight_200/`。知识问答、逻辑／空间／常识推理、复杂数学、计算机科学、数据分析、指令遵循、长上下文与长程任务、多语言各目标 200 题，原文分别保存在 `user_queries/{knowledge,reasoning,math,computer_science,data_analysis,instruction_following,long_context,multilingual}_200.json`，同时启动八个独立框架进程，不复用旧缓存，不补题。数据池仍为 HF `General-Level/General-Bench-Openset` 的 `nlp` 和 `image/comprehension`，数据卡清单及模型、需求快照在批次 `configuration/`。种子与采样沿用既有设置，未额外固定 seed。

除网页搜索外均使用 `openai/deepseek-flash`、`https://api.deepseek.com`，输出上限 300,000、请求超时 7,200 秒；DeepSeek 不增加全局 API 并发限制，框架内部工作线程池和依赖顺序保持原设置。搜索为 `openai/responses/gpt-5.6-luna`、既有网关与四 key，medium、强制原生搜索、12,000 输出 token、180 秒请求及重试预算、最多 6 次 429 尝试。所有进程通过 `cache/runtime/luna/` 的文件锁共享 4 个实际请求名额，操作系统在进程退出时释放锁；排队与退避不占名额，排队不消耗请求／重试预算，排队与退避不计入 24 小时转换无进展阈值。基础设施异常若未恢复则停止受影响运行，避免失败内容反馈规划器；模型内容过滤沿用既有处理。36 项离线测试通过，涵盖八进程共享四名额、进程被终止后的锁释放、排队计时、重试释放、错误不进入框架、原有预算与搜索行为。

启动命令：`python -u local/run_batch.py cache/batch_20260917_eight_200 --topics knowledge_200 reasoning_200 math_200 computer_science_200 data_analysis_200 instruction_following_200 long_context_200 multilingual_200`。实际通过 `nohup` 和独立进程会话启动，父进程 PID 3325404，已确认无控制终端、忽略 SIGHUP、标准输入为 `/dev/null`、标准输出与错误写入 `launcher.log`，正常 SSH 断联不影响运行。八个生成进程 PID 为 3325406–3325413，启动检查均存活且已有成功 API 返回。生成结束后按既有规则自动进行 DeepSeek 自测，回答和判分使用 300,000 输出 token、7,200 秒超时、temperature=0，每组 10 个线程，应用不额外重试；仅评测生成正常结束并导出结果的需求。过程与最终状态以批次 `batch.json`、逐任务日志、自测及 token 记录为准。
2026-09-18 00:19:37 UTC（本地 9 月 17 日）补跑数学与长上下文：`python -u local/run_batch.py cache/batch_20260917_math_long_context_200 --topics math_200 long_context_200`。两项此前在生成阶段失败、自测未开始；此次使用新目录从头生成，各目标 200 题，两个框架进程并行，原八需求批次及其六项完成结果保留。数据仍为 HF `General-Level/General-Bench-Openset` 的 `nlp` 与 `image/comprehension`，模型及数据卡配置与原批次快照相同。DeepSeek 全阶段及自测输出上限 300,000、请求超时 7,200 秒；Luna 仅用于搜索，四 key、全局 4 并发、最多 6 次 429 尝试、180 秒请求及重试预算、12,000 输出上限、medium 强制原生搜索。采样、种子及验证规则沿用原批次，未额外设 seed，不补题；成功导出后自动进行 DeepSeek 自测，每组 10 线程、temperature=0。并发限制不保证避免 token 速率限流，未恢复的搜索 API 错误仍使该任务退出。

补跑通过 `nohup setsid` 启动，父进程 PID 3892222，生成进程 PID 3892223、3892224；启动检查确认父进程已由 PID 1 接管、独立会话且无控制终端，标准输入接 `/dev/null`，输出写入 `cache/batch_20260917_math_long_context_200.launcher.log`。两个生成进程均已开始规划并收到模型返回；最终状态以本批次 `batch.json`、生成日志、自测和 token 记录为准。

该批次于 00:50:29 UTC 结束。数学导出 191 题，自测正确 187/191，9 题被验证拒绝，1,982 次调用无 API 错误且没有 Luna 调用，记录 11,442,447 tokens。长上下文未导出或自测，记录 10,828,854 tokens、142 次限流和 5 次超时，最终因搜索 HTTP 429 重试预算耗尽退出；搜索返回 43 次 completed、17 次内容过滤 incomplete，两个样本共四次内容过滤工具失败进入框架处理。异常调用的用量未知。

2026-09-18 01:07:57 UTC 单独重跑长上下文：`python -u local/run_batch.py cache/batch_20260918_long_context_200 --topics long_context_200`，目标 200 题，新缓存从头运行。使用 `benchmaker-baseline` 环境，数据为 HF `General-Level/General-Bench-Openset` 的 `nlp` 和 `image/comprehension`，需求、模型及数据卡快照位于批次 `configuration/`。模型与超参沿用上一批次：DeepSeek Flash 负责搜索以外各阶段及自测，300,000 输出上限、7,200 秒请求超时；Luna 原生搜索使用四 key、全局 4 并发、12,000 输出上限、medium、180 秒请求及重试预算、最多 6 次 429 尝试，失败退出策略不变。框架并发为 1，DeepSeek 不加全局并发限制；无额外 seed，采样沿用原设置，不补题，成功后自动自测（10 线程、temperature=0）。启动前未发现其他 baseline 运行或搜索探测进程，网关其他调用方未知。

本次以 `nohup setsid` 启动，父进程 PID 4029324，生成进程 PID 4029326。已确认独立会话、无控制终端、忽略 SIGHUP，输入为 `/dev/null`，输出为批次内 `launcher.log`；生成日志已出现模型规划返回。原有结果保留，进度及结果以新批次 `batch.json`、生成日志、自测与 token 记录为准。

2026-09-18 10:10:52 UTC 单独重跑长上下文并增加搜索超时 fallback：批次 `cache/batch_20260918_long_context_200_fallback/`，目标 200 题，框架并发 1。DeepSeek 配置、数据集、需求、预算、超时及自测规则沿用前轮；Luna 主端点仍为 `https://api.fangcunleap.com/azure-gateway/v1`，但全局并发降为 1。每个搜索端点最多 6 次超时请求；主端点连续超时耗尽后切换到 `https://api.sudocode.chat/v1`，备用端点同样最多 6 次超时请求。429 仍按每端点最多 6 次和原有 180 秒退避预算处理。备用密钥仅从 `WEB_SEARCH_FALLBACK_API_KEY` 读取，未写入实验记录；两端点共用文件锁队列。

本次改动先通过 22 项搜索队列、退避、传输和 fallback 离线测试；新增测试验证主端点连续超时后恰好切换备用端点。批次通过 `nohup setsid` 启动，父进程 PID 1204893，生成进程 PID 1204897；启动时确认无其他本地 baseline 搜索进程，父进程已由 PID 1 接管、无控制终端，输入为 `/dev/null`，配置快照记录并发 1、两端点及各自 6 次超时尝试。最终状态以该批次 `batch.json`、日志和 token 记录为准。

八需求最终成功产物已上传至 HF `assassinlike/b635` 的 `benchmark-agent` 配置（`test` split），提交 `336f44e71ea27b8cd2e254dd518793ea42563eda`。知识、推理、数学、计算机、数据分析、指令遵循、长上下文、多语言分别为 182、196、191、177、191、195、175、123 题，总计 1,430 题；DeepSeek Flash 答对 1,361 题，按题加权准确率 95.17%。数学来自双需求补跑批次，长上下文来自并发 1 的最终批次，其余六项来自八需求批次。上传脚本 `local/upload_hf_questions.py` 校验原始导出哈希与自测配置一致、逐题关联一致、题数和正确数一致，保留所有原始题目及自测字段；输入及参考输出以 JSON 字符串保留异构结构。上传包含八份 JSONL、需求及子任务定义、自测配置、来源及校验清单，未包含凭据。19 个上传文件（含根目录索引）均按提交版本下载并逐字节校验通过，其他 baseline 文件保留。
2026-09-18 Qwen 官方 API 最小连通性探测：端点 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`，模型 `qwen3.8-27b`，单请求、无重试，输入 `Reply with OK only.`，`max_tokens=16`、`enable_thinking=false`、`temperature=0`、`seed=42`、客户端超时 60 秒。HTTP 200，约 0.34 秒，回答 `OK`、`finish_reason=stop`；输入 17、输出 2、合计 19 tokens，请求 ID `6fd47557-b2f1-9cee-834e-84912b613e33`。响应头未提供速率配额信息。未运行正式题目或并发压力测试。官方动态限流文档 `https://help.aliyun.com/zh/model-studio/quota-management` 列出该模型北京及新加坡各档基线均为 500 万 TPM，账号与模型维度共享配额，业务空间可额外限流；未核实该凭据所在业务空间的控制台设置。
2026-09-18 15:16:02 UTC 启动 Qwen 官方测评 `cache/qwen3_8_27b_20260918/`，对已发布至 HF `assassinlike/b635`（`benchmark-agent` 配置、提交 `336f44e71ea27b8cd2e254dd518793ea42563eda`）的八需求全部 1,430 题答题，不重新生成 benchmark。各需求分别为 182、196、191、177、191、195、175、123 题；数据来自前述最终成功本地产物，每份导出与原自测配置的 SHA-256 匹配，来源批次和哈希记录在本轮 `config.json`。题目与参考答案另存于各需求目录，用户需求原文保留在 HF 与原批次配置中。

答题模型 `qwen3.8-27b`，端点 `https://dashscope.aliyuncs.com/compatible-mode/v1`，`enable_thinking=true`、思考预算由服务端默认控制、`max_tokens=131072`、temperature=0、seed=42、stream=false、请求超时 7200 秒。Python random、NumPy 和 PYTHONHASHSEED 均固定为 42；本环境没有 PyTorch，本次仅进行 API 推理。正式启动前以相同答题参数和 `Reply with OK only.` 做单请求探测，HTTP 200、stop，输入 53、输出 27（推理 22）、合计 80 tokens，探测消耗不计入正式统计。

全部需求共用 128 个工作线程，逐题答题后按原规则判分，需求交错提交。回答仅接收原始 input，选择题严格匹配字母；其他题由独立的 `deepseek-flash` 调用判分，端点 `https://api.deepseek.com`、temperature=0、max_tokens=300000、请求超时 7200 秒、thinking 采用服务端默认、不新增判分 seed，判分提示词和解析规则沿用 `local/self_evaluate.py`。重试保持请求参数和模型不变：429 最多 20 次，超时／连接故障／服务端 5xx 最多 6 次，两类独立计数；遵循数字 Retry-After，否则指数退避最高 60 秒并增加抖动，SDK 重试关闭。截断、错误和无法解析的判分单独标记，不当成错误答案或已评分题目。每个实际请求记录 token，逐题保存完整模型响应及判分，失败请求未知用量仍单列。

启动命令：`nohup setsid env PYTHONHASHSEED=42 /data1/zangyihe/.conda/conda_envs/benchmaker-baseline/bin/python -u local/evaluate_qwen.py cache/qwen3_8_27b_20260918 --workers 128`，标准输入接 `/dev/null`，输出写入批次 `launcher.log`。进程 PID 4094822，已确认 PID 1 接管、独立后台运行且忽略 SIGHUP。6 项离线测试覆盖参考答案隔离、原评分规则、未完成响应和重试请求不变；本轮进度查看 `status.json`，最终逐题汇总查看 `results.json`。原 DeepSeek 自测产物保留。
Qwen 评测的模型判分抽样复核：从 252 道 DeepSeek 判分题中查看 25 题，包括全部 12 道判错题、seed=42 抽取的 10 道判对非 choice 题及全部 3 道未走字母匹配的 choice 标注题。逐题依据与来源记录在 `cache/qwen3_8_27b_20260918/review_sample.md`。发现至少两道原判定明显不合理（knowledge index 167 的热液洋底沉积物事实、reasoning index 13 的必要条件推理），另有歧义和理由不足；multilingual index 121 实为翻译任务，虽然被标为 choice，不能按固定选项代号处理。此为助手独立文本复核与公开资料查证，没有追加评审模型调用，也未修改原题、参考答案或分数。抽样包含全部判错案例，不能用于估计总体误判率。

2026-09-18 RightAPI 并发探测：模型 `gpt-5.6-sol`，单 key，端点 `https://www.rightapi.ai/v1/chat/completions`。脚本 `local/check_sol_concurrency.py` 使用固定的两次骰子条件概率题（完整请求保存在 report.json），不使用正式 benchmark、不判分。`max_completion_tokens=2048`、stream=false、客户端超时 120 秒，temperature、reasoning、API seed 均省略使用服务端默认；Python random、NumPy、PYTHONHASHSEED 固定为 42。SDK 与应用层重试均关闭，每个请求只尝试一次。升档探测并发 1/2/4/8/16/32，每档发出与并发相同的请求数，档间等 15 秒，首次出现任何失败或未完成响应即停止升档。命令：`env PYTHONHASHSEED=42 /data1/zangyihe/.conda/conda_envs/benchmaker-baseline/bin/python -u local/check_sol_concurrency.py cache/sol_probe_20260918_burst --levels 1 2 4 8 16 32`。逐请求保存完整响应、完成状态、耗时、HTTP 错误、限流响应头及 token 用量；密钥只从忽略跟踪的 `.env` 读取。HTTP 成功与客户端在途数量不证明后端实际执行并行度，也不证明长输入和长推理负载下的持续能力。


探测结果：首次 120 秒超时配置下，并发 1/2/4/8 分别成功 1/1、2/2、4/4、8/8；16 并发成功 15/16，1 次客户端超时，未继续升档。随后以 `--levels 16 32 --timeout 300` 运行至 `cache/sol_probe_20260918_long_timeout/`，16 并发 16/16 成功（23.7–75.1 秒），32 并发 31/32 有效；异常请求 HTTP 200、finish_reason=stop，但 content=null、completion_tokens=0、refusal=null。没有任何 HTTP 429，故不能据此确定服务端并发硬上限。

持续补充请求复测使用同一脚本与请求，`--levels 16 --requests 48 --timeout 300` 输出到 `cache/sol_probe_20260918_sustained16/`，47/48 有效，另 1 次同样返回空答案；总耗时 169.7 秒。降至 `--levels 8 --requests 24 --timeout 300` 输出到 `cache/sol_probe_20260918_sustained8/`，24/24 有效，总耗时 158.4 秒，单请求约 21.6–125.7 秒，中间位置约 24.6 秒。最后一轮于 2026-09-18 18:26:24 UTC 结束。持续测试每个请求完成后立即补入下一请求；HTTP 成功且 stop 且存在非空答案才算有效，不评价数学准确率。8 并发两轮合计 32/32 有效，可作为保守起始并发；测试次数有限、全部是同一短题，不能保证长题持续评测零失败，也不能证明空响应由并发引起。未启动全部 1,430 题的正式测评。

本次共发出 151 次请求，148 次有效、2 次空响应、1 次超时，未自动重试。原始 Chat Completions usage 汇总输入 33,106、输出 105,108、合计 138,214 tokens；超时调用用量未知，未获得该渠道价格，不能计算实际费用。两次空响应同时报告 prompt_tokens=55/total_tokens=55 和 input_tokens=0/output_tokens=0；通用 token 汇总优先采用后者，因此其累计值比这里按原始 Chat 字段统计少 110 tokens，完整原始字段已保存。相同请求还存在 106 与 4,433 两种非空响应输入 token 计数，网关未解释差异。核心生成与评分流程未改动。


2026-09-18 启动 Sol 正式测评 `cache/gpt_5_6_sol_20260918/`，使用已发布 HF `assassinlike/b635` 的 `benchmark-agent` 配置（提交 `336f44e71ea27b8cd2e254dd518793ea42563eda`）对应的全部 1,430 道本地产物；知识、推理、数学、计算机、数据分析、指令遵循、长上下文、多语言分别 182、196、191、177、191、195、175、123 题。每份原始导出均校验 SHA-256 与原自测一致，不重新生成或修改题目及参考答案，源批次和哈希在本轮 config.json，题目和子任务定义另存于每个需求目录。

答题模型 `gpt-5.6-sol`，端点 `https://www.rightapi.ai/v1`，单 key、八需求交错提交并共用 8 个工作线程，实际 Sol 在途请求最多 8；`max_completion_tokens=131072`、stream=false、请求超时 7200 秒，temperature、reasoning、API seed 均省略使用服务端默认。Python random、NumPy、PYTHONHASHSEED 固定为 42；API 不承诺确定性。启动前同参数单请求返回 OK、stop、32 tokens，记录在 `cache/sol_20260918_setup/`，不计入正式用量。

沿用 Qwen 的外部评测及评分实现，选择题严格匹配字母，其余由独立 DeepSeek Flash 判分，端点 `https://api.deepseek.com`、temperature=0、max_tokens=300000、超时7200秒、thinking 服务端默认，提示词与解析方式不变。回答只接收 input，不传参考答案或来源。SDK 重试关闭；429 最多20次，超时／连接错误／5xx 最多6次；Sol 无 choices 或 stop 且空白答案（不含拒答或工具调用）最多6次，各类独立计数，重试保持原请求不变。遵循数字 Retry-After，否则指数退避最高60秒并加随机抖动。空响应原文保存至逐题记录，所有尝试计入 token；耗尽标记 error，截断和无效判分单列，均不算错误答案。统计优先使用 Chat Completions 字段，缺失时才转换 Responses 字段，避免网关冗余零值覆盖输入 token；25 项评分、重试与用量测试通过。

启动命令：`nohup setsid env PYTHONHASHSEED=42 /data1/zangyihe/.conda/conda_envs/benchmaker-baseline/bin/python -u local/evaluate_sol.py cache/gpt_5_6_sol_20260918 --workers 8`。PID 4053093，输入为 /dev/null，输出为批次 launcher.log；启动后确认 PID 1 接管、独立进程会话、无控制终端且忽略 SIGHUP，正常 SSH 断联不影响运行。代码快照保存在 code/，状态查看 status.json，逐题完整响应与判分保存在各需求 items/，最终汇总为 results.json；回答和判分 token 分别保存。先前 DeepSeek、Qwen 的结果保留。


Sol 原批次于 2026-09-18 19:20:10 UTC 结束，1,429 题已评分、1,317 题正确，另多语言 index=121 因 HTTP 400 未完成。8 次连接异常均通过原请求重试恢复；原 HTTP 400 未保存响应正文，无法从旧记录确定原因。

2026-09-18 19:31:38–19:31:52 UTC 单独补测未评分项：`env PYTHONHASHSEED=42 /data1/zangyihe/.conda/conda_envs/benchmaker-baseline/bin/python -u local/retry_unscored.py cache/gpt_5_6_sol_20260918`。脚本读取原 config.json，复用相同模型、端点、请求参数、提示词、评分和重试方法，固定 Python/NumPy/hash seed=42，实际并发1。来源哈希、题目与原导出一致；已评分项目跳过。补测前的逐题失败记录、汇总、状态和配置保存在 `recovery/20260918T193138Z/`，其下独立记录答题及判分用量。本次 Sol 和 DeepSeek 判分各成功调用一次，分别430、296 tokens，没有重试。Sol 返回 A；该题实际要求翻译，但原子任务标为 choice，仍沿用原提示词。按原有判分方式判错，没有修改题型或参考答案。

补测后全部1,430题均已评分，正确1,317，按题加权准确率92.0979%；多语言113/123。主 results.json、status.json 与该题记录已更新，其他1,429份逐题文件通过 SHA-256 校验完全不变；汇总逐条与全部逐题文件一致。原批次 token 文件保留原历史状态，补测用量在 recovery/ 下单独累计。
