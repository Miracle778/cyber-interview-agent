from app.db.connection import connect_index
from app.services.search_index import IndexedDocument, search_documents, upsert_document

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
