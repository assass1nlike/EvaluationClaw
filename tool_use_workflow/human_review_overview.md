EvaluationClaw benchmark is ready for human review.

Objective: Evaluate whether the target model can use tools in a short workflow to search, extract, and synthesize structured information.
Dimensions: 4
Ready items: 29

## Dimension item mix

| Dimension | Target | Ready | Item types |
| --- | ---: | ---: | --- |
| `single_tool_extraction` Single-Tool Extraction | 6 | 6 | agent_interaction: 6 |
| `multi_step_tool_workflow` Multi-Step Tool Workflow | 8 | 8 | agent_interaction: 8 |
| `structured_synthesis` Structured Synthesis from Multiple Sources | 8 | 9 | agent_interaction: 9 |
| `tool_error_resilience` Tool Error Handling and Edge Cases | 6 | 6 | agent_interaction: 6 |

## Dimension details

### `single_tool_extraction` Single-Tool Extraction
- Description: Model uses one tool (search, calculator, database lookup) to extract a specific piece of information and answer a factual question.
- Target/ready: 6 / 6
- Item types: agent_interaction: 6
- Planned types: agent_interaction
- Requirements: Generate a scenario with one tool (e.g., search_books, lookup_weather, calculate_expression). Provide the tool's function schema (name, parameters, return type).; The query must require the model to call the tool to obtain the answer; trivia knowledge alone should not suffice.; Tool returns a deterministic JSON response. Model must output the exact tool call and then the final answer.

### `multi_step_tool_workflow` Multi-Step Tool Workflow
- Description: Model uses two or more tools in sequence (search then extract, or search then calculate) to answer a question that requires chaining.
- Target/ready: 8 / 8
- Item types: agent_interaction: 8
- Planned types: agent_interaction
- Requirements: Generate a scenario where the model must call tool A, then tool B using data from tool A's response. Provide both tool schemas.; Example: 'Use search_company to find the CEO of Acme Corp, then use get_employee_email with the CEO's name to get their email address.'; Tool responses must be deterministic and contain the needed fields.

### `structured_synthesis` Structured Synthesis from Multiple Sources
- Description: Model searches multiple sources (tools) and synthesizes the gathered information into a structured format (JSON, table, etc.).
- Target/ready: 8 / 9
- Item types: agent_interaction: 9
- Planned types: agent_interaction
- Requirements: Generate a scenario requiring information from multiple tools (e.g., product details from one, reviews from another). Provide tool schemas.; Model must call each tool, collect all data, and produce a structured output (e.g., JSON with keys: title, rating, summary).; Ensure that the model's final output is a valid JSON object conforming to an expected schema (specified in the prompt).

### `tool_error_resilience` Tool Error Handling and Edge Cases
- Description: Model handles tool errors gracefully: rate limits, empty results, ambiguous queries, or tool failures.
- Target/ready: 6 / 6
- Item types: agent_interaction: 6
- Planned types: agent_interaction
- Requirements: Generate scenarios where the tool returns an error (e.g., 'rate limit exceeded', 'no results found', 'invalid parameter').; Model should not give up immediately; it should attempt to retry, modify parameters, or ask the user for more input.; The prompt must not directly reveal the correct resolution or prescribe the exact retry strategy. It may hint at ambiguity but should let the model decide how to adapt.

Reply with an empty line, 'approve', or 'ok' to run targets.
Or describe requested changes, for example: 'Split dimension X into A/B', 'delete item Y', 'add 2 code-sandbox items to dimension Z', or 'make dimension A focus on multi-turn escalation'.
