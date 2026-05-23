# CONTEXT.md Format

Use `CONTEXT.md` to define domain language for the repository. Keep it concise and practical so future architecture reviews can reuse the same words.

Recommended shape:

```markdown
# Context

## Domain Language

### Term

Definition of the domain concept, including what it includes, what it excludes, and where it appears in the codebase.
```

Guidelines:

- Prefer domain nouns over implementation names.
- Add terms only when they help name a real module, interface, workflow, or invariant.
- Update a term immediately when conversation reveals a sharper definition.
- Keep examples short and tied to files or workflows in the repo.
