# R2 Progressive Question Curation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace unbounded single-stage question generation with deterministic semantic sections, bounded discovery/enrichment Agent calls, persistent recoverable work items, and an explicit 200-candidate aggregate limit.

**Architecture:** Pure code first converts each source excerpt into stable `SourceSection` records and packs them into bounded discovery units. A two-stage LangGraph loop persists each discovery/enrichment unit in Runtime SQLite, reuses completed units after failure/restart, and reduces only validated outputs into the existing candidate persistence path; single-candidate revision remains separate. The existing Session, Execution, draft, duplicate detection, publication, HITL, and question lifecycle remain the owners of product state.

**Tech Stack:** Python 3.12, Pydantic v2, LangChain ToolStrategy, LangGraph, SQLite additive migration 018, pytest, React 19, TypeScript, Vitest.

## Global Constraints

- Discovery processes at most 6 sections and 6,000 source characters per Provider call and returns 0-6 `QuestionSeed` objects.
- Enrichment processes at most 3 seeds per Provider call and returns 0-3 full `QuestionCandidate` objects.
- A semantic section is at most 2,000 characters and has a stable `<source-id>#section-NNNN` reference and SHA-256 digest.
- Recognize Markdown headings, whole-line bold headings, question-ending lines, `1.`, `1、`, and `1)` with zero or more spaces after punctuation; normalize zero-width blank lines and empty HTML placeholders.
- Never duplicate the pre-boundary prefix into later sections.
- Discovery uses 2,048 output tokens; enrichment and single revision use 4,096 output tokens; all use a 180-second timeout and SDK `max_retries=0`.
- Work items persist refs, digests, state, bounded structured output, attempt count, and stable error code only; source bodies remain in existing source artifacts/Execution input.
- A curation batch aggregates at most 200 candidates and emits `candidate_limit_reached` instead of silently truncating.
- Failed retry reuses completed work items from the same batch and never repeats their Provider calls.
- Single-candidate revision never enters multi-question discovery/enrichment.
- Existing drafts, candidate records, source links, duplicate detection, publication, active catalog, review snapshots, and HITL behavior remain unchanged.
- Implement the global JSONL trace plan first so real Provider acceptance produces local request/response evidence.
- Treat the existing uncommitted GLM thinking, 180-second timeout, stable thread, and long-line chunk tests as implementation baseline evidence; fold or replace them deliberately and never discard them while applying Task 1.
- Preserve all unrelated dirty R3 files and local planning files; stage only files named by the current task.
- This R2 plan contains four vertical tasks and must be executed by one Agent without implementation subagents.

---

## File Structure

- `backend/app/review/curation_sections.py`: pure normalization, boundary recognition, hard section splitting, stable refs/digests, and discovery packing.
- `backend/app/agents/question_curation_contracts.py`: seed, discovery chunk, enrichment chunk, aggregate, and one-candidate revision contracts.
- `backend/app/agents/prompts/question_curation_prompts.py`: separate discovery, enrichment, and revision prompts/renderers.
- `backend/app/agents/question_curation_agent.py`: three named Agent runnables with bounded model policies; no batch loop or repository ownership.
- `backend/app/db/migrations/runtime/018_progressive_question_curation.sql`: additive work-item table and indexes.
- `backend/app/review/{models,repository}.py`: work-item records, idempotent planning, atomic claim/complete/fail, output validation, and batch retry attachment.
- `backend/app/graphs/question_curation.py`: explicit section-plan/discovery/enrichment/reduce loop and separate revision route.
- `backend/app/application/{graph_factory,execution_service}.py`: Graph dependencies, progress projection, failure state, candidate persistence, and work-item reuse.
- `backend/app/review/application.py`: retry the active failed batch instead of creating a replacement batch; expose generation phase.
- `frontend/src/features/review/reviewTypes.ts`, `CurationSessionList.tsx`, and `CurationRuntimePanel.tsx`: discovery/enrichment phase and 200-limit warning copy.
- Focused tests cover section contracts, migration/repository invariants, Graph recovery, API/resource projection, frontend progress, and the authorized Mybatis document.

### Task 1: Establish Deterministic Sections and Bounded Agent Contracts

**Files:**

- Create: `backend/app/review/curation_sections.py`
- Modify: `backend/app/agents/question_curation_contracts.py`
- Modify: `backend/app/agents/prompts/question_curation_prompts.py`
- Modify: `backend/app/agents/agent_factory.py`
- Modify: `backend/app/agents/agent_model_resolver.py`
- Create: `backend/tests/test_curation_sections.py`
- Modify: `backend/tests/test_question_curation_graph.py`
- Modify: `backend/tests/test_agent_factory.py`

**Interfaces:**

- Produces: `SourceSection`, `DiscoveryUnit`, `section_sources(source_excerpts)`, `pack_discovery_units(sections)`, `QuestionSeed`, `QuestionSeedChunk`, `QuestionCandidateChunk`, `QuestionCandidateBatch`, `QuestionRevisionOutput`, and `ModelInvocationPolicy`.
- Consumers: Task 3 Agents/Graph and Task 4 real-document acceptance.

- [ ] **Step 1: Write failing semantic-section tests**

```python
def test_sectioner_recognizes_chinese_and_markdown_boundaries_without_prefix_copy():
    source = (
        "source-1:mybatis.md\n"
        "前置说明\n\u200b\n补充说明\n\n"
        "# 插件原理\n正文 A\n"
        "**如何创建拦截器？**\n正文 B\n"
        "1、正向代理\n正文 C\n"
        "2) 反向代理\n正文 D\n"
        "缓存为什么失效？\n正文 E"
    )
    sections = section_sources((source,))
    assert [item.ref for item in sections] == [
        "source-1#section-0001", "source-1#section-0002",
        "source-1#section-0003", "source-1#section-0004",
        "source-1#section-0005", "source-1#section-0006",
        "source-1#section-0007",
    ]
    assert sum("前置说明" in item.text for item in sections) == 1
    assert any(item.text.startswith("1、正向代理") for item in sections)
    assert all(len(item.text) <= 2_000 for item in sections)


def test_long_section_has_stable_continuations_and_digest():
    first = section_sources(("s1:long.md\n# 标题\n" + "x" * 4_501,))
    second = section_sources(("s1:long.md\r\n# 标题\r\n" + "x" * 4_501,))
    assert [item.ref for item in first] == [
        "s1#section-0001", "s1#section-0002", "s1#section-0003"
    ]
    assert [(item.ref, item.digest) for item in first] == [
        (item.ref, item.digest) for item in second
    ]
    assert "".join(item.text for item in first).replace("# 标题\n", "", 1) == "x" * 4_501


def test_discovery_units_enforce_section_and_character_limits():
    sections = tuple(
        SourceSection(
            "s1", f"s1#section-{index:04d}", index, "x" * 1_100,
            sha256(str(index).encode("utf-8")).hexdigest(),
        )
        for index in range(1, 9)
    )
    units = pack_discovery_units(sections)
    assert all(len(unit.sections) <= 6 for unit in units)
    assert all(sum(len(section.text) for section in unit.sections) <= 6_000 for unit in units)
```

- [ ] **Step 2: Write failing strict-contract and per-Agent model-policy tests**

```python
def seed(index: int) -> QuestionSeed:
    return QuestionSeed(
        question_text=f"问题 {index}？",
        source_ref=f"s1#section-{index:04d}",
    )


def candidate(index: int) -> QuestionCandidate:
    return QuestionCandidate(
        title=f"题目 {index}", question_text=f"问题 {index}？",
        reference_answer=f"答案 {index}", topics=["database"],
        difficulty="medium", key_points=[f"关键点 {index}"], follow_ups=[],
        source_refs=[f"s1#section-{index:04d}"], correction_note="结构化原题",
    )


def test_discovery_and_enrichment_contracts_are_independently_bounded():
    assert QuestionSeedChunk(seeds=[]).seeds == []
    with pytest.raises(ValidationError):
        QuestionSeedChunk(seeds=[seed(index) for index in range(7)])
    assert QuestionCandidateChunk(candidates=[]).candidates == []
    with pytest.raises(ValidationError):
        QuestionCandidateChunk(candidates=[candidate(index) for index in range(4)])
    with pytest.raises(ValidationError):
        QuestionRevisionOutput.model_validate({"candidates": [candidate(1), candidate(2)]})


def test_factory_passes_explicit_discovery_and_enrichment_budgets(stub_resolver):
    AgentFactory(stub_resolver).create(
        AgentSpec(
            role="question_generation",
            execution_name="question_discovery",
            prompt=QUESTION_DISCOVERY_PROMPT,
            response_format=QuestionSeedChunk,
            model_policy=ModelInvocationPolicy(
                max_output_tokens=2_048, request_timeout_seconds=180, max_retries=0,
            ),
        ),
        model_bindings={"question_generation": "model-1"},
    )
    assert stub_resolver.calls[-1].model_policy.max_output_tokens == 2_048
```

- [ ] **Step 3: Run the focused tests and confirm missing modules/contracts**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_sections.py tests/test_question_curation_graph.py tests/test_agent_factory.py`

Expected: FAIL because semantic sections, the two chunk contracts, revision contract, and per-Agent invocation policy do not exist.

- [ ] **Step 4: Implement section normalization, boundary rules, packing, and contracts**

```python
@dataclass(frozen=True, slots=True)
class SourceSection:
    source_id: str
    ref: str
    ordinal: int
    text: str
    digest: str


@dataclass(frozen=True, slots=True)
class DiscoveryUnit:
    unit_index: int
    sections: tuple[SourceSection, ...]
    input_digest: str


class QuestionSeed(_StrictQuestionCurationOutput):
    question_text: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)


class QuestionSeedChunk(_StrictQuestionCurationOutput):
    seeds: list[QuestionSeed] = Field(default_factory=list, max_length=6)


class QuestionCandidateChunk(_StrictQuestionCurationOutput):
    candidates: list[QuestionCandidate] = Field(default_factory=list, max_length=3)


class QuestionCandidateBatch(_StrictQuestionCurationOutput):
    candidates: list[QuestionCandidate] = Field(default_factory=list, max_length=200)


class QuestionRevisionOutput(_StrictQuestionCurationOutput):
    candidate: QuestionCandidate
```

Use compiled boundary regexes in this order: Markdown heading, whole-line `**...**`/`__...__`, numbered prefix `^\s*\d{1,3}(?:[.、]|\))\s*\S`, and a non-empty line ending in `?` or `？`. Normalize CRLF to LF; treat lines containing only whitespace, `\u200b`, `\u200c`, `\u200d`, `\ufeff`, `&nbsp;`, `<br>`, `<br/>`, or `<p>&nbsp;</p>` as blank. Prefix paragraphs become independent sections. Split overlong sections by line while preserving every non-normalized character, then hard-split a single overlong line. Derive the digest from normalized UTF-8 section text.

- [ ] **Step 5: Add distinct prompts and explicit model policies**

```python
QUESTION_DISCOVERY_PROMPT = PromptSpec(
    id="question-discovery", version="1.0",
    system=(
        "识别输入小节中可形成的独立中文面试题。每个 source_ref 最多返回一道题；"
        "纯答案、代码、占位标题或重复表达返回零题。只返回 question_text 和 source_ref，"
        "不得生成答案、topic、难度、关键点、追问或纠错说明。"
    ),
)

QUESTION_ENRICHMENT_PROMPT = PromptSpec(
    id="question-enrichment", version="1.0",
    system=(
        "把给定的最多三条 question seed 补全为结构化面试题候选。每个候选必须保留 seed 的"
        "source_ref；可以纠正明显错误并补充答案，但不得创建输入中不存在的第四道题。"
    ),
)

QUESTION_REVISION_PROMPT = PromptSpec(
    id="question-revision", version="1.0",
    system="按用户反馈只重写给定的一道候选题，返回且仅返回一个完整候选，不得扩展为多题。",
)
```

Define `ModelInvocationPolicy(max_output_tokens, request_timeout_seconds, max_retries)` in `agent_model_resolver.py`, add it to `AgentSpec`, and pass it into `ChatModelResolver.resolve`. Apply only explicitly supplied values; do not restore a global 8,192-token `question_generation` default. Map the output limit to OpenAI `max_tokens`; for Anthropic reasoning, set `max_tokens` to the thinking budget plus the requested visible-output limit because Anthropic counts thinking inside that total. Apply timeout and retry fields to both providers and preserve GLM thinking mapping. Discovery uses 2,048 visible output tokens and enrichment/revision use 4,096.

- [ ] **Step 6: Run Task 1 tests and commit**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_sections.py tests/test_question_curation_graph.py tests/test_agent_factory.py`

Expected: PASS.

```bash
git add backend/app/review/curation_sections.py backend/app/agents/question_curation_contracts.py backend/app/agents/prompts/question_curation_prompts.py backend/app/agents/agent_factory.py backend/app/agents/agent_model_resolver.py backend/tests/test_curation_sections.py backend/tests/test_question_curation_graph.py backend/tests/test_agent_factory.py
git commit -m "feat(curation): define bounded discovery contracts"
```

### Task 2: Persist Idempotent Discovery and Enrichment Work Items

**Files:**

- Create: `backend/app/db/migrations/runtime/018_progressive_question_curation.sql`
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/tests/test_runtime_migrations.py`
- Create: `backend/tests/test_curation_work_items.py`

**Interfaces:**

- Consumes: strict chunk outputs from Task 1 and existing `review_question_batches`.
- Produces: `CurationWorkItemRecord`, `plan_curation_work_item`, `start_curation_work_item`, `complete_curation_work_item`, `fail_curation_work_item`, `list_curation_work_items`, `requeue_running_curation_work_items`, and `reattach_batch_run`.

- [ ] **Step 1: Write failing migration and repository invariant tests**

```python
def test_migration_018_adds_bounded_work_items(runtime_connection):
    columns = {row[1] for row in runtime_connection.execute("PRAGMA table_info(review_curation_work_items)")}
    assert columns == {
        "id", "batch_id", "stage", "unit_index", "input_digest",
        "source_refs_json", "status", "output_json", "attempt_count",
        "last_error_code", "created_at", "updated_at",
    }
    assert runtime_connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_plan_is_idempotent_for_same_digest_and_rejects_changed_input(repository, batch):
    first = repository.plan_curation_work_item(
        batch_id=batch.id, stage="discovery", unit_index=0,
        input_digest="a" * 64, source_refs=("s1#section-0001",),
    )
    assert repository.plan_curation_work_item(
        batch_id=batch.id, stage="discovery", unit_index=0,
        input_digest="a" * 64, source_refs=("s1#section-0001",),
    ) == first
    with pytest.raises(ReviewConflictError, match="curation work item input changed"):
        repository.plan_curation_work_item(
            batch_id=batch.id, stage="discovery", unit_index=0,
            input_digest="b" * 64, source_refs=("s1#section-0001",),
        )


def test_completed_item_cannot_be_restarted_or_overwritten(repository, work_item):
    running = repository.start_curation_work_item(work_item.id)
    completed = repository.complete_curation_work_item(
        running.id, output={"seeds": [{"question_text": "什么是 MVCC？", "source_ref": "s1#section-0001"}]}
    )
    assert completed.attempt_count == 1
    assert repository.start_curation_work_item(completed.id) == completed
    with pytest.raises(ReviewConflictError):
        repository.complete_curation_work_item(completed.id, output={"seeds": []})
```

- [ ] **Step 2: Run migration/repository tests and verify the table is absent**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_runtime_migrations.py tests/test_curation_work_items.py`

Expected: FAIL because migration 018 and work-item repository APIs do not exist.

- [ ] **Step 3: Add migration 018 and typed records**

```sql
CREATE TABLE review_curation_work_items (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES review_question_batches(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('discovery', 'enrichment')),
    unit_index INTEGER NOT NULL CHECK (unit_index >= 0),
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    source_refs_json TEXT NOT NULL CHECK (
        json_valid(source_refs_json) AND json_type(source_refs_json) = 'array'
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'running', 'completed', 'failed')
    ),
    output_json TEXT CHECK (output_json IS NULL OR json_valid(output_json)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id, stage, unit_index)
);

CREATE INDEX idx_review_curation_work_items_batch_stage_status
    ON review_curation_work_items(batch_id, stage, status, unit_index);
```

```python
CurationWorkStage: TypeAlias = Literal["discovery", "enrichment"]
CurationWorkStatus: TypeAlias = Literal["pending", "running", "completed", "failed"]

@dataclass(frozen=True, slots=True)
class CurationWorkItemRecord:
    id: str
    batch_id: str
    stage: CurationWorkStage
    unit_index: int
    input_digest: str
    source_refs: tuple[str, ...]
    status: CurationWorkStatus
    output: dict[str, object] | None
    attempt_count: int
    last_error_code: str | None
    created_at: str
    updated_at: str
```

- [ ] **Step 4: Implement transactional state transitions and retry attachment**

`plan_curation_work_item` must return the existing row only when digest and refs match. `start_curation_work_item` changes `pending|failed -> running`, increments attempt count, and clears the last error; completed returns unchanged. `complete_curation_work_item` accepts only running, validates output against `QuestionSeedChunk` or `QuestionCandidateChunk` according to stage before committing, and rejects a changed completed output. `fail_curation_work_item` accepts running and stores a stable code. `requeue_running_curation_work_items(batch_id)` converts only abandoned running rows to failed with `curation_interrupted`.

Replace the one-shot batch attach behavior with an explicit retry method while preserving initial attach:

```python
def reattach_batch_run(self, batch_id: str, run_id: str) -> QuestionBatchRecord:
    with self._transaction():
        cursor = self._connection.execute(
            "UPDATE review_question_batches SET run_id = ?, status = 'generating', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'failed'",
            (run_id, batch_id),
        )
        if cursor.rowcount != 1:
            raise ReviewConflictError("question batch cannot be retried")
    self.requeue_running_curation_work_items(batch_id)
    return self.get_batch(batch_id)
```

- [ ] **Step 5: Run repository tests, migration integrity, and commit**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_runtime_migrations.py tests/test_curation_work_items.py tests/test_review_repository.py`

Expected: PASS, including `PRAGMA foreign_key_check` and restart/retry transitions.

```bash
git add backend/app/db/migrations/runtime/018_progressive_question_curation.sql backend/app/review/models.py backend/app/review/repository.py backend/tests/test_runtime_migrations.py backend/tests/test_curation_work_items.py
git commit -m "feat(curation): persist recoverable work items"
```

### Task 3: Implement the Discovery/Enrichment Agents and Explicit Graph Loop

**Files:**

- Modify: `backend/app/agents/question_curation_agent.py`
- Modify: `backend/app/graphs/question_curation.py`
- Modify: `backend/app/application/graph_factory.py`
- Modify: `backend/tests/test_question_curation_graph.py`

**Interfaces:**

- Consumes: Task 1 section/contracts/prompts, Task 2 work-item repository, `AgentContext`, and stable isolated thread configuration.
- Produces: `QuestionCurationAgents(discovery, enrichment, revision)`, `discover`, `enrich`, `revise`, and a Graph state containing only source input, work-item IDs/indexes, phase progress, candidate output, and warnings.

- [ ] **Step 1: Replace old chunking tests with failing two-stage and revision tests**

```python
@pytest.mark.asyncio
async def test_graph_runs_bounded_discovery_then_enrichment(repository, batch, context):
    agents = RecordingCurationAgents(
        discovery_outputs=[QuestionSeedChunk(seeds=[seed(1), seed(2)])],
        enrichment_outputs=[QuestionCandidateChunk(candidates=[candidate(1), candidate(2)])],
    )
    graph = create_question_curation_graph(agents, repository=repository)
    result = await graph.ainvoke(
        {"batch_id": batch.id, "source_excerpts": [dense_source(2)], "similar_questions": []},
        context=context,
    )
    assert len(agents.discovery_calls) == 1
    assert len(agents.discovery_calls[0].sections) <= 6
    assert len(agents.enrichment_calls) == 1
    assert len(agents.enrichment_calls[0].seeds) <= 3
    assert len(result["candidates"]) == 2
    assert result["generation_phase"] == "enrichment"


@pytest.mark.asyncio
async def test_retry_reuses_completed_discovery_item(repository, batch, context):
    agents = RecordingCurationAgents(
        discovery_outputs=[
            QuestionSeedChunk(seeds=[seed(1)]), FakeProviderError(),
            QuestionSeedChunk(seeds=[seed(2)]),
        ],
        enrichment_outputs=[
            QuestionCandidateChunk(candidates=[candidate(1), candidate(2)])
        ],
    )
    graph = create_question_curation_graph(agents, repository=repository)
    with pytest.raises(FakeProviderError):
        await graph.ainvoke(curation_input(batch.id, section_count=7), context=context)
    await graph.ainvoke(curation_input(batch.id, section_count=7), context=replace(context, run_id="r2"))
    assert agents.discovery_call_indexes == [0, 1, 1]
    assert repository.list_curation_work_items(batch.id, stage="discovery")[0].attempt_count == 1


@pytest.mark.asyncio
async def test_single_revision_bypasses_discovery_and_enrichment(repository, batch, context):
    agents = RecordingCurationAgents(revision_output=QuestionRevisionOutput(candidate=candidate(1)))
    graph = create_question_curation_graph(agents, repository=repository)
    result = await graph.ainvoke(
        {**curation_input(batch.id), "revision_candidate_id": "candidate-1", "rewrite_feedback": "更具体"},
        context=context,
    )
    assert len(agents.revision_calls) == 1
    assert agents.discovery_calls == []
    assert agents.enrichment_calls == []
    assert len(result["candidates"]) == 1
```

Define the test doubles in the same test module with these exact contracts:

```python
def dense_source(question_count: int) -> str:
    return "s1:questions.md\n" + "\n".join(
        f"{index}、问题 {index}？\n答案 {index}"
        for index in range(1, question_count + 1)
    )


def curation_input(batch_id: str, *, section_count: int = 2) -> dict[str, object]:
    return {
        "batch_id": batch_id,
        "source_excerpts": [dense_source(section_count)],
        "similar_questions": [],
        "rewrite_feedback": None,
    }


@dataclass(frozen=True, slots=True)
class DiscoveryCall:
    unit_index: int
    sections: tuple[SourceSection, ...]


@dataclass(frozen=True, slots=True)
class EnrichmentCall:
    unit_index: int
    seeds: tuple[QuestionSeed, ...]


class FakeProviderError(RuntimeError):
    code = "provider_error"


class RecordingCurationAgents:
    def __init__(self, *, discovery_outputs=(), enrichment_outputs=(), revision_output=None):
        self._discovery_outputs = iter(discovery_outputs)
        self._enrichment_outputs = iter(enrichment_outputs)
        self.revision_output = revision_output
        self.discovery_calls: list[DiscoveryCall] = []
        self.enrichment_calls: list[EnrichmentCall] = []
        self.revision_calls: list[object] = []

    @property
    def discovery_call_indexes(self) -> list[int]:
        return [call.unit_index for call in self.discovery_calls]

    async def discover(self, sections, *, context, config, unit_index):
        self.discovery_calls.append(DiscoveryCall(unit_index, tuple(sections)))
        output = next(self._discovery_outputs)
        if isinstance(output, Exception):
            raise output
        return output

    async def enrich(self, seeds, *, sections, known_questions, context, config, unit_index):
        self.enrichment_calls.append(EnrichmentCall(unit_index, tuple(seeds)))
        output = next(self._enrichment_outputs)
        if isinstance(output, Exception):
            raise output
        return output

    async def revise(self, *, source_excerpts, rewrite_feedback, context, config):
        self.revision_calls.append((source_excerpts, rewrite_feedback))
        return self.revision_output
```

- [ ] **Step 2: Run Graph tests and verify old one-node generation fails the contract**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_question_curation_graph.py`

Expected: FAIL because the existing Graph has only `generate_candidates` and `QuestionCurationAgent.generate` owns an unbounded batch loop.

- [ ] **Step 3: Implement three named Agents with strict reference validation**

```python
@dataclass(frozen=True, slots=True)
class QuestionCurationAgents:
    discovery: AgentRunnable
    enrichment: AgentRunnable
    revision: AgentRunnable

    async def discover(self, sections, *, context, config, unit_index) -> QuestionSeedChunk:
        result = await self.discovery.ainvoke(
            {"messages": [HumanMessage(content=render_question_discovery_input(sections))]},
            isolated_thread_config(config, context, f"question_discovery:{context.run_id}:{unit_index}"),
            context=context,
        )
        chunk = QuestionSeedChunk.model_validate(result["structured_response"])
        allowed = {section.ref for section in sections}
        if any(seed.source_ref not in allowed for seed in chunk.seeds):
            raise ValueError("question discovery returned an unknown source ref")
        if len({seed.source_ref for seed in chunk.seeds}) != len(chunk.seeds):
            raise ValueError("question discovery returned duplicate source refs")
        return chunk
```

Implement matching `enrich` and `revise` methods. Enrichment verifies every candidate has exactly one seed ref from the input and returns at most three. Revision validates exactly one `QuestionRevisionOutput`. Remove `_split_numbered_source`, `_generation_units`, the 4,000-character chunk constants, and the 50-candidate early return.

- [ ] **Step 4: Implement the explicit conditional Graph**

```text
START -> route_mode
route_mode(revision) -> revise_one -> END
route_mode(curate) -> plan_sections -> discover_next
discover_next(pending) -> discover_next
discover_next(done) -> plan_enrichment
plan_enrichment -> enrich_next
enrich_next(pending) -> enrich_next
enrich_next(done) -> reduce_candidates -> END
```

Each plan node deterministically recreates packs from `source_excerpts`, plans or reuses Task 2 work items, and returns IDs plus `generation_phase`, `completed_units`, and `total_units`. Each execution node skips completed items, claims one pending/failed item, records output, and marks only that item failed before re-raising a Provider/validation error. `plan_enrichment` reads all completed discovery outputs, validates source refs, deduplicates normalized question text, caps planned seeds at 200, and adds `{ "code": "candidate_limit_reached", "limit": 200 }` when extra seeds exist. `reduce_candidates` validates completed enrichment outputs, merges high-confidence duplicates with existing `same_question`, preserves combined evidence/key points/follow-ups, and returns a `QuestionCandidateBatch` with at most 200 entries.

`ProductionGraphFactory` passes the shared `ReviewRepository` and creates all three Agents. The `question.revise` session kind and any input with `revision_candidate_id` use the revision route.

- [ ] **Step 5: Run Graph recovery, contract, and checkpoint tests**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_question_curation_graph.py tests/test_curation_work_items.py tests/test_checkpoint_serialization.py tests/test_agent_factory.py`

Expected: PASS; completed units are not called twice, a failed unit alone increments attempts, aggregate candidates never exceed 200, and checkpoint serialization contains work-item IDs/indexes rather than work-item output copies.

- [ ] **Step 6: Commit the Graph slice**

```bash
git add backend/app/agents/question_curation_agent.py backend/app/graphs/question_curation.py backend/app/application/graph_factory.py backend/tests/test_question_curation_graph.py
git commit -m "feat(curation): run progressive discovery graph"
```

### Task 4: Integrate Progress, Same-Batch Retry, UI Phase Copy, and Real Acceptance

**Files:**

- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/tests/test_curation_session_api.py`
- Modify: `backend/tests/test_review_api_restart.py`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/features/review/CurationSessionList.tsx`
- Modify: `frontend/src/features/review/CurationSessionList.test.tsx`
- Modify: `frontend/src/features/review/CurationRuntimePanel.tsx`
- Modify: `frontend/src/features/review/CurationRuntimePanel.test.tsx`
- Modify: `docs/verification/r2-complete-review-agent.md`
- Modify: `curation-failure-handoff.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `task_plan.md`

**Interfaces:**

- Consumes: Graph `generation_phase/completed_units/total_units/warnings/candidates`, same-batch retry repository API, and JSONL traces from the preceding plan.
- Produces: `append_curation_warning(session_id, warning)`, curation resource `progress.phase`, accurate phase progress Events/UI, explicit 200-limit warning, and real Mybatis acceptance evidence.

- [ ] **Step 1: Write failing API and retry tests**

```python
@pytest.mark.asyncio
async def test_curation_resource_projects_discovery_and_enrichment_progress(api):
    session = await start_dense_curation(api)
    resource = await wait_for_generation_phase(api, session["id"], "discovery")
    assert resource["progress"] == {"phase": "discovery", "completed": 0, "total": 2}
    resource = await wait_for_generation_phase(api, session["id"], "enrichment")
    assert resource["progress"]["phase"] == "enrichment"


@pytest.mark.asyncio
async def test_retry_reattaches_failed_batch_and_reuses_completed_items(api, repository):
    failed = await fail_second_discovery_unit(api)
    old_batch_id = failed["activeBatchId"]
    completed_id = repository.list_curation_work_items(old_batch_id, stage="discovery")[0].id
    retried = await api.post(f"/api/review/curation-sessions/{failed['id']}/retry")
    assert retried.json()["activeBatchId"] == old_batch_id
    assert repository.list_curation_work_items(old_batch_id, stage="discovery")[0].id == completed_id


@pytest.mark.asyncio
async def test_candidate_limit_warning_is_visible_and_not_an_execution_failure(api):
    resource = await finish_curation_with_seed_count(api, 205)
    assert resource["executionStatus"] == "completed"
    assert resource["candidateCount"] == 200
    assert {warning["code"] for warning in resource["warnings"]} >= {"candidate_limit_reached"}
```

- [ ] **Step 2: Write failing frontend phase/warning tests**

```tsx
it("shows the current bounded generation phase", () => {
  render(<CurationRuntimePanel session={session({ progress: { phase: "discovery", completed: 2, total: 5 } })} />);
  expect(screen.getByText("正在识别题目")).toBeInTheDocument();
  expect(screen.getByText("2 / 5")).toBeInTheDocument();
});

it("explains the 200 candidate limit", () => {
  render(<CurationSessionList sessions={[session({ warnings: [{ code: "candidate_limit_reached", limit: 200 }] })]} />);
  expect(screen.getByText("已生成前 200 道候选题，请先审核当前结果")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run backend/frontend tests and verify missing phase/reuse behavior**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_session_api.py tests/test_review_api_restart.py`

Run: `cd frontend && npm test -- --run src/features/review/CurationSessionList.test.tsx src/features/review/CurationRuntimePanel.test.tsx`

Expected: FAIL because progress has no phase, retry creates a new batch, and UI has no discovery/enrichment copy or candidate-limit warning.

- [ ] **Step 4: Project Graph progress and preserve the active batch on retry**

During `AgentExecutionService` values streaming, detect changes in `(generation_phase, completed_units, total_units)`, update `review_curation_sessions` with `stage="generating"`, and publish `curation.progress.changed` with safe fields `{resourceId, phase, completed, total}`. On Graph failure, mark the currently running work item failed before the batch/session failure transition. On success, keep the existing merge/draft/summary pipeline and call `ReviewRepository.append_curation_warning(session_id, warning)` for each Graph warning; that method canonicalizes the object, returns the unchanged Session when it already exists, and appends it atomically otherwise.

Change `retry_curation_session` to call `_start_curation_execution(..., resume_batch_id=curation.active_batch_id)`. When `resume_batch_id` is present, do not create a new batch; create a new Execution, call `reattach_batch_run`, and keep completed work items. New curation and explicit rewrite still create new batches. Map source excerpts into Graph input with snake-case `batch_id` and `revision_candidate_id` while preserving existing API payloads.

Expose:

```python
"progress": {
    "phase": active_work_stage_or_none,
    "completed": record.completed_units,
    "total": record.total_units,
}
```

Update TypeScript to `progress: { phase: "discovery" | "enrichment" | null; completed: number; total: number }`. Display `正在识别题目` for discovery, `正在补全候选` for enrichment, and current existing stage labels outside generating.

- [ ] **Step 5: Run targeted and full automated regression**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_sections.py tests/test_curation_work_items.py tests/test_question_curation_graph.py tests/test_curation_session_api.py tests/test_review_api_restart.py tests/test_agent_factory.py tests/test_checkpoint_serialization.py`

Expected: PASS.

Run: `cd frontend && npm test -- --run src/features/review/CurationSessionList.test.tsx src/features/review/CurationRuntimePanel.test.tsx src/features/review/QuestionCatalog.test.tsx`

Expected: PASS.

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q`

Run: `cd frontend && npm test -- --run && npm run build`

Expected: all backend/frontend tests and production build pass. This is the final full automated regression for this increment.

- [ ] **Step 6: Validate the authorized Mybatis document locally and with the configured Provider**

Use the already authorized original Mybatis source through the product curation API, not a custom prompt script. Before the Provider run, execute the sectioner-only diagnostic and record: source characters, section count, maximum section length, discovery-unit count, duplicate-prefix count, and stable first/last refs. Expected invariants: maximum section length `<= 2000`, discovery unit sections `<= 6`, discovery characters `<= 6000`, duplicate-prefix count `0`.

Run the complete product Execution with GLM-5.2. Confirm from Runtime data and the local JSONL trace:

- every discovery response has at most 6 seeds;
- every enrichment response has at most 3 candidates;
- no trace has missing `agent_name`, and discovery/enrichment are distinguishable;
- a forced failure/retry does not add a second model request for an already completed work item;
- final candidate count is at most 200 and any cap is visible as `candidate_limit_reached`;
- candidates enter the existing review, draft, source-link, and publication flows.

Do not copy source/request/response bodies into the local verification artifact. Record only IDs, counts, timings, usage, stable Provider request IDs, and pass/fail results in `docs/verification/r2-complete-review-agent.md`.

- [ ] **Step 7: Refresh failure handoff and project tracking facts**

Update `curation-failure-handoff.md` from “unresolved single-stage 400” to the implemented architecture, test evidence, JSONL location, remaining Provider limitations, and exact reproduction IDs. Update `findings.md`, `progress.md`, and `task_plan.md` with product status, maturity boundary, next R3 task, and the fact that user learning remains non-blocking. Do not modify `docs/my_idea.md`.

- [ ] **Step 8: Run final hygiene checks and commit**

Run: `git diff --check`

Run: `rg -n 'T[B]D|T[O]DO|P[L]ACEHOLDER|fill[ -]in' docs/superpowers/plans/2026-07-21-r2-progressive-question-curation.md backend/app backend/tests frontend/src/features/review`

Expected: no new placeholder matches in changed files and no whitespace errors.

```bash
git add backend/app/application/execution_service.py backend/app/review/application.py backend/app/review/repository.py backend/tests/test_curation_session_api.py backend/tests/test_review_api_restart.py frontend/src/features/review/reviewTypes.ts frontend/src/features/review/CurationSessionList.tsx frontend/src/features/review/CurationSessionList.test.tsx frontend/src/features/review/CurationRuntimePanel.tsx frontend/src/features/review/CurationRuntimePanel.test.tsx findings.md progress.md task_plan.md
git commit -m "fix(curation): complete recoverable progressive pipeline"
```

Keep `docs/verification/r2-complete-review-agent.md` and `curation-failure-handoff.md` synchronized as local diagnostic artifacts; do not stage or commit them.
