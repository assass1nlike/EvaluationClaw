单 VM 隔离构建入口为本目录 `run_batch.py`。

模型执行器、Docker daemon、软件容器和嵌套 QEMU 都位于来宾内。外层 QEMU 放在非特权容器中：独立网络命名空间且 network=none，不发布端口，cap-drop=ALL、no-new-privileges、只读根文件系统；仅传入 /dev/kvm、只读 QEMU 文件/配置和一块可写虚拟磁盘。没有宿主 Docker socket、共享源码、宿主凭据或宿主块设备。源码和依赖通过 SSH 复制，输出按指定文件取回。

外层限制为 4 核 CPU、10 GiB 内存、无额外 swap、512 个进程/线程、64 MiB 临时目录、50 GiB 固定 raw 磁盘及同等文件大小硬限制。来宾分配 4 vCPU、8 GiB 内存；内部运行器测试分配 2 核、3 GiB。磁盘已预留空间。测试没有以耗尽宿主资源的方式验证限额。

SSH 仅接受公钥，管理连接通过 docker exec 的固定转接器进入外层网络命名空间，不在宿主发布 SSH/VNC 端口。外层网络阻断直连；来宾只通过 QEMU 的显式转发访问 Unix socket 代理。代理只允许列出的下载/模型域名及 80/443 端口，拒绝非公网地址、多播、本机地址和接口网段。每次解析后固定实际公网 IP，再通过已有宿主代理转发，避免再次按域名解析到内网。宿主通用代理没有直接暴露给来宾。

在 gym-anything 根目录，首次验证使用：

```bash
source local/runtime/activate.sh
.venv/bin/python local/isolation/vm/payload.py
.venv/bin/python -u local/isolation/vm/verify.py
# 确认 ga-vm-isolation-check 已退出后，删除这个验证容器以复用名称。
docker rm ga-vm-isolation-check
.venv/bin/python -u local/isolation/vm/verify.py --smoke
```

payload.py 从保留的官方 Git 对象导出固定提交，将框架和依赖打包；不会复制旧题目产物、旧会话或宿主 .env。边界检查应从新磁盘开始；已有磁盘可用 --docker-smoke 复查 Docker，不能将含测试文件/模型会话的磁盘直接当正式实验初始镜像。

正式批量构建使用 10 台独立生成 VM，每台 8 vCPU、24 GiB 内存、200 GiB 预分配磁盘，外层内存上限 28 GiB。`build_clean.py` 从原安全镜像构建不含模型会话的生成初始镜像；`run_batch.py` 为各软件复制磁盘、预检并调用官方四阶段。嵌套 VM 密钥由各生成 VM 自行创建，截图 MCP 通过外部入口显式配置 thinking/high。所有阶段日志、退出状态和脱敏 API 元数据保存在批次目录。软件实际安装与生成质量以各软件日志为准，基础链路验证不代表完整构建成功。
