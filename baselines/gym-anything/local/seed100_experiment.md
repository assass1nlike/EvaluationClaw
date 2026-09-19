本轮目标 100 道种子题：D1 ERPNext、Moodle；D2 Redmine、Nuxeo Platform；D3 Visual Studio Code、LibreOffice Writer；D4 WordPress、Rancher；D6 QGIS、RStudio。每软件同一会话生成 10 道，最大 10 并行，只执行官方 propose 四阶段，不扩增。每阶段超时 36000 秒（10 小时）。旧批次已停止，新机批次为 `local/outputs/s100_0919`，使用独立安全 VM 构建。

新机器正式构建任务类型为 enterprise，Claude Code 固定 2.1.229，所有模型使用 deepseek-flash，thinking 开启，DeepSeek 和 Claude Code 的 effort 均为 high，配置保存在 `local/deepseek-settings.json`。所有可设置的本地随机种子均为 42；API 不设置 seed，用户接受远端输出的随机性。启动后检查官方截图 MCP 的真实图片调用、thinking/high 参数及返回结果，记录异常；目前主模型工具链已验证，截图模型调用仍待实测。单 VM 参数与工具链检查见 [新机配置](setup.md)。下文保留旧批次实际使用的配置与运行记录。

需求以主仓库 user-inputs.txt 前 15 行为准，本批使用第 1、2、3、4、6 行，完整文件快照保存在本批 user-inputs.txt。四阶段均注入需求原文和已批准的统一说明：以需求中的能力与限制条件作为设计目标，任务情境、初始状态和成功判据应检验它们，官方示例用于实现参考而不能替代评测目标。不提供具体题目、解法或评分规则。

批次：local/outputs/seeds10_clean_20260918T104248Z。命令：在 gym-anything 根目录执行 .venv/bin/python -u local/isolation/run_batch.py --batch local/outputs/seeds10_clean_20260918T104248Z。开始模型调用前，各容器生成 isolation_check.json；确认全部通过后为各软件写入空的 start 文件放行。官方提交 774476d752d748a69288f2ead97f75dd9df08ddb，任务类型 enterprise，原始示例任务来自该提交。提题提示仅把 5 new tasks 改为 10 new tasks；阶段提示、顺序、验证、失败处理和清理仍由官方实现执行。外层仅保存日志和隔离宿主资源，生成期间框架错误先报告讨论，不自行修补。

模型 deepseek-flash，服务 https://api.deepseek.com，提题使用 /anthropic，官方截图 MCP 使用 OpenAI 兼容接口。Claude Code 2.1.229，Python 3.12.13，依赖锁定文件保存在本批 requirements.lock。seed_everything 设置 Python/NumPy 为 42，PYTHONHASHSEED=42；远端接口无 seed。采样不覆盖 CLI/provider 默认；继承原始 effortLevel=xhigh、CLAUDE_CODE_EFFORT_LEVEL=high，服务端解释未知。保留正常 CLI 配置及 MCP 发现，项目模型配置仍指向 DeepSeek。凭据由只读本地配置文件提供，不写入本记录。

每软件使用独立 Ubuntu 24.04 生成容器、临时目录、HOME、Claude 配置与会话目录、Docker daemon/存储/网络、QEMU 软件缓存。仅挂载当前软件新工作副本、必要依赖和原始基础镜像；宿主旧输出、旧临时目录、旧会话、主仓库任务目录、宿主 Docker socket 均不挂载。保留祖先 CLAUDE.md/AGENTS.md 的发现；Claude 全局配置只保留 effort 与跳过权限提示设置，历史会话、记忆和 shell 快照不导入。基础桌面镜像 gym-anything-local/ubuntu-gnome-highres:20260915 与 QEMU 基础镜像沿用上一轮；软件 checkpoint 从空开始。保留此前批准的 Docker timeout/VNC、Docker/runc、QEMU/KVM 适配。生成器镜像 gym-anything-local/seed-isolation:20260918 的构建文件和镜像 ID 另存，基础镜像导入每软件私有 Docker；宿主历史镜像保留但不可由生成器直接枚举或调用。

此前 seeds10_20260918T100243Z 已按用户要求停止，不计入本轮结果；其 /tmp/nuxeo_probe、/tmp/taskdev、/tmp/erp_sandbox、/tmp/et_php 已移入该批 archived_tmp，停止并清理了本批容器及派生虚拟机。历史 51 题及其评估结果保留在宿主归档中。本轮以新会话、新官方源码和新软件缓存开始。最终按实际产出和验证证据统计，不人工补足数量。

隔离准备：在 gym-anything 下以 docker build -t gym-anything-local/seed-isolation:20260918 local/isolation 构建生成器镜像，以 docker save gym-anything-local/ubuntu-gnome-highres:20260915 -o local/outputs/isolation_assets/desktop.tar 导出原始桌面镜像供私有 Docker 导入。生成器内 Docker 为 29.1.3，镜像 ID 保存在 isolation_image.json。启动前回归检查 317 passed、22 skipped、7 subtests passed；KVM ioctl 返回 API 版本 12。准备过程中修复了 Python 解释器别名路径缺失，以及隔离目录检查误用有序列表的问题；这两次预检均未进入模型调用，相关日志归档于前一准备批次 local/outputs/seeds10_clean_20260918T102713Z 的 preflight_error 和 preflight_check_error。

生成容器连接专用宿主网络 gym-seed-isolated（10.250.0.0/24）。local/isolation/proxy.py 在 10.250.0.1:17890 将流量转发至宿主原有 127.0.0.1:7890 代理；http_proxy、https_proxy、all_proxy 使用该转接，NO_PROXY 继承原配置。代理转接本身不读取或暴露宿主文件。每个容器在调用模型前验证 GitHub 和 DeepSeek 连通性。前一次隔离尝试通过了文件系统检查，但因未继承宿主代理导致 GitHub 下载超时，已整体停止，本批使用新会话和空软件缓存重跑。

正式启动检查（2026-09-18T10:49:23.515940+00:00）：全部 10 份 isolation_check.json 通过，包含旧输出/旧临时文件/旧会话不可见、私有 Docker 镜像仅含原始基础镜像或为空、KVM 可访问、GitHub 与 DeepSeek 连通性。实际容器挂载与网络配置保存在 host_mount_audit.json，私有 Docker 中真实启动测试容器通过。10 路已进入官方第一阶段、各自使用独立新会话并收到模型响应，实际模型 deepseek-flash、超时 36000 秒。证据见 released.json、startup_check.json 和各软件 phase_1.input.json/phase_1.jsonl；后台入口 PID 见 process.json。

安全核查（2026-09-18T15:02:16.117904+00:00）：本批全部冻结并断网，代理转接停止，旧启动入口禁用。特权外层容器不能保护宿主；发现成功执行共享内核参数写入和凭据进入工具输出日志。完整范围、证据、限制及恢复前要求见 local/isolation/security.md。当前未恢复生成，不能将旧产物不可见表述为宿主安全隔离。


2026-09-18 独立 VM 验证：单 VM 的宿主文件/内核隔离、网络限制、CPU/内存/PID/磁盘限制，以及内部 Docker、嵌套 QEMU 的实际运行检查通过。deepseek-flash 经官方 CLI 调用完成一次来宾内工具操作，最大 3 轮、180 秒，实际 2 轮；仅为基础链路检查，不产生正式题目。运行器 seed=42、远端模型无 seed，采样使用 CLI/provider 默认。完整配置、输入版本、失败记录与验证范围见 local/isolation/vm/README.md，证据在 local/outputs/vm_isolation_check。旧批次已终止，正式 100 题未启动；批量 VM 接入、各软件下载链路及容量规划仍待完成。

2026-09-19 新机批次 `local/outputs/s100_0919`：用户批准启动正式 100 题。入口为 `source local/runtime/activate.sh` 后执行 `.venv/bin/python -u local/isolation/vm/run_batch.py --batch local/outputs/s100_0919`。十台生成 VM 各分配 8 vCPU、24 GiB 内存、200 GiB 预分配工作盘；外层限制 8 CPU、28 GiB 内存、无额外 swap、512 PID/线程。合计 80 CPU 配额、280 GiB 内存上限、2000 GiB 工作盘，各软件内部资源仍使用官方 env.json。受限网络、SSH 公钥、非特权只读外层及不发布宿主端口的边界沿用已验证方案。全部 VM 预检通过后一起进入官方四阶段；每阶段 36000 秒，官方进程退出、超时及继续下一阶段的逻辑原样保留。外层服务以 145200 秒限制异常残留，超出四阶段的总预算。

生成初始镜像从原公钥基础镜像的新副本构建，只安装 Docker/QEMU 和已锁定的运行依赖、原桌面镜像与官方源码，不运行模型、不含历史题目或会话。镜像 `local/outputs/vm_base/generator.qcow2`，SHA256 `482b5b22eb4726aa9a235b5831daaad7e2703bd4ef00f5a44303707d773f97b8`。每个软件另建嵌套 VM 密钥，在断网配置过程中写入嵌套基础镜像；宿主管理私钥不传入来宾。软件 VM 的代理设置属于网络适配，访问仍由宿主侧域名/IP 白名单约束。安装域名根据官方脚本加入白名单，被拒绝的主机名和端口记录到各软件 egress.jsonl，不记录 URL 或认证头。

截图 MCP 的外部入口仅为官方 OpenAI 客户端请求加入 `thinking.type=enabled` 和 `reasoning_effort=high`，保留官方提示、图片缩放、max_tokens=4096、响应文本和错误行为；记录是否成功、输出长度与 usage，不记录思考正文或认证信息。正式主模型调用仍由官方 Claude Code 执行。运行源码、依赖锁及 SHA256 清单保存至批次 source，需求原文及各软件配置另存；每 30 秒导出阶段日志与状态并替换实际 API key。完整原始状态保留在各 VM 私有磁盘，最终软件产物只作为压缩包取回，不在宿主执行模型产物。

启动前回归为 345 passed、22 skipped、7 subtests passed；另有 VM 边界参数、来宾输出路径约束和截图 API 传输测试 20 passed（其中 17 项代理测试与前者重合）。准备过程中只出现 Unix socket 路径过长导致的启动前失败及 VM SSH 尚未就绪的握手重试，缩短目录后完成干净镜像构建，没有生成模型任务。

正式放行时间为北京时间 2026-09-19 15:24:51（UTC 07:24:51）。10/10 VM 通过预检，全部进入官方第一阶段并收到 deepseek-flash 响应，visual-grounding MCP 均为 connected。启动检查保存于 `startup-check.json`，后台调度 PID 见 `process.json`，总体日志为 `supervisor.log`；01–10 对应上文软件顺序，每目录保存 config、preflight、state、phase_N 输入/输出/结果。宿主未发布管理端口，启动时 199 个导出文本文件扫描无实际 API key。旧准备监督进程在任何 VM 启动前停止过一次，用于补充来宾输出文件名/读取大小限制及固定版本 uv 传输；9 份已完成的干净磁盘保留，记录在 `local/outputs/s100_prep_0919/preparation-restart.json`，未发生模型会话重跑。

截图检查在 Writer 生成 VM 内另行执行 `check_screenshot.py`，不参与正式任务设计：白底、左红方块与右蓝圆形，询问颜色、位置及中心坐标。DeepSeek OpenAI 接口调用成功，thinking enabled、effort high，返回 108 个 reasoning tokens；正文却是要求执行 Bash 的文本工具标记，没有直接回答视觉问题。官方 MCP 原样返回了该正文和坐标缩放说明，因此只能确认接口接受图片及思考参数，不能将本次检查记为视觉定位成功。证据在 `06/screenshot-smoke.json`、`06/screenshot-smoke-api.jsonl`；保留此异常，没有更改官方提示、解析或增加自动执行/重试逻辑。后台 snap 更新访问 api.snapcraft.io 被代理拒绝，已记录；启动检查本身通过，实际软件安装是否受影响以阶段日志为准。

2026-09-19 16:03（北京时间）进度：10 路仍运行且日志持续更新；Nuxeo 位于阶段 1，ERPNext/Redmine/VS Code/Writer/WordPress/QGIS/RStudio 位于阶段 2，Moodle/Rancher 位于阶段 3，尚无软件完整结束。按相对官方初始目录新增、同时具有 task.json 与 verifier.py 统计，候选题 37 道：Redmine 10、VS Code 10、Writer 5、Rancher 10、QGIS 1、RStudio 1。这只是文件产出，不代表通过实机验证；快照见批次 progress_20260919T0803.json。多数 seed_tasks.json 仍为官方示例清单，不能据此统计新题。

Moodle 阶段 2、VS Code 和 Writer 阶段 1 的 CLI 返回码为 1，结果 is_error=true，正文均为“Connection lost mid-response”；没有触发 10 小时超时，官方调用自然进入下一阶段，未人工重跑。连接中断的具体网络根因尚未定位。代理白名单还阻挡了 Rancher 下载域名、rubygems.org 及多处政府/科研公开数据站点，属于本地网络适配限制，应与框架错误分开记录；本次进度检查未修改网络或框架。各 VM 磁盘剩余约 154–170 GiB。Moodle 已有 1 次、VS Code 已有 2 次正式截图 MCP 调用，均返回正文及思考内容，正文为具体软件界面描述；这三次没有重现独立图片检查的文本工具调用异常，但尚未逐张人工核验视觉准确性。

2026-09-19 16:25（北京时间），按用户要求向 10 台 VM 部署外部 CLI 重试入口，版本仍为 Claude Code 2.1.229。结构化 `terminal_reason=api_error` 且状态为空（传输中断）、408/409/429 或 5xx 时，间隔 5 秒额外重试最多 3 次（合计最多 4 次）。用同一 session 的 `--resume` 继续原请求，保留已写文件、需求及 thinking/high 参数，不重新发起一批提题。重试占用原阶段 10 小时限额；普通任务/框架错误及认证失败不触发重试。耗尽后返回最后退出码，仍由官方逻辑推进后续阶段。本次不修改官方框架、网络规则、模型配置或种子。

部署没有中断正在执行的 CLI，只对之后启动的阶段生效；之前的失败阶段未补跑。10 台的版本、部署时间和当时阶段记录在批次 `retry-deployment.json`，源码保存在 `source/retry-update/`。各 VM 导出 `retry-policy.json`、`phase_N_attempt_K.jsonl` 和 `api-retries.jsonl`，K 从 0 开始。部署后已观察到 VS Code 阶段 3 通过此入口启动，尚无真实重试结果。模拟 CLI 子进程测试覆盖首次成功、瞬时失败恢复、3 次重试上限、会话/参数保留，以及官方超时清理子进程；全套回归 362 passed、22 skipped、7 subtests passed，见 `retry-regression-final.log`。该测试不调用真实模型。

核对官方提交 774476d752d748a69288f2ead97f75dd9df08ddb：Docker 默认 bridge，仅在 `resources.net=False` 且未启用 VNC 时设置 network=none；QEMU 默认用户态 NAT，`resources.net=False` 时设置 restrict=on。官方运行器没有本地代理的域名白名单，也没有相同的公网/私网目的地址过滤。当前拒绝部分正常下载和公开数据站点的是本实验额外添加的白名单，不能将这些拒绝归因于官方方法能力；本次只核查来源，未放宽网络策略。
