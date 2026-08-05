# Agent 运行中心结构化响应展示修复计划

> **执行要求：** 使用 `superpowers:executing-plans` 与 `superpowers:test-driven-development`；这是独立的小型 UI 修复，不改观测数据和 JSONL 结构。

**目标：** 修复对象数组被“绿色成功背景 + 巨大白色胶囊”渲染的问题，让结构化模型响应保持中性、清晰和可扫描。

**架构：** 仅调整 `FriendlyResponseValue` 的值类型分流和 CSS。对象数组使用普通分组卡，基础值数组才使用紧凑标签；成功语义只保留在状态图标/小标签，不铺满正文背景。

**技术栈：** React、TypeScript、CSS、Testing Library、Vitest。

---

### Task 1: 用值类型驱动对象数组和基础值数组的不同呈现

**文件：**

- Modify: `frontend/src/features/observability/TraceJsonViewer.tsx`
- Modify: `frontend/src/features/observability/observability.css`
- Test: `frontend/src/features/observability/TraceEventInspector.test.tsx`

**步骤：**

- [x] 先添加失败测试：对象数组项得到 `data-value-kind="record"`，字符串/数字数组项得到 `data-value-kind="scalar"`。
- [x] FriendlyResponseValue 对 record 使用普通块级容器和字段行；只为 scalar 使用 pill 样式。
- [x] `.trace-model-response__result` 改为中性表面；移除作用于所有 `li` 的圆角胶囊规则；绿色只保留小型成功状态或左侧 accent。
- [x] 保持空值、深层对象、超长文本、复制和原文切换行为不变。
- [x] 运行：`cd frontend && npm test -- --run src/features/observability/TraceEventInspector.test.tsx`

### Task 2: 视觉回归与集成确认

**文件：**

- Modify: `docs/verification/interview-retrospective.md`

**步骤：**

- [x] 运行：`cd frontend && npm run build`
- [ ] 浏览器打开包含 `speakers`/`segments` 对象数组的模型响应，确认无巨大白色圆形、无整块绿色背景、长文字不溢出。
- [ ] 打开基础值数组，确认仍为紧凑标签且键值层级清楚。
- [x] 更新观测工作台验证证据。

### Task 3: 运行中详情自动刷新

**文件：**

- Modify: `frontend/src/features/observability/ExecutionTracePage.tsx`
- Test: `frontend/src/features/observability/ExecutionTracePage.test.tsx`

**步骤：**

- [x] `queued` / `running` 时每秒刷新执行摘要、Operation 与事件索引。
- [x] 从运行态进入终态时再刷新一次 Operation 与事件，避免最终原子响应因状态先结束而遗漏。
- [x] 结构化模型响应继续在 Provider 完整返回后一次性出现，不展示残缺 JSON。
- [x] 运行中总耗时按开始时间更新；终态自动停止轮询。
- [x] 定向测试覆盖响应自动出现及终态停止轮询，TypeScript 类型检查通过。

### Task 4: 统一运行中耗时的 UTC 时间解析

- [x] 添加回归测试，使用 SQLite `YYYY-MM-DD HH:mm:ss` UTC 时间复现北京时间环境固定多出 480 分钟。
- [x] 高级运行详情复用共享 `parseApiTimestamp`，不再直接使用浏览器相关的 `Date.parse` 解析无时区字符串。
- [x] 验证运行开始 23 秒时显示 `23 秒`，不再显示 `480:23`。

## 自检

- [x] 未改后端事件结构、JSONL 命名或存放路径。
- [x] 对象数组与基础值数组有测试锁定。
- [x] 成功颜色不再承担正文容器背景。
- [x] 高级运行详情不再是静态快照，终态不会继续轮询。
- [x] SQLite UTC 时间和带时区 ISO 时间使用同一解析口径。
