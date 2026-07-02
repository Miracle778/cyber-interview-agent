from cyber_interview.api.errors import ErrorEnvelope, ErrorResponse


def test_error_envelope_fields():
    e = ErrorEnvelope(
        code="run_not_found",
        category="input",
        retryable=False,
        safe_message="run not found",
        diagnostic_id="d1",
        next_actions=[],
    )
    assert e.category == "input" and e.retryable is False


def test_error_response_to_dict():
    e = ErrorEnvelope(
        code="already_published",
        category="policy",
        retryable=False,
        safe_message="已发布",
        diagnostic_id="d2",
        next_actions=["reject"],
    )
    r = ErrorResponse(envelope=e)
    d = r.model_dump()
    assert d["envelope"]["code"] == "already_published"
