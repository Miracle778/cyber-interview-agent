from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("./data")

    model_config = SettingsConfigDict(env_prefix="CIA_", env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()
