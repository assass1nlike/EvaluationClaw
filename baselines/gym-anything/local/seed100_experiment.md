本轮目标 100 道种子题：D1 ERPNext、Moodle；D2 Redmine、Nuxeo Platform；D3 Visual Studio Code、LibreOffice Writer；D4 WordPress、Rancher；D6 QGIS、RStudio。每软件同一会话生成 10 道，最大 10 并行，只执行官方 propose 四阶段，不扩增。每阶段超时 36000 秒（10 小时）。

需求以主仓库 user-inputs.txt 前 15 行为准，本批使用第 1、2、3、4、6 行，完整文件快照保存在本批 user-inputs.txt。四阶段均注入需求原文和已批准的统一说明：以需求中的能力与限制条件作为设计目标，任务情境、初始状态和成功判据应检验它们，官方示例用于实现参考而不能替代评测目标。不提供具体题目、解法或评分规则。

批次：local/outputs/seeds10_clean_20260918T104248Z。命令：在 gym-anything 根目录执行 .venv/bin/python -u local/isolation/run_batch.py --batch local/outputs/seeds10_clean_20260918T104248Z。开始模型调用前，各容器生成 isolation_check.json；确认全部通过后为各软件写入空的 start 文件放行。官方提交 774476d752d748a69288f2ead97f75dd9df08ddb，任务类型 enterprise，原始示例任务来自该提交。提题提示仅把 5 new tasks 改为 10 new tasks；阶段提示、顺序、验证、失败处理和清理仍由官方实现执行。外层仅保存日志和隔离宿主资源，生成期间框架错误先报告讨论，不自行修补。

模型 deepseek-flash，服务 https://api.deepseek.com，提题使用 /anthropic，官方截图 MCP 使用 OpenAI 兼容接口。Claude Code 2.1.229，Python 3.12.13，依赖锁定文件保存在本批 requirements.lock。seed_everything 设置 Python/NumPy 为 42，PYTHONHASHSEED=42；远端接口无 seed。采样不覆盖 CLI/provider 默认；继承原始 effortLevel 和 CLAUDE_CODE_EFFORT_LEVEL（xhigh），服务端解释未知。保留正常 CLI 配置及 MCP 发现，项目模型配置仍指向 DeepSeek。凭据由只读本地配置文件提供，不写入本记录。

每软件使用独立 Ubuntu 24.04 生成容器、临时目录、HOME、Claude 配置与会话目录、Docker daemon/存储/网络、QEMU 软件缓存。仅挂载当前软件新工作副本、必要依赖和原始基础镜像；宿主旧输出、旧临时目录、旧会话、主仓库任务目录、宿主 Docker socket 均不挂载。保留祖先 CLAUDE.md/AGENTS.md 的发现；Claude 全局配置只保留 effort 与跳过权限提示设置，历史会话、记忆和 shell 快照不导入。基础桌面镜像 gym-anything-local/ubuntu-gnome-highres:20260915 与 QEMU 基础镜像沿用上一轮；软件 checkpoint 从空开始。保留此前批准的 Docker timeout/VNC、Docker/runc、QEMU/KVM 适配。生成器镜像 gym-anything-local/seed-isolation:20260918 的构建文件和镜像 ID 另存，基础镜像导入每软件私有 Docker；宿主历史镜像保留但不可由生成器直接枚举或调用。

此前 seeds10_20260918T100243Z 已按用户要求停止，不计入本轮结果；其 /tmp/nuxeo_probe、/tmp/taskdev、/tmp/erp_sandbox、/tmp/et_php 已移入该批 archived_tmp，停止并清理了本批容器及派生虚拟机。历史 51 题及其评估结果保留在宿主归档中。本轮以新会话、新官方源码和新软件缓存开始。最终按实际产出和验证证据统计，不人工补足数量。

隔离准备：在 gym-anything 下以 docker build -t gym-anything-local/seed-isolation:20260918 local/isolation 构建生成器镜像，以 docker save gym-anything-local/ubuntu-gnome-highres:20260915 -o local/outputs/isolation_assets/desktop.tar 导出原始桌面镜像供私有 Docker 导入。生成器内 Docker 为 29.1.3，镜像 ID 保存在 isolation_image.json。启动前回归检查 317 passed、22 skipped、7 subtests passed；KVM ioctl 返回 API 版本 12。准备过程中修复了 Python 解释器别名路径缺失，以及隔离目录检查误用有序列表的问题；这两次预检均未进入模型调用，相关日志归档于前一准备批次 local/outputs/seeds10_clean_20260918T102713Z 的 preflight_error 和 preflight_check_error。

生成容器连接专用宿主网络 gym-seed-isolated（10.250.0.0/24）。local/isolation/proxy.py 在 10.250.0.1:17890 将流量转发至宿主原有 127.0.0.1:7890 代理；http_proxy、https_proxy、all_proxy 使用该转接，NO_PROXY 继承原配置。代理转接本身不读取或暴露宿主文件。每个容器在调用模型前验证 GitHub 和 DeepSeek 连通性。前一次隔离尝试通过了文件系统检查，但因未继承宿主代理导致 GitHub 下载超时，已整体停止，本批使用新会话和空软件缓存重跑。

正式启动检查（2026-09-18T10:49:23.515940+00:00）：全部 10 份 isolation_check.json 通过，包含旧输出/旧临时文件/旧会话不可见、私有 Docker 镜像仅含原始基础镜像或为空、KVM 可访问、GitHub 与 DeepSeek 连通性。实际容器挂载与网络配置保存在 host_mount_audit.json，私有 Docker 中真实启动测试容器通过。10 路已进入官方第一阶段、各自使用独立新会话并收到模型响应，实际模型 deepseek-flash、超时 36000 秒。证据见 released.json、startup_check.json 和各软件 phase_1.input.json/phase_1.jsonl；后台入口 PID 见 process.json。

安全核查（2026-09-18T15:02:16.117904+00:00）：本批全部冻结并断网，代理转接停止，旧启动入口禁用。特权外层容器不能保护宿主；发现成功执行共享内核参数写入和凭据进入工具输出日志。完整范围、证据、限制及恢复前要求见 local/isolation/security.md。当前未恢复生成，不能将旧产物不可见表述为宿主安全隔离。


2026-09-18 独立 VM 验证：单 VM 的宿主文件/内核隔离、网络限制、CPU/内存/PID/磁盘限制，以及内部 Docker、嵌套 QEMU 的实际运行检查通过。deepseek-flash 经官方 CLI 调用完成一次来宾内工具操作，最大 3 轮、180 秒，实际 2 轮；仅为基础链路检查，不产生正式题目。运行器 seed=42、远端模型无 seed，采样使用 CLI/provider 默认。完整配置、输入版本、失败记录与验证范围见 local/isolation/vm/README.md，证据在 local/outputs/vm_isolation_check。旧批次继续冻结、断网，正式 100 题未启动；批量 VM 接入、各软件下载链路及容量规划仍待完成。
