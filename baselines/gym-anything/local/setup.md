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

用于单 VM 验证的 50 GiB 预分配工作盘、cloud-init ISO 和 `framework.tar` 已准备在 `local/outputs/vm_isolation_check/`。代码包不含 API key、管理私钥、历史模型会话或历史生成题目。没有复制旧 `verification.json` 或 READY 标记。

实际启动验证待用户确认。计划按以下顺序验证，只有边界检查通过才执行第二步：

```bash
source local/runtime/activate.sh
.venv/bin/python -u local/isolation/vm/verify.py
# 上一步确认验证成功、容器已退出后，移除这个临时容器以复用名称。
docker rm ga-vm-isolation-check
.venv/bin/python -u local/isolation/vm/verify.py --smoke
```

该验证只使用一台 4 vCPU/8 GiB 来宾，外层限制 4 CPU/10 GiB、无额外 swap、512 PID、50 GiB 工作盘；不发布宿主端口、SSH 仅公钥、模型只在 VM 内执行。先检查隔离与内部 Docker/嵌套 QEMU，再用 deepseek-flash 做最多 3 轮、180 秒的工具链路检查；不生成正式题目，结束停止 VM。验证脚本 seed=42，远端接口无 seed。

正式 100 题尚未启动。新机真实验证、干净生成镜像、10 路 VM 调度、十款软件的下载与资源检查仍需依次完成；本次资源检查不等于已经验证所有软件的完整构建。
