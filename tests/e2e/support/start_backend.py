from __future__ import annotations

import os
import shutil
from pathlib import Path

import uvicorn


DATA_DIR = Path("/private/tmp/cyber-r16-e2e-data")
WORKSPACE_DIR = Path("/private/tmp/cyber-r16-e2e-workspace")

for path in (DATA_DIR, WORKSPACE_DIR):
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)

os.environ["CYBER_INTERVIEW_AGENT_DATA_DIR"] = str(DATA_DIR)
os.environ["R16_E2E_API_KEY"] = "local-e2e-key"

uvicorn.run("app.main:app", app_dir="backend", host="127.0.0.1", port=8017)
