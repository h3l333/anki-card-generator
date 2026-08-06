# Diagrams

PlantUML (`.puml`) source files documenting this project's architecture and
workflows- written for learning purposes as the project is built, kept even
after the code they describe changes, rather than treated as disposable
scratch work.

## Conventions

- One `.puml` file per diagram, named for what it depicts rather than its
  diagram type, e.g. `generate-flow.puml`, `db-schema.puml`, not
  `sequence1.puml`. Kebab-case, matching this repo's other file names.
- No subfolders yet- flat is enough for the current number of diagrams. Split
  into subdirectories (e.g. by workflow vs. schema vs. component) once there
  are enough files that a flat list stops being easy to scan, rather than
  guessing at categories now.
- Source files only. Rendered output (`.png`/`.svg`) isn't committed here-
  regenerate from the `.puml` source instead (e.g. the PlantUML VS Code
  extension, the `plantuml` CLI/jar, or pasting into
  [plantuml.com](https://www.plantuml.com/plantuml)), so the diagram's text
  representation stays the single source of truth instead of drifting out of
  sync with a stale exported image.

## Related docs

`ARCHITECTURE.md` and `DATABASE.md` (project root) describe the same
system in prose; these diagrams are a visual complement, not a replacement-
expect some duplication between the two rather than one deferring to the
other.
