# Task Agent Spec JSON

`metadata.task_agent` 是 EvaluationClaw 给复杂交互题使用的标准化 JSON 对象。它不是一个单独的外部文件路径，而是写在每道题目的 JSON metadata 里；导出 benchmark package 时也会作为普通 JSON 一起保存。JSON Schema 在 [task-agent-spec.schema.json](task-agent-spec.schema.json)。

这个规格用于这些题型：

- `multi_turn`：为每道题单独创建任务级 helper agent，用它的 `system_prompt` 扮演用户模拟器，动态生成后续轮次；如果提供了 `interaction.user_turns`，则使用这些确定性后续轮次。
- `agent_interaction`：为每道题保存目标 agent 的执行说明、初始状态和评分标准；内置 `workspace` / `code_sandbox` 环境仍通过 `metadata.agent_env` 执行，但同一份信息也应在 `metadata.task_agent` 中说明清楚。
- 其它未来复杂题型：只要需要模拟用户、环境控制器、任务专用 judge 或可复现实验场景，都应使用这个对象。

## 字段

`schema_version`

固定为 `evalclaw.task_agent.v1`。

`agent_role`

任务级 agent 的角色。例如：

- `dialogue_simulator`：多轮对话里的用户模拟器。
- `environment_controller`：交互环境控制器。
- `target_agent_executor`：给被测模型作为 agent 执行任务时的角色说明。
- `judge`：任务专用评分 agent。

`system_prompt`

给任务级 agent 的完整 system prompt。它应说明：

- 当前执行的是什么评估。
- agent 扮演什么角色。
- 每一轮应该如何行动。
- 哪些信息可以告诉 target，哪些不能泄露。
- 输出格式要求，例如必须返回 JSON。

`initial_content`

任务初始内容。可以是对象或字符串。对于代码库维护、文件编辑、工具使用类任务，建议写成：

```json
{
  "scenario": "The target must fix a small Python repository.",
  "files": {
    "solution.py": "def solve(x):\n    pass\n",
    "README.md": "Implement solve."
  },
  "notes": "Hidden tests are available only through run_tests."
}
```

`interaction`

交互方式。

- `max_turns`：最多生成几轮后续用户 turn 或执行几步。
- `initial_user_message`：可选第一轮用户消息；不写则使用 `BenchmarkItem.prompt`。
- `user_turns`：可选确定性后续轮次。写了它，runner 直接按列表执行，不再动态生成。
- `followup_instruction`：动态生成后续轮次时，helper agent 应怎样根据 transcript 选择下一句话。
- `stop_condition`：什么时候停止。

`scoring`

评分指导。

- `method`: `agent_judge` / `task_agent_judge` 表示用任务级 agent 打分；`runner_judge` 表示普通 judge 使用这里的额外指导；`deterministic` 表示由环境分数决定。
- `instructions`: 评分总体说明。
- `levels`: 1-5 分等评分等级的含义。
- `pass_fail`: `pass` / `partial` / `fail` 标准，适合工具执行、代码修复、环境模拟类任务。

`execution`

执行环境信息。

- `environment_type`: `dialogue`、`workspace`、`code_sandbox` 等。
- `agent_env`: 内置环境配置。为了兼容当前 runner，如果使用内置 `workspace` 或 `code_sandbox`，还应把同一份对象放到 `metadata.agent_env`。

## 示例

```json
{
  "metadata": {
    "task_agent": {
      "schema_version": "evalclaw.task_agent.v1",
      "agent_role": "dialogue_simulator",
      "system_prompt": "You are a task-specific user simulator for an EvaluationClaw multi-turn evaluation. Ask concise follow-up questions that test whether the target model can revise its answer after corrected requirements. Return JSON only when asked for the next turn.",
      "initial_content": {
        "scenario": "Evaluate whether the target can maintain consistency while revising a project plan."
      },
      "interaction": {
        "max_turns": 2,
        "followup_instruction": "First add a correction that invalidates one assumption. Then stop after the target revises.",
        "stop_condition": "Stop after the target has answered one meaningful correction."
      },
      "scoring": {
        "method": "agent_judge",
        "instructions": "Score the full transcript for consistency, correct incorporation of the correction, and concise communication.",
        "levels": {
          "5": "Correctly answers the initial request and fully incorporates the correction.",
          "3": "Partially incorporates the correction but misses an important implication.",
          "1": "Ignores the correction or contradicts the prior context."
        }
      },
      "execution": {
        "environment_type": "dialogue"
      }
    }
  }
}
```

## Planner / Generator 约定

如果 planner 在某个维度里使用 `multi_turn` 或 `agent_interaction`，它必须在该维度的 `item_requirements` 中告诉生成 worker：

- 这个维度要创建什么任务级 agent。
- `system_prompt` 应覆盖哪些行为和约束。
- `initial_content` 需要包含哪些场景、文件、状态或用户信息。
- 交互如何进行，包括是否使用确定性 `user_turns`。
- 评分是 `agent_judge`、`runner_judge` 还是 `deterministic`，以及各分数/通过标准是什么意思。

Generator 生成这类题时，应把上述内容写进 `metadata.task_agent`。如果是内置环境题，还要保留 `metadata.agent_env`，这样旧的 runner 和报告逻辑仍然能直接执行与展示。
