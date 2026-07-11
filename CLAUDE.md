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

Before stage closure, use `docs/superpowers/templates/stage-verification-template.md` and `docs/superpowers/templates/stage-learning-pack-template.md`, compare the result with the previous stage, then run `python3 scripts/check_stage_docs.py --verification docs/verification/<stage>.md --learning docs/learning/<stage>/`. Do not replace the final user guide with a Task log or the seven-file learning pack with one README. A failed gate blocks “ready for manual verification”; user exercises remain non-blocking.
