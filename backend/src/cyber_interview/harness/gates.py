from cyber_interview.domain.errors import ErrorCategory
from cyber_interview.harness.output_parser import FinalOutputResult


class GateError(Exception):
    """Raised when a gate rejects, carrying a category."""

    def __init__(self, message: str, category: ErrorCategory = ErrorCategory.POLICY):
        super().__init__(message)
        self.category = category


class Gate:
    """Policy Gate base class. DU02/DU03 add Model/Tool subclasses."""

    def check(self, **kwargs) -> None:
        raise NotImplementedError


class RunGate(Gate):
    def check(self, *, input_text: str, artifact_kind: str) -> None:
        if not input_text or not input_text.strip():
            raise GateError("输入文本不能为空", category=ErrorCategory.INPUT)
        if artifact_kind != "profile":
            raise GateError(
                f"不支持的 artifact kind: {artifact_kind}", category=ErrorCategory.INPUT
            )


class OutputGate(Gate):
    def validate(self, result: FinalOutputResult) -> None:
        if result.error is not None:
            raise GateError(result.error.safe_message, category=result.error.category)
        if result.profile is None:
            raise GateError("无 profile 输出", category=ErrorCategory.POLICY)
