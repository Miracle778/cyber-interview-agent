# R1.5 知识草稿与发布设计复核

## 1. 复核结论

R1 总规格中的三层数据和发布原则保持不变：原始资料与草稿位于 Workspace `artifacts/`，只有用户明确批准的标准 Markdown 才进入 `knowledge-vault/`；已发布文档必须可追溯、幂等，并且不能静默覆盖 Obsidian 外部修改。

旧实施计划需要适配 R1.3 的路径策略、R1.4 的持久化 HITL 和当前知识页。R1.5 将同时迁移旧上传链路，消除“上传即写入 Vault”的遗留行为，并用真实 `knowledge.publish` Graph 完成草稿、确认、发布和索引闭环。

## 2. 本阶段完成后的产品效果

用户在知识页可以：

1. 上传资料，原文件保存到 `artifacts/review/sources/`；
2. 查看由上传内容生成的持久化 Markdown 草稿；
3. 编辑草稿，使用 version 防止覆盖过期内容；
4. 请求发布，看到 `knowledge.publish` 待确认动作；
5. 在同一页面批准、编辑后批准或拒绝；
6. 批准后看到唯一 Vault 路径和索引状态；
7. 刷新或重启后继续处理未完成的草稿、action 和 publication run；
8. 手工 rescan 修复 `index_stale` 的已发布文档。

R1.5 不接真实 LLM，不迁移完整复习 Graph，不实现多文档批量审核、关系图、全文知识管理或高级冲突合并。以上分别属于 R1.6、R2 或 R7。

## 3. 方案选择

### 方案 A：复用 Agent Runtime 与确定性发布 Graph（采用）

`knowledge.publish` Graph 从 draft id、version 和 content hash 创建 pending action，再通过 LangGraph `interrupt()` 等待。批准后，R1.4 的 handler delivery 调用 `PublicationService`，随后恢复原 run。

优点是 action、checkpoint、重启恢复、并发决定和审计继续使用同一套状态机。代价是 publish request 返回 run，前端需要短暂轮询对应 action。

### 方案 B：API 直接创建 action，再手工维护命令状态（不采用）

该方案表面简单，但需要伪造或放宽 action 的 session/run 外键，并重复实现 waiting、resume 和取消语义。

### 方案 C：绕过 HITL 直接由草稿 API 发布（不采用）

该方案无法满足 R1 已批准的人工确认、重启恢复和重复批准幂等要求。

## 4. 数据模型与文件归属

Runtime migration `004_publication.sql` 一次创建完整 schema，后续任务不回改已执行迁移。

### 4.1 Knowledge Draft

`knowledge_drafts` 保存：

- stable id、workspace id；
- 可空的来源 session id、run id 和 agent type；
- domain、document type、document id、title；
- source refs、relation refs；
- 相对 content path、content hash；
- status、version、created/updated time。

用户直接上传生成的草稿没有 Agent session/run，因此 provenance 字段允许为空；未来 Agent 生成草稿时必须填写。正文固定保存为：

```text
artifacts/<domain>/drafts/<draft-id>.md
```

草稿状态为 `draft`、`review_pending`、`rejected`、`published`。只有 `draft` 和 `review_pending` 可以编辑；更新必须提交当前 version，并在原子替换前后校验 content hash。

### 4.2 Publication Run

`publication_runs` 以 action id 唯一，保存 draft id/version/hash、稳定 document id、target path、发布状态、写入 hash、错误码和时间。

状态为：

- `prepared`
- `file_written`
- `indexed`
- `completed`
- `index_stale`
- `failed`

Markdown 成功写入后即成为发布事实。后续索引失败不得删除文件，只进入 `index_stale`。

## 5. 上传与草稿链路

知识 API 从原始 `workspacePath` 迁移到已注册的 `workspaceId`。后端通过 Workspace Registry 解析 root，API 和前端不再为知识操作传任意本地路径。

上传链路按以下顺序执行：

1. 校验文件名、大小和类型；
2. 使用 `WorkspacePathPolicy` 写入 `review.sources`；
3. 从安全路径提取文本；
4. 沿用当前确定性 `create_question_draft` 生成问题内容；
5. 通过 `KnowledgeDraftService` 写入 `review.drafts` 并保存 metadata；
6. 返回持久化 draft resource，不再返回仅存在于前端内存的 `ReviewQuestion`；
7. 不初始化或写入 Vault，不更新 active index。

旧 `/api/knowledge/sources` 路由保留路径但更换请求字段和响应契约，不保留接受任意 `workspacePath` 的兼容入口。

## 6. 发布与 HITL 数据流

`POST /api/knowledge/drafts/{draft_id}/publish-request` 执行：

1. 读取 draft 当前 version/hash；
2. 创建新的 `knowledge.publish` session，或复用该 draft 尚未完成的发布 session；
3. 启动确定性 Graph run，input 固定包含 draft id/version/hash；
4. Graph 调用 Runtime 绑定的 `request_action`，action key 包含 draft id/version/hash；
5. Graph interrupt，run 进入 `waiting_for_approval`；
6. API 返回 session/run resource，前端按 run id 获取对应 pending action。

`KnowledgePublishActionHandler` 只在 action 状态为 `approved` 或 `edited_and_approved` 时发布；`rejected` 只恢复 Graph，不写 Vault。编辑后批准只允许修改 title 和 markdown。handler 先把编辑内容保存为新的 draft version，再发布该精确 version/hash。

handler 必须以 action id 作为 publication operation id。R1.4 delivery 重试时，已完成 publication run 直接返回原结果，不重复写文件或索引。

## 7. 标准 Markdown 与冲突保护

R1 文档类型 Registry 固定支持：

- `source` -> `00_inbox/`
- `question` -> `10_question_bank/`
- `session_report` -> `20_review_sessions/`
- `mastery_report` -> `30_mastery/`
- `concept` -> `40_concepts/`

目标路径固定为 `<directory>/<document-id>.md`，不使用标题作为文件名。frontmatter 至少包含 schema version、id、type、status、title、source refs、relation refs、confirmed ingestion 和 provenance；禁止 secret、authorization、system prompt、checkpoint 和隐藏分析字段。

写入使用同目录临时文件、flush、fsync 和 `os.replace`。如果目标已存在，必须比较 publication/manifest 记录的上次写入 hash 与当前文件 hash；不一致时返回 `external_document_changed`，保持用户文件不变。

## 8. Active Knowledge 与 Rescan

索引器解析 frontmatter，只有同时满足以下条件的文档进入 manifest 和 FTS：

```text
status == ingested
ingestion.confirmed_by_user == true
```

草稿、review pending、stale、archived、缺少合法 frontmatter 和软链接文档都不进入 active scope。rescan 重建派生索引，并把对应 `index_stale` publication run 修复为 `completed`；它不能改变 Vault Markdown 的事实内容。

## 9. API 与前端

草稿 API：

```text
POST  /api/knowledge/sources
GET   /api/knowledge/drafts?workspaceId=...
GET   /api/knowledge/drafts/{draft_id}
PATCH /api/knowledge/drafts/{draft_id}
POST  /api/knowledge/drafts/{draft_id}/publish-request
POST  /api/knowledge/rescan
```

知识页增加 DraftReview，展示草稿列表、Markdown 编辑、版本、状态、请求发布和发布结果。现有 ActionCenter 抽出“是否显示诊断入口”和 action type 过滤参数，在知识页只展示 `knowledge.publish` action，不复制第二套批准/拒绝逻辑。

发布请求后页面明确显示“等待人工确认”，不能提前显示成功。批准完成后刷新 draft、action、publication status 和 indexed count。版本冲突、外部修改和 index stale 都显示稳定错误码对应的下一步建议。

## 10. 错误与恢复

- stale draft PATCH：`409 draft_version_changed`；
- action 绑定的 version/hash 已变化：`409 draft_version_changed`；
- Vault 外部修改：`409 external_document_changed`；
- 非法 frontmatter：不进入 active index，并在 rescan 结果中计入 skipped；
- 文件已写、索引失败：返回/展示 `index_stale`，允许 rescan；
- 重复 publish request：若同 draft version 已有 waiting run，返回原 session/run；
- 重复批准：返回原 action/publication result，不重复产生文件；
- 服务重启：R1.4 reconciliation 重投 handler，publication journal 继续精确阶段。

错误响应和事件不包含绝对 Workspace 路径、草稿以外的正文、内部异常、checkpoint 或 secret。

## 11. 测试与验收

后端自动测试覆盖：

- 上传文件与草稿均在 Vault 外；
- version/hash 乐观并发；
- canonical frontmatter 和禁止字段；
- 原子写入与临时文件清理；
- publish Graph interrupt/resume；
- 拒绝不写 Vault；
- 编辑批准发布精确版本；
- action 和 publication 幂等；
- 外部修改冲突；
- index stale 与 rescan 修复；
- active scope 排除未确认文档；
- Workspace ID、路径穿越和软链接安全。

前端自动测试覆盖草稿恢复、编辑、版本冲突、请求发布、同页 ActionCenter、成功路径、外部冲突和 index stale 建议。

浏览器验收至少完成一次上传、刷新恢复、编辑、请求发布、批准、Vault 文件检查、重复操作、拒绝、后端重启和 rescan，并覆盖桌面与移动宽度。

## 12. 实施拆分

R1.5 按七个任务直接实现：

1. migration 与 KnowledgeDraftService；
2. 上传链路迁移和草稿 API 基础；
3. 文档类型 Registry、frontmatter 与原子 writer；
4. publication journal、Service 与 active index；
5. `knowledge.publish` Graph 和 R1.4 handler 集成；
6. 完整 REST API 与 typed errors；
7. DraftReview、ActionCenter 复用、浏览器验收和阶段文档。

状态机、文件一致性、HITL 集成和最终审阅由 Codex 实现。边界清晰的纯类型或展示任务可委派，但本次按用户要求不委派、不创建 worktree。
