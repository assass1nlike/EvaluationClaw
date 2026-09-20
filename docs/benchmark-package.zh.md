前沿模型 baseline 使用独立的文件交付接口。给构题模型的材料是 `evalclaw/authoring/docs/DELIVERY.md`、按需查阅的 `INTERFACES.md` 和无依赖的通信助手；不需要向它展示 TaskDefinition、Builder 契约或 EvalClaw 构题提示词。

准备说明文件、验证交付、转换的命令如下。安装当前项目后，也可将 `.venv/bin/python -m evalclaw.authoring` 写作 `benchmark-package`。

```bash
.venv/bin/python -m evalclaw.authoring kit /path/to/author-instructions
.venv/bin/python -m evalclaw.authoring check /path/to/package
.venv/bin/python -m evalclaw.authoring check /path/to/package --config /path/to/run-config.json
.venv/bin/python -m evalclaw.authoring prepare /path/to/package > /path/to/image-preparation.json
.venv/bin/python -m evalclaw.authoring exercise /path/to/package /path/to/cases.json
.venv/bin/python -m evalclaw.authoring pack /path/to/package /path/to/new-bundle
```

包根目录的 `benchmark.json` 给出用户需求和任务目录顺序。每题的 `task.json` 定位题面、材料与评分规则；单条文本题只需 id、prompt 和 grading。复杂任务可独立选择角色化消息、媒体材料、固定对话、Docker 工作区、自定义工具服务、程序或模型驱动的控制器、程序/模型/环境评分及多个指标。普通程序接收统一 JSON-lines 请求，辅助代码仅负责通信和错误传递。选择题可以把选项保留在题面中；转换器不拆分选项，不增加作答指令。

转换没有模型调用，不执行作者程序，也不修改原始输入、评分规则或程序逻辑。路径、字段和组件绑定遵循固定规则。结构错误带任务文件路径返回；不跳过坏题，不补写答案，也不自动降低交互要求。文件默认只供审阅，目标可见性必须明确声明。任务没有默认构题 effort，也不编造能力维度。内部题型标签仅按声明的交互接口生成，不能用它推断原题属于选择、填空还是开放生成。

输出目录包括 `original/` 原始文件、`suite.json` 通用任务表示，以及 `conversion.json` 原始文件校验值、转换结果校验值和逐题映射。转换结果只保存相对路径；加载时检查完整性并绑定当前位置，整个目录可以移动。程序通信助手内嵌在保存的组件中，不会在以后加载时自动替换成新版本。

通过现有 Python 接口运行或审阅：

```python
from pathlib import Path
from evalclaw.authoring import load_bundle
from evalclaw.execution.contract_capabilities import binding_issues
from evalclaw.execution.memory_budget import memory_budget
from evalclaw.execution.runner import run_eval
from evalclaw.quality.laaj import evaluate_with_laaj
from evalclaw.types import BenchmarkConfig, QcReport

suite = load_bundle('/path/to/bundle')
config = BenchmarkConfig.model_validate_json(Path('/path/to/run-config.json').read_text())
issues = [(item.id, target.id, binding_issues(item, config, target))
          for item in suite.tasks for target in config.targets]
assert not any(errors for _, _, errors in issues), issues
output = Path('/path/to/results')
output.mkdir(parents=True, exist_ok=True)
with memory_budget(config, output):
    # 只表示接收已验证结构的原始题目，不调用语义 QC 修改或筛题。
    accepted = QcReport(passed_item_ids=[item.id for item in suite.tasks],
                        summary='Imported package; no semantic QC performed')
    run = run_eval(suite, accepted, config, trace_dir=output / 'run')
    (output / 'run.json').write_text(run.model_dump_json(indent=2))
    quality = evaluate_with_laaj(suite.objective, suite, None, config, run=run,
                                artifact_dir=output, trace_dir=output / 'laaj')
    (output / 'laaj.json').write_text(quality.model_dump_json(indent=2))
```

如只评题目质量，可省略 `evaluate_with_laaj` 的 run 关键字参数。LaaJ 可访问原始题目、参考、代码及资源，并使用现有隔离环境探索接口；无需逐题转换或补写环境解释。

结构有效、所选后端支持、环境实际可执行、题目内容正确是不同的检查。`check` 只验证前两者（第二项需配置文件）；执行预检和 LaaJ 分别处理后两者。构题所用 Codex 与目标作答接口独立，原生工具服务和控制器不能静默替换成 shell 操作。第一版沿用当前运行器的能力限制，例如似然需相应模型接口，外部 shell harness 不支持原生控制器；自定义程序集不意味着自动获得 VM 或外部账号。

正式实验前固定交付说明、通信助手、转换器、运行配置和预算。格式修复反馈只包含结构或执行接口错误；保存全部原始产物、失败交付及修复消耗。题目内容的质量优化不是转换步骤，也不自动接入 EvalClaw 的语义 QC。

镜像来源或 Dockerfile 写在 benchmark.json 的 images 中，prepare 按声明准备并输出实际镜像 ID；本地别名不会被当作远程镜像拉取。目标配置用 supported_message_roles 声明接口支持的角色，未声明时兼容性检查不会声称已验证。exercise 执行作者提供的具体方法调用，复用正式运行器的返回验证，可提前发现工具错误字段、评分证据类型和分数边界问题；通过仅代表这些测试路径有效，不保证全部题目内容正确。

Python 评分器不能把候选目录放在私有检查模块之前，也不能把“在独立容器评分”等同于“任意候选代码都无法操纵评分逻辑”。这属于评分程序需要自行维护的信任边界；接口检查和转换器不会替作者重写评分算法。

批量入口使用 `python -m evalclaw.authoring.batch start CONFIG.json OUTPUT_DIRECTORY`。
配置示例在 `evalclaw/authoring/configs/acceptance.json`；将 jobs 替换为正式需求与题数即可，密钥通过配置指定的环境变量提供。启动时冻结代码、交付说明、配置及作者容器镜像 ID，后台协调器不依赖 SSH 连接。作者容器里的 `benchmark-package` 命令接到按任务隔离的检查服务，不获得宿主 Docker socket 或真实模型密钥。

每次检查保存交付快照和反馈；作者结束后固定原始 bundle，准备镜像、检查兼容性、重放作者测试，再运行目标及 LaaJ。镜像运行视图按实际 ID 固定并另存，不改原始 bundle。结果明确区分请求数、交付数、不兼容数、执行错误及有效评分数；有效均分不代表全部请求题目的准确率。没有自动重构题、语义优化或按目标得分筛题。完整统计约定随实验保存在 README.md。
