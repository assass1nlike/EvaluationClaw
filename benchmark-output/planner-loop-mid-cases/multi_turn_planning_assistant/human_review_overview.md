EvaluationClaw benchmark is ready for human review.

Objective: Evaluate whether the target model can conduct a multi-turn planning conversation that gathers constraints and revises recommendations accordingly.
Dimensions: 5
Ready items: 33

## Dimension item mix

| Dimension | Target | Ready | Item types |
| --- | ---: | ---: | --- |
| `constraint_gathering` Constraint Gathering | 6 | 6 | multi_turn: 6 |
| `revision_based_on_new_constraints` Revision Based on New Constraints | 6 | 6 | multi_turn: 6 |
| `handling_ambiguous_or_partial_constraints` Handling Ambiguous or Partial Constraints | 6 | 6 | multi_turn: 6 |
| `handling_conflicting_constraints` Handling Conflicting Constraints | 6 | 8 | multi_turn: 8 |
| `incremental_planning_with_multiple_revisions` Incremental Planning with Multiple Revisions | 6 | 7 | multi_turn: 7 |

## Dimension details

### `constraint_gathering` Constraint Gathering
- Description: Tests whether the model actively asks for relevant constraints (budget, preferences, limitations) before making a plan or recommendation.
- Target/ready: 6 / 6
- Item types: multi_turn: 6
- Planned types: multi_turn
- Requirements: Create a multi-turn dialogue scenario where the user provides a vague planning goal (e.g., 'Plan a team offsite', 'Organize a birthday dinner', 'Recommend a study schedule').; The dialogue simulator must start with only this vague goal and wait for the model to ask questions before revealing constraints.; Constraints must be realistic: budget, time, preferences, restrictions, etc.

### `revision_based_on_new_constraints` Revision Based on New Constraints
- Description: Tests whether the model can revise an existing plan when the user introduces new constraints after an initial recommendation.
- Target/ready: 6 / 6
- Item types: multi_turn: 6
- Planned types: multi_turn
- Requirements: Create a scenario where the user initially provides enough constraints for a reasonable plan (e.g., trip to Paris with 5 days and museum interests).; The model offers a concrete plan (e.g., itinerary, project timeline).; Then the user adds a contradictory or restrictive constraint (e.g., 'actually I only have 3 days' or 'no flying').

### `handling_ambiguous_or_partial_constraints` Handling Ambiguous or Partial Constraints
- Description: Tests whether the model asks clarifying questions when faced with ambiguous or incomplete information before committing to a plan.
- Target/ready: 6 / 6
- Item types: multi_turn: 6
- Planned types: multi_turn
- Requirements: Create a scenario where the user's initial request contains ambiguous terms like 'good', 'reasonable', 'fun', 'quick', 'somewhere', 'around', 'a few'.; The model should not proceed with a definitive plan without clarifying these terms.; The dialogue simulator should provide clarifications only when asked, but may leave some ambiguity (e.g., 'moderate budget' defined as $1000-$1500 per person).

### `handling_conflicting_constraints` Handling Conflicting Constraints
- Description: Tests whether the model can identify conflicts between user constraints and suggest trade-offs or compromises.
- Target/ready: 6 / 8
- Item types: multi_turn: 8
- Planned types: multi_turn
- Requirements: Create a scenario where the user states goals that conflict logically (e.g., 'I want to visit all five museums in one day' combined with 'I want to spend at least 3 hours in each').; The model must detect the conflict and explain why it's infeasible.; The model should propose alternatives or ask the user to prioritize (e.g., 'which museums are most important?', 'would you be willing to shorten some visits?').

### `incremental_planning_with_multiple_revisions` Incremental Planning with Multiple Revisions
- Description: Tests the model's ability to iteratively refine a plan through multiple rounds of new constraints and revisions over a longer conversation.
- Target/ready: 6 / 7
- Item types: multi_turn: 7
- Planned types: multi_turn
- Requirements: Create a scenario that requires multiple (3-4) changes: start with a simple plan, then user adds companion (need to adjust capacity/cost), changes date (seasonal impacts), adds new preference (e.g., 'must be wheelchair accessible'), and finally reduces budget.; The model must revise the plan at each step, maintaining consistency.; The dialogue simulator should introduce changes after the model's plan each time.

Reply with an empty line, 'approve', or 'ok' to run targets.
Or describe requested changes, for example: 'Split dimension X into A/B', 'delete item Y', 'add 2 code-sandbox items to dimension Z', or 'make dimension A focus on multi-turn escalation'.
