from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from enum import Enum
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
ARCHITECTURE_HEADINGS = (
    "## 总体结构",
    "## 组件职责",
    "## 状态所有权",
    "## 信任与一致性边界",
    "## 关键设计取舍",
)


class LearningProfile(str, Enum):
    FOUNDATION = "foundation"
    STATEFUL = "stateful"
    INTEGRATION = "integration"
    EXPERIENCE = "experience"


PROFILE_MINIMUMS = {
    LearningProfile.FOUNDATION: (2, 5),
    LearningProfile.STATEFUL: (2, 5),
    LearningProfile.INTEGRATION: (2, 5),
    LearningProfile.EXPERIENCE: (1, 3),
}


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
    issues: list[CheckIssue] = []
    for placeholder in PLACEHOLDERS:
        if placeholder.isascii():
            found = re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(placeholder)}(?![A-Za-z0-9_])",
                text,
            )
        else:
            found = placeholder in text
        if found:
            issues.append(CheckIssue(path, f"包含未完成占位符：{placeholder}"))
    return issues


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


def check_plan(path: Path, verification_text: str) -> list[CheckIssue]:
    text, issues = _read_text(path)
    if text is None:
        return issues

    browser_step = re.search(
        r"^- \[([ xX])\].*(?:浏览器|browser).*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if browser_step is None:
        issues.append(CheckIssue(path, "实施计划缺少浏览器验收复选项"))
    elif browser_step.group(1).strip().lower() != "x":
        issues.append(CheckIssue(path, "浏览器验收尚未完成，不能关闭阶段"))

    claims_browser_passed = bool(
        re.search(
            r"浏览器(?:验收|验证).{0,12}(?:通过|完成|覆盖)",
            verification_text,
            re.IGNORECASE,
        )
    )
    if browser_step is not None and browser_step.group(1).strip().lower() != "x" and claims_browser_passed:
        issues.append(CheckIssue(path, "verification 声称浏览器已通过，但计划仍未勾选"))
    return issues


def parse_learning_profile(
    path: Path, text: str
) -> tuple[LearningProfile | None, list[CheckIssue]]:
    issues: list[CheckIssue] = []
    profile_match = re.search(r"^- 类型：`([^`]+)`\s*$", text, re.MULTILINE)
    if profile_match is None:
        return None, [CheckIssue(path, "缺少固定学习档案类型声明")]

    raw_profile = profile_match.group(1)
    try:
        profile = LearningProfile(raw_profile)
    except ValueError:
        supported = ", ".join(item.value for item in LearningProfile)
        return None, [
            CheckIssue(path, f"未知学习档案类型 `{raw_profile}`；可选值：{supported}")
        ]

    profile_section = re.search(
        r"^## 学习档案\s*$([\s\S]*?)(?=^##\s|\Z)", text, re.MULTILINE
    )
    risk_drivers = []
    if profile_section is not None:
        risk_block = re.search(
            r"^- 风险驱动：\s*$([\s\S]*?)(?=^- \S|\Z)",
            profile_section.group(1),
            re.MULTILINE,
        )
        if risk_block is not None:
            risk_drivers = re.findall(
                r"^  - \S.+$", risk_block.group(1), re.MULTILINE
            )
    if len(risk_drivers) < 2:
        issues.append(CheckIssue(path, "学习档案至少两个阶段特有风险驱动"))
    return profile, issues


def _check_learning_structure(
    path: Path,
    name: str,
    text: str,
    profile: LearningProfile | None,
) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    for heading in LEARNING_REQUIREMENTS.get(name, ()):
        if heading not in text:
            issues.append(CheckIssue(path, f"缺少必需内容：{heading}"))

    if name == "architecture.md":
        for heading in ARCHITECTURE_HEADINGS:
            if not re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE):
                issues.append(CheckIssue(path, f"缺少必需内容：{heading}"))
    elif name == "code-walkthrough.md":
        chain_count = len(re.findall(r"^## 链路\S*", text, re.MULTILINE))
        minimum = PROFILE_MINIMUMS.get(profile, (1, 1))[0]
        if chain_count < minimum:
            issues.append(
                CheckIssue(path, f"当前学习档案至少需要 {minimum} 条真实代码链路")
            )
    elif name == "failure-journal.md":
        if not re.search(r"^## (?!简介|使用说明)\S.+$", text, re.MULTILINE):
            issues.append(CheckIssue(path, "至少需要一个真实故障的二级章节"))
        no_failure = "无真实故障" in text and "verification" in text.lower()
        evidence_terms = ("现象", "错误假设", "根因", "修正", "验证证据", "提前发现")
        if not no_failure and not all(term in text for term in evidence_terms):
            issues.append(
                CheckIssue(
                    path,
                    "故障日志必须包含现象、错误假设、根因、修正、验证证据和提前发现",
                )
            )
    elif name == "interview-questions.md":
        question_count = len(re.findall(r"^### \S.+$", text, re.MULTILINE))
        minimum = PROFILE_MINIMUMS.get(profile, (1, 1))[1]
        if question_count < minimum:
            issues.append(
                CheckIssue(path, f"当前学习档案至少需要 {minimum} 道三级标题自测题")
            )
    elif name == "exercises.md":
        capability_count = sum(
            term in text for term in ("Explain", "Trace", "Review", "Debug", "实现")
        )
        if "证据" not in text or capability_count < 2:
            issues.append(
                CheckIssue(path, "主练习必须要求所有权证据并覆盖至少两类能力")
            )

    return issues


def check_learning(directory: Path) -> list[CheckIssue]:
    if not directory.is_dir():
        return [CheckIssue(directory, "learning 目录不存在")]

    issues: list[CheckIssue] = []
    texts: dict[str, str] = {}
    for name in LEARNING_FILES:
        path = directory / name
        text, file_issues = _read_text(path)
        issues.extend(file_issues)
        if text is None:
            continue
        texts[name] = text
        issues.extend(_placeholder_issues(path, text))

    overview_path = directory / "overview.md"
    overview_text = texts.get("overview.md")
    profile: LearningProfile | None = None
    if overview_text is not None:
        profile, profile_issues = parse_learning_profile(overview_path, overview_text)
        issues.extend(profile_issues)

    for name, text in texts.items():
        issues.extend(
            _check_learning_structure(directory / name, name, text, profile)
        )
    return issues


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate stage documentation")
    parser.add_argument("--verification", required=True, type=Path)
    parser.add_argument("--learning", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    verification_text, read_issues = _read_text(args.verification)
    issues = read_issues
    if verification_text is not None:
        issues.extend(check_verification(args.verification))
        issues.extend(check_plan(args.plan, verification_text))
    issues.extend(check_learning(args.learning))
    if issues:
        for issue in sorted(issues, key=lambda item: (str(item.path), item.message)):
            print(f"{issue.path}: {issue.message}", file=sys.stderr)
        return 1

    print("Stage documentation gate passed")
    print(f"  verification: {args.verification}")
    print(f"  learning: {args.learning} ({len(LEARNING_FILES)} files)")
    print(f"  plan: {args.plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
