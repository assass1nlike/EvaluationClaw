# BenchMaker

上游：https://github.com/ypw0102/BenchMaker ，基于提交 `8aaa2b6c644d52580a640c67f3ee024f217eb240`。代码位于 `upstream/`；本地 API 接口和运行入口位于当前目录，调用属性生成、题目生成、解码和词汇统计流程。难度组合使用等价的按排名读取实现，代码及测试见下文。

已使用 `deepseek-flash` 完成 10 道中文代数题的生成与导出，每题保留 10 次作答记录。结果见 `runs/smoke/benchmark.json`，详细配置和验证记录见 `exps.md`。本次原始难度组合枚举的内存峰值约 15 GiB。

```bash
cd /data1/zangyihe/EvaluationClaw/baselines/Benchmaker
.venv/bin/python -u run.py --config configs/smoke.json --run smoke-2
```

每次使用新的 `--run` 名称，避免混入已有结果。输出为 `runs/<名称>/benchmark.json`；同目录的 `config.json` 保存模型和参数，`requests.jsonl` 保存实际提示、回答与 token 用量，`summary.txt` 保存上游统计，中间结果保留在原有目录结构中。首次验证的控制台日志为 `runs/smoke.log`。

中断后可加 `--resume` 继续同一任务，例如 `.venv/bin/python -u run.py --run smoke --resume`。入口清除上游留下的空题目占位文件，复用已保存的属性和题目，并延续 API 请求序号；本地随机数重新按任务 seed 初始化，续跑参数保存在 `resumes.jsonl`。难度组合计数会在续跑时重新构建。

任务 JSON 使用上游的能力描述和参数格式。`NumberPerAbility` 是每种能力的题量；上游解码按十档统计难度，运行时请使用不小于 10 的十的倍数。`DemoNum=8`、`DiverNum=5`、`OptionNum=4` 分别表示参考题数、候选题数和选项数。生成阶段仍执行每题 10 次作答校验和原有答案校准。

模型与密钥在 `.env` 中配置，格式见 `.env.example`。上游用于作答校验的 `4omini` 标识映射到 `BENCHMAKER_CALIBRATION_MODEL`，生成和内部裁判使用 `BENCHMAKER_MODEL`。当前配置为 `deepseek-flash`、thinking enabled、输出上限 200000 tokens、每组请求并发上限 20、接口等待超时 3600 秒。thinking 强度使用服务默认值 high；DeepSeek 在 thinking 模式忽略温度，虽然代码仍传入上游的温度值。原始回答交给上游解析和筛选，请求日志保存 thinking 内容、结束原因和完整 API usage。

每个运行目录的 `usage.json` 自动累计已返回请求的输入、输出及总 token 数，包含重试和被淘汰候选。思考 token 包含在服务端报告的输出用量中；未返回 usage 的请求无法计入本地总数。

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

## 三组 50 题运行

`configs/knowledge.json`、`configs/data-analysis.json`、`configs/instruction-following.json` 分别对应知识、数据分析和指令遵循需求，每组只有一个能力，生成 50 题，选项数 4、DemoNum 8、DiverNum 5、seed 42。

三组由 `batch.py` 并行启动时，托管在独立的 `benchmaker-50` tmux 会话中，SSH 断联不影响运行。当前三组从空目录重新运行，采用难度组合的等价实现；上一轮记录位于 `runs/archive/batch-50-initial/`，不用于此次生成。每个进程的地址空间硬上限为 16 GiB，已由系统资源限制强制执行。退出状态保存到 `runs/batch-50/status.json`。每组使用独立目录 `runs/<名称>/`，日志为 `runs/<名称>.log`。接口并发上限 20 是每组请求的上限；原流程每次仅请求 5 个候选或 10 次作答，不会为了填满并发而修改生成顺序。

```bash
cat runs/batch-50/status.json
tail -f runs/knowledge.log
cat runs/knowledge/usage.json
```

原始需求、实际配置和实验记录见 `exps.md`。仅正常完成并通过题量与结构检查的运行会生成 `benchmark.json` 和 `summary.txt`。

## 难度组合的等价实现

`upstream/difficulty.py` 按属性前缀和整数难度总分统计组合数量。随机选中某个排名后，先定位总分，再从最后一个属性向前恢复取值，只构造这一份组合。它保留完整组合空间、整数分数相加、同分时的稳定排序、排序后半部分、十档切分的原浮点边界、属性输出顺序及原有 `random.choice` 调用。因此相同输入和随机状态产生相同的抽样结果；不删减属性、不近似抽样。

属性系数沿用上游解析后的 1–10 整数。若有 d 个属性，计数表最多约为 O(d²) 个状态，不随组合总数指数增长。题目生成文件只将原来的完整枚举代码替换为对该模块的调用；运行配置记录两个文件的 SHA-256。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=42 .venv/bin/python -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=42 .venv/bin/python tests/verify_difficulty.py
```

第一项对照原始枚举验证排序、分档、抽样及随机状态；第二项读取三组已保存的属性，在 256 MiB 地址空间上限下各抽样 1000 次，将时间和内存结果保存到 `runs/difficulty-check/results.json`。该验证不调用 LLM，不重启生成任务。
