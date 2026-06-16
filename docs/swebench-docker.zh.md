# SWE-bench Docker 后端

EvaluationClaw 的 SWE-bench 支持采用 Docker-first 设计。真实 SWE-bench
实例依赖历史仓库、历史依赖、指定测试列表和隔离执行环境，因此不应复用轻量
`code_sandbox` 作为主路径，而应调用官方 SWE-bench harness。

## 前置条件

- Windows 上推荐使用 Docker Desktop + WSL2 backend。
- Docker CLI 和 Docker daemon 必须可用：`docker run --rm hello-world` 应成功。
- Windows Python 环境安装 EvaluationClaw 的 SWE-bench 可选依赖：

```powershell
python -m pip install -e ".[swebench]" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

官方 `swebench` harness 依赖 Unix-only API，例如 Python 的 `resource` 模块，因此
在 Windows Python 中不能直接运行。Windows 上应在 WSL Python 环境里运行官方
harness：

```powershell
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/d/localwork/EvaluationClaw && python3 -m venv .venv-swebench-wsl && . .venv-swebench-wsl/bin/activate && python -m pip install swebench datasets -i https://pypi.tuna.tsinghua.edu.cn/simple"
```

## Windows + WSL + 代理

如果 WSL 不能直连 HuggingFace、Docker Hub、Anaconda 或 PyPI，可以把 Windows
本地代理转发给 WSL 和 Docker build 使用。例如本机代理在 `127.0.0.1:7890`：

```powershell
python scripts/tcp_forward.py --listen-host 0.0.0.0 --listen-port 7891 --target-host 127.0.0.1 --target-port 7890
```

如果希望后台运行：

```powershell
Start-Process -FilePath python -ArgumentList @("scripts/tcp_forward.py", "--listen-host", "0.0.0.0", "--listen-port", "7891", "--target-host", "127.0.0.1", "--target-port", "7890") -WindowStyle Hidden
```

在 WSL 中通常使用 Windows WSL 网关地址访问该转发端口，例如：

```bash
curl -I -x http://172.18.96.1:7891 https://huggingface.co
```

如果 Docker daemon 拉 Docker Hub 镜像超时，需要在 Docker Desktop 的代理设置中
配置可由 Docker Desktop Linux engine 访问的代理地址，例如
`http://host.docker.internal:7891`。配置后重启 Docker Desktop，并用以下命令验证：

```powershell
docker pull ubuntu:22.04
```

SWE-bench 的 env image 构建阶段会在 Dockerfile `RUN` 中调用 conda/pip。仅设置
daemon 代理通常只能解决拉 base image，不能保证 conda 读到代理。base image 已经构建
出来后，可以让 EvaluationClaw 给 SWE-bench base image 注入 proxy 环境变量和
`/root/.condarc`：

```powershell
evalclaw swebench-prepare-proxy-base --proxy-url http://host.docker.internal:7891
```

## 运行官方 gold patch smoke test

Windows + WSL 推荐命令如下：

```powershell
evalclaw swebench-run `
  --use-wsl `
  --wsl-distro Ubuntu-24.04 `
  --wsl-http-proxy http://172.18.96.1:7891 `
  --namespace none `
  --dataset-name princeton-nlp/SWE-bench_Lite `
  --split test `
  --predictions-path gold `
  --instance-id pallets__flask-4045 `
  --max-workers 1 `
  --run-id evalclaw_smoke `
  --output-dir benchmark-output/swebench `
  --timeout 900
```

`--predictions-path gold` 交给官方 harness 使用 gold patches，用于验证本机
Docker/SWE-bench 环境本身是否能跑通。

如果没有预构建镜像，且需要本地强制构建，应同时传 `--force-rebuild` 和
`--namespace none`。官方 harness 不允许 force rebuild 与默认 namespace 同时使用。

## 运行模型预测 patch

先写官方 SWE-bench prediction JSONL：

```json
{"instance_id":"pallets__flask-4045","model_name_or_path":"my-model","model_patch":"diff --git ..."}
```

然后运行：

```powershell
evalclaw swebench-run `
  --use-wsl `
  --wsl-distro Ubuntu-24.04 `
  --wsl-http-proxy http://172.18.96.1:7891 `
  --namespace none `
  --dataset-name princeton-nlp/SWE-bench_Lite `
  --split test `
  --predictions-path predictions.jsonl `
  --max-workers 4 `
  --run-id my_model_swebench_lite
```

## 当前实现位置

- Docker preflight: `evalclaw/execution/docker.py`
- SWE-bench harness wrapper: `evalclaw/execution/swebench.py`
- CLI commands:
  - `evalclaw swebench-run`
  - `evalclaw swebench-prepare-proxy-base`
- 本地 TCP 转发工具: `scripts/tcp_forward.py`

## 注意事项

- EvaluationClaw 不复制官方 SWE-bench harness 的逻辑；它负责 preflight、prediction
  文件处理、命令构造、WSL 启动、Docker 可达性检查和结果收集。
- 完整可复现评测应优先使用 Docker。非 Docker 本地运行只能作为 debug fallback，因为
  Python 版本、依赖上界、warning 策略和系统库都可能导致历史仓库测试失真。
- SWE-bench 的 `FAIL_TO_PASS` / `PASS_TO_PASS` 字段在不同加载路径下可能是 list，
  也可能是 JSON 字符串。EvaluationClaw backend 已提供规范化 helper。
- 官方 harness 可能在单题有 errors 时仍以进程码 0 结束；实际评测状态应以生成的
  report JSON 和 stdout summary 为准。

## 与 EvaluationClaw 主流程的关系

普通规划、生成、QC 和 human review 阶段不会安装或检查 SWE-bench 环境。只有最终准备进入 runner，
并且 QC 通过的待运行题目中包含 SWE-bench item 时，EvaluationClaw 才会执行 SWE-bench preflight。

SWE-bench item 使用 `metadata.swebench` 标记，常用字段如下：

```json
{
  "swebench": {
    "dataset_name": "princeton-nlp/SWE-bench_Lite",
    "split": "test",
    "instance_id": "pallets__flask-4045",
    "use_wsl": true,
    "wsl_distro": "Ubuntu-24.04",
    "wsl_http_proxy": "http://172.18.96.1:7891",
    "namespace": "none",
    "timeout": 900
  }
}
```

主流程的行为是：

1. runner 发现最终 accepted items 中有 SWE-bench item。
2. 执行 preflight，检查 Docker daemon 和官方 `swebench` harness 是否可用。
3. 如果环境齐全，目标模型会先生成 unified diff patch，EvaluationClaw 写入官方 prediction JSONL，
   然后调用 SWE-bench harness 运行该实例。
4. 如果环境缺失，框架会明确报错并给出安装/配置命令；交互模式下，用户可以手动配置后按回车重试，
   也可以输入 `skip` 跳过本次 target execution，或输入 `abort` 中止。

这意味着 SWE-bench 不会成为 EvaluationClaw 的全局必装依赖；只有用户需求和最终题目方案真的选用了
SWE-bench，才会进入 Docker/WSL/harness 相关路径。
