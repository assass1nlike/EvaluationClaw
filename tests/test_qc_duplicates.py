from evalclaw.quality.dataset_checks import _duplicate_issues
from evalclaw.types import BenchmarkItem, QcCategory, QcSeverity, TaskType


def item(identifier, prompt):
    return BenchmarkItem(
        id=identifier, dimension_id="long-context", task_type=TaskType.generation,
        prompt=prompt, rubric="Check the answer against the supplied document.",
    )


def duplicates(*prompts, limit=None):
    return [issue for issue in _duplicate_issues(
        [item(str(i), prompt) for i, prompt in enumerate(prompts)],
        near_duplicate_limit=limit,
    ) if issue.category == QcCategory.duplicate]


def test_long_repetitive_near_duplicates_remain_warnings():
    document = "Record: alpha beta gamma delta; value = 42.\n" * 12000
    issues = duplicates(document + "Find the first record.", document + "Find the last record.")
    assert len(issues) == 1
    assert issues[0].severity == QcSeverity.warning


def test_long_exact_duplicates_still_reject_beyond_near_duplicate_limit():
    document = "Record alpha beta gamma.\n" * 12000
    issues = duplicates(document, "An unrelated task.", document.upper(), limit=1)
    assert len(issues) == 1
    assert issues[0].item_id == "2"
    assert issues[0].severity == QcSeverity.error


def test_full_suffix_is_checked_instead_of_a_shared_prefix_only():
    prefix = "Shared instructions: inspect every record.\n" * 400
    left = prefix + "alpha beta gamma delta\n" * 5000
    right = prefix + "delta gamma beta alpha\n" * 5000
    assert duplicates(left, right) == []


def test_small_change_at_end_of_long_input_is_not_an_exact_duplicate():
    prefix = "Review this record and report the requested value.\n" * 10000
    issues = duplicates(prefix + "Return 123.", prefix + "Return 456.")
    assert issues and all(issue.severity == QcSeverity.warning for issue in issues)


def test_unicode_long_inputs_are_compared_without_english_words():
    text = "检查记录中的数值，按照时间顺序归纳变化。\n" * 5000
    assert duplicates(text, text + "请说明理由。")[0].severity == QcSeverity.warning
    assert duplicates(text, "请阅读文档并回答问题，找出其中的矛盾。\n" * 5000) == []


def test_short_near_duplicates_keep_existing_behavior():
    issues = duplicates(
        "Analyze the supplied dataset and explain the first trend in detail.",
        "Analyze the supplied dataset and explain the second trend in detail.",
    )
    assert len(issues) == 1
    assert issues[0].severity == QcSeverity.warning
