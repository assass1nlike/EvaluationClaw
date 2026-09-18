本目录提供 Ubuntu 22.04 的原生 QEMU 6.2.0，二进制和依赖位于 rootfs，bin 中的脚本指定动态库、模块和固件路径。宿主用户通过 kvm 组访问 /dev/kvm，无需宿主安装 QEMU 软件包。

Linux QEMU 的 SSH 使用独立公钥，客户端不回退密码；来宾 SSH 禁止密码、交互式认证及 root 登录。QEMU 的 SSH、VNC 和其它管理转发端口仅监听 127.0.0.1。此为运行基础设施适配，不改变提题、构建或评分流程。Windows SSH 凭据尚未迁移，本轮软件使用 Linux。

私钥位于 ssh/key（目录 0700、文件 0600，Git 忽略），使用 `GYM_ANYTHING_QEMU_SSH_KEY` 指定。来宾只收到公钥。桌面账户密码保留，不能用于 SSH 登录。

安全镜像使用独立的 secure-cache；cache 中的旧基础镜像及旧任务快照保留原样，不能作为加固后的镜像恢复。现有实验启动入口继续禁用，旧批次工作副本不包含本次修改，不能恢复运行。

在 gym-anything 根目录运行 `.venv/bin/python local/runtime/qemu/secure_image.py` 仅准备公钥配置、写时复制磁盘和 cloud-init ISO，不启动 VM。经用户同意后，执行：

```bash
sg kvm -c '.venv/bin/python -u local/runtime/qemu/secure_image.py --run'
```

该命令先以 2 核、3 GiB 内存、无网卡的临时 VM 配置副本，再用官方运行器启动验证 VM；验证期间设置 `resources.net=false`，QEMU restrict=on，管理端口仅监听回环地址。两次启动均不运行模型、不挂载宿主目录；结束或失败时关闭相应 VM。检查公钥登录、拒绝密码、服务端认证列表、文件传输、VNC 截图及实际监听地址，通过后写 secure-cache/READY 和 verification.json。已有加固镜像可用 `--verify` 单独复查。READY 仅代表这些 SSH 检查通过，不代表实验隔离已经完成。

后续运行器需要设置：

```bash
export PATH="$PWD/local/runtime/qemu/bin:$PATH"
export GYM_ANYTHING_QEMU_CACHE="$PWD/local/runtime/qemu/secure-cache"
export GYM_ANYTHING_QEMU_SSH_KEY="$PWD/local/runtime/qemu/ssh/key"
```

2026-09-18 验证通过：SSH 仅提供 publickey，拒绝旧密码；公钥登录、SFTP/SCP 往返、1920×1080 桌面截图均正常。SSH 2250 和 VNC 6063 实际仅监听 127.0.0.1，测试结束后临时 VM 已关闭，两个端口及告警端口 2267 均无监听。镜像完整性检查通过，测试套件 317 passed、22 skipped、7 subtests passed。没有修改宿主 SSH 服务。2026-09-16 的原始环境检查日志位于 local/outputs/qemu_setup，仅证明当时旧基础镜像的功能可用。
