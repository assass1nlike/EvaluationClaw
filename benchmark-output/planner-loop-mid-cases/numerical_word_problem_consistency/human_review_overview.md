EvaluationClaw benchmark is ready for human review.

Objective: Evaluate the target model's ability to solve multi-step numerical word problems involving unit conversions, distractor filtering, and consistency checks.
Dimensions: 4
Ready items: 45

## Dimension item mix

| Dimension | Target | Ready | Item types |
| --- | ---: | ---: | --- |
| `unit_conversion` Multi-Step Unit Conversion | 8 | 15 | multiple_choice: 14, open_generation: 1 |
| `distractor_filtering` Distractor Filtering | 8 | 16 | multiple_choice: 16 |
| `consistency_checks` Consistency Checks | 7 | 7 | multiple_choice: 7 |
| `integrated_multi_step` Integrated Multi-Step Problems with All Aspects | 7 | 7 | open_generation: 7 |

## Dimension details

### `unit_conversion` Multi-Step Unit Conversion
- Description: Problems requiring multiple unit conversions (e.g., feet to miles, seconds to hours) within a multi-step calculation.
- Target/ready: 8 / 15
- Item types: multiple_choice: 14, open_generation: 1
- Planned types: multiple_choice, open_generation
- Requirements: Create 4 multiple-choice and 4 open-generation items. Each problem must involve at least two unit conversions (e.g., meters to kilometers, then hours to seconds).; Do not include extraneous numerical distractors; all provided numbers should be necessary for the solution.; Ensure conversion factors are standard and realistic. Answers must be numerical.

### `distractor_filtering` Distractor Filtering
- Description: Problems that include irrelevant numerical information that must be filtered out to reach the correct answer.
- Target/ready: 8 / 16
- Item types: multiple_choice: 16
- Planned types: multiple_choice, open_generation
- Requirements: Create 4 multiple-choice and 4 open-generation items. Each problem must include at least two extraneous numerical pieces of information that are not needed to solve the problem.; The correct answer should only use a subset of the given numbers. Ensure distractors in multiple-choice items include answers that would result from using irrelevant numbers.; For multiple-choice items, include all answer options clearly in the prompt.

### `consistency_checks` Consistency Checks
- Description: Problems that require verifying consistency of numerical information, such as checking for contradictory statements or verifying that intermediate results are plausible.
- Target/ready: 7 / 7
- Item types: multiple_choice: 7
- Planned types: multiple_choice, open_generation
- Requirements: Create 3 multiple-choice and 4 open-generation items.; Multiple-choice items should present a scenario with numerical claims and ask whether they are consistent or not, with options like 'Consistent', 'Inconsistent', or 'Cannot determine'.; Open-generation items should require the model to explain the consistency reasoning explicitly.

### `integrated_multi_step` Integrated Multi-Step Problems with All Aspects
- Description: Combined problems that require unit conversions, distractor filtering, and consistency checks simultaneously.
- Target/ready: 7 / 7
- Item types: open_generation: 7
- Planned types: open_generation
- Requirements: Generate 7 open-generation items only (no multiple-choice).; Each problem must require at least one unit conversion, include at least two irrelevant numbers, and have a built-in consistency check (e.g., the problem involves verifying that a derived value matches a given constraint).; The model should produce a step-by-step solution and a final numerical answer. Scoring will use a judge to evaluate correctness and reasoning quality.

Reply with an empty line, 'approve', or 'ok' to run targets.
Or describe requested changes, for example: 'Split dimension X into A/B', 'delete item Y', 'add 2 code-sandbox items to dimension Z', or 'make dimension A focus on multi-turn escalation'.
