# Cyber Interview Agent Collaboration Rules

## Required Session Startup

Before planning, editing, delegating, or answering project-status questions, read in order:

1. `docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`
2. `task_plan.md`
3. `findings.md`
4. `progress.md`
5. The current stage spec and implementation plan
6. Current Git branch, status, and recent commits

Repository files and executable state are authoritative. Do not reconstruct project state from chat memory alone.

## Non-Negotiable Workflow

- Keep product delivery and user ownership as separate tracks.
- User learning exercises never block implementation, commits, merges, or the next product stage.
- When product development and learning run concurrently, keep only one active learning worktree; create each learning branch from its own stage completion baseline, never from another learning branch.
- Record unfinished learning as understanding debt.
- Generate or update the local `docs/learning/<stage>/` ownership pack after each major stage.
- Batch product and architecture questions when possible and provide recommended defaults.
- Codex owns complex cross-layer work, critical state machines, security boundaries, review, and acceptance.
- Claude may implement ordinary bounded tasks with minimal required context; Codex reviews and verifies the result.
- Keep frontend behavior evolving with backend capabilities.
- Never modify or commit `docs/my_idea.md`.
- Only commit formal documents under `docs/superpowers/`; keep `docs/learning/` and `docs/verification/` local and sync them explicitly after branch merges.
- Maintain one incremental `docs/verification/<stage>.md` per product slice. Update it after every task, refresh final evidence before completion, and verify it is explicitly synchronized into the main repository after merges; delivery is not closed until this check passes.

## Completion Reporting

Report separately:

- Product status and verification evidence
- Product maturity boundary
- Ownership status: learned, pending learning, pending practice
- Next product task
- Non-blocking user exercise
