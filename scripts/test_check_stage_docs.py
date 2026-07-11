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


def valid_learning_files() -> dict[str, str]:
    return {
        "overview.md": """# 学习入口

## 学习基线
先理解 Agent Runtime。

## 本阶段解决的问题
限制工具访问范围。

## 如何使用本掌握包
按架构、链路、练习顺序阅读。

## 当前边界
仅覆盖本地工具。

## 掌握标准
能够独立解释安全链路。
""",
        "architecture.md": """# 架构

## 总体结构
API、Runtime 和工具层逐层约束访问。
""",
        "code-walkthrough.md": """# 代码走读

## 链路一：工具调用
请求从 API 进入 Runtime，再到工具适配器。
""",
        "failure-journal.md": """# 故障日志

## 路径校验遗漏
测试发现符号链接可以越界，修复后补充回归测试。
""",
        "interview-questions.md": """# 面试自测

### 为什么要在后端校验路径？
前端输入不可信，后端才是安全边界。
""",
        "presentation-script.md": """# 项目表达

## 3 分钟版本
介绍问题、方案和验证结果。

## 10 分钟讲解提纲
展开架构、关键链路、权衡和边界。
""",
        "exercises.md": """# 练习

## 主练习
为工具增加一种受限操作。

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
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            verification_path = root / "verification.md"
            learning_path = root / "learning"
            verification_path.write_text(verification, encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
