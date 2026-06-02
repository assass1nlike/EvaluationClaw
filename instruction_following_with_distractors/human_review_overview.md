EvaluationClaw benchmark is ready for human review.

Objective: Evaluate whether the target model follows multi-step instructions with distractors while preserving required format and order.
Dimensions: 5
Ready items: 13

## Dimension item mix

| Dimension | Target | Ready | Item types |
| --- | ---: | ---: | --- |
| `baseline_sequential` Baseline sequential instruction following | 2 | 3 | open_generation: 3 |
| `distractor_irrelevant_instructions` Distractor irrelevant instructions | 2 | 3 | open_generation: 3 |
| `distractor_order_preservation` Distractor order preservation | 2 | 2 | open_generation: 2 |
| `format_adherence_with_distractors` Format adherence with distractors | 2 | 2 | open_generation: 2 |
| `multi_turn_instruction_distractors` Multi-turn instruction following with distractors | 2 | 3 | multi_turn: 3 |

## Dimension details

### `baseline_sequential` Baseline sequential instruction following
- Description: Follow a sequence of 3-5 explicit steps in order, outputting results in a specified format (e.g., numbered list). No distractors.
- Target/ready: 2 / 3
- Item types: open_generation: 3
- Planned types: open_generation
- Requirements: Each item must include exactly 3-5 sequential instructions, with a clear required output format (e.g., numbered list, bulleted list, key-value pair).; Do not include any distractor instructions or irrelevant extra steps.; The ground truth answer must specify the exact expected output for each step in order.

### `distractor_irrelevant_instructions` Distractor irrelevant instructions
- Description: Follow a set of relevant instructions while ignoring one or two irrelevant instructions embedded in the prompt.
- Target/ready: 2 / 3
- Item types: open_generation: 3
- Planned types: open_generation
- Requirements: Each item must contain 3-5 total instructions, with 1-2 of them being distractors (irrelevant to the primary task).; Distractors should be clearly marked as irrelevant in the prompt (e.g., 'Note: This step is optional' or by context) but still easy to mistake if not careful.; The required output format must be specified and must match only the relevant steps.

### `distractor_order_preservation` Distractor order preservation
- Description: Follow instructions in the given order despite distractors that attempt to reorder or mislead about the sequence.
- Target/ready: 2 / 2
- Item types: open_generation: 2
- Planned types: open_generation
- Requirements: Each item must have 3-5 relevant steps in a specific order, plus 1-2 distractors that mention reordering or alternative sequences.; The required output format must preserve the original order (e.g., 'Output the results in the order they were first listed').; Scoring metadata: ground_truth_output in correct order, and an order_check field that verifies the correct sequence.

### `format_adherence_with_distractors` Format adherence with distractors
- Description: Produce output in a specified format (e.g., JSON, markdown list, table) while ignoring distractors that suggest different formats.
- Target/ready: 2 / 2
- Item types: open_generation: 2
- Planned types: open_generation
- Requirements: Each item must specify a clear output format (e.g., JSON, Markdown list, YAML).; Include 1-2 distractors that mention or use a different format (e.g., 'If helpful, you can also use bullet points').; The ground truth output must be a valid instance of the required format containing the correct data.

### `multi_turn_instruction_distractors` Multi-turn instruction following with distractors
- Description: Follow a sequence of instructions delivered across multiple conversational turns, with some turns containing distractors or misleading information.
- Target/ready: 2 / 3
- Item types: multi_turn: 3
- Planned types: multi_turn
- Requirements: Each item must be a multi_turn interaction with 3-5 user turns.; Include 1-2 distractor turns that contain irrelevant or misleading instructions.; The final turn must request output in a specific format (e.g., summary list, JSON).

Reply with an empty line, 'approve', or 'ok' to run targets.
Or describe requested changes, for example: 'Split dimension X into A/B', 'delete item Y', 'add 2 code-sandbox items to dimension Z', or 'make dimension A focus on multi-turn escalation'.
