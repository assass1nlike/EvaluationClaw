同一账号的多个框架进程可以共用一个 600 GiB 内存准入预算，无需 sudo：

```text
--memory-budget-gib 600
--memory-job-gib 1
--task-builder-workers 0
--runner-workers 0
```

不设置 `memory_cgroup` 时使用实测模式。所有参与运行共享跨进程锁及预算，统计已注册框架进程和子进程的 RSS，以及带 `evalclaw.memory-owner=<uid>` 标签的本机 Docker 容器 cgroup 内存（扣除可回收的 inactive_file 缓存）。同一账号创建的这些容器即使所属框架进程退出也继续计入；其它实验的未标记容器不会占用本预算。进程 RSS 可能重复计算共享页，因此统计偏保守。采样间隔最多一秒，在准入时刷新，记录在 `/tmp/evalclaw-memory-<uid>/<group>/usage.json`。

Builder、Runner、逐题 LaaJ、整体 LaaJ 环境探索和污染研究均在开始工作前申请预算。实测模式每个任务预留 `memory_job_gib`，上例为 1 GiB；不按容器声明的最大内存提前占满预算。调度检查实际用量与全部预留量的较大值，加上新任务预留不得超过预算减余量（默认 16 GiB）；整机 `MemAvailable` 也必须足以容纳新任务预留及余量。预算不足时只等待新任务准入，不暂停正在运行的工作。Builder/Runner 的 0 表示每个独立任务均可并发，LaaJ和污染研究也不设固定并发数。

这是准入控制，不是内核硬上限；已启动工作后续增长可以超过 600 GiB。Docker/BuildKit 服务自身的内存、构建中尚未成为普通容器的执行进程和镜像缓存不单独归属到实验，但会影响整机可用内存检查。已观察到的子进程脱离原进程后仍继续计入；两次采样之间出生并脱离的进程无法保证追踪。该模式要求本机 rootful Docker、默认 systemd cgroup v2 布局以及可读取的 `/proc` 和容器内存统计；采样失败时阻止新工作，不把未知使用量当作零。

若管理员提供了系统级 slice，可额外启用内核硬上限：

```text
--memory-budget-gib 600
--memory-cgroup /sys/fs/cgroup/evalclaw.slice
--task-builder-workers 0
--runner-workers 0
```

Python 配置对应 `memory_budget_gib=600`、`memory_cgroup="/sys/fs/cgroup/evalclaw.slice"`、`task_builder_max_workers=0`、`runner_max_workers=0`。未启用预算时，默认并发保持为 4。

所有参与预算的运行必须由同一账号启动在这个系统级 slice 内。需要本机 rootful Docker、systemd cgroup v2 和默认 Docker BuildKit；框架会在调用模型前检查条件，不满足就报错。Docker 命令固定使用本机默认 context。

管理员在仓库目录执行一次：

```bash
sudo install -m 644 scripts/systemd/evalclaw.slice /etc/systemd/system/evalclaw.slice
sudo systemctl daemon-reload
sudo systemctl start evalclaw.slice
```

然后让管理员将实验启动脚本作为系统服务启动，例如（账号和绝对路径按机器调整）：

```bash
sudo systemd-run --unit=evalclaw-batch-001 --slice=evalclaw.slice \
  --uid=zangyihe --gid=zangyihe --property=SupplementaryGroups=docker \
  --working-directory=/data1/zangyihe/EvaluationClaw \
  /bin/bash /absolute/path/to/batch-launcher.sh
```

启动脚本使用绝对路径加载代理、私密凭据和虚拟环境，并启动需要共享预算的各路框架调用。服务不依赖 SSH 连接。后续批次使用不同服务名、相同 slice。普通账号仅有 Docker 权限不足以创建这个硬上限；`systemd-run --user` 的进程组不能直接用作 rootful Docker 的 systemd slice。

600 GiB 是内核硬上限，覆盖框架及其子进程、Builder/目标/harness/judge/LaaJ 的本机容器，以及镜像构建的 `RUN` 执行进程。系统共享 Docker/BuildKit/containerd 服务自身的内存、镜像拉取及导出的服务端缓存、外部 VM/远程服务不在这个组内，因此这不是整台机器的总内存上限。镜像构建仍能使用本机已有镜像和缓存。

调度在跨进程文件锁下同时检查当前不可回收内存和活动任务预留量。默认预留 16 GiB 公共余量；每个独立任务至少预留 16 GiB，Builder 根据沙箱限制、Runner 根据题目声明的环境内存加 9 GiB 配套开销向上调整。可用 `--memory-headroom-gib` 和 `--memory-job-gib` 调整，前者在共享同一组的进程间必须一致。比如默认 8 GiB Builder 沙箱对应 17 GiB 预留，600 GiB 预算最多同时准入 34 个这样的构题任务，实际内存压力较大时更少。

预留只是并发调度的估计，不改变题目自身的资源限制，也不保证任务运行中永远不会超出估计。预算不足只让尚未开始的任务排队；已经开始的作答不因调度被暂停，其任务超时不包含排队时间。退出或崩溃的工作进程不继续占用预留量，遗留容器仍计入实际内存。

检测到共享 slice 的 OOM 后，活动作答保留现有证据并记为基础设施错误，不计入模型正确率；流水线停止推进。题目子容器自身限制触发的 OOM 不会把其它任务一并判为基础设施失败。若内核直接杀掉框架进程，就只能依赖已落盘的断点和服务日志恢复，不能保证生成最终报告。

两种模式的诊断目录均包含 `memory-budget.json`，排队和恢复准入也会写入运行日志。功能不迁移已有运行进程；启用前启动的实验不属于此预算。

管理员完成配置后，可在该 slice 内运行真实容器集成检查（需要本地 `alpine:3.21.5`）：

```bash
EVALCLAW_MEMORY_TEST_CGROUP=/sys/fs/cgroup/evalclaw.slice \
  .venv/bin/pytest -q tests/test_memory_budget.py
```
