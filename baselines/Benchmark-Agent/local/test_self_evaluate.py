from local.self_evaluate import answer_messages, choice_label, is_choice


def test_respondent_never_receives_reference_or_metadata():
    item = {"sample": {"input": {"context": "task context", "question": "task question"},
                       "output": {"answer": "private reference"}},
            "dataset_id": "private provenance"}
    messages = answer_messages(item, {"answer_type": "free_form"})
    item["sample"]["output"] = {"answer": "a different reference"}
    item["dataset_id"] = "different provenance"
    assert answer_messages(item, {"answer_type": "free_form"}) == messages
    assert len(messages) == 2


def test_choice_scoring_uses_subtask_schema_and_strict_label():
    assert is_choice({"answer_type": "choice"}, {"answer": "A"})
    assert not is_choice({"answer_type": "free_form"}, {"answer": "A"})
    assert not is_choice({"answer_type": "choice"}, {"answer": "answer text"})
    assert choice_label(" A\n") == "A"
    assert choice_label("A or B") is None
    assert choice_label("Answer: A") is None
    assert choice_label(None) is None
