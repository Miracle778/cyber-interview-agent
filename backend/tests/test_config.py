from pathlib import Path

import pytest

from cyber_interview.config import ConfigPermissionError, ProviderConfig, load_providers


def test_missing_config_returns_empty_mapping(tmp_path: Path):
    assert load_providers(tmp_path / "missing.toml") == {}


def test_loads_provider_with_api_key_and_base_url(tmp_path: Path):
    config_path = tmp_path / "config.local.toml"
    config_path.write_text(
        '[providers.openai]\n'
        'api_key = "secret"\n'
        'base_url = "https://api.openai.com/v1"\n',
        encoding="utf-8",
    )
    config_path.chmod(0o600)

    assert load_providers(config_path) == {
        "openai": ProviderConfig(api_key="secret", base_url="https://api.openai.com/v1")
    }


def test_base_url_is_optional(tmp_path: Path):
    config_path = tmp_path / "config.local.toml"
    config_path.write_text('[providers.openai]\napi_key = "secret"\n', encoding="utf-8")
    config_path.chmod(0o600)

    assert load_providers(config_path) == {
        "openai": ProviderConfig(api_key="secret", base_url=None)
    }


def test_group_readable_config_is_rejected(tmp_path: Path):
    config_path = tmp_path / "config.local.toml"
    config_path.write_text('[providers.openai]\napi_key = "secret"\n', encoding="utf-8")
    config_path.chmod(0o640)

    with pytest.raises(ConfigPermissionError):
        load_providers(config_path)
