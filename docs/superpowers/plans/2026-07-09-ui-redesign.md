# UI 重设计：Cyber Interview Agent（面试辅助工具）

> 定位纠正：cyber 只是名称，本产品是**面试辅助 agent 工具**（上传资料→生成题库→答题→评估→报告/掌握度）。
> 设计依据：ui-ux-pro-max 设计系统（Soft UI Evolution / Minimal Single Column / 浅色为主）。

## 设计系统摘要

| 维度 | 决策 |
|------|------|
| 风格 | Soft UI Evolution — 专业 SaaS/学习工具，柔和阴影，WCAG AA+ |
| 布局 | Minimal Single Column（引导式纵向流，用户已选定） |
| 主题 | 浅色为主（不引入深色切换，降低本轮流次） |
| 字体 | Lexend（标题）+ Source Sans 3（正文），Google Fonts |
| 图标 | lucide-react（已装），aria-hidden，不用 emoji |
| 动效 | 200–300ms，可见 focus ring，尊重 prefers-reduced-motion |
| 间距 | 4/8 节奏；圆角/阴影分级 token |

色板（CSS 变量）：
- `--bg #FAF5FF` / `--fg #0F172A` / `--muted #F7F3FD` / `--border #EFE7FC`
- `--primary #7C3AED` / `--on-primary #fff` / `--secondary #8B5CF6`
- `--accent #059669`（成功/正确）/ `--danger #DC2626` / `--ring #7C3AED`
- 评分语义：good=`#059669`、partial=`#D97706`（琥珀）、poor=`#DC2626`

## 硬约束（保持所有测试绿，不改测试）

来源：`App.test.tsx` + `tests/e2e/mvp-smoke.spec.ts` + 三个页面测试。

1. h1 文本 = "Cyber Interview Agent"；存在文本 "复习闭环 MVP"
2. 文档中前 3 个 h2 依次 = ["设置","知识文档","复习"]（→ 进度条等装饰不得用 h2）
3. 首屏同时可见按钮：测试连接 / 初始化工作区 / 上传资料 / 重新扫描 Vault / 发送回答
4. 首屏同时可见文本："请先初始化工作区"（无 workspace 时）、"请先上传资料生成题库草稿"（无 draft 时）
5. 保留所有 `getByLabelText`：Provider 名称 / Base URL / Model ID / Workspace Path / 选择资料文件 / 你的回答
6. 保留所有 `getByText` 单文本节点：评分：… / 缺失点：… / 证据：… / 关键点：… / 索引文档数：… / Provider 连接状态：… / Vault：…
   - 实现：这些字符串必须是**单元素单文本节点**（可在前面加 aria-hidden 图标 span，但不得把"标签：值"拆到两个子元素）
7. 按钮 accessible name 保留原文（按钮内可加 aria-hidden 图标，不影响 name）

## 文件改动

### 新增

- `src/app/global.css` — 设计 token（CSS 变量）、reset、基础排版、字体 @import、容器/卡片等工具类、reduced-motion。在 `App.tsx` 顶部 import。
- `src/shared/ui/Card.tsx` — 面容器（柔和阴影+边框+圆角），可选 header（图标+标题+状态徽标）。
- `src/shared/ui/Badge.tsx` — 状态徽标（连接状态、难度、掌握度、评分语义色）。
- `src/shared/ui/Spinner.tsx` — 小型加载 spinner（aria-hidden）。

### 修改

- `src/shared/ui/Button.tsx` — 增加 variant（primary/secondary/ghost/danger）、size、loading（spinner）、disabled 样式、cursor-pointer、focus ring。保留 `children` 渲染以保按钮名。
- `src/shared/ui/Field.tsx` — label+input+可选 helper/error、focus ring、`htmlFor` 关联（保 `getByLabelText`）。
- `src/app/layout/AppShell.tsx` — 固定顶栏（图标+h1"Cyber Interview Agent"+副标题"复习闭环 MVP"+右侧工作区状态徽标）；工作流进度条（3 步：设置/知识/复习，按 workspace/draft/report 状态显示 done/active/pending，**非 h2**）；居中容器内依次渲染三段 `<section>`（保持同屏可见）。
- `src/features/settings/SettingsPage.tsx` — Card 内两组：Provider（3 个 Field + 测试连接 + 连接状态徽标）、Workspace（path Field + 初始化工作区 + Vault 文案）。错误条 aria-live。loading 态。保留全部契约文案。
- `src/features/knowledge/KnowledgePage.tsx` — Card：上传行（文件输入+上传资料+重新扫描 Vault+索引文档数）；题库草稿卡（h3 标题、题目、参考答案代码块、topics 徽标、难度徽标、"关键点：…"单文本节点、掌握度徽标）；空态"暂无文档"；保留"请先初始化工作区"。
- `src/features/review/ReviewPage.tsx` — Card：当前题目；回答 textarea（label 你的回答）；发送回答（loading）；评估结果（"评分：…"带 aria-hidden 语义色圆点、"缺失点：…"、"证据：…"、报告 markdown `<pre>` 等宽）；确认报告 + 结果路径；错误条 aria-live。保留全部契约文案。

## 交互逻辑改进（在"同屏可见"约束内）

- **Loading**：异步按钮显示 spinner + 禁用
- **状态反馈**：Provider 连接徽标（ok/fail）、工作区就绪徽标、索引文档数、评分语义色（good/partial/poor）
- **进度条**：反映 workspace 就绪？draft 就绪？report 就绪？
- **空/错误态**：图标+引导文案，错误用 aria-live
- **可达性**：focus ring、4.5:1 对比、图标按钮 aria-label、键盘可达、reduced-motion

## 验证

- `pnpm test`（11 个）全绿
- `pnpm build`（tsc + vite）无错
- `pnpm e2e`（mvp-smoke）绿
- 手动：375 / 768 / 1440 响应式；reduced-motion；键盘导航；focus 可见

## 非目标（本轮不做）

深色模式切换、Tab/侧栏导航、后端改动、新增功能。
