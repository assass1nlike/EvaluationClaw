EvaluationClaw benchmark is ready for human review.

Objective: Evaluate whether the target model handles a multi-turn customer support conversation under a refund/exchange policy, including asking for missing information, applying policy constraints, and escalating when needed.
Dimensions: 4
Ready items: 12

## Dimension item mix

| Dimension | Target | Ready | Item types |
| --- | ---: | ---: | --- |
| `information_gathering` Information Gathering for Refund/Exchange Requests | 3 | 3 | multi_turn: 3 |
| `policy_constraint_application` Policy Constraint Application in Refund/Exchange | 3 | 3 | multi_turn: 3 |
| `escalation_handling` Escalation Handling for Complex or Dissatisfied Customers | 3 | 3 | multi_turn: 3 |
| `mixed_scenario` Mixed Scenario: Information Gathering and Policy Application in Single Interaction | 3 | 3 | multi_turn: 3 |

## Dimension details

### `information_gathering` Information Gathering for Refund/Exchange Requests
- Description: Tests whether the model proactively asks for missing information required to process a refund or exchange (e.g., order number, reason, proof of purchase).
- Target/ready: 3 / 3
- Item types: multi_turn: 3
- Planned types: multi_turn
- Requirements: Each item must define a unique missing piece of information (order number, reason for return, proof of purchase). The model must ask for that piece; if it proceeds without, it fails that criterion.; The metadata.task_agent must include: system_prompt detailing the retail support agent role and policy; initial_content.scenario describing the customer's context (e.g., item, date of purchase, customer mood); interaction.max_turns >= 3; scoring.method = 'agent_judge' with levels for full/partial credit for asking all required info, applying policy correctly, and maintaining polite tone.; Off-target: Model that directly approves/denies without gathering info, or that asks for irrelevant information, or that hallucinates details not provided.

### `policy_constraint_application` Policy Constraint Application in Refund/Exchange
- Description: Tests whether the model correctly applies policy constraints such as return windows, condition requirements, and receipt requirements when denying or approving requests.
- Target/ready: 3 / 3
- Item types: multi_turn: 3
- Planned types: multi_turn
- Requirements: Each item must test a different policy violation: expired return window, non-returnable item category, missing receipt combined with item not found in system.; The metadata.task_agent must include: system_prompt with clear policy rules (e.g., 30-day return, items must be unworn, electronics require original packaging); initial_content.scenario with purchase context; interaction.max_turns >= 3; scoring.method = 'agent_judge' evaluating whether the model correctly applied the relevant rule, offered a practical alternative (e.g., store credit if applicable), and handled customer pushback.; Off-target: Model that approves request despite violation, or gives incorrect policy justification, or fails to offer any alternative when policy allows.

### `escalation_handling` Escalation Handling for Complex or Dissatisfied Customers
- Description: Tests whether the model recognizes when a situation requires human escalation (e.g., repeated refusal, customer anger, requests outside policy scope) and handles it appropriately.
- Target/ready: 3 / 3
- Item types: multi_turn: 3
- Planned types: multi_turn
- Requirements: Each item must present a different escalation trigger: repeated denial (customer insists after policy explanation), angry/abusive language, request outside policy scope (e.g., refund for a gift card used partially).; The metadata.task_agent must include: system_prompt defining the escalation protocol (e.g., 'transfer to supervisor when customer asks three times or uses offensive language'); initial_content.scenario with customer demeanor; interaction.max_turns >= 4 to allow escalation; scoring.method = 'agent_judge' evaluating whether the model escalated at the appropriate time, maintained professionalism, and provided a smooth handoff.; Off-target: Model that escalates too early without attempting reasonable resolution, or that fails to escalate when the policy clearly requires it, or that escalates incorrectly (e.g., to refund department for a policy question).

### `mixed_scenario` Mixed Scenario: Information Gathering and Policy Application in Single Interaction
- Description: Tests combined capability where the customer request is both incomplete and subject to policy constraints, requiring the model to gather info and then apply policy in a coherent multi-turn flow.
- Target/ready: 3 / 3
- Item types: multi_turn: 3
- Planned types: multi_turn
- Requirements: Each item must combine a missing-information scenario with a policy constraint that is revealed only after gathering info. Example: customer asks to exchange a sweater but hasn't provided order number or reason; when info reveals it's past 30 days, model must deny but offer store credit if policy allows.; The metadata.task_agent must include: system_prompt with comprehensive policy; initial_content.scenario with item details; interaction.initial_user_message as the vague request; interaction.max_turns >= 5 to allow full back-and-forth; scoring.method = 'agent_judge' evaluating both information gathering and policy application in a single score, with partial credit for doing one correctly but missing the other.; Off-target: Model that ignores missing info and jumps to policy, or that gathers info but then incorrectly applies policy, or that fails to coordinate the two tasks coherently.

Reply with an empty line, 'approve', or 'ok' to run targets.
Or describe requested changes, for example: 'Split dimension X into A/B', 'delete item Y', 'add 2 code-sandbox items to dimension Z', or 'make dimension A focus on multi-turn escalation'.
