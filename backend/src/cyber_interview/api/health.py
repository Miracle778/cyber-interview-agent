from typing import Literal, TypedDict

from fastapi import APIRouter

router = APIRouter(prefix="/api")


class HealthChecks(TypedDict):
    database: Literal["skipped"]
    providers: Literal["not_configured"]


class HealthResponse(TypedDict):
    status: Literal["ok"]
    version: str
    checks: HealthChecks


@router.get("/health")
async def get_health() -> HealthResponse:
    return {
        "status": "ok",
        "version": "0.0.0",
        "checks": {
            "database": "skipped",
            "providers": "not_configured",
        },
    }
