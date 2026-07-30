"""Shared pytest fixtures for the backend test suite.

Isolates the FastAPI lifespan from the user's real application data directory.
``connect_app_database()`` (called with no argument inside ``app.main.lifespan``)
resolves to the real user data dir, so every ``TestClient(app)`` based fixture
would otherwise open the user's real ``app.sqlite``, build a runtime from real
workspaces and run ``recover_interrupted_runs()`` against real workspace state.
That access is non-deterministic and can leak across tests. Pointing
``CYBER_INTERVIEW_AGENT_DATA_DIR`` at a session-scoped temp dir makes the
lifespan use an empty, isolated app database while fixtures that need a
specific workspace still pass an explicit ``data_dir`` to
``connect_app_database``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _skip_symlink_tests_without_windows_privilege(
    monkeypatch: pytest.MonkeyPatch,
):
    """Skip only symlink cases when Windows has not enabled symlink creation."""
    if os.name != "nt":
        yield
        return

    original = Path.symlink_to

    def guarded_symlink_to(self, target, target_is_directory=False):
        try:
            return original(
                self,
                target,
                target_is_directory=target_is_directory,
            )
        except NotImplementedError:
            pytest.skip("this Windows environment does not support symlinks")
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                pytest.skip(
                    "Windows Developer Mode or symlink privilege is required"
                )
            raise

    monkeypatch.setattr(Path, "symlink_to", guarded_symlink_to)
    yield


@pytest.fixture(scope="session", autouse=True)
def _isolated_app_data_dir() -> Path:
    original = os.environ.get("CYBER_INTERVIEW_AGENT_DATA_DIR")
    with tempfile.TemporaryDirectory(prefix="cyber-test-appdata-") as tmp:
        os.environ["CYBER_INTERVIEW_AGENT_DATA_DIR"] = tmp
        yield Path(tmp)
    if original is not None:
        os.environ["CYBER_INTERVIEW_AGENT_DATA_DIR"] = original
    else:
        os.environ.pop("CYBER_INTERVIEW_AGENT_DATA_DIR", None)
