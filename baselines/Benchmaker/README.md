# BenchMaker

上游：https://github.com/ypw0102/BenchMaker ，固定提交 `8aaa2b6c644d52580a640c67f3ee024f217eb240`。原始源码位于 `upstream/`；本地 API 接口和运行入口位于当前目录，直接调用上游的属性生成、题目生成、解码和词汇统计流程。

已使用 `deepseek-flash` 完成 10 道中文代数题的生成与导出，每题保留 10 次作答记录。结果见 `runs/smoke/benchmark.json`，详细配置和验证记录见 `exps.md`。本次原始难度组合枚举的内存峰值约 15 GiB。

```bash
cd /data1/zangyihe/EvaluationClaw/baselines/Benchmaker
.venv/bin/python -u run.py --config configs/smoke.json --run smoke-2
```

每次使用新的 `--run` 名称，避免混入已有结果。输出为 `runs/<名称>/benchmark.json`；同目录的 `config.json` 保存模型和参数，`requests.jsonl` 保存实际提示、回答与 token 用量，`summary.txt` 保存上游统计，中间结果保留在原有目录结构中。首次验证的控制台日志为 `runs/smoke.log`。

中断后可加 `--resume` 继续同一任务，例如 `.venv/bin/python -u run.py --run smoke --resume`。入口清除上游留下的空题目占位文件，复用已保存的属性和题目，并延续 API 请求序号；本地随机数重新按任务 seed 初始化，续跑参数保存在 `resumes.jsonl`。上游仍会重新构建难度组合，因此续跑也有这部分计算开销。

任务 JSON 使用上游的能力描述和参数格式。`NumberPerAbility` 是每种能力的题量；上游解码按十档统计难度，运行时请使用不小于 10 的十的倍数。`DemoNum=8`、`DiverNum=5`、`OptionNum=4` 分别表示参考题数、候选题数和选项数。生成阶段仍执行每题 10 次作答校验和原有答案校准。

模型与密钥在 `.env` 中配置，格式见 `.env.example`。上游用于作答校验的 `4omini` 标识映射到 `BENCHMAKER_CALIBRATION_MODEL`，生成和内部裁判使用 `BENCHMAKER_MODEL`。接口将多份回答拆为独立请求，最多并发 2 个；温度沿用上游传入值，输出上限 16384 tokens。原始回答交给上游解析和筛选，请求日志保留包括截断在内的结束原因。当前 DeepSeek 配置关闭 thinking。

Python 和 NumPy 使用任务 seed，Python 哈希种子在进程启动时固定；API 请求 seed 为任务 seed 加请求序号，各次采样使用不同 seed。远程服务不保证确定性。这里的冒烟测试用于验证本机运行，不是论文结果复现或正式 baseline 对比。独立的忠实性、相关性及 embedding 评估属于上游可选后续步骤，本入口只执行生成及其自带统计。

重建环境：

```bash
mkdir -p .cache/tmp
UV_CACHE_DIR="$PWD/.cache/uv" uv venv --python /usr/bin/python3.10 .venv
UV_CACHE_DIR="$PWD/.cache/uv" TMPDIR="$PWD/.cache/tmp" \
  uv pip install --python .venv/bin/python -r requirements.lock
cp .env.example .env
# 填写 .env 中的 API 密钥和模型配置后运行。
```

虚拟环境、依赖缓存、NLTK 资源和所有运行产物均保存在本目录。
