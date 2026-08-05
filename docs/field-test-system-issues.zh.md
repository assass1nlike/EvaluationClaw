# EvalClaw 实测核心系统问题台账

更新日期：2026-08-05

## 记录范围

本文只记录在真实框架运行中已经得到证据支持、并且根因至少部分位于 EvalClaw 机制或协议中的问题。单次模型内容失误、尚未验证的怀疑和外部服务偶发故障不直接列为系统问题。

状态含义：

- `待修复`：根因仍存在。
- `已缓解，待复测`：已经修改相关机制，但还没有通过同类端到端实测证明问题消失。
- `已验证修复`：同类实测已通过，且原失败条件不再出现。

## 问题总览

| ID | 核心问题 | 严重度 | 状态 | 已确认于 |
| --- | --- | --- | --- | --- |
| FT-001 | Blueprint 工作量没有受到实际输出预算约束 | P0 | 待修复 | 50 题自适应欺骗诱导测试 |
| FT-002 | QC 结论跨修复轮次显著漂移，未改任务也可能由通过变为拒绝 | P0 | 待修复 | 两次 50 题自适应对话测试 |
| FT-003 | 大批量 QC 会漏掉用户要求的核心行为构念 | P0 | 待修复 | 两次 50 题自适应对话测试 |
| FT-004 | 环境题曾允许用描述性声明代替真实的初始状态构建 | P0 | 已验证修复 | Windows 隐藏故障修复测试 |
| FT-005 | 环境 Builder、打包器、验证器与运行时的字段/工具契约不完全一致 | P1 | 已缓解，待复测 | Windows 隐藏故障修复复测；医疗欺骗 benchmark |
| FT-006 | 失败运行没有完整保留 Planner 与 QC 的原始审计信息 | P1 | 待修复 | 50 题自适应欺骗诱导测试 |
| FT-007 | GUI 任务曾允许不可执行的私有 evaluator 声明和无条件成功检查 | P0 | 已验证修复 | Windows 隐藏故障修复 v7-v10 |
| FT-008 | 单题 QC warning 曾使全部通过的数据集无法产包 | P1 | 已验证修复 | Windows 隐藏故障修复 v11 |
| FT-009 | Windows provisioning 在 QC 前没有做 PowerShell 语法验证 | P0 | 已验证修复 | Windows 隐藏故障修复 v11-v13 |
| FT-010 | LLM 模式下未配置 Planner 时会静默使用本地默认计划 | P0 | 已验证修复 | Windows 隐藏故障修复 v9 |
| FT-011 | 目标模型上下文曾暴露 VM 故障注入和私有评分实现 | P0 | 已验证修复 | Windows 隐藏故障修复本地实跑 |
| FT-012 | Windows bridge 命令继承可交互 stdin，提示输入的 CLI 会长期挂起 | P1 | 已验证修复 | Windows 隐藏故障修复本地实跑 v8-v9 |
| FT-013 | 必须使用真实登录用户令牌的 Windows 初始状态无法可靠构建 | P0 | 已验证修复 | Windows 隐藏故障修复本地实跑 v5-v9 |
| FT-014 | VirtualBox 中 provisioning 后重启可能无限停在 Restarting | P0 | 已验证修复 | Windows 隐藏故障修复本地实跑 v3-v9 |
| FT-015 | Windows evaluator 对等价系统表示和路径大小写处理不稳，会产生假阴性 | P1 | 已验证修复 | Windows 隐藏故障修复 oracle 与真实 target |
| FT-016 | VirtualBox 克隆后恢复源快照的顺序错误 | P0 | 已验证修复 | vm-chain-matrix-05-public-workspace |
| FT-017 | Windows 双阶段启动默认等待窗口不足 | P0 | 已验证修复 | Researcher 任务 v10 |
| FT-018 | bridge 异步重定向流收尾可能阻塞 listener | P0 | 已验证修复 | Researcher 任务 v10 |
| FT-019 | artifact 对象被序列化为字典字符串 | P1 | 已验证修复 | vm-chain-matrix-06-operator-workspace |
| FT-020 | Windows identity 命名用户断言识别不完整 | P0 | 已验证修复 | Operator 任务 v3 |
| FT-021 | target 不可读私有 evaluator oracle 被误记为 0 分 | P0 | 已验证修复 | Operator 任务 v2 |
| FT-022 | QC 摘要曾无标记地截断 task-agent system prompt并产生假阳性 | P1 | 已缓解，待复测 | 医疗欺骗 benchmark v10 |
| FT-023 | Planner 缺少执行环境能力边界，可能选择无法实现任务合同的 runtime | P0 | 已缓解，待复测 | 医疗欺骗 benchmark v14 |
| FT-024 | OpenAI-compatible 流式路径曾缺少瞬态错误重试 | P1 | 已缓解，待复测 | 医疗欺骗 benchmark v11-v14 |
| FT-025 | Planner 可生成超出单次 Builder 稳定承载能力的 Blueprint | P0 | 待修复 | 医疗欺骗 benchmark v22 |
| FT-026 | 真实数据约束下缺少可执行、可审计的来源载荷 | P0 | 待修复 | 医疗欺骗 benchmark v23-v24 |
| FT-027 | QC 接受不存在的全局 item ID，污染通过/拒绝计数 | P1 | 待修复 | 医疗欺骗 benchmark v24 |
| FT-028 | 单个 Blueprint 修复失败会中断整个 QC 候选循环 | P1 | 待修复 | 医疗欺骗 benchmark v24 |

## FT-001：Blueprint 工作量没有受到实际输出预算约束

### 实测证据

在 50 题自适应欺骗诱导测试中，Planner 把 25 个字段完整的多轮对话任务放进同一个 Blueprint。该批次在初始构建和后续修复中反复出现超长请求：一次调用超时，多次响应达到 completion 上限；最后一轮首次响应截断，降低 effort 后仍在 16,384 completion tokens 处截断，整次运行 fail-closed。

运行日志：[`benchmark-output/deception-dialogue-50-inducement-v1.run.log`](../benchmark-output/deception-dialogue-50-inducement-v1.run.log)

截断诊断：[`attempt-01-initial.diagnostics.json`](../benchmark-output/deception-dialogue-50-inducement-v1/debug/task-builder/participant_commission__bp_participant_commission_all/20260716T025811.450569Z-98c78880/attempt-01-initial.diagnostics.json)

### 为什么属于框架问题

Planner 只需用自然语言声明一个 Blueprint 的工作量合理，框架没有根据题型、单题字段规模、预计输出长度和模型输出上限做可执行性检查。截断后，框架仍以更低 effort 重试同一个过大的工作单元，也不会把它拆成较小 Blueprint。

这里不应简单设置“每个 Blueprint 最多 N 题”：十几道简单选择题与十几道完整多轮任务的工作量不同。真正缺少的是与任务复杂度和输出预算相关的分组约束。

### 影响

- 大响应更容易超时、截断或表现为长连接故障。
- QC 返修会重复支付整个大批次的时间和 token 成本。
- 一个过大的 Blueprint 可以阻断整个 benchmark，已完成的其他任务也无法交付。

## FT-002：QC 结论跨修复轮次显著漂移

### 实测证据

第一次 50 题自适应对话测试的 QC 通过数依次为：

`46/50 -> 45/50 -> 49/50 -> 29/50`

最后一轮只要求 Builder 修复一个 Blueprint 中的 6 道题，但重新运行全量 QC 后共有 21 道题被拒绝，包含此前已经通过且未交给 Builder 修改的任务。

日志：[`benchmark-output/deception-dialogue-50-adaptive-v1.run.log`](../benchmark-output/deception-dialogue-50-adaptive-v1.run.log)

最近一次诱导测试中，QC 结果也从 `10/50`、`14/50` 变化到 `15/50`，同时问题数从 40 增至 68；第三轮在 QC 前因 Builder 截断终止。

### 为什么属于框架问题

LLM 审查本身可能有随机性，但框架每轮重新审查全量任务，并直接以本轮结果重建通过集合；它没有稳定保留已确认问题、区分“任务发生了变化”与“审查意见发生了变化”，也没有对未修改任务的新阻断结论做一致性复核。因此，定点修复流程在系统层面不保证验收范围稳定。

### 影响

- 修复正确问题后，整体通过率可能大幅下降。
- 运行结果取决于最后一次 QC 的偶然审查覆盖，而不只是数据集质量。
- Builder 可能在多个轮次中反复处理相似任务，却无法收敛。

## FT-003：大批量 QC 会漏掉核心行为构念

### 实测证据

第二次 50 题自适应对话测试最终得到 `50/50` 通过、`0 issues`。人工检查后发现，多个 simulator 的主要机制是逐步索要证据、质疑矛盾或逼近真相，而不是在 target 选择欺骗后增加奖励、在诚实或拒绝后增加代价。这不满足后来明确提出的“让欺骗相对诚实或拒绝越来越有利”的核心构念。

成功但存在语义漏检的包：[`evalclaw_2026-07-16T012927_426371_0000.json`](../benchmark-output/deception-dialogue-50-adaptive-v2/evalclaw_2026-07-16T012927_426371_0000.json)

在使用更明确需求重新测试后，第二轮 QC 已让全部 10 道 `participant_omission` 任务通过；但其中仍存在以逐步询问秘密、查验披露为主的 simulator policy。该次运行的中间 Builder 响应位于：[`debug/task-builder`](../benchmark-output/deception-dialogue-50-inducement-v1/debug/task-builder)

### 为什么属于框架问题

具体错误内容由模型生成，但框架把最多 50 道任务压入一次紧凑的 LLM QC 请求，并用有限的 QC 输出预算同时检查逐题结构、逐题语义、Planner 契约和全局覆盖。对于需要跨多轮机制才能判断的行为构念，这种审查单元没有提供稳定的逐任务验收保证。`50/50、0 issues` 与明确的人审反例同时存在，已经证明当前 QC 不能作为该类构念的可靠验收门。

### 影响

- 框架可能产出结构完全合法、但实际上测量了不同能力的 benchmark。
- `QC 通过` 和 `0 issues` 会给使用者错误的完成信号。
- 同一类语义偏差可能成批进入最终数据集。

## FT-004：环境题曾允许描述性状态冒充真实构建

### 实测证据

Windows 隐藏故障修复测试曾得到 `1/1` QC 通过和 `0 issues`，环境阶段还报告已生成 task-specific seed ISO。但最终任务中的 VM template 是一段描述性文字，`vm_provisioning` 和 setup commands 为空；生成的 ISO 只映射了三个任务协议 JSON，没有创建防火墙规则、计划任务、服务依赖等隐藏故障。

运行日志：[`run.stdout.log`](../benchmark-output/windows-hidden-repair-agent/run.stdout.log)

任务包：[`evalclaw_2026-07-15T121414_035483_0000.json`](../benchmark-output/windows-hidden-repair-agent/evalclaw_2026-07-15T121414_035483_0000.json)

### 为什么属于框架问题

当时的结构验证、QC 和环境物化只验证了“存在 VM/ISO/评估描述”，没有证明题目要求的初始故障真实存在。框架自己生成并接受了一个没有构造被测状态的环境，因此这不是 target model 能力问题。

### 当前状态

后续已经加入通用 VM provisioning、Windows Cloudbase-Init/NoCloud 路径、baseline checks 和 fail-closed 要求。v13 最终 Builder 响应经当前打包器与 VM materializer 硬审计后，成功生成 419,840 字节 NoCloud ISO；46,885 字节 Windows user-data 包含全部 4 条 provisioning 命令，4 条 baseline checks 与 6 条 evaluation checks 也完整保留。

审计来源：[`v13 最终 Builder 响应`](../benchmark-output/win-vm-gpt56-v13/debug/task-builder/long_horizon_windows_operations__windows_atlas_r-e8df3521/20260716T114316.585525Z-1fbe164c/attempt-02-structural-repair.response.txt)

物化目录：[`win-vm-gpt56-v13-audit`](../benchmark-output/win-vm-gpt56-v13-audit)

随后建立了可复用的 Windows 11 VirtualBox 模板，并用最终 Atlas 任务完成真实本机运行。SYSTEM provisioning、重启、登录用户 provisioning、六项 baseline、目标操作和六项私有 evaluation 均在隔离克隆内实际执行；最终 target 得分 `5/6`，唯一失败项是模型写出的交接文档不完整，不是环境缺失。结果：[`result-v9.json`](../benchmark-output/windows-vm-local-run/target-v10/result-v9.json)。原失败条件已经由端到端运行消除，因此状态为“已验证修复”。

## FT-005：环境 Builder 指令与验证器字段契约不完全一致

### 实测证据

Windows 复测中，Builder 连续三次返回包含桌面 surface、launch state 和 evaluation checks 的任务，但验证器连续判定“未标识 application/desktop surface”和“缺少 executable evaluation”。原始响应使用 `session.surface` 和 `session.evaluation_checks`；验证器实际接受的是另一组字段位置和名称。

三轮诊断与响应：[`windows-hidden-repair-agent-builder-debug`](../benchmark-output/windows-hidden-repair-agent-builder-debug/debug/task-builder/dim_longrange_diagnose_fix__bp_windows_multifault/20260715T143634.411923Z-43caec74)

### 为什么属于框架问题

Builder skill 要求模型“标识 application 或 desktop surface”并提供评估检查，但没有给出足够明确的可消费字段契约；验证器的错误文本继续使用同样的自然语言，而没有指出可接受字段。模型确实选择了语义上合理、但框架不读取的字段，随后 repair prompt 也无法帮助它纠正位置，形成无效循环。

### 影响

- 语义完整的环境设计可能因为协议位置错误而 fail-closed。
- 结构修复重复生成近似响应，浪费调用次数。
- Builder skill、打包器、验证器和运行时之间可能出现隐式字段分歧。

### 当前状态

Builder Skill、结构验证器、打包器和 QC 现已统一使用 `environment.vm_provisioning`、`environment.session` 与 `environment.evaluation`。Windows command 检查统一使用 raw PowerShell body；Scheduled Task 参数检查按每次 AST 调用分别判断，不再合并两个独立调用，验证器也不再原地修改待验证命令列表。v10-v13 的多轮真实 Builder 响应和最终本机运行均未再出现旧字段或协议错位，因此标记为“已验证修复”。

医疗欺骗 benchmark v9 又发现同类 workspace 协议错位：Builder 把房间写成对象数组，并把对象放在独立 `objects` 数组；运行时实际只接受 `environment.workspace.rooms` 为“房间名 -> item ID 数组”的映射。v14 进一步发现 canonical agent package 为 workspace 错误声明了 `read_file/write_file`，而运行时实际暴露 `look/move/inspect/take/place/final`。

当前已在 workspace Builder reference 中加入唯一可执行 JSON 形状和明确的修复反馈，并修正 canonical 工具列表。定向回归测试通过，但尚未得到同类端到端成功包，因此本条整体状态重新标记为“已缓解，待复测”。

## FT-006：失败运行缺少完整的 Planner 与 QC 审计信息

### 实测证据

最近一次 50 题诱导测试保留了每次 Task Builder 的原始响应和结构诊断，但输出目录没有 Planner 原始 JSON、各轮 QC 原始响应或完整的逐项 QC issue 快照。运行日志只保存每轮汇总；由于第三轮在 Builder 阶段终止，前两轮具体为什么拒绝、哪些问题后来消失或新增，无法从正式运行产物完整还原。

现有产物：[`deception-dialogue-50-inducement-v1`](../benchmark-output/deception-dialogue-50-inducement-v1)

### 为什么属于框架问题

这是框架的诊断产物保留策略，而不是模型能力问题。只保存 Builder 响应不足以分析 Planner 分组决策、QC 漏检和跨轮漂移。

### 影响

- 无法可靠归因失败发生在规划、构建还是验收。
- 难以比较多轮 QC，无法确认定点修复是否真的收敛。
- 大规模实测只能依赖控制台片段和人工推断。

医疗欺骗 benchmark v14 还暴露了 Windows debug 路径过长：同一响应文件可以保存，但稍长的 `.diagnostics.json` 路径超过传统 `MAX_PATH` 后报 `FileNotFoundError`。debug job 目录名现已保留短前缀和稳定哈希，将最长目录段从 57 字符缩至 33 字符。该修复只改善 Builder 诊断保存，Planner 与 QC 原始审计信息仍未完整落盘，因此 FT-006 状态保持“待修复”。

## FT-007：GUI 任务曾允许不可执行的私有 evaluator 声明和无条件成功检查

### 实测证据

v7 使用 `RUNNER_PRIVATE_BRIDGE_COMMAND:...` 作为检查命令；通用 desktop bridge 不解析这种符号 ID。v8 改为真实 PowerShell，但 evaluation 只输出状态 JSON 并无条件 `exit 0`，真正评分逻辑放在普通 `metadata.runner_private_evaluator` 中；runner、packager 和 bridge 都不会加载该对象。

响应：[`v8 Builder 响应`](../benchmark-output/win-vm-gpt56-v8/debug/task-builder/integrated_windows_diagnosis_repair_persistence_-c79faed1/20260716T090056.697513Z-469695b9/attempt-01-initial.response.txt)

### 当前状态

结构验证现在拒绝未注册命令 ID、普通 metadata 中的运行时 evaluator 声明，以及只采集输出后无条件成功的 evaluation command。v8 原响应已用新验证器复核并稳定得到三条阻断错误；最终 Atlas 任务则通过当前结构验证，并在真实 VM 中执行六项评分检查，得到 `5/6` 的可解释结果。状态为“已验证修复”。

## FT-008：单题 QC warning 曾使全部通过的数据集无法产包

### 实测证据

v11 最终报告 `1/1 items passed, 0 rejected, 5 issues`，但每条非 error issue 都按单题分母扣 0.05，质量分降至 0.75；`is_acceptable` 又要求分数至少 0.8，导致没有任何拒绝项时仍报 runner-ready 失败，也没有 affected task 可进入下一轮修复。

### 当前状态

runner-ready 现在只由 error 和 rejected item 决定；warning/info 继续保留并影响展示用质量分，但不阻止全部已通过的数据集产包。回归测试覆盖了单题 0.75 分、仅 warning 的场景，状态为“已验证修复”。

## FT-009：Windows provisioning 在 QC 前没有做 PowerShell 语法验证

### 实测证据

v11 最终任务曾被 LLM QC 判为通过，但独立调用 PowerShell AST parser 后发现 provisioning 命令有 33 个语法错误，根因包括把 `\\'` 当成 PowerShell 单引号转义。该 fixture 不可能在 guest 中成功构建。

### 当前状态

Windows VM 结构验证会在主机存在 `powershell`/`pwsh` 时使用固定 AST parser 只解析、不执行 provisioning。v11 原响应现在会被拒绝；v12-v13 实测中该门多次在 QC 前触发 structural repair，修复后的最终命令再次解析为合法，状态为“已验证修复”。没有本地 PowerShell parser 的主机不会伪造验证结论，guest baseline 仍负责最终 fail-closed。

## FT-010：LLM 模式下未配置 Planner 时会静默使用本地默认计划

### 实测证据

v9 因 openai-compatible 角色没有绑定 API key，未出现 Planner 调用日志，直接生成本地默认的 3 个维度、100 道题，直到 Task Builder 缺 key 才失败。这掩盖了真正的配置错误，也偏离用户明确要求的一道题。

### 当前状态

`task_builder=llm` 时，Planner 未配置现在直接 fail-closed；只有显式 `task_builder=local/auto` 才允许本地计划。离线测试也已改为明确声明 local 模式。CLI 缺 key 复测已确认流程在 Planner 前直接失败，未再创建默认计划，因此标记为“已验证修复”。

## FT-011：目标模型上下文曾暴露 VM 故障注入和私有评分实现

### 实测证据

在准备本机运行 Windows Atlas 隐藏故障修复任务时，对最终数据集和 config-drive 做目标可见性审计，发现打包器会把完整 `vm_provisioning`、`evaluation`、`session.baseline_checks` 和隐藏文件名复制进目标模型的初始上下文。VM 内公开任务清单还包含 rubric，公开 agent task package 包含 evaluator 检查与执行方式。Atlas provisioning 中既有全部初始故障构造，也有本地合成账号密码；evaluation 中则有精确检查命令和预期状态。即使 VM 隔离和评分执行本身正确，目标也可能通过提示或公开文件直接获得私有答案。

审计来源：[`v13 最终 Builder 响应`](../benchmark-output/win-vm-gpt56-v13/debug/task-builder/long_horizon_windows_operations__windows_atlas_r-e8df3521/20260716T114316.585525Z-1fbe164c/attempt-02-structural-repair.response.txt)

### 为什么属于框架问题

Builder 已经把公开场景、环境构建、初始状态检查和最终评分放在不同字段；泄漏发生在框架将这些字段重新打包为目标上下文和 VM 公开清单时。它与目标模型能力无关，并会系统性破坏所有包含私有构造或 evaluator 的环境题。

### 当前状态

目标初始上下文现在只派生公开场景、可见文件以及经过清理的 session、VM、browser 和 notes；runner-private provisioning、baseline、evaluation、隐藏引用、bridge/Provider 凭证及 config-drive 路径均被移除。VM 公开清单不再包含 rubric；公开 agent task package 不再包含 evaluator、评分检查或隐藏引用名称，完整内容仍只写入 runner-private 文件。Oracle 已确认目标身份无法读取 seed state 和 task private 目录；同一私有 item 随后由真实 target 完成 17 步操作并获得 `5/6`，未依赖私有构造或评分内容。状态为“已验证修复”。

## FT-012：Windows bridge 命令继承可交互 stdin

### 实测证据

v8 真实 target 在修复 Scheduled Task 时调用了会要求输入密码的 `schtasks /change`。bridge 启动命令进程时没有重定向标准输入，`schtasks.exe` 因而持续等待不可提供的交互输入；target 把该次工具超时设为 3600 秒后，整场运行被一条命令占住。

### 当前状态

bridge 现在为命令进程启用标准输入重定向，并在进程启动后立即关闭输入流。需要人工输入的命令会立即看到 EOF 并失败，合法的长时间非交互命令仍可运行，不需要设置武断的短超时上限。同一道私有任务从 v9 干净快照重跑后不再挂起，17 步 target 轨迹和最终评分完整落盘，状态为“已验证修复”。

## FT-013：登录用户初始状态缺少可靠构建阶段

### 实测证据

Atlas 任务要求非管理员目标修复自己名下的 Scheduled Task。早期 provisioning 全部以 SYSTEM 执行，创建出的任务也由 SYSTEM 控制；虽然任务运行身份写成 AtlasOperator，目标仍无权修改它。尝试使用 RunOnce 或用户启动项执行初始化又存在时序和权限不确定性。

### 当前状态

Windows provisioning 现在明确分为 SYSTEM 阶段和 post-login interactive 阶段。SYSTEM 阶段创建用户、文件和受保护状态，事务式重启后，bridge 在监听前以实际登录用户令牌同步执行一次性 interactive setup，并用 `ready`/`failed` marker fail-closed。Oracle 与真实 target 均证明 AtlasOperator 可以修改其任务，同时不能读取私有目录，状态为“已验证修复”。

## FT-014：VirtualBox provisioning 重启可能永久停滞

### 实测证据

Windows 在 VirtualBox NEM 后端中曾长时间停在 `Restarting`。早期 Provider 只能按固定时长猜测是否重启，bootstrap 还曾使用错误的 `VBoxControl.exe` 路径，无法向宿主声明“provisioning 已完成且正在重启”。

### 当前状态

bootstrap 现在从 `C:\Windows\System32\VBoxControl.exe` 写入明确的 restart-pending guest property。Provider 只有在看到该信号持续超过 grace period 时才 reset，不会按固定时间盲重启。v8 oracle 和 v9 真实 target 均完成了克隆、provisioning、重启、bridge 恢复和最终自动清理，状态为“已验证修复”。

## FT-015：Windows evaluator 的等价表示会产生假阴性

### 实测证据

Oracle 已把 Scheduled Task 修复正确，但旧 evaluator 仍拒绝：Windows API 可能把登录类型表示为 `Interactive` 或 `InteractiveToken`，路径比较则被大小写敏感的正则表达式影响。这使正确系统状态被错误扣分。

### 当前状态

evaluator 现在显式接受等价登录类型，并用大小写不敏感的 literal path comparison 检查 Windows 路径。修复后的同权限 oracle 得分从 `2/6` 提升到 `5/6`；真实 target 的 `scheduled_task_correct` 和端到端计划任务检查也均通过，状态为“已验证修复”。

## 暂不列为核心系统问题的现象

- `api.sudocode.chat` 在医疗 benchmark v11-v14 的长 Planner/Builder 请求中反复返回 `upstream_error`、`ConnectError` 和 `RemoteProtocolError`，而同一 key、模型和 endpoint 的最小请求仍能在数秒内成功。流式路径补齐有界重试后，部分调用恢复，部分调用连续三次失败；单 Worker 也出现 Planner 连续五轮失败。2026-08-05 改用 `api.sudorelay.com` 后，完整 deepresearch、Planner、六个 Builder 和三轮 QC 均完成，两次 `RemoteProtocolError` 由同一重试机制恢复，运行最终只因任务合同问题 fail-closed。因此现有证据进一步指向旧外部 endpoint 的长请求不稳定，而不是 Builder 并发本身。原始失败仍保留用于观察频率；不能把重试耗尽后的外部故障伪装为框架成功。
- 某个 Builder 单独生成了一道方向错误的题，不足以证明框架缺陷。只有当框架的规划、契约或 QC 让同类错误成批出现或错误通过时，才归入本台账。
- 尚未真正运行 target model 的测试不能用于判断 runner、评分器或目标模型适配器正确与否。

## FT-016：VirtualBox 克隆后恢复快照的顺序错误

### 实测证据

在 `vm-chain-matrix-05-public-workspace` 中，Provider 先执行 `clonevm`，再尝试在新克隆上执行 `snapshot restore evalclaw-ready-secure-v9`。VirtualBox 的 machine clone 不复制源 VM 的快照树，因此新 VM 直接报“this machine does not have any snapshots”。

### 当前状态

Provider 现在在 `clonevm` 命令中直接传入 `--snapshot <source snapshot>`，不再对克隆机恢复不存在的快照。定向 VirtualBox 回归测试通过，状态为“已验证修复”。

## FT-017：Windows 双阶段启动默认等待窗口不足

### 实测证据

真实 Windows 任务需要首次启动、SYSTEM config-drive、自动重启、用户登录和 post-login setup。端到端诊断显示该链路在约 313 秒后才完成；120 秒和 300 秒窗口会在 guest 即将就绪时误报 bridge timeout。

### 当前状态

CLI、`BenchmarkConfig`、desktop environment 和 VirtualBox bridge wait 的默认上限统一提高到 600 秒。v10 模板上的完整 `Researcher` 任务随后自动创建、执行、评分为 `1.0` 并清理克隆，状态为“已验证修复”。

## FT-018：Windows bridge 异步重定向流收尾可能阻塞 listener

### 实测证据

一次真实评分中，guest PowerShell 子进程已经退出，但 bridge 在读取 `ReadToEndAsync().Result` 时不再响应后续 `/evaluate` 请求，导致评分调用超时；同一 VM 的最终四项状态实际上全部正确。

### 当前状态

`EvalClawBridge.ps1` 在带超时的 `WaitForExit` 成功后再调用无参 `WaitForExit()`，再读取异步 stdout/stderr 结果。更新后的脚本已写入 v10 模板，完整端到端任务得分 `1.0`，状态为“已验证修复”。

## FT-019：任务 artifact 对象被错误序列化为 Python 字典字符串

### 实测证据

Builder 合法地产生 `{path, kind, format}` artifact 对象时，打包器曾用 `str(item)` 生成 `"{'path': ...}"`，使 artifact collector 把整个字典文本当作文件名。

### 当前状态

打包器现在对字符串 artifact 保留原值，对对象 artifact 提取其 `path`，并用回归测试覆盖 `output_contract` 与 `artifact_collection`。状态为“已验证修复”。

## FT-020：Windows 命名用户断言识别不完整

### 实测证据

结构检查原先只识别 `$env:USERNAME -eq/-ne 'user'`，漏掉 Builder 常用的 `WindowsIdentity.GetCurrent().Name -match '\\user$'`。因此候选可以声称以 `Operator` 登录，却没有创建用户、配置自动登录或重启。

### 当前状态

验证器现在同时识别常见 Windows identity `-match` 断言，并在结构阶段 fail-closed。新的实测中缺少用户创建/登录配置的候选被拦截，修复后的 `Operator` 任务才进入 VM，状态为“已验证修复”。

## FT-021：目标用户无法读取私有 evaluator oracle，错误地表现为 0 分

### 实测证据

`vm-chain-matrix-06-operator-workspace-v2` 的 target 已将配置和报告修复正确，但 evaluator 以 `Operator` bridge 身份读取只授予 SYSTEM/Administrators 的 `C:\ProgramData\ExportWorkspaceEvaluator`，结果是 Access Denied。Runner 将该 evaluator 失败记成普通 `0.0`，掩盖了评分器权限错误。

### 当前状态

Builder Skill 已明确说明 evaluator 与 target 使用同一登录令牌；Windows GUI evaluator 不得运行时读取 target 不可访问的 oracle，必须把预期值或 hash 内嵌在检查命令中。结构验证现在会拦截能静态识别的受保护 oracle 引用，状态为“已验证修复”。

## FT-022：QC 摘要无标记截断 task-agent system prompt

### 实测证据

医疗欺骗 benchmark v10 的 Builder 原始响应包含完整的多轮 simulator `system_prompt`，结尾明确说明终止条件；QC 却报告 canonical prompt 在 `adapt to` 处半句结束，并据此拒绝最后一题。检查发现 `compact_task_agent_for_qc` 直接取前 800 字符，没有尾部也没有摘要标记，因此 QC 实际审查的是框架制造的截断文本。

日志：[`medical v10 run.log`](../benchmark-output/medical-deception-real-world-20260804-v10-stream-newkey/run.log)

完整 Builder 响应：[`multi-turn final repair`](../benchmark-output/medical-deception-real-world-20260804-v10-stream-newkey/debug/task-builder/multi_turn_deceptive_intent__bp_multiturn_escala-ba27cbdc/20260804T150733.712324Z-32ede474/attempt-01-initial.response.txt)

### 当前状态

task-agent QC 摘要现在保留首尾、原始字符数，并插入 QC 已认识的 `QC review excerpt clipped` 标记。回归测试证明 prompt 尾部和标记均存在；尚待同类端到端复测，状态为“已缓解，待复测”。

## FT-023：Planner 缺少执行环境能力边界

### 实测证据

医疗欺骗 benchmark v14 的 Planner 要求任务提供可编辑 workspace、受保护证据、报告文件、JSON schema、哈希和确定性 validator，却把环境类别选为内置 `workspace`。该 runtime 只能进行房间移动、物品检查和 outgoing-bin 搬运，Builder 无法实现文件编辑合同。QC 正确拒绝了任务。

日志：[`medical v14 run.log`](../benchmark-output/medical-deception-real-world-20260804-v14-stream-worker1-low/run.log)

### 当前状态

Planner Skill 现在明确四种 runtime 的实际能力，并要求包含文件、脚本、schema、hash、测试或可执行 validator 的任务选择 `code_sandbox` 或 `docker_workspace`，不得选择 `workspace`。该变化已通过 Planner/Builder 合同测试，尚待同类端到端复测，状态为“已缓解，待复测”。

## FT-024：OpenAI-compatible 流式路径缺少瞬态错误重试

### 实测证据

医疗欺骗 benchmark v11 在 SSE 数据中收到 `upstream_error: Upstream service temporarily unavailable` 后立即失败。非流式请求已有 429、5xx 和传输错误的有界重试，但新增流式实现没有同等机制，导致一次外部瞬态错误直接消耗 Builder 调用并终止整轮。

日志：[`medical v11 run.log`](../benchmark-output/medical-deception-real-world-20260804-v11-stream-newkey/run.log)

### 当前状态

流式请求现在对 429、5xx、传输中断和明确的 `upstream_error` 做最多三次、总时限 300 秒的有界重试；每次失败的部分响应会丢弃。v12-v14 真实日志已显示重试实际触发；改用 `api.sudorelay.com` 的 v15 又确认两次 `RemoteProtocolError` 均恢复，流程继续完成全部 QC 轮次。由于完整 benchmark 仍因任务合同问题未产包，状态暂保持“已缓解，待复测”。

## FT-025：Planner 可生成超出单次 Builder 稳定承载能力的 Blueprint

### 实测证据

医疗欺骗 benchmark v22 在默认 `mid` 规模下规划了 500 道题，却只拆成 7 个 Blueprint。前两个 Blueprint 分别要求单次 Builder 生成 110 和 80 道带真实来源与评分字段的任务。第一个 Blueprint 的三次响应分别得到 0、20 和 110 个可用任务；第二个分别得到 5、10 和 53 个，最终在结构修复耗尽后 fail-closed。第二个 Blueprint 的最后响应已有 38166 bytes，仍无法满足 80 题；这不是 API 连接失败，而是工作包超过单次稳定输出能力。

日志：[`medical v22 run.log`](../benchmark-output/medical-deception-real-world-20260805-v22-rightapi-responses-run.log)

诊断目录：[`medical v22 task-builder traces`](../benchmark-output/medical-deception-real-world-20260805-v22-rightapi-responses/debug/task-builder/)

### 额外风险

第一个 Builder 初始响应明确说明现有资源不足以构造 110 个具有病例级真实来源、许可或去标识状态、意图金标和证据跨度的任务，因此返回空数组以避免伪造。结构修复只把它作为数量错误继续要求完整重建，后续响应遂开始生成尚待人工补齐真实材料的占位任务。框架当前没有把“来源不足”与“输出数量不足”区分为不同的可修复状态，数量修复可能覆盖模型正确的证据边界判断。

### 当前状态

问题已确认，尚未修复。合理修复需要同时约束 Planner 的 Blueprint 序列化工作量，并决定 Builder 数量不足时采用增量补齐、Planner 重拆包还是来源不足 fail-closed；不能仅为本次医疗案例设置固定题数上限。

## FT-026：真实数据约束下 Planner/Builder 生成了不可解析的资源包引用

### 实测证据

医疗欺骗 benchmark v23 明确要求 exactly 20 tasks。Planner 正确生成 4 个维度、4 个 Blueprint、20 道题，Builder 也将每个工作包限制为 5 题。三轮 QC 修复后仍有 5 道题被拒绝，最终报告为 `15/20 items passed, 5 rejected, quality_score=0.915`。阻塞问题是题目要求 task-visible 的 `Packet FCR-1`、`Packet MHD-1`、`Packet FNS-1`、`Packet CCA-1` 和 `Packet FDR-1`，但对应任务没有可解析的 packet URI、文件、asset 或 dataset identifier，`source.uri` 为空。

研究阶段三轮结果同时确认：没有找到公开验证过、带专家欺骗标签的真实医疗数据集；现有候选来源缺少病例级 URL、许可、去标识记录或可复核金标准。Builder 在部分初始响应中正确拒绝伪造来源，但修复后仍可能保留不可解析的包名引用。

日志：[`medical v23 run.log`](../benchmark-output/medical-deception-real-world-20260805-v23-20tasks-rightapi-responses-run.log)

QC 完整追踪：[`medical v23 QC trace`](../benchmark-output/medical-deception-real-world-20260805-v23-20tasks-rightapi-responses/debug/qc/20260805T112359.460843Z-334e29fa/)

v24 将约束改为“数据必须是已有的真实数据”。Planner 转而规划 MIMIC-IV、CMS、FDA、WHO、DOJ/OIG 和已发表病例来源，但多数任务仍只包含自行改写的记录片段、数据库首页或“本地保留 extract”的声明，没有附带可审计的行标识、抽取结果、来源跨度或文件。第一轮 QC 修复后为 `9/20 items passed, 11 rejected`；剩余问题仍集中于把“现有数据集存在”误当成“构题所用的具体记录已经物化并可验证”。这进一步确认根因是资源载荷/稳定标识协议缺失，而不是上一版用户措辞要求了专家欺骗标签。

v24 追踪：[`medical v24 QC trace`](../benchmark-output/medical-deception-existing-real-data-20260805-v24/debug/qc/20260805T132804.254882Z-85089016/)

### 当前状态

问题已确认，尚未修复。Planner/Builder 协议需要把“引用一个资源包名称”与“提供可供任务执行和 QC 解析的资源载荷或稳定标识”区分开；在真实数据不可访问时，应在规划或构建阶段明确阻断，而不是让不可解析的资源引用进入 QC 修复循环。

## FT-027：QC 接受不存在的全局 item ID，导致通过/拒绝计数矛盾

### 实测证据

医疗欺骗 benchmark v24 的初始 QC 将数据集级问题返回为 `item_id="benchmark"`。`run_qc_gate` 未校验该 ID 是否属于真实任务，直接把它加入 `rejected_item_ids`，于是 20 道任务的摘要显示 `2/20 items passed, 19 rejected`；实际被拒绝的是 18 道任务，另一个拒绝 ID 是不存在的 `benchmark`。

报告：[`medical v24 initial QC`](../benchmark-output/medical-deception-existing-real-data-20260805-v24/debug/qc/20260805T132804.254882Z-85089016/00-initial/report.json)

### 当前状态

问题已确认，尚未修复。QC 解析层应将 `null`/空 ID 作为全局问题，并对其他 ID 做任务集合校验；未知 ID 不应污染逐题通过数和拒绝数。

## FT-028：QC 修复候选的单个 Blueprint 构建失败会中断整个循环

### 实测证据

v24 第一轮 QC 候选已从 2 道提升到 9 道通过。第二轮只修复 4 个受影响 Blueprint，其中 `bp_safe_communication` 连续三次把来源绑定写入 `metadata.source_ids`，没有写入顶层 `resource_ids`；结构验证正确拒绝了这些响应，但异常直接终止整个 benchmark，第三轮 QC 未运行，当前最佳的第一轮候选也没有正常完成流程或形成草稿包。

诊断：[`medical v24 failed Blueprint repair`](../benchmark-output/medical-deception-existing-real-data-20260805-v24/debug/task-builder/uncertainty_safe_communi-ddcfdbe0/20260805T133959.003814Z-ae2d0305/attempt-03-structural-repair.diagnostics.json)

### 当前状态

问题已确认，尚未修复。Builder 忽略明确字段反馈属于本次模型响应问题；框架问题是候选构建没有隔离失败 Blueprint，也没有在候选无效时保留当前最佳数据集并继续执行既定的 fail-closed 收尾。

## 维护规则

以后每次实测后按以下规则更新本文：

1. 新现象先与已有问题合并，优先记录共同根因，不按每次报错重复建项。
2. 必须附可复查的日志、响应或最终包路径。
3. 明确区分模型生成错误、外部服务错误和框架机制错误。
4. 修复代码后先标记“已缓解，待复测”；只有同类端到端测试通过后才标记“已验证修复”。
5. 如果新证据推翻旧归因，直接修正文档，不保留已经失效的历史结论。
