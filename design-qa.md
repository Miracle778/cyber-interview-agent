# R2 Question Workspace Design QA

## Scope

- Selected source: `/Users/miracle778/.codex/generated_images/019f52f0-5368-7361-806d-3cfe8bd36e9d/exec-9f0f60c8-3773-4bee-87d2-351ea3d7f21f.png`
- Implementation capture: `/Users/miracle778/.codex/visualizations/2026/07/11/019f52f0-5368-7361-806d-3cfe8bd36e9d/r2-question-workspace-option-3.png`
- Corrected chat capture: `/Users/miracle778/.codex/visualizations/2026/07/11/019f52f0-5368-7361-806d-3cfe8bd36e9d/r2-review-chat-corrected.png`
- Side-by-side comparison: `/Users/miracle778/.codex/visualizations/2026/07/11/019f52f0-5368-7361-806d-3cfe8bd36e9d/r2-question-workspace-comparison.png`
- Viewport: 1487 × 1058 for both source and implementation.
- State: active three-question review round, first question waiting for a follow-up answer, feedback expanded.

## Comparison

### Full-page hierarchy

- Passed: persistent product navigation remains on the left.
- Passed: compact review toolbar replaces the previous stacked page header and card navigation.
- Passed: horizontal question progress establishes the active-question context before the workspace.
- Passed: conversation is the dominant surface; feedback is a narrower supporting column.
- Passed: the answer composer stays at the bottom of the conversation surface.

### Focused component checks

- Passed: active step, progress line, review tabs, history action, and overflow action preserve the selected reference hierarchy.
- Passed: user and interviewer turns use restrained editorial rows instead of nested chat cards.
- Passed: mastery, missing key points, model binding, reasoning effort, and token usage are grouped in the feedback rail.
- Passed: long real evaluation content scrolls inside the conversation rather than growing the whole page.
- Passed: feedback collapses and expands without leaving the active round.
- Passed: entering a draft enables the send action; clearing the draft disables it again.
- Passed: no visible runtime error banner appeared in the accepted state.

## Iteration history

1. Replaced the persistent history/runtime three-column composition with the selected question-workspace hierarchy.
2. Limited immersive layout to initialized workspaces so disconnected and setup states retain their diagnostic page header.
3. Updated component and application tests to assert the new progress and feedback contracts.
4. Compared source and implementation at identical size. Real runtime content is intentionally denser than the generated reference; internal scrolling and truthful backend-provided labels were retained.
5. User review found that the editorial message rows and detached form-like composer did not read as chat. Reworked the conversation into left/right avatar bubbles, added timestamps and an Agent typing state, auto-scrolled to the latest message, and docked a compact composer to the bottom of the conversation.
6. Browser review exposed one legacy selector forcing message metadata beside the bubble. Increased selector specificity, reloaded the real round, and confirmed metadata sits above each bubble without vertical text.

## Severity review

- P0: none.
- P1: none.
- P2: none requiring correction. Differences in copy length, question availability, model display, and token totals come from live product data rather than visual drift.

Browser console capture is not exposed by the selected in-app browser runtime. The fallback checks were a clean TypeScript compile, passing targeted tests, a successful live DOM interaction pass, and absence of the product error banner.

Final result: passed.
