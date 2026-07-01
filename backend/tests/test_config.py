from pathlib import Path

import pytest

from cyber_interview.config import ConfigPermissionError, load_provider_secrets


def test_missing_config_returns_empty_mapping(tmp_path: Path):
    assert load_provider_secrets(tmp_path / "missing.toml") == {}


def test_private_config_loads_provider_keys(tmp_path: Path):
    config_path = tmp_path / "config.local.toml"
    config_path.write_text('[providers]\nopenai_api_key = "secret"\n', encoding="utf-8")
    config_path.chmod(0o600)

    assert load_provider_secrets(config_path) == {"openai_api_key": "secret"}


def test_group_readable_config_is_rejected(tmp_path: Path):
    config_path = tmp_path / "config.local.toml"
    config_path.write_text('[providers]\nopenai_api_key = "secret"\n', encoding="utf-8")
    config_path.chmod(0o640)

    with pytest.raises(ConfigPermissionError):
        load_provider_secrets(config_path)
