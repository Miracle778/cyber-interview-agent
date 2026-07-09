from app.agents.review_graph import build_review_graph
from app.schemas.review import ReviewQuestion, ReviewRoundSettings

def test_review_graph_generates_report() -> None:
    graph = build_review_graph()
    question = ReviewQuestion(
        id="q1",
        title="SQL 注入",
        questionText="SQL 注入是什么？",
        referenceAnswer="使用参数化查询防止拼接 SQL。",
        topics=["web_security"],
        difficulty="medium",
        keyPoints=["参数化查询", "拼接 SQL"],
        followUps=[],
        mastery="weak",
    )
    settings = ReviewRoundSettings(selectedTopics=[], questionCount=1, mode="weak-point")
    result = graph.invoke({"questions": [question], "settings": settings, "user_answer": "使用参数化查询"})
    assert result["evaluation"]["score"] == "partial"
    assert "status: review_pending" in result["report_markdown"]
