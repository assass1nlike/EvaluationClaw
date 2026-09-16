建议分配以下十款软件，每个需求使用两个不同环境。选择依据是能力匹配、可构造的任务变化、可检查的结果，以及本项目中的实现条件；不按经济权重选软件。

2026-09-16 完整审阅了官方 488 行精选软件清单，并核对入选软件的环境配置与代表任务。依据的源码版本为 `774476d752d748a69288f2ead97f75dd9df08ddb`。以下是选型方案，未运行新的生成或执行实验。

| 用户需求 | 软件 | 官方环境目录 | 互补性 |
|---|---|---|---|
| 1. 跨中断、恢复和重排，持续完成大型开放目标 | ERPNext；Moodle | `erpnext_env`；`moodle_env` | 跨模块业务闭环；课程体系建设与运行 |
| 2. 不同会话在共享项目中保持决策与成果一致 | Redmine；Nuxeo Platform | `redmine_env`；`nuxeo_platform_env` | 项目决策与交付状态；文档版本与发布状态 |
| 3. 从已有产物推断未成文的结构与规范 | Visual Studio Code；LibreOffice Writer | `vscode_env`；`libreoffice_writer_env` | 代码库；文档集合 |
| 4. 从症状定位复杂系统故障并最小修复 | WordPress；Rancher | `wordpress_env`；`rancher_env` | 应用与内容层；集群与服务基础设施层 |
| 5. 在硬预算内选择经济有效的策略 | QGIS；RStudio | `qgis_env`；`rstudio_env` | 空间分析与批处理；数据分析与可复用计算 |

这里的 1–5 对应用户本次给出的五条需求。

**1. ERPNext 与 Moodle：跨阶段推进同一个最终目标。**

ERPNext 的销售、采购、库存、制造、交付和收付款共用业务对象，前期决策会约束后续操作。适合“完成一次客户交付并完成财务结算”之类的目标：中途出现缺货、交期变化或恢复会话后，仍需维护原订单、库存和资金之间的一致性。完成最后一张表单并不等于完成整个目标。可展开的题目方向包括订单履约、采购补货、分批交付、制造与质量处理、退货结算。

Moodle 可以承载“把一套培训方案建成可运行的课程体系”：课程结构、内容、题库、分组、先修限制、评分和结业条件相互关联。插入学员群体变化或重排课程建设顺序后，仍要兑现最初的学习目标与交付条件。可展开课程建设、分层学习路径、考核体系、特殊学员安排和学期迁移等方向。

两者的结果可以检查业务记录、依赖关系和可用状态，减少只凭长篇报告判断完成度的问题。相比 ProjectLibre，二者能实际完成业务或教学配置，而不只是制定描述未来工作的计划。

这类题必须保留同一项目状态，实际包含中断、恢复或重排，且让模型自行分解目标。一次连续执行很多点击、或顺序执行互不关联的小题，都不足以满足需求 1。

**2. Redmine 与 Nuxeo Platform：跨会话识别并尊重已确定的事实。**

Redmine 将讨论、问题单、里程碑、Wiki、附件和仓库关联在同一项目中，适合让后续会话在已有交付和决策基础上继续推进。例如早期方案已经被讨论否决、替代方案已有交付，后续会话应发现这些事实，避免重开废弃方案或重复创建已完成工作。题目可覆盖发布交接、范围调整、缺陷合并、跨子项目依赖和里程碑迁移。不能仅检查工单是否关闭，还要检查关联成果和决策是否一致。

Nuxeo Platform 提供文档版本、审核流程、生命周期、发布副本和访问权限，适合共享规范、合同和产品资料的多会话维护。例如已批准版本对外生效，而更新的内部草稿尚未批准；后续会话必须识别正确依据，不能机械地以“最后修改的文件”为准。题目可覆盖修订交接、内外版本同步、发布管理、资料合并和审核续办。

这对组合分别检查项目决策与文档成果的一致性。相比 Rocket.Chat 或 Mattermost，它们更容易同时保留“说过什么”和“实际做成什么”的证据，避免任务退化为聊天记录检索。

区别于需求 1，这里主要改变会话所掌握的上下文，检查不同会话对共享项目的认识是否一致；不必依赖每个会话都特别长。应保留共享状态，不能在每个会话开始时重新初始化项目。

**3. Visual Studio Code 与 LibreOffice Writer：分别覆盖代码和文档中的隐式规范。**

Visual Studio Code 可直接检查目录结构、相邻实现、调用关系、测试组织和错误处理方式，并新增符合已有设计的功能。适合让模型从多个现有模块中推断分层边界、接口形状、命名方式、数据流和扩展点。题目可覆盖添加模块、接入数据源、增加命令、扩展界面和补充持久化逻辑。功能正确与遵循本地规范应分别检查。

LibreOffice Writer 可从已有文档的章节组织、段落样式、术语、编号、表格和交叉引用中推断规范，再编写相容的新章节或新文档。题目可覆盖系列报告、技术手册、会议纪要、操作规程和合同附件。应检验可编辑文档的结构与样式关系，而不只看截图是否相似。

相比同时选择 VS Code 和 PyCharm，代码库与文档集合的组合覆盖了需求中两种明确不同的载体。两者都有独立的持久化产物，便于检查新增内容与原有内容的关系。

题目不能附带明确的规范说明、列出应该照搬的规则，或只要求遵守某个公共格式标准。已有产物须有足够一致的实例，使目标规范确实可以推断；允许多种合理实现，避免把作者没有在产物中体现的个人偏好作为唯一答案。

**4. WordPress 与 Rancher：分别定位应用层和基础设施层的故障。**

WordPress 的页面表现由内容、主题、插件、权限、媒体路径、缓存和数据库状态共同决定。适合从“部分角色看不到内容”“某些页面跳转错误”“更新后显示旧内容”等症状出发，识别真正原因并局部修复。题目可以覆盖路由、权限、主题、插件交互、媒体和缓存问题。应同时检查受影响功能恢复及原本正常的页面、权限或插件功能未被破坏。

Rancher 管理的 Kubernetes 环境具有服务、工作负载、配置、网络策略、存储、调度和健康检查之间的多层关系。适合“部分请求无法完成”“发布后仅某条业务链路失效”一类初始症状。题目可覆盖服务选择器、服务发现、配置漂移、网络策略、挂载和就绪状态。评分需覆盖业务连通性、其他工作负载及安全约束，不能把关闭所有限制或重建整个集群视为最小修复。

相比 Jenkins，这一组合覆盖应用故障与多服务基础设施故障两个更不同的层次；Jenkins 更容易围绕构建失败和显式错误日志组织题目。现有 WordPress 与 Rancher 任务已展示相应的故障注入和状态检查能力，但不自动满足“只给症状”的条件。

选型按“初始输入不提供复现步骤、失败测试或堆栈”理解需求 4；并不要求禁止模型自行诊断或禁止评分端验证修复。任务不能把根因、故障资源名或修复步骤泄漏给被测模型。最小修复需要结合有效改动范围与行为保持判断，不能只数修改行数。

**5. QGIS 与 RStudio：让策略选择产生可观察的资源差异。**

QGIS 同时支持逐对象操作、表达式筛选、空间连接、批量处理和处理模型。同一个任务可以逐区手工处理，也可以先缩小候选范围、一次性计算并复用流程。适合多区域风险分析、设施覆盖、空间匹配、重复地图输出和大批要素清理。可验证导出数据的要素集合、几何关系、坐标系和统计值，而不要求模型选择唯一的算法。

RStudio 支持向量化计算、联结与聚合、可复用函数和参数化报告。适合多个分组或批次的分析、重复报告、跨表核对和受限计算量下的估计问题。便宜但正确的路径可能是复用中间结果、合并计算，或在允许误差内采用合适的估计方法；不能为了省资源而遗漏任务要求。相比再选一个 GIS 工具，它提供了不同的数据结构、交互方式和计算策略。

预算应由执行系统强制记账和截断，并明确计算范围；生成器自身的调用预算不等于被测模型的预算。题目要有可行的经济策略，不能仅把普通题的时间压短。不要在题干直接告诉模型使用批处理或参数化；也不要因为解法“常见”而扣分，核心证据是正确性、成本和策略选择。“不寻常”可作为轨迹分析的补充维度。

**候选对比与实现依据。**

完整候选来源是 [selected_products.csv](../extras/research/task_generation/propose_and_amplify/memory/task_creation_notes/selected_products.csv)。十款名称均与该表精确对应；任务方向与职业信息参考了同目录的 [master_dataset.csv](../extras/research/task_generation/propose_and_amplify/memory/task_creation_notes/master_dataset.csv)。经济权重没有作为能力匹配的替代指标。

下表列出核对过的官方题目，证明相应操作和产物在项目中已有实现基础，不表示这些现有题已满足本次能力要求，也不表示需要直接复用这些题。

| 软件 | 官方题目示例 |
|---|---|
| ERPNext | [制造到收款的业务闭环](../benchmarks/cua_world/environments/erpnext_env/tasks/make_to_order_fulfillment/task.json) |
| Moodle | [分层考核与学习路径](../benchmarks/cua_world/environments/moodle_env/tasks/configure_tiered_assessment_pathway/task.json) |
| Redmine | [里程碑核对与项目复盘](../benchmarks/cua_world/environments/redmine_env/tasks/q1_milestone_reconciliation/task.json) |
| Nuxeo Platform | [不同版本的内外发布](../benchmarks/cua_world/environments/nuxeo_platform_env/tasks/manage_versioned_publications/task.json) |
| Visual Studio Code | [代码库与工作区编辑](../benchmarks/cua_world/environments/vscode_env/tasks/standardize_workspace_and_remediate_code/task.json) |
| LibreOffice Writer | [多文档手册组装](../benchmarks/cua_world/environments/libreoffice_writer_env/tasks/technical_manual_master_assembly/task.json) |
| WordPress | [性能故障与插件处理](../benchmarks/cua_world/environments/wordpress_env/tasks/diagnose_performance_bottleneck_and_cache/task.json) |
| Rancher | [多服务连通性修复](../benchmarks/cua_world/environments/rancher_env/tasks/microservice_mesh_connectivity_restoration/task.json) |
| QGIS | [空间处理模型及批处理](../benchmarks/cua_world/environments/qgis_env/tasks/airport_proximity_modeler_automation/task.json) |
| RStudio | [参数化分析报告](../benchmarks/cua_world/environments/rstudio_env/tasks/airline_parametrized_reporting/task.json) |

十款均有 Linux 环境实现；本机会话此前只实际运行过 Writer，不能据此声称其他九款已跑通。Rancher 包含 Kubernetes 服务，ERPNext、Nuxeo 等包含后台服务；各自仍需验证安装、资源和状态持久化。

软件选择属于输入侧适配。上面的题目方向用于解释选择，不能替代 Gym-Anything 的题目生成，更不能通过人工补全生成结果来掩盖 baseline 的不足。需求 1、2 的跨会话行为和需求 5 的硬预算不是选软件后自动获得的能力；后续若使用外部运行协议，应与被比较方法保持同等条件，并单独记录。生成、扩增及官方评分的核心流程保持不变；外部能力评估与官方评分分别报告。
