from fastapi.testclient import TestClient

from app.main import app


def test_run_review_returns_evaluation_and_report() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/review/run",
        json={
            "questions": [
                {
                    "id": "q1",
                    "title": "SQL 注入",
                    "questionText": "SQL 注入是什么？",
                    "referenceAnswer": "使用参数化查询防止拼接 SQL。",
                    "topics": ["web_security"],
                    "difficulty": "medium",
                    "keyPoints": ["参数化查询", "拼接 SQL"],
                    "followUps": [],
                    "mastery": "weak",
                }
            ],
            "settings": {
                "selectedTopics": [],
                "questionCount": 1,
                "mode": "weak-point",
            },
            "userAnswer": "使用参数化查询",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["evaluation"]["score"] == "partial"
    assert body["evaluation"]["missing_key_points"] == ["拼接 SQL"]
    assert "status: review_pending" in body["report_markdown"]
