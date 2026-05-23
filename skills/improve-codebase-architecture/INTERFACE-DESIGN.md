# Interface Design

Adapted from Matt Pocock's skills repo:
[INTERFACE-DESIGN.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/improve-codebase-architecture/INTERFACE-DESIGN.md)

When the user wants to explore alternative interfaces for a chosen deepening candidate, use a parallel sub-agent pattern. This follows the "Design It Twice" idea from Ousterhout: your first idea is unlikely to be the best.

Use the vocabulary in [LANGUAGE.md](LANGUAGE.md): module, interface, seam, adapter, leverage.

## Process

### 1. Frame the problem space

Before spawning sub-agents, write a user-facing explanation of the problem space for the chosen candidate. Include:

- The constraints any new interface must satisfy
- The dependencies it relies on, and which category they fall into from [DEEPENING.md](DEEPENING.md)
- A rough illustrative code sketch that grounds the constraints without becoming a proposal

Show this to the user, then proceed immediately to the next step. The user can read while the sub-agents work in parallel.

### 2. Spawn sub-agents

Spawn at least three sub-agents in parallel. Each one must produce a radically different interface for the deepened module.

Give each sub-agent a separate technical brief that includes:

- Relevant file paths
- Coupling details
- Dependency category from [DEEPENING.md](DEEPENING.md)
- What sits behind the seam
- Vocabulary from both [LANGUAGE.md](LANGUAGE.md) and `CONTEXT.md`

Use different design constraints for each:

- Agent 1: minimize the interface, aim for one to three entry points, maximize leverage per entry point
- Agent 2: maximize flexibility, support many use cases and extension
- Agent 3: optimize for the most common caller, make the default case trivial
- Agent 4, if applicable: design around ports and adapters for cross-seam dependencies

Each sub-agent should output:

1. Interface, including types, methods, params, invariants, ordering, and error modes
2. Usage example showing how callers use it
3. What the implementation hides behind the seam
4. Dependency strategy and adapters
5. Trade-offs, especially where leverage is high or thin

### 3. Present and compare

Present the designs sequentially so the user can absorb each one, then compare them in prose.

Contrast them by:

- Depth, meaning leverage at the interface
- Locality, meaning where change concentrates
- Seam placement

Then give your own recommendation. If a hybrid is stronger, propose it directly. Be opinionated.
