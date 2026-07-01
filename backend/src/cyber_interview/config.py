import stat
import tomllib
from pathlib import Path
from typing import Any


class ConfigPermissionError(PermissionError):
    """Raised when a secret config is accessible by another user."""


def load_provider_secrets(path: Path) -> dict[str, str]:
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
    return {str(key): str(value) for key, value in providers.items()}
