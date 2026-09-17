本轮重新构建 50 道种子题：五个需求各两个软件，每软件 5 道，仅运行 propose，不扩增。需求原文为 local/requirements/goal_1.txt 至 goal_5.txt，软件映射保留 local/software_selection.md。批次目录：local/outputs/seeds_20260916T144940Z；上一批完整保留在 local/outputs/seeds_20260916T084835Z，其方法记录为 experiment.md。

运行命令：在 gym-anything 根目录执行 `.venv/bin/python -u local/seed_batch.py --batch local/outputs/seeds_20260916T144940Z`。十个软件并行，四阶段各 7200 秒，每软件独立新会话，源码从官方固定提交 774476d752d748a69288f2ead97f75dd9df08ddb 检出，分支 seed-generation；没有导入上一批生成的任务或软件脚本。批次保存实际入口源码、输入、日志、结果、原始环境配置与需求。

模型 deepseek-flash，API https://api.deepseek.com，提题经 /anthropic 接口，官方截图 MCP 经 OpenAI 兼容接口。需求仍以 append-system-prompt 传入四阶段，官方提示与阶段顺序不变。CLI 2.1.229，依赖见 local/requirements.lock；Python/NumPy/hash seed 42，远端 API 无 seed。没有添加采样参数、轮数或费用上限。正常 CLI 配置发现恢复后，本机已有 effortLevel=xhigh/CLAUDE_CODE_EFFORT_LEVEL 配置也会被加载；未另作采样覆盖，不能保证服务端如何解释该设置。

已恢复四项行为：不使用 bare、不使用 strict-mcp-config 或 mcp-config 参数、不因调用失败由外部包装停止、不自行实现进程组清理。记录层直接调用上游 run_claude，仅观察 Popen 的退出/超时和保存流式输出，不改变等待、异常传播、后续阶段或清理决策。上游会在调用正常结束或超时后清理进程组，并继续后续阶段；所以整体退出 0 不代表各阶段成功。

截图工具通过各工作副本 .mcp.json 正常发现，项目 settings.local.json 允许该 MCP。沿用正常 CLI 配置目录，不新增隔离目录。主机个人设置另有其他模型与地址，故项目配置只覆盖 DeepSeek 相关服务、凭据及模型别名，避免调用错误服务；该文件权限 600，写入 Git 本地排除规则，凭据不进入配置快照和报告。仓库 CLAUDE.md、AGENTS.md 保留自动发现行为。

本轮范围仅恢复上述四项，Docker timeout/VNC 补丁保留，仍不能称为完全未修改的上游。保留 Docker/runc、自定义网络、本地桌面镜像与 QEMU/KVM 运行适配。QEMU 共用已验证的基础镜像，但软件 checkpoint 位于本批独立 qemu_cache；Docker 环境 version 附加批次名隔离 checkpoint，防止重用上一批被生成代理修改的状态。共享基础镜像 SHA256 为 a6caf767e214781120b53d8477bb5f59ea91fc65d74e92a4c09e87f5e090c939。

验证：恢复后的入口和已有测试共 319 passed、22 skipped、7 subtests passed，日志 local/outputs/official_restore_tests.log。四个真实子进程测试覆盖正常退出、非零退出、模型 is_error、超时：记录层均不额外阻断，官方清理会终止同组后台子进程。正式构建前做了一次独立 READY 请求，deepseek-flash 返回正常，正常配置发现下 visual-grounding 连接成功；日志在本批 preflight，未作为种子题会话。检查没有改任务。

人工仅监督、记录和处理 API/本机资源问题；发现框架 bug 不修补、不手动绕过，先向用户报告并讨论。官方生成代理按照原有提示自行调试仍属于本轮构建轨迹。独立审查不向生成器反馈。阶段失败、题目数量不足、真实验证缺失都按实际记录，不为凑够 50 人工补题或追加提示。
