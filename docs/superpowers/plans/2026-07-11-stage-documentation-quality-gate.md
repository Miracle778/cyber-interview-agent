# 阶段文档质量门禁实施计划

> **面向执行 Agent：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐项执行本计划。步骤使用复选框（`- [ ]`）跟踪。

**目标：** 将 verification 用户指南和 learning 七件套的结构要求固化为仓库规则、正式模板和可执行本地门禁。

**架构：** `scripts/check_stage_docs.py` 只读取指定的 verification 文件和 learning 目录，使用确定性规则返回成功或逐项错误。详细规范写入双轨工作流，AGENTS/CLAUDE 只保留强制入口；模板定义内容职责，人工对照负责机器无法判断的深度。

**技术栈：** Python 3 标准库、unittest、Markdown、Git。

## 全局约束

- `docs/verification/` 与 `docs/learning/` 继续由 Git 忽略，不得暂存或提交。
- 正式规则、模板、脚本和测试进入 Git。
- 门禁只读，不访问网络、不修改阶段文档。
- 不用固定字数或行数判断内容质量。
- 用户 learning 练习不阻塞产品开发；只要求掌握材料齐全。
- `progress.md` 保存开发流水账，最终 verification 不能以 Task 进度表为主体。

---

## 文件结构

新建：

- `scripts/check_stage_docs.py`：CLI、结构检查和错误输出。
- `scripts/test_check_stage_docs.py`：标准库 unittest 回归。
- `docs/superpowers/templates/stage-verification-template.md`：最终验证指南模板。
- `docs/superpowers/templates/stage-learning-pack-template.md`：七件套职责与章节模板。

修改：

- `docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`：详细权威规则。
- `AGENTS.md`：Codex/兼容 Agent 强制入口。
- `CLAUDE.md`：Claude Code 强制入口。
- `docs/superpowers/plans/2026-07-10-r1-4-persistent-hitl.md`：R1.4 最终 Task 接入门禁。
- `task_plan.md`、`findings.md`、`progress.md`：记录门禁落地与下一阶段状态。

### Task 1：文档门禁失败测试

**文件：**

- 新建：`scripts/test_check_stage_docs.py`

**接口：**

- 测试期望 `scripts/check_stage_docs.py` 支持 `--verification PATH --learning DIR`。
- 进程成功返回 `0`，失败返回 `1` 并把逐项原因写入 stderr。

- [ ] **步骤 1：编写失败测试**

使用 `tempfile.TemporaryDirectory()` 创建完整和缺陷样例。通过 `subprocess.run()` 调用仓库脚本，至少覆盖：

```python
def test_complete_stage_docs_pass(self):
    result = self.run_gate(valid_verification(), valid_learning_files())
    self.assertEqual(result.returncode, 0, result.stderr)


def test_task_log_verification_fails(self):
    result = self.run_gate("# R1\n\n## Task 进度\n\n### Task 1\n完成", valid_learning_files())
    self.assertEqual(result.returncode, 1)
    self.assertIn("最终用户验证指南", result.stderr)


def test_readme_only_learning_fails(self):
    result = self.run_gate(valid_verification(), {"README.md": "# learning"})
    self.assertEqual(result.returncode, 1)
    self.assertIn("overview.md", result.stderr)
```

完整样例必须包含五个 verification 章节、shell 命令块、编号人工步骤，以及七个 learning 文件要求的最小真实标题。

- [ ] **步骤 2：运行测试确认 RED**

```bash
python3 scripts/test_check_stage_docs.py
```

预期：FAIL，错误为 `scripts/check_stage_docs.py` 不存在。

- [ ] **步骤 3：确认测试自身质量**

检查每个失败样例只破坏一个要求；占位符、缺文件、缺章节和 Task 流水账分别有独立测试，不能用同一个全坏样例代替。

- [ ] **步骤 4：暂不提交**

Task 1 与实现共同形成完整 RED/GREEN 交付，测试在 Task 2 GREEN 后提交。

### Task 2：实现只读检查器

**文件：**

- 新建：`scripts/check_stage_docs.py`
- 修改：`scripts/test_check_stage_docs.py`

**接口：**

```python
@dataclass(frozen=True)
class CheckIssue:
    path: Path
    message: str


def check_verification(path: Path) -> list[CheckIssue]: ...
def check_learning(directory: Path) -> list[CheckIssue]: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

- [ ] **步骤 1：实现 verification 检查**

固定要求：

```python
VERIFICATION_HEADINGS = (
    "## 这次实现了什么",
    "## 代码地图",
    "## 自动验证",
    "## 人工验证",
    "## 当前边界",
)
PLACEHOLDERS = ("TODO", "TBD", "待补充", "待完善")
```

要求文件存在、非空、包含全部标题、至少一个 `bash`/`shell` 代码围栏、人工验证部分至少有一个 `### 1.` 或 `1.` 步骤，并拒绝以 `## Task 进度` 为主体的最终文档。

- [ ] **步骤 2：实现 learning 检查**

固定文件：

```python
LEARNING_FILES = (
    "overview.md",
    "architecture.md",
    "code-walkthrough.md",
    "failure-journal.md",
    "interview-questions.md",
    "presentation-script.md",
    "exercises.md",
)
```

对每个文件检查存在、非空、占位符和专属标题。`README.md` 不计入七件套；缺少任何固定文件都失败。

- [ ] **步骤 3：实现 CLI 和稳定输出**

```text
Stage documentation gate passed
  verification: <path>
  learning: <dir> (7 files)
```

失败时每行格式固定为：

```text
<path>: <reason>
```

按路径和消息排序后写入 stderr，返回 `1`。

- [ ] **步骤 4：运行测试确认 GREEN 并提交**

```bash
python3 scripts/test_check_stage_docs.py
git diff --check
```

预期：全部 unittest 通过，diff check 通过。

```bash
git add scripts/check_stage_docs.py scripts/test_check_stage_docs.py
git commit -m "feat(docs): validate stage documentation packs"
```

### Task 3：正式模板与仓库规则

**文件：**

- 新建：`docs/superpowers/templates/stage-verification-template.md`
- 新建：`docs/superpowers/templates/stage-learning-pack-template.md`
- 修改：`docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`
- 修改：`AGENTS.md`
- 修改：`CLAUDE.md`

**接口：**

- 详细规则只在双轨工作流维护。
- AGENTS/CLAUDE 提供相同命令入口和不可绕过的阶段关闭条件。

- [ ] **步骤 1：编写 verification 模板**

模板固定五个二级章节，并在“人工验证”中提供启动、准备数据、主流程、重复/刷新、持久化检查的编号结构。模板明确：开发中 Task 证据先写入 progress 或临时段，阶段结束必须整理，不能原样交付 Task 日志。

- [ ] **步骤 2：编写 learning 模板**

在一份正式模板中列出七个目标文件、每份必需章节、必须回答的问题和禁止使用的通用填充内容。明确 failure journal 只记录真实故障，exercises 必须有非阻塞降级形式。

- [ ] **步骤 3：更新权威工作流和 Agent 入口**

双轨工作流补充“机器门禁负责不能缺，人工门禁负责不能空”。AGENTS 和 CLAUDE 加入：

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/<stage>.md \
  --learning docs/learning/<stage>/
```

阶段关闭前必须对照上一阶段同类型文档，并在最终汇报记录门禁结果。

- [ ] **步骤 4：验证规则一致性并提交**

```bash
rg -n "check_stage_docs|最终用户验证指南|七件套" AGENTS.md CLAUDE.md docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md docs/superpowers/templates
git diff --check
```

```bash
git add AGENTS.md CLAUDE.md docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md docs/superpowers/templates
git commit -m "docs: require stage documentation quality gate"
```

### Task 4：接入 R1.4 并验证真实 R1.3 文档

**文件：**

- 修改：`docs/superpowers/plans/2026-07-10-r1-4-persistent-hitl.md`
- 修改：`task_plan.md`
- 修改：`findings.md`
- 修改：`progress.md`
- 本地验证：`docs/verification/r1_3_workspace_tool_security.md`
- 本地验证：`docs/learning/r1-3-tool-security/`

**接口：**

- R1.4 最终 Task 在产品测试与浏览器验收后运行文档门禁。
- 门禁通过不代表用户已完成 learning 练习。

- [ ] **步骤 1：更新 R1.4 最终关闭步骤**

在 Task 5 增加：使用正式模板整理 verification、生成七件套、对照 R1.3 文档、运行检查器、记录结果。门禁失败时不能将 R1.4 标为“可人工验证”。

- [ ] **步骤 2：运行真实 R1.3 门禁**

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/r1_3_workspace_tool_security.md \
  --learning docs/learning/r1-3-tool-security/
```

预期：通过并报告 7 个 learning 文件。

- [ ] **步骤 3：更新项目记录**

记录本次根因：存在性检查不能替代文档类型和结构检查；后续阶段以模板、脚本和人工对照三重门禁关闭。保持 R1.4 为下一产品任务。

- [ ] **步骤 4：最终验证并提交**

```bash
python3 scripts/test_check_stage_docs.py
python3 scripts/check_stage_docs.py --verification docs/verification/r1_3_workspace_tool_security.md --learning docs/learning/r1-3-tool-security/
git diff --check
git status --short
```

确认 `docs/verification/`、`docs/learning/` 仍被忽略，只提交正式计划和项目记录：

```bash
git add docs/superpowers/plans/2026-07-10-r1-4-persistent-hitl.md docs/superpowers/plans/2026-07-11-stage-documentation-quality-gate.md task_plan.md findings.md progress.md
git commit -m "docs: apply stage documentation gate to R1.4"
```

## 最终验收

- 检查器测试覆盖成功、缺章节、Task 日志、缺文件、README-only 和占位符。
- R1.3 当前 verification 与 learning 七件套通过真实门禁。
- AGENTS、CLAUDE、双轨工作流和模板表达同一关闭规则。
- R1.4 最终 Task 明确运行门禁。
- 本地文档继续被忽略，正式规则、模板、脚本、测试和计划均已提交。
