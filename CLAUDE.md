# Claude Code Project Instructions

This repository uses a shared dual-track development workflow.

Before doing any project work, read and follow:

1. `AGENTS.md`
2. `docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`
3. `task_plan.md`
4. `findings.md`
5. `progress.md`
6. The current stage spec and implementation plan

`AGENTS.md` is the concise cross-agent rule entry. The design spec is the single detailed source of truth. Do not let user learning exercises block product development. Concurrent learning uses one active learning worktree, and each learning branch starts from its own stage completion baseline rather than another learning branch. Work only from the minimal repository context required for the assigned task, and leave review and final acceptance to Codex.

For every product slice, incrementally maintain the ignored local file `docs/verification/<stage>.md`. After a branch merge, explicitly synchronize it into the main repository and verify the target exists; the product delivery is not closed until Codex confirms that synchronization.
