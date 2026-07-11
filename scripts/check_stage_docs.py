from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


VERIFICATION_HEADINGS = (
    "## 这次实现了什么",
    "## 代码地图",
    "## 自动验证",
    "## 人工验证",
    "## 当前边界",
)
PLACEHOLDERS = ("TODO", "TBD", "待补充", "待完善")
LEARNING_REQUIREMENTS = {
    "overview.md": (
        "## 学习基线",
        "解决的问题",
        "## 如何使用本掌握包",
        "## 当前边界",
        "## 掌握标准",
    ),
    "architecture.md": ("## 总体结构",),
    "presentation-script.md": ("## 3 分钟版本", "## 10 分钟讲解提纲"),
    "exercises.md": ("## 主练习", "## 降级形式", "## 练习状态"),
}
LEARNING_FILES = (
    "overview.md",
    "architecture.md",
    "code-walkthrough.md",
    "failure-journal.md",
    "interview-questions.md",
    "presentation-script.md",
    "exercises.md",
)


@dataclass(frozen=True)
class CheckIssue:
    path: Path
    message: str


def _read_text(path: Path) -> tuple[str | None, list[CheckIssue]]:
    if not path.is_file():
        return None, [CheckIssue(path, "文件不存在")]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return None, [CheckIssue(path, f"无法读取 UTF-8 文档：{error}")]
    if not text.strip():
        return None, [CheckIssue(path, "文件为空")]
    return text, []


def _placeholder_issues(path: Path, text: str) -> list[CheckIssue]:
    upper_text = text.upper()
    return [
        CheckIssue(path, f"包含未完成占位符：{placeholder}")
        for placeholder in PLACEHOLDERS
        if placeholder.upper() in upper_text
    ]


def check_verification(path: Path) -> list[CheckIssue]:
    text, issues = _read_text(path)
    if text is None:
        return issues

    issues.extend(_placeholder_issues(path, text))
    for heading in VERIFICATION_HEADINGS:
        if not re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE):
            issues.append(CheckIssue(path, f"缺少固定章节：{heading}"))

    if not re.search(r"^```(?:bash|shell|sh)\s*$", text, re.MULTILINE | re.IGNORECASE):
        issues.append(CheckIssue(path, "自动验证必须包含 bash、shell 或 sh 命令围栏"))

    manual_match = re.search(
        r"^## 人工验证\s*$([\s\S]*?)(?=^##\s|\Z)",
        text,
        re.MULTILINE,
    )
    if manual_match and not re.search(
        r"^(?:###\s+)?1[.)]\s+\S",
        manual_match.group(1),
        re.MULTILINE,
    ):
        issues.append(CheckIssue(path, "人工验证章节至少需要一个从 1 开始的编号步骤"))

    if re.search(r"^## Task 进度\s*$", text, re.MULTILINE | re.IGNORECASE):
        issues.append(
            CheckIssue(path, "最终用户验证指南不能保留 `## Task 进度` 流水账章节")
        )

    return issues


def _check_learning_structure(path: Path, name: str, text: str) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    for heading in LEARNING_REQUIREMENTS.get(name, ()):
        if heading not in text:
            issues.append(CheckIssue(path, f"缺少必需内容：{heading}"))

    if name == "code-walkthrough.md" and not re.search(
        r"^## 链路\S*", text, re.MULTILINE
    ):
        issues.append(CheckIssue(path, "至少需要一个以 `## 链路` 开头的真实代码链路"))
    elif name == "failure-journal.md":
        if not re.search(r"^## (?!简介|使用说明)\S.+$", text, re.MULTILINE):
            issues.append(CheckIssue(path, "至少需要一个真实故障的二级章节"))
    elif name == "interview-questions.md" and not re.search(
        r"^### \S.+$", text, re.MULTILINE
    ):
        issues.append(CheckIssue(path, "至少需要一个三级标题形式的自测问题"))

    return issues


def check_learning(directory: Path) -> list[CheckIssue]:
    if not directory.is_dir():
        return [CheckIssue(directory, "learning 目录不存在")]

    issues: list[CheckIssue] = []
    for name in LEARNING_FILES:
        path = directory / name
        text, file_issues = _read_text(path)
        issues.extend(file_issues)
        if text is None:
            continue
        issues.extend(_placeholder_issues(path, text))
        issues.extend(_check_learning_structure(path, name, text))
    return issues


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate stage documentation")
    parser.add_argument("--verification", required=True, type=Path)
    parser.add_argument("--learning", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    issues = check_verification(args.verification) + check_learning(args.learning)
    if issues:
        for issue in sorted(issues, key=lambda item: (str(item.path), item.message)):
            print(f"{issue.path}: {issue.message}", file=sys.stderr)
        return 1

    print("Stage documentation gate passed")
    print(f"  verification: {args.verification}")
    print(f"  learning: {args.learning} ({len(LEARNING_FILES)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
