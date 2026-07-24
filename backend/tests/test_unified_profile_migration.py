from __future__ import annotations

from pathlib import Path

from app.infrastructure.runtime_database import connect_runtime_database


def _columns(connection, table: str) -> set[str]:
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def test_unified_profile_schema_supports_sources_relations_and_presentation(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }

    assert {
        "profile_claim_sources",
        "profile_claim_relations",
        "profile_presentations",
    } <= tables
    assert {"source_kind", "source_ref_json"} <= _columns(
        connection, "profile_claim_proposals"
    )
    assert "deleted_at" in _columns(connection, "profile_claims")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_unified_profile_migration_preserves_existing_claims(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO profile_claims "
        "(id, workspace_id, claim_type, version) "
        "VALUES ('claim-1', 'w1', 'project', 1)"
    )
    connection.commit()

    row = connection.execute(
        "SELECT id, workspace_id, claim_type, version, deleted_at "
        "FROM profile_claims WHERE id = 'claim-1'"
    ).fetchone()
    assert tuple(row) == ("claim-1", "w1", "project", 1, None)
    connection.close()


def test_unified_profile_claim_types_accept_facts_and_presentation(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)

    for index, claim_type in enumerate(
        (
            "skill",
            "project",
            "experience",
            "education",
            "certification",
            "achievement",
            "link",
            "summary",
            "direction",
            "highlight",
        )
    ):
        connection.execute(
            "INSERT INTO profile_claims "
            "(id, workspace_id, claim_type, version) VALUES (?, 'w1', ?, 1)",
            (f"claim-{index}", claim_type),
        )
    connection.commit()

    assert connection.execute(
        "SELECT COUNT(*) FROM profile_claims WHERE workspace_id = 'w1'"
    ).fetchone()[0] == 10
    connection.close()
