# ADR：题目整理采用渐进式 Discovery 与 Enrichment 流水线

- 状态：Accepted
- 决定日期：2026-07-21
- 适用阶段：R2 题库整理及后续复用该能力的阶段
- 关联设计：`docs/superpowers/specs/2026-07-21-r2-progressive-question-curation-design.md`
- 关联设计：`docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md`

## 背景

题目整理当前用一个 Agent 调用同时完成题目发现和完整候选生成。真实高密度笔记证明，输入字符数不是可靠预算：20,051 字符可以包含数百个短主题和数十个明确标题，完整 candidate JSON 的规模远大于输入。固定字符分块、增大输出 token、延长超时和更换界面模型名称都不能建立“单次结构化输出有界”的保证。

现有实现还把答案中的普通数字列表误认为题目边界、漏掉中文无空格编号、复制首个编号前缀，并在聚合到 50 个候选时静默结束。这些是确定性编排问题，不能交给模型或 Provider 重试修正。

## 候选方案

### 方案 A：继续单阶段生成，动态调整字符/token 预算

拒绝。题目密度和完整输出大小不可由字符数稳定推导；更小块会增加碎片、重复和调用数，仍可能在一个块中包含大量短主题。

### 方案 B：用更强模型或不同 Provider 隐藏单阶段限制

拒绝。Provider 能力和路由可变化，且不能修复确定性 section、恢复、50 题上限和部分成功事实。

### 方案 C：本地 section + discovery + enrichment + 持久 work item

采用。确定性代码拥有切段、批量、进度、重试和停止条件；模型先返回小型 seed，再补全少量完整候选；每个工作单元持久记录，最终 reducer 仍是唯一正式候选入口。

## 决定

1. source 先由本地纯函数建立稳定 section ref，不允许模型自主切段。
2. discovery 单次最多处理 6 个 section，只返回 0–6 个 question seed。
3. enrichment 单次最多补全 3 个 seed，只返回 0–3 个完整 candidate。
4. 单次 Provider contract 与会话聚合 contract 分离；会话最多 200 个候选，达到上限必须显式 warning。
5. 每个 discovery/enrichment 单元使用 additive Runtime work-item 表持久化摘要、状态和严格输出；completed 单元在重启和显式重试时复用。
6. Graph 每次只推进一个 work item，并在节点间 checkpoint；模型不拥有循环、重试、数据库写入或停止条件。
7. 正式 candidate、draft、source link、去重和 publication 继续由现有 reducer/application service 拥有。
8. 原始 source 正文不进入 work-item 表、事件或 timeline；work item 只保存 refs、digest、状态和结构化 proposal。

## 结果

正向结果：

- 单次输入和输出都有结构上限，不依赖 Provider 猜测；
- 高密度短笔记和普通长文章使用同一流水线；
- 已完成调用不会因后续单元失败而重复；
- 进度、失败位置、重试范围和 200 题上限可解释、可恢复；
- 发布、HITL 和题目生命周期边界保持不变。

代价与风险：

- 模型调用次数增加，完整整理总耗时可能上升；
- 新增 work-item migration、Graph 循环和两类结构化 contract；
- section 偏细可能产生重复 seed，需要现有确定性去重；偏粗时由 2,000 字符 continuation 上限兜底；
- 首版 200 候选上限不能覆盖无限密度文件，达到上限后需用户先审核，后续再以真实需求决定是否增加分页继续整理。

## 重新评估条件

- 真实 Provider 对 6-seed discovery 或 3-candidate enrichment 仍无法稳定返回；
- 三种以上文档格式需要不同 section 语义，单一 sectioner 产生系统性遗漏；
- 用户经常命中 200 候选上限并明确需要同 session 分页继续；
- Provider 提供可验证的原生批量结构化作业、单元级幂等和恢复协议，可替代当前 work-item Graph。
