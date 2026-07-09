from pathlib import Path

class WorkspaceError(ValueError):
    pass

def resolve_workspace(path: str) -> Path:
    workspace = Path(path).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace

def ensure_inside_workspace(workspace: Path, target: Path) -> Path:
    workspace = workspace.resolve()
    target = target.expanduser().resolve()
    if target == workspace or workspace in target.parents:
        return target
    raise WorkspaceError("目标路径超出 workspace 沙箱")
