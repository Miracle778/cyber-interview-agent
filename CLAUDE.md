# Claude Code Project Instructions

This repository uses a shared dual-track development workflow.

Before doing any project work, read and follow:

1. `AGENTS.md`
2. Locate the authoritative worktree with Git status and recent commits.
3. `task_plan.md`, `findings.md`, and `progress.md` from that worktree.
4. The current stage spec and implementation plan.
5. The dual-track workflow spec only when workflow interpretation is required.

`AGENTS.md` is the concise cross-agent rule entry. The design spec is the single detailed source of truth. Do not let user learning exercises block product development. Concurrent learning uses one active learning worktree, and each learning branch starts from its own stage completion baseline rather than another learning branch. Work only from the minimal repository context required for the assigned task, and leave review and final acceptance to Codex.

For every product slice, incrementally maintain the ignored local file `docs/verification/<stage>.md`. After a branch merge, explicitly synchronize it into the main repository and verify the target exists; the product delivery is not closed until Codex confirms that synchronization.

Use targeted tests during implementation and reserve full regressions for integration/final acceptance. One Agent owns a slice end-to-end by default. Do not search for or invoke a skill that is not installed; every used skill needs an explicit exit condition, and two unchanged failures trigger diagnosis rather than retry.

Before stage closure, classify the seven-file learning pack with the formal template's risk profile, generate it after implementation stabilizes, compare it with the previous same-profile stage, and run `python3 scripts/check_stage_docs.py --verification docs/verification/<stage>.md --learning docs/learning/<stage>/ --plan <current-plan>`. Do not claim browser acceptance while its plan step is unchecked. User exercises remain non-blocking.
