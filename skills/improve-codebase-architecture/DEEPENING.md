# Deepening

Adapted from Matt Pocock's skills repo:
[DEEPENING.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/improve-codebase-architecture/DEEPENING.md)

How to deepen a cluster of shallow modules safely, given its dependencies. Assumes the vocabulary in [LANGUAGE.md](LANGUAGE.md): module, interface, seam, adapter.

## Dependency categories

When assessing a candidate for deepening, classify its dependencies. The category determines how the deepened module is tested across its seam.

### 1. In-process

Pure computation, in-memory state, no I/O. Always deepenable. Merge the modules and test through the new interface directly. No adapter is needed.

### 2. Local-substitutable

Dependencies that have local test stand-ins, such as PGLite for Postgres or an in-memory filesystem. Deepenable if the stand-in exists. The deepened module is tested with the stand-in running in the test suite. The seam is internal, not part of the module's external interface.

### 3. Remote but owned

Your own services across a network seam, such as microservices or internal APIs. Define a port, meaning an interface, at the seam. The deep module owns the logic while transport is injected as an adapter. Tests use an in-memory adapter. Production uses an HTTP, gRPC, or queue adapter.

Recommendation shape:

"Define a port at the seam, implement an HTTP adapter for production and an in-memory adapter for testing, so the logic sits in one deep module even though it is deployed across a network."

### 4. True external

Third-party services you do not control, such as Stripe or Twilio. The deepened module takes the external dependency as an injected port. Tests provide a mock adapter.

## Seam discipline

- One adapter means a hypothetical seam. Two adapters means a real seam. Do not introduce a port unless at least two adapters are justified, usually production plus test
- Internal seams and external seams are different. A deep module can have internal seams, private to its implementation and used by its own tests, as well as the external seam at its interface. Do not expose internal seams through the interface just because tests use them

## Testing strategy: replace, do not layer

- Old unit tests on shallow modules become waste once tests at the deepened module's interface exist. Delete them
- Write new tests at the deepened module's interface. The interface is the test surface
- Tests should assert on observable outcomes through the interface, not internal state
- Tests should survive internal refactors. If a test must change when the implementation changes, it is testing past the interface
