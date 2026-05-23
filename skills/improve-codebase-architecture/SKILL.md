---
name: improve-codebase-architecture
description: Find deepening opportunities in a codebase, informed by the domain language in CONTEXT.md and the decisions in docs/adr/. Use when the user wants to improve architecture, find refactoring opportunities, consolidate tightly-coupled modules, or make a codebase more testable and AI-navigable.
---

# Improve Codebase Architecture

Surface architectural friction and propose deepening opportunities, meaning refactors that turn shallow modules into deep ones. The aim is testability and AI-navigability.

## Glossary

Use these terms exactly in every suggestion. Consistent language is the point. Do not drift into "component," "service," "API," or "boundary." Full definitions live in [LANGUAGE.md](LANGUAGE.md).

- **Module**: anything with an interface and an implementation, such as a function, class, package, or slice
- **Interface**: everything a caller must know to use the module, including types, invariants, error modes, ordering, and config. Not just the type signature
- **Implementation**: the code inside
- **Depth**: leverage at the interface. A lot of behavior behind a small interface. Deep means high leverage. Shallow means the interface is nearly as complex as the implementation
- **Seam**: where an interface lives, a place behavior can be altered without editing in place. Use this term instead of "boundary"
- **Adapter**: a concrete thing satisfying an interface at a seam
- **Leverage**: what callers get from depth
- **Locality**: what maintainers get from depth. Change, bugs, and knowledge concentrated in one place

Key principles, with fuller detail in [LANGUAGE.md](LANGUAGE.md):

- **Deletion test**: imagine deleting the module. If complexity vanishes, it was a pass-through. If complexity reappears across many callers, it was earning its keep
- **The interface is the test surface**
- **One adapter equals a hypothetical seam. Two adapters equals a real seam**

This skill is informed by the project's domain model. The domain language gives names to good seams. ADRs record decisions the skill should not re-litigate.

## Process

### 1. Explore

Read the project's domain glossary and any ADRs in the area you are touching first.

Then use the Agent tool with `subagent_type=Explore` to walk the codebase. Do not follow rigid heuristics. Explore organically and note where you experience friction:

- Where does understanding one concept require bouncing between many small modules?
- Where are modules shallow, with an interface nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, but the real bugs hide in how they are called, meaning there is no locality?
- Where do tightly-coupled modules leak across their seams?
- Which parts of the codebase are untested, or hard to test through their current interface?

Apply the deletion test to anything you suspect is shallow. Would deleting it concentrate complexity, or just move it? "Yes, concentrates" is the signal you want.

### 2. Present candidates as an HTML report

Write a self-contained HTML file to the OS temporary directory so nothing lands in the repo. Resolve the temp directory from `$TMPDIR`, falling back to `/tmp`, or `%TEMP%` on Windows, and write to `<tmpdir>/architecture-review-<timestamp>.html` so each run gets a fresh file. Open it for the user with `xdg-open <path>` on Linux, `open <path>` on macOS, or `start <path>` on Windows, and tell them the absolute path.

The report uses Tailwind via CDN for layout and styling, and Mermaid via CDN for diagrams where a graph, flow, or sequence reliably communicates the structure. Mix Mermaid with hand-crafted CSS or SVG visuals. Use Mermaid when relationships are graph-shaped, such as call graphs, dependencies, and sequences. Use hand-built divs or SVG when you want something more editorial, such as mass diagrams, cross-sections, or collapse animations. Each candidate gets a before and after visualization. Be visual.

For each candidate, render a card with:

- **Files**: which files or modules are involved
- **Problem**: why the current architecture is causing friction
- **Solution**: plain English description of what would change
- **Benefits**: explained in terms of locality and leverage, and how tests would improve
- **Before / After diagram**: side-by-side, custom-drawn, illustrating the shallowness and the deepening
- **Recommendation strength**: one of `Strong`, `Worth exploring`, or `Speculative`, rendered as a badge

End the report with a **Top recommendation** section that explains which candidate you would tackle first and why.

Use `CONTEXT.md` vocabulary for the domain, and [LANGUAGE.md](LANGUAGE.md) vocabulary for the architecture. If `CONTEXT.md` defines "Order," talk about "the Order intake module," not "the FooBarHandler," and not "the Order service."

For ADR conflicts, if a candidate contradicts an existing ADR, only surface it when the friction is real enough to warrant revisiting the ADR. Mark it clearly in the card, for example: "contradicts ADR-0007, but worth reopening because..." Do not list every theoretical refactor an ADR forbids.

See [HTML-REPORT.md](HTML-REPORT.md) for the full HTML scaffold, diagram patterns, and styling guidance.

Do not propose interfaces yet. After the file is written, ask the user: "Which of these would you like to explore?"

### 3. Grilling loop

Once the user picks a candidate, drop into a grilling conversation. Walk the design tree with them: constraints, dependencies, the shape of the deepened module, what sits behind the seam, and which tests survive.

Side effects happen inline as decisions crystallize:

- **Naming a deepened module after a concept not in `CONTEXT.md`?** Add the term to `CONTEXT.md`. See [CONTEXT-FORMAT.md](CONTEXT-FORMAT.md). Create the file lazily if it does not exist
- **Sharpening a fuzzy term during the conversation?** Update `CONTEXT.md` immediately
- **User rejects the candidate with a load-bearing reason?** Offer an ADR, framed as: "Want me to record this as an ADR so future architecture reviews do not re-suggest it?" Only offer this when the reason would help a future explorer avoid re-suggesting the same thing. Skip ephemeral reasons, such as "not worth it right now," and skip self-evident reasons. See [ADR-FORMAT.md](ADR-FORMAT.md)
- **Want to explore alternative interfaces for the deepened module?** See [INTERFACE-DESIGN.md](INTERFACE-DESIGN.md)
