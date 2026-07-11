from pathlib import Path

from app.security.workspace_paths import (
    SCOPE_PATHS,
    PathPolicyError,
    WorkspacePathPolicy,
)

class WorkspaceError(ValueError):
    pass

def resolve_workspace(path: str) -> Path:
    workspace = Path(path).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace

def ensure_inside_workspace(workspace: Path, target: Path) -> Path:
    try:
        policy = WorkspacePathPolicy(workspace)
        expanded_target = target.expanduser()
        if not expanded_target.is_absolute():
            expanded_target = workspace / expanded_target
        for scope, scope_path in SCOPE_PATHS.items():
            try:
                relative = expanded_target.relative_to(workspace / scope_path)
            except ValueError:
                continue
            relative_path = relative.as_posix()
            if expanded_target.exists():
                return policy.resolve_for_read(scope, relative_path)
            return policy.resolve_for_create(scope, relative_path)
    except PathPolicyError as error:
        raise WorkspaceError("目标路径超出 workspace 沙箱") from error
    raise WorkspaceError("目标路径超出 workspace 沙箱")
