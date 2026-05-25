# Domain Docs: Single-Context Layout

tequila-mule uses a single-context layout for domain documentation:

- **`CONTEXT.md`** (repo root) — domain language, key concepts, architectural invariants
- **`docs/adr/`** (repo root) — Architecture Decision Records

## When Skills Read These Files

Skills that consume domain docs:

- **`improve-codebase-architecture`** — reads `CONTEXT.md` + `docs/adr/` to understand the project's language and past decisions
- **`grill-with-docs`** — grilling session that challenges plans against domain model, updates `CONTEXT.md` and ADRs inline
- **`diagnose`** — reads domain context to ground root-cause analysis
- **`tdd`** — reads domain context to write tests aligned with project invariants

## CONTEXT.md

Start with high-level project overview, domain terms, and architectural constraints. Example structure:

```markdown
# tequila-mule Context

## Project Vision
[1-2 sentences on why this exists]

## Key Concepts
- **Concept A:** Definition and why it matters
- **Concept B:** Definition and why it matters

## Architectural Constraints
- [Constraint 1]
- [Constraint 2]

## Core Invariants
- [Invariant 1: what must always be true]
- [Invariant 2: what must always be true]
```

## docs/adr/

Architecture Decision Records document significant decisions. Use [ADR template](https://adr.github.io/madr/) or your own, but include:

- **Status:** Accepted / Proposed / Superseded
- **Context:** Why this decision was needed
- **Decision:** What was decided
- **Consequences:** Tradeoffs, what changed

Example: `docs/adr/001-rolling-job-rotation.md`
