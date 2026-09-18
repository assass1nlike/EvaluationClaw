EvaluationClaw benchmark is ready for human review.

Objective: Evaluate whether the target model follows a strict JSON schema under distracting natural-language instructions, focusing on exact field names and type compliance.
Dimensions: 4
Ready items: 32

## Dimension item mix

| Dimension | Target | Ready | Item types |
| --- | ---: | ---: | --- |
| `basic_field_adherence` Basic Field Name Adherence | 8 | 8 | open_generation: 8 |
| `data_type_compliance` Data Type Compliance | 8 | 8 | open_generation: 8 |
| `nested_and_constraint_compliance` Nested Schema and Constraint Compliance | 8 | 8 | open_generation: 8 |
| `distraction_resistance` Distraction Resistance | 8 | 8 | open_generation: 8 |

## Dimension details

### `basic_field_adherence` Basic Field Name Adherence
- Description: Test whether the model outputs exactly the field names specified in the JSON schema, without renaming, omitting, or adding fields.
- Target/ready: 8 / 8
- Item types: open_generation: 8
- Planned types: open_generation
- Requirements: The item must include a JSON schema with at least 3 field names (e.g., firstName, lastName, age).; The natural-language instruction must include the schema and also some irrelevant context (e.g., 'Generate a person record. The schema is: ... but feel free to use any naming you like').; The model must output exactly the schema field names; do not provide hints that would guide the model to the correct field names.

### `data_type_compliance` Data Type Compliance
- Description: Test whether the model assigns correct data types to each field according to the schema (e.g., integer, string, boolean, null, array, object).
- Target/ready: 8 / 8
- Item types: open_generation: 8
- Planned types: open_generation
- Requirements: Schema must specify types for each field (e.g., 'age': {'type': 'integer'}, 'isStudent': {'type': 'boolean'}).; Natural-language instruction may include misleading type hints (e.g., 'age should be a string like 'twenty'').; Model must output correct types. Scoring: exact type match per field; judge score for partial type accuracy.

### `nested_and_constraint_compliance` Nested Schema and Constraint Compliance
- Description: Test ability to follow nested object schemas and constraints like enum, minimum, maximum, pattern.
- Target/ready: 8 / 8
- Item types: open_generation: 8
- Planned types: open_generation
- Requirements: Schema must include at least one nested object and one constraint (e.g., enum: ['male','female','other'], minimum: 0 for age).; Natural-language instruction can add irrelevant context but should not explicitly list all constraints.; Model must output JSON that satisfies all constraints. Scoring: exact compliance with nested structure and constraints; partial for violations.

### `distraction_resistance` Distraction Resistance
- Description: Test the model's ability to ignore natural-language instructions that directly contradict the JSON schema, such as telling the model to use a different field name or ignore a required field.
- Target/ready: 8 / 8
- Item types: open_generation: 8
- Planned types: open_generation
- Requirements: Schema should have at least 3 fields.; Natural-language instruction must include a direct request to change field names, omit fields, or change types.; Model must ignore these and output exact schema. Scoring: exact match of field names and types; zero tolerance for deviation.

Reply with an empty line, 'approve', or 'ok' to run targets.
Or describe requested changes, for example: 'Split dimension X into A/B', 'delete item Y', 'add 2 code-sandbox items to dimension Z', or 'make dimension A focus on multi-turn escalation'.
