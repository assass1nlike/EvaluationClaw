本轮生成 50 道种子题：五条评测需求，各对应两个软件，每软件 5 道。只运行官方 propose 阶段，尚不扩增。需求原文见 `requirements/goal_1.txt` 至 `goal_5.txt`；软件映射与选择理由见 `software_selection.md`。

运行入口：在 gym-anything 根目录执行 `.venv/bin/python local/seed_batch.py`。每次建立 `local/outputs/seeds_<UTC>/`，最新路径写入 `local/outputs/latest_seed_batch.txt`。十个软件各用一个共享 Git 对象、独立工作树的 clone；官方示例任务完整保留在各 clone 中。生成结果位于 `<软件>/workspace/benchmarks/cua_world/environments/<软件>/tasks/`。

模型为 deepseek-flash，API 根地址 https://api.deepseek.com，Claude Code 通过其 `/anthropic` 接口调用，视觉 MCP 使用同一模型的 OpenAI 兼容接口。凭据由 `local/.env` 载入，不进入配置快照。Claude Code 2.1.229；Python 依赖见 `requirements.lock`。上游提交 774476d752d748a69288f2ead97f75dd9df08ddb。远端模型采样参数沿用 CLI/服务默认值，未额外设置 temperature、top_p、最大输出或思考预算；Anthropic 协议没有请求 seed 参数。各 Python 进程的 seed_everything 固定 random 与 NumPy 为 42，PYTHONHASHSEED=42；这不保证远端生成或生成代码内随机行为完全复现。

每个软件使用官方 enterprise 提题流程：读取全部规范 → 参考已有任务并生成 5 道新题 → 官方盲提示要求复查、补全及检查实际运行截图 → 写入本次种子清单。需求原文通过 `--append-system-prompt` 在四次调用中传入，不添加人工题目设计或评分规则。每次调用的时限均为官方默认 7200 秒；十路并发，无额外轮数或费用上限。Claude 使用 bare 模式隔离个人 hooks、自动记忆和 CLAUDE.md 自动发现；各软件独立保存会话。显式配置官方 visual_grounding MCP。

外部包装记录每阶段的完整输入、JSONL 模型/工具输出、stderr、退出状态和最终结果。阶段超时、CLI 非零退出、缺失结果或 is_error 会停止该软件后续流程，避免上游将进程失败误记为完成。包装不修改任务内容、规范或官方阶段顺序。

服务类 ERPNext、Moodle、Redmine、Nuxeo、WordPress、Rancher 使用官方 QEMU 后端和单次构建的共享基础镜像；生成进入第二阶段前等待基础镜像就绪。VS Code、Writer、QGIS、RStudio 使用 Docker/runc、gym-anything-local 网络和本地官方桌面镜像 gym-anything-local/ubuntu-gnome-highres:20260915。各环境仅调整运行后端、镜像、挂载绝对路径和记录目录，保留原软件安装与初始化脚本；原始 env.json 单独留存。Docker 使用此前验证过的超时和 VNC checkpoint 恢复兼容修复。

最终应分别报告：实际产生的新任务数、必需文件和语法检查、模型自身的离线验证、真实软件环境验证，以及未通过或未执行的部分。完成提题不等于任务已通过真实环境评测，也不等于需求覆盖质量合格。

QEMU 基础系统使用 Ubuntu QEMU 6.2.0（包 6.2+dfsg-2ubuntu6.31），官方构建镜像大小 6,956,777,472 字节，SHA256 为 a6caf767e214781120b53d8477bb5f59ea91fc65d74e92a4c09e87f5e090c939。构建、镜像检查、KVM/SSH/X11/VNC 1920×1080 验证记录位于 `outputs/qemu_setup/`，安装与复现方式见 `runtime/qemu/README.md`。宿主用户加入 kvm 组；Python 启动 shim 使已启动会话的子进程获得 KVM 组权限，并使用 `local/q/1..6` 避免 Unix socket 路径过长。

共享镜像首次构建期间，六个服务类 CLI 会话暂停，镜像验证完成后原地恢复。ERPNext 与 Redmine 在恢复时报告流式响应中断；保留原调用记录，从原会话的官方提题阶段（start_idx=1）继续，未重新生成提示、人工补题或更换模型。对应目录的 `recovery.json`、`initial_exit.json` 与各阶段日志记录了这次基础设施恢复。CLI 输出中的美元费用是客户端估计，不应当作 DeepSeek 账单金额。

截图分析服务依赖固定为 mcp==1.30.0（官方服务使用 FastMCP v1 接口），真实 stdio 初始化与工具列表查询通过，见 `outputs/mcp_check.json`。依赖补齐之前启动的 CLI 阶段记录为 MCP 加载失败；之后的新阶段会加载该工具。早期阶段的截图检查能力不能按“已提供 MCP”推定成功，需逐题查看实际证据。
