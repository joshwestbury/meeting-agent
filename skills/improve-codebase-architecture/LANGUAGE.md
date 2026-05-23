# Language

Adapted from Matt Pocock's skills repo:
[LANGUAGE.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/improve-codebase-architecture/LANGUAGE.md)

Shared vocabulary for every suggestion this skill makes. Use these terms exactly. Do not substitute "component," "service," "API," or "boundary." Consistent language is the whole point.

## Terms

**Module**

Anything with an interface and an implementation. Deliberately scale-agnostic. This can apply to a function, class, package, or tier-spanning slice.

Avoid: unit, component, service.

**Interface**

Everything a caller must know to use the module correctly. That includes the type signature, but also invariants, ordering constraints, error modes, required configuration, and performance characteristics.

Avoid: API, signature.

**Implementation**

What is inside a module. Distinct from adapter. A thing can be a small adapter with a large implementation, or a large adapter with a small implementation.

**Depth**

Leverage at the interface. A module is deep when a lot of behavior sits behind a small interface. A module is shallow when the interface is nearly as complex as the implementation.

**Seam**

A place where behavior can be altered without editing in that place. More specifically, the location where a module's interface lives.

Avoid: boundary.

**Adapter**

A concrete thing that satisfies an interface at a seam.

**Leverage**

What callers get from depth. More capability per unit of interface they have to learn.

**Locality**

What maintainers get from depth. Change, bugs, knowledge, and verification concentrate in one place instead of spreading across callers.

## Principles

- Depth is a property of the interface, not the implementation
- A module can have internal seams, private to its implementation, as well as the external seam at its interface
- The deletion test: if deleting the module makes complexity vanish, it was likely a pass-through. If complexity reappears across many callers, it was earning its keep
- The interface is the test surface
- One adapter means a hypothetical seam. Two adapters means a real seam

## Relationships

- A module has one interface as its surface to callers and tests
- Depth is a property of a module measured against its interface
- A seam is where a module's interface lives
- An adapter sits at a seam and satisfies the interface
- Depth produces leverage for callers and locality for maintainers

## Rejected framings

- Measuring depth as a ratio of implementation lines to interface lines
- Treating interface as only a language keyword or a list of public methods
- Using boundary instead of seam
