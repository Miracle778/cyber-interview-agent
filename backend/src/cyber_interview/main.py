import json
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cyber_interview.api.health import router as health_router
from cyber_interview.api.profile import router as profile_router
from cyber_interview.app.approval_service import ArtifactApprovalService
from cyber_interview.app.profile_service import ProfileService
from cyber_interview.app.run_service import AgentRunService
from cyber_interview.config import load_providers
from cyber_interview.harness.fake_model import FakeModelGateway
from cyber_interview.harness.model_gateway import ModelChunk
from cyber_interview.harness.runtime import LoopAgentRuntime
from cyber_interview.harness.task_registry import TaskRegistry
from cyber_interview.infra.db import engine_from_settings, session_factory_from_settings
from cyber_interview.settings import get_settings

_singletons = {}


def _reset_singletons():
    _singletons.clear()


def _build_gateway(settings):
    providers = load_providers(settings.config_path)
    if "openai" in providers and providers["openai"].api_key:
        from cyber_interview.harness.model_adapters import OpenAIAdapter

        model = providers["openai"].model or "gpt-4o-mini"
        return OpenAIAdapter(config=providers["openai"], model=model), "openai", model
    if "anthropic" in providers and providers["anthropic"].api_key:
        from cyber_interview.harness.model_adapters import AnthropicAdapter

        model = providers["anthropic"].model or "claude-3-5-haiku-latest"
        return AnthropicAdapter(config=providers["anthropic"], model=model), "anthropic", model
    payload = json.dumps(
        {
            "schema_name": "profile",
            "schema_version": 1,
            "facts": [{"claim": "placeholder", "evidence_ref": None}],
        }
    )
    return (
        FakeModelGateway(
            chunks=[
                ModelChunk(type="delta", text=payload),
                ModelChunk(type="done", finish_reason="stop"),
            ]
        ),
        "openai",
        "gpt-4o-mini",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = engine_from_settings(settings)
    factory = session_factory_from_settings(settings)
    gateway, provider, model = _build_gateway(settings)
    runtime = LoopAgentRuntime(model_gateway=gateway)
    registry = TaskRegistry()
    run_service = AgentRunService(
        session_factory=factory,
        runtime=runtime,
        registry=registry,
        provider=provider,
        model=model,
    )
    app.state.session_factory = factory
    app.state.profile_service = ProfileService(run_service=run_service)
    app.state.approval_service = ArtifactApprovalService(session_factory=factory)
    app.state.registry = registry
    _singletons["engine"] = engine
    yield
    await registry.shutdown()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Cyber Interview Agent", version="0.0.0", lifespan=lifespan)
    settings = get_settings()
    gateway, provider, model = _build_gateway(settings)
    registry = TaskRegistry()

    def fallback_factory():
        return session_factory_from_settings(get_settings())()

    run_service = AgentRunService(
        session_factory=fallback_factory,
        runtime=LoopAgentRuntime(model_gateway=gateway),
        registry=registry,
        provider=provider,
        model=model,
    )
    app.state.session_factory = fallback_factory
    app.state.profile_service = ProfileService(run_service=run_service)
    app.state.approval_service = ArtifactApprovalService(session_factory=fallback_factory)
    app.state.registry = registry
    app.include_router(health_router)
    app.include_router(profile_router)
    return app


app = create_app()
