import pytest

from cyber_interview.domain.errors import ErrorCategory, OutputError
from cyber_interview.domain.profile import ProfileFact, ProfileVersion
from cyber_interview.harness.gates import GateError, OutputGate, RunGate
from cyber_interview.harness.output_parser import FinalOutputResult


def test_run_gate_rejects_empty_text():
    with pytest.raises(GateError):
        RunGate().check(input_text="", artifact_kind="profile")


def test_run_gate_accepts_nonempty():
    RunGate().check(input_text="some text", artifact_kind="profile")


def test_output_gate_rejects_error_result():
    result = FinalOutputResult(error=OutputError(category=ErrorCategory.MODEL, safe_message="bad"))
    with pytest.raises(GateError):
        OutputGate().validate(result)


def test_output_gate_accepts_profile():
    pv = ProfileVersion(facts=[ProfileFact(claim="x")])
    result = FinalOutputResult(profile=pv)
    OutputGate().validate(result)
