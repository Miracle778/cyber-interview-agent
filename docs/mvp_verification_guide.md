# Cyber Interview Agent MVP 验证与代码导览

## 先说结论

你感觉“像空架子”是对的，准确说当前实现是 **MVP 技术骨架 + 后端核心能力的可测切片**，还不是一个前端点按钮就能完整使用的产品。

当前已经跑通的是：

- React/Vite 前端工程能启动、测试、构建。
- FastAPI 后端能启动。
- workspace 和 Obsidian-compatible Vault 目录能初始化。
- 上传资料 API 能把文件写进 `knowledge-vault/00_inbox/`，并生成一个很粗糙的题库草稿。
- Vault rescan API 能扫描 Markdown，并写入 SQLite FTS 索引。
- LangGraph 复习 agent 能选择问题、评估回答、生成单轮报告草稿。
- 报告确认 API 能写入单轮报告，并生成全局掌握度更新建议。

当前还没有跑通的是：

- 设置页表单还没有真正调用后端。
- 知识文档页的“上传资料”和“重新扫描 Vault”按钮还没有绑定 API。
- 复习页的聊天输入还没有绑定 `/api/review/run`。
- 没有真实 LLM 调用；现在的题库生成和回答评估是规则/占位逻辑。
- 没有会话持久化、上下文压缩、HITL interrupt、provider 密钥存储。

所以现在不是完整 MVP 产品，而是 **第一条后端能力链条和前端页面壳**。下一步应该把 UI 和这些 API 串起来，才会真正有产品体感。

## 当前代码结构

```text
frontend/
  src/app/
    App.tsx
    layout/AppShell.tsx
  src/features/settings/
    SettingsPage.tsx
    settingsApi.ts
  src/features/knowledge/
    KnowledgePage.tsx
    knowledgeApi.ts
    knowledgeTypes.ts
  src/features/review/
    ReviewPage.tsx
    ReviewChat.tsx
    ReviewSessionList.tsx
    ReviewSetupPanel.tsx
    reviewApi.ts
    reviewTypes.ts
  src/shared/
    api/client.ts
    ui/Button.tsx
    ui/Field.tsx

backend/
  app/main.py
  app/api/
    routes_settings.py
    routes_knowledge.py
    routes_review.py
  app/agents/
    review_graph.py
    review_state.py
    tools.py
  app/db/
    connection.py
    schema.sql
  app/schemas/
    settings.py
    knowledge.py
    review.py
  app/services/
    workspace.py
    vault.py
    document_ingestion.py
    markdown.py
    search_index.py
    provider_registry.py
    mastery.py
```

## 一键自动验证

在仓库根目录执行：

```bash
pnpm --dir frontend test
pnpm --dir frontend build
cd backend && uv run pytest
cd .. && pnpm --dir frontend e2e
```

预期结果：

- 前端 Vitest：`5 passed` / `6 tests passed`。
- 前端 build：`vite build` 成功生成 `frontend/dist/`。
- 后端 pytest：`15 passed`，可能有一个 `StarletteDeprecationWarning`，目前不影响功能。
- E2E：`1 passed`，验证页面出现“设置 / 复习 / 知识文档”三个入口。

如果 E2E 首次失败提示缺少浏览器，执行：

```bash
pnpm --dir frontend exec playwright install
pnpm --dir frontend e2e
```

## 启动前后端

开两个终端。

终端 1：启动后端。

```bash
cd backend
uv run fastapi dev app/main.py
```

默认地址：

```text
http://127.0.0.1:8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

预期：

```json
{"status":"ok"}
```

终端 2：启动前端。

```bash
pnpm --dir frontend dev
```

默认地址：

```text
http://127.0.0.1:5173
```

页面现在只能看到基础 UI，不要期待按钮已经能完整操作后端。当前按钮主要是布局占位。

## 手动验证后端能力

下面命令使用一个临时 workspace，避免污染你的真实目录。

```bash
export CIA_WORKSPACE=/tmp/cyber-interview-agent-demo
mkdir -p "$CIA_WORKSPACE"
```

### 1. 初始化 workspace 和 Vault

```bash
curl -s -X POST http://127.0.0.1:8000/api/settings/workspace \
  -H 'Content-Type: application/json' \
  -d "{\"workspacePath\":\"$CIA_WORKSPACE\"}" | python -m json.tool
```

预期返回类似：

```json
{
  "workspacePath": "/tmp/cyber-interview-agent-demo",
  "vaultPath": "/tmp/cyber-interview-agent-demo/knowledge-vault"
}
```

检查目录：

```bash
find "$CIA_WORKSPACE/knowledge-vault" -maxdepth 1 -type d | sort
```

应该看到：

```text
00_inbox
10_question_bank
20_review_sessions
30_mastery
40_concepts
80_manifests
90_exports
.cyber-interview-agent
```

### 2. 测试 Provider 连通性占位逻辑

```bash
curl -s -X POST http://127.0.0.1:8000/api/settings/providers/test \
  -H 'Content-Type: application/json' \
  -d '{
    "id":"p1",
    "name":"OpenAI Compatible",
    "apiFormat":"openai-compatible",
    "baseUrl":"https://api.example.com/v1",
    "modelIds":["model-a"],
    "activeModelId":"model-a",
    "connectivityStatus":"unknown"
  }' | python -m json.tool
```

预期 `connectivityStatus` 变成 `ok`。

注意：这不是真实模型调用，只是当前占位校验：`baseUrl` 以 `http` 开头且有 `activeModelId` 就算 ok。

### 3. 上传资料并生成题库草稿

```bash
cat > /tmp/cache_question.txt <<'EOF'
缓存穿透是什么？
用户请求不存在的数据时，缓存无法命中，请求会持续打到数据库。常见防护是缓存空值或使用布隆过滤器。
EOF

curl -s -X POST http://127.0.0.1:8000/api/knowledge/sources \
  -F "workspacePath=$CIA_WORKSPACE" \
  -F "file=@/tmp/cache_question.txt" | python -m json.tool
```

预期返回一个 `ReviewQuestion` 草稿，类似：

```json
{
  "id": "q_xxx",
  "title": "缓存穿透是什么？",
  "questionText": "缓存穿透是什么？",
  "referenceAnswer": "缓存穿透是什么？\n用户请求...",
  "topics": ["uncategorized"],
  "difficulty": "medium",
  "keyPoints": ["缓存穿透是什么？"],
  "followUps": [],
  "mastery": "unknown"
}
```

检查原始文件：

```bash
ls "$CIA_WORKSPACE/knowledge-vault/00_inbox"
```

应该看到 `cache_question.txt`。

### 4. 扫描 Vault 并建立 SQLite FTS 索引

先手动放两份 Markdown：

```bash
mkdir -p "$CIA_WORKSPACE/knowledge-vault/10_question_bank"
cat > "$CIA_WORKSPACE/knowledge-vault/10_question_bank/cache_penetration.md" <<'EOF'
---
type: question
status: reviewed
---

# 缓存穿透

缓存空值、布隆过滤器、请求限流。
EOF
```

触发 rescan：

```bash
curl -s -X POST http://127.0.0.1:8000/api/knowledge/rescan \
  -F "workspacePath=$CIA_WORKSPACE" | python -m json.tool
```

预期：

```json
{"indexed": 1}
```

检查索引文件：

```bash
ls "$CIA_WORKSPACE/knowledge-vault/.cyber-interview-agent"
```

应该看到：

```text
index.sqlite
```

### 5. 调用复习 agent

```bash
curl -s -X POST http://127.0.0.1:8000/api/review/run \
  -H 'Content-Type: application/json' \
  -d '{
    "questions": [
      {
        "id": "q1",
        "title": "缓存穿透",
        "questionText": "缓存穿透是什么？",
        "referenceAnswer": "缓存空值或布隆过滤器可以减少不存在数据请求打到数据库。",
        "topics": ["backend"],
        "difficulty": "medium",
        "keyPoints": ["缓存空值", "布隆过滤器"],
        "followUps": [],
        "mastery": "weak"
      }
    ],
    "settings": {
      "selectedTopics": [],
      "questionCount": 1,
      "mode": "weak-point"
    },
    "userAnswer": "可以缓存空值"
  }' | python -m json.tool
```

预期：

- `current_question.id` 是 `q1`。
- `evaluation.score` 是 `partial`。
- `evaluation.missing_key_points` 包含 `布隆过滤器`。
- `report_markdown` 包含 `status: review_pending`。

注意：这还不是 LLM 评估，只是简单关键词规则。

### 6. 确认报告并生成 mastery 更新建议

```bash
curl -s -X POST http://127.0.0.1:8000/api/review/reports/confirm \
  -H 'Content-Type: application/json' \
  -d "{\"workspacePath\":\"$CIA_WORKSPACE\",\"reportMarkdown\":\"# 单轮复习报告\n\n- score: partial\"}" \
  | python -m json.tool
```

预期返回：

```json
{
  "reportPath": ".../knowledge-vault/20_review_sessions/session_report_xxx.md",
  "masteryPath": ".../knowledge-vault/30_mastery/global_mastery_review_pending.md"
}
```

检查文件：

```bash
cat "$CIA_WORKSPACE/knowledge-vault/30_mastery/global_mastery_review_pending.md"
```

应该能看到：

```yaml
type: mastery_report
status: review_pending
```

## 熟悉代码的建议阅读顺序

### 第一轮：从入口看整体

1. `backend/app/main.py`
   看 FastAPI app 注册了哪些路由。

2. `frontend/src/app/layout/AppShell.tsx`
   看当前前端页面由 Settings、Review、Knowledge 三块拼起来。

3. `docs/superpowers/specs/2026-07-09-cyber-interview-agent-mvp-design.md`
   看产品设计原意。

### 第二轮：看 workspace 和知识库

1. `backend/app/services/workspace.py`
   看 workspace 解析和沙箱校验。

2. `backend/app/services/vault.py`
   看 Vault 目录结构。

3. `backend/app/api/routes_knowledge.py`
   看上传、rescan 两个知识库入口。

4. `backend/app/services/search_index.py`
   看 SQLite FTS 索引如何写入和查询。

### 第三轮：看复习 agent

1. `backend/app/schemas/review.py`
   看题目和复习设置 DTO。

2. `backend/app/agents/tools.py`
   看选题和回答评估规则。

3. `backend/app/agents/review_graph.py`
   看 LangGraph 三节点流程：
   `choose_question -> evaluate_answer -> generate_report`。

4. `backend/app/api/routes_review.py`
   看 `/api/review/run` 和 `/api/review/reports/confirm`。

### 第四轮：看前端现状

1. `frontend/src/features/settings/SettingsPage.tsx`
   表单 UI，占位，还没绑定后端。

2. `frontend/src/features/knowledge/KnowledgePage.tsx`
   上传和 rescan 按钮，占位，还没绑定 API。

3. `frontend/src/features/review/ReviewPage.tsx`
   页面容器。

4. `frontend/src/features/review/ReviewChat.tsx`
   对话输入 UI，占位，还没绑定 `/api/review/run`。

5. `frontend/src/features/*/*Api.ts`
   已有 API 封装雏形，但多数 UI 尚未调用。

## 现在最该做的下一步

如果目标是让你感觉“功能真的跑起来”，下一步不要继续堆后端，而应该做一个前端可操作闭环：

1. 设置页输入 workspace path，点击后调用 `POST /api/settings/workspace`。
2. 知识页选择文件上传，调用 `POST /api/knowledge/sources`，把返回的题目草稿展示出来。
3. 复习页用一条草稿题目调用 `POST /api/review/run`，展示问题、评估和报告。
4. 点击确认报告，调用 `POST /api/review/reports/confirm`。

这一步完成后，才算有一个“人能在页面上走完”的最小闭环。

## 当前遗留事项

- `docs/my_idea.md` 是你的原始想法素材，当前仍未跟踪，尚未提交。
- 前端 UI 没有样式体系，布局只是语义结构。
- 后端 provider 还没有真实调用模型。
- question draft 生成非常粗糙，只取首行和全文片段。
- review evaluation 是关键词匹配，不是 LLM 评分。
- report 和 mastery 只是 Markdown 文件落盘，没有冲突合并、人审 UI 或版本管理。
- workspace 配置当前只在进程内存保存，重启后丢失。
