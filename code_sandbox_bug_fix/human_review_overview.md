EvaluationClaw benchmark is ready for human review.

Objective: Evaluate whether the target model can inspect a tiny Python repository in a sandbox, run tests, and fix a failing bug by identifying and correcting the root cause.
Dimensions: 4
Ready items: 5

## Dimension item mix

| Dimension | Target | Ready | Item types |
| --- | ---: | ---: | --- |
| `logical_error` Logical error in a simple function | 1 | 2 | agent_interaction: 2 |
| `off_by_one` Off-by-one error in loop or index | 1 | 1 | agent_interaction: 1 |
| `incorrect_api_usage` Wrong API usage or argument order | 1 | 1 | agent_interaction: 1 |
| `missing_edge_case` Missing handling of edge case | 1 | 1 | agent_interaction: 1 |

## Dimension details

### `logical_error` Logical error in a simple function
- Description: The target model must fix a function that returns wrong result due to an incorrect condition or expression logic (e.g., using `and` instead of `or`, swapped comparisons).
- Target/ready: 1 / 2
- Item types: agent_interaction: 2
- Planned types: agent_interaction
- Requirements: Create a tiny Python repository (e.g., 2 files: src.py and test.py).; Define a function with a logical error that produces wrong output for the test.; The test must be a single pytest test that fails on the buggy function and passes after the correct fix.

### `off_by_one` Off-by-one error in loop or index
- Description: The target model must fix an off-by-one error in a loop range or list index (e.g., using `range(n-1)` instead of `range(n)`, or incorrect slice endpoint).
- Target/ready: 1 / 1
- Item types: agent_interaction: 1
- Planned types: agent_interaction
- Requirements: Create a tiny Python repository with one off-by-one error in a loop or indexing.; Include a single pytest test that fails due to the error.; Use metadata.task_agent as described in the logical error dimension, with same agent_role and environment config.

### `incorrect_api_usage` Wrong API usage or argument order
- Description: The target model must fix incorrect usage of a standard library API (e.g., wrong argument name, wrong method, etc.).
- Target/ready: 1 / 1
- Item types: agent_interaction: 1
- Planned types: agent_interaction
- Requirements: Create a repo with a function that uses a standard library API incorrectly (e.g., wrong keyword argument, wrong number of arguments, wrong method name).; The test should fail because of the API misuse.; Same metadata.task_agent structure and scoring as previous dimensions.

### `missing_edge_case` Missing handling of edge case
- Description: The target model must add handling for an edge case that the function currently ignores (e.g., empty list, None input).
- Target/ready: 1 / 1
- Item types: agent_interaction: 1
- Planned types: agent_interaction
- Requirements: Create a repo where a function does not handle a standard edge case (e.g., empty input, zero value).; The test should cover that edge case and fail.; Same metadata.task_agent and scoring structure.

Reply with an empty line, 'approve', or 'ok' to run targets.
Or describe requested changes, for example: 'Split dimension X into A/B', 'delete item Y', 'add 2 code-sandbox items to dimension Z', or 'make dimension A focus on multi-turn escalation'.
