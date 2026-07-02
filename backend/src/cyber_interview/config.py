import stat
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ConfigPermissionError(PermissionError):
    """Raised when a secret config is accessible by another user."""


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    api_key: str = ""
    base_url: str | None = None


def load_providers(path: Path) -> dict[str, ProviderConfig]:
    """Load provider configurations from a TOML file.

    Each provider is a subtable of ``[providers]``:

        [providers.openai]
        api_key = "..."
        base_url = "https://api.openai.com/v1"
    """
    if not path.exists():
        return {}

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ConfigPermissionError(f"{path} must not be accessible by group or other users")

    with path.open("rb") as config_file:
        document: dict[str, Any] = tomllib.load(config_file)

    providers = document.get("providers", {})
    if not isinstance(providers, dict):
        return {}

    return {str(name): ProviderConfig.model_validate(entry) for name, entry in providers.items()}
