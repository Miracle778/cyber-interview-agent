# Agent 可观测工作台 — Design QA

## 任务运行方案 A

- Source visual truth: `docs/superpowers/assets/agent-observability/run-center-selected-reference.png`
- Rendered desktop: `docs/superpowers/assets/agent-observability/run-center-implementation-desktop.jpg`
- Rendered mobile: `docs/superpowers/assets/agent-observability/run-center-implementation-mobile.jpg`
- Side-by-side comparison: `docs/superpowers/assets/agent-observability/run-center-design-comparison.jpg`
- Route: `/agents`
- Viewports: 1487×1058 desktop and 390×844 mobile
- State: development workspace with 27 visible business executions, five tasks requiring attention, and the selected failed curation execution.

### Findings

- No actionable P0/P1/P2 mismatch remains after comparing the selected source and rendered desktop at the same viewport.
- The final hierarchy matches the selected concept: owner-friendly heading, prioritized action center, stable status tabs, searchable task list, and a full-height progressive-disclosure detail pane.
- The action count and rows use current API data. The rendered implementation shows five actionable tasks while the concept image shows two; this is a real-data difference rather than a layout mismatch.
- Status tabs remain visible after selection and filter locally over the loaded execution summaries, so selecting one state cannot erase the other facets.
- Generated trace filenames are replaced with Agent-level task names, while ordinary Markdown/text suffixes are removed.
- The detail pane leads with current outcome and next step. Token, context, error code, and advanced trace navigation stay under “查看技术详情”.
- Capabilities remain authoritative: business-page, manual quality check, and advanced-detail actions only appear when supported by the execution summary.
- Closing the desktop detail pane persists until another task is selected. At widths below 1024 px, the list opens by default and task selection opens an accessible full-screen detail layer.
- The 390 px pass verified the compact action list, horizontally stable status tabs, mobile task cards, full-screen detail, and 390 px bottom-sheet filter.
- Final page reload produced no new browser warning or error entries.

### Comparison History

1. The first rendered pass placed the action center above both columns, which made the detail pane start below the source hierarchy.
2. The second pass moved the detail pane to the outer workspace so it spans the action center and task list, matching the selected composition.
3. The narrow pass exposed a reserved desktop detail track and a hidden close action. Responsive initialization and overlay stacking were corrected, then the list, detail layer, and filter sheet were rechecked.

### Implementation Checklist

- [x] “需要你处理” is based on real waiting, partial, and failed states.
- [x] Status tabs remain stable and show real counts before interaction.
- [x] Search, Agent/status filters, and system-Agent inclusion work.
- [x] Friendly task/result copy replaces trace-centric list metadata.
- [x] Existing business, quality, and advanced diagnostics links remain reachable.
- [x] Desktop layout matches the selected reference hierarchy.
- [x] 390 px mobile layout has no page-level horizontal overflow.
- [x] Core controls, detail closing/reopening, and filter-sheet interactions work.
- [x] Final browser reload has no new warning or error entries.

## 运行质量方案 1

- Source visual truth: `docs/superpowers/assets/agent-observability/quality-overview-selected-reference.png`
- Route: `/agents/evaluations`
- Viewports: 1524×1032 desktop and 390×844 mobile
- State: development workspace with 27 executions in the selected seven-day range, including one completed evaluation that needs attention, one failed evaluation, feedback, and a metadata-only regression case.

## Findings

- No actionable P0/P1/P2 mismatch remains after the final side-by-side comparison.
- “任务运行” remains one primary module. “运行中心” and “运行质量” are sibling tabs; the evaluation workbench is preserved behind the secondary “评估工具” action.
- The overview follows the approved hierarchy: summary counts, time range, Agent filters, recent quality trend, attention list, recent results, and a 320 px progressive-disclosure detail drawer.
- All overview numbers derive from current execution and evaluation APIs. “需要关注” only counts completed/failed checks with an actionable issue; unchecked executions remain a separate state.
- Generated source hashes are not shown as primary task names. Known synthetic source titles receive an Agent-level task label, and ordinary text/Markdown filenames lose their file extension.
- The detail drawer keeps the primary issue verbatim but limits the impact summary to a readable excerpt. Full dimensions, evidence, feedback, comparison, trends, and regression cases remain available in “评估工具”.
- Native select controls use the shared `SelectControl` styling. The time range and Agent filters update the overview without navigation.
- At 1524 px, `scrollWidth === clientWidth === 1524`; the drawer is exactly 320 px and the summary title stays on one line.
- At 390 px, `scrollWidth === clientWidth === 390`; cards stack, filters scroll inside their own row, and primary controls remain at least 44 px high.
- Browser interaction verified: Agent filtering, time-range selection, opening tools, returning to overview, closing the detail drawer, and reopening it.
- Browser console warning/error count was zero on the final desktop pass.

## Comparison History

1. Initial implementation joined real execution and evaluation data but counted unchecked runs in the “需要关注” list, exposed synthetic source filenames, and allowed the shared full-width select wrapper to compress the overview title.
2. The first browser pass separated actionable attention from unchecked runs, normalized synthetic task names, and constrained the time-range control.
3. The final side-by-side pass shortened the drawer impact excerpt, applied warning semantics to the summary health label, and confirmed the selected desktop hierarchy against the approved reference.

## Implementation Checklist

- [x] One “任务运行” module with sibling center/quality tabs.
- [x] Owner-friendly overview is the default surface.
- [x] Existing professional evaluation capabilities remain reachable.
- [x] Real API data only; no invented quality counts.
- [x] Attention and unchecked states remain semantically distinct.
- [x] Desktop layout matches the approved reference hierarchy.
- [x] 390 px mobile layout has no page-level horizontal overflow.
- [x] Core controls and progressive-disclosure interactions work.
- [x] Console has no warning or error entries.

final result: passed
