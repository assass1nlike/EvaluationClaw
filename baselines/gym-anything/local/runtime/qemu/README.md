本目录提供 Ubuntu 22.04 的原生 QEMU 6.2.0（6.2+dfsg-2ubuntu6.31），用于 Gym-Anything 的虚拟机环境。二进制和依赖从单独的 Ubuntu 容器安装、导出，放在 rootfs；bin 中的启动脚本指定动态库、模块和固件路径。官方运行器代码未修改。

宿主用户 `zangyihe` 已加入 `kvm` 组（GID 109），使进程可以读写 `/dev/kvm`；无需宿主安装 QEMU 软件包。现有会话需要用 `sg kvm -c '<命令>'` 启动生成或验证进程，新登录会话自动继承该组。bin 中的 python/python3 入口在 `GYM_ANYTHING_RUNNER=qemu` 时自动使用该组，并把六个软件的虚拟机工作目录分别放到 `local/q/1` 至 `local/q/6`，避免 Unix socket 路径过长。1–6 分别对应 ERPNext、Moodle、Redmine、Nuxeo Platform、WordPress、Rancher。Docker 进程直接使用共享虚拟环境。复现命令（在 gym-anything 根目录执行）：

```bash
export PATH="$PWD/local/runtime/qemu/bin:$PATH"
export GYM_ANYTHING_QEMU_CACHE="$PWD/local/runtime/qemu/cache"
export GYM_ANYTHING_QEMU_WORK_DIR="$PWD/local/q/1"
export GYM_ANYTHING_RUNNER=qemu
sg kvm -c '.venv/bin/python -u local/runtime/qemu/build_base.py'
local/runtime/qemu/bin/qemu-img check local/runtime/qemu/cache/base_ubuntu_gnome.qcow2
sg kvm -c '.venv/bin/python -u local/runtime/qemu/smoke.py'
sha256sum -c local/outputs/qemu_setup/base.sha256
```

运行进程需要把本目录的绝对 `bin` 路径加入 PATH，并设置 `GYM_ANYTHING_QEMU_CACHE` 为本目录的绝对 `cache` 路径。每个并行工作副本分别设置 `GYM_ANYTHING_QEMU_WORK_DIR`，共享只读基础镜像，使用独立写时复制磁盘。基础镜像由官方代码和官方 cloud-init 配置生成。

安装与构建日志在 `local/outputs/qemu_setup/`。`cache/READY` 仅在基础镜像和实际启动验证完成后创建。

2026-09-16 实测：官方基础镜像构建1195秒，文件6956777472字节，qemu-img完整性检查无错误；官方QemuNativeRunner以KVM启动后，SSH命令、X11、1920×1080 VNC桌面及截图均正常。截图与检查日志保存于 `local/outputs/qemu_setup/`，基础镜像 SHA256 为 `a6caf767e214781120b53d8477bb5f59ea91fc65d74e92a4c09e87f5e090c939`，也保存在其中 `base.sha256`。此验证仅覆盖共享基础系统，具体软件的安装和任务验证由各自官方提题agent执行。
