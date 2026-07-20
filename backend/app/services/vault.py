from pathlib import Path

from app.security.workspace_paths import PathPolicyError

VAULT_DIRS = [
    "00_inbox",
    "10_question_bank",
    "20_review_sessions",
    "30_mastery",
    "40_concepts",
    "50_profile",
    "80_manifests",
    "90_exports",
    ".cyber-interview-agent",
]

def initialize_vault(workspace: Path) -> Path:
    vault = workspace / "knowledge-vault"
    for path in (vault, *(vault / dirname for dirname in VAULT_DIRS)):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise PathPolicyError("knowledge.active")
        path.mkdir(parents=False, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise PathPolicyError("knowledge.active")
    return vault
