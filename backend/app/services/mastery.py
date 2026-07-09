from pathlib import Path
from time import time_ns

def save_session_report(vault: Path, markdown: str) -> Path:
    report_dir = vault / "20_review_sessions"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"session_report_{time_ns()}.md"
    path.write_text(markdown, encoding="utf-8")
    return path

def build_global_mastery_update(report_markdown: str) -> str:
    return (
        "---\n"
        "type: mastery_report\n"
        "status: review_pending\n"
        "---\n\n"
        "# 全局掌握度更新建议\n\n"
        "## 本轮证据\n\n"
        f"{report_markdown[:1200]}\n"
    )
