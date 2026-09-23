本目录提供 Ubuntu 22.04 的原生 QEMU 6.2.0，二进制和依赖位于 rootfs，bin 中的脚本指定动态库、模块和固件路径。宿主用户通过 kvm 组访问 /dev/kvm，无需宿主安装 QEMU 软件包。

Linux QEMU 的 SSH 使用独立公钥，客户端不回退密码；来宾 SSH 禁止密码、交互式认证及 root 登录。SSH、VNC 和其它管理转发端口使用官方绑定方式，网络使用官方用户态 NAT，由 resources.net 控制是否启用 restrict=on。此为运行基础设施适配，不改变提题、构建或评分流程。

私钥位于 ssh/key（目录 0700、文件 0600，Git 忽略），使用 `GYM_ANYTHING_QEMU_SSH_KEY` 指定。来宾只收到公钥。桌面账户密码保留，不能用于 SSH 登录。

公钥镜像位于 secure-cache，旧任务快照不能作为干净重跑的初始状态。批量入口可使用 Docker 的设备映射访问 KVM。

在 gym-anything 根目录运行 `.venv/bin/python local/runtime/qemu/secure_image.py` 仅准备公钥配置、写时复制磁盘和 cloud-init ISO，不启动 VM。经用户同意后，执行：

```bash
sg kvm -c '.venv/bin/python -u local/runtime/qemu/secure_image.py --run'
```

该命令先以 2 核、3 GiB 内存、无网卡的临时 VM 配置副本，再用官方运行器启动验证 VM；验证期间设置 `resources.net=false`、QEMU restrict=on，管理端口使用官方绑定方式。两次启动均不运行模型、不挂载宿主目录；结束或失败时关闭相应 VM。检查公钥登录、拒绝密码、服务端认证列表、文件传输、VNC 截图及实际监听地址，通过后写 secure-cache/READY 和 verification.json。已有加固镜像可用 `--verify` 单独复查。

后续运行器需要设置：

```bash
export PATH="$PWD/local/runtime/qemu/bin:$PATH"
export GYM_ANYTHING_QEMU_CACHE="$PWD/local/runtime/qemu/secure-cache"
export GYM_ANYTHING_QEMU_SSH_KEY="$PWD/local/runtime/qemu/ssh/key"
```
