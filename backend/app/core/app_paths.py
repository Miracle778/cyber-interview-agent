import os
from pathlib import Path

from platformdirs import user_data_path


def resolve_app_data_dir() -> Path:
    override = os.getenv("CYBER_INTERVIEW_AGENT_DATA_DIR")
    path = (
        Path(override).expanduser()
        if override
        else user_data_path("cyber-interview-agent", appauthor=False)
    )
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()
