from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class ProviderErrorCode(str, Enum):
    OK = "ok"
    SECRET_MISSING = "secret_missing"
    AUTH_FAILED = "auth_failed"
    MODEL_NOT_FOUND = "model_not_found"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    PROTOCOL_ERROR = "protocol_error"


ERROR_MESSAGES: dict[ProviderErrorCode, str] = {
    ProviderErrorCode.OK: "连接成功",
    ProviderErrorCode.SECRET_MISSING: "未配置 API Key",
    ProviderErrorCode.AUTH_FAILED: "API Key 无效或已过期",
    ProviderErrorCode.MODEL_NOT_FOUND: "模型不存在",
    ProviderErrorCode.RATE_LIMITED: "请求频率超限",
    ProviderErrorCode.TIMEOUT: "请求超时",
    ProviderErrorCode.NETWORK_ERROR: "网络连接错误",
    ProviderErrorCode.PROTOCOL_ERROR: "协议错误",
}


@dataclass(frozen=True)
class ProviderTestResult:
    status: ProviderErrorCode
    latency_ms: int
    message: str
    resolved_model_id: str | None = None
    capabilities: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProviderErrorCode):
            object.__setattr__(self, "status", ProviderErrorCode(self.status))


class ProviderAdapter(Protocol):
    async def test_connection(
        self, *, base_url: str, model_id: str, api_key: str
    ) -> ProviderTestResult: ...


class FakeProviderAdapter:
    """In-memory ProviderAdapter for tests."""

    def __init__(self) -> None:
        self.next_result: ProviderTestResult = ProviderTestResult(
            status=ProviderErrorCode.OK,
            latency_ms=0,
            message=ERROR_MESSAGES[ProviderErrorCode.OK],
        )
        self.last_call: dict | None = None

    async def test_connection(
        self, *, base_url: str, model_id: str, api_key: str
    ) -> ProviderTestResult:
        self.last_call = {"base_url": base_url, "model_id": model_id, "api_key": api_key}
        return self.next_result
