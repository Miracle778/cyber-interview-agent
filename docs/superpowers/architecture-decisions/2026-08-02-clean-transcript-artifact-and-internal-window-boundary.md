# 准确转写文档 Artifact 与内部窗口边界

日期：2026-08-02

状态：Accepted

取代：

- `2026-08-02-interview-retrospective-corrected-transcript-evidence-boundary.md`
- `2026-08-02-retrospective-cleanup-grounded-unit-output.md`

## 背景

旧方案把长 ASR 原文切成窗口和 SourceUnit，要求模型在每个单元内恢复 turns，再由程序用 Diff 生成 Correction。它解决了输出截断和 offset 不可信，却把内部切分、模型段落和字符差异直接暴露给用户：一小时转写会产生上千条自动修订和大量段落，页面采用稿还可能与模型响应不一致。系统优化了可审计性，却没有先产出用户真正需要的“一份准确文档”。

同时，题目提取、复盘分析和证据引用已经依赖 `CleanupVersion` 与 `SegmentRecord` 外键。直接删除这些表会扩大迁移面，并让当前未合并特性失去可验证的增量路径。

## 决定

### 1. CleanupVersion 是准确转写文档的版本身份

保持现有表名与外键兼容，但给 `CleanupVersion` 增加唯一 `document_body` 和 `document_sha256`。在产品语义中，它等价于 `CleanTranscriptVersion`；work items 是该版本的内部构建过程，不是用户文档结构。

### 2. 窗口只做内部 Map，不成为领域段落

程序规划互不重叠且无缝覆盖原文的 target windows，并为每个 target 附带只读 before/after context。模型只返回 target 的修订正文和少量不确定项。Reducer 按 target_start 确定性拼接，每个原文位置只由一个窗口负责。

新运行不再让模型返回 SourceUnit、turn、offset 或逐字符 Correction，也不在 review_pending 前创建 SegmentRecord。

### 3. 连续文档是审核和下游处理的唯一权威正文

用户整体编辑 `document_body`，只处理术语、说话人或语义等稀疏问题。逐字符 Diff 不是待办生成器。确认前存在未解决的高风险问题会阻止确认；确认后文档不可原地修改。

题目提取和分析不得读取 source window、模型原始响应或旧 Correction adopted text。

### 4. SegmentRecord 降级为确认后生成的只读锚点

为兼容现有问题证据和分析外键，确认文档时由程序按自然段与有界长度生成稳定 SegmentRecord。它只负责定位和引用，不是模型输出，也不是用户需要逐段确认的采用稿。

历史 CleanupVersion 没有 document_body 时继续按旧 Segment/Correction 只读投影；重新整理会进入新模型。

### 5. 质量门槛包含直接 Prompt 基线

固定真实长 ASR 样本，在相同 Provider 和模型下比较直接整理 Prompt 与新 Workflow。新方案在事实遗漏、错误新增、术语误改、职责拔高和可读性上不得更差。架构可解释、可恢复或可观测不能替代输出质量。

## 参考

- DeerFlow 将长任务产物保存为 Artifact，并把上下文工程与面向用户的结果分离。
- LangGraph Map/Reduce 使用可并行 map、确定性 reducer 和持久状态处理长输入。
- Microsoft GraphRAG 区分输入 Document、内部 TextUnit 与最终产物，不把内部块当作文档本体。
- Haystack 将 Cleaner、Splitter、Writer 拆成明确阶段，切分结果服务处理流程而非强迫用户逐块审核。

具体链接与适用边界记录在 `docs/superpowers/specs/2026-08-02-interview-retrospective-transcript-correction-design.md`。

## 否决方案

### 继续优化 Segment/Correction 页面

否决。问题不是页面信息层级，而是错误的产品对象。即使卡片更紧凑，上千条 Diff 仍不应由用户处理。

### 只把窗口增大或 max_tokens 调高

否决。它只能推迟截断，无法消除重复上下文、模型 offset、采用稿分叉和人工审核爆炸。

### 直接一次调用模型处理全文

否决作为唯一生产路径。一小时级文本受 Provider 输入/输出限制、超时和失败重试影响，任何失败都会重做全文；但它保留为质量基线，防止 Workflow 在工程复杂度中损失整理效果。

### 立即删除现有 Segment/Correction 表

否决。当前问题、分析和证据链依赖 Segment ID。先把 Segment 降级成确认后锚点，可以在不破坏现有领域外键的前提下修正产品模型。

## 结果

收益：

- 用户只看到一份连续准确文档和少量真正不确定的问题；
- 上下文重叠不再造成正文重复；
- 失败可局部恢复，已完成窗口不重复调用；
- 页面采用稿、确认稿和下游输入拥有同一权威来源；
- 现有问题、分析、运行中心和证据 ID 可渐进兼容。

代价：

- CleanupVersion 在数据库命名上同时承载历史运行身份与新文档版本身份；
- 必须维护 target window 覆盖、Reduce 拼接和确认后锚点生成的不变量；
- 说话人不是主要录音内容或无法确定时，文档会保守保留 unknown/待确认，而不是强行制造完整对话；
- 历史与新投影需要一段兼容期，待当前特性稳定后再评估物理表重命名或归档。

## 面试讲述口径

这次调整的核心不是“Prompt 写得更长”，而是把产品 Artifact 和执行分块分开。模型负责有上下文的局部语义纠错，程序负责不重叠目标、确定性拼接、版本和恢复；用户审核的是最终文档，而不是 Map 任务的中间结构。为了避免 Workflow 只在工程上显得先进，还用相同模型的直接 Prompt 做质量基线，把输出质量设成不可回避的验收门槛。
