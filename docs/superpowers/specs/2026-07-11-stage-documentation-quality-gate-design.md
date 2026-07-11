# 阶段文档质量门禁设计

## 1. 背景

双轨工作流已经要求每个产品切片维护 verification 文档，并在阶段结束生成七份 learning 掌握包。但现有规则只约束文件位置、增量更新和文件名，没有明确区分开发流水账与最终交付指南，也没有可执行检查。

R1.3 因此出现两个问题：

- verification 最终仍是按 Task 排列的开发记录，不能直接指导用户理解和人工验收；
- learning 只有一份简略 README，没有沿用 R1.2 已建立的七件套结构。

本设计把阶段文档要求固化为仓库规则、正式模板和本地可执行门禁，避免依赖单次会话记忆。

## 2. 目标

- 明确 `progress.md`、verification 和 learning 的不同职责。
- 为 verification 与 learning 提供唯一正式模板。
- 在阶段关闭前用脚本检查结构、必要内容和明显空壳。
- 让 Codex、Claude、新会话和上下文压缩后恢复同一规则。
- 保持 `docs/verification/` 与 `docs/learning/` 本地忽略，不改变现有提交边界。

## 3. 不做什么

- 不把本地 verification 或 learning 纳入 Git。
- 不用固定行数或字数冒充内容质量。
- 不让机器脚本判断架构解释是否“足够好”。
- 不改写已经验收完成的历史 R1.1/R1.2 文档。
- 不让 learning 练习阻塞后续产品开发；门禁只要求掌握材料齐全，不要求用户已经完成练习。

## 4. 文档职责

### 4.1 progress.md

保存开发过程事实：Task 状态、测试数字、失败尝试、提交和待办。它是开发流水账的唯一正式位置。

### 4.2 Verification

开发中仍需按 Task 增量记录证据，防止信息丢失。阶段结束时必须整理为用户验证指南，固定包含：

1. 这次实现了什么；
2. 代码地图；
3. 自动验证；
4. 逐步人工验证；
5. 当前边界。

最终文档不能以 Task 进度表作为主体。真实故障可以保留，但应放入相关验证步骤、风险说明或 learning failure journal。

### 4.3 Learning 掌握包

每个主要切片固定生成：

```text
overview.md
architecture.md
code-walkthrough.md
failure-journal.md
interview-questions.md
presentation-script.md
exercises.md
```

七份文件分别承担学习入口、架构、真实代码链路、真实故障、自测、项目表达和非阻塞实践。单个 README 不能替代掌握包。

## 5. 正式模板

新增：

- `docs/superpowers/templates/stage-verification-template.md`
- `docs/superpowers/templates/stage-learning-pack-template.md`

模板说明每个章节的受众、必须回答的问题和不能出现的内容。新阶段先复制模板，再结合最终代码和真实开发记录填写。

模板本身允许说明性占位符；质量门禁只扫描实际阶段文档，不扫描模板。

## 6. 可执行门禁

新增标准库 Python 脚本：

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/<stage>.md \
  --learning docs/learning/<stage>/
```

脚本不访问网络，不写文件，失败返回非零退出码。

### 6.1 Verification 检查

- 文件存在且非空；
- 包含五个固定二级章节；
- 包含至少一个 shell 命令块；
- 包含可操作的编号步骤；
- 不包含 `TODO`、`TBD`、`待补充`、`待完善`；
- 不以 `Task 进度` 或纯 Task 列表作为最终主体。

### 6.2 Learning 检查

- 七个固定文件全部存在且非空；
- `overview.md` 包含学习基线、阶段问题、使用方式、边界和掌握标准；
- `architecture.md` 包含总体结构；
- `code-walkthrough.md` 至少包含一条真实链路；
- `failure-journal.md` 至少包含一条真实故障；
- `interview-questions.md` 至少包含一个三级问题；
- `presentation-script.md` 包含 3 分钟和 10 分钟版本；
- `exercises.md` 包含主练习、降级形式和练习状态；
- 所有文件不包含明显占位符；
- 单 README 或缺少任一文件都失败。

### 6.3 输出

成功时打印 verification 和 learning 的检查摘要。失败时逐条输出文件和缺失要求，方便 Agent 修正，不输出文档正文。

## 7. 人工内容门禁

脚本通过后，负责交付的 Codex 仍必须人工确认：

- 对照上一阶段同类型文档，结构和内容深度没有明显退化；
- 代码地图指向最终代码，而不是计划中的文件；
- 自动测试数字来自最新真实输出；
- 人工步骤可以由用户从零执行；
- failure journal 只写真实发生的问题；
- learning 能支持 Explain、Trace、Review、Debug 或实现练习；
- 产品成熟度和用户掌握度分开陈述。

机器门禁负责“不能缺”，人工门禁负责“不能空”。

## 8. 仓库规则接入

更新：

- `docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`：作为详细权威来源加入最终整理和质量门禁。
- `AGENTS.md`：加入阶段关闭前必须使用模板、运行脚本和人工对照的简要强制规则。
- `CLAUDE.md`：同步同一入口要求，Claude 不能自行降低文档结构。
- 当前下一阶段 R1.4 实施计划：最终 Task 明确运行门禁并记录结果。

后续新实施计划必须在最终 Task 包含相同关闭步骤。

## 9. 测试

新增 `scripts/test_check_stage_docs.py`，使用 Python 标准库 `unittest` 和临时目录覆盖：

- 完整 verification + 七件套通过；
- 缺少 verification 章节失败；
- Task 流水账形态失败；
- 缺少任一 learning 文件失败；
- README-only learning 失败；
- 占位符失败；
- 失败输出包含具体文件和原因。

最终验证：

```bash
python3 scripts/test_check_stage_docs.py
python3 scripts/check_stage_docs.py \
  --verification docs/verification/r1_3_workspace_tool_security.md \
  --learning docs/learning/r1-3-tool-security/
git diff --check
```

## 10. 验收

- 新会话只读仓库规则即可知道三类文档职责。
- Agent 可以从正式模板生成与 R1.2 同类的 verification 和七件套 learning。
- R1.3 当前本地文档通过门禁。
- 缺章节、缺文件、README-only 或占位符样例都会失败。
- R1.4 最终 Task 已包含门禁命令。
- 本地文档仍被 Git 忽略，正式规则、模板、脚本和测试进入 Git。
