import json

import pytest

from evalclaw.models.json_utils import extract_json


@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```", "Answer:\n{}\nEnd."])
def test_json_asset_strings_survive_parsing(wrapper):
    document = {"files": {"source.py": 'r"a{2,}"; r"thanks[, ]*"; \\"',
                          "data.txt": 'literal ,}\n,] and ``` fences'}}
    assert extract_json(wrapper.format(json.dumps(document))) == document


def test_trailing_comma_repair_preserves_string_contents():
    assert extract_json('{"regex": "{2,}", "values": ["a,]",],}') == {
        "regex": "{2,}", "values": ["a,]"],
    }


@pytest.mark.parametrize("document", [
    '{"tasks": [{"id": "nested"}] broken}',
    '{"tasks": [{"id": "nested"}]',
    '```json\n{"tasks": [{"id": "nested"}] broken}\n```',
])
def test_invalid_outer_document_is_not_replaced_by_nested_asset(document):
    with pytest.raises(ValueError):
        extract_json(document, allow_repair=False)
