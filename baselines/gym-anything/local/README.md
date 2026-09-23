种子构建入口为 `local/seed_batch.py --runtime docker`，使用普通 Docker 运行环境、宿主网络和现有 Docker daemon。下列为单题评估用法。

Gym-Anything 本机运行入口，使用官方 LibreOffice Writer 环境和任务。
源码位于 `..`，固定版本为 `774476d752d748a69288f2ead97f75dd9df08ddb`。

按用户评测需求生成任务的外部入口为 `generate.py`，用法和适配范围见 [需求输入说明](generation.md)。

在本目录执行：

```bash
PYTHONHASHSEED=42 ../.venv/bin/python -u run.py
```

默认任务 `contract_redline_generation` 要求比较两个合同版本，将修订痕迹保存到新的 DOCX 文件。模型是 `deepseek-flash`，API 地址为 `https://api.deepseek.com`；凭据读取本目录 `.env`，该文件不提交。

执行复用官方截图处理、历史窗口、鼠标键盘工具定义和动作解析，以及官方评测循环。DeepSeek 使用原生 function calling，历史也转换成原生工具消息，返回值交给官方动作解析器。模型只能通过 UI 操作；任务初始化、导出和评分使用原始官方脚本。评分包含 DOCX 修订标记检查及 DeepSeek 图片判断；输出文件不存在时直接返回 0 分。

默认配置：seed 42，40 步，temperature 0，top_p 1，最近 3 步截图历史，每次最多生成 4096 tokens，关闭 agent 请求的 thinking，API 超时 120 秒、最多重试 2 次。初始化后额外等待 180 秒，让 Writer 完成首次加载。官方评测循环将任务时限设为 86400 秒，以步数终止；Docker 使用 4 CPU、4 GiB 内存、1920×1080 桌面，缓存到软件初始化完成阶段。`--task` 可选择同一 Writer 环境的其他任务，`--steps` 设置步数上限。

每次运行记录在 `outputs/<UTC时间>/`：`config.json` 是实际配置，`model_calls.jsonl` 保存 agent 响应及 token 使用量，`agent/` 保存截图和动作，`episodes/` 保存官方轨迹及 `summary.json`，`documents/` 保存输入和输出文档。运行时 VNC 地址会写入日志，端口仅绑定本机。

官方评分中的图片判断使用原始默认参数：temperature 0.1、top_p 0.95、max_tokens 2048。

重新安装依赖和构建镜像：

```bash
uv venv --python 3.12 ../.venv
uv pip install --python ../.venv/bin/python -r requirements.lock
docker network create gym-anything-local
docker build -t gym-anything-local/ubuntu-gnome-highres:20260915 \
  -f ../src/gym_anything/presets/ubuntu_gnome_systemd_highres/Dockerfile \
  ../src/gym_anything/presets/ubuntu_gnome_systemd_highres
```

依赖锁定文件包含本机 SOCKS 代理所需的 `socksio`。镜像使用官方 Dockerfile；Ubuntu 软件包版本由构建时的软件源决定。

容器使用独立网络 `gym-anything-local`。Docker 运行器增加了 `GYM_ANYTHING_DOCKER_NETWORK` 配置，避免争用本机容量很小的默认 bridge；未设置时保留默认行为。

本机运行配置显式选择 `runc`。主机 `fs.inotify.max_user_instances` 已设为 8192，为多个容器提供足够的文件监听实例。该内核设置未写入系统持久化配置，主机重启后需检查；有管理员权限时可执行 `sudo sysctl -w fs.inotify.max_user_instances=8192`。

Docker 运行器支持初始化接口的 `timeout` 参数，并在缓存恢复时停止 VNC、清理旧 X11 状态，再启动 VNC。
