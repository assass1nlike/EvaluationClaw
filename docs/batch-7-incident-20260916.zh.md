# 7 路 agent 实验中止排查

运行目录：`benchmark-output/batch-7-20260915`。源码版本：`01d0ea7`。7 路初始目标共 230 题，全部为 agent；DeepSeek Flash 驱动 OpenClaw，开启研究、QC、Analyzer 和五项 LaaJ。启动于 2026-09-15 19:28 UTC，按用户要求于 2026-09-16 03:32 UTC 左右停止。

7 个框架进程和启动器已停止；按工作目录、父子关系、构建工具轨迹及容器网络确认归属后，停止残留宿主进程和本批容器。保留题目、镜像、检查点及日志。各路启动状态标记为 `stopped_by_user`；原框架检查点未改写。未干预上一批 15 路运行和其他项目的容器。

停止前整机内存约 418 GiB，停止后约 135 GiB。7 个主进程的 RSS 合计约 3.7 GiB；主要异常来自两个各占约 140–144 GiB 的验证进程，而非正常的 7 路模型调用。

| 需求 | 停止时阶段 | 已保存的初始逐题结果 | 其中运行错误 |
|---|---|---:|---:|
| 推理 | Analyzer 第一轮构题/修订 | 30 | 30 |
| 计算机科学 | 构题 | 0 | 0 |
| 多语言 | 主评测，最后一题尚未落盘 | 32 | 30 |
| 编排归因 | Analyzer 第三轮，前两轮已落盘 | 20 | 20 |
| 共享项目 | Analyzer 第一轮构题 | 20 | 19 |
| 故障定位 | 已进入 Analyzer | 14 | 14 |
| 最小权限 | Analyzer 第一轮构题 | 11 | 11 |

共 127 条初始逐题结果：123 条网关网络错误、1 条 OpenClaw 超时、3 条无运行错误。没有一路进入 LaaJ；这些数量不是构题目标完成量，也不能把错误计为模型答错。

## 内存与进程生命周期

两个异常进程 PID 为 `1238496` 和 `1268931`，执行同一个 `07-least-privilege/assets/task-builder/dimension_4__dimension_4_task_design_2/files/harness/tests/run_eval.py`，检查时已运行约 6.5 小时。一份父进程是已成为孤儿的 `verify/gradient.py`，另一份的 PPID 为 1。

该 Builder 的 `tool-round-075.json` 启动验证，内部给出 900 秒超时，但框架外层 `run_python` 在 60 秒后返回超时。`tool-round-076.json` 随后通过 `Popen(..., start_new_session=True)` 再启动一份验证。`tool-round-080.json` 只杀了第二份验证的父进程 `1268348`，未回收评估器子进程。

`tool-round-081.json` 保存了旧评估器代码片段：先执行 `sorted(glob.glob(os.path.join(base, "**", "*"), recursive=True))`，之后才检查文件类型和大小，且 `base` 包含宿主机 `/tmp`。这会在任何过滤之前收集完整递归路径列表。Builder 已把磁盘上的脚本改为有界遍历，但运行中的旧 Python 进程不会自动加载修改。停止后没有保留进程堆或栈，因此未进一步定位到实际分配内存的栈帧。

框架确定的问题：构建 Python 直接运行在宿主机；60 秒超时仅终止直接进程，没有覆盖后代、另起会话的后台服务和 Docker daemon 创建的容器，也没有对整个 Builder 作业施加内存上限。应以 Builder 作业为单位管理生命周期与资源，并提供受管理的后台运行能力；单纯缩短超时或减少并发不能解决这个问题。

## Docker 网关网络

检查时默认 `bridge` 为 `10.0.0.0/27`，已有 29 个容器端点，地址池耗尽。框架每道题创建内部网络，然后把模型网关额外连接到固定的 `bridge`。

使用框架原有网关启动函数、占位凭据进行一次不调用模型的诊断，复现：

```text
Error response from daemon: no available IPv4 addresses on this network's address pools: bridge
```

诊断容器和网络已由启动失败清理逻辑移除。此前一次 `none` 网络诊断不符合多网络连接前提，其报错不作为地址耗尽证据。

框架确定的问题：外网出口依赖宿主默认小地址池，实际网关链路未在大规模任务执行前验证；每题都独立重复同一失败。应使用容量明确且可配置的出口网络，在保持目标环境网络隔离的前提下做端到端预检，并将同类基础设施故障上报为批次阻塞。不要通过让目标直接接入外网来绕过隔离。

## 错误证据与 Analyzer

Docker 调用捕获了 stderr，但 `CalledProcessError` 的字符串只包含命令和退出码。失败的 `episode.json` 没保存该异常的 stderr，因此历史轨迹无法直接看到“地址耗尽”。应保留各阶段命令、退出码和脱敏后的 stdout/stderr。

主流程只检查 `run.results` 是否非空就启动 Analyzer；分析上下文又把 `error != null` 与低分共同标成 `failure_evidence.failed`。提示词禁止从基础设施错误推断弱点，但完成条件要求交付已验证的弱点 benchmark，否则继续给出 goal，缺少“没有有效证据、基础设施阻塞”的退出状态。

编排归因的三个 Analyzer 响应均承认没有有效主评测，却继续构造新题以获得首次有效测量。最小权限响应也承认没有有效测量，但提出了未经观察的能力假设。这不是用户需要的弱点迭代，应由结构化运行状态和迭代准入条件阻止，不能只靠提示词。

唯一超时题还有证据呈现问题：其 `result.json.raw_response` 为空，但保存的 `openclaw-output.txt` 包含最终回答、62 个 assistant turns、118 次工具调用及约 512 万 token 的累计用量（包含缓存读取）。Analyzer 将 actor 汇总中的 0 次工具调用误解为 target 没有执行，声称无目标输出。actor 汇总只覆盖 actor，不能用于描述 target。应把“超时但有保存的目标轨迹”和“启动前失败、目标未运行”明确区分，并直接指向相应轨迹。超时状态本身仍需保留，不能因为有最终文字就判作有效完成。

## 执行约束与验证

Builder Python 在独立 Docker 容器内执行，默认每个构题执行容器 8192 MiB 内存、512 个进程，禁止额外 swap。仅挂载本作业目录，临时目录与宿主隔离；后台服务可以跨工具调用保留。60 秒调用超时会回收整个 Python 容器，并返回部分输出及已生成文件。检查容器采用相同资源上限，可读取挂载的 Builder 作业文件；命令超时会停止容器。独立清理进程通过所属进程的管道关闭事件回收登记的容器和网络，覆盖所属进程被 SIGKILL 的情形。Docker 构建通过框架工具执行。

每个模型网关使用独立出口网络，目标仍位于其声明的隔离网络。构题前检查目标 harness 镜像、隔离容器到网关的连通性，以及网关到模型端点的 DNS/TCP/TLS 链路。预检不调用模型，不能验证模型名称、API key 有效性或推理服务质量。运行阶段的网关基础设施失败会阻止后续题目派发，已执行结果保存在 runner checkpoint，可在修复后恢复。未派发的题目不生成结果。

异常证据保存失败阶段、命令、退出码、stdout/stderr、耗时及目标输出；目标状态与 actor 证据分别记录。未确认的目标启动状态和工具调用次数保持未知。超时仍作为执行错误处理。Analyzer 的迭代策略不在本次修改范围内。

验证使用本地 `python:3.11-slim` 和 `evalclaw-model-gateway:latest` 镜像，构题运行时测试使用 128 MiB 内存限额，默认进程上限 512，限额检查用例为 32。没有恢复七路实验，也没有发起模型推理请求。

- `.venv/bin/python -m pytest -q --tb=short`：760 通过；5 个需显式启用的真实 Docker 测试跳过。
- `EVALCLAW_DOCKER_TESTS=1 .venv/bin/python -m pytest tests/test_builder_runtime.py tests/test_harness_output.py tests/test_harness_manifest.py tests/test_execution_contracts.py -q --tb=short`：62 通过，覆盖实际 OOM 限制、后台子进程超时回收、所属进程 SIGKILL 回收、文件隔离、检查容器资源访问、异常证据与中止派发。
- 网关预检：目标配置为 OpenClaw、`openai_compatible`、`deepseek-flash`、`https://api.deepseek.com`，凭据为占位字符串；单路及 4 路并发的隔离网络和上游 TLS 连通检查均通过。
