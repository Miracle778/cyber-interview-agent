from pathlib import Path

import pytest

from app.services.workspace import WorkspaceError, ensure_inside_workspace

def test_rejects_path_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    outside.write_text("x")
    with pytest.raises(WorkspaceError):
        ensure_inside_workspace(workspace, outside)
