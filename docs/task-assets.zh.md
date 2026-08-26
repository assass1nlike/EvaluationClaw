# Task Assets

题目使用的文件放在顶层 `assets` 字段中：

```json
{
  "prompt": "Inspect benchmark-output/assets/question.png and choose the correct answer.",
  "assets": [
    {"path": "benchmark-output/assets/question.png"}
  ]
}
```

`assets` 是列表，每项只包含 `path`。路径必须指向 runner 可读取的真实本地文件；prompt 必须用完全相同的路径指代该文件。完整路径会进入目标模型输入，因此文件名不得泄露答案或其他非预期信息。没有文件输入时使用空列表。

来源信息仍由 `resources` 和 `resource_ids` 表示，不放在 `assets` 中。构题工具生成、处理或下载文件后，应将工具返回的本地路径写入对应题目的 `assets` 和 prompt。

普通目标模型调用当前只支持图像文件，并根据目标 provider 生成原生图像输入。其他文件路径可以保存在题目契约中，但当前直接执行会在目标调用前报告不支持。
