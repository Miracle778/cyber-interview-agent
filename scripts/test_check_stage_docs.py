from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CHECKER = Path(__file__).with_name("check_stage_docs.py")


def valid_verification() -> str:
    return """# R1.3 验证指南

## 这次实现了什么

实现了受限工具与安全诊断。

## 代码地图

- `backend/app.py`：API 入口。

## 自动验证

```bash
python3 -m unittest
```

## 人工验证

### 1. 启动服务

运行启动命令并打开页面。

## 当前边界

当前仅支持本地 Workspace。
"""


def valid_learning_files(profile: str = "foundation") -> dict[str, str]:
    return {
        "overview.md": """# 学习入口

## 学习基线
先理解 Agent Runtime。

## 学习档案

- 类型：`%s`
- 风险驱动：
  - 持久化状态必须跨进程恢复；
  - 不可信输入不能获得运行权限。

## 本阶段解决的问题
限制工具访问范围。

## 如何使用本掌握包
按架构、链路、练习顺序阅读。

## 当前边界
仅覆盖本地工具。

## 掌握标准
能够独立解释安全链路。
""" % profile,
        "architecture.md": """# 架构

## 总体结构
API、Runtime 和工具层逐层约束访问。

## 组件职责
API 接收命令，Runtime 注入可信上下文，工具层执行受限操作。

## 状态所有权
Runtime 数据库拥有运行事实，前端缓存只负责展示。

## 信任与一致性边界
工作区身份和权限由 Runtime 注入，模型输入不可信。

## 关键设计取舍
采用后端强制策略，而不是依赖前端隐藏危险入口。
""",
        "code-walkthrough.md": """# 代码走读

## 链路一：工具调用
请求从 `backend/app/api.py` 进入 Runtime，再到工具适配器；Registry 拒绝越权分支，最终页面显示稳定错误码。

## 链路二：刷新恢复
页面从 `frontend/src/api.ts` 读取数据库事实；SSE 只触发刷新，最终展示持久化状态。
""",
        "failure-journal.md": """# 故障日志

## 路径校验遗漏
现象：测试发现符号链接可以越界。
错误假设：词法路径检查足够。
根因：真实路径可能经过符号链接逃逸。
修正：逐组件拒绝符号链接。
验证证据：路径安全回归测试通过。
提前发现：在设计阶段列出路径攻击矩阵。
""",
        "interview-questions.md": """# 面试自测

### 为什么要在后端校验路径？
前端输入不可信，后端才是安全边界。

### 状态由谁拥有？
数据库拥有运行事实。

### 服务重启后怎样恢复？
从持久化状态恢复，而不是依赖内存任务。

### 失败时怎样避免泄密？
只暴露稳定错误码。

### 怎样证明边界生效？
运行拒绝路径和重启恢复测试。
""",
        "presentation-script.md": """# 项目表达

## 3 分钟版本
介绍问题、方案和验证结果。

## 10 分钟讲解提纲
展开架构、关键链路、权衡和边界。
""",
        "exercises.md": """# 练习

## 主练习
完成 Trace 和 Review：追踪一次受限操作并审阅权限来源。证据保存为流程图和测试记录。

## 降级形式
只画调用链并标出安全边界。

## 练习状态
尚未开始，不阻塞产品开发。
""",
    }


class StageDocumentationGateTests(unittest.TestCase):
    def run_gate(
        self,
        verification: str,
        learning_files: dict[str, str],
        plan: str = "- [x] 浏览器和重启验收\n",
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            verification_path = root / "verification.md"
            learning_path = root / "learning"
            plan_path = root / "plan.md"
            verification_path.write_text(verification, encoding="utf-8")
            plan_path.write_text(plan, encoding="utf-8")
            learning_path.mkdir()
            for name, content in learning_files.items():
                (learning_path / name).write_text(content, encoding="utf-8")

            return subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--verification",
                    str(verification_path),
                    "--learning",
                    str(learning_path),
                    "--plan",
                    str(plan_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_complete_stage_docs_pass(self) -> None:
        result = self.run_gate(valid_verification(), valid_learning_files())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Stage documentation gate passed", result.stdout)
        self.assertIn("7 files", result.stdout)

    def test_missing_verification_heading_fails(self) -> None:
        verification = valid_verification().replace("## 代码地图", "## 文件说明")

        result = self.run_gate(verification, valid_learning_files())

        self.assertEqual(result.returncode, 1)
        self.assertIn("verification.md", result.stderr)
        self.assertIn("## 代码地图", result.stderr)

    def test_task_log_verification_fails(self) -> None:
        verification = valid_verification() + "\n## Task 进度\n\n### Task 1\n完成\n"

        result = self.run_gate(verification, valid_learning_files())

        self.assertEqual(result.returncode, 1)
        self.assertIn("最终用户验证指南", result.stderr)

    def test_missing_learning_file_fails(self) -> None:
        learning = valid_learning_files()
        del learning["architecture.md"]

        result = self.run_gate(valid_verification(), learning)

        self.assertEqual(result.returncode, 1)
        self.assertIn("architecture.md", result.stderr)

    def test_readme_only_learning_fails(self) -> None:
        result = self.run_gate(
            valid_verification(),
            {"README.md": "# learning\n"},
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("overview.md", result.stderr)
        self.assertIn("exercises.md", result.stderr)

    def test_placeholder_in_learning_fails(self) -> None:
        learning = valid_learning_files()
        learning["architecture.md"] += "\n待完善\n"

        result = self.run_gate(valid_verification(), learning)

        self.assertEqual(result.returncode, 1)
        self.assertIn("architecture.md", result.stderr)
        self.assertIn("占位符", result.stderr)

    def test_todo_candidate_is_not_a_placeholder(self) -> None:
        learning = valid_learning_files()
        learning["architecture.md"] += (
            "\nTodoCandidate 是稳定契约，正式 Todo Service 属于后续阶段。\n"
        )

        result = self.run_gate(valid_verification(), learning)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_or_unknown_learning_profile_fails(self) -> None:
        missing = valid_learning_files()
        missing["overview.md"] = missing["overview.md"].replace(
            "- 类型：`foundation`\n", ""
        )
        unknown = valid_learning_files("tutorial")

        missing_result = self.run_gate(valid_verification(), missing)
        unknown_result = self.run_gate(valid_verification(), unknown)

        self.assertEqual(missing_result.returncode, 1)
        self.assertIn("学习档案类型", missing_result.stderr)
        self.assertEqual(unknown_result.returncode, 1)
        self.assertIn("tutorial", unknown_result.stderr)

    def test_foundation_requires_two_risk_drivers(self) -> None:
        learning = valid_learning_files()
        learning["overview.md"] = learning["overview.md"].replace(
            "  - 不可信输入不能获得运行权限。\n", ""
        )

        result = self.run_gate(valid_verification(), learning)

        self.assertEqual(result.returncode, 1)
        self.assertIn("至少两个阶段特有风险驱动", result.stderr)

    def test_foundation_requires_five_architecture_sections(self) -> None:
        learning = valid_learning_files()
        learning["architecture.md"] = learning["architecture.md"].replace(
            "## 状态所有权", "## 数据说明"
        )

        result = self.run_gate(valid_verification(), learning)

        self.assertEqual(result.returncode, 1)
        self.assertIn("## 状态所有权", result.stderr)

    def test_foundation_requires_two_code_chains(self) -> None:
        learning = valid_learning_files()
        learning["code-walkthrough.md"] = learning["code-walkthrough.md"].replace(
            "## 链路二：刷新恢复", "## 补充说明"
        )

        result = self.run_gate(valid_verification(), learning)

        self.assertEqual(result.returncode, 1)
        self.assertIn("至少需要 2 条", result.stderr)

    def test_foundation_requires_five_interview_questions(self) -> None:
        learning = valid_learning_files()
        learning["interview-questions.md"] = learning["interview-questions.md"].replace(
            "### 怎样证明边界生效？", "## 验证说明"
        )

        result = self.run_gate(valid_verification(), learning)

        self.assertEqual(result.returncode, 1)
        self.assertIn("至少需要 5 道", result.stderr)

    def test_failure_journal_requires_evidence_shape(self) -> None:
        learning = valid_learning_files()
        learning["failure-journal.md"] = """# 故障日志

## 路径校验遗漏
测试有问题，后来修好了。
"""

        result = self.run_gate(valid_verification(), learning)

        self.assertEqual(result.returncode, 1)
        self.assertIn("现象、错误假设、根因、修正、验证证据和提前发现", result.stderr)

    def test_experience_profile_accepts_one_chain_and_three_questions(self) -> None:
        learning = valid_learning_files("experience")
        learning["code-walkthrough.md"] = learning["code-walkthrough.md"].split(
            "## 链路二：刷新恢复"
        )[0]
        questions = learning["interview-questions.md"].splitlines()
        kept_questions = []
        question_count = 0
        for line in questions:
            if line.startswith("### "):
                question_count += 1
            if question_count <= 3:
                kept_questions.append(line)
        learning["interview-questions.md"] = "\n".join(kept_questions)

        result = self.run_gate(valid_verification(), learning)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unchecked_browser_plan_blocks_stage_closure(self) -> None:
        result = self.run_gate(
            valid_verification(),
            valid_learning_files(),
            plan="- [ ] 浏览器和重启验收\n",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("浏览器验收尚未完成", result.stderr)

    def test_browser_claim_conflicting_with_plan_fails(self) -> None:
        verification = valid_verification().replace(
            "运行启动命令并打开页面。",
            "浏览器验收已经完成并通过。",
        )
        result = self.run_gate(
            verification,
            valid_learning_files(),
            plan="- [ ] 浏览器和重启验收\n",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("verification 声称浏览器已通过", result.stderr)


if __name__ == "__main__":
    unittest.main()
