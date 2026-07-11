from app.db.connection import connect_index
from app.services.search_index import IndexedDocument, rescan_active_documents, search_documents, upsert_document

def test_search_documents(tmp_path):
    conn = connect_index(tmp_path / "index.sqlite")
    upsert_document(conn, IndexedDocument(
        id="q1",
        path="10_question_bank/q1.md",
        title="SQL 注入",
        type="question",
        status="ingested",
        body="SQL 注入 参数化查询",
    ))
    assert search_documents(conn, "SQL") == ["q1"]


def test_rescan_indexes_only_confirmed_ingested_documents(tmp_path):
    vault = tmp_path / "knowledge-vault"
    directory = vault / "10_question_bank"
    directory.mkdir(parents=True)
    (vault / ".cyber-interview-agent").mkdir()
    (directory / "active.md").write_text("---\nid: q1\ntype: question\nstatus: ingested\ntitle: Active\ningestion:\n  confirmed_by_user: true\n---\nSQL active", encoding="utf-8")
    (directory / "draft.md").write_text("---\nid: q2\ntype: question\nstatus: draft\ntitle: Draft\n---\nSQL draft", encoding="utf-8")
    (directory / "invalid.md").write_text("---\n: invalid: yaml\n---\nSQL invalid", encoding="utf-8")
    conn = connect_index(vault / ".cyber-interview-agent/index.sqlite")

    result = rescan_active_documents(conn, vault)

    assert result == {"indexed": 1, "skipped": 2}
    assert search_documents(conn, "SQL") == ["q1"]
