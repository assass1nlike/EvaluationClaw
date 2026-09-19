# 在新机器继续 100 道种子题实验

源码在 `assass1nlike/EvaluationClaw` 的 `main` 分支，工作目录是 `baselines/gym-anything`。本次迁移文件夹为 `local/outputs/migration_20260918`，整体复制到新机器同一相对位置即可。文件夹含 API 凭据和 VM 管理私钥，权限保持 0700；不上传 GitHub。用户已同意为保留原始镜像超过 1 GB。

## 接续位置

正式实验目标为 **5 个需求 × 2 款软件 × 10 道种子题**，只做官方 propose 四阶段，不扩增。安全版本的正式 100 题尚未启动。已完成的是单台生成 VM 的边界检查、内部 Docker/嵌套 QEMU 的运行器检查，以及一次 DeepSeek 工具调用。

旧机器的 10 个实验容器已经终止，所有 QEMU VM 已退出，TCP 2267 无监听。旧机器不再做实验，也不启动验证 VM。旧 100 题批次 `seeds10_clean_20260918T104248Z` 不恢复；它的特权外层容器不能作为安全边界。两个旧批量入口 `local/seed_batch.py`、`local/isolation/run_batch.py` 继续保持禁用。

新机器需要先恢复文件和依赖，适配下述本机路径及网络，再完成安全批量调度。不能把历史验证报告复制成新机器的验证结果，也不能直接解除旧入口的禁用。

## 固定实验配置

| 需求 | 原文位置 | 软件与运行器 |
| --- | --- | --- |
| D1 | 主仓库 `user-inputs.txt` 第 1 行；`goal_1.txt` | ERPNext、Moodle：QEMU |
| D2 | 第 2 行；`goal_2.txt` | Redmine、Nuxeo Platform：QEMU |
| D3 | 第 3 行；`goal_3.txt` | Visual Studio Code、LibreOffice Writer：Docker |
| D4 | 第 4 行；`goal_4.txt` | WordPress、Rancher：QEMU |
| D6 | 第 6 行；`goal_5.txt` | QGIS、RStudio：Docker |

注意第五个实验需求对应 **D6**。迁移时已经逐字核对上述映射；前 15 行认定需求的完整文件、五个需求的原文与哈希在 `records/user-inputs.txt` 和 `records/requirements.json`。

- 官方固定提交：`774476d752d748a69288f2ead97f75dd9df08ddb`，仓库 `https://github.com/cmu-l3/gym-anything`。每软件从该提交的原始示例和新会话开始，不从主仓库中的历史生成任务继续。
- 模型 `deepseek-flash`，服务 `https://api.deepseek.com`；Claude Code 提题使用 `/anthropic`，截图 MCP 使用 OpenAI 兼容接口。Claude Code 固定 **2.1.229**，禁用自动更新。
- 每软件同一会话生成 10 道；最大同时 10 个软件；每阶段 36000 秒，共四阶段；任务类型 `enterprise`。四阶段通过官方流程恢复同一会话，不是每道题分别调用一次。
- Python/NumPy/hash seed 为 42，远端模型接口无 seed。采样参数保留 CLI/provider 默认，不额外设置交互轮数或费用上限。不要把 smoke test 的 3 轮、180 秒限制带入实验。
- 原批次实际配置为 `effortLevel=xhigh`、`CLAUDE_CODE_EFFORT_LEVEL=high`，完整最小配置在 `records/claude-settings.json`。不擅自统一这两个值；服务端如何解释尚未确认。
- 四阶段均通过 `local/generate.py` 加入原始需求和已批准的统一说明：任务情境、初始状态和成功判据应检验用户要评测的能力与限制；官方示例用于实现参考，不替代评测目标。不提供我们设计的题目、解法或评分规则。
- 保留已批准的数量 5→10、阶段超时、API/SDK、Docker timeout/VNC/runc/网络、QEMU 与公钥登录适配。官方阶段顺序、示例使用、失败处理、清理和评分保持原流程。不使用之前已撤销的 bare、strict MCP、自行终止后续阶段或自定义进程组清理。
- API、下载及机器资源问题可以处理；框架 bug 先报告讨论，不为跑通而修补。官方生成代理自己调试属于其原始流程。按实际产出与证据记录失败或缺题，不人工补齐 100。

## 文件包内容

`SHA256SUMS` 校验所有文件，`records/environment.json` 记录源机器版本，`records/images.json` 同时记录镜像解压后的哈希。`records/repository.json` 标明本次迁移对应的源码提交。

| 文件 | 用途 |
| --- | --- |
| `images/secure-base.qcow2.gz` | 已验证仅公钥 SSH 的完整基础 VM 镜像；没有 backing file 依赖 |
| `images/desktop.docker.tar.gz` | 原桌面 Docker 镜像 `gym-anything-local/ubuntu-gnome-highres:20260915` |
| `images/outer-tools.docker.tar.gz` | 原工具镜像 `gym-anything-local/seed-isolation:20260918`；仅供非特权外层启动 QEMU，必须覆盖旧默认入口 |
| `files/qemu-rootfs.tar.gz` | QEMU 6.2.0、动态库和固件，Linux x86_64 |
| `files/claude-2.1.229.tar.gz` | 实际使用的 Claude Code 二进制 |
| `files/uv-0.10.9.tar.gz` | 原依赖安装工具 |
| `files/python-3.12.13.tar.gz`、`files/venv.tar.gz` | 实际解释器与已安装依赖快照；安装路径需要重定位 |
| `files/upstream.bundle` | 官方固定提交及其 Git 历史，不含旧工作副本未提交的任务和配置 |
| `files/evidence.tar.gz` | VM/SSH 验证、工单截图、旧批次阶段记录、51 题导出与评估汇总；已做凭据脱敏，仅作历史证据 |
| `private/deepseek.env` | 本实验的 DeepSeek 模型、地址、API key |
| `private/qemu-key`、`private/qemu-key.pub` | 与基础 VM 匹配的管理密钥；私钥留在外层，不交给模型 |
| `records/requirements.*.lock` | 原锁定依赖及当前实际安装依赖，editable 路径已改为 `-e .` |

不携带旧软件 checkpoint、容器卷、50 GiB 验证工作盘、个人 Claude 会话、宿主 Git/SSH 凭据或通用代理配置。它们不是新一轮干净构建的输入，旧机器上的原始文件未删除。历史评估的完整截图/录像、全部失败批次和容器磁盘也仍在旧机器；本包保留用于接续的记录，不是整盘备份。

51 道旧题还在 HF dataset `assassinlike/b635`，固定提交 `31964d96304fb92dcbb3574c9280348bfa96c83d`，上传校验为 592 个文件、26,332,342 bytes。包内已带任务导出，不需要 HF token 恢复；本次没有携带 HF 凭据。这 51 题不作为本轮 100 题的种子输入。

## 新机器恢复顺序

先只检查硬件、解包和安装，不运行模型。新机器的架构、KVM 权限、嵌套虚拟化、Docker/cgroup 和可用资源尚未检查。二进制包适用于 Linux x86_64；源宿主为 Ubuntu 22.04.5、Docker 29.2.1、cgroup v2，已验证来宾 Docker 为 29.1.3。新机器不兼容时先说明差异，不能假定换系统后旧验证自动成立。

宿主还需 Git、Docker Engine、OpenSSH 客户端、`genisoimage`、`iproute2`、`procps`、`util-linux`、tar/gzip 和 CA 证书。包内 QEMU 不依赖宿主安装同版本 QEMU；宿主内核仍需提供可访问的 `/dev/kvm` 和嵌套虚拟化。不要在旧机器安装或更改这些系统配置。

在新机器检出主仓库 `main` 并复制迁移文件夹后，从 `baselines/gym-anything` 开始：

```bash
export GYM_ROOT="$PWD"
export MIGRATION_DIR="$GYM_ROOT/local/outputs/migration_20260918"
(cd "$MIGRATION_DIR" && sha256sum -c SHA256SUMS)
chmod 700 "$MIGRATION_DIR" "$MIGRATION_DIR/private"
chmod 600 "$MIGRATION_DIR/private/"*

# 下列目录应是新机器上的空目录；不要覆盖已有实验。
mkdir -p local/runtime/qemu/secure-cache local/runtime/qemu/ssh
chmod 700 local/runtime/qemu/ssh local/runtime/qemu/secure-cache
install -m 600 "$MIGRATION_DIR/private/deepseek.env" local/.env
install -m 600 "$MIGRATION_DIR/private/qemu-key" local/runtime/qemu/ssh/key
install -m 644 "$MIGRATION_DIR/private/qemu-key.pub" local/runtime/qemu/ssh/key.pub
gzip -dc "$MIGRATION_DIR/images/secure-base.qcow2.gz" > local/runtime/qemu/secure-cache/base_ubuntu_gnome.qcow2
tar -xzf "$MIGRATION_DIR/files/qemu-rootfs.tar.gz" -C local/runtime/qemu
mkdir -p local/outputs/isolation_assets
gzip -dc "$MIGRATION_DIR/images/desktop.docker.tar.gz" > local/outputs/isolation_assets/desktop.tar
docker load -i local/outputs/isolation_assets/desktop.tar
docker load -i "$MIGRATION_DIR/images/outer-tools.docker.tar.gz"
```

这些命令不启动容器或 VM。加载后逐项比较 `records/*-image.json` 中的镜像 ID；解压的 VM 镜像 SHA256 必须是 `399ae62720c46a6af2727796e33c9fa040d7760a09f4c4b1e1acffba1ef2e2ff`。不要把旧可密码登录的 `cache/base_ubuntu_gnome.qcow2` 换回来。

将历史证据解到独立归档目录，不覆盖新机器的 `vm_isolation_check/verification.json`：

```bash
mkdir -p local/outputs/migration_history
tar -xzf "$MIGRATION_DIR/files/evidence.tar.gz" -C local/outputs/migration_history
```

恢复官方 Git 对象到新的独立目录，保持 `main`：

```bash
git init -b main local/outputs/upstream
git -C local/outputs/upstream fetch "$MIGRATION_DIR/files/upstream.bundle" HEAD
git -C local/outputs/upstream checkout -B main FETCH_HEAD
git -C local/outputs/upstream rev-parse HEAD
```

最后一条必须输出官方固定提交。用这个目录替换 `payload.py` 对旧 ERPNext 工作副本的依赖。正式每软件工作副本也从这一提交创建。

依赖恢复有两条路径，优先使用包中的原始快照：

1. 将 Python 包解到独立的固定目录，Claude 二进制解到受控工具目录，`.venv` 解到当前 Gym 根目录。原虚拟环境指向 `/home/zangyihe/.local/share/uv/python/...`；需要重建 `.venv/bin/python*` 链接、`pyvenv.cfg`、入口脚本 shebang 和 editable 安装路径，然后以新解释器执行 `uv pip install --python .venv/bin/python --no-deps -e .`，不能带着旧绝对路径直接使用。不要在新宿主创建旧用户家目录来掩盖这些依赖。
2. 如需重建环境，安装 uv 0.10.9、Python 3.12.13，创建 `.venv`，从当前 Gym 根目录执行 `uv pip install --python .venv/bin/python -r "$MIGRATION_DIR/records/requirements.installed.lock"`。该文件与原锁相比仅多出 `hypothesis==6.112.1`、`sortedcontainers==2.4.0` 两个测试依赖；原锁另存。不能不告知就升级 Anthropic SDK 0.84.0 或其它依赖。

恢复后核对 `python --version`、`claude --version`、依赖版本和源码哈希，再跑不启动 VM 的测试。Claude 只恢复包内最小设置及全新的 onboarding 状态，不导入源机器个人配置、记忆和会话。

## 必须按新机器适配的地方

这些属于外部运行适配，不要求改变官方提题逻辑：

- `local/runtime/qemu/bin/qemu-img`、`qemu-system-x86_64` 中的 rootfs 绝对路径；`bin/python*` 的 shebang。模型执行用的 Python 包装器只能放进生成 VM，不在宿主运行模型命令。
- `local/isolation/vm/payload.py` 的官方 Git 对象目录与 Claude 路径；打包前创建输出目录。该验证脚本只打包了 Writer 示例，正式调度要携带对应软件的原始示例和全部已批准适配，尤其不能沿用旧 `seed_batch.prepare` 漏掉公钥适配文件的复制清单。
- `local/isolation/vm/smoke.py` 中的旧 Python 家目录链接；新 Python 包和虚拟环境在来宾内必须保持相互一致的路径。
- `local/isolation/vm/verify.py` 中写死的 KVM GID `109`，改为新宿主 `/dev/kvm` 的实际 GID；QEMU 子进程以无特权身份运行。来宾当前写死 `kvm_intel`，AMD 主机需相应处理并实测嵌套 KVM。
- `proxy.py` 的上游 `127.0.0.1:7890` 是旧机器服务，新机器未必有。若公网可直达，可改为代理完成同样的域名/IP 校验后直接连接已固定的公网 IP；保留域名白名单、私网/元数据/本机网段拒绝规则，不能将来宾改为不受限直连。不得复制整份旧机器通用代理配置。
- 新实验从空的软件缓存、新 HOME、新 Claude 会话和新临时目录开始。嵌套软件 VM 在生成 VM 内另建 SSH 密钥，不把外层管理私钥送进去。需求、环境与输出路径由受控复制传入和取回，不挂载宿主源码或输出目录给来宾。
- 保留正常 CLI/MCP 发现：软件工作副本提供官方截图 MCP 配置和 DeepSeek 模型映射，避免继承新机器其他模型服务；祖先 AGENTS/CLAUDE 指令按 `records/instructions/` 核对，不能默默改变构建条件。这份指令快照是迁移时的仓库状态，不能代替旧运行的提示日志。仓库开发统一在 `main`。

`local/README.md` 和旧实验记录中的宿主 Docker/网络/sysctl 命令是历史用法，不是新机安全启动方案。尤其不能在新宿主运行模型、特权生成器或为其写宿主内核参数。

## 安全批量构建还差什么

已验证的边界是：**宿主 → 非特权、network=none 的 QEMU 工具容器 → 生成 VM → 软件 Docker/嵌套 VM**。外层只传 `/dev/kvm`、只读工具/配置、受控 Unix 代理 socket，以及一块有容量上限的工作盘；不发布宿主端口。SSH 仅公钥，管理连接通过 `docker exec` 内部转接，模型没有宿主执行接口。私钥、宿主 Docker socket、主机文件系统和块设备不进来宾。

单 VM 已实测参数：4 vCPU/8 GiB 来宾，外层 4 CPU/10 GiB 内存、swap 0、512 PID/线程、64 MiB tmpfs、固定预分配 50 GiB raw 盘和同等文件大小上限；只读根文件系统、cap-drop ALL、no-new-privileges、默认 seccomp、日志 5 MiB × 2。内部特权容器只能作用于来宾内核。原报告为 334 passed、22 skipped、7 subtests passed；网络/文件/内核/资源边界和基本运行器链路通过，不代表所有软件完整构建均通过。

接下来在新机器依次完成：

1. 检查新宿主资源与嵌套 KVM，迁移上述路径和代理适配，在新磁盘上重做单 VM 边界与运行器/API 验证；结束关闭 VM。先与用户确认实际启动测试。
2. 建立没有测试题目、模型会话或临时 API 配置的干净生成基础镜像，接入最多 10 路独立 VM 调度；保持官方四阶段执行和失败行为。
3. 检查十款软件的下载域名、安装链路及各自 CPU/内存/磁盘需要。当前白名单仅覆盖 Ubuntu/Debian/GitHub/Docker/PyPI/DeepSeek，不能假定十款软件够用，也不能自动放开所有域名。
4. 预留批量资源并保存实际配置。照搬单 VM 上限时 10 路需要 500 GiB 工作盘、100 GiB 外层内存和合计 40 CPU 配额，另留宿主、基础镜像、Docker 存储、输出的余量；这是待核验的初始预算，不是已验证各软件足够。不因资源不足静默降并发或挤占其它任务。
5. 用户确认接续后从全新批次开始 100 题。保留配置、依赖、原文、代码/镜像哈希、各阶段输入与输出、错误和退出状态。官方整体退出 0 不等于每题真实构建验证成功。

本轮迁移只导出文件、记录状态和同步代码，没有启动 VM、运行模型或继续构建题目。
