EvaluationClaw benchmark is ready for human review.

Objective: Evaluate whether the target model answers questions grounded in a short provided document packet, citing supporting evidence and avoiding unsupported claims.
Dimensions: 6
Ready items: 18

## Dimension item mix

| Dimension | Target | Ready | Item types |
| --- | ---: | ---: | --- |
| `direct_fact_extraction` Direct Fact Extraction and Citation | 3 | 3 | open_generation: 3 |
| `multi_fact_with_multiple_citations` Multi-fact Answer with Multiple Citations | 3 | 3 | open_generation: 3 |
| `refusal_unsupported_queries` Refusal to Answer Unsupported Queries | 3 | 3 | open_generation: 3 |
| `ambiguity_contradiction_handling` Ambiguity and Contradiction Handling | 3 | 3 | open_generation: 3 |
| `citation_format_precision` Citation Format and Precision | 3 | 3 | open_generation: 3 |
| `grounded_irrelevant_information` Groundedness Amidst Irrelevant Information | 3 | 3 | open_generation: 3 |

## Dimension details

### `direct_fact_extraction` Direct Fact Extraction and Citation
- Description: Test whether the model correctly extracts a single factual statement from the document and cites the exact supporting sentence.
- Target/ready: 3 / 3
- Item types: open_generation: 3
- Planned types: open_generation
- Requirements: Generate a short document (3–5 sentences) and a question that has a clear answer present in the document. The answer should be a single fact. Ensure the document contains a sentence that directly answers the question. The model must output an answer with a citation to the exact sentence. Avoid ambiguous or multi-fact questions. The scoring judge will check: 1) factual correctness, 2) correct sentence cited, 3) no extra unsupported claims.

### `multi_fact_with_multiple_citations` Multi-fact Answer with Multiple Citations
- Description: Test whether the model can aggregate multiple facts from the document, citing each fact appropriately.
- Target/ready: 3 / 3
- Item types: open_generation: 3
- Planned types: open_generation
- Requirements: G; e; n

### `refusal_unsupported_queries` Refusal to Answer Unsupported Queries
- Description: Test whether the model declines to answer or states 'not supported' when the question cannot be answered from the given document.
- Target/ready: 3 / 3
- Item types: open_generation: 3
- Planned types: open_generation
- Requirements: G; e; n

### `ambiguity_contradiction_handling` Ambiguity and Contradiction Handling
- Description: Test how the model handles documents with ambiguous or contradictory statements, requiring careful citation or qualification.
- Target/ready: 3 / 3
- Item types: open_generation: 3
- Planned types: open_generation
- Requirements: G; e; n

### `citation_format_precision` Citation Format and Precision
- Description: Test whether the model adheres to a specified citation format and cites precise spans (e.g., sentence number or exact quote) rather than vague references.
- Target/ready: 3 / 3
- Item types: open_generation: 3
- Planned types: open_generation
- Requirements: G; e; n

### `grounded_irrelevant_information` Groundedness Amidst Irrelevant Information
- Description: Test whether the model ignores irrelevant or distractor information in the document and only uses relevant facts to answer.
- Target/ready: 3 / 3
- Item types: open_generation: 3
- Planned types: open_generation
- Requirements: G; e; n

Reply with an empty line, 'approve', or 'ok' to run targets.
Or describe requested changes, for example: 'Split dimension X into A/B', 'delete item Y', 'add 2 code-sandbox items to dimension Z', or 'make dimension A focus on multi-turn escalation'.
