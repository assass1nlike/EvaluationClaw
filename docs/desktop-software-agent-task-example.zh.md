# 桌面软件 Agent 任务示例：LibreOffice Calc 数据清洗与导出

这是一道 `gui_desktop` / `desktop_software` 类型的 agent 评测题示例。它测试目标 agent 能否在 VM 桌面环境中操作真实桌面软件，而不是只回答静态问题。

## 初始需求

用户给 EvalClaw 的自然语言需求可以是：

> 测试一个 AI agent 使用桌面表格软件完成数据清洗、公式计算和导出报告的能力。任务应在隔离 VM 中运行，并通过产物自动评分。

## 评测目标

这道题主要考察：

- 能否理解表格任务要求，而不是只生成文字说明。
- 能否通过截图、鼠标、键盘、文件工具操作桌面软件。
- 能否在多步 GUI 环境中保持目标状态。
- 能否保存正确产物，并让环境检查器自动验证。

## 任务描述

目标 agent 进入一个新的 LibreOffice Calc VM 会话。桌面上已有 `Desktop/orders_raw.csv`，其中包含订单数据：

```csv
order_id,region,status,amount
1001,East,paid,120.50
1002,West,cancelled,88.00
1003,East,paid,43.25
1004,North,paid,200.00
1005,West,paid,51.75
```

agent 需要：

1. 用 LibreOffice Calc 打开 `orders_raw.csv`。
2. 新增一列 `net_amount`。
3. 对 `status=paid` 的订单，`net_amount` 等于 `amount`；对 cancelled 订单，`net_amount` 为 `0`。
4. 创建一个汇总区域，按 `region` 计算 `net_amount` 总和。
5. 保存为 `Desktop/orders_cleaned.ods`。
6. 导出汇总为 `Desktop/region_summary.csv`。

## BenchmarkItem 示例

下面是转换为 EvalClaw item 后的核心 JSON。真实 benchmark package 里它会作为 `BenchmarkItem.metadata` 的一部分保存。

```json
{
  "id": "libreoffice_calc_order_cleanup_001",
  "dimension_id": "desktop_spreadsheet_operation",
  "task_type": "agent_interaction",
  "prompt": "Use LibreOffice Calc in the VM to clean the order spreadsheet. Add net_amount, compute regional paid totals, save the edited spreadsheet, export the regional summary CSV, then run evaluation.",
  "rubric": "Full credit requires the edited spreadsheet and exported CSV to contain correct net_amount and regional totals. Partial credit is available for creating only one correct artifact.",
  "tags": ["agent", "gui_desktop", "desktop_software", "spreadsheet", "vm"],
  "metadata": {
    "task_agent": {
      "schema_version": "evalclaw.task_agent.v1",
      "agent_role": "target_agent_executor",
      "system_prompt": "You are the target agent in a GUI desktop software evaluation. Use exactly one valid tool action per turn. Inspect the desktop state, operate LibreOffice Calc, save artifacts, and do not claim completion until the environment evaluation passes.",
      "initial_content": {
        "scenario": "A fresh VM desktop session contains a CSV file on the Desktop. The task is to use LibreOffice Calc to clean the data and export a summary artifact.",
        "files": {
          "Desktop/orders_raw.csv": "order_id,region,status,amount\n1001,East,paid,120.50\n1002,West,cancelled,88.00\n1003,East,paid,43.25\n1004,North,paid,200.00\n1005,West,paid,51.75\n"
        },
        "session": {
          "application": "libreoffice_calc",
          "start_state": "VM desktop is logged in. Desktop/orders_raw.csv is present. LibreOffice Calc is installed but not yet opened.",
          "assets": ["Desktop/orders_raw.csv"],
          "expected_artifacts": [
            "Desktop/orders_cleaned.ods",
            "Desktop/region_summary.csv"
          ],
          "restrictions": [
            "The target agent should operate the spreadsheet application through GUI tools.",
            "Direct file writing is allowed only for diagnostics or recovery if the bridge policy permits it; primary completion should be via LibreOffice Calc."
          ]
        },
        "vm": {
          "isolation": "fresh_snapshot",
          "image": "evalclaw-libreoffice-gui",
          "snapshot": "clean-with-calc-and-bridge",
          "display": {"width": 1280, "height": 900, "scale": 1.0},
          "required_software": ["LibreOffice Calc", "evalclaw-desktop-bridge"],
          "network": "none",
          "locale": "en_US.UTF-8"
        },
        "evaluation": {
          "method": "spreadsheet_artifact_check",
          "checks": [
            "orders_cleaned.ods exists and has a net_amount column.",
            "cancelled order 1002 has net_amount 0.",
            "paid orders preserve their amount as net_amount.",
            "region_summary.csv exists.",
            "region_summary.csv contains East=163.75, North=200.00, West=51.75."
          ],
          "pass_criteria": "Both artifacts exist and all numeric checks match exactly within currency rounding.",
          "partial_criteria": "At least one artifact is present and most computed values are correct.",
          "fail_criteria": "No valid artifact is produced or the summary totals are substantially wrong."
        }
      },
      "interaction": {
        "max_turns": 30,
        "initial_user_message": "Clean Desktop/orders_raw.csv in LibreOffice Calc, save Desktop/orders_cleaned.ods, export Desktop/region_summary.csv, then run evaluation.",
        "user_turns": [],
        "followup_instruction": "",
        "stop_condition": "Stop when the bridge evaluation reports completion or the step limit is reached."
      },
      "scoring": {
        "method": "deterministic",
        "instructions": "Use the VM desktop bridge evaluator. Award full credit only when artifact checks pass.",
        "levels": {
          "5": "All spreadsheet and CSV artifact checks pass.",
          "3": "One artifact is correct or the outputs are mostly correct with minor formatting issues.",
          "1": "The agent does not produce usable artifacts."
        },
        "pass_fail": {
          "pass": "orders_cleaned.ods and region_summary.csv both exist and contain correct values.",
          "partial": "Some required output exists but at least one artifact or value is missing.",
          "fail": "No meaningful spreadsheet output is produced."
        }
      },
      "execution": {
        "environment_type": "gui_desktop",
        "agent_env": {
          "type": "gui_desktop",
          "requires_vm": true,
          "max_steps": 30,
          "timeout": 30,
          "session": {
            "application": "libreoffice_calc",
            "start_state": "Desktop/orders_raw.csv is ready to open.",
            "assets": ["Desktop/orders_raw.csv"],
            "expected_artifacts": [
              "Desktop/orders_cleaned.ods",
              "Desktop/region_summary.csv"
            ]
          },
          "vm": {
            "image": "evalclaw-libreoffice-gui",
            "snapshot": "clean-with-calc-and-bridge",
            "display": {"width": 1280, "height": 900, "scale": 1.0},
            "required_software": ["LibreOffice Calc", "evalclaw-desktop-bridge"],
            "network": "none",
            "locale": "en_US.UTF-8"
          },
          "evaluation": {
            "method": "spreadsheet_artifact_check",
            "expected_artifacts": [
              "Desktop/orders_cleaned.ods",
              "Desktop/region_summary.csv"
            ],
            "checks": [
              {
                "name": "ods_has_net_amount",
                "description": "orders_cleaned.ods contains a net_amount column.",
                "weight": 0.2
              },
              {
                "name": "net_amount_values",
                "description": "paid rows keep amount; cancelled rows have net_amount 0.",
                "weight": 0.3
              },
              {
                "name": "summary_csv_exists",
                "description": "region_summary.csv exists.",
                "weight": 0.15
              },
              {
                "name": "summary_totals",
                "description": "Region totals are East=163.75, North=200.00, West=51.75.",
                "weight": 0.35
              }
            ],
            "pass_criteria": "All weighted checks pass.",
            "partial_criteria": "At least one artifact is correct and total score is above 0.4.",
            "fail_criteria": "No expected artifact exists or score is below 0.4."
          }
        }
      }
    },
    "agent_env": {
      "type": "gui_desktop",
      "requires_vm": true,
      "max_steps": 30,
      "timeout": 30,
      "session": {
        "application": "libreoffice_calc",
        "start_state": "Desktop/orders_raw.csv is ready to open.",
        "assets": ["Desktop/orders_raw.csv"],
        "expected_artifacts": [
          "Desktop/orders_cleaned.ods",
          "Desktop/region_summary.csv"
        ]
      },
      "vm": {
        "image": "evalclaw-libreoffice-gui",
        "snapshot": "clean-with-calc-and-bridge",
        "display": {"width": 1280, "height": 900, "scale": 1.0},
        "required_software": ["LibreOffice Calc", "evalclaw-desktop-bridge"],
        "network": "none",
        "locale": "en_US.UTF-8"
      },
      "evaluation": {
        "method": "spreadsheet_artifact_check",
        "expected_artifacts": [
          "Desktop/orders_cleaned.ods",
          "Desktop/region_summary.csv"
        ],
        "pass_criteria": "All spreadsheet artifact checks pass.",
        "partial_criteria": "Some artifact or value checks pass.",
        "fail_criteria": "No meaningful spreadsheet output is produced."
      }
    }
  }
}
```

## 可用工具

该题运行时，目标 agent 通常会看到 `gui_desktop` 环境暴露的工具，包括：

- `screenshot`: 获取当前屏幕截图。
- `mouse_move` / `click` / `drag` / `scroll`: 操作 UI。
- `key` / `type`: 输入快捷键和文本。
- `list_files` / `read_file`: 检查桌面文件或导出的 CSV。
- `run_command`: 做有限诊断，例如查看文件是否存在。
- `evaluate`: 调用 bridge 内部评分器。
- `final`: 结束任务并触发最终评分。

## 执行流程

运行时流程如下：

1. `environment_claw` 检查该 item 需要 `gui_desktop` 且 `requires_vm=true`。
2. VM provider 创建或重置一个 LibreOffice VM。
3. VM 内启动 desktop bridge，并返回 `bridge_url`。
4. runner 创建 `DesktopBridgeAgentEnvironment`。
5. 目标 agent 每轮接收截图/观察和工具 schema，返回一个 JSON action。
6. bridge 在 VM 内执行鼠标、键盘、文件或命令动作。
7. agent 调用 `evaluate` 后，bridge 检查 `.ods` 和 `.csv` 产物。
8. runner 保存完整 trace、最终状态和分数。

## 评分方式

这类任务最好使用确定性 artifact scoring，而不是只用 LLM judge。原因是桌面软件任务通常有明确产物：

- 文件是否存在。
- 表格列是否存在。
- 单元格值是否正确。
- CSV 导出内容是否正确。
- 是否产生了不应该出现的错误文件或空文件。

如果 bridge 支持 LibreOffice headless 检查，可以在 VM 内用命令读取 `.ods` 或转换为 CSV 后比较。评分器返回类似：

```json
{
  "score": 0.85,
  "done": false,
  "observation": "orders_cleaned.ods is correct, but region_summary.csv misses West=51.75.",
  "checks": [
    {"name": "ods_has_net_amount", "passed": true, "weight": 0.2},
    {"name": "net_amount_values", "passed": true, "weight": 0.3},
    {"name": "summary_csv_exists", "passed": true, "weight": 0.15},
    {"name": "summary_totals", "passed": false, "weight": 0.35}
  ]
}
```

## 设计要点

- 桌面软件任务必须写清楚 `session`、`vm`、`evaluation`。
- 不要把 `bridge_url`、API key、VM provider secret 写进题目；这些由运行时配置注入。
- 初始文件可以放在 `initial_content.files` 或由 VM 镜像/bridge session 准备。
- 评分标准要尽量落到 artifact/state check，而不是让 judge 只看 agent 的自述。
- 如果任务真的要求 GUI 操作，就使用 `gui_desktop`；如果只是命令行处理 CSV，用 `docker_workspace` 或 `code_sandbox` 更合适。
