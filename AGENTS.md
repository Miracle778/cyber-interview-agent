# Cyber Interview Agent Collaboration Rules

## Required Session Startup

Before planning, editing, delegating, or answering project-status questions, read in order:

1. Run `git worktree list`, `git status --short`, and `git log -5 --oneline` to locate the authoritative worktree.
2. Read `task_plan.md`, `findings.md`, and `progress.md` from that worktree.
3. Read the current stage spec and implementation plan.
4. Read `docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md` only when workflow interpretation or modification is required.

Historical planning files under `docs/superpowers/history/` are not startup inputs. Read them only to investigate a specific past decision.

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
- Before closing a stage, reshape verification as the final user guide, generate the seven-file learning pack from the formal templates, compare both with the previous stage, and run `python3 scripts/check_stage_docs.py --verification docs/verification/<stage>.md --learning docs/learning/<stage>/`. A failed gate blocks the “ready for manual verification” status; unfinished user exercises do not.
- Use targeted tests during tasks. Run full backend/frontend regression at most twice per stage: once after cross-layer integration when needed and once before final acceptance.
- Run one minimal browser happy path before final documentation, then one complete browser acceptance pass. Re-run only affected scenarios after fixes.
- Default to one Agent owning a slice end-to-end. Do not hand off mid-task or create subagents unless work is genuinely independent and non-overlapping.
- Use a skill only when installed and clearly applicable. State its purpose, expected artifact, and exit condition; stop after two unchanged failures and diagnose instead of retrying.
- Keep tool output focused: locate with `rg`/`git diff --stat`, read only risk files, and default to quiet tests and approximately 4,000 output tokens.
- Before stage closure, run `python3 scripts/check_stage_docs.py --verification docs/verification/<stage>.md --learning docs/learning/<stage>/ --plan <current-plan>`. Unchecked browser acceptance or inconsistent evidence blocks “ready for manual verification”.

## Completion Reporting

Report separately:

- Product status and verification evidence
- Product maturity boundary
- Ownership status: learned, pending learning, pending practice
- Next product task
- Non-blocking user exercise
