EvaluationClaw benchmark is ready for human review.

Objective: Evaluate whether the target model reviews a small Python code change for bugs, regressions, and missing tests, providing actionable findings with severity.
Dimensions: 3
Ready items: 30

## Dimension item mix

| Dimension | Target | Ready | Item types |
| --- | ---: | ---: | --- |
| `bug_detection` Bug Detection in Code Changes | 10 | 10 | open_generation: 10 |
| `regression_detection` Regression Detection in Code Changes | 10 | 10 | open_generation: 10 |
| `missing_test_detection` Missing Test and Actionability Detection | 10 | 10 | open_generation: 10 |

## Dimension details

### `bug_detection` Bug Detection in Code Changes
- Description: Model identifies a bug introduced in a small Python diff.
- Target/ready: 10 / 10
- Item types: open_generation: 10
- Planned types: open_generation
- Requirements: Each item is a small Python diff (added lines with +, removed with -) for a self-contained function or script.; The diff must contain at least one bug: off-by-one in loop, wrong variable, incorrect condition, missing import, etc.; Provide ground truth: exact bug location, type, severity (critical/major/minor), and a description of the fix.

### `regression_detection` Regression Detection in Code Changes
- Description: Model identifies a regression where a change breaks existing functionality.
- Target/ready: 10 / 10
- Item types: open_generation: 10
- Planned types: open_generation
- Requirements: Each item is a small Python diff where the change appears innocuous but introduces a regression (behavior change that breaks existing callers or assumptions).; Examples: renaming a parameter, changing default value, removing error handling, altering function return type, breaking backward compatibility.; Provide ground truth: the regression point, what functionality is broken, severity (critical/major/minor), and how to fix or avoid.

### `missing_test_detection` Missing Test and Actionability Detection
- Description: Model identifies missing tests in a code change and suggests what tests are needed.
- Target/ready: 10 / 10
- Item types: open_generation: 10
- Planned types: open_generation
- Requirements: Each item is a small Python diff either adding a new function/class, modifying a public API, or removing a test file. The diff must lack corresponding tests or modify tests in a way that breaks coverage.; Provide ground truth: what test scenarios are missing (e.g., edge cases, error handling, integration with existing code), severity of missing tests (critical if core functionality, minor if niche).; Prompt: 'Review the following Python code diff. Identify any missing tests or test gaps. Suggest what tests should be added and explain why. Assign severity.'

Reply with an empty line, 'approve', or 'ok' to run targets.
Or describe requested changes, for example: 'Split dimension X into A/B', 'delete item Y', 'add 2 code-sandbox items to dimension Z', or 'make dimension A focus on multi-turn escalation'.
