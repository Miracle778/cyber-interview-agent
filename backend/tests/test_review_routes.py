from fastapi.testclient import TestClient

from app.main import app


def test_legacy_review_bypass_routes_are_removed() -> None:
    client = TestClient(app)

    run = client.post("/api/review/run", json={})
    confirm = client.post("/api/review/reports/confirm", json={})

    assert run.status_code == 404
    assert confirm.status_code == 404
