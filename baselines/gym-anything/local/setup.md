# 新机器配置

2026-09-19，宿主 `TSingSV`，目录 `/data1/zangyihe/EvaluationClaw/baselines/gym-anything`，代码保持在 `main`。迁移文件夹已从 `/data1/zangyihe/resume/` 移入 `local/outputs/migration_20260918/`；完整校验通过。恢复的是原始镜像与运行依赖，实验配置见 [迁移说明](migration.md)。

在 Gym 根目录激活基础设施工具：

```bash
source local/runtime/activate.sh
```

Python 3.12.13、Claude Code 2.1.229、uv 0.10.9 位于 `local/runtime/tools/`，虚拟环境为 `.venv`；177 项第三方依赖版本与迁移快照相同，依赖一致性检查通过。解释器链接和 editable 安装已重定位。该入口不加载 API 凭据、不启动代理、Docker daemon、VM 或模型，也不把旧模型命令包装器加到宿主 PATH。

原桌面镜像及外层 QEMU 工具镜像均已导入，镜像 ID、文件层和配置与迁移快照一致。公钥基础 VM 镜像位于 `local/runtime/qemu/secure-cache/base_ubuntu_gnome.qcow2`，SHA256 为 `399ae62720c46a6af2727796e33c9fa040d7760a09f4c4b1e1acffba1ef2e2ff`；没有依赖其它磁盘。管理私钥、API 文件权限为 0600，不纳入 Git，不放入来宾代码包。

官方源码已从 Git bundle 恢复至 `local/outputs/upstream` 的 `main`，固定提交 `774476d752d748a69288f2ead97f75dd9df08ddb`。五条需求与迁移快照一致。历史证据解压至 `local/outputs/migration_history`，不作为新机验证结果或新题输入。

主机为 AMD，192 个逻辑 CPU、约 1 TiB 内存；检查时约 934 GiB 可用，`/data1` 约 6.6 TiB 空闲，Docker 存储在 `/data3/docker`。Docker 29.1.3、cgroup v2，AMD 嵌套虚拟化开关为 1。当前用户没有宿主 `/dev/kvm` 的直接权限；非特权、只读、断网容器通过指定设备和实际 KVM GID 109，成功执行 KVM API 查询（版本 12）。没有创建 VM，也没有修改宿主设备权限或用户组。

外部脚本适配：QEMU 工具相对路径、恢复后的官方 Git 目录及 Claude/Python 路径、实际 KVM GID、AMD/Intel 模块选择。官方框架、需求注入与提题提示保持不变。旧两个批量入口仍禁用。

来宾出口代理仍执行域名白名单、固定已验证公网 IP、拒绝私网/元数据/本机网段的规则。激活脚本将 `GYM_VM_UPSTREAM_PROXY_PORT` 设为 17891，使用本用户已有的回环代理；未修改共享 7890 代理。已通过这个受限 Unix socket 代理实测 GitHub 200、DeepSeek 未认证 401，回环地址、元数据地址和非许可域名返回 403。该上游服务由主仓库 `benchmark-output/setup-20260917/` 管理，重启后需先恢复它。

不启动实际运行器的回归命令：

```bash
GYM_ANYTHING_RUN_EXECUTION_TESTS=0 .venv/bin/python -m pytest \
  tests local/test_generate.py local/test_seed_batch.py local/isolation/vm/test_proxy.py -q
```

结果为 342 passed、22 skipped、7 subtests passed，一项 Pillow 弃用警告。日志、依赖清单、镜像身份、KVM 查询、代理检查和配置状态都在 `local/outputs/setup_20260919/`。

用于单 VM 验证的 50 GiB 工作盘和新机验证证据位于 `local/outputs/vm_isolation_check/`。这块磁盘已经包含测试状态，不能作为正式实验的干净初始盘。基础镜像保持原样。

2026-09-19 经用户授权，按以下顺序完成实际验证，边界检查通过后才执行第二步：

```bash
source local/runtime/activate.sh
.venv/bin/python -u local/isolation/vm/verify.py
# 上一步确认验证成功、容器已退出后，移除这个临时容器以复用名称。
docker rm ga-vm-isolation-check
.venv/bin/python -u local/isolation/vm/verify.py --smoke
```

验证只使用一台 4 vCPU/8 GiB 来宾，外层限制 4 CPU/10 GiB、无额外 swap、512 PID、50 GiB 工作盘；不发布宿主端口、SSH 仅公钥。宿主文件/内核隔离、网络白名单与私网拒绝、资源限额检查通过。来宾 root 写入与宿主同名的路径也没有改变宿主文件。内部 Docker 29.1.3 和 AMD 嵌套 KVM 均实际启动成功；官方 Docker/QEMU 运行器完成命令执行和 1920×1080 截图。

deepseek-flash 经 `/anthropic` 和 Claude Code 2.1.229 在 VM 内完成一次工具操作，产物为 `{"hostname":"gym-isolation","marker":42}`；上限 3 轮、180 秒，实际 2 轮，返回 success。验证脚本 seed=42，远端接口无 seed，采样使用 CLI/provider 默认；没有 dataset，也未生成正式题目。

启动时出现过 SSH 尚未就绪的握手重试，以及来宾打印服务等待 90 秒后由 systemd 自行恢复。Docker 首张截图为黑底和鼠标；随后用相同原始镜像、运行器及资源配置单独检查，GNOME 桌面正常显示，在初次及额外等待 15、30 秒后的截图均正常。补查只增加进程/窗口观察和等待，没有修改官方代码、镜像或生成流程；原始截图与所有日志保留。一次额外 SSH 检查碰到 VM 已关机而失败，下一阶段重复检查成功。

验证及补查结束后，外层容器 exited、restart policy 为 no，可见 QEMU 进程为 0，相关管理端口无监听，代理 socket 已删除。导出文本中的实际 API key 检查无命中。结果在 `local/outputs/setup_20260919/live-result.json`；原阶段日志为 `live-boundary.log`、`live-smoke.log`，桌面补查脚本及截图也保存在同目录。迁移的基础镜像未被更改。

正式 100 题尚未启动。干净生成镜像、10 路 VM 调度、十款软件的下载与资源检查仍需完成；本次单 VM 验证不等于已经验证所有软件的完整构建。

2026-09-19 按用户要求配置后续种子构建：deepseek-flash 开启 thinking，Claude Code 的配置文件及 `--effort` 均为 high。入口、VM 代码包和工作副本统一使用 `local/deepseek-settings.json`，作用于官方 propose 全部四阶段。没有修改官方框架的构建、验证或失败处理逻辑。

在同一安全验证 VM 中，用不改写请求正文的来宾内观察代理检查实际 HTTPS 请求；仅保存模型参数、状态码、思考字符计数及工具块数量，不保存认证头或思考正文。最终检查主会话两次请求均为 `model=deepseek-flash`、`thinking={type:adaptive,display:omitted}`、`output_config.effort=high`、`max_tokens=32000`、流式响应，HTTP 200；首轮返回 369 个思考字符和一个工具调用，工具结果送回后得到 success。生成标题的辅助调用也使用 high，未显式发送 thinking，服务默认开启并返回了思考内容。Claude Code 的汇总 `thinking_tokens` 为 0，与实际流式思考事件不一致，不能用该计数判断思考是否开启。Anthropic 协议的 effort 与 OpenAI 协议 `reasoning_effort` 的对应关系遵循 DeepSeek 官方文档，文档快照保存在证据目录。

验证上限 3 轮、180 秒，实际 2 轮；Python、NumPy 与哈希种子为 42，API 无 seed，其余采样参数使用 CLI/provider 默认，无 dataset。模型通过 Bash 在来宾写出 `{"hostname":"gym-isolation","value":17575}`，正确计算 1 至 37 的平方和。过程出现启动期 SSH 握手重试、LiteLLM 价格表下载超时后使用自带副本，最终模型请求均成功。初次检查的 TLS 重试及观察脚本对 thinking 字段的严格断言失败保留在 `first_check/`，最终检查使用实际协议语义核验思考开启和 high。

证据及复现脚本在 `local/outputs/thinking_check/`：`host_check.py`、`guest_check.py`、`requests.json`、`result.json`。结束后验证 VM 已停止、无 QEMU 进程、无宿主管理端口监听，出口 socket 与来宾临时 API 文件已删除，基础镜像 SHA256 未变。文本产物检查无实际 API key。回归命令在上述基础上加入 `local/test_generation_api.py`，结果 345 passed、22 skipped、7 subtests passed，一项既有 Pillow 弃用警告。正式 100 题未启动。
