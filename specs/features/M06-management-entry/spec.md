# Explicit local-management launch boundary

### M06MANAGEMENTENTRY-001: No inherited edit permission
The local-management flag defaults off. Pairing, local record existence and
provider-memory transmission consent alone do not enable edits. Requesting
management without configured memory mode fails before opening admission or
storage. A truthy non-boolean argument cannot substitute for explicit consent.

### M06MANAGEMENTENTRY-002: Inert composition
The bootstrap validates explicit local-edit consent and typed server-owned
memory options, but creates no reader/writer/client/process while constructing
the factory. The paired app alone invokes its async open. Failed open closes
the manager and propagates the fixed error. Existing no-memory and read-only
memory routes remain unchanged when the flag is absent.

This is a next-stage candidate tested only with synthetic data. It does not
record automatically, transmit memory, create a missing database, or expand
account permissions. It is separate from the immutable1515 delivery.

### M06MANAGEMENTENTRY-003: Edits and actual Actor recall remain causally bound

Through the paired HTTP API, manual correction or soft-forget committed while
an Actor generation is paused invalidates that old packet before any new grant.
A subsequent input reads the new scoped state. No presentation receipt or
automatic memory row is manufactured. Recall consent without edit consent
keeps management disabled and rejects writes without changing the database.
Tests use real local SQLite/ASGI with synthetic generation/review only.
