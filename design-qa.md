# 题目库浏览器视觉门禁

## Source visual truth

- 用户选定设计：`/Users/miracle778/.codex/generated_images/019f52f0-5368-7361-806d-3cfe8bd36e9d/exec-4e9e2b44-055a-4375-a8e0-6f1c9eaa9e34.png`
- 验收范围：题目检索、状态/难度/来源筛选、主题目录、结果列表、Markdown 阅读与编辑入口。
- 设计意图：在既有产品壳层内，将原先拥挤的双栏页面改为“目录—结果—阅读器”三栏内容浏览器。

## Implementation evidence

- 最终桌面页面：`.design-qa/question-library/implementation-1440x1024-final.png`
- 移动端页面：`.design-qa/question-library/implementation-390x844-final.png`
- 视口与状态：1440 × 1024；题目库、无筛选、首个已入库题目、渲染模式。
- 数据：真实分页读取 51 道题；待确认 33、已入库 18、已拒绝 0。
- 交互证据：搜索 `Redis` 得到 20 条；待确认状态筛选可用；阅读/原文切换可用，原文模式直接编辑保存；可返回整理会话。
- 浏览器：0 warning、0 error；桌面与 390px 均无页面横向溢出。

## Side-by-side comparison

- 全页面最终并排：`.design-qa/question-library/comparison-1440x1024-final.png`
- 浏览器主体最终并排：`.design-qa/question-library/comparison-explorer-final.png`
- 第一轮实现：`.design-qa/question-library/implementation-1440x1024-v1.png`
- 第一轮发现并修复：隐藏标签意外显示、难度标签竖向换行、长标题缺少完整内容提示。
- 最终逐面复核：
  - 字体：搜索、筛选、目录、结果标题、正文形成稳定层级；长标题截断并提供原生 tooltip。
  - 间距与布局：三栏宽度分别约 209/339/600px；筛选条、列表和阅读器均不重叠。
  - 颜色与表面：沿用产品 Indigo、语义状态色和既有圆角/边框，而非引入效果图之外的新视觉体系。
  - 图标与文案：沿用现有 Lucide 图标；状态、难度、来源均使用中文产品文案。
  - 响应式：中屏收拢目录，移动端单列流动；390px `clientWidth=scrollWidth=364`。

## Intentional differences

- 保留现有产品导航壳层与真实题库数据，未复制设计图中的伪 ID、伪排序和伪数量。
- 目录由真实题目的首主题动态生成，不伪造设计图中的父级分类树。
- 当前领域接口未提供题库页面直接拒绝 mutation，因此不添加无实际行为的“拒绝”按钮；已有确认、编辑、AI 重写和生成会话入口均保留。
- 移动端截图受内置浏览器 DPR 捕获比例影响；以真实 DOM 宽度与无溢出测量作为响应式证据。

## Gate result

- [x] 搜索优先的题目浏览入口。
- [x] 状态、难度、来源筛选及清除筛选。
- [x] 稳定主题目录、扁平结果列表和阅读详情三栏。
- [x] Markdown 阅读、原文直接编辑保存和 AI 重写能力未回退。
- [x] 消除原先 API 首 50 条静默截断，状态和目录统计来自完整分页结果。
- [x] 正式同画布并排比较完成，修正后无剩余 P0/P1/P2。
- [x] 发布审批在当前视口以内显示，具备明确关闭入口；关闭后保留可恢复的待处理提示。
- [x] 发布审批默认阅读渲染内容，编辑与拒绝理由按需展开，主操作在有界弹层底部保持可见。

## Publication approval evidence

- 实现截图：`.design-qa/question-library/publication-approval-redesign-2026-07-16.png`
- 使用真实未决 `knowledge.publish` action 验收；确认关闭按钮、服务端 pending 恢复入口、Markdown 预览和操作层级。
- 未执行批准或拒绝，避免验收过程改变用户的真实题目状态。

final result: passed
