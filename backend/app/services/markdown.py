import frontmatter

from app.knowledge.frontmatter import PublishedDocument, render_published_document
from app.schemas.review import ReviewQuestion


__all__ = [
    "PublishedDocument",
    "render_published_document",
    "render_question_markdown",
]

def render_question_markdown(question: ReviewQuestion, status: str = "review_pending") -> str:
    post = frontmatter.Post(
        content=(
            f"# {question.title}\n\n"
            f"## 问题\n\n{question.question_text}\n\n"
            f"## 参考答案\n\n{question.reference_answer}\n\n"
            "## 关键得分点\n\n"
            + "\n".join(f"- {point}" for point in question.key_points)
        ),
        type="question",
        id=question.id,
        status=status,
        topics=question.topics,
        difficulty=question.difficulty,
        mastery=question.mastery,
    )
    return frontmatter.dumps(post)
