# README visual assets

The first three PNG files are generated README whiteboard diagrams. Product
screenshots are generated from the isolated fictional workspace created by
`scripts/seed_readme_demo.py`.

Visual language:

- light-gray graph paper and hand-drawn dark marker ink;
- blue for Agents, context and data flow;
- green for confirmed, trusted state;
- red only for failure, risk, conflicts and forbidden paths;
- gray dotted borders for planned capabilities.

`09-system-technical-architecture.png` is the component-level architecture
diagram. Unlike the whiteboard diagrams, it uses a compact layered system view
so API, orchestration, runtime, data ownership, providers, tracing and quality
evaluation can be explained from one image without implying that diagnostic
state is a second source of business truth.
