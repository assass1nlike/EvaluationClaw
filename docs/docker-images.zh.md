容器启动前可通过统一镜像获取流程使用 Docker Hub 加速源，不需要修改系统 Docker daemon：

```bash
export EVALCLAW_DOCKER_MIRRORS=docker.m.daocloud.io,docker.1panel.live,hub.rat.dev
export EVALCLAW_CRANE_EXECUTABLE=/absolute/path/to/crane
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY="$HTTPS_PROXY"
export EVALCLAW_IMAGE_ROUTES='{"docker.1panel.live":"direct"}'
```

本机 `benchmark-output/setup-20260917/activate.sh` 已配置上述镜像源和现有代理端口，后续启动实验前加载即可。正在运行的源码快照和进程环境不自动更新。

镜像构建默认允许3600秒。Builder的 `build_image.timeout_s` 可指定至7200秒；未指定时使用默认值。原生环境和外部harness准备任务镜像时也默认允许3600秒。该时长独立于目标作答预算和镜像下载超时。

普通构建失败会把错误返回 Builder，由它修改后重新构建。尚未成功构建的本地镜像不能用于镜像检查或交互探索，也不会按同名远程镜像下载。构建超时、进程被信号终止、Docker 无法执行或构建失败后 daemon 不可达时，流水线以构建执行错误停止。构建日志保存在构建目录下的 `logs/` 中，每次记录 stdout、stderr、退出码和超时状态；异常信息包含日志路径。

框架优先复用本地镜像；缺失时按所列顺序下载，成功后导入 Docker。同一镜像及平台的并发请求合并为一次获取。普通 Docker Hub 引用及已配置加速源的前缀表示同一镜像，都使用完整的换源顺序；未配置为加速源的独立 registry 保持原地址。带 digest 的引用保留所指定的 digest 下载，并用独立本地缓存标签承载，不替换成可变的 latest。

下载默认沿用宿主机代理，不依赖 Docker daemon 的代理。`EVALCLAW_IMAGE_ROUTES` 按 registry 主机名选择 `direct`（这次下载及其认证、重定向均直连）或 `environment`（沿用现有代理环境）。未列出的主机沿用环境；该设置不改变模型、搜索或构建中软件包下载的网络。本机1panel仅接受大陆出口，因此设为直连。

配置镜像源后，框架创建容器时使用 `--pull never`，不会在镜像缺失时隐式回退直连 Docker Hub。所有源失败、下载超时或导入失败会记录为基础设施错误，环境预检不会因此要求 Builder 改题。`pull_image=false` 且本地镜像缺失时同样报错，不擅自下载。

此策略覆盖 Builder 沙箱、镜像检查/交互探索、目标任务、actor 工具和评分沙箱，以及框架的两种镜像构建入口。构建前使用Docker官方语法解析器读取最终阶段依赖的 `FROM`、外部 `COPY --from`、`RUN --mount=from` 和声明的构建前端，处理阶段引用、全局ARG及平台。按统一策略准备依赖后，通过BuildKit源映射使用按镜像ID固定的本地标签，保留原Dockerfile。每次构建的 `image-sources.json` 和 `source-policy.json` 记录依赖及映射。不修改 Docker daemon 设置，也不把安装软件包的网络请求当成镜像下载。

依赖准备支持普通ARG引用及 `${VAR:-default}`、`${VAR:+value}` 等基本展开；其它镜像表达式会明确要求Builder提供具体引用。同一构建中，同一镜像引用不能同时对应不同平台，应分别使用不同引用。构建依赖准备失败会保存原因并停止；Dockerfile解析或引用错误返回Builder修复。

未设置 `EVALCLAW_DOCKER_MIRRORS` 时沿用 Docker 的原有拉取行为。加速源或代理本身故障仍可能使镜像不可获取；此时流水线会报告阻塞，而不会通过改变题目来掩盖故障。
