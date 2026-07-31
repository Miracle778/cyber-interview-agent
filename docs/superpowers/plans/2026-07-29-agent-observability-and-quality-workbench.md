# Agent Observability and Quality Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a project-wide Agent Run Center, advanced trace explorer, quality evaluation lab, and trace retention/projection controls as four independently usable vertical slices.

**Architecture:** Per-Execution JSONL remains the authoritative detailed ledger. A rebuildable workspace SQLite index provides queries and summaries. Business truth continues to come from `agent_runs`, domain tables, usage projections, and artifacts; the trace index never becomes a second runtime. Evaluation reads frozen executions through an isolated read-only runtime and writes only evaluation-domain records.

**Tech Stack:** FastAPI, Pydantic v2, SQLite/WAL migrations, LangChain/LangGraph middleware, OpenTelemetry, React 19, TypeScript, TanStack Query, React Router, Vitest, Playwright.

> **2026-07-31 maturity note:** Slice 3 delivered v1 historical-result review, not candidate business-Agent replay. Evaluation v2 and real regression are planned separately in `2026-07-31-agent-evaluation-v2-migration.md`.

## Global Constraints

- Formal product contract: `docs/superpowers/specs/2026-07-29-agent-observability-and-quality-workbench-design.md`.
- Architecture boundary: `docs/superpowers/architecture-decisions/2026-07-29-agent-trace-ledger-and-evaluation-boundaries.md`.
- Visual references:
  - `docs/superpowers/assets/agent-observability/agent-run-center-reference.png`
  - `docs/superpowers/assets/agent-observability/execution-trace-explorer-reference.png`
  - `docs/superpowers/assets/agent-observability/quality-evaluation-lab-reference.png`
- Do not modify `docs/my_idea.md`.
- Do not write trace metadata back into `agent_runs`, messages, checkpoint state, profile, question bank, knowledge, job-target, or review domain tables.
- Do not show or calculate monetary cost. Token, context, latency, call count, and retry count remain visible.
- Never persist secrets. Advanced mode may disclose stored prompt/message/tool/provider bodies only after server-side workspace and path validation.
- Never fabricate model reasoning. Show only fields actually returned by the Provider.
- No dead controls. Every visible control is derived from the Agent Observability Registry and current execution capability.
- All displayed timestamps use Asia/Shanghai through the existing shared formatter.
- Use targeted tests while implementing. Full backend/frontend regression is permitted only after cross-slice integration and before final acceptance.
- Update local `docs/verification/agent-observability-and-quality-workbench.md` after each slice; do not include that local verification file in ordinary product commits.

---

## Delivery Map

| Slice | User-visible outcome | Required predecessor | Detailed plan |
|---|---|---|---|
| 1 | Global Agent Run Center and read-only execution trace | None | `2026-07-29-agent-observability-slice-1-run-center.md` |
| 2 | Advanced input/output/tool inspection, copy, export, local switch | Slice 1 | `2026-07-29-agent-observability-slice-2-advanced-trace.md` |
| 3 | Eval Packs, manual/automatic Judge, regression cases, version comparison | Slice 2 | `2026-07-29-agent-observability-slice-3-quality-evaluation.md` |
| 4 | Retention, cleanup receipts, external safe projection, long-term trends | Slice 3 | `2026-07-29-agent-observability-slice-4-retention-and-projection.md` |

## Shared Contract Locked Before Slice 1

### Business execution

One row in `agent_runs` is one top-level Execution. It is the unit counted on the Run Center. Model invocations, tools, subgraphs, and system Agents are child Operations, never additional top-level executions.

### Registry

Create one code registry that declares:

```python
@dataclass(frozen=True, slots=True)
class AgentObservabilityRegistration:
    graph_id: str
    display_name: str
    route_template: str
    capabilities: frozenset[Literal[
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
    ]]
    eval_pack_id: str | None
    system_components: tuple[str, ...]
```

Every production `graph_id` must have exactly one registration. Tests fail when a graph is registered in the runtime but absent from observability.

### Trace hierarchy

The next emitted trace schema is v3:

```json
{
  "schema_version": 3,
  "event_id": "uuid",
  "operation_id": "uuid",
  "parent_operation_id": "uuid-or-null",
  "operation_kind": "execution|agent|model|tool|graph",
  "event_type": "model.request",
  "payload": {}
}
```

The reader remains compatible with v1/v2 rows. It synthesizes a stable operation key from `run_id + invocation_id + operation_kind` when hierarchy fields are missing. Existing files are not rewritten.

### Query index

SQLite stores searchable metadata and byte pointers only:

- execution identity/status/display metadata;
- operation hierarchy, type, role, timing, status, and aggregate usage;
- event type, time, file-relative path, byte start/length, payload hash;
- per-file scan offset and last complete sequence.

The indexer:

- scans only completed newline-terminated rows;
- leaves a crash-torn trailer for the next pass;
- records malformed completed rows as gaps instead of failing the business run;
- updates one trace file in a short transaction;
- can rebuild entirely from JSONL;
- is invoked at workspace startup, before list/detail queries, and by the SSE polling loop;
- never runs inside `AgentTraceWriter.append()`.

### Execution summary authority

`ExecutionSummaryAssembler` merges:

- status/progress/result/artifacts: `agent_runs`, `agent_events`, and domain projections;
- model usage: `model_invocation_usage`;
- context: `agent_context_usage`;
- operation latency/retries/errors: trace index;
- labels/routes/capabilities: registry.

When trace is absent or damaged, the execution remains visible with `traceHealth=missing|partial`; business status is never downgraded.

## Cross-Slice Acceptance

- [x] All production graph IDs are registered.
- [x] An execution remains visible when its JSONL is missing, corrupt, or temporarily unindexed.
- [x] A new trace event becomes visible without reloading the whole application.
- [x] The global list counts business executions, not model/tool calls.
- [x] Normal mode shows safe summaries; advanced mode shows allowed stored bodies.
- [x] Manual Judge is available for supported executions without pretending to be the business Agent.
- [x] Judge failure cannot change the business execution result.
- [x] No UI or API reports cost.
- [x] 390, 768, 1024, and 1440 widths have no page-level horizontal overflow.
- [x] One minimal browser path is recorded after each slice and one complete browser acceptance pass is recorded before closure.

## Commit and Integration Policy

Each detailed plan ends in a reviewable product commit. Do not combine all four slices into one commit. After every slice:

1. run only the listed targeted tests;
2. update the local verification record;
3. inspect `git diff --stat` and `git diff --check`;
4. compare the implemented page with the corresponding reference image;
5. commit only the slice and formal `docs/superpowers/` changes.

Final stage closure additionally runs:

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/agent-observability-and-quality-workbench.md \
  --learning docs/learning/agent-observability-and-quality-workbench/ \
  --plan docs/superpowers/plans/2026-07-29-agent-observability-and-quality-workbench.md
```
