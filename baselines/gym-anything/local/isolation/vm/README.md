2026-09-18：单个生成 VM 的隔离与基础功能验证通过。正式 100 题没有启动，旧批量入口仍禁用。旧机器全部 VM 已退出，后续在新机器接续，见 [迁移说明](../../migration.md)。

模型执行器、Docker daemon、软件容器和嵌套 QEMU 都位于来宾内。外层 QEMU 放在非特权容器中：独立网络命名空间且 network=none，不发布端口，cap-drop=ALL、no-new-privileges、只读根文件系统；仅传入 /dev/kvm、只读 QEMU 文件/配置和一块可写虚拟磁盘。没有宿主 Docker socket、共享源码、宿主凭据或宿主块设备。源码和依赖通过 SSH 复制，输出按指定文件取回。

外层限制为 4 核 CPU、10 GiB 内存、无额外 swap、512 个进程/线程、64 MiB 临时目录、50 GiB 固定 raw 磁盘及同等文件大小硬限制。来宾分配 4 vCPU、8 GiB 内存；内部运行器测试分配 2 核、3 GiB。磁盘已预留空间。测试没有以耗尽宿主资源的方式验证限额。

SSH 仅接受公钥，管理连接通过 docker exec 的固定转接器进入外层网络命名空间，不在宿主发布 SSH/VNC 端口。外层网络阻断直连；来宾只通过 QEMU 的显式转发访问 Unix socket 代理。代理只允许列出的下载/模型域名及 80/443 端口，拒绝非公网地址、多播、本机地址和接口网段。每次解析后固定实际公网 IP，再通过已有宿主代理转发，避免再次按域名解析到内网。宿主通用代理没有直接暴露给来宾。

实际检查结果：

- 来宾无法看到宿主哨兵、块设备或 Docker socket。来宾 root 写入同名路径、修改来宾内核参数，均未改变宿主对应内容。
- 外层根文件系统和 cgroup 写入、原始套接字创建、超过 50 GiB 的文件扩展均被拒绝；cgroup 中实际 CPU/内存/swap/PID 限额与配置一致。
- 直接访问宿主网关及绕过代理的连接被阻断；经代理访问回环、私网、元数据地址和未许可域名被拒绝。DeepSeek 返回预期未认证 401，GitHub 返回 200；内部 Docker 容器也经受控代理取得 GitHub 200。
- 来宾 Docker 29.1.3 成功运行特权容器；嵌套 KVM 返回 API 12，并实际启动来宾。框架 Docker 和 QEMU 运行器均完成命令执行、1920×1080 桌面截图；嵌套 QEMU 使用来宾内独立生成的私钥，不复制宿主管理私钥。
- deepseek-flash 经 https://api.deepseek.com/anthropic 和 Claude Code 2.1.229 完成一次工具操作，产物包含来宾主机名 gym-isolation 和检查值 42。调用使用官方 run_claude，最大 3 轮、超时 180 秒，实际 2 轮；不生成 benchmark。仅提供本次必需 API 配置，临时凭据文件删除，导出响应做凭据替换。
- 验证结束，外层容器已退出，代理 socket 已删除；旧 10 个实验容器也已终止，告警端口 2267 无监听。

证据位于 ../../outputs/vm_isolation_check/：verification.json 汇总结果，container-inspect.json 保存实际外层配置，outer-guardrails.json 和 same-path-write-check.json 保存写入检查，docker-desktop.png 与 qemu.png 保存截图，model-response.json 保存脱敏响应，attempts 保留准备过程中失败的记录。完整回归 334 passed、22 skipped、7 subtests passed；其中代理规则测试 17 项。

测试使用 Python random seed=42、运行器 seed=42；远端模型无 seed，采样使用 CLI/provider 默认。本次没有 dataset 或正式任务。框架源自官方提交 774476d752d748a69288f2ead97f75dd9df08ddb，并复制当前已批准的 Docker、QEMU、公钥和需求适配文件。基础 QCOW2 SHA256 为 399ae62720c46a6af2727796e33c9fa040d7760a09f4c4b1e1acffba1ef2e2ff。桌面镜像 gym-anything-local/ubuntu-gnome-highres:20260915 的 ID 为 sha256:da0fb8bed9b56a6d5b4e9fdfa8dbc49a135f6e5602eeead4798dec09b0c6c3b1；外层只使用 gym-anything-local/seed-isolation:20260918 的工具文件，覆盖其启动入口，不启动其中的 Docker daemon。

在 gym-anything 根目录，首次验证使用：

```bash
source local/runtime/activate.sh
.venv/bin/python local/isolation/vm/payload.py
.venv/bin/python -u local/isolation/vm/verify.py
# 确认 ga-vm-isolation-check 已退出后，删除这个验证容器以复用名称。
docker rm ga-vm-isolation-check
.venv/bin/python -u local/isolation/vm/verify.py --smoke
```

payload.py 从保留的官方 Git 对象导出固定提交，将框架和依赖打包；不会复制旧题目产物、旧会话或宿主 .env。已准备的验证磁盘保留，可复查；临时传输 tar/ISO 已清理。边界检查应从新磁盘开始；已有磁盘可用 --docker-smoke 复查 Docker，不能将含测试文件/模型会话的磁盘直接当正式实验初始镜像。

准备过程中遇到的失败均有记录：128 个进程的上限使 QEMU 在线程创建时退出，已加 init 回收进程并调整硬上限至 512；来宾包安装因此中断，执行 dpkg 配置恢复。另有测试夹具遗漏 root 用户、截图路径不在产物目录、使用 network=none 导致 TigerVNC 无法解析容器自身主机名，以及基础镜像没有 curl；均通过修正测试输入处理。Docker 桌面测试调用框架已有的等待方法后截图，不改动框架实现或正式生成流程。首次立即截图失败也保留在记录中。

正式构建仍需：将 10 路调度接入这个边界，建立无测试状态的新初始镜像，配置嵌套软件 VM 的受控下载链路并核验各软件所需域名，落实各软件资源配置及总磁盘预算。当前每 VM 50 GiB，10 并行需预留 500 GiB；/data1 当前剩余约 353 GiB，另有本次已预留的 50 GiB，尚不足完整预留。不能把这些基础检查表述为已验证所有软件安装、完整官方四阶段构建或 100 题并行。
