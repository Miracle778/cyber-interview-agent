from pathlib import Path

from cyber_interview.settings import Settings


def test_settings_defaults():
    settings = Settings(_env_file=None)

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.data_dir == Path("./data")
    assert settings.config_path == Path("config.local.toml")


def test_settings_environment_override(monkeypatch):
    monkeypatch.setenv("CIA_PORT", "9000")
    monkeypatch.setenv("CIA_DATA_DIR", "/tmp/career-agent")

    settings = Settings(_env_file=None)

    assert settings.port == 9000
    assert settings.data_dir == Path("/tmp/career-agent")


def test_settings_config_path_override(monkeypatch):
    monkeypatch.setenv("CIA_CONFIG_PATH", "/etc/career/config.toml")

    settings = Settings(_env_file=None)

    assert settings.config_path == Path("/etc/career/config.toml")
