# R3 Profile Material UI — Design QA

- Source visual truth: `docs/superpowers/assets/r3/resume-version-reference.png`
- Implementation screenshots: `docs/verification/assets/r3/profile-versions-390.jpg`, `profile-versions-768.jpg`, `profile-versions-1024.jpg`, `profile-versions-1440.jpg`
- Viewports: 390×844, 768×900, 1024×900, 1440×1000 CSS px
- Density normalization: source 1488×1058 and desktop implementation 1440×1000 were compared as full desktop views at deviceScaleFactor 1; responsive captures use their named CSS width at deviceScaleFactor 1.
- State: one active résumé, version 1 selected, ingest stopped because the profile extraction model is not configured.

**Findings**

- No actionable P0/P1/P2 mismatch remains. The desktop view preserves the reference hierarchy: fixed product sidebar, page tabs, version list, largest document/status region, and a narrow action rail. The failed execution replaces the reference's completed preview and diff data intentionally, using the same grid rather than inventing unavailable product data.
- Fonts and typography: existing Inter/system stack, 28 px page title level, 16–18 px section hierarchy, and 12–14 px dense metadata match the product reference and remain readable.
- Spacing and layout rhythm: desktop three-column proportions track the reference; 768–1024 collapse the action rail without losing the primary task; 390 becomes a single labeled-card flow. Measured page `scrollWidth === clientWidth` at all four widths.
- Colors and tokens: existing blue-gray surfaces, primary blue selection, green completion, and semantic red failure tokens are used consistently. Red is limited to a real terminal failure, not an in-progress stage.
- Image and icon fidelity: the screen contains no raster content from the reference. UI icons use the existing Lucide library used throughout the product; no placeholder artwork or handcrafted SVG/CSS illustration was introduced.
- Copy and content: upload, retry, privacy, and failure text explain what happened and how to recover. Internal paths, Tool arguments, and model reasoning are not exposed.

**Open Questions**

- Populated Evidence preview and successful multi-version comparison depend on a configured `profile_extraction` model and later R3 Claim/diff APIs. Their empty and failure states are implemented now; populated claim review belongs to the next tasks.

**Comparison History**

1. Initial browser pass found a P1 state mismatch: a graph-construction failure left the material marked as processing, causing indefinite polling. The execution failure path now persists a retryable material terminal status, and the page explains that the uploaded file is retained.
2. Post-fix screenshots show the terminal state inline in the version workspace, with retry guidance and no page-level horizontal overflow at 390, 768, 1024, or 1440 px.

**Implementation Checklist**

- [x] Desktop reference hierarchy preserved.
- [x] Mobile controls remain reachable and at least 44 px high.
- [x] Keyboard-selectable version rows and visible focus styles retained.
- [x] Failure, loading, empty, upload, retry, archive/restore, primary-version, and Evidence locator behavior covered by focused tests or browser evidence.
- [x] Browser console has no warning or error entries.

**Follow-up Polish**

- P3: compare the populated document/Evidence view again after a development profile model is configured and Task 10 exposes real Claim proposals.

final result: passed
