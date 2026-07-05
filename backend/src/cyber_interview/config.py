import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider.

    `model` is the provider's default model id. DU01 has no AgentDefinition yet,
    so the default model is configured at provider level; DU03+ AgentDefinition
    may override per-agent (定稿 §12.1).
    """

    api_key: str = ""
    base_url: str | None = None
    model: str | None = None


def load_providers(path: Path) -> dict[str, ProviderConfig]:
    """Load provider configurations from a TOML file.

    Each provider is a subtable of ``[providers]``:

        [providers.openai]
        api_key = "..."
        base_url = "https://api.openai.com/v1"
    """
    if not path.exists():
        return {}

    with path.open("rb") as config_file:
        document: dict[str, Any] = tomllib.load(config_file)

    providers = document.get("providers", {})
    if not isinstance(providers, dict):
        return {}

    return {str(name): ProviderConfig.model_validate(entry) for name, entry in providers.items()}
