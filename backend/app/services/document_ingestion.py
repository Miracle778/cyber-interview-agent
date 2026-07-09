from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader

from app.schemas.review import ReviewQuestion

def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")

def create_question_draft(text: str) -> ReviewQuestion:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "未命名问题")
    return ReviewQuestion(
        id=f"q_{uuid4().hex[:12]}",
        title=first_line[:60],
        questionText=first_line,
        referenceAnswer=text[:1200],
        topics=["uncategorized"],
        difficulty="medium",
        keyPoints=[first_line[:80]],
        followUps=[],
        mastery="unknown",
    )
