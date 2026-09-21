人工评审以同一用户需求下的两道题为一组，综合比较需求契合度与评测质量，只允许选择 A 或 B，理由可选。模型作答用于辅助判断题目质量，不把模型得分低直接视作题目更好。单题比较的结果不能直接代表整套 benchmark 的覆盖度与多样性。

启动示例界面：

```bash
.venv/bin/python -m evalclaw.reporting.human_judge \
  examples/human-judge/comparisons.json \
  --database benchmark-output/human-judge/demo.sqlite \
  --port 8877 --seed 42
```

浏览器打开 `http://127.0.0.1:8877`。远程服务器可通过 SSH 转发访问：`ssh -L 8877:127.0.0.1:8877 用户名@服务器`。这是本地／可信网络的评审服务，没有公共用户注册与管理员登录；研究者导出仅通过命令行。需要常驻时放在 tmux 中运行。

点击“开始新的评审”生成独立恢复码。恢复码保存在当前浏览器，并可在页面右上角复制到另一浏览器继续；每位评审人应使用独立恢复码。提交才会保存，跳过的组不计入结果。允许回看和修改，统计使用最后一次提交，同时保留所有修改记录。SQLite 将选择保存在服务端，重启服务后仍可继续。

导入数据时，用自己的 JSON 替换命令中的示例文件，格式见 [示例](../examples/human-judge/comparisons.json)：

- `title`：页面标题，使用不暴露来源的名称。
- `pairs`：明确配好的比较组；每组具有唯一 `id`、用户需求 `requirement` 和恰好两个 `candidates`。
- 每个候选的 `source` 是仅研究者可见的来源名；`task` 和 `response` 分别承载完整题目与作答，可以是文本、对象或数组。确实没有作答时显式写 `null`，界面会标明未提供。
- `sections` 补充参考答案、评分规则、环境、工具、执行轨迹等，每项包含 `title` 与 `content`。既可直接放入已有 TaskDefinition 和作答记录，也可按这些阅读层次组织内容；界面不调用模型重写或概括题目。
- `artifacts` 是附件列表，每项包含中性的展示名 `label` 和相对于 JSON 所在目录的文件 `path`。文件必须位于该目录内。附件支持完整下载；不超过2 MiB的UTF-8文本及PNG/JPEG可在页内预览。超过此大小不会截掉内容，而是提供完整文件下载。

每位评审人的组顺序、A/B位置通过 seed、数据指纹、恢复码和组序号确定，刷新后保持不变。服务端不向评审页面发送 `source`、原始组 `id` 或本地附件路径，也不提供来源映射查询。题目正文、嵌入的元数据和附件仍可能自行暴露来源：正式导入时应统一清理非题目本身所需的来源标识，保留影响解题或评分的真实内容；程序不使用关键词替换改写原题。

数据与附件应在一次评审期间保持不变。启动时会计算内容指纹；修改数据、附件或 seed 后必须换用新的数据库，防止不同版本的选择混在一起。页面按需展示当前组，长结构可展开；文件下载不局限于页面预览范围。导入者需提供完整文件，只有路径或镜像名称不能替代实际环境证据。

研究者导出：

```bash
.venv/bin/python -m evalclaw.reporting.human_judge \
  examples/human-judge/comparisons.json \
  --database benchmark-output/human-judge/demo.sqlite \
  --export benchmark-output/human-judge/decisions.json
```

导出包含数据指纹、seed、匿名评审编号、原始组ID、左右候选序号及来源、获选来源、理由、提交时间，以及完整修改历史。`decisions` 是每人每组的最后提交，`history` 是审计记录，不能把历史记录重复计票。导出不包含可登录的恢复码。正式题集的抽样、配对与评审人数需另行确定；示例用于验证界面，不构成实验结果。
