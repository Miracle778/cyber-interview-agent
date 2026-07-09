from pathlib import Path

VAULT_DIRS = [
    "00_inbox",
    "10_question_bank",
    "20_review_sessions",
    "30_mastery",
    "40_concepts",
    "80_manifests",
    "90_exports",
    ".cyber-interview-agent",
]

def initialize_vault(workspace: Path) -> Path:
    vault = workspace / "knowledge-vault"
    for dirname in VAULT_DIRS:
        (vault / dirname).mkdir(parents=True, exist_ok=True)
    return vault
