from cyber_interview.domain.errors import ErrorCategory, OutputError


def test_output_error_carries_category_and_message():
    err = OutputError(
        category=ErrorCategory.MODEL,
        safe_message="无法解析为 JSON",
        finish_reason="length",
    )
    assert err.category is ErrorCategory.MODEL
    assert err.safe_message == "无法解析为 JSON"
    assert err.finish_reason == "length"


def test_finish_reason_optional():
    err = OutputError(category=ErrorCategory.POLICY, safe_message="schema 不合法")
    assert err.finish_reason is None
