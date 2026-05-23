# ADR Format

Use ADRs to record durable architecture decisions that future reviews should respect or consciously revisit. Store them under `docs/adr/` unless the repo already has a different ADR location.

Recommended filename:

```text
NNNN-short-kebab-title.md
```

Recommended shape:

```markdown
# NNNN. Title

Date: YYYY-MM-DD

## Status

Accepted

## Context

What pressure, constraint, or recurring design question led to this decision?

## Decision

What decision did the team make?

## Consequences

What becomes easier, what becomes harder, and what should future agents avoid re-suggesting?
```

Offer an ADR only for load-bearing reasons. Avoid recording temporary priority calls or obvious constraints.
