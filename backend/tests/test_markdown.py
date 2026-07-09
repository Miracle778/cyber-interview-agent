import frontmatter

from app.schemas.review import ReviewQuestion
from app.services.markdown import render_question_markdown


def test_render_question_markdown_includes_frontmatter_and_body() -> None:
    question = ReviewQuestion(
        id="q1",
        title="SQL 注入",
        questionText="SQL 注入是什么？",
        referenceAnswer="使用参数化查询防止拼接 SQL。",
        topics=["web_security"],
        difficulty="medium",
        keyPoints=["参数化查询", "拼接 SQL"],
        followUps=[],
        mastery="unknown",
    )

    markdown = render_question_markdown(question)
    parsed = frontmatter.loads(markdown)

    assert parsed["type"] == "question"
    assert parsed["id"] == "q1"
    assert parsed["status"] == "review_pending"
    assert parsed["topics"] == ["web_security"]
    assert "# SQL 注入" in parsed.content
    assert "- 参数化查询" in parsed.content
