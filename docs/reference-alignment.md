# 人工 benchmark 的 LaaJ 格式适配

入口是 `scripts/convert_reference_benchmarks.py`。转换不调用 LLM，不改题目、答案或评分规则。输出的 `suite.json` 使用与主框架及生成式 baselines 相同的任务表示，直接交给共享 LaaJ。`construction.json` 只提供题目，不包含构题过程。没有导入实际作答时，不生成运行成绩。

| 输入 | 保留的内容 |
| --- | --- |
| MMLU-Pro test + validation | 官方 API 提示、同学科 few-shot 示例、选项顺序、私有答案及原生答案提取规则 |
| LiveBench 原生 JSONL / Parquet | 指定 release 的加入/移除规则、system prompt、逐轮 user 输入、原生评分分派与参考答案 |
| LiveBench Coding | 完整题面、补全前缀、公开/隐藏测试、测试配置；编码的隐藏测试解码为可审阅数据，禁止执行 pickle 对象 |
| LiveBench Agentic Coding | 完整仓库版本、参考/测试补丁、显式指定的原生 agent scaffold、环境构建与评分源码；与普通 Coding 分组保留 |
| IFBench | 原始提示、全部约束及参数、strict 后 loose 的原生调用顺序、prompt 和 instruction 两种统计粒度 |
| HELM Long Context | 官方 `scenario_state.json` 与 `run_spec.json` 中已渲染的请求，适用于 RULER QA、∞Bench 英文 QA/MC/summary、OpenAI MRCR；保留选择标签映射和原生 metric 配置 |

HELM 每个实例只选指定的一个 train trial，不把 calibration 或重复请求当成新题。已截断的输入会被拒绝。MRCR 历史 assistant 消息属于题面上下文；公开运行中的模型回答和成绩不进入转换后的题目。数据版本、语言、子任务、长度及正式评测取样范围由实验配置另行冻结。

这些是题目质量审阅适配器。原生评分源码以 reviewer-only 文件提供，实时评分/环境组件明确标记为未接入；不把无法现场运行误报成原题失败，也不宣称完成了 target 重跑接入。LaaJ 可分页读取完整题目、答案和原生源码。污染检测走共享入口。

转换清单示例（路径相对启动目录）：

```json
{
  "seed": 42,
  "benchmarks": [{
    "id": "reasoning",
    "format": "livebench",
    "upstream": "/path/to/LiveBench",
    "repo": "https://github.com/LiveBench/LiveBench",
    "revision": "完整的已固定 Git commit",
    "dataset": {"repo": "livebench/reasoning", "revision": "已固定 HF commit", "split": "test"},
    "inputs": {"rows": "/path/to/test.parquet"},
    "options": {"release": "2024-11-25"},
    "sample_size": 2,
    "goal": "原始用户评测需求"
  }]
}
```

```bash
python -m pip install -e '.[references]'
python scripts/convert_reference_benchmarks.py manifest.json output/reference-review
```

`sample_size` 省略时转换全部选中数据；取样前应用 release 筛选。其它输入约定：`mmlu-pro` 使用 `rows` 和 `validation`，`ifbench` 使用 `rows`，`helm` 使用 `state` 和 `run_spec`，可指定 `options.train_trial_index`（默认 0）。Agentic Coding 在 `livebench` 格式下额外要求 `options.scaffold`，路径相对官方源码目录。转换记录含原始输入与评分源码的 SHA-256、版本、选中 ID 和 seed；源码 checkout 必须匹配固定 commit 且没有 tracked 修改。

HF 的 `livebench/liveswebench` 是另一种旧格式，不适用于现版 Agentic Coding 接口。

```bash
REFERENCE_VALIDATION_ROOT=/path/to/reference-validation \
  python -m pytest tests/test_reference_import.py tests/test_laaj_task_evidence.py tests/test_laaj_per_item.py -q
```
