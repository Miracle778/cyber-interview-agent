from pathlib import Path

from app.services.vault import VAULT_DIRS, initialize_vault

def test_initialize_vault_creates_required_dirs(tmp_path: Path) -> None:
    vault = initialize_vault(tmp_path)
    for dirname in VAULT_DIRS:
        assert (vault / dirname).is_dir()
