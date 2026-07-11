# Cyber Interview Agent 规划发现记录

## 2026-07-10：初始规划上下文

### 代码与 Git 状态

- 当前分支 `main` 最新提交是 `6b8914b feat(review): implement review loop UI and align with backend contract`。
- 该提交只包含 review 相关文件：
  - `frontend/src/features/review/ReviewPage.test.tsx`
  - `frontend/src/features/review/ReviewPage.tsx`
  - `frontend/src/features/review/reviewApi.ts`
- 当前工作区仍有未提交改动，涉及：
  - `docs/mvp_verification_guide.md`
  - `frontend/src/app/App.test.tsx`
  - `frontend/src/app/App.tsx`
  - `frontend/src/app/layout/AppShell.tsx`
  - `frontend/src/features/knowledge/*`
  - `frontend/src/features/settings/*`
  - `frontend/src/shared/ui/Button.tsx`
  - `frontend/src/shared/ui/Field.tsx`
  - `tests/e2e/mvp-smoke.spec.ts`
- 当前未跟踪文件包括：
  - `docs/my_idea.md`
  - `docs/product_roadmap.md`
  - `docs/superpowers/plans/2026-07-09-frontend-mvp-review-loop.md`
  - `docs/superpowers/plans/2026-07-09-ui-redesign.md`
  - `frontend/src/app/global.css`
  - `frontend/src/shared/ui/Badge.tsx`
  - `frontend/src/shared/ui/Card.tsx`
  - `frontend/src/shared/ui/Spinner.tsx`
- 用户已明确要求 `docs/my_idea.md` 留在本地，不要动。

### 来自 product_roadmap.md 的阶段

- P0：MVP 可操作闭环。
- P1：MVP 质量补强。
- P2：知识库管理。
- P3：资料摄取与整理。
- P4：题库管理。
- P5：Obsidian 协同。
- P6：进度与掌握度 Dashboard。
- P7：学习计划。
- P8：面试准备工作台。
- P9：设置、运行环境与产品化。
- P10：个人信息中心。
- P11：JD 与岗位追踪。
- P12：面试复盘。
- P13：模拟面试。
- P14：移动端入口。

### 来自 MVP design 的 Post-MVP Roadmap

- 阶段 2：个人信息中心。
- 阶段 3：JD 与岗位追踪。
- 阶段 4：面试复盘。
- 阶段 5：模拟面试。
- 阶段 6：移动端入口。
- 这些阶段已在 `product_roadmap.md` 中映射为 P10-P14。

### 来自 frontend MVP review loop spec

- P0 的核心目标是让浏览器中完成最小复习闭环：
  1. 输入 workspace path，初始化 Vault。
  2. 输入 Provider 基础信息，执行连接测试。
  3. 上传资料，看到题库草稿。
  4. 用题库草稿开始复习。
  5. 输入回答，调用复习 agent。
  6. 看到评分、缺失点和报告草稿。
  7. 确认报告，看到 report 和 mastery draft 路径。
  8. 手动触发 Vault rescan。
- P0 明确不做：
  - 真实 LLM Provider 调用。
  - API key 加密存储。
  - 多题批量复习。
  - 会话持久化列表。
  - 完整知识文档列表。
  - Obsidian 图谱或关系图 UI。
  - 多文件批量上传。
  - Provider 多配置保存和切换。

### 来自 frontend MVP review loop implementation plan

- 计划把跨页状态放在 `AppShell`。
- 设置页负责 Provider 测试和 workspace 初始化。
- 知识页负责上传资料、展示题库草稿、rescan。
- 复习页负责单题单轮回答、报告展示、报告确认。
- 后端不在 P0 中修改，因为 required endpoints 已存在。

### 来自 UI redesign plan

- UI redesign 是一条独立体验计划，定位是面试辅助工具，不是网络安全产品。
- 计划新增：
  - `src/app/global.css`
  - `src/shared/ui/Card.tsx`
  - `src/shared/ui/Badge.tsx`
  - `src/shared/ui/Spinner.tsx`
- 计划修改：
  - Button、Field、AppShell、SettingsPage、KnowledgePage、ReviewPage。
- 硬约束包括：
  - h1 文本保留 `Cyber Interview Agent`。
  - 文本 `复习闭环 MVP` 保留。
  - 前三个 h2 为 `设置`、`知识文档`、`复习`。
  - 首屏按钮和前置条件提示必须仍可见。
  - `getByLabelText` 依赖的 label 必须保留。
  - 关键中文文本必须保持单文本节点。

## 规划判断

- 当前最重要的不是继续加新功能，而是先收口当前工作区。
- P0 已有一部分实现和提交，但还有未提交文件，需要归类确认。
- UI redesign 与 P0 有交叉文件，必须避免混入同一个不可解释提交。
- P1 应在 P0 收口后立即进行，目标是让用户能稳定手动验证并理解每一步。
- P1.5 必须单独插入真实 LLM 接入，放在 P1 之后、P2 之前。
- P2-P5 是复习 agent 之外的产品基础：知识库、资料、题库、Obsidian 协同。
- P6-P8 是长期使用能力：Dashboard、计划、面试准备工作台。
- P10-P14 是原 MVP design 中明确写过的 Post-MVP 功能，不能遗漏。

## 风险与注意事项

- 当前 `product_roadmap.md` 中仍写着“前端还没有形成可点击闭环”，这可能与最新 P0 实现状态不一致，需要在 S0/S1 收口时更新。
- `docs/mvp_verification_guide.md` 已被修改，需确认内容是否和当前实际 UI 一致。
- UI redesign 计划可能已经有部分文件生成，但尚未确认测试和人工视觉验收。
- 真实 LLM 不应混入 P0/P1，但必须作为 P1.5 单独规划，不能被拖到 P2 之后。
- P1.5 第一版优先做 OpenAI-compatible、后端 `.env`/本地配置读取、真实 provider test、LLM 题库生成、LLM 回答评估、fake provider 测试。
- P1.5 暂不做多 provider 管理 UI、系统密钥链、流式输出、多轮面试、embedding/向量检索。
- `docs/my_idea.md` 必须持续排除在提交之外。

## 2026-07-10：原始 idea 与现有排期对齐审计

### 对齐的部分

- 复习主闭环与原始 idea 一致：零散问题资料 -> 题库整理 -> 对话复习 -> 单轮报告 -> 全局掌握度 -> 指导下一轮。
- Workspace 文件沙箱、独立 Obsidian-compatible Vault、显式摄取确认、可重建索引等方向与原始 idea 一致。
- 个人信息、JD、面试复盘、模拟面试、移动端入口都被记录，没有功能名称层面的遗漏。

### 发生偏移的部分

- 现有 roadmap 将个人信息、JD、复盘、模拟面试整体推迟到 P10-P13，在它们之前插入 P2-P9 多个基础设施和衍生模块，导致原始产品主体被过度后置。
- P8“面试准备工作台”和 P11“JD 与岗位追踪”职责重叠，形成重复阶段；原始 idea 中岗位就是面试追踪的一级索引，不应拆成两个相似产品。
- P7“学习计划”并非原始 idea 的独立核心页面，属于全局掌握度和岗位准备产生的推荐能力，不应优先于个人信息、复盘和模拟面试。
- P6 Dashboard 中的掌握度、薄弱点、下一步建议本应首先作为复习 agent 的右侧状态与全局报告体验，而不是后置成独立阶段。
- P1.5 只规划 OpenAI-compatible 第一版、后端环境变量和单一 Provider，弱化了原始 idea 明确要求的多 Provider、多模型、OpenAI/Anthropic 格式、保存与切换。
- 原始 idea 要求每个 agent 页面具备独立工具、文件沙箱、上下文压缩、状态恢复、持久记忆和 HITL；当前 roadmap 只在复习 MVP spec 中局部描述，缺少跨页面 Agent Runtime 基线。
- 原始 idea 强调个人资料、复盘产物、模拟面试总结都通过显式“推送”进入知识库；现有 P3 摄取阶段偏向通用文件导入，没有把跨模块发布/摄取协议设为产品主干。
- 原始 idea 中 React + Python + LangGraph 的技术方向需要在近期形成明确架构决策，不能等到各页面开发后再补。

### 修正方向

- 从“基础设施阶段堆叠”改成“共享底座 + 纵向产品闭环”的排期。
- 近期先完成 Provider/模型管理、LangGraph Agent Runtime、会话与 HITL、知识库发布协议等共享底座。
- 随后完成真正的复习 agent MVP：多题轮次、模式选择、追问、会话派生、单轮与全局掌握度，而不只是单题技术切片。
- 再按依赖推进个人信息 agent -> JD/岗位追踪 -> 面试复盘 -> 模拟面试 -> 移动端。
- 知识库管理、Obsidian 兼容、Dashboard 和推荐能力作为各纵向闭环的配套能力逐步增强，不再长期挡在原始核心页面之前。

## 2026-07-10：新路线决策

- 采用“共享底座 + 纵向业务闭环”，替换旧 P0-P14 的基础设施堆叠顺序。
- 新阶段统一为 R0-R8：
  - R0 技术切片与质量基线。
  - R1 共享 Agent 与知识库底座。
  - R2 完整复习 Agent。
  - R3 个人信息 Agent。
  - R4 岗位与 JD 追踪。
  - R5 面试复盘 Agent。
  - R6 模拟面试 Agent。
  - R7 知识库与本地产品化增强。
  - R8 移动端 Channel。
- 原 P8“面试准备工作台”和 P11“JD 与岗位追踪”合并为 R4，以岗位作为复习、复盘和模拟面试的一级索引。
- 原 P6 Dashboard 与 P7 学习计划不再作为阻塞原始核心功能的独立阶段；掌握度、弱点、差距和建议首先进入各 Agent 页面状态与报告。
- Provider 能力由后置产品化提前到 R1，并恢复多 Provider、多模型、OpenAI-compatible、Anthropic-compatible、保存、切换和真实连接测试要求。
- LangGraph、checkpoint、会话恢复、上下文压缩、独立工具、Workspace 沙箱和 HITL 被定义为 R1 共享 Agent Runtime 基线。
- 知识库采用统一草稿/审核/发布契约，从 R1 开始贯穿所有业务阶段；R7 只负责完整管理、Obsidian 冲突和长期产品化增强。
- 默认技术栈明确为 React + TypeScript + Vite、Python + FastAPI、LangGraph、SQLite、Markdown/frontmatter Vault。

## 2026-07-10：R1 现有代码审计

### 可以沿用

- `backend/pyproject.toml` 已声明 LangGraph、LangChain、`langchain-openai` 和 `langchain-anthropic`，不用重新选择主框架。
- `ProviderConfig` 已包含 `api_format`、`base_url`、`model_ids`、`active_model_id` 和连接状态，可作为新持久化模型的输入基础。
- 前端设置页已有 Provider 名称、Base URL、Model ID 和连接测试入口，可渐进扩展为 Provider 列表与编辑区。
- 后端已有 `review_graph.py` 和 `ReviewState`，可以作为验证共享 Runtime 接口的第一个迁移对象。
- Vault、SQLite FTS、manifest schema 和 `ensure_inside_workspace` 已有最小技术切片，可在原模块上增强。

### 必须重做或补齐

- 当前 Provider 测试只检查 URL 是否以 `http` 开头，没有真实网络调用、鉴权、模型检查或错误分类。
- Provider 没有保存/列表/更新/删除/切换 API；Workspace 只保存在进程全局变量中，重启即丢失。
- API key 还没有进入 schema、保存策略和脱敏返回契约，需要先决定 secret storage。
- 当前 graph 每次同步编译并一次性跑完，没有 checkpointer、thread/session id、interrupt、恢复或持久状态。
- 当前 Agent 工具只是普通 Python 函数，没有共享 tool registry、Agent allowlist 或权限审计。
- 当前 workspace 检查使用 `resolve()` 做基础父路径判断，但 R1 还需定义软链接、文件创建前目标、路径穿越和 workspace 切换后的授权边界。
- 当前 SQLite 只存 manifest 和 FTS；R1 需要区分 app config/session/checkpoint 数据与 Vault 内可重建索引数据。
- 当前前端跨步骤状态主要在 `AppShell` 内存中，R1 会话状态应以后端持久化为准。

### R1 设计应拆成四个子系统

1. Provider 与 Secret 管理。
2. LangGraph Runtime、会话和 checkpoint。
3. Workspace 沙箱、tool allowlist 和 HITL。
4. 统一知识草稿、审核和发布协议。

四个子系统共用 schema 和持久化约定，但实施时应分任务逐项验收，避免一次大改。

## 2026-07-10：R1 设计决策

### Provider 作用域

- 采用“全局 Provider + Workspace 模型用途映射”。
- Provider、连接信息和 secret 引用由应用级配置统一保存，不随 Workspace 重复创建。
- 每个 Workspace 单独保存模型用途映射，例如题库生成、回答评估、报告总结和普通 Agent 对话分别选择哪个 Provider/model。
- 切换 Workspace 时保留全局 Provider，只切换该 Workspace 的模型用途和业务数据。
- Vault 不保存 API key，也不保存可直接还原 API key 的密文。

### API Key 保存

- 采用“系统密钥链 + 环境变量兜底”。
- Provider 元数据只保存 `secret_ref`，不保存明文或可直接还原的密文。
- Python 后端负责访问 macOS Keychain、Windows Credential Manager 或 Linux Secret Service。
- 无可用密钥链的环境允许通过环境变量注入，但不自动写入本地文件。
- 前端只能创建、替换和删除 API key，任何读取接口都不返回完整 key。

### R1 其余架构决策

- 应用级配置使用操作系统应用数据目录中的 `app.sqlite`，保存 Provider 元数据和 Workspace 注册表。
- 每个 Workspace 在 `.cyber-interview-agent/runtime.sqlite` 保存会话、checkpoint、HITL 和领域运行状态；该目录不属于 Obsidian Vault。
- 复习、个人信息、岗位、复盘和模拟面试使用独立 LangGraph，共享 Runtime、Provider、HITL 和知识发布接口。
- Agent 工具默认拒绝；每个 Agent 配置 tool allowlist 和 Workspace 子目录授权，路径解析后再次校验并拒绝软链接越界。
- HITL 使用持久化 `pending_action`；支持接受、编辑后接受、拒绝，确认接口幂等，服务重启后可继续。
- 简历、JD、转写等原始资料和领域草稿保存在 Workspace 领域目录；用户确认后才生成带来源关系的 Vault 文档。
- Provider 可以在连接失败时保存，状态为 `unknown/ok/failed`；调用时再次尝试并返回分类错误。
- Agent 命令使用 REST，模型输出、节点进度、工具调用和状态事件使用 SSE。
- R1 验收使用现有单题复习 graph 接入共享 Runtime：覆盖真实 LLM、会话持久化、SSE、暂停恢复、一次 HITL 和一次知识草稿发布；完整多题复习留到 R2。

### R1 实施组织方式

- 采用方案 A“按能力做纵向切片”。
- 切片顺序：应用配置与 Provider -> 会话 Runtime 与 SSE -> 工具权限与 Workspace 沙箱 -> 持久化 HITL -> 知识草稿与发布 -> 单题复习迁移验收。
- 每个切片同时包含必要的数据模型、后端 API、前端入口、自动测试和人工验证，不先堆完整后端平台。
- 不采用“先完成全部后端再接 UI”，避免长期只有不可操作骨架。
- 不采用“直接围绕复习页边做边抽象”，避免共享 Runtime 被复习领域模型污染。

### 数据恢复术语修正

- 正式设计不使用容易混淆的“是否可重建”描述，改为“删除后能否从其他数据自动恢复”。
- Vault Markdown、`artifacts/` 原始资料、Provider 配置、API key 和关键会话状态都不能自动恢复，需要备份或重新录入。
- Vault 是 manifest、FTS 和关系索引的重建来源，但 Vault 自身不是可重建数据。
- 真正可以删除后自动重建的只有 manifest 派生表、FTS、关系索引、缓存和临时文件。

### Provider 详细设计确认

- Provider、Provider Model、Workspace Model Binding 和 Provider Test Run 分表保存。
- 连接状态记录在具体模型上，不使用笼统的 Provider 单状态；同一 Provider 下不同模型可有不同结果。
- 初始模型用途为题库生成、回答评估、报告总结和普通 Agent 对话。
- 模型 ID 第一版由用户手工维护，不依赖兼容性不稳定的模型发现接口。
- 真实连接测试发起最小模型请求，记录错误分类和耗时，不记录密钥或回复正文。
- Provider 可以在测试失败时保存；修改协议、URL 或 API key 后，模型测试状态重置为 unknown。
- 删除仍被 Workspace 绑定的 Provider 或模型时返回冲突，要求先解除或替换绑定。

### Agent Runtime 详细设计确认

- 产品 `session_id` 同时作为 LangGraph `thread_id`；每次执行生成独立 `run_id`。
- 每个 session 同一时间只允许一个 active run，避免并发覆盖状态。
- Workspace `runtime.sqlite` 分别保存 session、message、run、event、checkpoint 和 pending action。
- checkpoint 只服务 Graph 执行恢复，聊天记录和产品状态使用独立表保存。
- SSE 事件先持久化再发送，客户端通过事件 ID 断线续传。
- R1 不引入外部任务队列，使用进程内异步执行；服务重启后将 running run 标记 interrupted，并允许从 checkpoint 恢复。
- 等待 HITL 的 run 使用 waiting_for_approval 状态，服务重启后保持可操作。
- session 固定 graph id 和 graph version；缺少兼容版本时进入 migration_required，不静默使用新 Graph 恢复旧 checkpoint。
- Runtime 事件覆盖 run、graph node、message、tool、HITL、draft 和错误生命周期。

### Workspace 沙箱、工具与 HITL 详细设计确认

- Workspace 注册后使用稳定 workspace id；Agent API 不接受可任意改变的原始本地路径。
- 工具只接受相对路径，并在创建父目录、解析真实路径和实际 I/O 前执行授权检查；拒绝路径穿越和软链接越界。
- Tool Registry 为每个工具声明输入/输出 schema、风险级别、required scope 和审计策略；权限默认拒绝。
- Graph 不能直接访问文件系统、设置 API 或任意网络，只能调用 Runtime 注入的已授权工具与 Provider adapter。
- HITL 使用持久化 pending action，支持接受、编辑后接受、拒绝和稍后处理。
- pending action 使用版本号和幂等键；重复或并发处理不会执行两次。
- Graph 通过 interrupt 等待 action，处理后从同一 checkpoint 恢复。
- R1 默认只监听 localhost，限制 CORS；移动端或远程访问需要后续独立身份认证设计。

### 知识草稿与发布详细设计确认

- 原始资料、Agent 草稿和已发布知识分层保存：Workspace 领域 sources、Workspace 领域 drafts、Obsidian Vault。
- 草稿正文使用 Markdown 文件，runtime DB 保存稳定 id、来源、关系、状态、版本和 content hash。
- 用户申请推送时创建 knowledge.publish pending action；action 绑定草稿版本与 hash，过期版本不能继续批准。
- PublicationService 通过临时文件和原子替换写入 Vault；稳定文档 id 与幂等 action 防止重复文件。
- Markdown 写入成功后即成为发布事实；索引失败标记 index_stale，并由 rescan 修复，不回滚或删除已发布 Markdown。
- 已被 Obsidian 外部修改的文件不静默覆盖；R1 返回冲突，完整冲突合并留到 R7。
- 只有 status=ingested 且 confirmed_by_user=true 的文档进入 active knowledge scope。
- Vault frontmatter 保存来源和 Agent provenance，但不保存密钥、请求头、完整 system prompt、checkpoint 或隐藏分析。

## 2026-07-11：R1.1 Provider 与模型设置落地发现

### 已落地事实

- R1.1 已在 `codex/r1-provider-settings` 分支完成，并 fast-forward 合并回 `main`，最新提交为 `b5b6696 feat(settings): bind workspace model roles`。
- R1.1 对应 7 个提交：
  - `cbbc414`：应用数据库迁移。
  - `609e42d`：Provider secret store，支持系统密钥存储和环境变量引用。
  - `9319fbd`：Provider、Model、Workspace 和 Binding 持久化。
  - `acf8923`：真实 Provider adapters 和模型测试。
  - `7f8f8fc`：Provider/Model/Workspace REST API。
  - `26e2a18`：前端 Provider 与 Model 管理。
  - `b5b6696`：Workspace 模型用途绑定。
- 设置页现在可以管理多个 Provider、多个模型，并为四个固定用途选择模型：
  - `question_generation`
  - `answer_evaluation`
  - `report_summarization`
  - `agent_chat`
- OpenAI-compatible 与 Anthropic-compatible 都走真实最小模型请求测试；测试状态记录在模型粒度，不再是粗糙的 Provider 全局状态。
- API key 不通过读取接口回显；元数据只保存 secret reference。
- Workspace 注册和恢复已经接入设置页，模型用途绑定按 workspace 保存。

### 验证结果

- 后端测试：78 passed，1 个 Starlette deprecation warning。
- 前端测试：27 passed。
- 前端 production build：passed。
- 浏览器人工视觉 QA 覆盖 desktop 1440x1000 与 mobile 390x844/有效 375 宽度。
- 本地验证文档已同步到 `docs/verification/2026-07-10-r1-1-provider-settings.md`，该目录按用户要求忽略，不提交。

### 仍需注意

- R1.1 完成的是 LLM Provider 基础设施；复习 Agent、资料摄取、报告总结等业务调用还没有真正接入模型绑定。
- 业务调用绑定模型应在 R1.2 Runtime 和 R1.6 单题复习迁移中完成，不能在 R1.2 提前把复习业务逻辑揉进去。
- R1.2 需要沿用 R1.1 的 app config/provider services，不要再引入第二套 Provider 配置来源。
- 模型真实测试会消耗少量额度；自动测试仍应使用 fake/deterministic provider。

## 2026-07-11：产品布局重构发现

### 产品层级

- 原来的“设置 -> 知识 -> 复习”纵向进度条是技术切片顺序，不是最终产品的日常使用顺序；继续沿用会让设置错误地成为所有任务的第一步。
- 当前真实入口拆为 `/review`、`/knowledge`、`/settings`。最终产品仍保留首页、个人资料、岗位、面试复盘和模拟面试等一级能力，但未实现前不显示空壳入口。
- 设置归入系统组；复习与知识库归入工作台组。根路径暂时进入复习，等首页具备真实聚合数据后再开放。
- R1.2 会引入 session/run/SSE，先建立稳定路由和页面容器可以避免 Runtime 状态继续堆入单个 `AppShell` 页面。

### 交互与布局

- 1024px 及以上使用 240px 常驻侧栏；更窄视口使用顶部栏和模态抽屉。最终一级功能超过五个，因此不采用移动端底部导航。
- 移动抽屉支持遮罩、关闭按钮、Escape、路由后关闭、背景滚动锁定和焦点返回。
- 复习页目前使用主工作区与 300px 流程摘要双列，后续可扩展为会话列表、对话区、上下文/动作区三栏。
- PageHeader 统一展示页面标题、短描述、后端和 Workspace 状态；流程状态只出现在复习场景，不再全局重复。
- UI 使用中性灰白画布、靛青主色和独立语义色；移除旧的紫色单页氛围、装饰渐变和过大圆角。

### 验证与测试发现

- 前端单元测试更新为路由、导航、抽屉、恢复动作和 skip link 行为，共 35 passed。
- Playwright E2E 不能假设本地数据库为空；Workspace 可能是“待初始化”或已恢复路径。环境状态由组件测试覆盖，E2E 只验证稳定的路由和功能入口。
- 浏览器 QA 覆盖 1440x1000、1024x768、768x1024、375x812；四档均无水平溢出、控件越界或控制台错误。
- UI 规范复查补充了“跳到主内容”链接，避免键盘用户每次穿过完整侧栏。
- 当前边界仍是 R0 单题本地状态；题库草稿、报告和会话刷新持久化属于 R1.2/R1.6。

## 2026-07-11：R1.2 设计复核发现

- 既有 R1 总规格对 session/run/checkpoint/SSE 的核心决策完整且已获批准，不需要重新设计 Runtime。
- 旧 R1.2 计划只交付前端 client，没有浏览器可操作入口，与“每个切片可人工验证”的执行原则不一致。
- 采用设置页 Runtime 自检方案：确定性 `test.echo` session 可以真实创建、运行、观察 SSE 和刷新恢复，但不混入复习业务。
- 不采用提前迁移复习页；完整复习 Graph 仍在 R1.6，避免绕过工具安全、HITL 和知识发布协议。
- Repository、EventStream、RunManager 和 REST/SSE 共享状态契约且复杂度高；本切片全部由 Codex 实现，不委派 Claude。
- worktree 复用主仓库依赖时，`pnpm` 会尝试重装链接的 `node_modules` 并访问 registry；基线和后续验证应直接调用主仓库已安装的 Vitest/tsc/Vite 二进制，或在获批网络下独立安装。

## 2026-07-11：R1.2 实施与验收发现

- Workspace Runtime 数据与 app config 数据必须分库：Provider/Workspace registry 留在应用级 `app.sqlite`，Agent session/checkpoint/event 跟随 Workspace 存在 `runtime.sqlite`。
- SQLite 不能在显式索引中引用隐式 `rowid`；事件和消息排序使用显式时间与 ID，产品消息仍按插入顺序读取。
- 单 Session 并发保护必须落在数据库唯一约束上，进程内 lock 只负责执行串行化，不能作为状态真相源。
- LangGraph checkpoint 不能替代产品消息和 run 状态；前端刷新从 session detail 恢复最终状态，SSE 只负责增量事件和断线补发。
- SSE 使用命名事件时，浏览器不能只监听 `onmessage`；前端必须对已注册事件类型使用 `addEventListener`。
- 自动重连显式携带最后 event ID，重复 ID 在 Hook 内去重；`run.failed` 不清空先前消息和时间线。
- 浏览器验收发现 optimistic `running` 会在终态事件后继续禁用按钮；终态事件必须优先于旧的本地 run 快照。
- SSE 重放包含同一 session 的历史 run；运行状态只能使用 latest run 对应的事件派生，否则旧终态会错误覆盖新 run 的 queued/running 状态。
- 设置页确定性自检证明了 session、run、checkpoint、SSE 和刷新恢复的真实闭环，同时保持 R1.6 复习业务迁移边界。
