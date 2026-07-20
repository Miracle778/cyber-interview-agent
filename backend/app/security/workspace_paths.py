from __future__ import annotations

import stat
from pathlib import Path, PureWindowsPath


SCOPE_PATHS = {
    "review.sources": Path("artifacts/review/sources"),
    "review.drafts": Path("artifacts/review/drafts"),
    "profile.materials": Path("artifacts/profile/materials"),
    "knowledge.active": Path("knowledge-vault"),
    "diagnostics.security": Path(".cyber-interview-agent/diagnostics"),
}


class PathPolicyError(ValueError):
    code = "workspace_path_denied"

    def __init__(self, scope: str, relative_path: str | None = None) -> None:
        detail = f"scope={scope}"
        if relative_path is not None:
            detail = f"{detail}, path={relative_path}"
        super().__init__(f"Workspace path denied ({detail})")


class WorkspacePathPolicy:
    def __init__(self, workspace_root: Path) -> None:
        expanded_root = workspace_root.expanduser()
        if expanded_root.is_symlink() or not expanded_root.is_dir():
            raise PathPolicyError("workspace")
        self.workspace_root = expanded_root.resolve(strict=True)

    def resolve_for_read(self, scope: str, relative_path: str) -> Path:
        scope_root, parts = self._resolve_scope_and_parts(scope, relative_path)
        target = self._walk_existing(scope, relative_path, scope_root, parts)
        if not target.is_file():
            raise PathPolicyError(scope, relative_path)
        return target.resolve(strict=True)

    def scope_root(self, scope: str) -> Path:
        """Return the resolved directory for a scope, validating it is a real
        directory inside the workspace. Used to create safe subdirectories."""
        scope_relative = SCOPE_PATHS.get(scope)
        if scope_relative is None:
            raise PathPolicyError(scope)
        root = self._walk_existing(
            scope, None, self.workspace_root, scope_relative.parts
        )
        if not root.is_dir():
            raise PathPolicyError(scope)
        self._assert_within(
            scope, None, self.workspace_root, root.resolve(strict=True)
        )
        return root

    def resolve_for_create(self, scope: str, relative_path: str) -> Path:
        scope_root, parts = self._resolve_scope_and_parts(scope, relative_path)
        parent_parts = parts[:-1]
        parent = self._walk_existing(
            scope, relative_path, scope_root, parent_parts
        )
        if not parent.is_dir():
            raise PathPolicyError(scope, relative_path)

        target = parent / parts[-1]
        if target.exists() or target.is_symlink():
            target_stat = target.lstat()
            if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISREG(target_stat.st_mode):
                raise PathPolicyError(scope, relative_path)

        self._assert_within(scope, relative_path, scope_root, parent.resolve(strict=True))
        return target

    def _resolve_scope_and_parts(
        self, scope: str, relative_path: str
    ) -> tuple[Path, tuple[str, ...]]:
        scope_relative = SCOPE_PATHS.get(scope)
        if scope_relative is None:
            raise PathPolicyError(scope)

        parts = self._validate_relative_path(scope, relative_path)
        scope_root = self._walk_existing(
            scope,
            None,
            self.workspace_root,
            scope_relative.parts,
        )
        if not scope_root.is_dir():
            raise PathPolicyError(scope)
        self._assert_within(scope, None, self.workspace_root, scope_root.resolve(strict=True))
        return scope_root, parts

    @staticmethod
    def _validate_relative_path(scope: str, relative_path: str) -> tuple[str, ...]:
        if (
            not relative_path
            or "\x00" in relative_path
            or Path(relative_path).is_absolute()
            or PureWindowsPath(relative_path).is_absolute()
        ):
            raise PathPolicyError(scope)

        parts = tuple(relative_path.split("/"))
        if any(part in {"", ".", ".."} for part in parts):
            raise PathPolicyError(scope)
        return parts

    def _walk_existing(
        self,
        scope: str,
        relative_path: str | None,
        start: Path,
        parts: tuple[str, ...],
    ) -> Path:
        current = start
        for part in parts:
            current = current / part
            try:
                current_stat = current.lstat()
            except (FileNotFoundError, NotADirectoryError, OSError) as error:
                raise PathPolicyError(scope, relative_path) from error
            if stat.S_ISLNK(current_stat.st_mode):
                raise PathPolicyError(scope, relative_path)
        return current

    @staticmethod
    def _assert_within(
        scope: str,
        relative_path: str | None,
        root: Path,
        target: Path,
    ) -> None:
        if target != root and root not in target.parents:
            raise PathPolicyError(scope, relative_path)
