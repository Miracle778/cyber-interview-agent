# ADR：统一个人画像与多来源事实模型

日期：2026-07-24

状态：Accepted

## 背景

R3 已经用 MaterialVersion、Evidence、ProfileClaimVersion 和 Proposal 建立可信简历底座，但当前产品把简历解析结果当作个人画像展示。用户看到原文片段、页码和待确认字段，却无法直接理解系统形成了怎样的个人能力档案。

进一步讨论确认：

- 简历不是画像唯一来源；
- 用户可以直接补充真实信息；
- 对话和 Agent 可以提出归纳建议；
- 多份简历应共同支持一份画像；
- 新版简历不能重建或覆盖长期画像；
- 来源追溯应当按需查看，不应占据画像主界面。

## 决策

### 1. Workspace 级单一画像

同一 Workspace 维护一份统一个人画像。`profile_claims` 继续作为稳定事实身份，`profile_claim_versions` 继续作为不可变确认版本。不会为每份简历、每个 Session 或每个求职目标复制一套画像。

### 2. 简历与画像解耦

Material、MaterialVersion 和 Evidence 是来源资产；Profile Claim 是长期画像资产。

```text
MaterialVersion / User Input / Conversation / Agent Inference
                     ↓
              Profile Proposal
                     ↓
              User Confirmation
                     ↓
        Profile Claim + Claim Version
```

删除或替换简历不自动删除 Claim。来源消失时更新支持状态，并由用户决定保留或删除。

### 3. 四种来源

Claim Version 和 Proposal 使用显式来源：

```text
resume_extraction
user_input
conversation
agent_inference
```

来源引用使用类型化关联，不把所有来源伪装成 Evidence：

- `resume_extraction` 引用 Evidence；
- `user_input` 引用用户命令回执；
- `conversation` 引用正式用户消息；
- `agent_inference` 引用确认 Claim Version 和基础 profile version。

正文、消息全文和模型输出不复制进来源关联。

### 4. 确认规则

- 用户在画像编辑器主动保存：直接创建 confirmed Claim Version；
- 简历提取：创建 pending Proposal；
- 对话整理：创建 pending Proposal；
- Agent 归纳：创建 pending Proposal；
- 普通 Agent 回答和下游 context：只读取 confirmed Claim Version；
- 审核场景可以读取当前 Proposal，但不得把它当作正式事实。

### 5. 固定画像结构

事实类型扩展为：

```text
skill
project
experience
education
certification
achievement
link
```

职业概况、能力方向和代表性亮点属于画像展示内容，必须由用户直接维护或通过引用已确认事实的 Proposal 确认。它们不成为无来源的模型自由文本。

为复用同一版本与确认机制，内部增加 `summary`、`direction` 和 `highlight`
三种 presentation Claim Type；它们不被当作新的原始事实，必须通过
`supported_by` 关系引用已确认事实，或明确标记为用户直接维护。

### 6. 类型化关系

新增 Workspace 内 Profile Claim 关系：

```text
belongs_to
used_in
supported_by
```

关系端点必须属于同一 Workspace。关系用于项目归属、技能使用经历和亮点支持，不复制事实内容。

### 7. 读取投影

新增统一画像投影，按用户任务返回：

- identity：职业概况、能力方向、主要方向；
- highlights：用户确认并排序的亮点；
- experience timeline；
- projects；
- skills with usage；
- education/certification/achievement；
- actionable gaps；
- pending counts 和轻量来源摘要。

原文 Evidence 不进入默认投影。用户点击“查看依据”时再单独读取。

`ConfirmedProfileContext` 继续是下游安全契约，默认不包含完整 Evidence 和待确认内容。

### 8. 编辑与版本

用户按画像卡片编辑。每次保存：

```text
validate schema and relationships
→ optimistic version check
→ append confirmed Claim Version
→ update current pointer
→ persist idempotency receipt
→ recompute profile version
```

历史恢复追加新版本，不修改历史。R3 不建设整个画像 Time Travel。

### 9. Agent 写入边界不变

Agent 仍然没有直接写 Claim 的 Tool。对话补充和归纳内容只能输出 Proposal 或受约束 Action Plan；用户确认后由确定性领域服务执行。

### 10. 数据重置

当前本地测试画像可以清除，但重置不是数据库迁移的隐式副作用。提供目标 Workspace、显式确认和 dry-run 的本地重置命令，只删除 Profile 领域行和对应私有材料文件，不影响题库、复习、Workspace 或 Provider 配置。

## 被否决的方案

### 每份简历一套画像

会导致同一事实重复确认、版本冲突和 Agent 不知道应读取哪一份画像。

### 用一段 AI 总结作为画像真相

无法稳定编辑、比较和追溯；模型改写会把推断包装成事实。

### 只做前端分组展示

无法支持本人补充、对话补充、统一来源、项目关系和跨简历增量更新，只会形成漂亮但不真实的画像外观。

### 所有信息必须引用简历 Evidence

会阻止用户补充真实但尚未写进简历的经历，也会迫使系统伪造来源。

### Agent 直接更新画像

破坏现有确认、Diff、乐观锁和回执边界。

### 画像综合评分

没有具体岗位和透明计算标准时属于虚假精确。基础画像只展示明确缺失项，岗位准备度由 R4 计算。

## 结果

优点：

- 用户主对象从解析器输出变成可读、可编辑的长期画像；
- 复用现有 Claim 版本、Proposal、Action Plan 和 confirmed-profile；
- 支持无简历开始和多份简历统一；
- 画像来源真实可解释，不把用户陈述伪装成 Evidence；
- 为 R4 岗位目标提供稳定输入。

成本：

- 需要扩展 Claim 类型、来源和关系 schema；
- 需要新增手动编辑、统一画像投影和四入口前端；
- Ingest 必须从“每次创建候选”升级为增量匹配与冲突；
- 删除预检和 Agent 上下文装配需要理解多来源；
- 当前 R3 最终验收需要按新产品主线重新执行。

## 验证

- 手动创建的 confirmed 信息没有 Evidence 也能安全进入画像和 confirmed-profile；
- pending 简历/对话/归纳建议不能进入普通 Agent 回答；
- 多份简历支持同一 Claim，不复制 Claim；
- 项目、工作和技能关系只能连接同一 Workspace；
- 卡片恢复创建新版本；
- 删除单一来源不会删除仍有其他来源支持的 Claim；
- 统一画像首页不依赖原文片段渲染；
- 目标 Workspace 重置不改变题库、复习、设置和其他 Workspace。
