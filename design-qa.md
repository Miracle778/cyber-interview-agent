# 题库整理右栏候选文件视觉门禁

## Source visual truth

- 设计图：`/Users/miracle778/.codex/generated_images/019f52f0-5368-7361-806d-3cfe8bd36e9d/exec-b741e063-b8b1-479c-b249-3145b50a3029.png`
- 验收范围：整理会话右栏候选状态下钻，以及它与会话消息中文件卡片的一致性。

## Implementation evidence

- 真实集成页面：`.design-qa/curation-status-drilldown-1440x900-v2.png`
- 最终聚焦页面：`.design-qa/curation-status-harness-1440x900-final.png`
- 视口：1440 × 900；状态：选中“待确认”。
- 交互：状态筛选、查看 Markdown、返回原筛选、发布及备注均复用共享候选对象和回调。
- 浏览器：0 warning、0 error，无页面横向溢出；右栏 `clientHeight=scrollHeight=614`；文件列表 `clientHeight=410`、`scrollHeight=594`，以内部滚动约束长度。

## Side-by-side comparison

- 全页面首轮：`.design-qa/curation-status-comparison-full.png`
- 最终右栏并排：`.design-qa/curation-status-comparison-right-rail-final-lossless.png`
- 第一轮发现并修复：状态顺序错误、卡片缺少题目摘要。
- 第二轮发现并修复：重复列表标题、英文难度、操作视觉层级不足。
- 最终逐面复核：
  - 字体：标题、文件名、元信息和正文层级一致。
  - 间距：状态切换、三张完整卡片和有界滚动符合设计密度。
  - 颜色：沿用产品 Indigo 与语义状态 token，状态不只依赖颜色表达。
  - 图标：沿用现有 Lucide 文件图标，清晰且与产品其他页面一致。
  - 文案：待确认/已发布/已拒绝/草稿、中文难度、查看/发布/备注完整。

## Intentional differences

- 设计图的 `M↓` 图形替换为项目现有 FileText 图标，避免引入第二套图标语言。
- `历史版本` 只在真实历史候选上展示，不因视觉样例而伪造业务状态。
- 加载数量不另设固定页脚；列表采用可见滚动条表达仍有内容，避免重复信息占用右栏高度。

## Gate result

- [x] 共享 Markdown 候选卡组件。
- [x] 可点击状态统计与选中态。
- [x] 有界文件列表和三张完整卡片。
- [x] 详情关闭后返回原状态筛选。
- [x] 右栏与会话记录共享候选状态、发布和备注动作。
- [x] 正式并排比较完成，两轮修正后无剩余 P0/P1/P2。

final result: passed
